"""Kevin's everyday skills: staying with the player, holding, shooting, moving where they point."""

import math

from m8py.skills import Done, Failed, skill


@skill(
    when='stand up and stay with the player; the default with no order: "follow me", "come on", "get up", "stop crouching"',
    tags=("core",),
)
def follow(k):
    k.crouch(False)  # a crouch outlasts the skill that made it (behind_aim, peek): get up first
    yield
    while True:
        k.follow()
        yield


@skill(
    when='stay where you are and guard the spot: "stay here", "wait", "hold this position"',
    tags=("core",),
)
def stay(k):
    k.crouch(False)
    yield
    while True:
        k.stay()
        yield


def in_aim_line(k, point, margin=3):
    """Whether point is within margin metres of the player's line of aim, between them and the aim."""
    player = k.player
    aim = (player.get("aim") or {}).get("pos")
    if not aim or k.distance(player["pos"], aim) < 1:
        aim = k.ahead_of(player["pos"], player.get("facing", 0), 40)
    dx, dy = aim[0] - player["pos"][0], aim[1] - player["pos"][1]
    vx, vy = point[0] - player["pos"][0], point[1] - player["pos"][1]
    length = math.hypot(dx, dy)
    along, across = (vx * dx + vy * dy) / length, (dx * vy - dy * vx) / length
    return 0 < along < length + 3 and abs(across) < margin


@skill(
    when='keep pushing on ahead of the player, off their line of fire: "take point", "lead the way", "keep moving ahead of me"',
    args={"distance": "how far ahead of the player to push on to, metres; 6 just to get in front"},
    tags=("core",),
)
def lead(k, distance=25):
    k.crouch(False)
    yield
    ahead, side = min(distance, 8), None
    while True:
        player, me = k.player, k.me.get("pos")
        if not player.get("pos") or not me:
            yield
            continue
        if k.me.get("health", 1) < 0.25:
            return Failed("low health")
        facing = math.radians(player.get("facing", 0))
        if side is None:  # stay on the side of the player's path he is already on
            across = math.cos(facing) * (me[1] - player["pos"][1]) - math.sin(facing) * (me[0] - player["pos"][0])
            side = "left" if across > 0 else "right"
        on_path = k.ahead_of(player["pos"], player.get("facing", 0), ahead)
        other = "right" if side == "left" else "left"
        spot, swap = (k.side_point(on_path, player["pos"], s, 4) for s in (side, other))
        if in_aim_line(k, spot) and not in_aim_line(k, swap):  # never in front of the player's gun
            side, spot = other, swap
        if k.distance(me, spot) < 2 and ahead < distance:  # there: walk on, don't wait for the player
            ahead = min(distance, ahead + 6)
            continue
        k.go(spot)
        if k.stuck(4):
            if ahead <= 6:
                return Failed("can't get ahead of the player: blocked")
            ahead, side = max(6, ahead - 6), ("right" if side == "left" else "left")
        yield


@skill(
    when='stop shooting until told otherwise: "hold your fire", "stop shooting", "cease fire"',
    tags=("core",),
)
def hold_fire(k):
    k.hold_fire()
    yield
    return Done("holding fire")


def in_front_of_player(k):
    """The enemy closest to the player's line of aim (within 45 degrees), in sight first."""
    player = k.player
    if not player.get("pos"):
        return None
    aim = (player.get("aim") or {}).get("pos")
    if aim and k.distance(player["pos"], aim) > 1:
        ahead = math.atan2(aim[1] - player["pos"][1], aim[0] - player["pos"][0])
    else:
        ahead = math.radians(player.get("facing", 0))
    best = None
    for enemy in k.enemies:
        dx, dy = enemy["pos"][0] - player["pos"][0], enemy["pos"][1] - player["pos"][1]
        off = abs((math.atan2(dy, dx) - ahead + math.pi) % (2 * math.pi) - math.pi)
        if off <= math.pi / 4:
            score = (not enemy.get("in_sight"), off > math.pi / 12, math.hypot(dx, dy))
            if best is None or score < best[0]:
                best = (score, enemy)
    return best and best[1]


@skill(
    when='shoot one enemy (never scenery) until it is dead or gone: "kill him", "shoot him", "the one in front of me"',
    args={"target": "kind#id; 'aim' for the one in front of the player; empty for the nearest in sight"},
    tags=("core",),
)
def attack(k, target=""):
    if target in ("aim", "") and not k.enemies:  # the game only fires at enemies, never at a spot
        return Failed("no enemies here: I can only shoot at enemies, not at things")
    if target == "aim":
        enemy = in_front_of_player(k) or k.nearest_enemy(in_sight=True)
        if enemy is None:
            return Failed("no enemy in front of you: I can only shoot at enemies, not at things")
        target = f"{enemy['kind']}#{enemy['id']}"
    if not target:
        nearest = k.nearest_enemy(in_sight=True)
        if nearest is None:
            return Failed("no enemy to attack")
        target = f"{nearest['kind']}#{nearest['id']}"
    if not k.alive(target):
        return Failed("no such enemy")
    started = k.time
    while k.alive(target):
        if k.me.get("health", 1) < 0.25:
            return Failed("low health")
        if k.me.get("shields", 1) < 0.4:  # unshielded, an elite kills him in a second
            return Failed("shields down")
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
    while k.me.get("activity") != "cover":
        if k.time - started > 8:
            return Failed("found no cover in 8 s")
        k.cover()
        yield
    held = k.time
    while k.me.get("shields", 1) < 0.9 and k.time - held < 10:  # let the shields recharge
        k.cover()
        yield
    return Done("in cover")


@skill(
    when='go to where the player aims, or that way if it is far: "go there", "move up there", "check that out", "run to that waterfall"',
    tags=("core",),
)
def go_to_aim(k):
    player = k.player
    aim = (player.get("aim") or {}).get("pos")
    if not aim and not player.get("pos"):
        return Failed("can't see where you are")
    k.crouch(False)
    yield
    if aim:  # a surface, a wall or a rock face: stop short of it on the player's side
        spots = [(k.behind(aim, player["pos"], -short), "there") for short in (1.5, 3.0)]
    else:  # aiming past the game's aim range (a far waterfall, the sky): head the way they face
        spots = [(k.ahead_of(player["pos"], player.get("facing", 0), m), f"went {m} m that way") for m in (30, 15)]
    start = k.me.get("pos")
    for spot, reached in spots:
        while k.distance(k.me.get("pos"), spot) > 1.5:
            if k.me.get("health", 1) < 0.25:  # a far aim (a waterfall 120 m off) can walk into patrols
                return Failed("low health")
            k.go(spot)
            if k.stuck(4):
                break
            yield
        else:
            return Done(reached)
    if aim and k.distance(k.me.get("pos"), aim) <= 5:
        return Done("as close as I can get")
    if not aim and k.distance(k.me.get("pos"), start) >= 10:
        return Done("went that way until the path was blocked")
    return Failed("path blocked")


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
