"""Who is better than us at what: one skill at a time, on the same maps (Ben, Oct 2).

    python -m lab.skills                     top 10 + teams within 50 Elo of us, 40 recent games each; us: newest 200
    python -m lab.skills --strategy          also rewrite the skills block in STRATEGY.md (the refresh does this)
    python -m lab.skills --since 2026-10-02T06:40 --games 60

Ben (Oct 2): re-check who to learn what from after every replay analysis; we may overtake a team at a skill.
Every run is compared with the previous one (data/skills/latest.json) and the changes are listed: a team that is
no longer better than us at a skill stops being copied there. History: data/skills/history.jsonl.

Ben's rule: learn a skill only from the teams that are measurably better than us at it; a team that is
weaker at a skill teaches nothing there, even if it is strong at others.

Per game, for one side (its own dragons only), from the replay:
  eat100 / eat200   pearls eaten by rounds 100 / 200 (a turn where the tail stays put; a sprint that eats is missed)
  eat_rate          pearls eaten per dragon-turn, rounds 0-200 (farming per dragon: pathing to food)
  army100           dragons alive at round 100
  nav_deaths        deaths into kelp, into itself or with no valid action, per 100 dragon-turns (lower is better)
  body_deaths       deaths into another dragon's body, per 100 dragon-turns (lower is better)
  rams              head-on trades this side started, per game
  rammed            head-on trades the other side started on us, per game (lower is better)
  queen_round       round the queen died (500 if she lived)
  longest_500       longest dragon at the end, games that reached round 500 (exact: the replay's result)
  win               1 win, 0.5 draw, 0 loss

Comparison: each team game is compared with OUR mean on the same map (our newest --ours ladder games),
so map mix does not bias it. diff = mean(team value - our map mean); a team is "better" when the diff is in its
favour by more than 2 standard errors. The opponent mix still differs (they play other teams than we do).
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import math
import sqlite3
import sys
from concurrent.futures import ProcessPoolExecutor

from .common import DATA, load_replay

TEAM_ID = 135
NEW_MAPS = {"Stripes", "Tower Defense", "Islands", "Around UNSW", "weakhold", "Maze", "Australia"}   # ranked pool from Oct 2
OUT = DATA / "skills"
LOWER_BETTER = {"nav_deaths", "body_deaths", "rammed"}
METRICS = ["eat100", "eat200", "eat_rate", "army100", "coverage200", "nav_deaths", "body_deaths", "rams", "rammed", "queen_round",
           "longest_500", "win"]
NAMES = {"eat100": "pearls eaten by r100", "eat200": "pearls eaten by r200", "eat_rate": "pearls per dragon-turn r0-200",
         "army100": "dragons alive r100", "coverage200": "map covered by r200 (% of tiles our heads stood on)", "nav_deaths": "kelp/self/no-action deaths per 100 dragon-turns",
         "body_deaths": "deaths into a body per 100 dragon-turns", "rams": "head-on trades started per game",
         "rammed": "head-on trades suffered per game", "queen_round": "queen death round (500 = lived)",
         "longest_500": "longest dragon at round 500", "win": "win rate"}


def game_metrics(job) -> dict | None:
    path, side = job
    try:
        r = load_replay(path)
    except Exception:
        return None
    team = {i: ("A" if l.split()[1] == "0" else "B") for i, l in enumerate(x for x in r.map.splitlines() if x.startswith("DRAGON "))}
    queen = 0 if team.get(0) == side else 1
    # Ben (Oct 3): "calc's worms swarm us all over the map while we take a little portion": coverage is a skill too
    W, H = (int(v) for v in r.map.splitlines()[0].split()[1:3])
    visited = set()
    alive = collections.Counter(team.values())
    tails, actor, dying = {}, None, []
    eaten = eaten200 = 0
    out = {}
    turns200 = turns = 0
    nav = body = rams = rammed = 0
    qd = None
    rnd = 0
    for e in r.events:
        k = e.which()
        if k == "roundStart":
            rnd = e.roundStart.round
            if rnd == 100:
                out["eat100"] = eaten
                out["army100"] = alive[side]
            if rnd == 200:
                eaten200 = eaten
        elif k == "dragonSplit":
            s = e.dragonSplit
            t = "A" if str(s.team) == "a" else "B"
            team[s.childId] = t
            alive[t] += 1
            tails[s.childId] = (s.childBody[-1].x, s.childBody[-1].y)
            tails[s.parentId] = (s.parentBody[-1].x, s.parentBody[-1].y)
        elif k == "dragonUpdate":
            u = e.dragonUpdate
            here = (u.tail.x, u.tail.y)
            if tails.get(u.id) == here and team.get(u.id) == side:
                eaten += 1
            if team.get(u.id) == side and rnd < 200:
                visited.add((u.head.x, u.head.y))
            tails[u.id] = here
        elif k == "dragonAction":
            actor, dying = e.dragonAction.id, []
            if team.get(actor) == side:
                turns += 1
                if rnd < 200:
                    turns200 += 1
        elif k == "dragonDeath":
            d = e.dragonDeath
            t = team.get(d.id)
            alive[t] -= 1
            reason = str(d.reason)
            if t == side:
                if reason in ("hitWall", "hitSelf", "noValidAction"):
                    nav += 1
                elif reason == "hitOtherBody":
                    body += 1
                if d.id == queen and qd is None:
                    qd = rnd
            if reason == "hitHeadToHead":
                dying.append(d.id)
                if len(dying) == 2 and actor in dying:
                    other = dying[0] if dying[1] == actor else dying[1]
                    if team.get(actor) == side and team.get(other) != side:
                        rams += 1
                    elif team.get(actor) != side and team.get(other) == side:
                        rammed += 1
    if rnd < 100:
        return None
    res = r.result
    mine = res.teamA if side == "A" else res.teamB
    out["eat200"] = eaten200 if rnd >= 200 else None
    out["coverage200"] = 100.0 * len(visited) / (W * H) if rnd >= 200 else None
    out["eat_rate"] = (eaten200 if rnd >= 200 else eaten) / max(1, turns200)
    out["nav_deaths"] = 100 * nav / max(1, turns)
    out["body_deaths"] = 100 * body / max(1, turns)
    out["rams"] = rams
    out["rammed"] = rammed
    out["queen_round"] = qd if qd is not None else 500
    out["longest_500"] = mine.longestDragon if rnd >= 499 and mine.dragonCount > 0 else None
    which = res.which() if hasattr(res, "which") else None
    winner = str(res.winner) if which == "winner" else None
    out["win"] = 0.5 if winner is None else (1.0 if winner.upper().startswith(side) else 0.0)
    return out


def team_games(db, team_id: int, n: int, since: str) -> list[tuple]:
    rows = db.execute("""SELECT id, map, CASE WHEN team_a = ? THEN 'A' ELSE 'B' END FROM games
                         WHERE (team_a = ? OR team_b = ?) AND has_replay = 1 AND at >= ? ORDER BY at DESC""",
                      (team_id, team_id, team_id, since)).fetchall()
    return [r for r in rows if (DATA / "replays" / f"{r[0]}.replay").is_file()][:n]


def our_games(since: str) -> list[tuple]:
    """Our ladder games, newest first: (id, map, side, at)."""
    from .api import Client
    from .diagnose import our_games as fetch
    games = fetch(Client(), 300, since)
    games.sort(key=lambda g: g["at"], reverse=True)
    return [(g["id"], g["map"], g["us"], g["at"]) for g in games]


def compare(team_rows: list[tuple], ours_by_map: dict) -> dict:
    """team_rows: [(map, metrics)]. Returns {metric: (diff, se, n)} against our per-map means."""
    out = {}
    for m in METRICS:
        resid, ourvar = [], []
        for mp, x in team_rows:
            v = x.get(m)
            ref = [y[m] for y in ours_by_map.get(mp, []) if y.get(m) is not None]
            if v is None or len(ref) < 2:
                continue
            mu = sum(ref) / len(ref)
            var = sum((a - mu) ** 2 for a in ref) / (len(ref) - 1)
            resid.append(v - mu)
            ourvar.append(var / len(ref))
        n = len(resid)
        if n < 4:
            continue
        mean = sum(resid) / n
        sd = math.sqrt(sum((a - mean) ** 2 for a in resid) / (n - 1))
        se = math.sqrt(sd * sd / n + sum(ourvar) / n)   # + our map means' own error (conservative: taken as fully shared)
        out[m] = (mean, se, n)
    return out


STATES = {"better": "better than us", "even": "no measurable difference", "worse": "worse than us"}
# Counts of a behaviour or overall results, not skills: shown in the report, never a reason to copy a team.
NOT_SKILLS = {"rams", "win"}
BEGIN, END = "<!-- skills:begin (lab.skills --strategy writes this block) -->", "<!-- skills:end -->"


def state_of(m: str, d: float, se: float) -> str:
    if m in LOWER_BETTER:
        d = -d
    return "better" if d > 2 * se else "worse" if d < -2 * se else "even"


def changes(prev: dict | None, status: dict) -> list[str]:
    """What moved since the previous run: teams that stopped or started being better than us, per skill."""
    if not prev:
        return []
    out = []
    for m, teams in status.items():
        if m in NOT_SKILLS:
            continue
        old = prev.get("status", {}).get(m, {})
        for name, (st, d, se, n) in teams.items():
            if name not in old or old[name][0] == st:
                continue
            was = old[name][0]
            if st == "worse":
                out.append(f"we are now better than {name} at {NAMES[m]} ({d:+.2f}; was {STATES[was]})")
            elif st == "better":
                out.append(f"{name} is now better than us at {NAMES[m]} ({d:+.2f}; was {STATES[was]})")
            elif was == "better":
                out.append(f"{name} is no longer measurably better at {NAMES[m]} ({d:+.2f}): stop copying it there")
            else:
                out.append(f"{name} is no longer measurably worse at {NAMES[m]} ({d:+.2f})")
    gone = {n for t in prev.get("status", {}).values() for n in t} - {n for t in status.values() for n in t}
    out += [f"{name} is no longer in the comparison (left the top 10 / +-50 group)" for name in sorted(gone)]
    return out


def strategy_block(info: str, status: dict, our_mean: dict, moved: list[str], prev_at: str | None) -> str:
    lines = [BEGIN, info, "", "| skill | us | learn it from (better than us on the same maps, strongest evidence first) |",
             "|---|---|---|"]
    for m in METRICS:
        if m in NOT_SKILLS:
            continue
        better = sorted(((abs(d) / max(se, 1e-9), name, d) for name, (st, d, se, n) in status.get(m, {}).items()
                         if st == "better"), reverse=True)
        who = ", ".join(f"{name} {d:+.2f}" for _, name, d in better[:6])
        if len(better) > 6:
            who += f" and {len(better) - 6} more"
        um = our_mean.get(m)
        shown = f"{um:.2f}" if um is not None else "-"
        lines.append(f"| {NAMES[m]} | {shown} | {who or '**nobody better: copy no one here**'} |")
    lines += ["", f"Changes since the previous run ({prev_at}):" if prev_at else "First run: no previous run to compare with."]
    if moved:
        lines += [f"- {c}" for c in moved]
    elif prev_at:
        lines.append("- none")
    lines.append(END)
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="lab.skills")
    p.add_argument("--ours", type=int, default=200, help="our newest ladder games (whichever version was live)")
    p.add_argument("--since", default="", help="only our games from this time (UTC)")
    p.add_argument("--their-since", default="2026-10-01T12:00", help="their games from (after the queen rule)")
    p.add_argument("--games", type=int, default=40, help="recent games per team")
    p.add_argument("--near", type=int, default=50)
    p.add_argument("--jobs", type=int, default=8)
    p.add_argument("--strategy", action="store_true", help="rewrite the skills block in STRATEGY.md")
    p.add_argument("--maps", default="", help="only these maps (comma-separated names, or 'new' for the 7 maps added Oct 2); "
                                              "a separate report (data/skills/<tag>_latest.md), never the STRATEGY block")
    p.add_argument("--no-rescout", action="store_true", help="never re-scout, even if our rating moved")
    args = p.parse_args(argv)
    # Ben (Oct 3): "check our elo every time you analyse: we are 1927 and you're still fighting 17xx". The +-50 group comes
    # from the newest ladder snapshot; re-scout (fresh snapshot, the new group's games and replays) when it is older than
    # 2 hours or our team rating has moved more than 25 since.
    try:
        from .api import Client
        live = Client().get("/team")["team"]["elo"]
        dbw = sqlite3.connect(DATA / "scout.db", timeout=900)
        snap0 = dbw.execute("SELECT MAX(at) FROM ladder").fetchone()[0]
        then = dbw.execute("SELECT elo FROM ladder WHERE at = ? AND team_id = ?", (snap0, TEAM_ID)).fetchone()
        dbw.close()
        age_h = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(snap0)).total_seconds() / 3600 if snap0 else 99
        print(f"our team rating now {live}; ladder snapshot {snap0} had {then[0] if then else '?'} ({age_h:.1f} h old)", flush=True)
        if not args.no_rescout and (age_h > 2 or then is None or abs(live - then[0]) > 25):
            from . import scout
            print("re-scouting the top 10 and the teams within", args.near, "of our rating now", flush=True)
            scout.refresh(10, 4.5, quiet=True, near=args.near)
    except Exception as e:  # never block the analysis on the ladder API
        print("rating check failed:", e, flush=True)
    db = sqlite3.connect(f"file:{DATA / 'scout.db'}?mode=ro", uri=True, timeout=60)
    names = dict(db.execute("SELECT id, name FROM teams").fetchall())
    snap = db.execute("SELECT MAX(at) FROM ladder").fetchone()[0]
    top = [r[0] for r in db.execute("SELECT team_id FROM ladder WHERE at = ? AND rank IS NOT NULL ORDER BY rank LIMIT 10", (snap,))]
    me = db.execute("SELECT elo FROM ladder WHERE at = ? AND team_id = ?", (snap, TEAM_ID)).fetchone()
    near = [r[0] for r in db.execute("SELECT team_id FROM ladder WHERE at = ? AND team_id != ? AND ABS(elo - ?) <= ? ORDER BY elo DESC",
                                     (snap, TEAM_ID, me[0] if me else 0, args.near))] if me else []
    teams = top + [t for t in near if t not in top]
    # A team that was better than us at any skill in one of the last 3 runs stays in, even if our rating moved it out of
    # the +-50 window: leaving the window says nothing about the skill (Ben: re-check who to learn from).
    only = set()
    if args.maps:
        only = NEW_MAPS if args.maps == "new" else {x.strip() for x in args.maps.split(",")}
        args.strategy = False
    tag = ("maps-" + ("new" if args.maps == "new" else "custom") + "_") if only else ""
    prev_path = OUT / f"{tag}latest.json"
    prev = json.loads(prev_path.read_text(encoding="utf-8")) if prev_path.is_file() else None
    kept = []
    ids = {n: i for i, n in names.items()}
    recent = sorted(p for p in OUT.glob("2*.json"))[-3:]          # the last 3 saved runs (full comparison only)
    for path in recent:
        for m, rows in json.loads(path.read_text(encoding="utf-8")).get("status", {}).items():
            if m in NOT_SKILLS:
                continue
            for name, (st, *_rest) in rows.items():
                tid = ids.get(name)
                if st == "better" and tid is not None and tid not in teams and tid not in kept:
                    kept.append(tid)
    teams += kept
    ours = [g for g in our_games(args.since) if not only or g[1] in only][: args.ours]
    jobs = [(DATA / "replays" / f"{gid}.replay", side) for gid, _, side, _ in ours]
    plan = {tid: [r for r in team_games(db, tid, 10 ** 6 if only else args.games, args.their_since) if not only or r[1] in only][: args.games]
            for tid in teams}
    for tid, rows in plan.items():
        jobs += [(DATA / "replays" / f"{gid}.replay", side) for gid, _, side in rows]
    span = f"{min(g[3] for g in ours)[:16]} to {max(g[3] for g in ours)[:16]} UTC" if ours else "none"
    print(f"ladder snapshot {snap}; us {len(ours)} games ({span}); {len(teams)} teams "
          f"({len(top)} top, {len(near)} within {args.near}, {len(kept)} kept: teachers in the last 3 runs); {len(jobs)} replays", flush=True)
    with ProcessPoolExecutor(args.jobs) as pool:
        metrics = dict(zip(jobs, pool.map(game_metrics, jobs, chunksize=4)))
    ours_by_map = collections.defaultdict(list)
    for gid, mp, side, _ in ours:
        x = metrics.get((DATA / "replays" / f"{gid}.replay", side))
        if x:
            ours_by_map[mp].append(x)
    our_mean = {}
    for m in METRICS:
        vals = [x[m] for xs in ours_by_map.values() for x in xs if x.get(m) is not None]
        our_mean[m] = sum(vals) / len(vals) if vals else None
    table = {}
    for tid, rows in plan.items():
        tr = [(mp, metrics.get((DATA / "replays" / f"{gid}.replay", side))) for gid, mp, side in rows]
        tr = [(mp, x) for mp, x in tr if x]
        table[tid] = (len(tr), compare(tr, ours_by_map))
    status = {m: {} for m in METRICS}
    for t in teams:
        for m, (d, se, n) in table[t][1].items():
            status[m][names.get(t, str(t))] = [state_of(m, d, se), round(d, 4), round(se, 4), n]
    now = dt.datetime.now().isoformat(timespec="minutes")
    info = (f"Run {now}: ladder snapshot {snap}; us = our newest {sum(len(v) for v in ours_by_map.values())} ladder games "
            f"({span}, {len(ours_by_map)} maps); them = the top 10 and the teams within {args.near} Elo, up to {args.games} "
            f"games each since {args.their_since}, plus {len(kept)} teachers of the last 3 runs that left those groups. "
            f"Better = ahead of us by > 2 standard errors on the same maps.")
    moved = changes(prev, status)
    lines = [f"# Skills {now}", "", info, "",
             "Each cell: their value minus ours on the same maps (n games). **Bold** = better than us by > 2 standard errors.", ""]
    head = "| skill | US | " + " | ".join(names.get(t, str(t))[:14] + (" (kept)" if t in kept else " (near)" if t not in top else "") for t in teams) + " |"
    lines += [head, "|" + "---|" * (len(teams) + 2)]
    for m in METRICS:
        cells = []
        for t in teams:
            cmp = table[t][1]
            if m not in cmp:
                cells.append("-")
                continue
            d, se, n = cmp[m]
            cells.append(("**%+.2f**" if state_of(m, d, se) == "better" else "%+.2f") % d + f" ({n})")
        um = our_mean[m]
        shown = f"{um:.2f}" if um is not None else "-"
        lines.append(f"| {NAMES[m]} | {shown} | " + " | ".join(cells) + " |")
    lines += ["", "## Who to learn each skill from (better than us by > 2 SE, strongest evidence first)", ""]
    for m in METRICS:
        ts = sorted(((abs(d) / max(se, 1e-9), name, d) for name, (st, d, se, n) in status[m].items() if st == "better"),
                    reverse=True)
        note = " (a count, not a skill: never a reason to copy)" if m in NOT_SKILLS else ""
        lines.append(f"- **{NAMES[m]}**{note}: " + (", ".join(f"{name} ({d:+.2f})" for _, name, d in ts) if ts else "nobody measurably better"))
    lines += ["", f"## Changes since the previous run ({prev['at'] if prev else '-'})", ""]
    if moved:
        lines += [f"- {c}" for c in moved]
    else:
        lines.append("- none" if prev else "- first run")
    text = "\n".join(lines) + "\n"
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    (OUT / f"{tag}{stamp}.md").write_text(text, encoding="utf-8")
    (OUT / f"{tag}latest.md").write_text(text, encoding="utf-8")
    record = {"at": now, "snapshot": snap, "us": {"games": len(ours), "span": span}, "our_mean": our_mean, "status": status}
    (OUT / (f"{tag}{stamp}.json" if tag else f"{stamp}.json")).write_text(json.dumps(record, indent=1), encoding="utf-8")
    prev_path.write_text(json.dumps(record, indent=1), encoding="utf-8")
    with open(OUT / f"{tag}history.jsonl", "a", encoding="utf-8") as h:
        h.write(json.dumps({"at": now, "changes": moved}) + "\n")
    if args.strategy:
        path = DATA.parent / "STRATEGY.md"
        doc = path.read_text(encoding="utf-8")
        block = strategy_block(info, status, our_mean, moved, prev["at"] if prev else None)
        if BEGIN in doc and END in doc:
            doc = doc[: doc.index(BEGIN)] + block + doc[doc.index(END) + len(END):]
            path.write_text(doc, encoding="utf-8")
            print("STRATEGY.md skills block updated")
        else:
            print("STRATEGY.md has no skills block markers; not written")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
