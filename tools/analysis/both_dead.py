"""Games where both queens die are decided by the longest living dragon, then total length (docs/structure.md). Oct 12:
v065 lost 99 of its 164 such ranked games (60%), its biggest loss bucket. Per side (us: cached ranked games of the given
submissions; a top team: scout replays since --since), in both-dead games: who lost the queen first, the round the
second queen died, and at the end (r500 or the last round) each side's longest dragon, total length and dragon count.
    python analysis/both_dead.py --subs 22056 [--teams "aAah,larp stock zi balls"] [--per-team 40]
"""
from __future__ import annotations

import argparse
import collections
import sqlite3
import statistics as st
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lab.common import DATA, load_replay  # noqa: E402

US = 135


def one(path, side):
    from lab.track import Tracker
    t = Tracker(load_replay(path), strict=False)
    q = next(i for i in (0, 1) if t.dragons[i].team == side)
    eq = 1 - q
    died = {}
    last = None
    for turn in t.run():
        for i in (q, eq):
            if i not in t.dragons and i not in died:
                died[i] = turn.round
        last = turn.round
    if q not in died or eq not in died:
        return None
    mine = [len(d.body) for d in t.dragons.values() if d.team == side]
    theirs = [len(d.body) for d in t.dragons.values() if d.team != side]
    return {"first": "ours" if died[q] < died[eq] else "theirs" if died[eq] < died[q] else "same",
            "second": max(died.values()), "end": last,
            "long_us": max(mine, default=0), "long_them": max(theirs, default=0),
            "tot_us": sum(mine), "tot_them": sum(theirs), "n_us": len(mine), "n_them": len(theirs)}


def report(label, rows):
    if not rows:
        print(f"{label}: no both-dead games")
        return
    n = len(rows)
    won = sum(1 for r in rows if (r["long_us"], r["tot_us"]) > (r["long_them"], r["tot_them"]))
    first = collections.Counter(r["first"] for r in rows)
    print(f"{label}: {n} both-dead games, longest-dragon wins {won} ({won / n:.0%}); queen lost first: ours {first['ours']}, theirs "
          f"{first['theirs']}; 2nd queen death median r{st.median(r['second'] for r in rows):.0f} | at the end: longest "
          f"{st.mean(r['long_us'] for r in rows):.1f} vs {st.mean(r['long_them'] for r in rows):.1f}, total "
          f"{st.mean(r['tot_us'] for r in rows):.0f} vs {st.mean(r['tot_them'] for r in rows):.0f}, dragons "
          f"{st.mean(r['n_us'] for r in rows):.1f} vs {st.mean(r['n_them'] for r in rows):.1f}", flush=True)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--subs", default="22056")
    p.add_argument("--teams", default="aAah,larp stock zi balls,chat gippy tea,SSS")
    p.add_argument("--since", default="2026-10-11T12:00")
    p.add_argument("--per-team", type=int, default=40)
    p.add_argument("--limit", type=int, default=100)
    a = p.parse_args()
    from lab.api import Client
    from lab.diagnose import CACHE, TEAM_ID
    subs = set(a.subs.split(","))
    c = Client()
    rows, seen = [], set()
    for b in c.get(f"/battles?limit={a.limit}"):
        if not b.get("ranked") or b.get("outcome") not in ("win", "loss", "draw"):
            continue
        d = c.get(f"/battles/{b['id']}")
        side = "A" if d["match"]["teamAId"] == TEAM_ID else "B"
        for g in d.get("games", []):
            path = CACHE / f"{g['id']}.replay"
            if g["id"] in seen or not path.is_file():
                continue
            seen.add(g["id"])
            r = load_replay(path)
            if str(r.botA if side == "A" else r.botB) not in subs:
                continue
            x = one(path, side)
            if x:
                rows.append(x)
    report("us", rows)
    db = sqlite3.connect(f"file:{DATA / 'scout.db'}?mode=ro", uri=True)
    names = {n: i for i, n in db.execute("SELECT id, name FROM teams")}
    for name in a.teams.split(","):
        if name not in names:
            continue
        tid = names[name]
        rows = []
        for gid, ta in db.execute("""SELECT id, team_a FROM games WHERE (team_a = ? OR team_b = ?) AND has_replay = 1 AND
                                     ranked = 1 AND at >= ? ORDER BY at DESC LIMIT ?""", (tid, tid, a.since, a.per_team)):
            path = DATA / "replays" / f"{gid}.replay"
            if path.is_file():
                x = one(path, "A" if ta == tid else "B")
                if x:
                    rows.append(x)
        report(name, rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
