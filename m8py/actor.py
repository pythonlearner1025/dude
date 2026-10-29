"""The actor: a fast hosted model (DeepSeek V4.1 Flash through OpenRouter, reasoning off) that
picks Kevin's next skill as one line, from the library's catalog and a short state digest."""

from __future__ import annotations

import inspect
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import ActorConfig
from .skills import Library

CALL = re.compile(r"^(\w+)\s*\((.*)\)\s*$")


@dataclass(slots=True)
class Decision:
    kind: str  # start, keep, nofit or invalid
    skill: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    order: str | None = None
    error: str | None = None


def value(token: str) -> Any:
    try:
        return int(token)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        return token


def parse(text: str, library: Library) -> Decision:
    """One answer line: `<skill> <args>`, `keep`, or `nofit <order> | <skill> <args>`. Lenient:
    takes the first non-empty line, drops quotes and backticks, accepts name(arg, arg) and k=v."""
    line = next((x for x in text.strip().splitlines() if x.strip()), "")
    line = line.strip().strip("`'\"").rstrip(".").strip()
    if line.lower().startswith("keep"):
        return Decision("keep")
    order = None
    if line.lower().startswith("nofit"):
        order, _, line = line[5:].partition("|")
        order, line = order.strip(" :"), line.strip()
        if not line:
            return Decision("nofit", order=order)
    if match := CALL.match(line):
        name, rest = match[1], [x.strip() for x in match[2].split(",") if x.strip()]
    else:
        name, *rest = line.split() or [""]
    name = name.lower()
    found = library.skills.get(name)
    if not found:
        return Decision("invalid", order=order, error=f'"{line}" names no skill')
    params = list(inspect.signature(found.fn).parameters)[1:]
    args: dict[str, Any] = {}
    for position, token in enumerate(rest):
        key, eq, raw = token.partition("=")
        if eq:
            args[key.strip()] = value(raw.strip().strip("'\""))
        elif position < len(params):
            args[params[position]] = value(token.strip("'\""))
    return Decision("nofit" if order is not None else "start", name, args, order)


class Actor:
    def __init__(self, cfg: ActorConfig, client: httpx.AsyncClient) -> None:
        self.cfg, self.client = cfg, client
        self.headers = {"Authorization": f"Bearer {os.environ.get(cfg.key_env, '')}"}

    async def ask(self, system: str, user: str) -> tuple[str, int, dict[str, Any]]:
        """The answer line, milliseconds, and token usage (incl. cached prompt tokens)."""
        body: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2,
            "max_tokens": 40,
            "reasoning": {"enabled": False},
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if self.cfg.provider:
            body["provider"] = {"only": [self.cfg.provider], "allow_fallbacks": False}
        started = time.monotonic()
        text, usage = "", {}
        async with self.client.stream(
            "POST", self.cfg.url, json=body, headers=self.headers, timeout=self.cfg.timeout
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: ") or line[6:].strip() == "[DONE]":
                    continue
                chunk = json.loads(line[6:])
                usage = chunk.get("usage") or usage
                choices = chunk.get("choices") or []
                if choices:
                    text += choices[0].get("delta", {}).get("content") or ""
                    if "\n" in text.strip():  # one line is the whole answer
                        break
        return text.strip(), round((time.monotonic() - started) * 1000), usage
