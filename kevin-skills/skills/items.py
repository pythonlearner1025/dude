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


def weapons(k):
    """(held, on his back) from the game's summary: "holding a pistol (...), an assault rifle on his back"."""
    text = k.state.get("state") or ""
    held = re.search(r"holding an? ([a-z ]+?)(?: \(|,|\.|$)", text)
    back = re.search(r"an? ([a-z ]+?) on his back", text)
    return (held[1] if held else ""), (back[1] if back else "")


@skill(
    when='swap to the weapon on his back: "switch weapons", "use your other gun", "pull out your pistol"',
    args={"kind": "the weapon wanted, or empty for the other one"},
    tags=("calm", "combat"),
)
def switch_weapon(k, kind=""):
    held, back = weapons(k)
    if kind and held and kind.lower() in held:
        return Done(f"already holding the {held}")
    if not back or not k.offered("switch_weapon"):
        return Failed("no other weapon")
    if kind and kind.lower() not in back:
        return Failed(f"no {kind}; my other weapon is the {back}")
    started = k.time
    while k.time - started < 5:
        if weapons(k) == (back, held):
            return Done(f"holding the {back}")
        k.switch_weapon()
        yield
    return Failed("couldn't switch")
