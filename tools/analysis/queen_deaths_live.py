"""Our queen's deaths in ranked ladder games, per live version (fixed windows, ranked battles only: unranked duel
battles mix the candidate and the champion). Cause = who acted when she died: herself, our dragon, enemy dragon.
    python analysis/queen_deaths_live.py
"""
import collections
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lab.api import Client  # noqa: E402
from lab.common import GameMap, load_replay  # noqa: E402
from lab.diagnose import CACHE, TEAM_ID  # noqa: E402

# live windows (UTC) from data/releases.json (local AEST - 10 h); v52 = 14908 from 12:00:56
WINDOWS = [("v46", "2026-10-02T06:32:20", "2026-10-02T09:47:49"),
           ("v48b", "2026-10-02T09:47:49", "2026-10-02T12:00:53"),
           ("v52", "2026-10-02T12:00:53", "2026-10-02T17:35:43"),
           ("v60u", "2026-10-02T17:35:43", "2026-10-02T20:14:35"),
           ("v63c", "2026-10-02T20:14:35", "2026-10-02T22:38:33"),
           ("v64", "2026-10-02T22:38:33", "2026-10-02T23:39:10"),   # v65 was active 23:06:30-23:07:26 by mistake
           ("v65", "2026-10-02T23:39:10", "2026-10-03T01:08:23"),
           ("v66", "2026-10-03T01:08:23", "2026-10-03T01:21:14"),   # reverted to v65 by the old ranked trial
           ("v65 again", "2026-10-03T01:21:14", "2026-10-03T02:03:14"),
           ("v67", "2026-10-03T02:03:14", "2026-10-03T03:16:44"),
           ("v70c", "2026-10-03T03:16:44", "2026-10-03T03:26:12"),  # reverted by its duel (-2.7 SE)
           ("v67 again", "2026-10-03T03:26:12", "2026-10-03T04:53:15"),
           ("v74", "2026-10-03T04:53:15", "2026-10-03T06:43:26"),     # v67 without MID_SAFE (15532)
           ("v75", "2026-10-03T06:43:26", "2026-10-03T07:43:45"),     # v74 + gate guards (15615)
           ("v76", "2026-10-03T07:43:45", "2026-10-03T08:51:00"),     # v75 + queen sprint (15664)
           ("v77", "2026-10-03T08:51:00", "2026-10-03T10:28:27"),     # v76 + queen corridor fixes (15713)
           ("v65 again", "2026-10-03T10:28:27", "2026-10-04T00:00:00"),  # Ben: v77 worse than v65 (duel 0.533 vs 0.583)
           ("v008", "2026-10-06T01:02:23", "2026-10-07T05:52:38"),    # Phuc's line (v004-v008 from Oct 4), 18147
           ("v009a", "2026-10-07T05:52:38", "2026-10-07T07:41:00"),   # v008 + split to the unit limit, 19261
           ("v008 again", "2026-10-07T07:41:00", "2026-10-07T10:12:38"),  # v009a lost its duel (-0.067)
           ("v012d", "2026-10-07T10:12:38", "2026-10-07T11:11:58"),   # v008 + merge fixes, 19446
           ("v013", "2026-10-07T11:11:58", "2026-10-07T13:20:47"),    # v012d + queen exits, 19497
           ("v017q", "2026-10-07T13:20:47", "2026-10-07T13:44:00"),   # v013 + queen out of corridors, 19607 (reverted)
           ("v013 again", "2026-10-07T13:44:00", "2026-10-07T14:45:59"),
           ("v019", "2026-10-07T14:45:59", "2026-10-07T15:06:00"),    # v013 + ram dodge, 19660 (reverted)
           ("v013 (3)", "2026-10-07T15:06:00", "2026-10-07T22:47:56"),
           ("v020b", "2026-10-07T22:47:56", "2026-10-08T00:14:04"),   # v013 + trickle feeding from round 200, 20056
           ("v021", "2026-10-08T00:14:04", "2026-10-08T01:00:00"),   # v020b + fountain farming + stall fix, 20127 (reverted ~01:00 UTC)
           ("v020b again", "2026-10-08T01:00:00", "2026-10-08T02:12:26"),
           ("v022", "2026-10-08T02:12:26", "2026-10-08T02:55:00"),   # v020b + queen anchored during the merge, 20228 (reverted ~02:5x UTC, approximate: the duel prints no time)
           ("v020b (3)", "2026-10-08T02:55:00", "2026-10-08T03:14:24"),
           ("v023", "2026-10-08T03:14:24", "2026-10-08T04:00:00"),   # v020b + fountain farming to Ben's spec, 20279 (reverted ~04:0x UTC, approximate)
           ("v020b (4)", "2026-10-08T04:00:00", "2026-10-08T04:19:19"),
           ("v025", "2026-10-08T04:19:19", "2026-10-08T05:25:16"),   # v020b + fountain rules on unseen maps only, 20330 (kept, +0.020)
           ("v026", "2026-10-08T05:25:16", "2026-10-08T07:31:27"),   # v025 + no 2:2 inside pockets (unseen maps), 20387 (kept +0.020)
           ("v030", "2026-10-08T07:31:27", "2026-10-08T08:27:07"),   # v026 + no Portals long-dragon rule, 20496 (kept +0.083)
           ("v032", "2026-10-08T08:27:07", "9999")]   # v030 + enemy-queen hunt, 20551 (kept +0.033)


