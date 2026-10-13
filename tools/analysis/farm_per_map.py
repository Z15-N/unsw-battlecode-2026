"""Pearls eaten by r50 / r100 / r200 per map: us (v056's ranked games, replays cached by the watcher) vs the teams within
50 Elo and the top 10 (scout replays since --since), so the farming gap is read map by map, not through the map mix.
Uses lab.study.study_game (a tail that stays put on a dragonUpdate = a pearl eaten).
    python analysis/farm_per_map.py [--since 2026-10-10T12:00] [--sub 22006] [--jobs 6]
"""
from __future__ import annotations

import argparse
import collections
import sqlite3
import statistics as st
import pathlib
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lab.common import DATA, load_replay  # noqa: E402

US = 135


def one(job):
    path, side, group = job
    from lab.study import study_game
    try:
        r = load_replay(path)
        e = study_game(path, side)["eat"]
    except Exception:
        return None
    from lab.common import GameMap
    return group, GameMap.parse(r.map).name, e.get("eat50", 0), e.get("eat100", 0), e.get("eat200", 0)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--since", default="2026-10-10T12:00")
    p.add_argument("--sub", default="22006")
    p.add_argument("--jobs", type=int, default=6)
    a = p.parse_args()
    db = sqlite3.connect(f"file:{DATA / 'scout.db'}?mode=ro", uri=True)
    snap = db.execute("SELECT max(at) FROM ladder").fetchone()[0]
    lad = db.execute("SELECT team_id, rank, elo FROM ladder WHERE at = ?", (snap,)).fetchall()
    our_elo = next(e for tid, _, e in lad if tid == US)
    top = [tid for tid, rk, _ in lad if rk is not None and rk <= 10 and tid != US]
    near = [tid for tid, _, e in lad if abs(e - our_elo) <= 50 and tid != US and tid not in top]
    jobs = []
    for group, tids, n in (("top10", top, 25), ("near50", near, 6)):
        for tid in tids:
            for gid, ta in db.execute("""SELECT id, team_a FROM games WHERE (team_a = ? OR team_b = ?) AND has_replay = 1 AND
                                         ranked = 1 AND at >= ? ORDER BY at DESC LIMIT ?""", (tid, tid, a.since, n)):
                path = DATA / "replays" / f"{gid}.replay"
                if path.is_file():
                    jobs.append((str(path), "A" if ta == tid else "B", group))
    from lab.api import Client
    from lab.diagnose import CACHE, TEAM_ID
    c = Client()
    for b in c.get("/battles?limit=50"):
        if not b.get("ranked") or b.get("outcome") not in ("win", "loss", "draw"):
            continue
        d = c.get(f"/battles/{b['id']}")
        side = "A" if d["match"]["teamAId"] == TEAM_ID else "B"
        for g in d.get("games", []):
            path = CACHE / f"{g['id']}.replay"
            if path.is_file():
                r = load_replay(path)
                if str(r.botA if side == "A" else r.botB) == a.sub:
                    jobs.append((str(path), side, "us"))
    acc = collections.defaultdict(list)
    with ProcessPoolExecutor(a.jobs) as pool:
        for x in pool.map(one, jobs, chunksize=4):
            if x:
                group, m, e50, e100, e200 = x
                acc[(m, group)].append((e50, e100, e200))
    maps = sorted({m for m, _ in acc})
    tot = collections.defaultdict(list)
    print(f"{'map':26s} | {'us (n) r50/r100/r200':28s} | {'+-50 (n)':28s} | {'top 10 (n)':28s}")
    for m in maps:
        cells = []
        for g in ("us", "near50", "top10"):
            v = acc.get((m, g), [])
            if v:
                cells.append(f"({len(v):2d}) {st.mean(x[0] for x in v):4.0f} {st.mean(x[1] for x in v):5.0f} {st.mean(x[2] for x in v):5.0f}")
            else:
                cells.append("-")
        print(f"{m:26s} | {cells[0]:28s} | {cells[1]:28s} | {cells[2]:28s}")
        # paired by map: ratio us / others where both exist
        if acc.get((m, "us")):
            u = st.mean(x[1] for x in acc[(m, "us")])
            for g in ("near50", "top10"):
                if acc.get((m, g)):
                    tot[g].append(u / max(1.0, st.mean(x[1] for x in acc[(m, g)])))
    for g, v in tot.items():
        print(f"us / {g} pearls by r100, mean over {len(v)} maps both played: {st.mean(v):.2f} (median {st.median(v):.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
