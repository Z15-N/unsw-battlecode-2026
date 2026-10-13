"""Internal tournament on unseen maps (Ben, Oct 3: "build a tournament like the Sprint: our bots fight each other on unseen
maps, the first place gets published"). See TOURNAMENT.md.

    python -m lab.tournament data/tournaments/T1.json            run it, write standings
    python -m lab.tournament data/tournaments/T1.json --publish  ... and release the winner if it beats the champion

Config (JSON):
  {"name": "T1",
   "entrants": [
     {"name": "v67", "dir": "../candidates/v67", "champion": true},
     {"name": "v71", "dir": "../candidates/v71"},
     {"name": "v67-noBaby", "base": "../candidates/v67", "flags": {"BABY_HUNT": false}}
   ],
   "maps": "unseen",          arena map spec (default: the 7 new ladder maps + swapped twins)
   "fresh": 12,               plus this many freshly generated maps, never seen by any bot or by earlier tournaments
   "seeds": 1, "jobs": 11}

Every pair plays every map from both sides. Win 1, draw 0.5. Ranked by score; ties broken head to head.
Output: data/tournaments/<name>_<stamp>.md / .json (standings, head-to-head matrix, per-map wins).
"""
from __future__ import annotations

import argparse
import datetime as dt
import itertools
import json
import pathlib
import random
import re
import shutil
import subprocess
import sys

from . import arena
from .common import DATA

OUT = DATA / "tournaments"
BUDGET_MIN = 50
BUILD = pathlib.Path(__file__).resolve().parents[2] / "candidates" / "tournament"


def build_entrant(t_name: str, e: dict) -> str:
    """An entrant is a folder, or a base folder with `constexpr bool FLAG = ...;` switches flipped."""
    if "dir" in e:
        return e["dir"]
    base = pathlib.Path(e["base"])
    dst = BUILD / t_name / e["name"]
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(base, dst)
    main = dst / "main.cpp"
    src = main.read_text(encoding="utf-8")
    for flag, value in e.get("flags", {}).items():
        val = ("true" if value else "false") if isinstance(value, bool) else str(value)
        pat = re.compile(rf"(constexpr\s+(?:bool|int|double)\s+{re.escape(flag)}\s*=\s*)([^;]+);")
        if not pat.search(src):
            raise SystemExit(f"{e['name']}: no constexpr {flag} in {base}")
        src = pat.sub(lambda m: m.group(1) + val + ";", src, count=1)
    main.write_text(src, encoding="utf-8")
    return str(dst)


def fresh_maps(t_name: str, count: int, seed: int) -> list[str]:
    from .mapgen import generate
    out = DATA / "maps_tournament" / t_name
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(count):
        name, text = generate(seed, i)
        p = out / f"{name}.map"
        p.write_text(text)
        paths.append(str(p))
    return paths


def prior_games(work: list[tuple]) -> list[dict]:
    """Results of work items (batch, map, seed, bot_a, bot_b) this exact code already played (arena.db, by hash)."""
    hashes = {}
    for _, _, _, a, b in work:
        for bot in (a, b):
            if bot not in hashes:
                hashes[bot] = arena.source_hash(bot)
    db = arena.connect()
    out, seen = [], set()
    for _, mp, seed, a, b in work:
        key = (mp, seed, a, b)
        if key in seen:
            continue
        seen.add(key)
        row = db.execute("""SELECT winner FROM games WHERE map = ? AND seed = ? AND hash_a = ? AND hash_b = ?
                            ORDER BY at DESC LIMIT 1""", (mp, f"{seed:016x}", hashes[a], hashes[b])).fetchone()
        if row is not None:
            out.append({"map": mp, "seed": seed, "a": a, "b": b, "winner": row[0], "reused": True})
    return out


