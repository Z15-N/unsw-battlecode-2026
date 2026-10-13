"""Random symmetric maps, standing in for the qualifier's unseen maps.

    python -m lab.mapgen --count 20 --seed 1        -> data/maps_gen/gen_<seed>_<i>.map

Maps follow docs/map-files.md: 10-64 per side, mirror x / mirror y / rotation
symmetry, kelp and portal edges, per-tile pearl gaps, alternating team spawns
(dragon 0 and 1 are the queens). Kelp is placed in mirrored pairs and rejected
if it disconnects the spawns or walls off too much of the board.
"""

from __future__ import annotations

import argparse
import pathlib
import random
import sys

from .common import DATA

OUT = DATA / "maps_gen"


class Gen:
    def __init__(self, rng: random.Random, w: int, h: int, sym: str) -> None:
        self.rng, self.w, self.h, self.sym = rng, w, h, sym
        self.hedge = {}     # (x, y) north edge of tile -> (kind, pid)
        self.vedge = {}     # (x, y) west edge of tile
        self.gaps = {}
        self.next_pid = 0
        self.protected = set()      # ("h"|"v", x, y) edges that must stay open (inside spawn bodies)

    # ---- symmetry ---------------------------------------------------------
    def mirror(self, x: int, y: int) -> tuple[int, int]:
        w, h = self.w, self.h
        if self.sym == "y":
            return w - 1 - x, y
        if self.sym == "x":
            return x, h - 1 - y
        return w - 1 - x, h - 1 - y

    def mirror_h(self, x: int, y: int) -> tuple[int, int]:
        """North edge of (x, y) -> the north edge it mirrors to."""
        w, h = self.w, self.h
        if self.sym == "y":
            return w - 1 - x, y
        if self.sym == "x":
            return x, (h - y) % h
        return w - 1 - x, (h - y) % h

    def mirror_v(self, x: int, y: int) -> tuple[int, int]:
        """West edge of (x, y) -> the west edge it mirrors to."""
        w, h = self.w, self.h
        if self.sym == "y":
            return (w - x) % w, y
        if self.sym == "x":
            return x, h - 1 - y
        return (w - x) % w, h - 1 - y

    # ---- connectivity -----------------------------------------------------
    def passable(self, x: int, y: int, d: str) -> bool:
        w, h = self.w, self.h
        if d == "N":
            e = self.hedge.get((x, y))
        elif d == "S":
            e = self.hedge.get((x, (y + 1) % h))
        elif d == "W":
            e = self.vedge.get((x, y))
        else:
            e = self.vedge.get(((x + 1) % w, y))
        return not (e and e[0] == 1)

    def reachable(self, start: tuple[int, int]) -> set:
        w, h = self.w, self.h
        seen = {start}
        stack = [start]
        while stack:
            x, y = stack.pop()
            for d, (dx, dy) in (("N", (0, -1)), ("E", (1, 0)), ("S", (0, 1)), ("W", (-1, 0))):
                if not self.passable(x, y, d):
                    continue
                nb = ((x + dx) % w, (y + dy) % h)
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        return seen

    # ---- features ---------------------------------------------------------
    def kelp_wall(self) -> list:
        """A straight or L-shaped run of kelp edges, as (orient, x, y) cells."""
        rng = self.rng
        x, y = rng.randrange(self.w), rng.randrange(self.h)
        length = rng.randint(2, max(3, min(self.w, self.h) // 2))
        horizontal = rng.random() < 0.5
        out = []
        for i in range(length):
            if horizontal:
                out.append(("h", (x + i) % self.w, y))
            else:
                out.append(("v", x, (y + i) % self.h))
        if rng.random() < 0.35:           # an elbow
            ex, ey = out[-1][1], out[-1][2]
            for i in range(rng.randint(2, length)):
                out.append(("v", ex, (ey + i) % self.h) if horizontal else ("h", (ex + i) % self.w, ey))
        return out

    def place_kelp(self, walls: int, spawns: list) -> None:
        target = set(spawns)
        for _ in range(walls):
            wall = self.kelp_wall()
            added = []
            for orient, x, y in wall:
                table = self.hedge if orient == "h" else self.vedge
                mx, my = (self.mirror_h if orient == "h" else self.mirror_v)(x, y)
                if (orient, x, y) in self.protected or (orient, mx, my) in self.protected:
                    continue
                for key in ((x, y), (mx, my)):
                    if key not in table:
                        table[key] = (1, -1)
                        added.append((table, key))
            comp = self.reachable(spawns[0])
            if not target <= comp or len(comp) < 0.7 * self.w * self.h:
                for table, key in added:
                    del table[key]

    def place_portals(self, pairs: int) -> None:
        rng = self.rng
        for _ in range(pairs):
            orient = rng.choice("hv")
            table = self.hedge if orient == "h" else self.vedge
            mfun = self.mirror_h if orient == "h" else self.mirror_v
            for _try in range(30):
                a = (rng.randrange(self.w), rng.randrange(self.h))
                b = (rng.randrange(self.w), rng.randrange(self.h))
                ma, mb = mfun(*a), mfun(*b)
                cells = {a, b, ma, mb}
                on_axis_a, on_axis_b = ma == a, mb == b
                if len({a, b}) < 2 or any(c in table for c in cells) or on_axis_a != on_axis_b:
                    continue
                if any((orient, cx, cy) in self.protected for cx, cy in cells):
                    continue
                if on_axis_a:          # both on the line of symmetry: one shared pair
                    pid = self.next_pid
                    self.next_pid += 1
                    table[a] = (2, pid)
                    table[b] = (2, pid)
                elif ma == b:           # the pair is its own mirror image
                    pid = self.next_pid
                    self.next_pid += 1
                    table[a] = (2, pid)
                    table[b] = (2, pid)
                else:
                    if len(cells) < 4:
                        continue
                    p1, p2 = self.next_pid, self.next_pid + 1
                    self.next_pid += 2
                    table[a] = (2, p1)
                    table[b] = (2, p1)
                    table[ma] = (2, p2)
                    table[mb] = (2, p2)
                break

    def place_pearls(self) -> None:
        rng = self.rng
        style = rng.choice(["rich", "fields", "sparse", "mixed"])
        fields = [(rng.randrange(self.w), rng.randrange(self.h), rng.randint(2, 6)) for _ in range(rng.randint(2, 7))]
        for y in range(self.h):
            for x in range(self.w):
                key = (x, y)
                m = self.mirror(x, y)
                if m in self.gaps:
                    self.gaps[key] = self.gaps[m]
                    continue
                near = any(min(abs(x - fx), self.w - abs(x - fx)) + min(abs(y - fy), self.h - abs(y - fy)) <= r
                           for fx, fy, r in fields)
                if style == "rich":
                    lo = rng.randint(3, 30)
                elif style == "fields":
                    lo = rng.randint(5, 40) if near else (0 if rng.random() < 0.6 else rng.randint(200, 900))
                elif style == "sparse":
                    lo = rng.randint(40, 300) if rng.random() < 0.5 else 0
                else:
                    lo = rng.randint(5, 60) if near else rng.randint(80, 1500)
                self.gaps[key] = (0, 0) if lo == 0 else (lo, lo + rng.randint(0, lo))

    def spawns(self, per_team: int) -> list:
        """Team A spawns (head first), each a straight run of free cells."""
        rng = self.rng
        out = []
        taken = set()
        for _ in range(per_team):
            for _try in range(200):
                L = rng.randint(2, 6)
                x, y = rng.randrange(self.w), rng.randrange(self.h)
                d = rng.choice([(1, 0), (-1, 0), (0, 1), (0, -1)])
                cells = [(x + d[0] * i, y + d[1] * i) for i in range(L)]
                if not all(0 <= cx < self.w and 0 <= cy < self.h for cx, cy in cells):
                    continue
                mirrored = [self.mirror(*c) for c in cells]
                if len(set(cells) | set(mirrored)) < 2 * L or (set(cells) | set(mirrored)) & taken:
                    continue
                # keep team A on "its" side so the mirror is far away
                hx, hy = cells[0]
                mx, my = mirrored[0]
                span = self.h if self.sym == "x" else self.w if self.sym == "y" else (self.w + self.h) // 2
                if min(abs(hx - mx), self.w - abs(hx - mx)) + min(abs(hy - my), self.h - abs(hy - my)) < span // 3:
                    continue
                taken |= set(cells) | set(mirrored)
                for body in (cells, mirrored):
                    for (ax, ay), (bx, by) in zip(body, body[1:]):
                        if ax == bx:
                            self.protected.add(("h", ax, max(ay, by)))
                        else:
                            self.protected.add(("v", max(ax, bx), ay))
                out.append(cells)
                break
        return out

    def render(self, name: str, a_spawns: list) -> str:
        w, h = self.w, self.h
        lines = [f"MAP {w} {h}", f"SYMMETRY {self.sym if self.sym != 'r' else 'xy'}", f"MAP_NAME {name}",
                 f"TILE_COUNT {w * h}"]
        for y in range(h):
            for x in range(w):
                lo, hi = self.gaps[(x, y)]
                lines.append(f"TILE {x} {y} {lo} {hi}")
        edges = []
        for (x, y), (kind, pid) in sorted(self.hedge.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            edges.append((2 * y * (w + 1) + x, kind, pid))
        for (x, y), (kind, pid) in sorted(self.vedge.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            edges.append(((2 * y + 1) * (w + 1) + x, kind, pid))
        edges.sort()
        lines.append(f"EDGE_COUNT {len(edges)}")
        lines += [f"EDGE {i} {k} {p}" for i, k, p in edges]
        dragons = []
        for cells in a_spawns:
            mirrored = [self.mirror(*c) for c in cells]
            dragons.append((0, cells))
            dragons.append((1, mirrored))
        lines.append(f"DRAGON_COUNT {len(dragons)}")
        for team, cells in dragons:
            lines.append(f"DRAGON {team} {len(cells)} " + " ".join(f"{x} {y}" for x, y in cells))
        return "\n".join(lines) + "\n"


def generate(seed: int, index: int) -> tuple[str, str]:
    rng = random.Random(seed * 1000003 + index)
    w = rng.choice([rng.randint(10, 24), rng.randint(20, 40), rng.randint(32, 64)])
    h = rng.choice([rng.randint(10, 24), rng.randint(16, 40), rng.randint(24, 64)])
    sym = rng.choice(["x", "y", "r"])
    g = Gen(rng, w, h, sym)
    a_spawns = g.spawns(rng.randint(1, 5))
    if not a_spawns:
        return generate(seed, index + 7919)
    spawn_heads = [c[0] for c in a_spawns] + [g.mirror(*c[0]) for c in a_spawns]
    g.place_portals(rng.randint(0, 4))
    g.place_kelp(rng.randint(0, (w * h) // 40 + 2), spawn_heads)
    g.place_pearls()
    name = f"gen_{seed}_{index}"
    return name, g.render(name, a_spawns)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="lab.mapgen")
    p.add_argument("--count", type=int, default=20)
    p.add_argument("--seed", type=int, default=1)
    args = p.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    for i in range(args.count):
        name, text = generate(args.seed, i)
        (OUT / f"{name}.map").write_text(text)
    print(f"wrote {args.count} maps to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
