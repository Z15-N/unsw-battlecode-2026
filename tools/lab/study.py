"""How the top teams play, next to how we play: one table per behaviour, from public replays.

    python -m lab.study                      top-10 teams (latest ladder) + our live bot, 8 replays each
    python -m lab.study --teams 314,20 --games 12 --map Trophy

Ben (Oct 2): keep analysing opponents' replays and copy what works. The refresh runs this every
4 hours and keeps each report in data/study/<time>.md; the latest is data/study/latest.md.

Per team (averaged over its games, its own dragons only):
  sonar       rays per dragon-turn, rounds 0-100 / 100-300 / 300+
  army        dragons alive and pearls eaten at rounds 50/100/200
  split       mean parent length at a split, share of 4 -> 2+2 splits, splits per dragon-turn
  spacing     mean Manhattan distance from a head to its nearest own head; share of heads with an own head
              within 2 (crowding); share of turns ending next to an enemy head (danger)
  sprints     share of moves with more than one step
  rams        head-on trades started per game, share started by a shorter dragon, share from 2+ tiles away
  endgame     longest own dragon at rounds 300/400/499
  opening     where heads are at round 25, as a share in the map's centre third (per map)
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import sqlite3
import statistics
import sys

from .common import DATA, load_replay
from .track import Tracker

STUDY = DATA / "study"
TEAM_ID = 135


def manhattan(a, b, w, h):
    dx = abs(a[0] - b[0])
    dy = abs(a[1] - b[1])
    return min(dx, w - dx) + min(dy, h - dy)


def study_game(path, side: str) -> dict:
    r = load_replay(path)
    out = collections.defaultdict(list)
    rays = collections.Counter()
    turns = collections.Counter()
    moves = multi = 0
    rams = shorter = far = 0
    splits = []
    eaten = 0
    tails = {}
    actor = None
    dying = []
    lengths = {}
    team = {i: ("A" if l.split()[1] == "0" else "B") for i, l in enumerate(x for x in r.map.splitlines() if x.startswith("DRAGON "))}
    rnd = 0
    for e in r.events:
        k = e.which()
        if k == "roundStart":
            rnd = e.roundStart.round
        elif k == "dragonSplit":
            s = e.dragonSplit
            tm = "A" if str(s.team) == "a" else "B"
            team[s.childId] = tm
            if tm == side:
                splits.append((len(s.parentBody) + len(s.childBody), len(s.childBody)))
            tails[s.childId] = (s.childBody[-1].x, s.childBody[-1].y)
            tails[s.parentId] = (s.parentBody[-1].x, s.parentBody[-1].y)
            lengths[s.childId] = len(s.childBody)
            lengths[s.parentId] = len(s.parentBody)
        elif k == "dragonUpdate":
            u = e.dragonUpdate
            here = (u.tail.x, u.tail.y)
            if tails.get(u.id) == here and team.get(u.id) == side:
                eaten += 1
                if u.id in lengths:
                    lengths[u.id] += 1
            elif tails.get(u.id) == here and u.id in lengths:
                lengths[u.id] += 1
            tails[u.id] = here
        elif k == "dragonAction":
            a = e.dragonAction
            actor, dying = a.id, []
            if team.get(a.id) == side:
                band = 0 if rnd < 100 else 1 if rnd < 300 else 2
                turns[band] += 1
                if a.action.which() == "move":
                    moves += 1
                    if len(a.action.move) > 1:
                        multi += 1
        elif k == "sonarPing":
            if team.get(e.sonarPing.senderId) == side:
                band = 0 if rnd < 100 else 1 if rnd < 300 else 2
                rays[band] += 1
        elif k == "dragonDeath":
            d = e.dragonDeath
            if str(d.reason) == "hitHeadToHead":
                dying.append(d.id)
                if len(dying) == 2 and actor in dying and team.get(actor) == side:
                    rams += 1
                    other = dying[0] if dying[1] == actor else dying[1]
                    la, lo = lengths.get(actor), lengths.get(other)
                    if la and lo and la < lo:
                        shorter += 1
        if k == "roundStart" and rnd in (50, 100, 200):
            out[f"eat{rnd}"].append(eaten)
    return {"rays": rays, "turns": turns, "moves": moves, "multi": multi, "rams": rams, "rams_shorter": shorter,
            "splits": splits, "eat": {k: v[0] for k, v in out.items()}}


def board_facts(path, side: str) -> dict:
    """Facts that need the whole board: spacing, crowding, danger, army size, king curve, opening."""
    r = load_replay(path)
    t = Tracker(r, strict=False)
    w, h = t.w, t.h
    near, crowd, danger, heads_n = [], 0, 0, 0
    army = {}
    longest = {}
    centre = None
    last = -1
    for _ in t.run():
        if t.round == last:
            continue
        last = t.round
        rnd = t.round
        if rnd in (50, 100, 200):
            army[rnd] = sum(1 for d in t.dragons.values() if d.team == side)
        if rnd in (300, 400, 499):
            longest[rnd] = max([len(d.body) for d in t.dragons.values() if d.team == side] or [0])
        if rnd == 25:
            mine = [(d.body[0][0], d.body[0][1]) for d in t.dragons.values() if d.team == side]
            if mine:
                centre = sum(1 for (x, y) in mine if w / 3 <= x < 2 * w / 3 and h / 3 <= y < 2 * h / 3) / len(mine)
        if rnd % 5 or rnd < 20:
            continue
        own = [(d.body[0][0], d.body[0][1]) for d in t.dragons.values() if d.team == side]
        foe = [(d.body[0][0], d.body[0][1]) for d in t.dragons.values() if d.team != side]
        for i, p in enumerate(own):
            others = [manhattan(p, q, w, h) for j, q in enumerate(own) if j != i]
            if others:
                m = min(others)
                near.append(m)
                crowd += m <= 2
            danger += any(manhattan(p, q, w, h) == 1 for q in foe)
            heads_n += 1
    return {"near": statistics.mean(near) if near else 0.0, "crowd": crowd / max(heads_n, 1),
            "danger": danger / max(heads_n, 1), "army": army, "longest": longest, "centre": centre}


def team_rows(db, team_id: int, games: int, map_name: str | None) -> list:
    q = """SELECT id, team_a, team_b, map FROM games WHERE (team_a = ? OR team_b = ?) AND replay_bytes IS NOT NULL"""
    args = [team_id, team_id]
    if map_name:
        q += " AND map = ?"
        args.append(map_name)
    q += " ORDER BY at DESC LIMIT ?"
    args.append(games)
    return db.execute(q, args).fetchall()


def our_rows(games: int, map_name: str | None) -> list:
    """Our live bot's recent ladder games (replays cached by lab.diagnose), as (id, team_a, team_b, map, us)."""
    from .api import Client
    from .diagnose import our_games
    client = Client()
    live = [s for s in client.get("/submissions") if s.get("status") == "active"]
    since = live[0].get("uploadedAt", "") if live else ""
    rows = []
    for g in our_games(client, 40, since):
        if map_name and g["map"] != map_name:
            continue
        a, b = (TEAM_ID, -1) if g["us"] == "A" else (-1, TEAM_ID)
        rows.append((g["id"], a, b, g["map"], TEAM_ID))
    return rows[:games]