def standings(names: list[str], dirs: dict, results: list[dict]) -> dict:
    pts = {n: 0.0 for n in names}
    games = {n: 0 for n in names}
    h2h = {a: {b: [0.0, 0] for b in names} for a in names}
    by_dir = {v: k for k, v in dirs.items()}
    per_map = {n: {} for n in names}
    crashes = 0
    for r in results:
        if "crash" in r:
            crashes += 1
            continue
        a, b = by_dir[r["a"]], by_dir[r["b"]]
        sa = 0.5 if r["winner"] is None else float(r["winner"] == "A")
        mp = pathlib.Path(r["map"]).stem
        for me, them, s in ((a, b, sa), (b, a, 1 - sa)):
            pts[me] += s
            games[me] += 1
            h2h[me][them][0] += s
            h2h[me][them][1] += 1
            pm = per_map[me].setdefault(mp, [0.0, 0])
            pm[0] += s
            pm[1] += 1

    def key(n):
        return pts[n] / max(1, games[n])
    order = sorted(names, key=key, reverse=True)
    # head-to-head breaks exact ties between neighbours
    for i in range(len(order) - 1):
        x, y = order[i], order[i + 1]
        if abs(key(x) - key(y)) < 1e-9 and h2h[y][x][0] > h2h[x][y][0]:
            order[i], order[i + 1] = y, x
    return {"order": order, "points": pts, "games": games, "h2h": h2h, "per_map": per_map, "crashes": crashes}


