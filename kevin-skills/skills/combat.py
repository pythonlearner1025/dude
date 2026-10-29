"""Kevin's fighting skills: flanking, rushing, clearing an area, covering the player."""

import math

from m8py.skills import Done, Failed, skill


@skill(
    when='go around an enemy and hit it from one side: "flank right", "go around", "hit them from the left"',
    args={"target": "kind#id, or empty for the nearest in sight", "side": "left or right, as the player sees it"},
    tags=("combat",),
)
def flank(k, target="", side="right"):
    if not target:
        nearest = k.nearest_enemy(in_sight=True)
        if nearest is None:
            return Failed("no enemy to flank")
        target = f"{nearest['kind']}#{nearest['id']}"
    started = k.time
    for metres in (12, 7):  # wide first, then tighter if that side is blocked
        while k.alive(target):
            if k.time - started > 25:
                return Failed("flank took too long")
            if k.me.get("health", 1) < 0.25:
                return Failed("low health")
            enemy = k.enemy(target)
            if abs(enemy["pos"][2] - k.me.get("pos", enemy["pos"])[2]) > 4:
                return Failed("can't reach it: it's above or below me")
            spot = k.side_point(enemy["pos"], k.player["pos"], side, metres)
            if k.distance(k.me.get("pos"), spot) <= 2:
                return (yield from k.run("attack", target=target))
            k.go(spot)
            if k.stuck(3):
                break
            yield
        else:
            return Done("target down")
    return Failed(f"no way around to the {side}")


@skill(
    when='charge an enemy and fight up close: "rush him", "push up on him", "get in his face"',
    args={"target": "kind#id"},
    tags=("combat",),
)
def rush(k, target):
    if not k.alive(target):
        return Failed("no such enemy")
    started = k.time
    while k.alive(target):
        if k.time - started > 20:
            return Failed("still alive after 20 s")
        if k.me.get("health", 1) < 0.25:
            return Failed("low health")
        if k.me.get("shields", 1) < 0.4:
            return Failed("shields down")
        k.rush(target)
        yield
    return Done("target down")


@skill(
    when='pull back toward the player, away from the enemies: "fall back", "retreat", "get back here"',
    tags=("combat",),
)
def fall_back(k):
    started = k.time
    while k.time - started < 5:
        k.fall_back()
        yield
    return Done("fell back")


@skill(
    when='throw a grenade at an enemy or a group: "grenade them", "frag him", "nade that group"',
    args={"target": "kind#id"},
    tags=("combat",),
)
def grenade(k, target):
    if not k.alive(target):
        return Failed("no such enemy")
    k.grenade(target)
    yield
    yield
    return Done("grenade thrown")


@skill(
    when='melee an enemy within a few metres: "punch him", "melee him", "hit him"',
    args={"target": "kind#id"},
    tags=("combat",),
)
def melee(k, target):
    enemy = k.enemy(target)
    if not enemy:
        return Failed("no such enemy")
    if enemy.get("distance_m", 99) > 4:
        return Failed("too far for melee")
    k.melee(target)
    yield
    return Done("hit")


@skill(
    when='kill every enemy in sight, nearest first: "clear the area", "clear the room", "take them all out"',
    tags=("combat",),
)
def clear_area(k):
    started = k.time
    while k.time - started < 120:
        enemy = k.nearest_enemy(in_sight=True)
        if enemy is None:
            return Done("area clear")
        result = yield from k.run("attack", target=f"{enemy['kind']}#{enemy['id']}")
        if isinstance(result, Failed) and result.reason in ("low health", "shields down"):
            return result
        yield
    return Failed("still enemies after 2 minutes")


def in_line_of_fire(k):
    """The side ("left"/"right") to step out to if Kevin stands within 2 m of the player's line of
    aim, between them and what they aim at; None if he is clear."""
    player, me = k.player, k.me.get("pos")
    if not player.get("pos") or not me:
        return None
    aim = (player.get("aim") or {}).get("pos")
    if aim and k.distance(player["pos"], aim) > 1:
        dx, dy, reach = aim[0] - player["pos"][0], aim[1] - player["pos"][1], k.distance(player["pos"], aim)
    else:
        rad = math.radians(player.get("facing", 0))
        dx, dy, reach = math.cos(rad), math.sin(rad), 40
    length = math.hypot(dx, dy)
    vx, vy = me[0] - player["pos"][0], me[1] - player["pos"][1]
    along, across = (vx * dx + vy * dy) / length, (dx * vy - dy * vx) / length
    if not (0 < along < reach and abs(across) < 2):
        return None
    return "left" if across > 0 else "right"  # away from the line, the short way


