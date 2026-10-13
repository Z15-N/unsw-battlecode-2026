"""Why the live bot wins and loses: our recent ladder games, one line per game and a summary.

    python -m lab.diagnose                    the active submission's games (newest 40 battles)
    python -m lab.diagnose --since 2026-10-01T22:45 --map Trophy --boards 200,250

Per game: how it ended, army size and pearls eaten (us/them) at rounds 50/100/150/200/300,
and head-on collisions split by who moved into whom. Replays are cached in data/replays
(no database, so it runs while the 4-hourly refresh holds scout.db).
What to look for (STRATEGY.md 1c): the pearl race from round 50, and who starts the trades.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys

from .api import Client
from .common import DATA, load_replay
from .track import Tracker

TEAM_ID = 135
MARKS = (50, 100, 150, 200, 300)
CACHE = DATA / "replays"


def our_games(client: Client, battles: int, since: str) -> list[dict]:
    games = []
    for b in client.get(f"/battles?limit={battles}"):
        if b.get("outcome") == "live" or b["at"] < since:
            continue
        detail = client.get(f"/battles/{b['id']}")
        m = detail["match"]
        for g in detail.get("games", []):
            if g.get("status") != "completed" or not g.get("hasReplay"):
                continue
            path = CACHE / f"{g['id']}.replay"
            if not path.is_file():
                CACHE.mkdir(parents=True, exist_ok=True)
                path.write_bytes(client.replay(g["id"]))
            us = "A" if m["teamAId"] == TEAM_ID else "B"
            games.append({"id": g["id"], "map": g.get("mapName"), "us": us, "won": g.get("winner") == us.lower(),
                          "opponent": b["opponent"], "elo": b["opponentElo"], "at": b["at"]})
    return games


def analyse(game: dict) -> dict:
    r = load_replay(CACHE / f"{game['id']}.replay")
    U = game["us"]
    T = "B" if U == "A" else "A"
    team = {i: ("A" if l.split()[1] == "0" else "B")
            for i, l in enumerate(x for x in r.map.splitlines() if x.startswith("DRAGON "))}
    alive = collections.Counter(team.values())
    eaten = collections.Counter()
    tail = {}
    rams = collections.Counter()
    deaths = collections.Counter()
    snaps = {}
    actor, dying = None, []
    mi, rnd = 0, 0
    for e in r.events:
        k = e.which()
        if k == "roundStart":
            rnd = e.roundStart.round
            while mi < len(MARKS) and rnd >= MARKS[mi]:
                snaps[MARKS[mi]] = (alive[U], alive[T], eaten[U], eaten[T])
                mi += 1
        elif k == "dragonSplit":
            s = e.dragonSplit
            t = "A" if str(s.team) == "a" else "B"
            team[s.childId] = t
            alive[t] += 1
            tail[s.childId] = (s.childBody[-1].x, s.childBody[-1].y)
            tail[s.parentId] = (s.parentBody[-1].x, s.parentBody[-1].y)
        elif k == "dragonUpdate":
            u = e.dragonUpdate
            here = (u.tail.x, u.tail.y)
            if tail.get(u.id) == here:              # the tail stayed: it ate
                eaten[team.get(u.id)] += 1
            tail[u.id] = here
        elif k == "dragonAction":
            actor, dying = e.dragonAction.id, []
        elif k == "dragonDeath":
            d = e.dragonDeath
            t = team.get(d.id)
            alive[t] -= 1
            if t == U:
                deaths[str(d.reason)] += 1
            if str(d.reason) == "hitHeadToHead":
                dying.append(d.id)
                if len(dying) == 2 and actor in dying:
                    rams["we rammed" if team.get(actor) == U else "they rammed"] += 1
    res = r.result
    mine, theirs = (res.teamA, res.teamB) if U == "A" else (res.teamB, res.teamA)
    end = "eliminated us" if mine.dragonCount == 0 else "we eliminated" if theirs.dragonCount == 0 else "round 500"
    return {**game, "end": end, "rounds": rnd, "snaps": snaps, "rams": dict(rams), "deaths": dict(deaths),
            "longest": (mine.longestDragon, theirs.longestDragon), "total": (mine.totalLength, theirs.totalLength)}


def board(game: dict, rounds: list[int]) -> None:
    r = load_replay(CACHE / f"{game['id']}.replay")
    t = Tracker(r, strict=False)
    done = set()
    for _ in t.run():
        if t.round in rounds and t.round not in done:
            done.add(t.round)
            grid = [["." for _ in range(t.w)] for _ in range(t.h)]
            for (x, y) in t.pearls:
                grid[y][x] = "*"
            for d in t.dragons.values():
                for k, (x, y, f) in enumerate(d.body):
                    mine = d.team == game["us"]
                    grid[y][x] = ("@" if mine else "E") if k == 0 else ("o" if mine else "e")
            ours = sum(1 for d in t.dragons.values() if d.team == game["us"])
            print(f"round {t.round}: us @o {ours}, them Ee {len(t.dragons) - ours}, pearls {len(t.pearls)}")
            print("\n".join("".join(row) for row in grid) + "\n")
        if len(done) == len(rounds):
            break


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="lab.diagnose")
    p.add_argument("--battles", type=int, default=40)
    p.add_argument("--since", default=None, help="UTC ISO time; default: when the active submission went live")
    p.add_argument("--map", default=None)
    p.add_argument("--boards", default=None, help="rounds to draw for the first matching game, e.g. 200,250")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    client = Client()
    since = args.since
    if since is None:
        live = [s for s in client.get("/submissions") if s.get("status") == "active"]
        since = live[0].get("uploadedAt", "") if live else ""
    games = [g for g in our_games(client, args.battles, since) if not args.map or g["map"] == args.map]
    rows = [analyse(g) for g in games]
    if args.json:
        print(json.dumps(rows))
        return 0
    for g in rows:
        s = g["snaps"]
        line = " ".join(f"r{m} {v[0]}/{v[1]} eat {v[2]}/{v[3]}" for m, v in sorted(s.items()))
        print(f"{g['map'][:14]:14} {'W' if g['won'] else 'L'} {g['opponent'][:14]:14} ({g['elo']}) {g['end']:13} "
              f"| {line} | rams us/them {g['rams'].get('we rammed', 0)}/{g['rams'].get('they rammed', 0)}")
    by = collections.defaultdict(lambda: collections.Counter())
    for g in rows:
        c = by[g["map"]]
        c["games"] += 1
        c["won"] += g["won"]
        c["eliminated"] += g["end"] == "eliminated us"
        c["we_rammed"] += g["rams"].get("we rammed", 0)
        c["they_rammed"] += g["rams"].get("they rammed", 0)
    print("\nper map: won/games, times we were eliminated, head-on trades started (us/them) per game")
    for mp, c in sorted(by.items(), key=lambda kv: kv[1]["won"] / kv[1]["games"]):
        print(f"  {mp:18} {c['won']}/{c['games']}  eliminated {c['eliminated']}  rams {c['we_rammed'] / c['games']:.1f}/"
              f"{c['they_rammed'] / c['games']:.1f}")
    if args.boards and rows:
        board(rows[0], [int(x) for x in args.boards.split(",")])
    return 0


if __name__ == "__main__":
    sys.exit(main())
