"""Why do our ranked games end the way they do? (Oct 12, after twelve queue candidates came out even in self-play.) For
our cached ranked games of the given submissions: by result (won / lost), whether our queen and theirs were alive at the
end, and for games where ours died, the round band.
    python analysis/loss_types.py 22056 [--limit 100]
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lab.api import Client  # noqa: E402
from lab.common import GameMap, load_replay  # noqa: E402
from lab.diagnose import CACHE, TEAM_ID  # noqa: E402


def one(path, side):
    r = load_replay(path)
    gm = GameMap.parse(r.map)
    team = {i: tm for i, (tm, _) in enumerate(gm.dragons)}
    ours = next(i for i in (0, 1) if team[i] == side)
    theirs = 1 - ours
    death = {}
    rnd = 0
    for e in r.events:
        k = e.which()
        if k == "roundStart":
            rnd = e.roundStart.round
        elif k == "dragonDeath" and e.dragonDeath.id in (0, 1):
            death.setdefault(e.dragonDeath.id, rnd)
    return {"map": gm.name, "ours_dead": death.get(ours), "theirs_dead": death.get(theirs), "bot": str(r.botA if side == "A" else r.botB)}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("subs")
    p.add_argument("--limit", type=int, default=100)
    a = p.parse_args()
    subs = set(a.subs.split(","))
    c = Client()
    seen = set()
    cnt = collections.Counter()
    dead_band = collections.Counter()
    for b in c.get(f"/battles?limit={a.limit}"):
        if not b.get("ranked") or b.get("outcome") not in ("win", "loss", "draw"):
            continue
        d = c.get(f"/battles/{b['id']}")
        side = "A" if d["match"]["teamAId"] == TEAM_ID else "B"
        for g in d.get("games", []):
            path = CACHE / f"{g['id']}.replay"
            if g["id"] in seen:
                continue
            seen.add(g["id"])
            if not path.is_file():
                try:
                    path.write_bytes(c.replay(g["id"]))
                except Exception:
                    continue
            x = one(path, side)
            if x["bot"] not in subs:
                continue
            won = str(g.get("winner", "")).lower() == side.lower()
            res = "won" if won else "lost"
            state = f"ours {'dead' if x['ours_dead'] is not None else 'alive'}, theirs {'dead' if x['theirs_dead'] is not None else 'alive'}"
            cnt[(res, state)] += 1
            cnt[res] += 1
            if x["ours_dead"] is not None:
                r0 = x["ours_dead"]
                dead_band[(res, "<150" if r0 < 150 else "150-299" if r0 < 300 else "300+")] += 1
    total = cnt["won"] + cnt["lost"]
    print(f"{total} games, won {cnt['won']} ({cnt['won'] / max(1, total):.0%})")
    for res in ("won", "lost"):
        for state in ("ours alive, theirs dead", "ours alive, theirs alive", "ours dead, theirs alive", "ours dead, theirs dead"):
            print(f"  {res:4s} {state:26s} {cnt[(res, state)]:4d}")
    for res in ("won", "lost"):
        print(f"  {res}: our queen died " + ", ".join(f"{band} {dead_band[(res, band)]}" for band in ("<150", "150-299", "300+")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