@skill(
    when='stay by the player and shoot whatever threatens them, out of their line of fire: "cover me", "watch my back", "you\'re in my way"',
    tags=("combat",),
)
def cover_player(k):
    k.crouch(False)
    yield
    while True:
        enemy = k.nearest_enemy(in_sight=True)
        side = in_line_of_fire(k)
        if side:  # Chief fires through him otherwise: step 3 m out of the line first
            k.go(k.side_point(k.me["pos"], k.player["pos"], side, 3))
        elif enemy and enemy.get("distance_m", 99) < 35:
            k.shoot(enemy["id"])
        else:
            k.follow()
        yield


def duck_back(k, cover):
    """Back into cover, crouched, until the shields are up again."""
    back = k.time
    while k.distance(k.me.get("pos"), cover) > 1.5 and k.time - back < 5:
        k.go(cover)
        if k.stuck(3):
            break
        yield
    while k.time - back < 2 or (k.me.get("shields", 1) < 0.9 and k.time - back < 12):
        k.crouch()
        yield


def look_out(k, cover):
    """No enemies: step out beside the cover toward the player's aim, look a few seconds, come back."""
    aim = (k.player.get("aim") or {}).get("pos")
    if not aim or k.distance(cover, aim) < 3:
        aim = k.ahead_of(k.player.get("pos") or cover, k.player.get("facing", 0), 15)
    k.crouch(False)
    out = k.time
    while k.time - out < 4:
        k.go(k.side_point(cover, aim, "left", 3))
        if k.stuck(2):
            break
        yield
    yield from duck_back(k, cover)
    # the game can only fire at enemies: there is no shooting at scenery
    return Done("peeked out: no enemies in sight, and I can only shoot at enemies")


@skill(
    when='from cover, step out and shoot, duck back in: "peek out", "stop hiding"; no enemies: looks where you aim ("shoot at that rock")',
    args={"target": "kind#id, or empty for the nearest"},
    tags=("calm", "combat"),
)
def peek(k, target=""):
    cover, side = k.me.get("pos"), "left"
    started, peeks = k.time, 0
    while k.time - started < 45:
        if k.me.get("health", 1) < 0.25:
            return Failed("low health")
        enemy = k.enemy(target) if target else k.nearest_enemy(True) or k.nearest_enemy(False)
        far = enemy and not enemy.get("in_sight") and enemy.get("distance_m", 0) > 60
        if (enemy is None or far) and not peeks and not target:  # nothing near to peek at
            return (yield from look_out(k, cover))
        if enemy is None:
            return Done("target down" if target else "no enemies left") if peeks else Failed("no such enemy")
        # out: stand; shoot if one is in sight, else step beside the cover until one is
        k.crouch(False)
        out, fired = k.time, 0
        while k.time - out < 6 and fired < 8 and k.me.get("shields", 1) >= 0.4:
            seen = k.enemy(target) if target else k.nearest_enemy(in_sight=True)
            if target and seen is None:
                break
            if seen and seen.get("in_sight"):
                k.shoot(seen["id"])
                fired += 1
            else:
                k.go(k.side_point(cover, enemy["pos"], side, 3))
                if k.stuck(2):
                    break
            yield
        if not fired:  # that side is blocked or shows nothing: try the other next time
            side = "right" if side == "left" else "left"
        peeks += 1
        yield from duck_back(k, cover)
    return Done(f"peeked out {peeks} times; enemies still there")


@skill(
    when='press forward and drive enemies back:"push them back", "push them off the ridge", "press the attack"',
    args={"target": "kind#id, or empty for the nearest in sight"},
    tags=("combat",),
)
def push(k, target=""):
    started = k.time
    while k.time - started < 60:
        enemy = k.enemy(target) if target else k.nearest_enemy(in_sight=True)
        if enemy is None:
            return Done("pushed them back" if k.time > started else "no enemies to push")
        result = yield from k.run("rush", target=f"{enemy['kind']}#{enemy['id']}")
        if target or (isinstance(result, Failed) and result.reason in ("low health", "shields down")):
            return result
        yield
    return Failed("still enemies after a minute")
