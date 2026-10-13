"""Rebuild, from a replay's events alone, the round block each dragon was sent.

Server replays cannot be re-simulated (the judge's pearl spawns do not follow
the local engine for the same seed), but they record every action, body change,
split, death, pearl and sonar. Folding those events in order gives the board as
each dragon saw it at the start of its turn. Pearl countdowns are only known
when the replay carries pearlCountdown events (local replays); otherwise
spawnable tiles report UNKNOWN_PEARL_TIME.

`track(replay)` yields Turn records; `Turn.block()` renders the protocol text.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .common import CAPNP_DIR, DIRS, OFFSET, OPPOSITE, GameMap, load_replay

UNIT_LIMIT = 64
VISION_RADIUS = 3
UNKNOWN_PEARL_TIME = -2
ECHO_INDEX = {"kelp": 0, "ally": 1, "allyHead": 2, "enemy": 3, "enemyHead": 4}


class TrackError(RuntimeError):
    pass


@dataclass
class Dragon:
    id: int
    team: str
    body: list                       # [[x, y, facing], ...] head first
    inbox: list = field(default_factory=list)
    echoes: list = field(default_factory=lambda: [0, 0, 0, 0, 0])
    protocol3: bool = False          # ECHOES appear once a reply has said PROTOCOL 3
    turns: int = 0


@dataclass
class Turn:
    round: int
    id: int
    team: str
    first: bool                      # first turn of a process: an init block precedes it
    header: dict
    tiles: list                      # 49 (x, y, has_pearl, pearl_time)
    bodies: list                     # (team, id, x, y, facing, is_head)
    hedges: list                     # 8 rows of 7 symbols
    vedges: list                     # 7 rows of 8 symbols
    action: tuple | None = None      # ("move", "NNE") | ("split", n) | ("none",) | ("tle",)
    width: int = 0
    height: int = 0

    def init_block(self) -> str:
        return (f"ID {self.id}\nTEAM {self.team}\nMAP {self.width} {self.height}\n"
                f"UNIT_LIMIT {UNIT_LIMIT}\n")

    def block(self, echoes: bool = True) -> str:
        h = self.header
        out = [f"ROUND {self.round}", f"DIR {h['dir']}", f"LENGTH {h['length']}",
               f"UNIT_COUNT {h['units']}", f"NUM_MSGS {len(h['msgs'])}"]
        out += [str(v) for v in h["msgs"]]
        if echoes and h["echoes"] is not None:
            out.append("ECHOES " + " ".join(map(str, h["echoes"])))
        out += [f"{x} {y} {p} {t}" for x, y, p, t in self.tiles]
        out.append(f"DRAGON_BODIES {len(self.bodies)}")
        out += [f"{t} {i} {x} {y} {f} {hd}" for t, i, x, y, f, hd in self.bodies]
        out += [" ".join(r) for r in self.hedges]
        out += [" ".join(r) for r in self.vedges]
        return "\n".join(out) + "\n"


def _dir_between(a, b, w, h):
    """Direction of the step from a to b on the torus, None if not adjacent."""
    for d, (dx, dy) in OFFSET.items():
        if ((a[0] + dx) % w, (a[1] + dy) % h) == (b[0], b[1]):
            return d
    return None


class Tracker:
    def __init__(self, replay, strict: bool = True) -> None:
        self.replay = replay
        self.map = GameMap.parse(replay.map)
        self.w, self.h = self.map.width, self.map.height
        self.strict = strict
        self.round = -1
        self.pearls: set = set()
        self.countdown: dict = {}           # (x, y) -> (value, round it was set)
        self.dragons: dict[int, Dragon] = {}
        self.mismatches = 0
        self.portal_surprises = 0           # steps our edge model got wrong (should stay 0)
        for i, (team, cells) in enumerate(self.map.dragons):
            body = []
            for k, (x, y) in enumerate(cells):
                if k == 0:
                    f = _dir_between(cells[1], cells[0], self.w, self.h) if len(cells) > 1 else "N"
                else:
                    f = _dir_between(cells[k], cells[k - 1], self.w, self.h)
                body.append([x, y, f or "N"])
            self.dragons[i] = Dragon(i, team, body)

    # ---- observation ------------------------------------------------------
    def pearl_time(self, x: int, y: int) -> int:
        lo, hi = self.map.gaps.get((x, y), (0, 0))
        if hi == 0:
            return -1
        known = self.countdown.get((x, y))
        if known is None:
            return UNKNOWN_PEARL_TIME
        value, at = known
        return value - (self.round - at)

    def observe(self, d: Dragon) -> Turn:
        w, h = self.w, self.h
        hx, hy = d.body[0][0], d.body[0][1]
        xs = [(hx + k) % w for k in range(-VISION_RADIUS, VISION_RADIUS + 1)]
        ys = [(hy + k) % h for k in range(-VISION_RADIUS, VISION_RADIUS + 1)]
        window = {(x, y) for y in ys for x in xs}
        tiles = [(x, y, int((x, y) in self.pearls), self.pearl_time(x, y)) for y in ys for x in xs]
        bodies = []
        for other in sorted(self.dragons.values(), key=lambda o: o.id):
            for k, (x, y, f) in enumerate(other.body):
                if (x, y) in window:
                    bodies.append((other.team, other.id, x, y, f, int(k == 0)))
        hedges = [[self.map.hedge[(hy - VISION_RADIUS + r) % h][x].symbol() for x in xs]
                  for r in range(2 * VISION_RADIUS + 2)]
        vxs = xs + [(xs[-1] + 1) % w]
        vedges = [[self.map.vedge[y][x].symbol() for x in vxs] for y in ys]
        units = sum(1 for o in self.dragons.values() if o.team == d.team)
        header = {"dir": d.body[0][2], "length": len(d.body), "units": units,
                  "msgs": list(d.inbox), "echoes": list(d.echoes) if d.protocol3 else None}
        return Turn(self.round, d.id, d.team, d.turns == 0, header, tiles, bodies, hedges, vedges,
                    width=w, height=h)

    # ---- event folding ----------------------------------------------------
    def _fail(self, message: str) -> None:
        self.mismatches += 1
        if self.strict:
            raise TrackError(f"round {self.round}: {message}")

    def _update(self, d: Dragon, facing: str, head: tuple, tail: tuple) -> None:
        """One dragonUpdate per step taken: the head advances to `head` (through
        any portal), the body follows, and the tail is trimmed to `tail`."""
        if (d.body[0][0], d.body[0][1]) != head:
            expect = self.map.step(d.body[0][0], d.body[0][1], facing)
            if expect != head:
                self.portal_surprises += 1
            d.body[0][2] = facing
            d.body.insert(0, [head[0], head[1], facing])
        d.body[0][2] = facing
        while len(d.body) > 1 and (d.body[-1][0], d.body[-1][1]) != tail:
            d.body.pop()
        if (d.body[-1][0], d.body[-1][1]) != tail:
            self._fail(f"dragon {d.id} tail {tail} is not on its body")
            d.body.append([tail[0], tail[1], facing])

    def _split(self, ev) -> None:
        parent = self.dragons[ev.parentId]
        facing = {(x, y): f for x, y, f in parent.body}
        pbody = [(p.x, p.y) for p in ev.parentBody]
        cbody = [(p.x, p.y) for p in ev.childBody]
        parent.body = [[x, y, facing.get((x, y), "N")] for x, y in pbody]
        child = []
        for k, (x, y) in enumerate(cbody):
            if k == 0:
                f = CAPNP_DIR[str(ev.childFacing)]
            else:
                f = OPPOSITE[facing.get(cbody[k - 1], "N")]
            child.append([x, y, f])
        team = "A" if str(ev.team) == "a" else "B"
        self.dragons[ev.childId] = Dragon(ev.childId, team, child, protocol3=parent.protocol3)

    def run(self):
        """Yield (Turn, None) at each turn start, then fill Turn.action as it is read."""
        pending: Turn | None = None
        actor: Dragon | None = None
        for e in self.replay.events:
            kind = e.which()
            if kind == "roundStart":
                self.round = e.roundStart.round
            elif kind == "pearlCountdown":
                c = e.pearlCountdown
                self.countdown[(c.tile.x, c.tile.y)] = (c.countdown, self.round)
            elif kind == "tileChange":
                t = e.tileChange
                (self.pearls.add if t.hasPearl else self.pearls.discard)((t.tile.x, t.tile.y))
            elif kind == "turnStart":
                if pending is not None:
                    yield pending
                actor = self.dragons.get(e.turnStart.id)
                if actor is None:
                    self._fail(f"turn for unknown dragon {e.turnStart.id}")
                    pending = None
                    continue
                pending = self.observe(actor)
                actor.inbox.clear()
                actor.echoes = [0, 0, 0, 0, 0]
                actor.turns += 1
                actor.protocol3 = True       # every current helper replies with PROTOCOL 3
            elif kind == "dragonAction":
                a = e.dragonAction
                d = self.dragons.get(a.id)
                if a.tle:
                    act = ("tle",)
                    if d is not None:
                        d.turns = 0          # the judge restarts the process
                else:
                    which = a.action.which()
                    if which == "move":
                        act = ("move", "".join(CAPNP_DIR[str(s)] for s in a.action.move))
                    elif which == "split":
                        act = ("split", a.action.split)
                    else:
                        act = ("none",)
                if pending is not None and pending.id == a.id:
                    pending.action = act
            elif kind == "dragonUpdate":
                u = e.dragonUpdate
                d = self.dragons.get(u.id)
                if d is not None:
                    self._update(d, CAPNP_DIR[str(u.facing)], (u.head.x, u.head.y), (u.tail.x, u.tail.y))
            elif kind == "dragonSplit":
                self._split(e.dragonSplit)
            elif kind == "dragonDeath":
                self.dragons.pop(e.dragonDeath.id, None)
            elif kind == "sonarPing":
                p = e.sonarPing
                sender = self.dragons.get(p.senderId)
                value = p.value64 if p.value64 else p.value
                if p.which() == "hitId":
                    target = self.dragons.get(p.hitId)
                    if target is not None:
                        target.inbox.append(value)
                if sender is not None:
                    slot = ECHO_INDEX.get(str(p.hitKind))
                    if slot is not None:
                        sender.echoes[slot] += 1
        if pending is not None:
            yield pending


def track(source, strict: bool = True):
    replay = source if hasattr(source, "events") else load_replay(source)
    return Tracker(replay, strict)
