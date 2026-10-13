"""How small is the door to our queen's home? (v057 pre-check: door sealing; Ben, Oct 11.)
docs: bodies are walls, a dragon that rams a body dies alone. If a few tiles separate the queen's home from the enemy
side, guards lying across them seal her in. Per current map and queen id: home = the learned home (data/map_plans.json,
as maps.hpp's qhome) or her spawn; for each radius r, the minimum vertex cut (max-flow, node splitting, Menger) between
every tile within r path steps of home and every tile within ENEMY_R of the enemy queen's spawn, cutting only tiles farther than r. Prints the cut size
per r (">12" when larger), and for the smallest cut whose sealed room holds >= 40 tiles: the room size and the cut tiles.
    python analysis/home_cuts.py
"""
from __future__ import annotations

import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lab.common import GameMap  # noqa: E402
from map_topology import graph  # noqa: E402

DATA = pathlib.Path(__file__).resolve().parents[2] / "data"
RADII = (2, 3, 4, 5, 6, 8, 10)
CAP = 12
MIN_ROOM = 40
ENEMY_R = 6      # the enemy side: every tile within this many path steps of the enemy queen's spawn


def bfs(adj, src):
    d = {src: 0}
    q = collections.deque([src])
    while q:
        u = q.popleft()
        for v in adj.get(u, ()):
            if v not in d:
                d[v] = d[u] + 1
                q.append(v)
    return d


def min_cut(adj, region: set, sinks: set):
    """Min vertex cut between `region` (contracted source) and `sinks` (contracted sink), cutting only tiles in neither.
    Returns (size, cut tiles) or (None, None) when larger than CAP."""
    INF = 10 ** 9
    cap = collections.defaultdict(int)
    nbr = collections.defaultdict(set)

    def add(a, b, c):
        cap[(a, b)] += c
        nbr[a].add(b)
        nbr[b].add(a)

    S, T = ("S",), ("T",)
    for u, vs in adj.items():
        if u in sinks:
            continue
        uo = S if u in region else (u, "out")
        if u not in region:
            add((u, "in"), (u, "out"), 1)
        for v in vs:
            if v in region:
                continue
            add(uo, T if v in sinks else (v, "in"), INF)
    flow = 0
    while True:
        par = {S: None}
        q = collections.deque([S])
        while q and T not in par:
            a = q.popleft()
            for b in nbr[a]:
                if b not in par and cap[(a, b)] > 0:
                    par[b] = a
                    q.append(b)
        if T not in par:
            break
        b = T
        while par[b] is not None:
            a = par[b]
            cap[(a, b)] -= 1
            cap[(b, a)] += 1
            b = a
        flow += 1
        if flow > CAP:
            return None, None
    # source side of the residual graph: cut = split edges from in (reached) to out (not reached)
    reached = set(par)
    cut = [v[0] for v in reached if len(v) == 2 and v[1] == "in" and (v[0], "out") not in reached]
    return flow, cut


def main() -> int:
    plans = json.loads((DATA / "map_plans.json").read_text())
    for p in sorted((DATA / "maps_current").glob("*.map")):
        m = GameMap.parse(p.read_text())
        adj = graph(m)
        spawns = {i: tuple(cells[0]) for i, (_, cells) in enumerate(m.dragons) if i <= 1}
        for q in (0, 1):
            home = tuple(plans.get(m.name, {}).get(str(q), {}).get("home") or spawns[q])
            if home not in adj:
                home = spawns[q]
            enemy = spawns[1 - q]
            dist = bfs(adj, home)
            edist = bfs(adj, enemy)
            sinks = {t for t, k in edist.items() if k <= ENEMY_R}
            row, best = [], None
            for r in RADII:
                region = {t for t, k in dist.items() if k <= r}
                if region & sinks:
                    row.append("-")
                    continue
                size, cut = min_cut(adj, region, sinks)
                if size is None:
                    row.append(f">{CAP}")
                    continue
                walls = set(cut)
                room = len(bfs({u: [v for v in vs if v not in walls] for u, vs in adj.items() if u not in walls}, home))
                row.append(f"{size}({room})")
                if room >= MIN_ROOM and (best is None or size < best[0]):
                    best = (size, r, room, sorted(cut))
            tail = f"  best: {best[0]} tiles at r{best[1]}, room {best[2]}: {best[3]}" if best else ""
            print(f"{m.name:24s} q{q} home {home}: " + " ".join(f"r{r}={x}" for r, x in zip(RADII, row)) + tail, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
