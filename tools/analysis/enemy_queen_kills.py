"""Who kills the enemy queen, and where does she sit? (Pre-check for algorithm queue #3, cops and robbers; Ben, Oct 11.)
Per side and game: did the enemy queen die by one of this side's dragons (its move, or her move into its body/head), in
which round; and the enemy queen's distance (wrapped Manhattan) from her learned home (data/map_plans.json, her id) over
r100-499: share of her turns within 4 tiles, and at her death.
Groups: top 10 (latest ladder snapshot, scout replays since --since) and us (team 135 games since --since).
    python analysis/enemy_queen_kills.py [--since 2026-10-10T12:00] [--per-team 20]
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
PLANS = json.loads((DATA / "map_plans.json").read_text())


def one(job):
    path, side = job
    from lab.track import Tracker
    try:
        t = Tracker(load_replay(path), strict=False)
    except Exception:
        return None
    W, H = t.w, t.h
    eq = next(i for i in (0, 1) if t.dragons[i].team != side)
    home = PLANS.get(t.map.name, {}).get(str(eq), {}).get("home")
    md = lambda a, b: min(abs(a[0] - b[0]), W - abs(a[0] - b[0])) + min(abs(a[1] - b[1]), H - abs(a[1] - b[1]))
    c = collections.Counter()
    c["games"] = 1
    last = None
    teams = {}                       # every dragon's team, kept after it dies (head-on rams kill the killer too)
    for turn in t.run():
        for d in t.dragons.values():
            teams.setdefault(d.id, d.team)
        if eq not in t.dragons:
            team = teams.get(turn.id)
            if turn.id == eq:
                c["enemy queen died by her own move"] += 1   # into a wall, her body, or one of ours (counted below)
            elif team == side:
                c["enemy queen killed by us"] += 1
                c["kill round sum"] += turn.round
            else:
                c["enemy queen died other"] += 1
            if home and last:
                c["at death within 4 of home"] += md(last, home) <= 4
                c["deaths with a home"] += 1
            break
        if turn.id == eq and home and 100 <= turn.round < 500:
            q = t.dragons[eq].body[0]
            last = (q[0], q[1])
            c["her turns r100+"] += 1
            c["her turns within 4 of home"] += md(last, home) <= 4
        elif turn.id == eq:
            q = t.dragons[eq].body[0]
            last = (q[0], q[1])
    return c


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--since", default="2026-10-10T12:00")
    p.add_argument("--per-team", type=int, default=20)
    a = p.parse_args()
    db = sqlite3.connect(f"file:{DATA / 'scout.db'}?mode=ro", uri=True)
    snap = db.execute("SELECT max(at) FROM ladder").fetchone()[0]
    top = [tid for tid, rk in db.execute("SELECT team_id, rank FROM ladder WHERE at = ?", (snap,)) if rk is not None and rk <= 10 and tid != US]

    def jobs(tids, n):
        out = []
        for tid in tids:
            for gid, ta in db.execute("""SELECT id, team_a FROM games WHERE (team_a = ? OR team_b = ?) AND has_replay = 1 AND
                                         ranked = 1 AND at >= ? ORDER BY at DESC LIMIT ?""", (tid, tid, a.since, n)):
                path = DATA / "replays" / f"{gid}.replay"
                if path.is_file():
                    out.append((str(path), "A" if ta == tid else "B"))
        return out

    with ProcessPoolExecutor(2) as pool:
        for label, js in (("top 10", jobs(top, a.per_team)), ("us", jobs([US], 400))):
            tot = collections.Counter()
            for x in pool.map(one, js, chunksize=2):
                if x:
                    tot.update(x)
            g = max(1, tot["games"])
            print(f"== {label}: {tot['games']} games; enemy queen killed by them {tot['enemy queen killed by us']} "
                  f"({tot['enemy queen killed by us'] / g:.0%}, mean round {tot['kill round sum'] / max(1, tot['enemy queen killed by us']):.0f}), "
                  f"by her own move {tot['enemy queen died by her own move']}, other {tot['enemy queen died other']}; "
                  f"enemy queen within 4 of her learned home on {tot['her turns within 4 of home'] / max(1, tot['her turns r100+']):.0%} "
                  f"of her r100+ turns, at death {tot['at death within 4 of home']}/{tot['deaths with a home']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
