"""Every 30 minutes (Ben, Oct 3: "let the +-50 elo run every 30 minutes so we can observe our elo change before we move to
the next version"): log our team rating and the live submission, then re-scout the top 10 and the teams within 50 of
our rating NOW (fresh ladder snapshot, their newest games and replays), so every analysis compares us with the teams we
actually meet.

    python -m lab.elowatch            one run (the scheduled task "battlecode-elowatch" runs elowatch_task.pyw)
    python -m lab.elowatch --show     our rating per live version from the log

Log: data/elo_history.jsonl: a rating line on every run, then a scout line when this run did the re-scout.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import traceback

from .common import DATA

LOG = DATA / "elo_history.jsonl"
LOCK = DATA / "elowatch.lock"


def log_rating() -> dict:
    """Log our team rating and the live submission now (Oct 8: the re-scout grew to 20-36 minutes, overlapping runs were
    refused and the rating went unlogged for an hour, so the rating is written first, on every run)."""
    from .api import Client
    c = Client()
    team = c.get("/team")
    live = [s for s in c.get("/submissions") if s.get("status") == "active"]
    row = {"at": dt.datetime.now().isoformat(timespec="seconds"), "utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "team_elo": team["team"]["elo"], "rank": team.get("rank"), "peak": team.get("peak")}
    if live:
        s = c.get(f"/submissions/{live[0]['id']}")
        row.update({"submission": s["id"], "name": s.get("name"), "submission_rating": s.get("rating"),
                    "record": f"{s['wins']}-{s['draws']}-{s['losses']}"})
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    return row


def scout_once(scout_hours: float = 1.0) -> dict:
    """Re-scout the top 10 and the teams within 50 of our rating; logged as its own line (no team_elo)."""
    row = {"at": dt.datetime.now().isoformat(timespec="seconds")}
    try:
        from . import scout
        row["scout"] = scout.refresh(10, scout_hours, quiet=True, near=50)
    except Exception:
        row["scout_error"] = traceback.format_exc()[-500:]
    row["done"] = dt.datetime.now().isoformat(timespec="seconds")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    return row


def show() -> None:
    rows = [json.loads(l) for l in LOG.read_text(encoding="utf-8").splitlines() if l.strip()] if LOG.is_file() else []
    rows = [r for r in rows if "team_elo" in r]   # scout-only lines carry no rating
    last = None
    for r in rows:
        tag = r.get("name")
        if tag != last:
            print(f"--- {tag} (submission {r.get('submission')})")
            last = tag
        print(f"  {r['at']}  team {r['team_elo']}  rank {r.get('rank')}  submission {r.get('submission_rating')}  {r.get('record', '')}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="lab.elowatch")
    p.add_argument("--show", action="store_true")
    p.add_argument("--hours", type=float, default=1.0, help="scout games from the last N hours")
    args = p.parse_args(argv)
    if args.show:
        show()
        return 0
    row = log_rating()
    if sys.stdout is not None:
        print(json.dumps(row))
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        if time.time() - LOCK.stat().st_mtime < 3600:
            if sys.stdout is not None:
                print("another elowatch scout is in progress: rating logged, scout skipped")
            return 0
        LOCK.unlink()
        os.close(os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    try:
        srow = scout_once(args.hours)
        if sys.stdout is not None:
            print(json.dumps({k: v for k, v in srow.items() if k != "scout_error"}))
    finally:
        LOCK.unlink(missing_ok=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
