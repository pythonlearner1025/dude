"""Kevin's fighting skills: flanking, rushing, clearing an area, covering the player."""

from m8py.skills import Done, Failed, skill


@skill(
    when='go around an enemy and hit it from one side: "flank right", "go around", "hit them from the left"',
    args={"target": "kind#id", "side": "left or right, as the player sees it"},
    tags=("combat",),
)
def flank(k, target, side="right"):
    started = k.time
    for metres in (12, 7):  # wide first, then tighter if that side is blocked
        while k.alive(target):
            if k.time - started > 25:
                return Failed("flank took too long")
            if k.me.get("health", 1) < 0.25:
                return Failed("low health")
            spot = k.side_point(k.enemy(target)["pos"], k.player["pos"], side, metres)
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
        if isinstance(result, Failed) and result.reason == "low health":
            return result
        yield
    return Failed("still enemies after 2 minutes")


@skill(
    when='stay by the player and shoot whatever threatens them: "cover me", "watch my back"',
    tags=("combat",),
)
def cover_player(k):
    while True:
        enemy = k.nearest_enemy(in_sight=True)
        if enemy and enemy.get("distance_m", 99) < 35:
            k.shoot(enemy["id"])
        else:
            k.follow()
        yield
