"""How much of what our feeders drop ends up in the dragon they feed? (Pre-check for algorithm queue #5, death-drop layout.)
docs/death.md: a dying dragon drops a pearl on every second segment (ceil(L/2)). For our ranked games (API battles since
--since, played by --sub), from the round our side's first sacrifice-like death happens near our longest dragon (an own
-move death of one of our dragons within 4 of the longest's head, r >= 300) to r500: pearls our dead dragons dropped within
6 of the fed dragon, how many of those tiles the fed dragon's head entered while the pearl lay there (eaten), how many an
enemy took, and how many were left at the end; plus the fed dragon's length gain and its turns spent.
    python analysis/feed_efficiency.py --since 2026-10-11T06:54 --sub 22006
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lab.api import Client  # noqa: E402
from lab.common import load_replay  # noqa: E402
from lab.diagnose import CACHE, TEAM_ID  # noqa: E402
from lab.track import Tracker  # noqa: E402

LATE = 430  # ~ the endgame feeding (consStart = 470 - (W+H)/2 on the 32-64 maps)


def game(path, side):
    t = Tracker(load_replay(path), strict=False)
    W, H = t.w, t.h
    md = lambda a, b: min(abs(a[0] - b[0]), W - abs(a[0] - b[0])) + min(abs(a[1] - b[1]), H - abs(a[1] - b[1]))
    c = collections.Counter()
    drops = {}            # tile -> round dropped (our feeders' pearls near the fed dragon)
    prev = {}
    fed = None
    fed_len0 = None
    for turn in t.run():
        ours = {i: d for i, d in t.dragons.items() if d.team == side}
        if turn.round >= 300 and ours:
            # the dragon being fed: our queen while she lives (trickle and endgame feeding both go to her), else the longest
            qid = next((i for i in (0, 1) if i in ours), None)
            pick = ours[qid] if qid is not None else max(ours.values(), key=lambda d: len(d.body))
            if fed is None or fed not in t.dragons or (qid is not None and fed != qid):
                fed = pick.id
                fed_len0 = len(pick.body)
        # deaths since the previous turn: dragons in prev but gone now
        for i, (team, body) in list(prev.items()):
            if i not in t.dragons and team == side and fed is not None and fed in t.dragons and i != fed:
                fh = tuple(t.dragons[fed].body[0][:2])
                if md(tuple(body[0]), fh) <= 6:
                    c["feeder deaths"] += 1
                    for k, seg in enumerate(body):
                        if k % 2 == 0:
                            dd = md(tuple(seg), fh)
                            band = "1-2" if dd <= 2 else "3-4" if dd <= 4 else "5-6" if dd <= 6 else "7+"
                            drops[tuple(seg)] = (turn.round, band)
                            c[f"by distance at the drop {band}: dropped"] += 1
                            c[("late" if turn.round >= LATE else "trickle") + ": pearls dropped"] += 1
        # pearls eaten: a dropped tile without a pearl now (Oct 12: also by its distance from the fed head when dropped)
        for tile in list(drops):
            if tile not in t.pearls:
                eater = None
                for d in t.dragons.values():
                    if tuple(d.body[0][:2]) == tile:
                        eater = d
                ph = "late" if turn.round >= LATE else "trickle"
                if eater is not None and eater.id == fed:
                    c[f"{ph}: eaten by the fed dragon"] += 1
                    c[f"by distance at the drop {drops[tile][1]}: the fed dragon ate it"] += 1
                elif eater is not None and eater.team == side:
                    c[f"{ph}: eaten by another of ours"] += 1
                    fh = tuple(t.dragons[fed].body[0][:2]) if fed in t.dragons else tile
                    c[f"{ph}: ours ate it at distance {min(md(tile, fh), 9)} from the fed head"] += 1
                elif eater is not None:
                    c[f"{ph}: eaten by an enemy"] += 1
                else:
                    c[f"{ph}: gone (unseen eater)"] += 1
                del drops[tile]
        prev = {i: (d.team, [(x, y) for x, y, _ in d.body]) for i, d in t.dragons.items()}
    c["left at the end"] += len(drops)
    if fed is not None and fed in t.dragons and fed_len0:
        c["fed dragon length gain"] += len(t.dragons[fed].body) - fed_len0
        c["fed dragon alive at end"] += 1
    c["games"] += 1
    return c


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--since", default="2026-10-11T06:54")
    p.add_argument("--sub", default="22006")
    a = p.parse_args()
    subs = set(a.sub.split(","))
    cl = Client()
    tot = collections.Counter()
    for b in cl.get("/battles?limit=50"):
        if not b.get("ranked") or b["at"][:19] < a.since or b.get("outcome") not in ("win", "loss", "draw"):
            continue
        d = cl.get(f"/battles/{b['id']}")
        side = "A" if d["match"]["teamAId"] == TEAM_ID else "B"
        for g in d.get("games", []):
            path = CACHE / f"{g['id']}.replay"
            if path.is_file() and str(load_replay(path).botA if side == "A" else load_replay(path).botB) in subs:
                tot.update(game(path, side))
    for k in sorted(tot):
        print(f"{k:28s} {tot[k]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
