"""Kevin's skills for things lying around: weapons."""

import re

from m8py.skills import Done, Failed, skill


def metres(label):
    found = re.search(r"\((\d+) m\)", label)
    return int(found[1]) if found else 99


@skill(
    when='pick up a weapon lying nearby: "grab that rifle", "get a shotgun", "pick up a weapon"',
    args={"kind": "weapon name, or empty for the nearest"},
    tags=("calm", "combat"),
)
def pick_up_weapon(k, kind=""):
    options = (k.offered("pick_up") or {}).get("options") or {}
    matching = sorted(
        ((ident, label) for ident, label in options.items() if kind.lower() in label.lower()),
        key=lambda item: metres(item[1]),
    )
    if not matching:
        return Failed(f"no {kind or 'weapon'} nearby")
    ident, label = matching[0]
    started = k.time
    while k.time - started < 10:
        k.pick_up(ident)
        if ident not in ((k.offered("pick_up") or {}).get("options") or {}):
            return Done(f"picked up the {label.split(' (')[0]}")
        yield
    return Failed("couldn't reach it")
