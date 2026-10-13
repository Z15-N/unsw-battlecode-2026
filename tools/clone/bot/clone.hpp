// Shared by the imitation bot (main.cpp) and the training extractor
// (tools/clone/extract/extract.cpp): one parser, one memory, one feature
// function, so what the model is trained on is exactly what it sees in a game.
#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "known_maps.hpp"

namespace mimic {

constexpr int R = 3;                 // vision radius
constexpr int V = 7;                 // vision size
constexpr int CELLS = V * V;
constexpr int GRID_CHANNELS = 14;
constexpr int MAP_SLOTS = 16;        // known maps + "unknown"
constexpr int MOVE_FEATURES = 7;
constexpr int SCALARS = 4 + 2 + 2 + 1 + 1 + 1 + 1 + MAP_SLOTS + 2 + 1 + 6 + 1 + 1;
constexpr int FEATURES = CELLS * GRID_CHANNELS + SCALARS + 4 * MOVE_FEATURES;
constexpr int ACTIONS = 5;           // N, E, S, W, split
constexpr char DIRS[4] = {'N', 'E', 'S', 'W'};
constexpr int DX[4] = {0, 1, 0, -1};
constexpr int DY[4] = {-1, 0, 1, 0};

inline int dir_index(char c) {
    switch (c) {
    case 'N': return 0;
    case 'E': return 1;
    case 'S': return 2;
    default: return 3;
    }
}

enum EdgeKind : std::int8_t { OPEN = 0, KELP = 1, PORTAL = 2, UNKNOWN = 3 };

struct Part {
    char team;
    int id, x, y;
    char facing;
    bool head;
};

struct Init {
    int id = 0;
    char team = 'A';
    int w = 0, h = 0, unit_limit = 64;
};

struct Obs {
    int round = 0;
    char dir = 'N';
    int length = 0, units = 0;
    std::vector<std::uint64_t> msgs;
    bool has_echoes = false;
    int echoes[5] = {0, 0, 0, 0, 0};
    int tx[CELLS], ty[CELLS], pearl[CELLS], ptime[CELLS];
    std::vector<Part> parts;
    std::int8_t hk[V + 1][V], vk[V][V + 1];      // edge kinds
    int hp[V + 1][V], vp[V][V + 1];              // portal ids (-1 if none)
    int hx = 0, hy = 0;                          // our head
};

// ---------------------------------------------------------------- parsing
struct Reader {
    std::FILE* in;
    std::string line;
    explicit Reader(std::FILE* f) : in(f) {}

