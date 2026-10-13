"""Write a bot's maps.hpp: every known map's pearl timers, edges and symmetry.

    python tools/gen_maps.py candidates/v48/maps.hpp [source maps folder; default maps/]

Each map is read from data/maps_current (the server's /maps text, saved Oct 10) when it is there, else from the source
folder (the toolkit-only maps: big_empty, default_small, stronghold, Colosseum, arena).

The bot recognises a map by its size, then drops every candidate its view contradicts (identifyMap), so the
order below is the order candidates are tried. Keep the old order and append new maps at the end.
Rebuilt on Oct 2 (the original script was lost); it reproduces v46's maps.hpp byte for byte.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from lab.common import KELP, PORTAL, GameMap  # noqa: E402

ORDER = ["autarky", "big_empty", "default", "default_small", "devil", "dilemma", "queen_of_spades",
         "schooltime", "stronghold", "trauma", "trophy", "portals", "slithery_fight", "Colosseum", "arena"]
# Ben, Oct 10: "No need for unseen maps, we go on full hard code" -- every current server map is known. The 7 Oct 2 maps
# (our blind test set until now) and the 14 maps that appeared after the Oct 9 close follow the old 15, so the old maps'
# indices and same-size candidate order are unchanged.
ORDER += ["stripes", "tower_defense", "islands", "around_unsw", "weakhold", "maze", "australia",
          "athena", "atlantis", "caution", "detention", "ezam", "hive", "maelstrom", "metro", "ouroboros", "thermopylae",
          "troll_australia", "trolley_problem", "trolley_problem_buffed", "whale_song"]
CURRENT = ROOT / "data" / "maps_current"
# v054 (Ben, Oct 11: hard code per map): each queen's home learned from the top teams' replays (analysis/map_plans.py:
# where the queens that survived to r500 on the winning side kept their head in r200-499). Used where at least
# HOME_MIN_GAMES such queens and HOME_MIN_SHARE of their heat within 2 tiles back it; -1 = none (the bot uses her spawn).
PLANS = ROOT / "data" / "map_plans.json"
HOME_MIN_GAMES, HOME_MIN_SHARE = 5, 0.10
# A home farther than this (wrapped Manhattan) from her spawn is not used: on these mirror-symmetric maps the other queen's
# home is at her spawn, so the far ones (Islands 26, Athena 23, Thermopylae 21; 7-16 games) look like noise.
HOME_MAX_DIST = 8
# v055 (Ben's option 3): per map, the tiles where the winning side ate most in r0-300 (analysis/map_farms.py, 80 winning
# games a map), both queen sides merged (the maps are mirror-symmetric), weights 0-1000 against the busiest tile.
FARMS = ROOT / "data" / "map_farms.json"
FARM_TILES = 48
# v056 (Ben, Oct 11: "start with Tarjan's algorithm"): per map, from analysis/map_topology.py, every tile that lies in an
# exact dead end (Tarjan articulation points; the size of the tightest dead-end region) or in a one-wide corridor (chain
# of two-neighbour tiles, portals counted; its length and whether it ends in a dead end). Triples (tile, dead-end size,
# corridor length * 2 + dead-end flag).
sys.path.insert(0, str(ROOT / "tools" / "analysis"))
from map_topology import corridors, dead_ends, graph  # noqa: E402
# v057 (Ben, Oct 11: door sealing, algorithm queue #2): per map and queen id, the smallest door between her home (qhome, else
# her spawn) and the enemy side (every tile within home_cuts.ENEMY_R of the enemy queen's spawn): a minimum vertex cut
# (max-flow, Menger) of at most DOOR_MAX tiles whose sealed room holds >= home_cuts.MIN_ROOM tiles. For each door tile, its
# post: the room-side neighbour nearest home (where a guard stands). -1 = no such door (open maps).
from home_cuts import ENEMY_R, MIN_ROOM, RADII, bfs, min_cut  # noqa: E402
DOOR_MAX = 4
TRAPS = ROOT / "data" / "queen_traps.json"
TRAP_MIN, TRAP_TOP = 3, 16
DOOR_POST_OUTSIDE = True
ROOM_MIN = 12


def doors(m: GameMap, adj: dict, home_tile: int, q: int) -> tuple[list[int], list[int], int]:
    home = (home_tile % m.width, home_tile // m.width) if home_tile >= 0 else tuple(m.dragons[q][1][0])
    enemy = tuple(m.dragons[1 - q][1][0])
    if home not in adj or enemy not in adj:
        return [-1] * DOOR_MAX, [-1] * DOOR_MAX, 0
    dist, edist = bfs(adj, home), bfs(adj, enemy)
    sinks = {t for t, k in edist.items() if k <= ENEMY_R}
    best = None
    smallest = 0   # v059c: the smallest room (>= ROOM_MIN tiles) behind a door of <= DOOR_MAX tiles around her home
    for r in RADII:
        region = {t for t, k in dist.items() if k <= r}
        if region & sinks:
            continue
        size, cut = min_cut(adj, region, sinks)
        if not size or size > DOOR_MAX:
            continue
        walls = set(cut)
        room = bfs({u: [v for v in vs if v not in walls] for u, vs in adj.items() if u not in walls}, home)
        if len(room) >= ROOM_MIN and (smallest == 0 or len(room) < smallest):
            smallest = len(room)
        if len(room) >= MIN_ROOM and (best is None or size < best[0]):
            best = (size, sorted(cut), room)
    if best is None:
        return [-1] * DOOR_MAX, [-1] * DOOR_MAX, smallest
    tiles, posts = [], []
    for (x, y) in best[1]:
        if DOOR_POST_OUTSIDE:
            # v057b: the post is outside the room (v057's inside posts crowded the queen in rooms of ~50 tiles: on the door
            # maps her deaths went 62% -> 71% and the score 0.408 vs v056); the outside neighbour farthest from home
            outside = [v for v in adj[(x, y)] if v not in best[2] and v not in best[1]]
            post = max(outside, key=lambda v: dist.get(v, 0)) if outside else (x, y)
        else:
            inside = [v for v in adj[(x, y)] if v in best[2]]
            post = min(inside, key=lambda v: best[2][v]) if inside else (x, y)
        tiles.append(y * m.width + x)
        posts.append(post[1] * m.width + post[0])
    return tiles + [-1] * (DOOR_MAX - len(tiles)), posts + [-1] * (DOOR_MAX - len(posts)), smallest
ALIAS = {"dilemma": "prisoners_dilemma"}  # our file name -> the server's
SYM = {"y": 0, "x": 1, "xy": 2}  # Oct 9: "y" was 80 (a typo; the bot knows 0-2, and v37-v41 maps.hpp have 0 for the y maps)


def record(i: int, m: GameMap) -> list[str]:
    pal: list[tuple[int, int]] = []
    tiles = []
    for y in range(m.height):
        for x in range(m.width):
            g = m.gaps.get((x, y), (0, 0))
            if g not in pal:
                pal.append(g)
            tiles.append(pal.index(g))
    edges = []
    for y in range(m.height):
        for x in range(m.width):
            t = y * m.width + x
            for d, e in ((0, m.hedge[y][x]), (3, m.vedge[y][x])):
                if e.kind == KELP:
                    edges.append((t * 4 + d, 1, -1))
                elif e.kind == PORTAL:
                    edges.append((t * 4 + d, 2, e.portal))
    edge_text = ",".join(f"{{{c},{k},{p}}}" for c, k, p in edges) or "{0,0,0}"
    return [f"static const int pal{i}[] = {{{','.join(str(v) for g in pal for v in g)}}};",
            f"static const unsigned char tile{i}[] = {{{','.join(map(str, tiles))}}};",
            f"static const EdgeRec edge{i}[] = {{{edge_text}}};"], len(pal), len(edges)


def main(out: str, src: pathlib.Path | None = None) -> None:
    src = src or (ROOT / "maps")
    lines = ["// Generated by tools/gen_maps.py from the bundled competition maps. Do not edit.", "#pragma once", "",
             "namespace maps {", "",
             "struct EdgeRec { int code; signed char kind; int pid; };",
             "struct MapRec { const char* name; int W, H, sym; int nPal; const int* pal; const unsigned char* tile;"
             " int nEdges; const EdgeRec* edges; int qhome[2]; int nFarm; const int* farm; int nTopo; const int* topo;"
             " int door[2][4]; int doorPost[2][4]; int qspawn[2]; int nStart; int qroom[2]; int nTrap; const int* trap; };", ""]
    import json
    plans = json.loads(PLANS.read_text()) if PLANS.is_file() else {}
    traps = json.loads(TRAPS.read_text()) if TRAPS.is_file() else {}
    farms = json.loads(FARMS.read_text()) if FARMS.is_file() else {}
    table = []
    for i, stem in enumerate(ORDER):
        server = CURRENT / f"{ALIAS.get(stem, stem)}.map"
        m = GameMap.parse((server if server.is_file() else src / f"{stem}.map").read_text())
        body, n_pal, n_edges = record(i, m)
        lines += body
        homes = []
        for q in ("0", "1"):
            pl = plans.get(m.name, {}).get(q, {})
            h = pl.get("home")
            sp = m.dragons[int(q)][1][0] if len(m.dragons) > int(q) else (0, 0)
            near = h and (min(abs(h[0] - sp[0]), m.width - abs(h[0] - sp[0])) +
                          min(abs(h[1] - sp[1]), m.height - abs(h[1] - sp[1]))) <= HOME_MAX_DIST
            ok = h and near and pl.get("home_games", 0) >= HOME_MIN_GAMES and pl.get("home_share", 0) >= HOME_MIN_SHARE
            homes.append(h[1] * m.width + h[0] if ok else -1)
        merged = {}
        for q in ("0", "1"):
            for x, y, share in farms.get(m.name, {}).get("farm", {}).get(q, []):
                merged[(x, y)] = merged.get((x, y), 0.0) + share
        top = sorted(merged.items(), key=lambda kv: -kv[1])[:FARM_TILES]
        peak = top[0][1] if top else 1.0
        farm = [v for (x, y), sh in top for v in (y * m.width + x, int(round(1000 * sh / peak)))]
        lines.append(f"static const int farm{i}[] = {{{','.join(map(str, farm)) or '0'}}};")
        de, co = dead_ends(m), corridors(m)
        topo = []
        for (x, y) in sorted(set(de) | set(co), key=lambda t: (t[1], t[0])):
            ln, dead = co.get((x, y), (0, False))
            topo += [y * m.width + x, de.get((x, y), 0), ln * 2 + int(dead)]
        lines.append(f"static const int topo{i}[] = {{{','.join(map(str, topo)) or '0'}}};")
        # v067: tiles where queens of every team died by their own move (analysis/queen_trap_tiles.py, all ranked replays
        # since Oct 10): per queen id the TRAP_TOP tiles with >= TRAP_MIN deaths, as (queen id, tile, deaths) triples.
        tr = []
        for q in ("0", "1"):
            for x, y, n, _ours in sorted(traps.get(m.name, {}).get(q, []), key=lambda r: -r[2])[:TRAP_TOP]:
                if n >= TRAP_MIN:
                    tr += [int(q), y * m.width + x, n]
        lines.append(f"static const int trap{i}[] = {{{','.join(map(str, tr)) or '0'}}};")
        adj = graph(m)
        # v057: each queen's spawn head and the number of starting dragons (teams alternate in file order, so a starter's
        # queen is the one with its id's parity; a later-born dragon compares its birth tile with the spawns)
        qsp = [m.dragons[q][1][0][1] * m.width + m.dragons[q][1][0][0] if len(m.dragons) > q else -1 for q in (0, 1)]
        dr = [doors(m, adj, homes[q], q) if len(m.dragons) > 1 else ([-1] * DOOR_MAX, [-1] * DOOR_MAX, 0) for q in (0, 1)]
        arr = lambda k: "{" + ", ".join("{" + ",".join(map(str, dr[q][k])) + "}" for q in (0, 1)) + "}"
        table.append(f'    {{"{m.name}", {m.width}, {m.height}, {SYM.get(m.symmetry, -1)}, {n_pal}, pal{i}, tile{i}, '
                     f"{n_edges}, edge{i}, {{{homes[0]}, {homes[1]}}}, {len(farm) // 2}, farm{i}, {len(topo) // 3}, topo{i}, "
                     f"{arr(0)}, {arr(1)}, {{{qsp[0]}, {qsp[1]}}}, {len(m.dragons)}, {{{dr[0][2]}, {dr[1][2]}}}, "
                     f"{len(tr) // 3}, trap{i}}}")
    lines += ["", "static const MapRec all[] = {", ",\n".join(table), "};", f"static const int count = {len(ORDER)};",
              "", "} // namespace maps", ""]
    pathlib.Path(out).write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"wrote {out}: {len(ORDER)} maps")


if __name__ == "__main__":
    main(sys.argv[1], pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else None)
