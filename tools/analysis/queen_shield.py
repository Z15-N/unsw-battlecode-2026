"""How do the teams whose queens survive keep enemies off her? (Ben's rule: copy a skill from the teams better at it.)
Per team (scout replays since --since, ranked) and us: queen deaths by enemies per game, and over her turns r50-450:
allied body segments within 2 (Chebyshev) of her head, allied heads within 3, enemy heads within 6, her length, her free
sides, the share of turns in a Tarjan dead end (analysis/map_topology.dead_ends), and her distance from her spawn.
    python analysis/queen_shield.py [--since 2026-10-10T12:00] [--per-team 15] [--teams "aAah,larp stock zi balls,..."]
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
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lab.common import DATA, load_replay  # noqa: E402

US = 135
_de = {}


def one(job):
    path, side = job
    from lab.track import Tracker
    from map_topology import dead_ends
    try:
        t = Tracker(load_replay(path), strict=False)
    except Exception:
        return None
    W, H = t.w, t.h
    if t.map.name not in _de:
        _de[t.map.name] = dead_ends(t.map)
    de = _de[t.map.name]
    cheb = lambda a, b: max(min(abs(a[0] - b[0]), W - abs(a[0] - b[0])), min(abs(a[1] - b[1]), H - abs(a[1] - b[1])))
    md = lambda a, b: min(abs(a[0] - b[0]), W - abs(a[0] - b[0])) + min(abs(a[1] - b[1]), H - abs(a[1] - b[1]))
    q = next(i for i in (0, 1) if t.dragons[i].team == side)
    spawn = tuple(t.dragons[q].body[0][:2])
    c = collections.Counter()
    c["games"] = 1
    for turn in t.run():
        if q not in t.dragons:
            c["enemy kill" if turn.id != q else "own death"] += 1
            break
        if turn.id != q or not (50 <= turn.round < 450):
            continue
        qd = t.dragons[q]
        h = (qd.body[0][0], qd.body[0][1])
        occ = set()
        ally_seg = ally_head = enemy_head = 0
        for d in t.dragons.values():
            for k, (x, y, _) in enumerate(d.body):
                occ.add((x, y))
                if d.id == q:
                    continue
                if d.team == side and cheb((x, y), h) <= 2:
                    ally_seg += 1
                if k == 0 and d.team == side and md((x, y), h) <= 3:
                    ally_head += 1
                if k == 0 and d.team != side and md((x, y), h) <= 6:
                    enemy_head += 1
        free = sum(1 for dr in "NESW" if (n := t.map.step(*h, dr)) is not None and n not in occ)
        c["turns"] += 1
        c["ally seg r2"] += ally_seg
        c["ally head r3"] += ally_head
        c["enemy head r6"] += enemy_head
        c["turns enemy near"] += enemy_head > 0
        c["len"] += len(qd.body)
        c["free"] += free
        c["in dead end"] += h in de
        c["from spawn"] += md(h, spawn)
    return c


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--since", default="2026-10-10T12:00")
    p.add_argument("--per-team", type=int, default=15)
    p.add_argument("--teams", default="aAah,larp stock zi balls,chat gippy tea,WeHaveQuizzes,forgot to mention,horse,SSS,Cutlery")
    a = p.parse_args()
    db = sqlite3.connect(f"file:{DATA / 'scout.db'}?mode=ro", uri=True)
    names = {n: i for i, n in db.execute("SELECT id, name FROM teams")}
    groups = [(n, names[n]) for n in a.teams.split(",") if n in names] + [("us", US)]

    def jobs(tid, n):
        out = []
        for gid, ta in db.execute("""SELECT id, team_a FROM games WHERE (team_a = ? OR team_b = ?) AND has_replay = 1 AND
                                     ranked = 1 AND at >= ? ORDER BY at DESC LIMIT ?""", (tid, tid, a.since, n)):
            path = DATA / "replays" / f"{gid}.replay"
            if path.is_file():
                out.append((str(path), "A" if ta == tid else "B"))
        return out

    with ProcessPoolExecutor(2) as pool:
        for label, tid in groups:
            tot = collections.Counter()
            for x in pool.map(one, jobs(tid, a.per_team if tid != US else 60), chunksize=2):
                if x:
                    tot.update(x)
            g, n = max(1, tot["games"]), max(1, tot["turns"])
            print(f"{label[:22]:22s} games {tot['games']:3d}: queen killed by enemies {tot['enemy kill'] / g:4.0%}, own {tot['own death'] / g:4.0%} | "
                  f"r50-450: ally segments within 2 {tot['ally seg r2'] / n:4.1f}, ally heads within 3 {tot['ally head r3'] / n:4.2f}, "
                  f"enemy head within 6 on {tot['turns enemy near'] / n:4.0%} of turns, length {tot['len'] / n:4.1f}, free sides "
                  f"{tot['free'] / n:3.1f}, in a dead end {tot['in dead end'] / n:4.0%}, from spawn {tot['from spawn'] / n:4.1f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