    // Next non-empty line with comments stripped; false at EOF.
    bool next() {
        char buf[4096];
        while (std::fgets(buf, sizeof buf, in)) {
            line.assign(buf);
            auto hash = line.find('#');
            if (hash != std::string::npos) line.erase(hash);
            while (!line.empty() && (line.back() == '\n' || line.back() == '\r' || line.back() == ' '))
                line.pop_back();
            std::size_t start = line.find_first_not_of(' ');
            if (start == std::string::npos) continue;
            if (start) line.erase(0, start);
            return true;
        }
        return false;
    }
};

inline bool starts(const std::string& s, const char* p) { return s.rfind(p, 0) == 0; }

inline bool read_init(Reader& r, Init& init) {
    int got = 0;
    while (got < 4 && r.next()) {
        const char* s = r.line.c_str();
        if (starts(r.line, "ID ")) { init.id = std::atoi(s + 3); got++; }
        else if (starts(r.line, "TEAM ")) { init.team = s[5]; got++; }
        else if (starts(r.line, "MAP ")) { std::sscanf(s + 4, "%d %d", &init.w, &init.h); got++; }
        else if (starts(r.line, "UNIT_LIMIT ")) { init.unit_limit = std::atoi(s + 11); got++; }
    }
    return got == 4;
}

inline void parse_edge(const char* tok, std::int8_t& kind, int& pid) {
    if (tok[0] == '.') { kind = OPEN; pid = -1; }
    else if (tok[0] == 'w') { kind = KELP; pid = -1; }
    else { kind = PORTAL; pid = std::atoi(tok); }
}

// Reads one round block; false at EOF or ENDGAME. `self_id` locates our head.
inline bool read_round(Reader& r, int self_id, Obs& o) {
    if (!r.next() || starts(r.line, "ENDGAME")) return false;
    if (!starts(r.line, "ROUND")) return false;
    o.round = std::atoi(r.line.c_str() + 6);
    r.next(); o.dir = r.line[4];
    r.next(); o.length = std::atoi(r.line.c_str() + 7);
    r.next(); o.units = std::atoi(r.line.c_str() + 11);
    r.next(); int n = std::atoi(r.line.c_str() + 9);
    o.msgs.clear();
    for (int i = 0; i < n; i++) { r.next(); o.msgs.push_back(std::strtoull(r.line.c_str(), nullptr, 10)); }
    r.next();
    o.has_echoes = false;
    if (starts(r.line, "ECHOES")) {
        o.has_echoes = true;
        std::sscanf(r.line.c_str() + 7, "%d %d %d %d %d", &o.echoes[0], &o.echoes[1], &o.echoes[2],
                    &o.echoes[3], &o.echoes[4]);
        r.next();
    }
    for (int i = 0; i < CELLS; i++) {
        if (i) r.next();
        std::sscanf(r.line.c_str(), "%d %d %d %d", &o.tx[i], &o.ty[i], &o.pearl[i], &o.ptime[i]);
    }
    r.next();
    int parts = std::atoi(r.line.c_str() + 14);
    o.parts.clear();
    for (int i = 0; i < parts; i++) {
        r.next();
        Part p{};
        char team, facing;
        int head;
        std::sscanf(r.line.c_str(), "%c %d %d %d %c %d", &team, &p.id, &p.x, &p.y, &facing, &head);
        p.team = team; p.facing = facing; p.head = head == 1;
        if (p.head && p.id == self_id) { o.hx = p.x; o.hy = p.y; }
        o.parts.push_back(p);
    }
    char tok[32];
    for (int y = 0; y <= V; y++) {
        r.next();
        const char* s = r.line.c_str();
        for (int x = 0; x < V; x++) {
            int used = 0;
            std::sscanf(s, "%31s%n", tok, &used);
            s += used;
            parse_edge(tok, o.hk[y][x], o.hp[y][x]);
        }
    }
    for (int y = 0; y < V; y++) {
        r.next();
        const char* s = r.line.c_str();
        for (int x = 0; x <= V; x++) {
            int used = 0;
            std::sscanf(s, "%31s%n", tok, &used);
            s += used;
            parse_edge(tok, o.vk[y][x], o.vp[y][x]);
        }
    }
    return true;
}

// ---------------------------------------------------------------- world memory
struct World {
    Init init;
    int w = 0, h = 0;
    int map_slot = MAP_SLOTS - 1;       // identified known map, or "unknown"
    bool identified = false;
    std::vector<int> candidates;        // known maps still consistent with what we saw
    std::vector<std::int8_t> hedge, vedge;   // [y*w+x] north / west edge of each tile
    std::vector<int> hport, vport;           // portal ids
    std::vector<int> partner;           // for a portal edge slot (2*cell + v): where you come out
    std::vector<int> pearl_seen;        // round a pearl was last seen at the tile, -1 none
    std::vector<std::int8_t> spawnable; // -1 unknown, 0 never, 1 spawns
    int last_action = -1;               // 0..3 moves, 4 split
    int turns = 0;

    void reset(const Init& i) {
        init = i;
        w = i.w; h = i.h;
        identified = false;
        map_slot = MAP_SLOTS - 1;
        candidates.clear();
        for (int k = 0; k < known::map_count; k++)
            if (known::maps[k].w == w && known::maps[k].h == h) candidates.push_back(k);
        hedge.assign(w * h, UNKNOWN); vedge.assign(w * h, UNKNOWN);
        hport.assign(w * h, -1); vport.assign(w * h, -1);
        partner.assign(2 * w * h, -1);
        pearl_seen.assign(w * h, -1);
        spawnable.assign(w * h, -1);
        last_action = -1;
        turns = 0;
    }

    int cell(int x, int y) const { return ((y % h + h) % h) * w + ((x % w + w) % w); }

