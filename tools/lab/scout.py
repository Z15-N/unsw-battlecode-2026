"""Pull the top teams' public games and replays into data/scout.db.

    python -m lab.scout refresh --top 10 --hours 4     (run from tools/)
    python -m lab.scout status
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from .api import Client
from .common import DATA

DB_PATH = DATA / "scout.db"
# Games before the "Slay Queen" rules (queen length decides, ceil(L/4) free steps)
# were played under different rules, so never learn from them.
RULES_EPOCH = dt.datetime(2026, 10, 1, 9, 30, tzinfo=dt.timezone.utc)
REPLAYS = DATA / "replays"

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY, name TEXT, first_seen TEXT
);
CREATE TABLE IF NOT EXISTS ladder (
    at TEXT, team_id INTEGER, rank INTEGER, elo INTEGER, wins INTEGER,
    PRIMARY KEY (at, team_id)
);
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY, at TEXT, map TEXT, ranked INTEGER, challenge INTEGER,
    tournament INTEGER, status TEXT, team_a INTEGER, team_b INTEGER, elo_a INTEGER,
    elo_b INTEGER, winner TEXT, has_replay INTEGER, replay_bytes INTEGER,
    replay_error TEXT
);
CREATE INDEX IF NOT EXISTS games_a ON games (team_a, at);
CREATE INDEX IF NOT EXISTS games_b ON games (team_b, at);
CREATE TABLE IF NOT EXISTS refreshes (
    at TEXT, top INTEGER, hours REAL, new_games INTEGER, replays INTEGER,
    seconds REAL, teams TEXT
);
"""


