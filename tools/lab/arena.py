"""Many sandboxed games in parallel, results in data/arena.db.

    python -m lab.arena bot_a bot_b [--maps pool] [--seeds 4] [--jobs 10]

Every (map, seed) pair is played twice with the sides swapped, so neither bot
gains from moving first. Prints per-map and overall scores with a 95% interval
and the Elo gap that score implies.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import pathlib
import random
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool

from .common import DATA, ROOT

DB_PATH = DATA / "arena.db"
POOL = ["schooltime", "portals", "slithery_fight", "queen_of_spades", "default", "trophy", "dilemma",
        "autarky", "devil", "trauma"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, batch TEXT, map TEXT, seed TEXT,
    bot_a TEXT, bot_b TEXT, hash_a TEXT, hash_b TEXT, winner TEXT, rounds INTEGER,
    end_reason INTEGER, queen_a INTEGER, queen_b INTEGER, longest_a INTEGER, longest_b INTEGER,
    total_a INTEGER, total_b INTEGER, deaths TEXT, p99_a INTEGER, p99_b INTEGER,
    max_a INTEGER, max_b INTEGER, errors TEXT, seconds REAL
);
CREATE INDEX IF NOT EXISTS games_bots ON games (bot_a, bot_b);
"""


def connect() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=120)
    db.executescript(SCHEMA)
    return db


def source_hash(bot: str) -> str:
    """What the bot is: its source files, so renamed copies compare equal."""
    path = pathlib.Path(bot)
    h = hashlib.sha256()
    files = [path] if path.is_file() else sorted(
        p for p in path.rglob("*") if p.is_file() and p.suffix in (".cpp", ".hpp", ".h", ".c", ".cc", ".py", ".wasm")
        and not any(part.startswith(".") for part in p.relative_to(path).parts))
    for f in files:
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def expand_maps(spec: str) -> list[str]:
    """'pool' (the old 10 ladder maps), 'swapped', 'unseen' (the 7 Oct 2 ladder maps), 'new' (the 14 Oct 10 maps), 'current'
    (all 31 server maps), 'gen', 'all', or a comma list."""
    gen = sorted(str(p) for p in (DATA / "maps_gen").glob("*.map"))
    # The server lists either team first, so in half the ladder games dragon 0 (a queen) is team B's.
    # data/maps_swapped holds the pool maps with the teams swapped (Oct 2: v24's queen logic broke on exactly those).
    swapped = sorted(str(p) for p in (DATA / "maps_swapped").glob("*.map"))
    # The 7 maps added to the ranked pool on Oct 2, with swapped twins. Our bots have no data for them on purpose:
    # the qualifier plays unseen maps, and these are real organiser maps we have never tuned on.
    unseen = sorted(str(p) for p in (DATA / "maps_unseen").glob("*.map"))
    # The 14 ladder maps that appeared after the Oct 9 close (server /maps text, Oct 10), with swapped twins.
    new = sorted(str(p) for p in (DATA / "maps_new").glob("*.map"))
    if "+" in spec:                                   # union, e.g. 'unseen+gen'
        return [m for part in spec.split("+") for m in expand_maps(part)]
    if spec == "unseen":
        return unseen
    if spec == "pool":
        return list(POOL)
    if spec == "swapped":
        return swapped
    if spec == "gen":
        return gen
    if spec == "new":
        return new
    if spec == "current":                             # every server map (31) from both sides
        return list(POOL) + swapped + unseen + new
    if spec == "all":
        return list(POOL) + swapped + unseen + gen
    return spec.split(",")


def map_path(name: str) -> pathlib.Path:
    p = pathlib.Path(name)
    if p.is_file():
        return p
    return ROOT / "maps" / f"{name}.map"


def _play(job: tuple) -> dict:
    sys.setrecursionlimit(10000)
    from .localrun import play
    batch, mp, seed, a, b = job
    started = time.monotonic()
    for attempt in range(3):          # a sandbox that fails to boot is the harness, not the bot: retry
        try:
            m = play(map_path(mp), a, b, seed=seed)
            break
        except Exception as error:
            if attempt == 2 or "failed to start" not in repr(error):
                return {"batch": batch, "map": mp, "seed": seed, "a": a, "b": b, "crash": repr(error)[:500],
                        "seconds": time.monotonic() - started}
            time.sleep(2)
    pts = m.points

    def pct(team, q):
        v = pts.get(team) or [0]
        return v[min(len(v) - 1, int(len(v) * q))]

    return {"batch": batch, "map": mp, "seed": seed, "a": a, "b": b, "winner": m.winner, "rounds": m.rounds,
            "end_reason": m.end_reason, "queen": m.queen, "longest": m.longest, "total": m.total,
            "deaths": m.deaths, "p99": (pct("A", 0.99), pct("B", 0.99)),
            "max": (pct("A", 1.0), pct("B", 1.0)), "errors": m.errors[:20], "seconds": m.seconds}


def prebuild(bots: list[str]) -> None:
    from .localrun import resolve
    for bot in set(bots):
        resolve(bot)


def run(bot_x: str, bot_y: str, maps: list[str], seeds: int, jobs: int, base_seed: int | None = None,
        quiet: bool = False) -> list[dict]:
    rng = random.Random(base_seed)
    batch = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{rng.randrange(1 << 16):04x}"
    work = []
    for mp in maps:
        for _ in range(seeds):
            seed = rng.getrandbits(64)
            work.append((batch, mp, seed, bot_x, bot_y))
            work.append((batch, mp, seed, bot_y, bot_x))
    results = execute(work, jobs, quiet)
    if not quiet:
        report(results, bot_x, bot_y)
    return results


