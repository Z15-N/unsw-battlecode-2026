"""Check the tracker against round blocks recorded from real local games.

    python -m lab.test_track            (run from tools/)
"""

from __future__ import annotations

import collections
import pickle
import sys

from .common import DATA
from .track import track


def sections(block: str) -> dict:
    lines = [l.strip() for l in block.strip().splitlines()]
    out = {"header": [], "tiles": [], "bodies": [], "edges": []}
    def is_tile(line: str) -> bool:
        parts = line.split()
        return len(parts) == 4 and all(p.lstrip("-").isdigit() for p in parts)

    i = 0
    while not is_tile(lines[i]):
        out["header"].append(lines[i])
        i += 1
    out["tiles"] = lines[i:i + 49]
    i += 49
    n = int(lines[i].split()[1])
    out["bodies"] = sorted(lines[i + 1:i + 1 + n])
    out["edges"] = lines[i + 1 + n:]
    return out


def compare(name: str) -> bool:
    truth = pickle.load(open(DATA / "fixtures" / f"{name}.blocks.pkl", "rb"))
    rounds = {d: [b.decode() for b in bl if not b.startswith(b"ID ")] for d, bl in truth.items()}
    seen = collections.Counter()
    bad = collections.Counter()
    example = {}
    total = 0
    for turn in track(DATA / "fixtures" / f"{name}.replay").run():
        k = seen[turn.id]
        seen[turn.id] += 1
        real = rounds[turn.id][k]
        mine = turn.block()
        total += 1
        a, b = sections(real), sections(mine)
        for part in a:
            if a[part] != b[part]:
                bad[part] += 1
                example.setdefault(part, (turn.round, turn.id, a[part], b[part]))
    missing = sum(len(v) for v in rounds.values()) - total
    ok = not bad and missing == 0
    print(f"{name}: {total} turns compared, mismatches {dict(bad) or 'none'}, untracked turns {missing}")
    for part, (rnd, did, x, y) in example.items():
        diff = [(p, q) for p, q in zip(x, y) if p != q][:5]
        print(f"  first {part} mismatch: round {rnd} dragon {did}: {diff or (len(x), len(y))}")
    return ok


if __name__ == "__main__":
    names = sys.argv[1:] or ["portals_v23_v19", "default_v23_v19"]
    sys.exit(0 if all([compare(n) for n in names]) else 1)
