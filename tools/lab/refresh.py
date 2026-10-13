"""The 4-hourly job: sync the docs (rule changes), scrape the top 10, summarise
new games, retrain every imitation opponent, prune old raw replays. Safe to run by hand.

    python -m lab.refresh [--top 10] [--hours 4] [--keep-hours 48]

Windows Task Scheduler runs it (task "battlecode-refresh"); output goes to
data/logs/refresh-<time>.log and the outcome to data/refresh_status.json.
A lock file stops two runs overlapping; the release loop only ever reads
finished opponents, so a slow refresh never blocks a release.
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import datetime as dt
import json
import os
import sys
import time
import traceback

from .common import DATA, load_replay

LOCK = DATA / "refresh.lock"
STATUS = DATA / "refresh_status.json"
LOGS = DATA / "logs"

STATS_SCHEMA = """
CREATE TABLE IF NOT EXISTS game_stats (
    game_id INTEGER, team TEXT, team_id INTEGER, won INTEGER, rounds INTEGER,
    queen INTEGER, longest INTEGER, total INTEGER, dragons_end INTEGER, max_dragons INTEGER,
    splits INTEGER, sprints INTEGER, sonars INTEGER, deaths TEXT, queen_died_round INTEGER,
    PRIMARY KEY (game_id, team)
);
"""


def summarize(db, limit: int = 100000) -> int:
    """One row per team per game: the numbers strategy questions are asked of."""
    db.executescript(STATS_SCHEMA)
    rows = db.execute("""SELECT g.id, g.team_a, g.team_b, g.winner FROM games g
                         WHERE g.replay_bytes IS NOT NULL
                         AND NOT EXISTS (SELECT 1 FROM game_stats s WHERE s.game_id = g.id)
                         ORDER BY g.at DESC LIMIT ?""", (limit,)).fetchall()
    done = 0
    for gid, team_a, team_b, winner in rows:
        path = DATA / "replays" / f"{gid}.replay"
        if not path.is_file():
            continue
        try:
            r = load_replay(path)
        except Exception:
            continue
        team = {}
        for i, line in enumerate(l for l in r.map.splitlines() if l.startswith("DRAGON ")):
            team[i] = "A" if line.split()[1] == "0" else "B"
        alive = collections.Counter(team.values())
        max_alive = dict(alive)
        splits, sprints, sonars = collections.Counter(), collections.Counter(), collections.Counter()
        deaths = {"A": collections.Counter(), "B": collections.Counter()}
        queen_died = {}
        rnd = 0
        for e in r.events:
            k = e.which()
            if k == "roundStart":
                rnd = e.roundStart.round
            elif k == "dragonSplit":
                s = e.dragonSplit
                t = "A" if str(s.team) == "a" else "B"
                team[s.childId] = t
                splits[t] += 1
                alive[t] += 1
                max_alive[t] = max(max_alive.get(t, 0), alive[t])
            elif k == "dragonAction":
                a = e.dragonAction
                if not a.tle and a.action.which() == "move" and len(a.action.move) > 1:
                    sprints[team.get(a.id, "?")] += 1
            elif k == "sonarPing":
                sonars[team.get(e.sonarPing.senderId, "?")] += 1
            elif k == "dragonDeath":
                d = e.dragonDeath
                t = team.get(d.id, "?")
                if t in deaths:
                    deaths[t][str(d.reason)] += 1
                    alive[t] -= 1
                if d.id <= 1:
                    queen_died[t] = rnd
        res = r.result
        # The replay's GameResult has no queen field: queens alive at the end
        # are the ones that never died; their length is unknown here (-1).
        for t, tid, standing in (("A", team_a, res.teamA), ("B", team_b, res.teamB)):
            won = None if winner is None else int(winner == t.lower())
            db.execute("""INSERT OR REPLACE INTO game_stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (gid, t, tid, won, rnd + 1, 0 if t in queen_died else -1, standing.longestDragon,
                        standing.totalLength, standing.dragonCount, max_alive.get(t, 0), splits[t],
                        sprints[t], sonars[t], json.dumps(dict(deaths[t])), queen_died.get(t)))
        done += 1
        if done % 50 == 0:
            db.commit()
    db.commit()
    return done


