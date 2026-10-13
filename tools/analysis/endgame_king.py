"""How does a side grow the dragon that ends longest in a both-dead game? (Oct 12: our both-dead endgames end 21.7 vs
28.6 longest with 55% more total length; top teams 32-90.) For both-dead games of each side: the final longest dragon's
birth round and birth length, its length at r100/200/300/400/end, whether it was ever split from (a parent), and the
pearls its head took split into spawned pearls and death drops (a pearl that appeared in a turn with a death).
    python analysis/endgame_king.py [--teams "SSS,larp stock zi balls"] [--per-team 40] [--subs 22056]
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

MARKS = (100, 200, 300, 400)


def one(path, side):
    from lab.track import Tracker
    t = Tracker(load_replay(path), strict=False)
    q = next(i for i in (0, 1) if t.dragons[i].team == side)
    eq = 1 - q
    born, lens, eats, parent = {}, collections.defaultdict(dict), collections.defaultdict(collections.Counter), set()
    origin = {}                       # pearl tile -> "spawn" / "drop"
    prev_pearls = set(t.pearls)
    prev_ids = set(t.dragons)
    marks = list(MARKS)
    died = set()
    for turn in t.run():
        # new pearls since the last turn: drops if a dragon died in between
        now = set(t.pearls)
        gone_dragons = prev_ids - set(t.dragons)
        for tile in now - prev_pearls:
            origin[tile] = "drop" if gone_dragons else "spawn"
        for tile in prev_pearls - now:
            for d in t.dragons.values():
                if d.team == side and tuple(d.body[0][:2]) == tile:
                    eats[d.id][origin.get(tile, "spawn")] += 1
        for d in t.dragons.values():
            if d.id not in born:
                born[d.id] = (turn.round, len(d.body))
            if turn.action and turn.id == d.id and turn.action[0] == "split":
                parent.add(d.id)
        while marks and turn.round >= marks[0]:
            for d in t.dragons.values():
                if d.team == side:
                    lens[d.id][marks[0]] = len(d.body)
            marks.pop(0)
        for i in (q, eq):
            if i not in t.dragons:
                died.add(i)
        prev_pearls, prev_ids = now, set(t.dragons)
    if not {q, eq} <= died:
        return None
    mine = [d for d in t.dragons.values() if d.team == side]
    if not mine:
        return None
    k = max(mine, key=lambda d: len(d.body))
    return {"born": born.get(k.id, (0, 0)), "lens": [lens[k.id].get(m) for m in MARKS] + [len(k.body)],
            "parent": k.id in parent, "spawn": eats[k.id]["spawn"], "drop": eats[k.id]["drop"], "starter": k.id <= 1 or born.get(k.id, (0,))[0] <= 1}


def report(label, rows):
    if not rows:
        print(f"{label}: none")
        return
    n = len(rows)
    med = lambda xs: st.median(xs) if xs else 0
    cells = []
    for j, m in enumerate(list(MARKS) + ["end"]):
        xs = [r["lens"][j] for r in rows if r["lens"][j] is not None]
        cells.append(f"r{m} {med(xs):.0f} ({len(xs)})")
    print(f"{label}: {n} games | final longest born median r{med([r['born'][0] for r in rows]):.0f} at length "
          f"{med([r['born'][1] for r in rows]):.0f}, a starter in {sum(r['starter'] for r in rows)}, split from in "
          f"{sum(r['parent'] for r in rows)} | length (alive) " + ", ".join(cells) + f" | ate spawns {st.mean(r['spawn'] for r in rows):.1f}, "
          f"drops {st.mean(r['drop'] for r in rows):.1f}", flush=True)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--teams", default="SSS,larp stock zi balls,chat gippy tea,aAah")
    p.add_argument("--since", default="2026-10-11T12:00")
    p.add_argument("--per-team", type=int, default=40)
    p.add_argument("--subs", default="22056")
    p.add_argument("--us-games", type=int, default=60)
    a = p.parse_args()
    db = sqlite3.connect(f"file:{DATA / 'scout.db'}?mode=ro", uri=True)
    names = {n: i for i, n in db.execute("SELECT id, name FROM teams")}
    for name, tid, n in [(x, names.get(x), a.per_team) for x in a.teams.split(",")] + [("us", 135, a.us_games * 3)]:
        if tid is None:
            continue
        rows = []
        for gid, ta, tb in db.execute("""SELECT id, team_a, team_b FROM games WHERE (team_a = ? OR team_b = ?) AND has_replay = 1
                                         AND ranked = 1 AND at >= ? ORDER BY at DESC LIMIT ?""", (tid, tid, a.since, n)):
            path = DATA / "replays" / f"{gid}.replay"
            if not path.is_file():
                continue
            side = "A" if ta == tid else "B"
            if tid == 135:
                r = load_replay(path)
                if str(r.botA if side == "A" else r.botB) not in set(a.subs.split(",")):
                    continue
            try:
                x = one(path, side)
            except Exception:
                continue
            if x:
                rows.append(x)
        report(name, rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
