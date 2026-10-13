"""Entry point for the Windows scheduled task "battlecode-trial" (every 10 min, no console window).

One look at the running ladder trial: spend ranked scrims, keep or revert when it is due.
Output goes to data/logs/trial.log.
"""

import contextlib
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from lab import trial  # noqa: E402
from lab.common import DATA  # noqa: E402

if __name__ == "__main__":
    log = DATA / "logs" / "trial.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as out, contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        print(f"--- {dt.datetime.now().isoformat(timespec='seconds')}")
        try:
            trial.main(["--once"])
        except BaseException as error:  # a failed look must not kill the schedule
            print(f"trial task failed: {error!r}")
