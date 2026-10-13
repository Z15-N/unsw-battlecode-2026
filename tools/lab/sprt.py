"""Sequential probability ratio test for a candidate against the champion (Ben, Oct 11: "find the best algorithm we can
use" -> SPRT for decisions, as chess engines test: it stops as soon as the evidence is clear instead of a fixed 124-248).

    python -m lab.sprt ../candidates/v055 --against ../candidates/v054 [--maps current] [--elo0 0] [--elo1 25]

Unit = a pair: one (map, seed) played from both sides, which cancels side and map luck. Rounds of `--pairs` pairs
(2 games each) run on the process pool; after each round the GSPRT log-likelihood ratio of the pair scores is updated
(normal approximation: LLR = n * (s1 - s0) * (2*mean - s0 - s1) / (2*var), s = expected pair score under each Elo).
Stop when LLR >= log((1-beta)/alpha) (H1: the candidate is better by elo1), LLR <= log(beta/(1-alpha)) (H0: not better
than elo0), or at --max games (inconclusive). Results append to data/sprt.json.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import pathlib
import random
import sys

from . import arena
from .common import DATA

LOG = DATA / "sprt.json"


def expected(elo: float) -> float:
    return 1.0 / (1.0 + 10 ** (-elo / 400.0))


# Ben, Oct 11 ~00:20: H1 lowered from +40 to +20 Elo (score 0.529) so small real gains can ship; the cap is 1600 games.
# Under +40 nine candidates scored 0.50-0.53 and none could pass (v056 itself was 0.527, shipped at the cap).
VAR_FLOOR = 0.05   # pair-score variance floor: early rounds of near-identical pairs would otherwise swing the LLR
MIN_ROUNDS = 2     # no verdict before this many rounds
# Simulated (400 runs each, rounds of 22 pairs, cap 800 games): elo0 0 / elo1 40 accepts H1 3% at a true +0, 84% at +40,
# 100% at +60, 0% at -40, after 181-445 games on average. Deciding after every pair with no floor accepted 13% at +0.


def llr(pairs: list[float], s0: float, s1: float) -> float:
    n = len(pairs)
    if n < 2:
        return 0.0
    mean = sum(pairs) / n
    var = max(sum((x - mean) ** 2 for x in pairs) / (n - 1), VAR_FLOOR)
    return n * (s1 - s0) * (2 * mean - s0 - s1) / (2 * var)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="lab.sprt")
    p.add_argument("candidate")
    p.add_argument("--against", required=True)
    p.add_argument("--maps", default="current")
    p.add_argument("--elo0", type=float, default=0.0)
    p.add_argument("--elo1", type=float, default=20.0)
    p.add_argument("--alpha", type=float, default=0.05)
    p.add_argument("--beta", type=float, default=0.05)
    p.add_argument("--max", type=int, default=1600, help="games")
    p.add_argument("--pairs", type=int, default=22, help="pairs per round (2 games each)")
    p.add_argument("--jobs", type=int, default=6)  # Ben's laptop (12 threads) stays usable
    p.add_argument("--seed", type=int, default=None)
    args = p.parse_args(argv)
    maps = arena.expand_maps(args.maps)
    rng = random.Random(args.seed)
    s0, s1 = expected(args.elo0), expected(args.elo1)
    lower, upper = math.log(args.beta / (1 - args.alpha)), math.log((1 - args.beta) / args.alpha)
    batch = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-sprt"
    pair_scores: list[float] = []
    games = crashes = 0
    verdict = "inconclusive"
    value = 0.0
    print(f"SPRT {pathlib.Path(args.candidate).name} vs {pathlib.Path(args.against).name}: H0 elo {args.elo0:+g} "
          f"(score {s0:.3f}) / H1 elo {args.elo1:+g} ({s1:.3f}), bounds [{lower:.2f}, {upper:.2f}], max {args.max} games, "
          f"{len(maps)} map files", flush=True)
    rounds = 0
    while games < args.max:
        work = []
        for _ in range(args.pairs):
            mp, seed = rng.choice(maps), rng.getrandbits(64)
            work.append((batch, mp, seed, args.candidate, args.against))
            work.append((batch, mp, seed, args.against, args.candidate))
        results = arena.execute(work, args.jobs, quiet=True)
        by_pair: dict[tuple, list[float]] = {}
        for r in results:
            if "crash" in r:
                crashes += 1
                continue
            s = arena.score_of(r, args.candidate)
            if s is not None:
                by_pair.setdefault((r["map"], r["seed"]), []).append(s)
        for scores in by_pair.values():
            if len(scores) == 2:
                pair_scores.append(sum(scores) / 2)
        games += len(results)
        rounds += 1
        value = llr(pair_scores, s0, s1)
        mean = sum(pair_scores) / max(len(pair_scores), 1)
        print(f"  {games:4d} games ({len(pair_scores)} pairs): score {mean:.3f}, LLR {value:+.2f} [{lower:.2f}, {upper:.2f}]"
              + (f", crashes {crashes}" if crashes else ""), flush=True)
        if rounds < MIN_ROUNDS:
            continue
        if value >= upper:
            verdict = "H1 accepted (better)"
            break
        if value <= lower:
            verdict = "H0 accepted (not better)"
            break
    mean = sum(pair_scores) / max(len(pair_scores), 1)
    print(f"verdict: {verdict} after {games} games, score {mean:.3f}, LLR {value:+.2f}", flush=True)
    row = {"at": dt.datetime.now().isoformat(timespec="seconds"), "candidate": args.candidate, "against": args.against,
           "maps": args.maps, "elo0": args.elo0, "elo1": args.elo1, "games": games, "pairs": len(pair_scores),
           "score": round(mean, 4), "llr": round(value, 3), "verdict": verdict, "crashes": crashes, "batch": batch}
    log = json.loads(LOG.read_text()) if LOG.is_file() else []
    LOG.write_text(json.dumps(log + [row], indent=1))
    return 0 if verdict.startswith("H1") else 1


if __name__ == "__main__":
    sys.exit(main())