def one(c, b):
    d = c.get(f"/battles/{b['id']}")
    m = d["match"]
    us = "A" if m["teamAId"] == TEAM_ID else "B"
    out = []
    for g in d.get("games", []):
        if g.get("status") != "completed" or not g.get("hasReplay"):
            continue
        p = CACHE / f"{g['id']}.replay"
        if not p.is_file():
            CACHE.mkdir(parents=True, exist_ok=True)
            p.write_bytes(c.replay(g["id"]))
        r = load_replay(p)
        gm = GameMap.parse(r.map)
        team = {i: x[0] for i, x in enumerate(gm.dragons)}
        myq = 0 if team[0] == us else 1
        eq = 1 - myq
        rnd, actor = 0, None
        qd = eqd = None
        for e in r.events:
            k = e.which()
            if k == "roundStart":
                rnd = e.roundStart.round
            elif k == "dragonSplit":
                s = e.dragonSplit
                team[s.childId] = "A" if str(s.team) == "a" else "B"
            elif k == "dragonAction":
                actor = e.dragonAction.id
            elif k == "dragonDeath":
                x = e.dragonDeath
                who = "herself" if actor == x.id else ("our dragon" if team.get(actor) == us else "enemy dragon")
                if x.id == myq and qd is None:
                    qd = (rnd, str(x.reason), who)
                if x.id == eq and eqd is None:
                    eqd = (rnd, str(x.reason), who)
        out.append(dict(id=g["id"], map=g.get("mapName"), opp=b["opponent"], won=g.get("winner") == us.lower(), qd=qd, eqd=eqd))
    return out


def main():
    c = Client()
    battles = [b for b in c.get("/battles?limit=200") if b.get("ranked") and b.get("outcome") != "live"]
    for name, lo, hi in WINDOWS:
        bs = [b for b in battles if lo <= b["at"][:19] < hi]
        rows = [x for b in bs for x in one(c, b)]
        n = len(rows)
        if not n:
            continue
        dead = [x for x in rows if x["qd"]]
        edead = [x for x in rows if x["eqd"]]
        cause = collections.Counter(x["qd"][2] for x in dead)
        reason = collections.Counter(x["qd"][1] for x in dead)
        when = collections.Counter("r<100" if x["qd"][0] < 100 else "r100-249" if x["qd"][0] < 250 else "r250+" for x in dead)
        won_alive = sum(x["won"] for x in rows if not x["qd"])
        won_dead = sum(x["won"] for x in dead)
        print(f"{name}: {len(bs)} ranked battles, {n} games ({lo[11:16]}-{hi[11:16] if hi != '9999' else 'now'} UTC)")
        print(f"  our queen died in {len(dead)}/{n} = {100 * len(dead) / n:.0f}%   enemy queen died in {len(edead)}/{n} = {100 * len(edead) / n:.0f}%")
        print(f"  by: {dict(cause)}   reason: {dict(reason)}   when: {dict(when)}")
        print(f"  won {won_alive}/{n - len(dead)} with our queen alive, {won_dead}/{len(dead)} with her dead")
        if name == WINDOWS[-1][0]:
            per = collections.defaultdict(lambda: [0, 0, 0])
            for x in rows:
                per[x["map"]][0] += 1
                per[x["map"]][1] += x["won"]
                per[x["map"]][2] += bool(x["qd"])
            for m, (g, w, q) in sorted(per.items(), key=lambda kv: kv[1][1] / kv[1][0]):
                print(f"    {m[:18]:18s} games {g:2d}  won {w:2d}  queen died {q:2d}")
            for x in dead:
                print(f"    {x['id']} {x['map'][:16]:16s} {x['opp'][:18]:18s} r{x['qd'][0]:3d} {x['qd'][1]:10s} by {x['qd'][2]:12s} won={x['won']}")


if __name__ == "__main__":
    main()
