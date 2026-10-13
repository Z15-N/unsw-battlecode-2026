"""Run a queue of lab steps one after another, detached from any terminal (no tool time limits).

    python -m lab.chain <queue.json>

The queue is a JSON list of steps:
  {"wait_for": "<log path>", "pattern": "<regex>"}          wait until the log matches
  {"run": ["-m", "lab.screen", ...], "log": "<log path>"}    run python with these args, output to the log
  {"duel_after_release": "<release log>", "champion": 15411, "log": "<duel log>"}
                                                              when the release log names its new submission, duel it
Progress goes to data/logs/chain.log.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import time

from .common import DATA

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOG = DATA / "logs" / "chain.log"


def say(msg: str) -> None:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%dT%H:%M:%S ") + msg + "\n")


def wait_for(path: str, pattern: str, timeout_h: float = 12) -> bool:
    end = time.time() + timeout_h * 3600
    rx = re.compile(pattern)
    while time.time() < end:
        p = pathlib.Path(path)
        if p.is_file() and rx.search(p.read_text(encoding="utf-8", errors="replace")):
            return True
        time.sleep(20)
    return False


def main(argv=None) -> int:
    queue = json.loads(pathlib.Path((argv or sys.argv[1:])[0]).read_text(encoding="utf-8"))
    for step in queue:
        if "wait_for" in step:
            say(f"waiting for /{step['pattern']}/ in {step['wait_for']}")
            if not wait_for(step["wait_for"], step["pattern"]):
                say("timed out; stopping the chain")
                return 1
        elif "run" in step:
            say("running python " + " ".join(step["run"]))
            with open(step["log"], "w", encoding="utf-8") as out:
                rc = subprocess.call([sys.executable] + step["run"], cwd=ROOT, stdout=out, stderr=subprocess.STDOUT)
            say(f"finished (exit {rc}) -> {step['log']}")
        elif "duel_after_release" in step:
            if not wait_for(step["duel_after_release"], r"submission \d+ is |GATE FAIL"):
                say("release never finished; no duel")
                continue
            text = pathlib.Path(step["duel_after_release"]).read_text(encoding="utf-8", errors="replace")
            m = re.search(r"submission (\d+) is ", text)
            if not m:
                say("release failed its gate; no duel")
                continue
            say(f"starting the duel of submission {m.group(1)} vs {step['champion']} (detached)")
            out = open(step["log"], "w", encoding="utf-8")
            subprocess.Popen([sys.executable, "-m", "lab.duel", "--candidate", m.group(1), "--champion", str(step["champion"]), "--dev"],
                             cwd=ROOT, stdout=out, stderr=subprocess.STDOUT)
    say("chain done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