    void adopt_known(int k) {
        const auto& m = known::maps[k];
        identified = true;
        map_slot = std::min(k, MAP_SLOTS - 2);
        for (int i = 0; i < w * h; i++) {
            hedge[i] = m.hedge[i] == 'w' ? KELP : m.hedge[i] == 'p' ? PORTAL : OPEN;
            vedge[i] = m.vedge[i] == 'w' ? KELP : m.vedge[i] == 'p' ? PORTAL : OPEN;
        }
        for (int a = 0; a < m.portal_count; a++) {
            const auto& p = m.portals[a];
            (p.orient == 'h' ? hport : vport)[cell(p.x, p.y)] = p.id;
        }
        link_portals();
    }

    // For each portal edge, the partner edge with the same id.
    void link_portals() {
        std::vector<std::pair<int, int>> ends;   // (id, slot) slot = 2*cell + (v ? 1 : 0)
        for (int c = 0; c < w * h; c++) {
            if (hedge[c] == PORTAL && hport[c] >= 0) ends.push_back({hport[c], 2 * c});
            if (vedge[c] == PORTAL && vport[c] >= 0) ends.push_back({vport[c], 2 * c + 1});
        }
        std::sort(ends.begin(), ends.end());
        for (std::size_t i = 0; i + 1 < ends.size(); i++)
            if (ends[i].first == ends[i + 1].first) {
                partner[ends[i].second] = ends[i + 1].second;
                partner[ends[i + 1].second] = ends[i].second;
            }
    }

    void observe(const Obs& o) {
        // Edges from the window into memory, and check map candidates.
        bool changed_portals = false;
        for (int r = 0; r <= V; r++)
            for (int c = 0; c < V; c++) {
                int x = o.hx - R + c, y = o.hy - R + r;
                int id = cell(x, y);
                if (!identified) {
                    if (hedge[id] != PORTAL && o.hk[r][c] == PORTAL) changed_portals = true;
                    hedge[id] = o.hk[r][c]; hport[id] = o.hp[r][c];
                }
            }
        for (int r = 0; r < V; r++)
            for (int c = 0; c <= V; c++) {
                int x = o.hx - R + c, y = o.hy - R + r;
                int id = cell(x, y);
                if (!identified) {
                    if (vedge[id] != PORTAL && o.vk[r][c] == PORTAL) changed_portals = true;
                    vedge[id] = o.vk[r][c]; vport[id] = o.vp[r][c];
                }
            }
        if (!identified && !candidates.empty()) {
            std::vector<int> keep;
            for (int k : candidates) {
                const auto& m = known::maps[k];
                bool ok = true;
                for (int r = 0; r <= V && ok; r++)
                    for (int c = 0; c < V && ok; c++) {
                        char e = m.hedge[cell(o.hx - R + c, o.hy - R + r)];
                        int kind = e == 'w' ? KELP : e == 'p' ? PORTAL : OPEN;
                        ok = kind == o.hk[r][c];
                    }
                for (int r = 0; r < V && ok; r++)
                    for (int c = 0; c <= V && ok; c++) {
                        char e = m.vedge[cell(o.hx - R + c, o.hy - R + r)];
                        int kind = e == 'w' ? KELP : e == 'p' ? PORTAL : OPEN;
                        ok = kind == o.vk[r][c];
                    }
                if (ok) keep.push_back(k);
            }
            candidates = keep;
            if (candidates.size() == 1) adopt_known(candidates[0]);
        }
        if (changed_portals && !identified) link_portals();
        for (int i = 0; i < CELLS; i++) {
            int id = cell(o.tx[i], o.ty[i]);
            spawnable[id] = o.ptime[i] == -1 ? 0 : 1;
            pearl_seen[id] = o.pearl[i] ? o.round : -1;
        }
        turns++;
    }

