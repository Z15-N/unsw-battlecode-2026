"""Why did our dragon move that way on the ladder? Rebuild one dragon's exact input blocks from a replay (lab.track),
feed them to a native debug build that prints each direction's score at one round (env WHY_ID / WHY_ROUND), and check
that the re-played move matches the replay's (else the reconstruction is off and the scores mean nothing).
    python analysis/why_move.py find <replay> <side A|B> [max]          list skipped adjacent pearls (rounds 0-100)
    python analysis/why_move.py run <replay> <dragon id> <round> [exe]   per-direction scores at that turn
"""
import os
import subprocess
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lab.common import load_replay  # noqa: E402
from lab.track import Tracker  # noqa: E402

EXE = os.environ.get("WHY_EXE", "why.exe")  # the native debug build of the bot


def turns_of(path):
    t = Tracker(load_replay(path), strict=False)
    out = []
    for turn in t.run():
        after = t.dragons.get(turn.id)
        out.append((turn, None if after is None else len(after.body)))
    return t, out


def find(path, side, cap=10):
    t, turns = turns_of(path)
    W, H = t.w, t.h
    n = 0
    for turn, after_len in turns:
        if turn.team != side or turn.round > 100 or turn.id in (0, 1) or not turn.action or turn.action[0] != "move":
            continue
        hx = hy = None
        for tm, i, x, y, f, hd in turn.bodies:
            if i == turn.id and hd:
                hx, hy = x, y
        if hx is None or after_len is None or after_len > turn.header["length"]:
            continue
        occ = {(x, y) for tm, i, x, y, f, hd in turn.bodies}
        pear = {(x, y) for x, y, p, _ in turn.tiles if p}
        for (nx, ny), e, dname in ((((hx, (hy - 1) % H)), t.map.hedge[hy][hx], "N"), (((hx, (hy + 1) % H)), t.map.hedge[(hy + 1) % H][hx], "S"),
                                   ((((hx - 1) % W, hy)), t.map.vedge[hy][hx], "W"), ((((hx + 1) % W, hy)), t.map.vedge[hy][(hx + 1) % W], "E")):
            if e.kind == 0 and (nx, ny) in pear and (nx, ny) not in occ:
                print(f"round {turn.round} dragon {turn.id} L {turn.header['length']} at ({hx},{hy}): pearl {dname} at ({nx},{ny}), moved {turn.action[1]}")
                n += 1
                break
        if n >= cap:
            break


def run(path, dragon, rnd, exe=EXE):
    t, turns = turns_of(path)
    mine = [(turn, a) for turn, a in turns if turn.id == dragon and turn.round <= rnd]
    if not mine or mine[-1][0].round != rnd:
        raise SystemExit("no such turn")
    start = max(k for k, (turn, _) in enumerate(mine) if turn.first)
    feed = mine[start][0].init_block() + "".join(turn.block() for turn, _ in mine[start:])
    env = dict(os.environ, WHY_ID=str(dragon), WHY_ROUND=str(rnd))
    p = subprocess.run([exe], input=feed.encode(), capture_output=True, env=env, timeout=120)
    out = p.stdout.decode(errors="replace").split("\n")
    moves = [l for l in out if l.startswith(("MOVE", "SPLIT"))]
    print(f"replay's action at round {rnd}: {mine[-1][0].action}; re-played last action: {moves[-1] if moves else None}"
          f" ({len(moves)} actions for {len(mine) - start} turns fed)")
    for l in p.stderr.decode(errors="replace").split("\n"):
        if l.startswith(("WHY", "ESC", "TRUNC")):
            print(" ", l)


if __name__ == "__main__":
    if sys.argv[1] == "find":
        find(sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 10)
    else:
        run(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5] if len(sys.argv) > 5 else EXE)
