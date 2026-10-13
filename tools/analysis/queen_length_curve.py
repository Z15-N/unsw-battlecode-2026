"""How long are the queens, round by round, and when do they die? (Oct 12: 28 of our queen's 36 own-move deaths on the
ladder (v056/v065) came at length 2-3, between r55 and r310; before round 150 our queen splits like any starter.)
Per team (scout replays since --since, ranked) and us: the share of games with the queen alive and her median length
(alive only) at rounds 25/50/100/150/200/300, the splits she made before r150, and her deaths (own move / enemy) before
r150 and after.
    python analysis/queen_length_curve.py [--since 2026-10-11T12:00] [--per-team 25]
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
MARKS = (25, 50, 100, 150, 200, 300)


def one(job):
    path, side = job
    from lab.track import Tracker
    try:
        t = Tracker(load_replay(path), strict=False)
    except Exception:
        return None
    q = next(i for i in (0, 1) if t.dragons[i].team == side)
    lens, splits, death = {}, 0, None
    marks = list(MARKS)
    for turn in t.run():
        while marks and turn.round >= marks[0] and q in t.dragons:
            lens[marks.pop(0)] = len(t.dragons[q].body)
        if turn.id == q and turn.action and turn.action[0] == "split" and turn.round < 150:
            splits += 1
        if q not in t.dragons:
            death = (turn.round, turn.id == q)
            break
    return {"lens": lens, "splits": splits, "death": death, "map": t.map.name}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--since", default="2026-10-11T12:00")
    p.add_argument("--per-team", type=int, default=25)
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
            res = [x for x in pool.map(one, jobs(tid, a.per_team if tid != US else 3 * a.per_team), chunksize=2) if x]
            if not res:
                continue
            n = len(res)
            cells = []
            for m in MARKS:
                alive = [x["lens"][m] for x in res if m in x["lens"] and not (x["death"] and x["death"][0] < m)]
                cells.append(f"r{m} {len(alive) / n:4.0%} {st.median(alive) if alive else 0:4.1f}")
            early_own = sum(1 for x in res if x["death"] and x["death"][0] < 150 and x["death"][1])
            early_en = sum(1 for x in res if x["death"] and x["death"][0] < 150 and not x["death"][1])
            late_own = sum(1 for x in res if x["death"] and x["death"][0] >= 150 and x["death"][1])
            late_en = sum(1 for x in res if x["death"] and x["death"][0] >= 150 and not x["death"][1])
            print(f"{label[:20]:20s} n {n:3d} | alive% / median len: " + " | ".join(cells) +
                  f" | splits<r150 {st.mean(x['splits'] for x in res):4.1f} | deaths <r150 own {early_own / n:4.0%} enemy {early_en / n:4.0%},"
                  f" r150+ own {late_own / n:4.0%} enemy {late_en / n:4.0%}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
