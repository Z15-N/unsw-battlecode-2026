"""Our place on the ladder, our live bot per map, and why we lose.

    python -m lab.ladder status            rating, rank, per-map table (weakest first), recent battles
    python -m lab.ladder pull [--battles 40]   download our recent games' replays into data/replays
    python -m lab.ladder losses [--hours 6]    per map: how our lost games went (queen fate, eliminations)
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import sys

from .api import Client
from .common import DATA, load_replay
from .scout import REPLAYS, connect

TEAM_ID = 135


def status(client: Client) -> None:
    team = client.get("/team")
    subs = client.get("/submissions")
    live = [s for s in subs if s.get("status") == "active"]
    print(f"rank {team.get('rank')}  peak {team.get('peak')}")
    if not live:
        print("no active submission")
        return
    s = client.get(f"/submissions/{live[0]['id']}")
    print(f"active: {s['name']} (id {s['id']}) rating {s.get('rating')}  record {s['wins']}-{s['draws']}-{s['losses']}")
    rows = sorted((s.get("byMap") or {}).items(), key=lambda kv: kv[1].get("rating") or 0)
    for name, m in rows:
        n = m["wins"] + m["draws"] + m["losses"]
        print(f"  {name:18} rating {m.get('rating')}  {m['wins']}-{m['draws']}-{m['losses']}"
              f"  ({m['wins'] / max(n, 1):.0%})")
    print("recent battles:")
    for b in client.get("/battles?limit=10"):
        print(f"  {b['at'][:16]} vs {b['opponent'][:24]:24} ({b['opponentElo']}) {b['outcome']:5} "
              f"{b['wins']}-{b['losses']}  elo {b.get('eloChange')}")


def pull(client: Client, battles: int) -> int:
    db = connect()
    got = 0
    for b in client.get(f"/battles?limit={battles}"):
        if b.get("outcome") == "live":
            continue
        detail = client.get(f"/battles/{b['id']}")
        m = detail["match"]
        for g in detail.get("games", []):
            if g.get("status") != "completed":
                continue
            row = db.execute("SELECT replay_bytes FROM games WHERE id = ?", (g["id"],)).fetchone()
            if row and row[0]:
                continue
            db.execute("""INSERT OR IGNORE INTO games (id, at, map, ranked, challenge, tournament, status, team_a,
                          team_b, winner, has_replay) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                       (g["id"], b["at"], g.get("mapName"), int(b["ranked"]), 0, 0, "completed", m["teamAId"],
                        m["teamBId"], g.get("winner"), int(bool(g.get("hasReplay")))))
            if g.get("hasReplay"):
                path = REPLAYS / f"{g['id']}.replay"
                REPLAYS.mkdir(parents=True, exist_ok=True)
                if not path.is_file():
                    path.write_bytes(client.replay(g["id"]))
                db.execute("UPDATE games SET replay_bytes = ? WHERE id = ?", (path.stat().st_size, g["id"]))
                got += 1
        db.commit()
    print(f"downloaded {got} replays of our games")
    return got


def losses(hours: float) -> None:
    db = connect()
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).isoformat()
    rows = db.execute("""SELECT id, map, team_a, team_b, winner FROM games
                         WHERE (team_a = ? OR team_b = ?) AND at >= ? AND replay_bytes IS NOT NULL""",
                      (TEAM_ID, TEAM_ID, since)).fetchall()
    per_map = collections.defaultdict(lambda: collections.Counter())
    for gid, mp, a, b, winner in rows:
        us = "A" if a == TEAM_ID else "B"
        won = winner == us.lower()
        c = per_map[mp]
        c["games"] += 1
        c["won"] += won
        try:
            r = load_replay(REPLAYS / f"{gid}.replay")
        except Exception:
            continue
        queens = {0: None, 1: None}
        rnd = 0
        team = {i: ("A" if l.split()[1] == "0" else "B")
                for i, l in enumerate(x for x in r.map.splitlines() if x.startswith("DRAGON "))}
        elim = r.result.endReason == 0 or str(r.result.endReason) == "teamEliminated"
        for e in r.events:
            k = e.which()
            if k == "roundStart":
                rnd = e.roundStart.round
            elif k == "dragonDeath" and e.dragonDeath.id <= 1:
                queens[e.dragonDeath.id] = (rnd, str(e.dragonDeath.reason))
        ours = 0 if team.get(0) == us else 1
        mine, theirs = queens[ours], queens[1 - ours]
        if not won:
            c["lost"] += 1
            c["lost_elim"] += elim
            c["lost_our_queen_dead"] += mine is not None
            c["lost_their_queen_alive"] += theirs is None
            if mine:
                c[f"our_queen:{mine[1]}"] += 1
                c["our_queen_death_round_sum"] += mine[0]
        else:
            c["won_their_queen_dead"] += theirs is not None
            c["won_our_queen_alive"] += mine is None
    for mp, c in sorted(per_map.items(), key=lambda kv: kv[1]["won"] / max(kv[1]["games"], 1)):
        lost = c["lost"]
        causes = {k.split(":")[1]: v for k, v in c.items() if k.startswith("our_queen:")}
        avg = c["our_queen_death_round_sum"] / max(c["lost_our_queen_dead"], 1)
        print(f"{mp:18} {c['won']}/{c['games']} won | losses: eliminated {c['lost_elim']}/{lost}, our queen died "
              f"{c['lost_our_queen_dead']}/{lost} (avg round {avg:.0f}, {causes}), their queen alive "
              f"{c['lost_their_queen_alive']}/{lost}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="lab.ladder")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    pl = sub.add_parser("pull")
    pl.add_argument("--battles", type=int, default=40)
    lo = sub.add_parser("losses")
    lo.add_argument("--hours", type=float, default=6)
    args = p.parse_args(argv)
    client = Client()
    if args.cmd == "status":
        status(client)
    elif args.cmd == "pull":
        pull(client, args.battles)
    else:
        losses(args.hours)
    return 0


if __name__ == "__main__":
    sys.exit(main())
