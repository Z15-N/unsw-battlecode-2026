"""Battlecode lab: scouting, replay tracking, imitation opponents and match running."""

import sys

# Team names carry emoji and the docs carry maths symbols; Windows consoles and redirected logs default to cp1252.
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