def connect() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=900)   # elowatch (:09/:39) and refresh (:06) both write; a scout holds the lock for minutes
    db.executescript(SCHEMA)
    return db


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def parse_time(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


def top_teams(client: Client, n: int) -> list[dict]:
    ladder = client.get("/ratings")["ladder"]
    return [t for t in ladder if not t.get("dev")][:n]


def record_ladder(db: sqlite3.Connection, client: Client) -> list[dict]:
    ladder = client.get("/ratings")["ladder"]
    at = now()
    db.executemany("INSERT OR IGNORE INTO teams VALUES (?, ?, ?)",
                   [(t["id"], t["name"], at) for t in ladder])
    db.executemany("UPDATE teams SET name = ? WHERE id = ?", [(t["name"], t["id"]) for t in ladder])
    db.executemany("INSERT OR REPLACE INTO ladder VALUES (?, ?, ?, ?, ?)",
                   [(at, t["id"], t["rank"], t["elo"], t.get("wins")) for t in ladder])
    db.commit()
    return ladder


def list_games(client: Client, db: sqlite3.Connection, team_id: int, since: dt.datetime,
               max_pages: int = 60) -> int:
    """Page through a team's public games, newest first, until older than `since`."""
    added = 0
    for page in range(1, max_pages + 1):
        data = client.team_games(team_id, page)
        matches = data.get("matches") or []
        if not matches:
            break
        rows = []
        oldest = None
        for m in matches:
            at = parse_time(m["at"])
            oldest = at if oldest is None or at < oldest else oldest
            if at < since:
                continue
            a, b = m.get("a") or {}, m.get("b") or {}
            rows.append((m["id"], m["at"], m.get("mapName"), int(bool(m.get("ranked"))),
                         int(bool(m.get("challenge"))), int(bool(m.get("tournament"))),
                         m.get("status"), a.get("id"), b.get("id"), a.get("elo"), b.get("elo"),
                         m.get("winner"), int(bool(m.get("hasReplay")))))
        before = db.total_changes
        db.executemany("""INSERT INTO games (id, at, map, ranked, challenge, tournament, status,
                          team_a, team_b, elo_a, elo_b, winner, has_replay)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                          ON CONFLICT(id) DO UPDATE SET status=excluded.status,
                          winner=excluded.winner, has_replay=excluded.has_replay""", rows)
        added += db.total_changes - before
        db.commit()
        if oldest is not None and oldest < since:
            break
    return added


def download_replays(client: Client, db: sqlite3.Connection, team_ids: list[int],
                     since: dt.datetime, workers: int = 4) -> int:
    REPLAYS.mkdir(parents=True, exist_ok=True)
    marks = ",".join("?" * len(team_ids))
    todo = [row[0] for row in db.execute(
        f"""SELECT id FROM games WHERE has_replay = 1 AND status = 'completed'
            AND replay_bytes IS NULL AND at >= ?
            AND (team_a IN ({marks}) OR team_b IN ({marks})) ORDER BY at DESC""",
        [since.isoformat()] + team_ids + team_ids)]

    def fetch(game_id: int):
        path = REPLAYS / f"{game_id}.replay"
        if path.is_file() and path.stat().st_size > 0:
            return game_id, path.stat().st_size, None
        try:
            blob = client.replay(game_id)
            path.write_bytes(blob)
            return game_id, len(blob), None
        except Exception as error:  # recorded, retried next refresh
            return game_id, None, str(error)[:300]

    done = 0
    with ThreadPoolExecutor(workers) as pool:
        for game_id, size, error in pool.map(fetch, todo):
            db.execute("UPDATE games SET replay_bytes = ?, replay_error = ? WHERE id = ?",
                       (size, error, game_id))
            done += size is not None
            if done % 25 == 0:
                db.commit()
    db.commit()
    return done


def refresh(top: int, hours: float, quiet: bool = False, near: int = 50) -> dict:
    """The top `top` teams, plus (Ben, Oct 2) every team rated within `near` of us: the ones we actually meet."""
    started = time.monotonic()
    client = Client()
    db = connect()
    ladder = record_ladder(db, client)
    real = [t for t in ladder if not t.get("dev")]
    teams = real[:top]
    me = next((t for t in real if t["id"] == 135), None)
    if me and near > 0:
        teams += [t for t in real if t not in teams and t["id"] != 135 and abs(t["elo"] - me["elo"]) <= near]
    since = max(dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours), RULES_EPOCH)
    new_games = 0
    for t in teams:
        added = list_games(client, db, t["id"], since)
        new_games += added
        if not quiet:
            print(f"  #{str(t.get('rank')):<4} {t['name'][:28]:28} elo {t['elo']}  +{added} games", flush=True)
    replays = download_replays(client, db, [t["id"] for t in teams], since)
    seconds = time.monotonic() - started
    db.execute("INSERT INTO refreshes VALUES (?, ?, ?, ?, ?, ?, ?)",
               (now(), top, hours, new_games, replays, seconds,
                json.dumps([t["id"] for t in teams])))
    db.commit()
    summary = {"teams": len(teams), "new_games": new_games, "replays": replays,
               "seconds": round(seconds, 1)}
    if not quiet:
        print(f"refresh: {summary}")
    return summary


def status() -> None:
    db = connect()
    last = db.execute("SELECT at, top, hours, new_games, replays, seconds FROM refreshes "
                      "ORDER BY at DESC LIMIT 1").fetchone()
    print("last refresh:", last)
    snap = db.execute("SELECT MAX(at) FROM ladder").fetchone()[0]
    rows = db.execute("""SELECT l.rank, t.name, l.elo, l.team_id,
            (SELECT COUNT(*) FROM games g WHERE (g.team_a = l.team_id OR g.team_b = l.team_id)
             AND g.replay_bytes IS NOT NULL) AS replays
            FROM ladder l JOIN teams t ON t.id = l.team_id WHERE l.at = ? ORDER BY l.rank IS NULL, l.rank, l.elo DESC LIMIT 15""",
                      (snap,)).fetchall()
    for rank, name, elo, tid, n in rows:
        print(f"  #{rank:<3} {name[:28]:28} elo {elo:<5} id {tid:<5} replays {n}")
    size = sum(p.stat().st_size for p in REPLAYS.glob("*.replay")) if REPLAYS.exists() else 0
    print(f"replay store: {size / 1e6:.0f} MB")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="lab.scout")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("refresh")
    r.add_argument("--top", type=int, default=10)
    r.add_argument("--hours", type=float, default=4)
    sub.add_parser("status")
    args = parser.parse_args(argv)
    if args.cmd == "refresh":
        refresh(args.top, args.hours)
    else:
        status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