def execute(work: list[tuple], jobs: int, quiet: bool = False) -> list[dict]:
    """Play (batch, map, seed, bot_a, bot_b) jobs on one process pool, any mix of bots."""
    bots = {w[3] for w in work} | {w[4] for w in work}
    prebuild(sorted(bots))
    hashes = {bot: source_hash(bot) for bot in bots}
    db = connect()
    results = []
    started = time.monotonic()
    pending = list(work)
    for restart in range(4):        # a worker dying (Windows IPC handles under load) breaks the pool: replay what's left
        try:
            with ProcessPoolExecutor(jobs) as pool:
                futures = {pool.submit(_play, job): job for job in pending}
                for fut in as_completed(futures):
                    r = fut.result()
                    pending.remove(futures[fut])
                    results.append(r)
                    _record(db, r, hashes, quiet, len(results), len(work), started)
            break
        except BrokenProcessPool:
            if restart == 3:
                raise
            print(f"\n  process pool broke; replaying {len(pending)} unfinished games", flush=True)
            time.sleep(5)
    if not quiet:
        print()
    return results


def _record(db, r: dict, hashes: dict, quiet: bool, i: int, total: int, started: float) -> None:
    """Store one finished game in arena.db and show progress."""
    if "crash" not in r:
        db.execute("""INSERT INTO games (at, batch, map, seed, bot_a, bot_b, hash_a, hash_b, winner,
            rounds, end_reason, queen_a, queen_b, longest_a, longest_b, total_a, total_b, deaths,
            p99_a, p99_b, max_a, max_b, errors, seconds) VALUES
            (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (dt.datetime.now().isoformat(timespec="seconds"), r["batch"], r["map"], f"{r['seed']:016x}",
                    r["a"], r["b"], hashes[r["a"]], hashes[r["b"]], r["winner"], r["rounds"],
                    r["end_reason"], *r["queen"], *r["longest"], *r["total"], json.dumps(r["deaths"]),
                    *r["p99"], *r["max"], json.dumps(r["errors"]), r["seconds"]))
        db.commit()
    if not quiet:
        elapsed = time.monotonic() - started
        print(f"\r  {i}/{total} games  {elapsed:.0f}s  eta {elapsed / i * (total - i):.0f}s ", end="", flush=True)


def score_of(r: dict, bot: str) -> float | None:
    if "crash" in r:
        return None
    side = "A" if r["a"] == bot else "B"
    return 0.5 if r["winner"] is None else float(r["winner"] == side)


def interval(scores: list[float]) -> tuple[float, float, float]:
    n = len(scores)
    if not n:
        return 0.5, 0.0, 1.0
    mean = sum(scores) / n
    var = sum((s - mean) ** 2 for s in scores) / max(n - 1, 1)
    half = 1.96 * math.sqrt(var / n) if n > 1 else 0.5
    return mean, max(0.0, mean - half), min(1.0, mean + half)


def elo(p: float) -> float:
    p = min(max(p, 1e-3), 1 - 1e-3)
    return -400 * math.log10(1 / p - 1)


def report(results: list[dict], bot_x: str, bot_y: str) -> dict:
    by_map: dict[str, list[float]] = {}
    for r in results:
        s = score_of(r, bot_x)
        if s is not None:
            by_map.setdefault(pathlib.Path(r["map"]).stem, []).append(s)
    crashes = sum("crash" in r for r in results)
    name_x, name_y = pathlib.Path(bot_x).name, pathlib.Path(bot_y).name
    print(f"{name_x} vs {name_y}: score of {name_x}")
    allscores = []
    for mp, s in sorted(by_map.items()):
        mean, lo, hi = interval(s)
        allscores += s
        print(f"  {mp:16} {mean:5.2f}  [{lo:.2f}, {hi:.2f}]  n={len(s)}")
    mean, lo, hi = interval(allscores)
    print(f"  {'overall':16} {mean:5.2f}  [{lo:.2f}, {hi:.2f}]  n={len(allscores)}  "
          f"elo {elo(mean):+.0f} [{elo(lo):+.0f}, {elo(hi):+.0f}]" + (f"  crashes {crashes}" if crashes else ""))
    worst = {}
    for r in results:
        if "crash" in r:
            continue
        for side, bot in (("A", r["a"]), ("B", r["b"])):
            k = 0 if side == "A" else 1
            worst[bot] = max(worst.get(bot, 0), r["max"][k])
    for bot, pts in worst.items():
        print(f"  max CPU points/turn {pathlib.Path(bot).name}: {pts / 1e6:.1f}M (limit 100M)")
    return {"score": mean, "lo": lo, "hi": hi, "n": len(allscores)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="lab.arena")
    p.add_argument("bot_a")
    p.add_argument("bot_b")
    p.add_argument("--maps", default="pool", help="'pool', 'gen', 'all', or comma-separated names/paths")
    p.add_argument("--seeds", type=int, default=2, help="seeds per map; each is played both ways")
    p.add_argument("--jobs", type=int, default=max(1, min(6, (os.cpu_count() or 2) - 2)))  # Ben's laptop stays usable
    p.add_argument("--seed", type=int, default=None)
    args = p.parse_args(argv)
    maps = expand_maps(args.maps)
    run(args.bot_a, args.bot_b, maps, args.seeds, args.jobs, args.seed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
