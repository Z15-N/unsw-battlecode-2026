"""Quick screen: several candidates, one batch each against the champion.

    python -m lab.screen ../candidates/v27a ../candidates/v27b --against ../versions/server/14126_v24_queen

Each candidate plays every pool + generated map once from each side (60 games).
Promising ones (score >= 0.5) go on to the full gate in lab.release.
Results are appended to data/screens.json.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

from . import arena
from .common import DATA

LOG = DATA / "screens.json"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="lab.screen")
    p.add_argument("candidates", nargs="+")
    p.add_argument("--against", required=True)
    p.add_argument("--maps", default="all")
    p.add_argument("--seeds", type=int, default=1)
    p.add_argument("--jobs", type=int, default=11)
    p.add_argument("--seed", type=int, default=7, help="same seeds for every candidate (paired comparison)")
    args = p.parse_args(argv)
    maps = arena.expand_maps(args.maps)
    rows = []
    for cand in args.candidates:
        results = arena.run(cand, args.against, maps, args.seeds, args.jobs, base_seed=args.seed, quiet=True)
        scores = [s for s in (arena.score_of(r, cand) for r in results) if s is not None]
        pool = [arena.score_of(r, cand) for r in results
                if "crash" not in r and not pathlib.Path(r["map"]).stem.startswith("gen_")]
        mean, lo, hi = arena.interval(scores)
        row = {"at": dt.datetime.now().isoformat(timespec="seconds"), "candidate": cand, "against": args.against,
               "games": len(scores), "score": round(mean, 3), "lo": round(lo, 3), "hi": round(hi, 3),
               "pool": round(sum(pool) / max(len(pool), 1), 3), "crashes": sum("crash" in r for r in results)}
        rows.append(row)
        print(f"{pathlib.Path(cand).name:12} score {mean:.3f} [{lo:.3f}, {hi:.3f}] pool {row['pool']:.3f} "
              f"n={len(scores)}", flush=True)
    log = json.loads(LOG.read_text()) if LOG.is_file() else []
    LOG.write_text(json.dumps(log + rows, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
