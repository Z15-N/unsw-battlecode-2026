"""SPSA tuning of the bot's constants (Ben, Oct 11: "find the best algorithm we can use"; the method chess engines tune
hand-written evaluation constants with, on noisy win rates).

    python -m lab.spsa <base candidate folder> <spec.json> [--iters 40] [--pairs 22] [--jobs 6]

spec.json: {"name": "queen_endgame", "params": [{"name": "QTRAP_PEN", "decl": "constexpr double QTRAP_PEN = {v};",
            "match": "constexpr double QTRAP_PEN = ", "value": 80, "min": 20, "max": 200, "c": 20, "int": false}, ...]}
"match" must find exactly one line of main.cpp that starts the declaration; the whole statement up to ';' is replaced.

Each iteration k: delta in {-1, +1}^d; theta+/- = theta +/- c_k * delta (clipped; c_k = c / (k+1)^0.101 per parameter);
build both bots from the base, play `--pairs` (map, seed) pairs head to head on all current maps (both sides each);
r = score(theta+) - 0.5; theta += a_k * r / (c_k * delta) * c^2 * STEP (a_k = a / (A + k + 1)^0.602, step scaled per
parameter by its c). State (theta, history) goes to data/spsa_<name>.json after every iteration and resumes from it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import random
import re
import shutil
import sys

from . import arena
from .common import DATA, ROOT

WORK = DATA / "spsa_bots"
A_GAIN, A_STAB, ALPHA, GAMMA = 1.0, 5.0, 0.602, 0.101
# Step scale: an update is a_k * r * c * STEP in units of the parameter (r = theta+'s score - 0.5). With STEP 10 a typical
# r of +-0.05 moves a parameter ~0.17 c at k = 0. (Oct 11: the first run had / 10: 0.03 on QTRAP_PEN's c = 20, ~100x too small.)
STEP = 10.0


def write_bot(base: pathlib.Path, dest: pathlib.Path, params: list[dict], theta: list[float]) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(base, dest, ignore=shutil.ignore_patterns(".unswbc-build", "__pycache__"))
    src = (dest / "main.cpp").read_text(encoding="utf-8")
    for prm, v in zip(params, theta):
        val = str(int(round(v))) if prm.get("int") else f"{v:.4f}"
        i = src.find(prm["match"])
        assert i >= 0 and src.count(prm["match"]) == 1, f"{prm['name']}: declaration not found once"
        j = src.index(";", i)
        src = src[:i] + prm["decl"].replace("{v}", val).rstrip(";") + src[j:]
    (dest / "main.cpp").write_text(src, encoding="utf-8", newline="\n")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="lab.spsa")
    p.add_argument("base")
    p.add_argument("spec")
    p.add_argument("--iters", type=int, default=40)
    p.add_argument("--pairs", type=int, default=22)
    p.add_argument("--jobs", type=int, default=6)  # Ben's laptop (12 threads) stays usable
    p.add_argument("--maps", default="current")
    args = p.parse_args(argv)
    spec = json.loads(pathlib.Path(args.spec).read_text())
    params = spec["params"]
    state_path = DATA / f"spsa_{spec['name']}.json"
    state = json.loads(state_path.read_text()) if state_path.is_file() else \
        {"name": spec["name"], "base": args.base, "theta": [float(x["value"]) for x in params], "k": 0, "history": []}
    maps = arena.expand_maps(args.maps)
    rng = random.Random(state["k"] * 7919 + 17)
    base = pathlib.Path(args.base).resolve()
    WORK.mkdir(parents=True, exist_ok=True)
    plus_dir, minus_dir = WORK / f"{spec['name']}_plus", WORK / f"{spec['name']}_minus"
    print(f"SPSA {spec['name']}: {len(params)} params from {base.name}, resuming at iteration {state['k']}", flush=True)
    for _ in range(args.iters):
        k = state["k"]
        delta = [rng.choice((-1, 1)) for _ in params]
        ck = [x["c"] / (k + 1) ** GAMMA for x in params]
        clip = lambda i, v: min(max(v, params[i]["min"]), params[i]["max"])
        th = state["theta"]
        plus = [clip(i, th[i] + ck[i] * delta[i]) for i in range(len(params))]
        minus = [clip(i, th[i] - ck[i] * delta[i]) for i in range(len(params))]
        write_bot(base, plus_dir, params, plus)
        write_bot(base, minus_dir, params, minus)
        batch = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + f"-spsa{k}"
        work = []
        for _ in range(args.pairs):
            mp, seed = rng.choice(maps), rng.getrandbits(64)
            work += [(batch, mp, seed, str(plus_dir), str(minus_dir)), (batch, mp, seed, str(minus_dir), str(plus_dir))]
        results = arena.execute(work, args.jobs, quiet=True)
        scores = [s for s in (arena.score_of(r, str(plus_dir)) for r in results if "crash" not in r) if s is not None]
        r = (sum(scores) / len(scores) - 0.5) if scores else 0.0
        ak = A_GAIN / (A_STAB + k + 1) ** ALPHA
        new = [clip(i, th[i] + ak * r * params[i]["c"] ** 2 / (ck[i] * delta[i]) * STEP) for i in range(len(params))]
        state["theta"] = new
        state["k"] = k + 1
        state["history"].append({"k": k, "at": dt.datetime.now().isoformat(timespec="seconds"), "games": len(scores),
                                 "plus_score": round(r + 0.5, 4), "theta": [round(v, 3) for v in new]})
        state_path.write_text(json.dumps(state, indent=1))
        print(f"iter {k}: {len(scores)} games, theta+ scored {r + 0.5:.3f} -> " +
              ", ".join(f"{x['name']}={v:.2f}" for x, v in zip(params, new)), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
