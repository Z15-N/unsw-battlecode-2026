"""How do teams kill the enemy queen? (algorithm queue #3, cops and robbers; Ben, Oct 11.) Per kill of the enemy queen
by a side's dragon: the killer's length and age, how far the killer's birth tile and the kill tile are from the enemy
queen's spawn (wrapped Manhattan), the enemy queen's length, whether the kill was a multi-step move, whether a second
dragon of the killer's side was within 4 of her at the kill (a pincer), and how many of the side's dragons were within 6 of
her over the 5 rounds before (pressure).
    python analysis/queen_kill_style.py [--since 2026-10-10T12:00] [--per-team 20]
"""
from __future__ import annotations

import argparse
import collections
import sqlite3
import statistics as st
import pathlib
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lab.common import DATA, load_replay  # noqa: E402

US = 135


def one(job):
    path, side = job
    from lab.track import Tracker
    try:
        t = Tracker(load_replay(path), strict=False)
    except Exception:
        return None
    W, H = t.w, t.h
    md = lambda a, b: min(abs(a[0] - b[0]), W - abs(a[0] - b[0])) + min(abs(a[1] - b[1]), H - abs(a[1] - b[1]))
    eq = next(i for i in (0, 1) if t.dragons[i].team != side)
    espawn = tuple(t.dragons[eq].body[0][:2])
    born, teams = {}, {}
    pressure = collections.deque(maxlen=5)
    last_eq, eq_len = None, 0
    for turn in t.run():
        for d in t.dragons.values():
            if d.id not in born:
                born[d.id] = (turn.round, tuple(d.body[0][:2]))
                teams[d.id] = d.team
        if eq in t.dragons:
            q = t.dragons[eq]
            last_eq, eq_len = tuple(q.body[0][:2]), len(q.body)
            if turn.id == eq:
                pressure.append(sum(1 for d in t.dragons.values() if d.team == side and md(tuple(d.body[0][:2]), last_eq) <= 6))
            continue
        if teams.get(turn.id) != side:
            return None
        k = t.dragons.get(turn.id)
        kb = born.get(turn.id, (0, espawn))
        allies_near = sum(1 for d in t.dragons.values() if d.team == side and d.id != turn.id and md(tuple(d.body[0][:2]), last_eq) <= 4)
        return {"round": turn.round, "killer_len": turn.header["length"], "killer_age": turn.round - kb[0],
                "killer_starter": kb[0] <= 1, "birth_to_espawn": md(kb[1], espawn), "kill_to_espawn": md(last_eq, espawn),
                "eq_len": eq_len, "multi": bool(turn.action and turn.action[0] == "move" and len(turn.action[1]) >= 2),
                "pincer": allies_near >= 1, "pressure": st.mean(pressure) if pressure else 0, "map": t.map.name}
    return None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--since", default="2026-10-10T12:00")
    p.add_argument("--per-team", type=int, default=20)
    a = p.parse_args()
    db = sqlite3.connect(f"file:{DATA / 'scout.db'}?mode=ro", uri=True)
    snap = db.execute("SELECT max(at) FROM ladder").fetchone()[0]
    top = [tid for tid, rk in db.execute("SELECT team_id, rank FROM ladder WHERE at = ?", (snap,)) if rk is not None and rk <= 10 and tid != US]

    def jobs(tids, n):
        out = []
        for tid in tids:
            for gid, ta in db.execute("""SELECT id, team_a FROM games WHERE (team_a = ? OR team_b = ?) AND has_replay = 1 AND
                                         ranked = 1 AND at >= ? ORDER BY at DESC LIMIT ?""", (tid, tid, a.since, n)):
                path = DATA / "replays" / f"{gid}.replay"
                if path.is_file():
                    out.append((str(path), "A" if ta == tid else "B"))
        return out

    with ProcessPoolExecutor(2) as pool:
        for label, js in (("top 10", jobs(top, a.per_team)), ("us", jobs([US], 400))):
            ks = [x for x in pool.map(one, js, chunksize=2) if x]
            if not ks:
                continue
            med = lambda f: st.median(k[f] for k in ks)
            share = lambda f: sum(1 for k in ks if k[f]) / len(ks)
            print(f"== {label}: {len(js)} games, {len(ks)} kills of the enemy queen: round median {med('round')}; killer length "
                  f"median {med('killer_len')}, age {med('killer_age')}, starter {share('killer_starter'):.0%}; killer born "
                  f"{med('birth_to_espawn')} from her spawn; kill {med('kill_to_espawn')} from her spawn; her length median "
                  f"{med('eq_len')}; multi-step kill {share('multi'):.0%}; a 2nd hunter within 4 {share('pincer'):.0%}; our dragons "
                  f"within 6 of her over the 5 rounds before, mean {st.mean(k['pressure'] for k in ks):.1f}", flush=True)
            rounds = sorted(k["round"] for k in ks)
            print(f"   kill rounds quartiles: {rounds[len(rounds) // 4]}, {rounds[len(rounds) // 2]}, {rounds[3 * len(rounds) // 4]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
