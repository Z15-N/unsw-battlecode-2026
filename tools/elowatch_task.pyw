"""Entry point for the Windows scheduled task "battlecode-elowatch" (every 30 minutes, no console window)."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from lab import elowatch  # noqa: E402

if __name__ == "__main__":
    sys.exit(elowatch.main([]))
