"""How queens use sprints (Ben, Oct 11: "sprinting is super powerful, make use of it" for escaping and finding pearls).
For every queen turn that moved and survived (docs/movement.md: ceil(L/4) free steps, every further step costs a segment):
  multi      share of moves with 2+ steps, by length band (1 / 2 / 3 / 4+ free steps)
  full       share of moves that used every free step
  paid       moves with more steps than free
  eat/turn   pearls eaten per move (length after - before + segments paid), single-step vs multi-step moves
  near       an enemy head within 6 (Manhattan, wrap) before the move: multi share near vs far
Plus per game: queen length at r100 / r200 / r300 and her pearls eaten by r200.
Groups: top 10 and +-50 Elo (latest ladder snapshot, scout replays since SINCE), us (team 135 games since --us-since).
    python analysis/queen_sprint_use.py [--since 2026-10-10T00:00] [--us-since 2026-10-11T04:05] [--per-team 30] [--jobs 10]
"""
from __future__ import annotations

import argparse
import collections
import sqlite3
import pathlib
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lab.common import DATA, load_replay  # noqa: E402

US = 135
BANDS = ((2, 4), (5, 8), (9, 12), (13, 999))


def one(job):
    path, side = job
    from lab.track import Tracker
    try:
        t = Tracker(load_replay(path), strict=False)
    except Exception:
        return None
    W, H = t.w, t.h
    queen = next(i for i in (0, 1) if t.dragons[i].team == side)
    c = collections.Counter()
    eaten = 0
    marks = {}
    for turn in t.run():
        for m in (100, 200, 300):
            if m not in marks and turn.round >= m:
                marks[m] = len(t.dragons[queen].body) if queen in t.dragons else 0
        if turn.id != queen or not turn.action or turn.action[0] != "move" or queen not in t.dragons:
            continue
        L0 = turn.header["length"]
        L1 = len(t.dragons[queen].body)
        steps = len(turn.action[1])
        free = (L0 + 3) // 4
        paid = max(0, steps - free)
        ate = L1 - L0 + paid
        if turn.round < 200:
            eaten += ate
        hx, hy = [(x, y) for tm, i, x, y, f, hd in turn.bodies if i == queen and hd][0]
        near = any(tm != side and hd and min(abs(x - hx), W - abs(x - hx)) + min(abs(y - hy), H - abs(y - hy)) <= 6
                   for tm, i, x, y, f, hd in turn.bodies)
        band = next(f"{a}-{b}" for a, b in BANDS if a <= L0 <= b) if L0 >= 2 else "1"
        multi = steps >= 2
        c[band + ":moves"] += 1
        c[band + ":multi"] += multi
        c[band + ":full"] += steps >= free and free >= 2
        c[band + ":paid"] += paid > 0
        c[band + (":near" if near else ":far")] += 1
        c[band + (":near_multi" if near else ":far_multi")] += multi
        c["moves"] += 1
        c["multi"] += multi
        c[("multi" if multi else "single") + ":n"] += 1
        c[("multi" if multi else "single") + ":ate"] += ate
    for m in (100, 200, 300):
        c[f"len{m}"] += marks.get(m, len(t.dragons[queen].body) if queen in t.dragons else 0)
    c["eaten200"] += eaten
    c["games"] += 1
    return c


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--since", default="2026-10-10T00:00")
    p.add_argument("--us-since", default="2026-10-11T04:05")
    p.add_argument("--per-team", type=int, default=30)
    p.add_argument("--jobs", type=int, default=10)
    a = p.parse_args()
    db = sqlite3.connect(f"file:{DATA / 'scout.db'}?mode=ro", uri=True)
    snap = db.execute("SELECT max(at) FROM ladder").fetchone()[0]
    ladder = db.execute("SELECT team_id, rank, elo FROM ladder WHERE at = ? ORDER BY rank", (snap,)).fetchall()
    names = dict(db.execute("SELECT id, name FROM teams"))
    our_elo = next((e for tid, _, e in ladder if tid == US), None)
    top = [tid for tid, rk, _ in ladder if rk is not None and rk <= 10 and tid != US]
    near = [tid for tid, _, e in ladder if our_elo is not None and abs(e - our_elo) <= 50 and tid != US and tid not in top]
    print(f"ladder {snap}: us {our_elo}; top 10 {[names.get(t) for t in top]}; +-50 {len(near)} teams")

    def jobs_for(tids, since, per_team):
        out = []
        for tid in tids:
            rows = db.execute("""SELECT id, team_a, team_b FROM games WHERE (team_a = ? OR team_b = ?) AND has_replay = 1
                                 AND ranked = 1 AND at >= ? ORDER BY at DESC LIMIT ?""", (tid, tid, since, per_team)).fetchall()
            for gid, ta, tb in rows:
                path = DATA / "replays" / f"{gid}.replay"
                if path.is_file():
                    out.append((str(path), "A" if ta == tid else "B"))
        return out

    groups = {"top 10": jobs_for(top, a.since, a.per_team), "+-50": jobs_for(near, a.since, max(6, a.per_team // 3)),
              "us": jobs_for([US], a.us_since, 400)}
    with ProcessPoolExecutor(a.jobs) as pool:
        for label, js in groups.items():
            tot = collections.Counter()
            for x in pool.map(one, js, chunksize=2):
                if x:
                    tot.update(x)
            g = max(1, tot["games"])
            print(f"\n== {label}: {tot['games']} games, {tot['moves']} queen moves, multi-step {tot['multi'] / max(1, tot['moves']):.1%}")
            print(f"   queen length mean r100 {tot['len100'] / g:.1f}, r200 {tot['len200'] / g:.1f}, r300 {tot['len300'] / g:.1f}; "
                  f"pearls eaten by r200 {tot['eaten200'] / g:.1f}")
            print(f"   pearls per move: single {tot['single:ate'] / max(1, tot['single:n']):.3f} ({tot['single:n']}), "
                  f"multi {tot['multi:ate'] / max(1, tot['multi:n']):.3f} ({tot['multi:n']})")
            for lo, hi in BANDS:
                b = f"{lo}-{hi}"
                n = tot[b + ":moves"]
                if not n:
                    continue
                print(f"   L {b:7s} moves {n:6d}: multi {tot[b + ':multi'] / n:6.1%}, all free steps {tot[b + ':full'] / n:6.1%}, "
                      f"paid {tot[b + ':paid'] / n:5.1%}; multi near enemy {tot[b + ':near_multi'] / max(1, tot[b + ':near']):6.1%} "
                      f"({tot[b + ':near']}), far {tot[b + ':far_multi'] / max(1, tot[b + ':far']):6.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
