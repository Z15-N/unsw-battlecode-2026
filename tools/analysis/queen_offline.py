"""Offline ladder test of a queen change: take our ladder queen's turns where an enemy head was within 2 and her move
ended with 0-1 free exits (cornered), re-play her exact inputs (lab.track) into native builds, and see what each build
would have done at that turn: the move and the free exits it leaves. The base build must reproduce the replay's move
(validation); the candidate's moves show whether the change gets her out of the corner on real ladder situations.
    python analysis/queen_offline.py <base.exe> <candidate.exe> lo_utc hi_utc [max turns]
"""
import collections
import subprocess
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lab.common import KELP, load_replay  # noqa: E402
from lab.track import Tracker  # noqa: E402

STEP = {"N": (0, -1), "S": (0, 1), "W": (-1, 0), "E": (1, 0)}


def cornered_turns(path, side):
    t = Tracker(load_replay(path), strict=False)
    W, H = t.w, t.h
    q = next(i for i in (0, 1) if t.dragons[i].team == side)

    def md(a, b):
        dx = abs(a[0] - b[0]); dy = abs(a[1] - b[1])
        return min(dx, W - dx) + min(dy, H - dy)

    def edge_open(x, y, d):
        if d == "N": return t.map.hedge[y][x].kind != KELP
        if d == "S": return t.map.hedge[(y + 1) % H][x].kind != KELP
        if d == "W": return t.map.vedge[y][x].kind != KELP
        return t.map.vedge[y][(x + 1) % W].kind != KELP

    def exits(x, y, occ):
        n = 0
        for d, (dx, dy) in STEP.items():
            nx, ny = (x + dx) % W, (y + dy) % H
            if edge_open(x, y, d) and (nx, ny) not in occ:
                n += 1
        return n

    hist, out = [], []
    prev = {i: (d.team, (d.body[0][0], d.body[0][1])) for i, d in t.dragons.items()}
    for turn in t.run():
        post_occ = {(x, y) for d in t.dragons.values() for x, y, _ in d.body}
        if turn.id == q:
            hist.append(turn)
            hp = prev[q][1] if q in prev else None
            a = turn.action or ("none",)
            if hp and a[0] == "move" and q in t.dragons:
                ens = [md(p, hp) for i, (tm, p) in prev.items() if tm != side]
                np_ = (t.dragons[q].body[0][0], t.dragons[q].body[0][1])
                if ens and min(ens) <= 2 and exits(np_[0], np_[1], post_occ) <= 1:
                    # what other moves were open, with the board as her move found it (bodies after her own move)
                    out.append(dict(round=turn.round, hist=list(hist), head=hp, act=a[1], post_occ=post_occ))
        prev = {i: (d.team, (d.body[0][0], d.body[0][1])) for i, d in t.dragons.items()}
    return t, out, exits, W, H


def replay_move(exe, hist):
    start = max(k for k, turn in enumerate(hist) if turn.first)
    feed = hist[start].init_block() + "".join(turn.block() for turn in hist[start:])
    p = subprocess.run([exe], input=feed.encode(), capture_output=True, timeout=300)
    moves = [l for l in p.stdout.decode(errors="replace").split("\n") if l.startswith(("MOVE", "SPLIT"))]
    return moves[-1].strip() if moves else None


def main():
    base, cand, lo, hi = sys.argv[1:5]
    cap = int(sys.argv[5]) if len(sys.argv) > 5 else 40
    from lab.api import Client
    from lab.diagnose import CACHE, TEAM_ID
    c = Client()
    jobs = []
    for b in c.get("/battles?limit=200"):
        if not b.get("ranked") or b.get("outcome") == "live" or not (lo <= b["at"][:19] < hi):
            continue
        d = c.get(f"/battles/{b['id']}")
        us = "A" if d["match"]["teamAId"] == TEAM_ID else "B"
        jobs += [(CACHE / f"{g['id']}.replay", us) for g in d.get("games", []) if (CACHE / f"{g['id']}.replay").is_file()]
    tally = collections.Counter()
    n = 0
    for path, side in jobs:
        if n >= cap:
            break
        try:
            t, cases, exits, W, H = cornered_turns(path, side)
        except Exception:
            continue
        for cse in cases:
            if n >= cap:
                break
            n += 1
            mb = replay_move(base, cse["hist"])
            mc = replay_move(cand, cse["hist"])
            tally["turns"] += 1
            tally["base reproduces"] += mb == f"MOVE {cse['act']}"
            if mc != mb:
                tally["candidate differs"] += 1
            if mc and mc.startswith("MOVE "):
                x, y = cse["head"]
                for ch in mc.split()[1]:
                    dx, dy = STEP[ch]
                    x, y = (x + dx) % W, (y + dy) % H
                occ = set(cse["post_occ"])
                e = exits(x, y, occ)
                tally[f"candidate exits {min(e, 2)}{'+' if e >= 2 else ''}"] += 1
            print(f"{path.stem} r{cse['round']}: replay {cse['act']}  base {mb}  candidate {mc}", flush=True)
    print(dict(tally))


if __name__ == "__main__":
    main()