def report(cfg: dict, st: dict, maps: list[str], stamp: str) -> str:
    names = st["order"]
    champ = next((e["name"] for e in cfg["entrants"] if e.get("champion")), None)
    lines = [f"# Tournament {cfg['name']} ({stamp})", "",
             f"{len(names)} entrants, round robin, both sides of {len(maps)} maps x {cfg.get('seeds', 1)} seed(s); "
             f"crashes {st['crashes']}. Maps: {cfg.get('maps', 'unseen')} + {cfg.get('fresh', 0)} fresh generated.", "",
             "| place | entrant | score | points / games |", "|---|---|---|---|"]
    for i, n in enumerate(names, 1):
        tag = " (champion)" if n == champ else ""
        lines.append(f"| {i} | {n}{tag} | {st['points'][n] / max(1, st['games'][n]):.3f} | {st['points'][n]:.1f} / {st['games'][n]} |")
    lines += ["", "Head to head (row's score against column):", "",
              "| | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for a in names:
        cells = []
        for b in names:
            s, g = st["h2h"][a][b]
            cells.append("—" if a == b else f"{s / max(1, g):.2f}")
        lines.append(f"| {a} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="lab.tournament")
    p.add_argument("config")
    p.add_argument("--publish", action="store_true", help="release the winner if it is not the champion and beat it head to head")
    p.add_argument("--force", action="store_true", help="run even if over the time budget")
    p.add_argument("--fresh", action="store_true", help="replay every game (don't reuse games this code already played)")
    args = p.parse_args(argv)
    cfg = json.loads(pathlib.Path(args.config).read_text(encoding="utf-8"))
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    t_name = cfg["name"]
    dirs = {e["name"]: build_entrant(t_name, e) for e in cfg["entrants"]}
    names = list(dirs)
    maps = arena.expand_maps(cfg.get("maps", "unseen"))
    if cfg.get("fresh", 0):
        maps += fresh_maps(t_name, cfg["fresh"], cfg.get("map_seed", int(dt.datetime.now().strftime("%m%d%H%M"))))
    seeds = cfg.get("seeds", 1)
    rng = random.Random(cfg.get("base_seed", 7))
    batch = f"T-{t_name}-{stamp}"
    work = []
    for mp in maps:
        for _ in range(seeds):
            seed = rng.getrandbits(64)
            for x, y in itertools.combinations(names, 2):
                work.append((batch, mp, seed, dirs[x], dirs[y]))
                work.append((batch, mp, seed, dirs[y], dirs[x]))
    # Ben (Oct 3): a version is built and published within 0-1:30 h, because the other teams improve fast. Measured on
    # 11 workers: T2 220 games in 17.8 min (12.3 a minute), T3 ~20 min; estimated at 10 a minute. The tournament gets
    # at most BUDGET_MIN.
    # Games this exact code already played on this map and seed (arena.db, by source hash) are reused, so adding an
    # entrant to a finished field (Ben, Oct 3: "let v67 compete as well") only plays its own games.
    reused = [] if args.fresh else prior_games(work)
    done = {(r["map"], r["seed"], r["a"], r["b"]) for r in reused}
    todo = [w for w in work if (w[1], w[2], w[3], w[4]) not in done]
    est = len(todo) / (10.0 * cfg.get("jobs", 11) / 11)
    print(f"tournament {t_name}: {len(names)} entrants, {len(maps)} maps, {len(work)} games ({len(reused)} reused, "
          f"{len(todo)} to play), ~{est:.0f} min", flush=True)
    if est > cfg.get("budget_min", BUDGET_MIN) and not args.force:
        raise SystemExit(f"~{est:.0f} min is over the {cfg.get('budget_min', BUDGET_MIN)} min budget: fewer entrants or maps (or --force)")
    results = reused + (arena.execute(todo, cfg.get("jobs", 11)) if todo else [])
    st = standings(names, dirs, results)
    OUT.mkdir(parents=True, exist_ok=True)
    md = report(cfg, st, maps, stamp)
    (OUT / f"{t_name}_{stamp}.md").write_text(md, encoding="utf-8")
    (OUT / f"{t_name}_{stamp}.json").write_text(json.dumps({"config": cfg, "maps": maps, "dirs": dirs, **st}, indent=1), encoding="utf-8")
    (OUT / "latest.md").write_text(md, encoding="utf-8")
    print(md)
    winner = st["order"][0]
    champ = next((e["name"] for e in cfg["entrants"] if e.get("champion")), None)
    if args.publish:
        if champ is None or winner == champ:
            print(f"winner {winner} is the champion: nothing to publish")
            print("RELEASE NONE: the champion won", flush=True)
            return 0
        # First place is published. If it fails its release gate, the next entrant placed above the champion is tried
        # (Oct 3: T4's winner, the INTEL removal, failed its gate 0.48; 2nd place was Ben's gate guards).
        for place, name in enumerate(st["order"], 1):
            if name == champ:
                break
            s, g = st["h2h"][name][champ]
            if s / max(1, g) < 0.5:
                print(f"place {place} {name} scored {s / max(1, g):.2f} against the champion head to head: not published")
                continue
            desc = (f"Tournament {t_name} place {place} ({stamp}): {st['points'][name] / max(1, st['games'][name]):.3f} over "
                    f"{st['games'][name]} games on {len(maps)} unseen maps, {s / max(1, g):.2f} vs the champion {champ}. "
                    + cfg.get("desc", {}).get(name, ""))
            print("publishing", name, flush=True)
            # short gate (the tournament already measured it): crashes, CPU, the clone smoke test, the 1-hour rule
            rc = subprocess.call([sys.executable, "-m", "lab.release", dirs[name], "--name",
                                  f"{name} ({t_name} {'winner' if place == 1 else f'place {place}'})",
                                  "--desc", desc[:900], "--maps", "unseen", "--batches", "1"])
            log = json.loads((DATA / "releases.json").read_text(encoding="utf-8"))
            last = log[-1] if log else {}
            # Always say how the release ended (Oct 3: T4's winner failed its gate silently and a waiter sat on this
            # log for an hour).
            gt = last.get("gate") or {}
            print(f"RELEASE {'UPLOADED' if last.get('uploaded') else 'NOT UPLOADED'}: {name}, gate {gt.get('verdict')} "
                  f"{gt.get('score')} [{gt.get('lo')}, {gt.get('hi')}] over {gt.get('games')} games, rc {rc}", flush=True)
            if rc == 0 and last.get("uploaded") and last.get("submission_id") and last.get("champion_id"):
                # WORKFLOW 6.2: every release is judged by the paired duel straight away
                print(f"duel: {last['submission_id']} vs {last['champion_id']}", flush=True)
                rc = subprocess.call([sys.executable, "-m", "lab.duel", "--candidate", str(last["submission_id"]),
                                      "--champion", str(last["champion_id"]), "--dev"])
                print(f"DUEL DONE rc {rc}", flush=True)
                return rc
        print("RELEASE NONE: no entrant above the champion passed its gate", flush=True)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