    // The tile one step from (x, y) towards d, through portals; -1 if kelp.
    int step(int x, int y, int d) const {
        int c = cell(x, y);
        int slot;
        std::int8_t kind;
        switch (d) {
        case 0: slot = 2 * c; kind = hedge[c]; break;
        case 2: { int s = cell(x, y + 1); slot = 2 * s; kind = hedge[s]; break; }
        case 3: slot = 2 * c + 1; kind = vedge[c]; break;
        default: { int s = cell(x + 1, y); slot = 2 * s + 1; kind = vedge[s]; break; }
        }
        if (kind == KELP) return -1;
        if (kind == PORTAL && partner[slot] >= 0) {
            int other = partner[slot] / 2;
            int ox = other % w, oy = other / w;
            switch (d) {
            case 0: return cell(ox, oy - 1);
            case 2: return cell(ox, oy);
            case 3: return cell(ox - 1, oy);
            default: return cell(ox, oy);
            }
        }
        return cell(x + DX[d], y + DY[d]);
    }
};

// ---------------------------------------------------------------- features
struct Scratch {
    std::vector<int> dist, queue;
    std::vector<std::int8_t> blocked;
};

// Breadth-first search from `start` over remembered edges with `blocked` cells;
// returns the distance to the nearest remembered pearl and the reachable count.
inline void search(const World& wd, Scratch& s, int start, int limit, int& pearl_dist, int& reach) {
    const int n = wd.w * wd.h;
    s.dist.assign(n, -1);
    s.queue.clear();
    s.dist[start] = 0;
    s.queue.push_back(start);
    pearl_dist = -1;
    reach = 0;
    for (std::size_t qi = 0; qi < s.queue.size(); qi++) {
        int c = s.queue[qi];
        reach++;
        if (pearl_dist < 0 && wd.pearl_seen[c] >= 0 && s.dist[c] > 0) pearl_dist = s.dist[c];
        if (s.dist[c] >= limit) continue;
        int x = c % wd.w, y = c / wd.w;
        for (int d = 0; d < 4; d++) {
            int nx = wd.step(x, y, d);
            if (nx < 0 || s.dist[nx] >= 0 || s.blocked[nx]) continue;
            s.dist[nx] = s.dist[c] + 1;
            s.queue.push_back(nx);
        }
    }
}

struct Features {
    float v[FEATURES];
    bool deadly[4];           // kelp, a body segment that will still be there, or our own neck
    int reach[4];             // cells reachable after the move (capped), 0 if deadly
    bool can_split;
};

inline void features(const World& wd, const Obs& o, Scratch& s, Features& f) {
    std::fill(std::begin(f.v), std::end(f.v), 0.0f);
    const int me = wd.init.id;
    const char team = wd.init.team;
    // window cell index from absolute coords
    auto window = [&](int x, int y) -> int {
        int c = ((x - (o.hx - R)) % wd.w + wd.w) % wd.w;
        int r = ((y - (o.hy - R)) % wd.h + wd.h) % wd.h;
        return (c < V && r < V) ? r * V + c : -1;
    };
    // own body order: we only know segments, not their order, so measure each
    // segment's distance to our head along the body by walking facings back.
    std::vector<int> own_rank(CELLS, -1);
    {
        // segments of ours by cell, then walk from head following "who points to me"
        std::vector<int> mine(CELLS, -1);
        std::vector<char> face(CELLS, 0);
        for (const auto& p : o.parts)
            if (p.id == me) { int k = window(p.x, p.y); if (k >= 0) { mine[k] = 1; face[k] = p.facing; } }
        int k = window(o.hx, o.hy), rank = 0;
        while (k >= 0 && own_rank[k] < 0) {
            own_rank[k] = rank++;
            int r = k / V, c = k % V, next = -1;
            for (int d = 0; d < 4; d++) {
                int nr = r - DY[d], nc = c - DX[d];        // neighbour that faces towards us
                if (nr < 0 || nr >= V || nc < 0 || nc >= V) continue;
                int nk = nr * V + nc;
                if (mine[nk] == 1 && own_rank[nk] < 0 && face[nk] == DIRS[d]) { next = nk; break; }
            }
            k = next;
        }
    }
    s.blocked.assign(wd.w * wd.h, 0);
    for (int i = 0; i < CELLS; i++) {
        float* g = f.v + i * GRID_CHANNELS;
        int r = i / V, c = i % V;
        g[0] = o.pearl[i] ? 1.f : 0.f;
        g[1] = o.ptime[i] != -1 ? 1.f : 0.f;
        g[2] = o.hk[r][c] == KELP;
        g[3] = o.vk[r][c + 1] == KELP;
        g[4] = o.hk[r + 1][c] == KELP;
        g[5] = o.vk[r][c] == KELP;
        g[6] = (o.hk[r][c] == PORTAL || o.vk[r][c + 1] == PORTAL || o.hk[r + 1][c] == PORTAL ||
                o.vk[r][c] == PORTAL);
    }
    for (const auto& p : o.parts) {
        int k = window(p.x, p.y);
        if (k < 0) continue;
        float* g = f.v + k * GRID_CHANNELS;
        bool ours = p.team == team;
        bool queen = p.id <= 1;
        if (p.id == me) {
            if (!p.head) {
                int rank = own_rank[k] >= 0 ? own_rank[k] : o.length - 1;
                g[7] = std::min(o.length - rank, 16) / 16.f;     // turns until this cell frees
            }
        } else if (ours) {
            g[p.head ? 9 : 8] = 1.f;
        } else {
            g[p.head ? 11 : 10] = 1.f;
        }
        if (queen) g[ours ? 12 : 13] = 1.f;
        bool own_tail = p.id == me && own_rank[k] == o.length - 1 && o.length > 1;
        if (!own_tail) s.blocked[wd.cell(p.x, p.y)] = 1;
    }
    // scalars
    float* sc = f.v + CELLS * GRID_CHANNELS;
    int at = 0;
    sc[at + dir_index(o.dir)] = 1.f; at += 4;
    sc[at++] = std::min(o.length, 64) / 32.f;
    sc[at++] = std::log((float)std::max(o.length, 1)) / 4.f;
    sc[at++] = o.round / 500.f;
    sc[at++] = o.round >= 450 ? 1.f : 0.f;
    sc[at++] = o.units / 64.f;
    sc[at++] = me <= 1 ? 1.f : 0.f;                  // queen
    sc[at++] = team == 'A' ? 1.f : 0.f;
    sc[at++] = std::min(me, 64) / 64.f;
    sc[at + wd.map_slot] = 1.f; at += MAP_SLOTS;
    sc[at++] = (float)o.hx / wd.w;
    sc[at++] = (float)o.hy / wd.h;
    int known_pearls = 0;
    for (int v : wd.pearl_seen) known_pearls += v >= 0;
    sc[at++] = std::min(known_pearls, 40) / 40.f;
    if (wd.last_action >= 0) sc[at + wd.last_action] = 1.f;
    at += 5;
    sc[at++] = wd.last_action < 0 ? 1.f : 0.f;
    f.can_split = o.length >= 4 && o.units < wd.init.unit_limit;
    sc[at++] = f.can_split ? 1.f : 0.f;
    sc[at++] = wd.identified ? 1.f : 0.f;
    // per move
    float* mv = sc + SCALARS;
    int head = wd.cell(o.hx, o.hy);
    for (int d = 0; d < 4; d++) {
        float* m = mv + d * MOVE_FEATURES;
        int dest = wd.step(o.hx, o.hy, d);
        bool head_on = false, body = false;
        if (dest >= 0) {
            int k = window(dest % wd.w, dest / wd.w);
            for (const auto& p : o.parts)
                if (wd.cell(p.x, p.y) == dest) {
                    if (p.head && p.id != me && p.team != team) head_on = true;
                    else body = true;           // our own tail too: it has not moved yet
                }
            (void)k;
        }
        f.deadly[d] = dest < 0 || body;
        f.reach[d] = 0;
        m[0] = f.deadly[d] ? 1.f : 0.f;
        m[1] = head_on ? 1.f : 0.f;
        if (dest < 0 || body || head_on) continue;
        int k = window(dest % wd.w, dest / wd.w);
        m[2] = (k >= 0 && o.pearl[k]) ? 1.f : 0.f;
        // our head cell becomes body after the move
        std::int8_t was = s.blocked[head];
        s.blocked[head] = 1;
        int pearl_dist, reach;
        search(wd, s, dest, 24, pearl_dist, reach);
        s.blocked[head] = was;
        f.reach[d] = reach;
        m[3] = std::min(reach, 128) / 128.f;
        m[4] = pearl_dist < 0 ? 1.f : std::min(pearl_dist, 24) / 24.f;
        m[5] = pearl_dist < 0 ? 1.f : 0.f;
        // enemy heads that could meet us next turn
        int threats = 0;
        for (const auto& p : o.parts)
            if (p.head && p.team != team) {
                int dx = std::abs(((p.x - dest % wd.w) % wd.w + wd.w + wd.w / 2) % wd.w - wd.w / 2);
                int dy = std::abs(((p.y - dest / wd.w) % wd.h + wd.h + wd.h / 2) % wd.h - wd.h / 2);
                if (dx + dy <= 2) threats++;
            }
        m[6] = std::min(threats, 3) / 3.f;
    }
}

} // namespace mimic
