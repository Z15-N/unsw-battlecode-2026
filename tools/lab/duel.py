"""Paired duel on the ladder: the candidate and the champion play the same opponents on the same maps.

    python -m lab.duel --candidate 14556 --champion 14375            (submission ids)
    python -m lab.duel --candidate 14556 --champion 14375 --teams 3 --dev

Why: a ranked trial compares a fresh rating with the champion's settled one, and the scrims go to stronger teams.
On Oct 2 every candidate after v29b trialled 40-140 below it while v29b itself slid from 1755 to 1717. Here both
bots meet the same teams on the same 10 pool maps in unranked games (no rating effect; we are always team A), so
the opponents' strength cancels out.

Steps: activate the candidate, request 10-map unranked battles against N teams near our rating (and the organisers'
dev bot if --dev), wait for every game; activate the champion, the same; compare per (opponent, map). The champion
is active again at the end, whatever happens. Hand battles share the 60-games-an-hour allowance with ranked scrims
(3 teams x 10 maps x 2 bots = 60); dev games have their own 60.
Results go to data/duels.json; lab.trial skips its turn while data/duel.lock exists.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
import time

from .api import Client
from .common import DATA

LOCK = DATA / "duel.lock"
LOG = DATA / "duels.json"
TEAM_ID = 135
DEV_TEAM = 545
POOL_MAP_IDS = [9, 20, 21, 7, 4, 11, 17, 19, 13, 15]   # the 10 maps until Oct 2; see pool_maps()


def pool_maps(client: Client) -> list[int]:
    """The active ranked maps (17 from Oct 2: Stripes, Tower Defense, Islands, Around UNSW, weakhold, Maze, Australia
    were added). A battle request takes 10 maps, so slot k plays a rotating window and every map gets played."""
    try:
        ids = [m["id"] for m in client.get("/maps") if m.get("active") and not m.get("private")]
        return ids or POOL_MAP_IDS
    except Exception:
        return POOL_MAP_IDS


def window(ids: list[int], slot: int) -> list[int]:
    if len(ids) <= 10:
        return list(ids)
    return [ids[(slot * 10 + j) % len(ids)] for j in range(10)]


def activate(client: Client, sub_id: int) -> None:
    client.post(f"/submissions/{sub_id}/activate", {})
    for _ in range(30):
        live = [s for s in client.get("/submissions") if s.get("status") == "active"]
        if live and live[0]["id"] == sub_id:
            return
        time.sleep(2)
    raise RuntimeError(f"submission {sub_id} did not become active")


def opponents(client: Client, n: int, exclude: set) -> list[dict]:
    ladder = client.get("/ratings")["ladder"]
    me = next(t for t in ladder if t["id"] == TEAM_ID)
    pool = [t for t in ladder if not t.get("dev") and t["id"] != TEAM_ID and t["id"] not in exclude]
    pool.sort(key=lambda t: abs(t["elo"] - me["elo"]))
    return pool[: n * 3]          # spares: some teams have no active bot


def request(client: Client, team_id: int, map_ids: list[int]) -> list[int]:
    r = client.post("/battles", {"teamId": team_id, "ranked": False, "mapIds": map_ids})
    return r.get("ids", [])


def wait_done(client: Client, ids: list[int], timeout: float = 1800) -> dict[int, dict]:
    done: dict[int, dict] = {}
    deadline = time.monotonic() + timeout
    while len(done) < len(ids) and time.monotonic() < deadline:
        for gid in ids:
            if gid in done:
                continue
            d = client.get(f"/battles/{gid}")
            if d["match"]["status"] in ("completed", "failed", "error", "cancelled"):
                done[gid] = {"map": d.get("mapName"), "winner": d["match"].get("winner"), "status": d["match"]["status"]}
        if len(done) < len(ids):
            time.sleep(20)
    return done


def arm(client: Client, sub_id: int, teams: list[dict], dev: bool, n_teams: int,
        maps: list[int]) -> tuple[dict, list[int], list[int]]:
    """Play the arm; returns {(team, map): score}, the team ids actually played and the battle ids (for the replays:
    queen fates, Oct 12). The i-th team played gets map window i, so both arms meet the same team on the same maps."""
    activate(client, sub_id)
    ids_by_team, played = {}, []
    for t in teams:
        if len(played) >= n_teams:
            break
        try:
            ids_by_team[t["id"]] = request(client, t["id"], window(maps, len(played)))
            played.append(t["id"])
        except Exception as error:                      # no active bot, or the allowance
            print(f"  skip {t['name']}: {str(error)[:80]}")
    if dev:
        for k in range(3):                                # the dev allowance is its own 60 games an hour: 30 per arm
            try:
                ids_by_team[f"{DEV_TEAM}.{k}"] = request(client, DEV_TEAM, window(maps, n_teams + k))
            except Exception as error:
                print(f"  dev: {str(error)[:80]}")
                break
    all_ids = [g for ids in ids_by_team.values() for g in ids]
    res = wait_done(client, all_ids)
    scores = {}
    for team, ids in ids_by_team.items():
        for gid in ids:
            r = res.get(gid)
            if not r or r["status"] != "completed":
                continue
            w = r["winner"]
            scores[f"{team}|{r['map']}"] = 1.0 if w == "a" else 0.5 if w is None else 0.0
    return scores, played, all_ids


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="lab.duel")
    p.add_argument("--candidate", type=int, required=True)
    p.add_argument("--champion", type=int, required=True)
    p.add_argument("--teams", type=int, default=3)
    p.add_argument("--dev", action="store_true", help="also play the organisers' dev bot (its own allowance)")
    p.add_argument("--no-decide", action="store_true", help="only report; leave active whatever was active before the duel")
    args = p.parse_args(argv)
    client = Client()
    # Oct 8: a --no-decide regression duel (candidate = the live v032, champion = the old v013) left the old bot live:
    # the champion is activated for its half and was left active. Remember what was live and restore it when only
    # reporting.
    live_before = next((x["id"] for x in client.get("/submissions") if x.get("status") == "active"), None)
    LOCK.write_text(str(args.candidate))
    started = dt.datetime.now().isoformat(timespec="seconds")
    try:
        teams = opponents(client, args.teams, set())
        maps = pool_maps(client)
        print(f"candidate {args.candidate} vs the field on {len(maps)} maps", flush=True)
        cand, played, cand_ids = arm(client, args.candidate, teams, args.dev, args.teams, maps)
        same = [t for t in teams if t["id"] in played]
        print(f"champion {args.champion} vs the same {len(same)} teams", flush=True)
        champ, _, champ_ids = arm(client, args.champion, same, args.dev, args.teams, maps)
    finally:
        try:
            activate(client, live_before if (args.no_decide and live_before) else args.champion)
        finally:
            LOCK.unlink(missing_ok=True)
    keys = sorted(cand.keys() & champ.keys())
    diffs = [cand[k] - champ[k] for k in keys]
    n = len(diffs)
    mean = sum(diffs) / max(n, 1)
    sd = math.sqrt(sum((d - mean) ** 2 for d in diffs) / max(n - 1, 1)) if n > 1 else 0.0
    se = sd / math.sqrt(n) if n else 0.0
    out = {"at": started, "candidate": args.candidate, "champion": args.champion, "pairs": n,
           "candidate_score": round(sum(cand[k] for k in keys) / max(n, 1), 3),
           "champion_score": round(sum(champ[k] for k in keys) / max(n, 1), 3),
           "diff": round(mean, 3), "se": round(se, 3), "teams": played, "dev": args.dev,
           "per_game": {k: [cand[k], champ[k]] for k in keys}, "battle_ids": {"candidate": cand_ids, "champion": champ_ids}}
    log = json.loads(LOG.read_text(encoding="utf-8")) if LOG.is_file() else []
    log.append(out)
    LOG.write_text(json.dumps(log, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k not in ("per_game", "battle_ids")}))
    if not args.no_decide and n:
        # WORKFLOW step 6: keep the candidate only when it is at least as good on the same games (Oct 3, after the
        # team rating fell ~235 in a day: v76 went -0.117 +- 0.079 and v77 -0.067 +- 0.082 and both stayed under the old
        # 'revert only below -1.5 SE' rule, so small losses piled up release after release). The cost: with 60 pairs
        # (SE ~0.08) a small real gain is kept only about half the time (v46's queen fix went -0.033 +- 0.082).
        keep = mean >= 0.0
        if keep:
            activate(client, args.candidate)
        from .release import releases, save_log
        rel = releases()
        for e in reversed(rel):
            if e.get("submission_id") == args.candidate:
                e.update({"trial": "keep (duel)" if keep else "revert (duel)",
                          "trial_end": dt.datetime.now().isoformat(timespec="seconds"),
                          "duel": {k: v for k, v in out.items() if k not in ("per_game", "battle_ids")}})
                break
        save_log(rel)
        print(("KEPT: candidate " if keep else "REVERTED: champion ") + str(args.candidate if keep else args.champion) + " is active")
    return 0


if __name__ == "__main__":
    sys.exit(main())
