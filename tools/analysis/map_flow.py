"""One map, us vs named teams: per 50-round band, the team's dragons alive at the band start (median), pearls eaten,
splits, and non-queen deaths by kind (kelp/self/no action, into a body, head-on) per game. Us = our ranked games
since lo_utc on that map; others = scout replays on that map.
    python analysis/map_flow.py Devil "aAah,horse" lo_utc [games]
"""
import collections
import sqlite3
import statistics
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lab.common import DATA, GameMap, load_replay  # noqa: E402

BANDS = [(0, 50), (50, 100), (100, 150), (150, 200), (200, 300), (300, 500)]


def one(path, side):
    r = load_replay(path)
    gm = GameMap.parse(r.map)
    team = {i: x[0] for i, x in enumerate(gm.dragons)}
    length = {i: len(x[1]) for i, x in enumerate(gm.dragons)}
    alive = set(team)
    rnd = 0
    actor = None
    out = collections.defaultdict(collections.Counter)
    alive_at = {}

    def band(rr):
        for lo, hi in BANDS:
            if lo <= rr < hi:
                return (lo, hi)
        return None

    for e in r.events:
        k = e.which()
        if k == "roundStart":
            rnd = e.roundStart.round
            for lo, hi in BANDS:
                if rnd == max(lo, 1):
                    alive_at[(lo, hi)] = sum(1 for i in alive if team.get(i) == side)
        elif k == "dragonSplit":
            s = e.dragonSplit
            team[s.childId] = "A" if str(s.team) == "a" else "B"
            alive.add(s.childId)
            if team[s.childId] == side and band(rnd):
                out[band(rnd)]["splits"] += 1
        elif k == "dragonAction":
            actor = e.dragonAction.id
        elif k == "dragonDeath":
            i = e.dragonDeath.id
            alive.discard(i)
            if team.get(i) != side or i <= 1 or not band(rnd):
                continue
            why = str(e.dragonDeath.reason)
            kind = "head-on" if why == "hitHeadToHead" else ("into a body" if why == "hitOtherBody" else "kelp/self/none")
            out[band(rnd)][kind] += 1
        elif k == "pearlEaten" if hasattr(e, "pearlEaten") else False:
            pass
    return out, alive_at, str(r.result.winner).lower() == side.lower()


def main():
    mp = sys.argv[1]
    names = [x.strip() for x in sys.argv[2].split(",") if x.strip()]
    lo = sys.argv[3]
    cap = int(sys.argv[4]) if len(sys.argv) > 4 else 20
    groups = {}
    from lab.api import Client
    from lab.diagnose import CACHE, TEAM_ID
    c = Client()
    jobs = []
    for b in c.get("/battles?limit=200"):
        if not b.get("ranked") or b.get("outcome") == "live" or b["at"][:19] < lo:
            continue
        d = c.get(f"/battles/{b['id']}")
        us = "A" if d["match"]["teamAId"] == TEAM_ID else "B"
        jobs += [(CACHE / f"{g['id']}.replay", us) for g in d.get("games", []) if g.get("mapName") == mp and (CACHE / f"{g['id']}.replay").is_file()]
    groups["us"] = jobs[:cap]
    db = sqlite3.connect(f"file:{DATA / 'scout.db'}?mode=ro", uri=True)
    cols = [r[1] for r in db.execute("pragma table_info(games)")]
    mapcol = "map" if "map" in cols else ("map_name" if "map_name" in cols else None)
    for nm in names:
        row = db.execute("SELECT id FROM teams WHERE name = ?", (nm,)).fetchone()
        if not row or not mapcol:
            continue
        js = []
        for gid, ta in db.execute(f"SELECT id, team_a FROM games WHERE ranked = 1 AND at >= ? AND {mapcol} = ? AND (team_a = ? OR team_b = ?) ORDER BY at DESC",
                                  (lo, mp, row[0], row[0])):
            p = DATA / "replays" / f"{gid}.replay"
            if p.is_file():
                js.append((p, "A" if ta == row[0] else "B"))
            if len(js) >= cap:
                break
        groups[nm] = js
    for nm, js in groups.items():
        tot = collections.defaultdict(collections.Counter)
        alive = collections.defaultdict(list)
        n = won = 0
        for p, s in js:
            try:
                out, al, w = one(p, s)
            except Exception:
                continue
            n += 1
            won += w
            for bnd, cnt in out.items():
                tot[bnd].update(cnt)
            for bnd, v in al.items():
                alive[bnd].append(v)
        if not n:
            print(f"{nm}: no {mp} games")
            continue
        print(f"{nm[:18]:18s} {n} {mp} games, won {won}")
        for bnd in BANDS:
            cnt = tot[bnd]
            al = alive.get(bnd, [])
            print(f"   r{bnd[0]:3d}-{bnd[1] - 1:3d}: alive at start {statistics.median(al) if al else float('nan'):5.1f} ({len(al)} games) | splits {cnt['splits'] / n:5.1f}"
                  f" | deaths kelp/self/none {cnt['kelp/self/none'] / n:5.1f}, into a body {cnt['into a body'] / n:5.1f}, head-on {cnt['head-on'] / n:5.1f}")


if __name__ == "__main__":
    main()