def summarise(name: str, rows: list) -> dict:
    acc = collections.defaultdict(list)
    maps_centre = collections.defaultdict(list)
    for gid, a, b, mp, team_id in rows:
        path = DATA / "replays" / f"{gid}.replay"
        if not path.is_file():
            continue
        side = "A" if a == team_id else "B"
        try:
            g = study_game(path, side)
            f = board_facts(path, side)
        except Exception:
            continue
        for band in range(3):
            if g["turns"][band]:
                acc[f"sonar{band}"].append(g["rays"][band] / g["turns"][band])
        if g["moves"]:
            acc["sprints"].append(g["multi"] / g["moves"])
        acc["rams"].append(g["rams"])
        if g["rams"]:
            acc["rams_shorter"].append(g["rams_shorter"] / g["rams"])
        if g["splits"]:
            acc["split_parent"].append(statistics.mean(p for p, c in g["splits"]))
            acc["split_422"].append(sum(1 for p, c in g["splits"] if p == 4 and c == 2) / len(g["splits"]))
        for k, v in g["eat"].items():
            acc[k].append(v)
        acc["near"].append(f["near"])
        acc["crowd"].append(f["crowd"])
        acc["danger"].append(f["danger"])
        for k, v in f["army"].items():
            acc[f"army{k}"].append(v)
        for k, v in f["longest"].items():
            acc[f"long{k}"].append(v)
        if f["centre"] is not None:
            maps_centre[mp].append(f["centre"])
    mean = {k: statistics.mean(v) for k, v in acc.items() if v}
    mean["games"] = len(acc["near"])
    mean["centre"] = {mp: statistics.mean(v) for mp, v in maps_centre.items()}
    return {"name": name, **mean}


