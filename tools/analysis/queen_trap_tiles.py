"""Where do queens kill themselves, per map and queen id? (Ben, Oct 10-12: hard code per map; v056/v065's own-move deaths
cluster on Islands 75%, athena 62%, caution 60%, the Trolleys 40-50% of games.) For every ranked replay since --since (all
teams in scout.db, plus our cached games): each queen's own-move death tile and her head 1-3 turns before it. Prints,
per map and queen id, the tiles where 2+ such deaths happened (and how many of them were ours), and writes
data/queen_traps.json {map: {"0": [[x, y, deaths, ours], ...], "1": [...]}} for gen_maps.
    python analysis/queen_trap_tiles.py [--since 2026-10-10T00:00] [--per-map 120]
"""
from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import pathlib
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lab.common import DATA, load_replay  # noqa: E402

US = 135


def one(job):
    path, ours_side = job
    try:
        r = load_replay(path)
    except Exception:
        return []
    from lab.common import GameMap
    gm = GameMap.parse(r.map)
    team = {i: t for i, (t, _) in enumerate(gm.dragons)}
    heads = {0: [tuple(gm.dragons[0][1][0])], 1: [tuple(gm.dragons[1][1][0])]}
    actor = None
    out = []
    dead = set()
    for e in r.events:
        k = e.which()
        if k == "dragonAction":
            actor = e.dragonAction.id
        elif k == "dragonUpdate":
            u = e.dragonUpdate
            if u.id in heads:
                heads[u.id].append((u.head.x, u.head.y))
        elif k == "dragonDeath":
            q = e.dragonDeath.id
            if q in (0, 1) and q not in dead:
                dead.add(q)
                if actor == q:
                    h = heads[q]
                    out.append((gm.name, q, h[-1], h[-4] if len(h) >= 4 else h[0], team[q] == ours_side))
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--since", default="2026-10-10T00:00")
    p.add_argument("--per-map", type=int, default=120)
    p.add_argument("--jobs", type=int, default=6)
    a = p.parse_args()
    db = sqlite3.connect(f"file:{DATA / 'scout.db'}?mode=ro", uri=True)
    jobs = []
    for gid, ta, tb in db.execute("""SELECT id, team_a, team_b FROM games WHERE has_replay = 1 AND ranked = 1 AND at >= ?
                                     ORDER BY at DESC""", (a.since,)):
        path = DATA / "replays" / f"{gid}.replay"
        if path.is_file():
            jobs.append((str(path), "A" if ta == US else ("B" if tb == US else "-")))
    print(f"{len(jobs)} replays", flush=True)
    deaths = collections.defaultdict(collections.Counter)
    ours = collections.defaultdict(collections.Counter)
    total = collections.Counter()
    with ProcessPoolExecutor(a.jobs) as pool:
        for res in pool.map(one, jobs, chunksize=8):
            for m, q, tile, before, mine in res:
                deaths[(m, q)][tile] += 1
                total[(m, q)] += 1
                if mine:
                    ours[(m, q)][tile] += 1
    out = collections.defaultdict(dict)
    for (m, q), cnt in sorted(deaths.items()):
        hot = [(t, n) for t, n in cnt.most_common() if n >= 2]
        if hot:
            print(f"{m:26s} q{q}: {total[(m, q)]:3d} own-move deaths; tiles with 2+: " +
                  ", ".join(f"{t}x{n}" + (f"(ours {ours[(m, q)][t]})" if ours[(m, q)][t] else "") for t, n in hot[:8]))
        out[m][str(q)] = [[t[0], t[1], n, ours[(m, q)][t]] for t, n in hot]
    (DATA / "queen_traps.json").write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
