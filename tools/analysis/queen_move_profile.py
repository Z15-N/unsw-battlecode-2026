"""How do queens move and eat by length? (algorithm queue #9, Oct 12: beam search for 13+ queens, space-time A* that
arrives as pearls spawn.) Per team (scout replays since --since, ranked) and us, queen moves only: by length band
(2-4, 5-8, 9-12, 13+), the share of moves with 1 / 2 / 3 / 4+ steps, and how often a move used every free step she had
(ceil(L/4)); her eats per 100 moves, and the share of her eats that were 'timed' (a spawned pearl, not a death drop, that
appeared at most 2 rounds before she ate it).
    python analysis/queen_move_profile.py [--since 2026-10-11T12:00] [--per-team 25]
"""
from __future__ import annotations

import argparse
import collections
import sqlite3
import pathlib
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lab.common import DATA, GameMap, load_replay  # noqa: E402

US = 135


def band(L):
    return "2-4" if L <= 4 else "5-8" if L <= 8 else "9-12" if L <= 12 else "13+"


def one(job):
    path, side = job
    try:
        r = load_replay(path)
    except Exception:
        return None
    gm = GameMap.parse(r.map)
    q = next(i for i, (tm, _) in enumerate(gm.dragons) if tm == side)
    L = len(gm.dragons[q][1])
    c = collections.Counter()
    appeared = {}
    died = False
    rnd, actor, steps, eaten = 0, None, 0, []
    for e in r.events:
        k = e.which()
        if k == "roundStart":
            rnd = e.roundStart.round
            died = False
        elif k == "tileChange":
            t = e.tileChange
            xy = (t.tile.x, t.tile.y)
            if t.hasPearl:
                appeared[xy] = -99 if died else rnd  # death drops (pearls made in a turn with a death) are not spawns
            elif actor == q:
                eaten.append(rnd - appeared.get(xy, -99))
        elif k == "turnStart":
            if actor == q and steps:
                free = (L + 3) // 4
                b = band(L)
                c[(b, "moves")] += 1
                c[(b, min(steps, 4))] += 1
                if steps >= 2 and steps == free:
                    c[(b, "all free")] += 1
                if free >= 2:
                    c[(b, "could sprint")] += 1
                c["moves"] += 1
                c["eats"] += len(eaten)
                c["timed"] += sum(1 for a in eaten if 0 <= a <= 2)
                L += len(eaten) - max(0, steps - free)
            actor, steps, eaten, died = e.turnStart.id, 0, [], False
        elif k == "dragonAction" and e.dragonAction.id == q:
            a = e.dragonAction
            if not a.tle and a.action.which() == "move":
                steps = len(a.action.move)
        elif k == "dragonSplit" and e.dragonSplit.parentId == q:
            L = len(e.dragonSplit.parentBody)
        elif k == "dragonDeath":
            died = True
            if e.dragonDeath.id == q:
                break
    return c


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
            tot = collections.Counter()
            for x in pool.map(one, jobs(tid, a.per_team if tid != US else 3 * a.per_team), chunksize=2):
                if x:
                    tot.update(x)
            cells = []
            for b in ("2-4", "5-8", "9-12", "13+"):
                n = max(1, tot[(b, "moves")])
                cells.append(f"{b}: {tot[(b, 'moves')]:5d} mv, 1/2/3/4+ {tot[(b, 1)] / n:3.0%}/{tot[(b, 2)] / n:3.0%}/{tot[(b, 3)] / n:3.0%}/{tot[(b, 4)] / n:3.0%}, all-free {tot[(b, 'all free')] / max(1, tot[(b, 'could sprint')]):3.0%}")
            m = max(1, tot["moves"])
            print(f"{label[:18]:18s} eats/100 moves {100 * tot['eats'] / m:4.1f}, timed {tot['timed'] / max(1, tot['eats']):3.0%} | " + " | ".join(cells), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