def prune(db, keep_hours: float) -> int:
    """Delete raw replays older than the window once they are summarised.
    Games against us are kept."""
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=keep_hours)).isoformat()
    rows = db.execute("""SELECT id FROM games WHERE at < ? AND replay_bytes IS NOT NULL
                         AND team_a != 135 AND team_b != 135
                         AND EXISTS (SELECT 1 FROM game_stats s WHERE s.game_id = games.id)""",
                      (cutoff,)).fetchall()
    removed = 0
    for (gid,) in rows:
        path = DATA / "replays" / f"{gid}.replay"
        if path.is_file():
            path.unlink()
            removed += 1
    return removed


def alive(pid: int) -> bool:
    """Is that process still running? (A killed refresh leaves its lock behind.)"""
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(handle)
    return code.value == 259                                           # STILL_ACTIVE


@contextlib.contextmanager
def locked():
    DATA.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        age = time.time() - LOCK.stat().st_mtime
        try:
            holder = int(LOCK.read_text().strip() or 0)
        except (OSError, ValueError):
            holder = 0
        if age < 6 * 3600 and alive(holder):
            raise SystemExit(f"another refresh is running ({age / 60:.0f} min old lock)")
        LOCK.unlink()
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    try:
        yield
    finally:
        LOCK.unlink(missing_ok=True)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="lab.refresh")
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--hours", type=float, default=4.5)
    p.add_argument("--games", type=int, default=150)
    p.add_argument("--keep-hours", type=float, default=48)
    p.add_argument("--near", type=int, default=50, help="also teams rated within this of us")
    p.add_argument("--summarize", type=int, default=800, help="game_stats rows to build per run (newest first)")
    args = p.parse_args(argv)
    LOGS.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = LOGS / f"refresh-{stamp}.log"
    status = {"started": stamp, "ok": False}
    with locked(), open(log_path, "w", encoding="utf-8", buffering=1) as log, \
            contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        started = time.monotonic()
        try:
            from . import clones, docs_sync, scout
            try:
                status["docs_changed"] = docs_sync.sync()
            except Exception:
                traceback.print_exc()
            status["scout"] = scout.refresh(args.top, args.hours, quiet=False, near=args.near)
            db = scout.connect()
            try:                                  # Ben: don't hold back on replays; our own games are kept for good
                from .api import Client
                from .diagnose import our_games
                status["our_games"] = len(our_games(Client(), 200, ""))
            except Exception:
                traceback.print_exc()
            status["summarized"] = summarize(db, limit=args.summarize)
            try:                                  # Ben: never stop studying the top teams (data/study/latest.md)
                from . import study
                study.main(["--games", "5"])
                status["study"] = "data/study/latest.md"
            except Exception:
                traceback.print_exc()
            try:                                  # Ben: re-check who to learn each skill from; we may overtake them
                from . import skills
                skills.main(["--strategy", "--jobs", "6"])
                status["skills"] = "data/skills/latest.md"
            except Exception:
                traceback.print_exc()
            status["pruned"] = prune(db, args.keep_hours)
            status["ok"] = True
        except Exception:
            traceback.print_exc()
            status["error"] = traceback.format_exc()[-2000:]
        status["seconds"] = round(time.monotonic() - started)
        status["log"] = str(log_path)
        STATUS.write_text(json.dumps(status, indent=1))
        # Clones last (Oct 3): training ~10 teams takes 2.5 h+, and the scheduler's time limit killed the 22:06 and
        # 02:06 runs inside it, before the stats, study and skills steps ever ran. The analysis now always runs
        # first; a run cut short here loses only the remaining clones (each team is exported as it finishes).
        if status["ok"]:
            try:
                clones.run_all(args.top, args.games)
                status["clones"] = "done"
            except Exception:
                traceback.print_exc()
                status["clones"] = "failed"
            status["seconds"] = round(time.monotonic() - started)
            STATUS.write_text(json.dumps(status, indent=1))
    if sys.stdout is not None:            # pythonw (the scheduled task) has no console
        print(json.dumps({k: v for k, v in status.items() if k != "error"}, indent=1))
    return 0 if status["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
