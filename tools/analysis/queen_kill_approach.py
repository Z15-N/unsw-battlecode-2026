"""Where do enemy killers come from? (algorithm queue #6, escape split; Ben, Oct 11-12.) A split leaves the queen in place
and sends her rear segments off as a child whose head is her old tail, facing away from her: it can only meet a killer
that comes at her from behind. For every enemy kill of our queen (head-on: the killer moves into her head) in our cached
ranked games of the given submissions: her length, and for each of her last 3 turns the killer's head distance (wrapped
Manhattan) to her head and to her tail, whether it was nearer her rear half than her head, and whether the killer
was within 2 of the tile a child's head would take after a split (one step from her tail, away from her body).
    python analysis/queen_kill_approach.py 22006,22056
"""
from __future__ import annotations

import collections
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lab.api import Client  # noqa: E402
from lab.common import load_replay  # noqa: E402
from lab.diagnose import CACHE, TEAM_ID  # noqa: E402
from lab.track import Tracker  # noqa: E402


def one(path, side, subs):
    r = load_replay(path)
    if str(r.botA if side == "A" else r.botB) not in subs:
        return None
    t = Tracker(r, strict=False)
    W, H = t.w, t.h
    md = lambda a, b: min(abs(a[0] - b[0]), W - abs(a[0] - b[0])) + min(abs(a[1] - b[1]), H - abs(a[1] - b[1]))
    q = next(i for i in (0, 1) if t.dragons[i].team == side)
    snaps = collections.deque(maxlen=4)   # her body and every enemy head, at the start of her last turns
    for turn in t.run():
        if q in t.dragons:
            if turn.id == q:
                body = [tuple(s[:2]) for s in t.dragons[q].body]
                enemies = {d.id: tuple(d.body[0][:2]) for d in t.dragons.values() if d.team != side}
                snaps.append((turn.round, body, enemies))
            continue
        # she is gone: who moved last?
        if turn.id == q or not snaps:
            return {"own": True}
        killer = turn.id
        if t.dragons.get(killer) is not None and t.dragons[killer].team == side:
            return {"own": True}
        rows = []
        for rnd, body, enemies in list(snaps)[-3:]:
            if killer not in enemies:
                continue
            k = enemies[killer]
            dh, dt = md(k, body[0]), md(k, body[-1])
            near_seg = min(range(len(body)), key=lambda i: md(k, body[i]))
            rows.append({"round": rnd, "len": len(body), "dh": dh, "dt": dt, "rear": near_seg >= len(body) / 2 and dt < dh})
        return {"own": False, "rows": rows, "len": len(snaps[-1][1]), "map": t.map.name}
    return None


def main() -> int:
    subs = set(sys.argv[1].split(","))
    c = Client()
    seen, kills, own = set(), [], 0
    for b in c.get("/battles?limit=100"):
        if not b.get("ranked") or b.get("outcome") not in ("win", "loss", "draw"):
            continue
        d = c.get(f"/battles/{b['id']}")
        side = "A" if d["match"]["teamAId"] == TEAM_ID else "B"
        for g in d.get("games", []):
            p = CACHE / f"{g['id']}.replay"
            if not p.is_file() or g["id"] in seen:
                continue
            seen.add(g["id"])
            try:
                res = one(p, side, subs)
            except Exception as e:  # noqa: BLE001
                print("skip", g["id"], e)
                continue
            if res is None:
                continue
            if res["own"]:
                own += 1
            else:
                kills.append(res)
    print(f"{len(seen)} games read; enemy kills {len(kills)}, own-move/ally deaths {own}")
    lens = collections.Counter()
    rear_any, rear_last, short = 0, 0, 0
    for k in kills:
        L = k["len"]
        lens["2-3" if L < 4 else "4-7" if L < 8 else "8-12" if L < 13 else "13+"] += 1
        if L < 4:
            short += 1
        if any(r["rear"] for r in k["rows"]):
            rear_any += 1
        if k["rows"] and k["rows"][0]["rear"]:
            rear_last += 1
    print("her length at the kill:", dict(lens))
    print(f"killer nearer her rear half than her head in any of her last 3 turns: {rear_any}/{len(kills)}; "
          f"3 turns before: {rear_last}/{len(kills)}; she was under 4 long (cannot split 2+2): {short}")
    for lo, hi in ((4, 7), (8, 12), (13, 999)):
        ks = [k for k in kills if lo <= k["len"] <= hi]
        last = sum(1 for k in ks if k["rows"] and k["rows"][-1]["rear"])
        first = sum(1 for k in ks if k["rows"] and k["rows"][0]["rear"])
        print(f"length {lo}-{hi}: {len(ks)} kills; killer at her rear half on her last turn {last}, 3 turns before {first}")
    for k in kills[:40]:
        print(f"  {k['map']:24s} L{k['len']:2d} " + " | ".join(f"r{r['round']} dh{r['dh']} dt{r['dt']}{' REAR' if r['rear'] else ''}" for r in k["rows"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
