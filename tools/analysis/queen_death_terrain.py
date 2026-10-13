"""Where does our queen die, by terrain? (pick between algorithm queue #10 Tarjan-topology queen and the others; Ben, Oct 11.)
For our ranked games (replays in data/replays named by the API since --since, played by submission --sub), per queen death
and over all her turns: the share of her head tiles that are one-wide corridor tiles (analysis/map_topology.corridors),
dead-end tiles (dead_ends), and her free sides (open neighbours without a body) at her last turn.
    python analysis/queen_death_terrain.py --since 2026-10-11T04:05 --sub 21987,22006
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lab.api import Client  # noqa: E402
from lab.common import load_replay  # noqa: E402
from lab.diagnose import CACHE, TEAM_ID  # noqa: E402
from lab.track import Tracker  # noqa: E402
from map_topology import corridors, dead_ends  # noqa: E402

_topo = {}


def topo(m):
    if m.name not in _topo:
        _topo[m.name] = (corridors(m), dead_ends(m))
    return _topo[m.name]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--since", default="2026-10-11T04:05")
    p.add_argument("--sub", default="21987,22006")
    a = p.parse_args()
    subs = set(a.sub.split(","))
    c = Client()
    tot = collections.Counter()
    for b in c.get("/battles?limit=50"):
        if not b.get("ranked") or b["at"][:19] < a.since or b.get("outcome") not in ("win", "loss", "draw"):
            continue
        d = c.get(f"/battles/{b['id']}")
        side = "A" if d["match"]["teamAId"] == TEAM_ID else "B"
        for g in d.get("games", []):
            path = CACHE / f"{g['id']}.replay"
            if not path.is_file():
                continue
            r = load_replay(path)
            if str(r.botA if side == "A" else r.botB) not in subs:
                continue
            t = Tracker(r, strict=False)
            co, de = topo(t.map)
            q = next(i for i in (0, 1) if t.dragons[i].team == side)
            last, free = None, 0
            tot["games"] += 1
            for turn in t.run():
                if q not in t.dragons:
                    kind = "own" if turn.id == q else "enemy"
                    tot[f"{kind} deaths"] += 1
                    if last:
                        tot[f"{kind}: in corridor"] += last in co
                        tot[f"{kind}: corridor >= 4"] += last in co and co[last][0] >= 4
                        tot[f"{kind}: in dead end"] += last in de
                        tot[f"{kind}: free sides <= 1"] += free <= 1
                    break
                if turn.id != q:
                    continue
                qb = t.dragons[q].body
                last = (qb[0][0], qb[0][1])
                occ = {(x, y) for dd in t.dragons.values() for x, y, _ in dd.body}
                free = sum(1 for dr in "NESW" if (n := t.map.step(*last, dr)) is not None and n not in occ)
                tot["turns"] += 1
                tot["turns in corridor"] += last in co
                tot["turns corridor >= 4"] += last in co and co[last][0] >= 4
                tot["turns in dead end"] += last in de
    for k in sorted(tot):
        print(f"{k:28s} {tot[k]}")
    n = max(1, tot["turns"])
    print(f"share of her turns: corridor {tot['turns in corridor'] / n:.1%} (>= 4 long {tot['turns corridor >= 4'] / n:.1%}), dead end {tot['turns in dead end'] / n:.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
