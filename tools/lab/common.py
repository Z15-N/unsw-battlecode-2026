"""Paths, map parsing and replay loading shared by every lab tool."""

from __future__ import annotations

import gzip
import os
import pathlib
import sys
from dataclasses import dataclass, field

# Oct 12 (Ben: "don't bomb my laptop with terminals"): started from a background job, every python.exe process-pool
# worker (arena, sprt, spsa, the analyses) opened its own console window on Windows. Workers start as pythonw.exe
# (no console) instead.
if os.name == "nt":
    import multiprocessing

    _pythonw = pathlib.Path(sys.executable).with_name("pythonw.exe")
    if _pythonw.is_file() and pathlib.Path(sys.executable).name.lower() == "python.exe":
        multiprocessing.set_executable(str(_pythonw))

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
SCHEMA = ROOT / "tools" / "schema" / "replay.capnp"

DIRS = "NESW"
OFFSET = {"N": (0, -1), "E": (1, 0), "S": (0, 1), "W": (-1, 0)}
OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}
CAPNP_DIR = {"north": "N", "east": "E", "south": "S", "west": "W"}

EMPTY, KELP, PORTAL = 0, 1, 2

_schema = None


def schema():
    global _schema
    if _schema is None:
        import capnp

        capnp.remove_import_hook()
        _schema = capnp.load(str(SCHEMA))
    return _schema


def load_replay(source: bytes | str | pathlib.Path):
    """Parse a local (packed capnp) or server (gzip of packed capnp) replay."""
    raw = source if isinstance(source, bytes) else pathlib.Path(source).read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return schema().Replay.from_bytes_packed(raw, traversal_limit_in_words=2**62, nesting_limit=1 << 12)


@dataclass
class Edge:
    kind: int = EMPTY
    portal: int = -1

    def symbol(self) -> str:
        return "." if self.kind == EMPTY else "w" if self.kind == KELP else str(self.portal)


@dataclass
class GameMap:
    width: int
    height: int
    name: str = ""
    symmetry: str = ""
    gaps: dict = field(default_factory=dict)            # (x, y) -> (min_gap, max_gap)
    hedge: list = field(default_factory=list)           # [y][x] north edge of tile (x, y)
    vedge: list = field(default_factory=list)           # [y][x] west edge of tile (x, y)
    portals: dict = field(default_factory=dict)         # id -> [("h"|"v", x, y), ...]
    dragons: list = field(default_factory=list)         # [(team "A"/"B", [(x, y), ...] head first)]

    @staticmethod
    def parse(text: str) -> "GameMap":
        lines = [l.split("#", 1)[0].split() for l in text.splitlines()]
        lines = [l for l in lines if l]
        assert lines[0][0] == "MAP", "map must start with MAP"
        w, h = int(lines[0][1]), int(lines[0][2])
        m = GameMap(w, h)
        m.hedge = [[Edge() for _ in range(w)] for _ in range(h)]
        m.vedge = [[Edge() for _ in range(w)] for _ in range(h)]
        for parts in lines[1:]:
            tag = parts[0]
            if tag == "MAP_NAME":
                m.name = " ".join(parts[1:])
            elif tag == "SYMMETRY":
                m.symmetry = parts[1]
            elif tag == "TILE":
                x, y, lo, hi = map(int, parts[1:5])
                m.gaps[(x % w, y % h)] = (lo, hi)
            elif tag == "EDGE":
                index, kind, pid = int(parts[1]), int(parts[2]), int(parts[3])
                row, x = divmod(index, w + 1)
                if row % 2 == 0:
                    orient, y = "h", (row // 2) % h
                else:
                    orient, y = "v", ((row - 1) // 2) % h
                x %= w
                edge = Edge(kind, pid if kind == PORTAL else -1)
                (m.hedge if orient == "h" else m.vedge)[y][x] = edge
                if kind == PORTAL:
                    m.portals.setdefault(pid, []).append((orient, x, y))
            elif tag == "DRAGON":
                team = "A" if parts[1] == "0" else "B"
                n = int(parts[2])
                coords = list(map(int, parts[3:3 + 2 * n]))
                m.dragons.append((team, [(coords[2 * i] % w, coords[2 * i + 1] % h) for i in range(n)]))
        return m

    def edge(self, x: int, y: int, d: str) -> Edge:
        w, h = self.width, self.height
        if d == "N":
            return self.hedge[y][x]
        if d == "S":
            return self.hedge[(y + 1) % h][x]
        if d == "W":
            return self.vedge[y][x]
        return self.vedge[y][(x + 1) % w]

    def step(self, x: int, y: int, d: str) -> tuple[int, int] | None:
        """Destination of one step, through portals; None if kelp blocks it."""
        w, h = self.width, self.height
        e = self.edge(x, y, d)
        if e.kind == KELP:
            return None
        if e.kind == PORTAL:
            ends = self.portals[e.portal]
            here = ("h" if d in "NS" else "v",) + self._edge_coord(x, y, d)
            other = ends[1] if ends[0] == here else ends[0]
            _, ex, ey = other
            if d == "N":
                return ex, (ey - 1) % h
            if d == "S":
                return ex, ey
            if d == "W":
                return (ex - 1) % w, ey
            return ex, ey
        dx, dy = OFFSET[d]
        return (x + dx) % w, (y + dy) % h

    def _edge_coord(self, x: int, y: int, d: str) -> tuple[int, int]:
        if d == "S":
            return x, (y + 1) % self.height
        if d == "E":
            return (x + 1) % self.width, y
        return x, y

    def pearl_time_default(self, x: int, y: int) -> int:
        lo, hi = self.gaps.get((x, y), (0, 0))
        return -1 if hi == 0 else 0
