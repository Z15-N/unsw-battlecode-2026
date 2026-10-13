"""Per-map farming and openings learned from the top teams' winning games (Ben, Oct 11: option 3, "learn from the top teams'
data directly", hard-coded per map). For every map:
  - farm tiles: where the WINNING side's dragons ate in r0-300 (a dragon's tail stayed = it ate on the tile its head
    moved onto), per queen side (the side whose queen is id 0 or id 1), the top FARM_TOP tiles with their share;
  - openings: for each starting dragon id of the winning side, its head at r10/r25/r50 (most common tile, with share).
Output: data/map_farms.json {map: {"farm": {"0": [[x, y, share], ...], "1": [...]}, "open": {dragon id: {"10": [x, y, share], ...}}}}
    python analysis/map_farms.py [games per map] [processes]"""
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
FARM_TOP = 24
MARKS = (10, 25, 50)


def one(path: str):
    try:
        r = load_replay(pathlib.Path(path))
    except Exception:
        return None
    w = str(r.result.winner).upper()
    if w not in ("A", "B"):
        return None
    gm = GameMap.parse(r.map)
    team = {i: t for i, (t, _) in enumerate(gm.dragons)}
    starters = [i for i in team if team[i] == w]
    tail = {i: tuple(c[-1]) for i, (_, c) in enumerate(gm.dragons)}
    head = {i: tuple(c[0]) for i, (_, c) in enumerate(gm.dragons)}
    eats = []
    marks = {}
    rnd = 0
    for e in r.events:
        k = e.which()
        if k == "roundStart":
            rnd = e.roundStart.round
            if rnd in MARKS:
                marks[rnd] = {i: head[i] for i in starters if i in head}
            if rnd > 300:
                break
        elif k == "dragonUpdate":
            u = e.dragonUpdate
            if u.id in tail:
                if (u.tail.x, u.tail.y) == tail[u.id] and team.get(u.id) == w:
                    eats.append((u.head.x, u.head.y))
                tail[u.id] = (u.tail.x, u.tail.y)
                head[u.id] = (u.head.x, u.head.y)
        elif k == "dragonSplit":
            s = e.dragonSplit
            team[s.childId] = "A" if str(s.team) == "a" else "B"
            tail[s.parentId] = (s.parentBody[-1].x, s.parentBody[-1].y)
            tail[s.childId] = (s.childBody[-1].x, s.childBody[-1].y)
            head[s.parentId] = (s.parentBody[0].x, s.parentBody[0].y)
            head[s.childId] = (s.childBody[0].x, s.childBody[0].y)
        elif k == "dragonDeath":
            head.pop(e.dragonDeath.id, None)
    wq = next(q for q in (0, 1) if team[q] == w)
    return gm.name, wq, eats, marks


def main() -> int:
    per_map = int(sys.argv[1]) if len(sys.argv) > 1 else 80
    procs = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    db = sqlite3.connect(DATA / "scout.db")
    maps = [m for (m,) in db.execute("SELECT DISTINCT map FROM games WHERE has_replay=1 AND at >= ?", (SINCE,))]
    paths = []
    for mp in maps:
        ids = [g for (g,) in db.execute("SELECT id FROM games WHERE has_replay=1 AND at >= ? AND map=? AND winner IN ('a','b') "
                                        "ORDER BY at DESC", (SINCE, mp))]
        paths += [str(DATA / "replays" / f"{g}.replay") for g in ids if (DATA / "replays" / f"{g}.replay").is_file()][:per_map]
    print(f"{len(paths)} replays over {len(maps)} maps", flush=True)
    farm = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    opening = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(collections.Counter)))
    games = collections.Counter()
    with ProcessPoolExecutor(procs) as pool:
        for res in pool.map(one, paths, chunksize=4):
            if not res:
                continue
            name, wq, eats, marks = res
            games[name] += 1
            farm[name][wq].update(eats)
            for rr, heads in marks.items():
                for i, h in heads.items():
                    opening[name][i][rr][h] += 1
    out = {}
    for name in sorted(games):
        f = {}
        for q in (0, 1):
            c = farm[name][q]
            tot = sum(c.values()) or 1
            f[str(q)] = [[x, y, round(n / tot, 4)] for (x, y), n in c.most_common(FARM_TOP)]
        o = {}
        for i, byr in opening[name].items():
            o[str(i)] = {}
            for rr, c in byr.items():
                (x, y), n = c.most_common(1)[0]
                o[str(i)][str(rr)] = [x, y, round(n / sum(c.values()), 3)]
        out[name] = {"games": games[name], "farm": f, "open": o}
        top0 = f["0"][:3]
        print(f"{name:26s} {games[name]:3d} games | farm q0 top {top0} | openings for {len(o)} starters", flush=True)
    (DATA / "map_farms.json").write_text(json.dumps(out, indent=1))
    print("wrote data/map_farms.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