COLUMNS = [("games", "games", "{:.0f}"), ("sonar0", "sonar r0-100", "{:.2f}"), ("sonar1", "sonar r100-300", "{:.2f}"),
           ("sonar2", "sonar r300+", "{:.2f}"), ("army50", "army r50", "{:.1f}"), ("army100", "army r100", "{:.1f}"),
           ("army200", "army r200", "{:.1f}"), ("eat50", "eaten r50", "{:.0f}"), ("eat100", "eaten r100", "{:.0f}"),
           ("eat200", "eaten r200", "{:.0f}"), ("split_parent", "split parent len", "{:.2f}"),
           ("split_422", "4->2+2 share", "{:.0%}"), ("near", "nearest own head", "{:.2f}"),
           ("crowd", "own head within 2", "{:.0%}"), ("danger", "next to enemy head", "{:.1%}"),
           ("sprints", "multi-step moves", "{:.1%}"), ("rams", "rams started/game", "{:.1f}"),
           ("rams_shorter", "rams by shorter", "{:.0%}"), ("long300", "longest r300", "{:.1f}"),
           ("long400", "longest r400", "{:.1f}"), ("long499", "longest r499", "{:.1f}")]


def report(rows: list[dict]) -> str:
    out = [f"# Study {dt.datetime.now().isoformat(timespec='minutes')}", "",
           "| metric | " + " | ".join(r["name"][:14] for r in rows) + " |",
           "|---|" + "---|" * len(rows)]
    for key, label, fmt in COLUMNS:
        out.append(f"| {label} | " + " | ".join(fmt.format(r[key]) if key in r else "-" for r in rows) + " |")
    maps = sorted({mp for r in rows for mp in r.get("centre", {})})
    if maps:
        out += ["", "Heads in the centre third at round 25 (openings):", "",
                "| map | " + " | ".join(r["name"][:14] for r in rows) + " |", "|---|" + "---|" * len(rows)]
        for mp in maps:
            out.append(f"| {mp} | " + " | ".join(f"{r['centre'][mp]:.0%}" if mp in r.get("centre", {}) else "-"
                                                for r in rows) + " |")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="lab.study")
    p.add_argument("--teams", default=None, help="comma-separated team ids (default: latest top 10)")
    p.add_argument("--games", type=int, default=8)
    p.add_argument("--map", default=None)
    p.add_argument("--near", type=int, default=50, help="also teams rated within this of us (one combined column)")
    args = p.parse_args(argv)
    db = sqlite3.connect(f"file:{DATA / 'scout.db'}?mode=ro", uri=True, timeout=60)
    names = dict(db.execute("SELECT id, name FROM teams").fetchall())
    if args.teams:
        ids = [int(x) for x in args.teams.split(",")]
    else:
        snap = db.execute("SELECT MAX(at) FROM ladder").fetchone()[0]
        ids = [r[0] for r in db.execute("SELECT team_id FROM ladder WHERE at = ? ORDER BY rank IS NULL, rank, elo DESC LIMIT 10", (snap,))]
    results = []
    # Ben (Oct 2): also the teams rated within 50 of us, the ones we actually meet, as one combined column.
    snap = db.execute("SELECT MAX(at) FROM ladder").fetchone()[0]
    me = db.execute("SELECT elo FROM ladder WHERE at = ? AND team_id = ?", (snap, TEAM_ID)).fetchone()
    if me and not args.teams:
        near = [r[0] for r in db.execute("SELECT team_id FROM ladder WHERE at = ? AND team_id != ? AND ABS(elo - ?) <= ?",
                                         (snap, TEAM_ID, me[0], args.near))]
        rows = []
        for tid in near:
            rows += [(*row, tid) for row in team_rows(db, tid, 2, args.map)]
        if rows:
            results.append(summarise(f"NEAR +-{args.near}", rows))
            print(f"studied {len(near)} teams within {args.near} of us: {results[-1]['games']} games", flush=True)
    for tid in ids + [TEAM_ID]:
        if tid == TEAM_ID:
            rows = our_rows(args.games * 3, args.map)
        else:
            rows = [(*row, tid) for row in team_rows(db, tid, args.games, args.map)]
        if not rows:
            continue
        results.append(summarise(names.get(tid, str(tid)) if tid != TEAM_ID else "US", rows))
        print(f"studied {results[-1]['name']}: {results[-1]['games']} games", flush=True)
    text = report(results)
    STUDY.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    (STUDY / f"{stamp}.md").write_text(text, encoding="utf-8")
    (STUDY / "latest.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
