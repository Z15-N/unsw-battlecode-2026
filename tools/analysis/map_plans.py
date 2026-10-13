"""Per-map plans learned from the top teams' replays (Ben, Oct 11: "don't forget our hard code strategy"): for every map
and each queen id (each has a fixed spawn), where the queens that SURVIVED to r500 on the WINNING side kept their head in
r200-499 (the queen's home), and where the winners' longest dragon kept its head in r400-499 (the king's spot).
Output: data/map_plans.json {map name: {"0": {...}, "1": {...}}} with the home/king tiles, sample sizes and the heat share
within 2 tiles; tools/gen_maps.py turns it into maps.hpp.
    python analysis/map_plans.py [games per map] [processes]"""
from __future__ import annotations

import collections
import json
import pathlib
import sqlite3
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lab.common import GameMap, load_replay  # noqa: E402

DATA = pathlib.Path(__file__).resolve().parents[2] / "data"
SINCE = "2026-10-10T00:00"


def one(path: str):
    """(map name, W, H, {queen id: [head tiles r200-499] if she lived and her team won}, [winner's longest heads r400-499])."""
    try:
        r = load_replay(pathlib.Path(path))
    except Exception:
        return None
    gm = GameMap.parse(r.map)
    team = {i: t for i, (t, _) in enumerate(gm.dragons)}
    length = {i: len(c) for i, (_, c) in enumerate(gm.dragons)}
    tail = {i: tuple(c[-1]) for i, (_, c) in enumerate(gm.dragons)}
    head = {i: tuple(c[0]) for i, (_, c) in enumerate(gm.dragons)}
    alive = set(length)
    qtrail = {0: [], 1: []}
    ktrail = {"A": [], "B": []}
    qdead = set()
    rnd = 0
    for e in r.events:
        k = e.which()
        if k == "roundStart":
            rnd = e.roundStart.round
            if 400 <= rnd <= 499:
                for t in ("A", "B"):
                    mine = [i for i in alive if team.get(i) == t]
                    if mine:
                        ktrail[t].append(head[max(mine, key=lambda i: length[i])])
        elif k == "dragonUpdate":
            u = e.dragonUpdate
            if u.id in length:
                if (u.tail.x, u.tail.y) == tail.get(u.id):
                    length[u.id] += 1
                tail[u.id] = (u.tail.x, u.tail.y)
                head[u.id] = (u.head.x, u.head.y)
                if u.id in (0, 1) and 200 <= rnd <= 499:
                    qtrail[u.id].append(head[u.id])
        elif k == "dragonSplit":
            s = e.dragonSplit
            team[s.childId] = "A" if str(s.team) == "a" else "B"
            length[s.parentId], length[s.childId] = len(s.parentBody), len(s.childBody)
            tail[s.parentId] = (s.parentBody[-1].x, s.parentBody[-1].y)
            tail[s.childId] = (s.childBody[-1].x, s.childBody[-1].y)
            head[s.parentId] = (s.parentBody[0].x, s.parentBody[0].y)
            head[s.childId] = (s.childBody[0].x, s.childBody[0].y)
            alive.add(s.childId)
        elif k == "dragonDeath":
            alive.discard(e.dragonDeath.id)
            if e.dragonDeath.id in (0, 1):
                qdead.add(e.dragonDeath.id)
    w = str(r.result.winner).upper()
    if w not in ("A", "B") or rnd < 499:
        return None
    queens = {q: qtrail[q] for q in (0, 1) if q not in qdead and team[q] == w}
    return gm.name, gm.width, gm.height, queens, {q: team[q] for q in (0, 1)}, ktrail[w], w


def hot(points, W, H, radius=2):
    """The tile with the most points within `radius` (wrapped Chebyshev), and that share of all points."""
    cnt = collections.Counter(points)
    best, bestv = None, -1
    for (x, y) in cnt:
        v = sum(cnt.get(((x + dx) % W, (y + dy) % H), 0) for dx in range(-radius, radius + 1) for dy in range(-radius, radius + 1))
        if v > bestv:
            best, bestv = (x, y), v
    return best, bestv / max(1, len(points))


def main() -> int:
    per_map = int(sys.argv[1]) if len(sys.argv) > 1 else 80
    procs = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    db = sqlite3.connect(DATA / "scout.db")
    maps = [m for (m,) in db.execute("SELECT DISTINCT map FROM games WHERE has_replay=1 AND at >= ?", (SINCE,))]
    paths = []
    for mp in maps:
        ids = [g for (g,) in db.execute("SELECT id FROM games WHERE has_replay=1 AND at >= ? AND map=? AND winner IN ('a','b') "
                                        "ORDER BY at DESC", (SINCE, mp))]
        got = [str(DATA / "replays" / f"{g}.replay") for g in ids if (DATA / "replays" / f"{g}.replay").is_file()]
        paths += got[:per_map]
    print(f"{len(paths)} replays over {len(maps)} maps", flush=True)
    qpts = collections.defaultdict(lambda: collections.defaultdict(list))
    kpts = collections.defaultdict(lambda: collections.defaultdict(list))
    nq = collections.defaultdict(collections.Counter)
    size = {}
    with ProcessPoolExecutor(procs) as pool:
        for res in pool.map(one, paths, chunksize=4):
            if not res:
                continue
            name, W, H, queens, qteam, ktrail, w = res
            size[name] = (W, H)
            for q, trail in queens.items():
                qpts[name][q] += trail
                nq[name][q] += 1
            # the king's spot belongs to the winner's queen id (the side it plays from)
            wq = next(q for q in (0, 1) if qteam[q] == w)
            kpts[name][wq] += ktrail
    out = {}
    for name in sorted(size):
        W, H = size[name]
        out[name] = {}
        for q in (0, 1):
            home, hs = hot(qpts[name][q], W, H) if qpts[name][q] else (None, 0)
            king, ks = hot(kpts[name][q], W, H) if kpts[name][q] else (None, 0)
            out[name][str(q)] = {"home": home, "home_share": round(hs, 3), "home_games": nq[name][q],
                                 "king": king, "king_share": round(ks, 3)}
        print(f"{name:26s} q0 home {out[name]['0']['home']} ({out[name]['0']['home_games']} games, {out[name]['0']['home_share']:.0%}) "
              f"king {out[name]['0']['king']} | q1 home {out[name]['1']['home']} ({out[name]['1']['home_games']}, "
              f"{out[name]['1']['home_share']:.0%}) king {out[name]['1']['king']}", flush=True)
    (DATA / "map_plans.json").write_text(json.dumps(out, indent=1))
    print("wrote data/map_plans.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
