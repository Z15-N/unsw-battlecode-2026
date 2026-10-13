"""Entry point for the Windows scheduled task "battlecode-refresh" (no console window)."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from lab import refresh  # noqa: E402

if __name__ == "__main__":
    sys.exit(refresh.main([]))
