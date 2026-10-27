from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from aiohttp import web

from .brain import Event, Heard, Loaded, PromptFile, Saved
from .link import GameLink
from .trace import Trace

ASSETS = Path(__file__).parent / "assets"


def create_app(trace: Trace, system: PromptFile, combat: PromptFile, radio: PromptFile, link: GameLink, inputs) -> web.Application:
    app=web.Application()
    async def page(request:web.Request)->web.Response: return web.FileResponse(ASSETS/("history.html" if request.path=="/history" else "site.html"))
    async def get_trace(request:web.Request)->web.Response:
        since=int(request.query.get("since","0")); return web.json_response({"prompt":trace.prompt,"entries":trace.entries[since:],"next":len(trace.entries),"state":link.state,"session":trace.session})
    async def sessions(request:web.Request)->web.Response:
        values=[]
        for p in trace.session_dir.parent.iterdir():
            if p.is_dir() and p.name.isdigit():
                f=p/"trace.jsonl"; values.append({"name":p.name,"bytes":f.stat().st_size if f.exists() else 0})
        values.sort(key=lambda x:x["name"],reverse=True); return web.json_response({"live":trace.session,"sessions":values})
    async def session(request:web.Request)->web.Response:
        name=request.query.get("name","")
        if not name.isdigit(): raise web.HTTPNotFound(text="no such session")
        path=trace.session_dir.parent/name/"trace.jsonl"
        if not path.exists(): raise web.HTTPNotFound(text="no such session")
        return web.json_response([json.loads(x) for x in path.read_text().splitlines() if x])
    async def view(request:web.Request)->web.Response:
        name=request.query.get("name","")
        if not name.isdigit(): raise web.HTTPNotFound()
        path=trace.session_dir/"views"/f"{name}.png"
        if not path.exists():
            path=next(trace.session_dir.parent.glob(f"*/views/{name}.png"),path)
        if not path.exists(): raise web.HTTPNotFound()
        return web.FileResponse(path)
    async def prompt(request:web.Request)->web.Response:
        target={"system":system,"combat":combat,"radio":radio}[request.match_info["name"]]
        if request.method=="POST": target.set(await request.text()); return web.Response()
        return web.Response(text=target.get())
    async def send(request:web.Request)->web.Response:
        body=await request.text(); kind=request.match_info["kind"]
        await inputs.put({"say":Heard(body),"event":Event(body,True),"save":Saved(body),"load":Loaded(body)}[kind]); return web.Response()
    async def state(request:web.Request)->web.Response:
        try: link.state=json.loads(await request.text())
        except ValueError as exc: raise web.HTTPBadRequest(text=str(exc))
        return web.Response()
    app.router.add_get("/",page); app.router.add_get("/history",page); app.router.add_get("/trace",get_trace); app.router.add_get("/sessions",sessions); app.router.add_get("/session",session); app.router.add_get("/view",view)
    app.router.add_route("*","/{name:system|combat|radio}",prompt); app.router.add_post("/{kind:say|event|save|load}",send); app.router.add_post("/state",state)
    return app
