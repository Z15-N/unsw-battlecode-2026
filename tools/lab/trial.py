"""Ladder trial: judge an uploaded release on the real ladder, keep it or bring the champion back.

    python -m lab.trial              one look: the running trial's numbers, and its verdict if it is due
    python -m lab.trial --watch      spend ranked scrims, look every 10 min, decide, exit

A new upload starts from the rating of the bot it took over from, and re-activating
the old bot restores its exact rating (docs/elo.md), so trying a release on the
ladder costs nothing if we revert. The decision (GOALS.md step 9):
  - after --games ranked games: keep it if its rating >= the champion's, else revert
  - early revert: after 40 games it trails the champion by more than 80
  - a teammate's upload replacing it ends the trial ("superseded")
While a trial runs we spend our ranked allowance (12 battles an hour) on teams
near and above us, so the new rating settles faster. Requests go to data/scrims.json.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time

from .api import Client
from .common import DATA
from .release import releases, save_log

SCRIMS = DATA / "scrims.json"
TEAM_ID = 135
PER_HOUR = 12


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def running() -> tuple[list, dict | None]:
    log = releases()
    for entry in reversed(log):
        if entry.get("trial") == "running":
            return log, entry
    return log, None


def games_of(sub: dict) -> int:
    return sub["wins"] + sub["draws"] + sub["losses"]


def scrim_log() -> list:
    return json.loads(SCRIMS.read_text(encoding="utf-8")) if SCRIMS.is_file() else []


def spend_scrims(client: Client, quiet: bool = False) -> int:
    """Request ranked battles up to the hourly allowance against teams near and above us."""
    log = scrim_log()
    hour_ago = (now() - dt.timedelta(hours=1)).isoformat()
    used = sum(1 for s in log if s["at"] >= hour_ago and s.get("ok"))
    if used >= PER_HOUR:
        return 0
    ladder = client.get("/ratings")["ladder"]
    me = next((t for t in ladder if t["id"] == TEAM_ID), None)
    if not me:
        return 0
    refused = {s["team"] for s in log if not s.get("ok") and s["at"] >= (now() - dt.timedelta(hours=8)).isoformat()}
    recent = [s["team"] for s in log if s["at"] >= hour_ago and s.get("ok")]
    # Informative and allowed: rated from 50 below us (the rule) to 200 above (still ~25% wins for us).
    pool = [t for t in ladder if not t.get("dev") and t["id"] != TEAM_ID and t["id"] not in refused
            and me["elo"] - 50 <= t["elo"] <= me["elo"] + 200]
    pool.sort(key=lambda t: (recent.count(t["id"]), abs(t["elo"] - (me["elo"] + 50))))
    made = 0
    for t in pool:
        if used + made >= PER_HOUR:
            break
        if recent.count(t["id"]) >= 2:
            continue
        entry = {"at": now().isoformat(), "team": t["id"], "name": t["name"], "elo": t["elo"], "our_elo": me["elo"]}
        try:
            r = client.post("/battles", {"teamId": t["id"], "ranked": True})
            entry.update({"ok": True, "battle": (r.get("ids") or [None])[0]})
            made += 1
            recent.append(t["id"])
        except Exception as error:                                 # ranked switch off, or over the limit
            detail = error.read().decode("utf-8", "replace") if hasattr(error, "read") else ""
            entry.update({"ok": False, "error": (str(error) + " " + detail)[:300]})
            if "429" in str(error) or "limit" in str(error).lower():
                log.append(entry)
                break
        log.append(entry)
    SCRIMS.write_text(json.dumps(log[-2000:], indent=1), encoding="utf-8")
    if made and not quiet:
        print(f"requested {made} ranked battles ({used + made}/{PER_HOUR} this hour)")
    return made


BENCH = DATA / "dev_bench.json"
BENCH_TEAM = 545                              # "dev test 1 :P", an organisers' bot rated ~1830, above us
POOL_MAP_IDS = [9, 20, 21, 7, 4, 11, 17, 19, 13, 15]


def spend_bench(client: Client, sub: dict) -> int:
    """Unranked games against the organisers' strong bot: a separate 60-games-an-hour allowance, no rating effect,
    same 10 maps every time. Games start at once, so they are played by the submission active now."""
    log = json.loads(BENCH.read_text(encoding="utf-8")) if BENCH.is_file() else []
    hour_ago = (now() - dt.timedelta(hours=1)).isoformat()
    used = sum(len(e["ids"]) for e in log if e["at"] >= hour_ago)
    made = 0
    from .duel import pool_maps, window
    maps = pool_maps(client)                     # all 17 active maps from Oct 2, 10 per request in rotation
    k = len(log)
    while used + made + 10 <= 60:
        try:
            r = client.post("/battles", {"teamId": BENCH_TEAM, "ranked": False, "mapIds": window(maps, k)})
            k += 1
        except Exception as error:
            print(f"bench: {error}")
            break
        log.append({"at": now().isoformat(), "submission": sub["id"], "name": sub["name"], "ids": r.get("ids", [])})
        made += len(r.get("ids", []))
    BENCH.write_text(json.dumps(log, indent=1), encoding="utf-8")
    return made


def bench_score(client: Client, sub_id: int) -> tuple[float, int]:
    """Our score in finished benchmark games played by this submission (results cached in the log)."""
    log = json.loads(BENCH.read_text(encoding="utf-8")) if BENCH.is_file() else []
    wins = games = 0
    changed = False
    for e in log:
        if e["submission"] != sub_id:
            continue
        results = e.setdefault("results", {})
        for gid in e["ids"]:
            if str(gid) not in results:
                m = client.get(f"/battles/{gid}")["match"]
                if m.get("status") != "completed":
                    continue
                results[str(gid)] = m.get("winner")
                changed = True
            w = results[str(gid)]
            games += 1
            wins += 1 if w == "a" else 0.5 if w is None else 0     # we are always team A when we challenge
    if changed:
        BENCH.write_text(json.dumps(log, indent=1), encoding="utf-8")
    return (wins / games if games else 0.0), games


def judge(client: Client, min_games: int, max_hours: float, act: bool = True) -> str:
    if (DATA / "duel.lock").is_file():                # lab.duel is switching submissions: hands off
        print("duel in progress: no judging, no scrims")
        return "duel"
    log, entry = running()
    if not entry:
        print("no trial running")
        return "none"
    if not entry.get("submission_id"):                 # the build outlasted lab.release's wait: find it by name
        subs = [s for s in client.get("/submissions") if s.get("name") == entry["name"]]
        if not subs or subs[0].get("status") not in ("active", "ready"):
            print(f"trial {entry['name']}: upload not built yet")
            return "running"
        entry["submission_id"] = subs[0]["id"]
        save_log(log)
    cand = client.get(f"/submissions/{entry['submission_id']}")
    champ = client.get(f"/submissions/{entry['champion_id']}")
    active = [s for s in client.get("/submissions") if s.get("status") == "active"]
    # The record counts unranked games too (the benchmark): only ranked games move the rating.
    try:
        _, bench_games = bench_score(client, cand["id"])
    except Exception:
        bench_games = 0
    n = games_of(cand) - entry.get("candidate_games0", 0) - bench_games
    gap = (cand.get("rating") or 0) - (champ.get("rating") or 0)
    age = (dt.datetime.now() - dt.datetime.fromisoformat(entry["at"])).total_seconds() / 3600
    print(f"trial {entry['name']} (#{cand['id']}): rating {cand.get('rating')} after {n} games "
          f"({cand['wins']}-{cand['draws']}-{cand['losses']}) vs champion {champ['name']} {champ.get('rating')}"
          f"  gap {gap:+}  age {age:.1f} h")
    try:
        cb, cn = bench_score(client, cand["id"])
        pb, pn = bench_score(client, champ["id"])
        print(f"  benchmark vs dev test 1 (unranked, same 10 maps): candidate {cb:.2f} over {cn}, champion {pb:.2f} over {pn}")
        entry["bench"] = {"candidate": [round(cb, 3), cn], "champion": [round(pb, 3), pn]}
    except Exception as error:
        print(f"  benchmark: {error}")
    verdict = "running"
    if not active or active[0]["id"] != cand["id"]:
        verdict = "superseded"
    elif n >= 40 and gap < -80:          # one burst of challenges from an underrated new bot cost v34t 139 in 25 games
        verdict = "revert"
    elif n >= min_games or (age >= max_hours and n >= 15):
        verdict = "keep" if gap >= 0 else "revert"
    if verdict == "running":
        return verdict
    if verdict == "revert" and act:
        client.post(f"/submissions/{champ['id']}/activate", {})
        print(f"REVERTED: {champ['name']} (#{champ['id']}) is active again")
    elif verdict == "keep":
        print(f"KEPT: {entry['name']} is the new champion")
    else:
        print(f"{verdict.upper()}: trial ended")
    entry.update({"trial": verdict, "trial_end": dt.datetime.now().isoformat(timespec="seconds"),
                  "trial_games": n, "trial_rating": cand.get("rating"), "trial_champion_rating": champ.get("rating")})
    save_log(log)
    return verdict


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="lab.trial")
    p.add_argument("--watch", action="store_true")
    p.add_argument("--games", type=int, default=60, help="ranked games before the verdict")
    p.add_argument("--hours", type=float, default=4.0, help="decide with what we have after this long")
    p.add_argument("--no-scrims", action="store_true")
    p.add_argument("--once", action="store_true", help="one look plus scrims (the scheduled task)")
    p.add_argument("--every", type=float, default=600, help="seconds between looks in --watch")
    args = p.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")    # logs are files: cp1252 can't hold the docs
    client = Client()
    while True:
        verdict = judge(client, args.games, args.hours)
        if verdict != "running" or not (args.watch or args.once):
            return 0
        if not args.no_scrims:
            try:
                spend_scrims(client)
            except Exception as error:
                print(f"scrims: {error}")
            try:
                live = [s for s in client.get("/submissions") if s.get("status") == "active"]
                if live and spend_bench(client, live[0]):
                    print(f"requested benchmark games for {live[0]['name']}")
            except Exception as error:
                print(f"bench: {error}")
        sys.stdout.flush()
        if args.once:
            return 0
        time.sleep(args.every)


if __name__ == "__main__":
    sys.exit(main())
