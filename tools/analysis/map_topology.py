"""Dead ends of a map, exactly, from its graph (Ben, Oct 11: "start with Tarjan's algorithm").

Tiles are nodes; every open side and every portal link is an edge (GameMap.step). Tarjan's DFS (iterative) finds the
articulation points: a vertex a is one when some DFS child c has low[c] >= disc[a], and removing a then cuts c's subtree
off from the rest. For every such cut, the smaller side is a dead-end region of exactly that many tiles; each tile keeps
the size of the tightest dead end it lies in (0 = in the open core). Small separate components (e.g. Schooltime's sealed
2x2 queen boxes) count as dead ends of their own size.

    dead_ends(GameMap) -> {(x, y): size}
    python analysis/map_topology.py [map file ...]    (prints a summary per map)
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lab.common import DATA, GameMap  # noqa: E402

MAX_DEAD_END = 200  # larger cut-off regions are parts of the map, not traps (a 63-long queen's trap cap is 3*63+10)


def graph(m: GameMap) -> dict[tuple, set]:
    adj: dict[tuple, set] = {}
    for y in range(m.height):
        for x in range(m.width):
            for d in "NESW":
                t = m.step(x, y, d)
                if t is not None and t != (x, y):
                    adj.setdefault((x, y), set()).add(t)
                    adj.setdefault(t, set()).add((x, y))
    return adj


def dead_ends(m: GameMap) -> dict[tuple, int]:
    adj = graph(m)
    disc: dict[tuple, int] = {}
    low: dict[tuple, int] = {}
    sub: dict[tuple, int] = {}
    order: list[tuple] = []          # preorder: subtree of v = order[disc[v] : disc[v] + sub[v]]
    comps: list[tuple[int, int]] = []  # (first preorder index, size) per connected component
    cuts: list[tuple[int, int, int]] = []  # (cut vertex preorder index, child preorder start, child subtree size)
    for root in adj:
        if root in disc:
            continue
        start = len(order)
        disc[root] = low[root] = len(order)
        order.append(root)
        stack = [(root, None, iter(adj[root]))]
        while stack:
            v, parent, it = stack[-1]
            nxt = next(it, None)
            if nxt is not None:
                if nxt not in disc:
                    disc[nxt] = low[nxt] = len(order)
                    order.append(nxt)
                    stack.append((nxt, v, iter(adj[nxt])))
                elif nxt != parent:
                    low[v] = min(low[v], disc[nxt])
                continue
            stack.pop()
            sub[v] = len(order) - disc[v]
            if parent is not None:
                low[parent] = min(low[parent], low[v])
                if low[v] >= disc[parent]:
                    cuts.append((disc[parent], disc[v], sub[v]))
        comps.append((start, len(order) - start))
    biggest = max((size for _, size in comps), default=0)
    size_of = {}
    for start, size in comps:
        for k in range(start, start + size):
            size_of[k] = (start, size)
    best: dict[int, int] = {}
    for cut, cs, csize in cuts:
        start, total = size_of[cs]
        other = total - 1 - csize          # tiles on the far side of the cut vertex
        if other <= 0 or csize <= 0:       # a DFS root with one branch: nothing is cut off
            continue
        if csize <= other:
            for k in range(cs, cs + csize):
                best[k] = min(best.get(k, 1 << 30), csize)
        else:
            # the side holding the DFS root (and the cut vertex's other branches) is the smaller one;
            # the cut vertex itself sits between the two sides and belongs to neither
            for k in range(start, start + total):
                if cs <= k < cs + csize or k == cut:
                    continue
                best[k] = min(best.get(k, 1 << 30), other)
    for start, size in comps:
        if size < biggest // 4:
            for k in range(start, start + size):
                best[k] = min(best.get(k, 1 << 30), size)
    # Only real dead ends: a cut that halves the map (Trauma: two ~570-tile halves joined at one tile) is not one.
    return {order[k]: v for k, v in best.items() if v <= min(MAX_DEAD_END, size_of[k][1] // 4)}


def corridors(m: GameMap) -> dict[tuple, tuple[int, bool]]:
    """One-wide corridors: maximal chains of tiles with exactly two neighbours (portals count). For each such tile:
    (length of its chain, True if one end of the chain is a dead end / the chain closes on itself)."""
    adj = graph(m)
    deg2 = {t for t, n in adj.items() if len(n) == 2}
    out: dict[tuple, tuple[int, bool]] = {}
    seen: set = set()
    for t in deg2:
        if t in seen:
            continue
        chain = [t]
        seen.add(t)
        ends = []
        for first in adj[t]:
            prev, cur = t, first
            while cur in deg2 and cur not in seen:
                seen.add(cur)
                chain.append(cur)
                prev, cur = cur, next(x for x in adj[cur] if x != prev)
            ends.append(cur)
        dead = any(len(adj.get(e, ())) <= 1 for e in ends) or any(e in deg2 for e in ends)
        for c in chain:
            out[c] = (len(chain), dead)
    return out


def main() -> int:
    paths = [pathlib.Path(a) for a in sys.argv[1:]] or sorted((DATA / "maps_current").glob("*.map"))
    for p in paths:
        m = GameMap.parse(p.read_text())
        de = dead_ends(m)
        tiles = len(graph(m))
        sizes = sorted(set(de.values()))
        co = corridors(m)
        long_c = sorted({ln for ln, _ in co.values()}, reverse=True)[:5]
        print(f"{m.name:26s} tiles {tiles:4d}, in a dead end {len(de):4d} ({len(de) / max(tiles, 1):4.0%}), sizes "
              f"{sizes[:6]}{' ...' if len(sizes) > 6 else ''}; corridor tiles {len(co):4d} ({len(co) / max(tiles, 1):3.0%}), "
              f"longest chains {long_c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
