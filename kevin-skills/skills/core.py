"""Kevin's everyday skills: staying with the player, holding, shooting, moving where they point."""

from m8py.skills import Done, Failed, skill


@skill(
    when='stay with the player; the default with no order: "follow me", "come on", "with me"',
    tags=("core",),
)
def follow(k):
    while True:
        k.follow()
        yield


@skill(
    when='stay where you are and guard the spot: "stay here", "wait", "hold this position"',
    tags=("core",),
)
def stay(k):
    while True:
        k.stay()
        yield


@skill(
    when='move ahead of the player, where they face: "get in front of me", "take point", "lead"',
    args={"distance": "metres ahead of the player"},
    tags=("core",),
)
def lead(k, distance=6):
    while True:
        player = k.player
        if player.get("pos"):
            k.go(k.ahead_of(player["pos"], player.get("facing", 0), distance))
            if k.stuck(4):
                return Failed("can't get ahead of the player: blocked")
        yield


@skill(
    when='stop shooting until told otherwise: "hold your fire", "stop shooting", "cease fire"',
    tags=("core",),
)
def hold_fire(k):
    k.hold_fire()
    yield
    return Done("holding fire")


@skill(
    when='shoot one enemy until it is dead or gone: "kill him", "shoot that", "take out the elite"',
    args={"target": "kind#id"},
    tags=("core",),
)
def attack(k, target):
    if not k.alive(target):
        return Failed("no such enemy")
    started = k.time
    while k.alive(target):
        if k.me.get("health", 1) < 0.25:
            return Failed("low health")
        if k.time - started > 30:
            return Failed("still alive after 30 s")
        k.shoot(target)
        yield
    return Done("target down")


@skill(
    when='take cover from the enemies and crouch: "take cover", "get down", "find cover"',
    tags=("core",),
)
def take_cover(k):
    started = k.time
    while k.time - started < 8:
        k.cover()
        if k.me.get("activity") == "cover":
            return Done("in cover")
        yield
    return Failed("found no cover in 8 s")


@skill(
    when='go to where the player is aiming: "go there", "move up there", "check that out"',
    tags=("core",),
)
def go_to_aim(k):
    aim = (k.player.get("aim") or {}).get("pos")
    if not aim:
        return Failed("the player isn't aiming at anything")
    spot = list(aim)
    while k.distance(k.me.get("pos"), spot) > 1.5:
        k.go(spot)
        if k.stuck(4):
            return Failed("path blocked")
        yield
    return Done("there")


@skill(
    when='get behind what the player aims at, away from enemies: "get behind that rock", "use that cover"',
    args={"metres": "how far past the thing aimed at"},
    tags=("core",),
)
def behind_aim(k, metres=3.0):
    aim = k.player.get("aim") or {}
    if not aim.get("pos"):
        return Failed("the player isn't aiming at anything")
    threat = k.nearest_enemy(in_sight=False)
    away = threat["pos"] if threat else k.player["pos"]
    spot = k.behind(aim["pos"], away, metres)
    while k.distance(k.me.get("pos"), spot) > 1.5:
        k.go(spot)
        if k.stuck(4):
            return Failed("can't get behind it: path blocked")
        yield
    k.crouch()
    yield
    return Done(f"behind the {aim.get('label', 'cover')}")
