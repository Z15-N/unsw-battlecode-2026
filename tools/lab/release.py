"""Gate a candidate against the bot that is live right now, upload it, and hand it to the ladder trial.

    python -m lab.release ../bot --name v25 --desc "what changed"      (from tools/)
    python -m lab.release ../bot --name v25 --desc "..." --dry-run      gate only

Steps (GOALS.md checklist):
  1. print GOALS.md, STRATEGY.md and any docs changes since the last release
  2. download the submission that is ACTIVE on the server: that is the champion,
     whoever uploaded it (teammates develop in parallel)
  3. gate: batches of games on the 10 pool maps + generated unseen maps, both
     sides. Games this exact code already played against this exact champion
     (arena.db, by source hash) count, so an interrupted gate resumes.
       pass   the 95% interval is above 0.5
       trial  score >= 0.5 after the batch budget (no measurable regression)
       fail   anything else, or the interval sits below 0.5
  4. clone smoke test: candidate and champion each play every top-10 imitation
     bot; the candidate may not score lower
  5. zero crashes / timeouts, max CPU under 85M points per turn (judge: 100M; was 50M until Oct 7)
  6. snapshot to versions/local/<name>, upload with `unswbc submit`, log to
     data/releases.json with the champion's rating, for `lab.trial` to judge
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import pathlib
import random
import re
import shutil
import subprocess
import sys
import time
import zipfile

from . import arena
from .api import API, Client
from .common import DATA, ROOT

LOG = DATA / "releases.json"
LOCAL = ROOT / "versions" / "local"
SERVER = ROOT / "versions" / "server"
CLONES = ROOT / "opponents" / "clones"
CPU_LIMIT = 85_000_000   # Ben, Oct 7: "push the limit to max"; the judge kills a turn at 100M, 15% margin


def banner(title: str) -> None:
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78, flush=True)


def read_goals() -> None:
    banner("GOALS.md (re-read before every release)")
    print((ROOT / "notebook" / "GOALS.md").read_text(encoding="utf-8"))
    banner("STRATEGY.md (Ben's direction)")
    text = (ROOT / "notebook" / "STRATEGY.md").read_text(encoding="utf-8")
    print(text[:3000] + ("\n[...]" if len(text) > 3000 else ""))
    changes = sorted((DATA / "docs_changes").glob("*.diff")) if (DATA / "docs_changes").exists() else []
    last = releases()[-1]["at"] if releases() else ""
    fresh = [c for c in changes if c.stem > last.replace("-", "").replace(":", "").replace("T", "-")[:15]]
    banner("Docs changes since the last release")
    print("\n".join(c.read_text(encoding="utf-8")[:2000] for c in fresh) or "none")


def releases() -> list:
    return json.loads(LOG.read_text(encoding="utf-8")) if LOG.is_file() else []


def save_log(log: list) -> None:
    LOG.write_text(json.dumps(log, indent=1), encoding="utf-8")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def fetch_submission(client: Client, s: dict) -> pathlib.Path:
    folder = SERVER / f"{s['id']}_{slug(s['name'])}"
    if not folder.exists():
        blob = subprocess.run(["curl", "-sL", f"{API}/submissions/{s['id']}/download",
                               "-H", "Authorization: Bearer " + client.key], capture_output=True).stdout
        zipfile.ZipFile(io.BytesIO(blob)).extractall(folder)
    return folder


def active_champion(client: Client) -> tuple[dict, pathlib.Path]:
    subs = client.get("/submissions")
    live = [s for s in subs if s.get("status") == "active"]
    if not live:
        raise SystemExit("no active submission on the server: nothing to gate against")
    return live[0], fetch_submission(client, live[0])


def prior_results(candidate: str, champion: str) -> list[dict]:
    """Gate games this exact candidate code already played against this exact champion code."""
    hc, hp = arena.source_hash(candidate), arena.source_hash(champion)
    db = arena.connect()
    rows = db.execute("""SELECT map, hash_a, winner, errors, max_a, max_b FROM games
                         WHERE (hash_a = ? AND hash_b = ?) OR (hash_a = ? AND hash_b = ?)""",
                      (hc, hp, hp, hc)).fetchall()
    out = []
    for mp, ha, winner, errors, max_a, max_b in rows:
        a, b = (candidate, champion) if ha == hc else (champion, candidate)
        out.append({"map": mp, "a": a, "b": b, "winner": winner, "errors": json.loads(errors or "[]"),
                    "max": (max_a, max_b)})
    return out


def summarize(results: list[dict], candidate: str) -> dict:
    scores = [s for s in (arena.score_of(r, candidate) for r in results) if s is not None]
    mean, lo, hi = arena.interval(scores)
    def group(r) -> str:
        path = pathlib.Path(r["map"])
        return "gen" if path.stem.startswith("gen_") else "new" if path.parent.name == "maps_unseen" else "pool"
    pool = [arena.score_of(r, candidate) for r in results if "crash" not in r and group(r) == "pool"]
    new = [arena.score_of(r, candidate) for r in results if "crash" not in r and group(r) == "new"]
    gen = [arena.score_of(r, candidate) for r in results if "crash" not in r and group(r) == "gen"]
    crashes = [r for r in results if "crash" in r]
    errors = [e for r in results if "errors" in r for e in r["errors"] if (e[2] == "A") == (r["a"] == candidate)]
    cpu = max([(r["max"][0] if r["a"] == candidate else r["max"][1]) for r in results if "max" in r] or [0])
    return {"games": len(scores), "score": round(mean, 4), "lo": round(lo, 4), "hi": round(hi, 4),
            "pool": round(sum(pool) / max(len(pool), 1), 4), "unseen": round(sum(gen) / max(len(gen), 1), 4),
            "new_maps": round(sum(new) / max(len(new), 1), 4),
            "crashes": len(crashes), "bot_errors": len(errors), "max_cpu": cpu,
            "first_problem": (errors or crashes)[:1]}


def gate(candidate: str, champion: str, batches: int, seeds: int, jobs: int, reuse: bool, maps: str = "all") -> dict:
    """`maps`: 'all' by default. A change that only acts on maps the bot does not know (mapIdx < 0) plays exactly like
    the champion on the known ones, so it may gate on 'unseen+gen' (say so in the release note)."""
    maps = arena.expand_maps(maps)
    per_batch = len(maps) * seeds * 2
    results = prior_results(candidate, champion) if reuse else []
    if results:
        print(f"reusing {len(results)} games this code already played against this champion")
    verdict = "undecided"
    while True:
        s = summarize(results, candidate)
        if s["games"]:
            print(f"after {s['games']} games: score {s['score']:.3f} [{s['lo']:.3f}, {s['hi']:.3f}]", flush=True)
        if s["games"] >= per_batch and s["lo"] > 0.5:
            verdict = "pass"
            break
        if s["games"] >= per_batch and s["hi"] < 0.5:
            verdict = "fail"
            break
        if s["games"] >= 2 * per_batch and s["score"] < 0.46:      # clearly not better: stop paying for games
            verdict = "fail"
            break
        if s["games"] >= batches * per_batch:
            verdict = "trial" if s["score"] >= 0.5 else "fail"
            break
        banner(f"gate batch {s['games'] // per_batch + 1}/{batches}: "
               f"{pathlib.Path(candidate).name} vs {pathlib.Path(champion).name}")
        results += arena.run(candidate, champion, maps, seeds, jobs, quiet=False)
    out = {"verdict": verdict, **summarize(results, candidate)}
    if out["crashes"] or out["bot_errors"]:
        out["verdict"] = "fail"
        out["why"] = f"{out['crashes']} crashes, {out['bot_errors']} timeouts/errors (first: {out['first_problem']})"
    if out["max_cpu"] > CPU_LIMIT:
        out["verdict"] = "fail"
        out["why"] = f"max CPU {out['max_cpu'] / 1e6:.1f}M > {CPU_LIMIT / 1e6:.0f}M"
    return out


def clone_smoke(candidate: str, champion: str, jobs: int, maps_per_clone: int = 2) -> dict:
    """Both bots play every imitation bot on the same maps and seeds; the candidate may not do worse."""
    clones = []
    for src in sorted(CLONES.iterdir()) if CLONES.exists() else []:
        if not (src / "clone.json").is_file():           # export writes clone.json last: unfinished otherwise
            continue
        # Freeze a copy: the 4-hourly refresh rewrites opponents/clones/ while we play.
        try:
            frozen = DATA / "smoke_clones" / f"{src.name}_{arena.source_hash(str(src))}"
            if not frozen.exists():
                shutil.copytree(src, frozen, ignore=shutil.ignore_patterns(".unswbc-build", "__pycache__"))
        except OSError:                                   # being re-exported right now
            continue
        clones.append(str(frozen))
    if not clones:
        return {"verdict": "skip", "why": "no imitation bots built"}
    rng = random.Random(1)
    batch = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-smoke"
    work = []
    for clone in clones:
        for mp in rng.sample(arena.POOL, maps_per_clone):
            seed = rng.getrandbits(64)
            for bot in (candidate, champion):
                work += [(batch, mp, seed, bot, clone), (batch, mp, seed, clone, bot)]
    banner(f"clone smoke test: {len(clones)} imitation bots, {len(work)} games")
    # Games this exact code already played on the same map and seed against the same clone count (arena.db, by hash).
    db = arena.connect()
    hashes = {b: arena.source_hash(b) for b in {w[3] for w in work} | {w[4] for w in work}}
    results, todo = [], []
    for w in work:
        _, mp, seed, a, b = w
        row = db.execute("""SELECT winner, errors, max_a, max_b FROM games WHERE map = ? AND seed = ? AND hash_a = ?
                            AND hash_b = ? ORDER BY id DESC LIMIT 1""", (mp, f"{seed:016x}", hashes[a], hashes[b])).fetchone()
        if row:
            results.append({"map": mp, "seed": seed, "a": a, "b": b, "winner": row[0],
                            "errors": json.loads(row[1] or "[]"), "max": (row[2], row[3])})
        else:
            todo.append(w)
    if len(todo) < len(work):
        print(f"reusing {len(work) - len(todo)} smoke games already played")
    results += arena.execute(todo, jobs) if todo else []
    crashed = [r for r in results if "crash" in r]
    if crashed:                                       # harness failures (sandbox boot, load): one retry each
        print(f"retrying {len(crashed)} crashed smoke games; first: {crashed[0]['crash'][:200]}")
        retry = [(r["batch"], r["map"], r["seed"], r["a"], r["b"]) for r in crashed]
        results = [r for r in results if "crash" not in r] + arena.execute(retry, jobs)
    score, per_game = {}, {}
    for bot in (candidate, champion):
        mine = {}
        for r in results:
            if bot in (r["a"], r["b"]):
                s = arena.score_of(r, bot)
                if s is not None:
                    opp = r["b"] if r["a"] == bot else r["a"]
                    mine[(opp, r["map"], r["seed"], r["a"] == bot)] = s
        per_game[bot] = mine
        score[bot] = sum(mine.values()) / max(len(mine), 1)
    problems = summarize([r for r in results if candidate in (r["a"], r["b"])], candidate)
    out = {"candidate": round(score[candidate], 3), "champion": round(score[champion], 3),
           "games": len(work), "crashes": problems["crashes"], "bot_errors": problems["bot_errors"]}
    # Paired test on the same (clone, map, seed, side) games: fail only on a regression bigger than the noise
    # (2 standard errors of the paired difference, and at least 3 games' worth).
    keys = per_game[candidate].keys() & per_game[champion].keys()
    diffs = [per_game[candidate][k] - per_game[champion][k] for k in keys]
    n = max(len(diffs), 1)
    mean = sum(diffs) / n
    se = (sum((d - mean) ** 2 for d in diffs) / max(n - 1, 1) / n) ** 0.5
    out["paired_diff"] = round(mean, 3)
    worse = mean < -max(2 * se, 3 / n)
    out["verdict"] = "fail" if worse or problems["crashes"] or problems["bot_errors"] else "pass"
    print(json.dumps(out))
    return out


def snapshot(candidate: pathlib.Path, name: str) -> pathlib.Path:
    dest = LOCAL / slug(name)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(candidate, dest, ignore=shutil.ignore_patterns(".unswbc-build", "__pycache__"))
    return dest


def upload(folder: pathlib.Path, name: str, desc: str) -> str:
    for attempt in range(5):                 # the server answers 502 now and then
        done = subprocess.run(["unswbc", "submit", str(folder), "-n", name, "-d", desc],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        print(done.stdout + done.stderr)
        if done.returncode == 0:
            return done.stdout
        time.sleep(20 * (attempt + 1))
    raise SystemExit("upload failed")


def find_upload(client: Client, name: str, before: set[int], wait: float = 600) -> dict | None:
    """The submission we just uploaded, once it has built (it goes active by itself)."""
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        new = [s for s in client.get("/submissions") if s["id"] not in before and s.get("name") == name]
        if new and new[0].get("status") in ("active", "ready", "failed", "error"):
            return new[0]
        time.sleep(15)
    return None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="lab.release")
    p.add_argument("candidate")
    p.add_argument("--name", required=True)
    p.add_argument("--desc", required=True)
    p.add_argument("--batches", type=int, default=4, help="gate budget in batches of 60 games")
    p.add_argument("--seeds", type=int, default=1, help="seeds per map per batch (each played both ways)")
    p.add_argument("--jobs", type=int, default=10)
    p.add_argument("--against", default=None, help="gate against this folder instead of the live bot")
    p.add_argument("--fresh", action="store_true", help="don't reuse earlier games of the same code")
    p.add_argument("--maps", default="all", help="gate maps (arena spec), e.g. 'unseen+gen' for blind-play-only changes")
    p.add_argument("--no-smoke", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--ladder-trial", default=None, metavar="REASON",
                   help="send to the ladder trial even if the self-play score is below 0.5 (never past crashes, timeouts, "
                        "CPU or the smoke test); the reason is logged")
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")    # logs are files: cp1252 can't hold the docs

    read_goals()
    client = Client()
    if args.against:
        champ_meta, champ = {"name": pathlib.Path(args.against).name, "id": None}, pathlib.Path(args.against)
    else:
        champ_meta, champ = active_champion(client)
    banner(f"champion: {champ_meta['name']} (submission {champ_meta['id']}) -> {champ}")
    candidate = str(pathlib.Path(args.candidate))
    result = gate(candidate, str(champ), args.batches, args.seeds, args.jobs, reuse=not args.fresh, maps=args.maps)
    if args.ladder_trial and result["verdict"] == "fail" and "why" not in result:
        result["verdict"] = "trial"
        result["forced"] = args.ladder_trial          # self-play score only; crashes/CPU still fail ("why" set)
    if result["verdict"] != "fail" and not args.no_smoke:
        result["smoke"] = clone_smoke(candidate, str(champ), args.jobs)
        if result["smoke"]["verdict"] == "fail":
            result["verdict"] = "fail"
            result["why"] = f"clone smoke test: {result['smoke']}"
    banner(f"GATE {result['verdict'].upper()}: {json.dumps(result)}")
    entry = {"at": dt.datetime.now().isoformat(timespec="seconds"), "name": args.name, "desc": args.desc,
             "champion": champ_meta.get("name"), "champion_id": champ_meta.get("id"), "gate": result,
             "uploaded": False}
    if result["verdict"] in ("pass", "trial") and not args.dry_run:
        if champ_meta.get("id"):
            champ_now = client.get(f"/submissions/{champ_meta['id']}")
            entry["champion_rating"] = champ_now.get("rating")
            entry["champion_games"] = champ_now["wins"] + champ_now["draws"] + champ_now["losses"]
        # WORKFLOW: every version gets at least 1 hour live before the next one is published. On Oct 3 a gate that
        # reused its screen games passed at once and replaced v64 after 28 minutes; now the upload waits.
        live_since = None
        for e in reversed(releases()):
            if e.get("uploaded") and e.get("submission_id") == champ_meta.get("id"):
                live_since = dt.datetime.fromisoformat(e["at"])
                break
        if live_since is not None:
            wait = (live_since + dt.timedelta(hours=1) - dt.datetime.now()).total_seconds()
            if wait > 0:
                print(f"the live version went up at {live_since:%H:%M}; waiting {wait / 60:.0f} min for its hour (WORKFLOW)", flush=True)
                time.sleep(wait)
        before = {s["id"] for s in client.get("/submissions")}
        folder = snapshot(pathlib.Path(args.candidate), args.name)
        note = (f"{args.desc} | gate vs {champ_meta['name']}: {result['score']:.2f} "
                f"[{result['lo']:.2f},{result['hi']:.2f}] over {result['games']} games "
                f"(pool {result['pool']:.2f}, new maps {result.get('new_maps', 0):.2f}, generated {result['unseen']:.2f}), "
                f"max CPU {result['max_cpu'] / 1e6:.0f}M"
                + (" | ladder trial" if result["verdict"] == "trial" else ""))
        upload(folder, args.name, note[:1000])
        entry.update({"uploaded": True, "snapshot": str(folder), "note": note,
                      "trial": "awaiting duel"})  # WORKFLOW 6.2: lab.duel judges it (lab.trial's ranked trial reverted v66 after 10 min on Oct 3)
        sub = find_upload(client, args.name, before)
        if sub:
            entry.update({"submission_id": sub["id"], "status": sub.get("status")})
            print(f"submission {sub['id']} is {sub.get('status')}; judge it with: python -m lab.trial")
    log = releases()
    log.append(entry)
    save_log(log)
    return 0 if result["verdict"] in ("pass", "trial") else 1


if __name__ == "__main__":
    sys.exit(main())
