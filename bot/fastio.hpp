#pragma once
// Fast reader of the engine's wire protocol (https://game.battlecode.au/docs/protocol) into the stock helper's
// Controller / Game / Vision. The stock unswbc::update builds a std::istringstream and a vector<std::string> for each
// of the ~170 lines of a round block, about 1.1M judge points a turn; this reads each line with fgets and splits it in
// place. The parsed contents are the same, so play is unchanged. helper.hpp stays stock, so `unswbc update` may
// replace it freely.
#include "helper.hpp"

#include <cstdio>

namespace fastio {

// One input line split on whitespace. The views point into line_buffer: valid until the next line is read.
struct Tokens {
    static constexpr int MAX = 16;
    std::string_view tok[MAX];
    int n = 0;
    std::string_view operator[](int i) const { return tok[i]; }
};

inline char line_buffer[1 << 12];
inline bool is_space(char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n' || c == '\v' || c == '\f'; }

// Next line with at least one token (blank lines skipped, '#' starts a comment). O(line length). False at EOF.
inline bool next_tokens(Tokens& t) {
    while (std::fgets(line_buffer, sizeof line_buffer, stdin)) {
        t.n = 0;
        char* p = line_buffer;
        while (true) {
            while (is_space(*p)) p++;
            if (*p == '\0' || *p == '#') break;
            char* start = p;
            while (*p != '\0' && *p != '#' && !is_space(*p)) p++;
            if (t.n >= Tokens::MAX) throw std::runtime_error("too many values on a line");
            t.tok[t.n++] = std::string_view(start, static_cast<std::size_t>(p - start));
        }
        if (t.n > 0) return true;
    }
    return false;
}

inline void need_tokens(Tokens& t) {
    if (!next_tokens(t)) throw std::runtime_error("unexpected end of controller input");
}

inline std::string_view labelled(Tokens& t, std::string_view label) {
    need_tokens(t);
    if (t[0] != label) throw std::runtime_error("expected " + std::string(label) + ", got " + std::string(t[0]));
    if (t.n != 2) throw std::runtime_error(std::string(label) + " requires 1 value");
    return t[1];
}

template <typename T> T integer(std::string_view text) { return unswbc::parse_util::parse_integer<T>(text); }

// Same as unswbc::init: full stdout buffer (one write per turn), then the spawn block.
inline std::tuple<unswbc::Controller&, unswbc::Game&> init() {
    using namespace unswbc;
    std::setvbuf(stdout, nullptr, _IOFBF, 1 << 16);
    Tokens t;
    int const dragon_id = integer<int>(labelled(t, "ID"));
    Team const team(parse_util::read_char_safe(labelled(t, "TEAM")));
    need_tokens(t);
    if (t[0] != "MAP" || t.n != 3) throw std::runtime_error("expected MAP width height");
    int const width = integer<int>(t[1]), height = integer<int>(t[2]);
    if (width <= 0 || height <= 0) throw std::runtime_error("map dimensions must be positive");
    int const unit_limit = integer<int>(labelled(t, "UNIT_LIMIT"));
    if (unit_limit <= 0) throw std::runtime_error("UNIT_LIMIT must be positive");
    parse_util::game_storage = std::make_unique<Game>(width, height, unit_limit);
    parse_util::controller_storage = std::make_unique<Controller>(dragon_id, team, Direction::NORTH, Vision{}, unit_limit);
    unswbc::ct = parse_util::controller_storage.get();
    unswbc::game = parse_util::game_storage.get();
    return {*unswbc::ct, *unswbc::game};
}

// Same contract as unswbc::update: reads the next round block, false once the game is over (EOF or ENDGAME).
// O(lines in the block): 49 tiles + visible segments + 15 edge rows + messages.
inline bool update(unswbc::Controller& controller, unswbc::Game& game_state) {
    using namespace unswbc;
    Tokens t;
    if (!next_tokens(t) || t[0] == "ENDGAME") return false;
    if (t.n != 2) throw std::runtime_error("malformed: no round number");
    game_state.round_num = integer<int>(t[1]);

    Direction const current_direction(parse_util::read_char_safe(labelled(t, "DIR")));
    controller.head.dir = current_direction;
    controller.length = integer<int>(labelled(t, "LENGTH"));
    controller.unit_count = integer<int>(labelled(t, "UNIT_COUNT"));
    if (controller.unit_count <= 0 || controller.unit_count > controller.unit_limit)
        throw std::runtime_error("UNIT_COUNT must be between 1 and UNIT_LIMIT");

    int const num_sonar_msgs = integer<int>(labelled(t, "NUM_MSGS"));
    if (num_sonar_msgs < 0) throw std::runtime_error("NUM_MSGS cannot be negative");
    controller.sonar_messages.clear();
    for (int index = 0; index < num_sonar_msgs; index++) {
        need_tokens(t);
        if (t.n != 1) throw std::runtime_error("missing sonar message value");
        controller.sonar_messages.push_back(integer<std::uint64_t>(t[0]));
    }

    need_tokens(t);
    controller.sonar_echoes = {};
    if (t[0] == "ECHOES") {
        if (t.n != 6) throw std::runtime_error("ECHOES requires 5 values");
        controller.sonar_echoes = {integer<int>(t[1]), integer<int>(t[2]), integer<int>(t[3]), integer<int>(t[4]),
                                   integer<int>(t[5])};
        need_tokens(t);
    }

    // Tile index by board position: one stamp per map tile (allocated once) instead of a hash map per turn.
    static std::vector<int> index_of, stamp_of;
    static int stamp = 0;
    int const width = game_state.width, height = game_state.height;
    std::size_t const area = static_cast<std::size_t>(width) * static_cast<std::size_t>(height);
    if (index_of.size() != area) {
        index_of.assign(area, 0);
        stamp_of.assign(area, 0);
    }
    stamp++;
    auto const find_index = [&](int x, int y) -> int {
        if (x < 0 || y < 0 || x >= width || y >= height) return -1;
        std::size_t const key = static_cast<std::size_t>(y) * width + x;
        return stamp_of[key] == stamp ? index_of[key] : -1;
    };

    constexpr int SIDE = Constants::VISION_SIZE;
    std::vector<Tile> tiles;
    tiles.reserve(SIDE * SIDE);
    for (int index = 0; index < SIDE * SIDE; index++) {
        if (index > 0) need_tokens(t);
        if (t.n != 4) throw std::runtime_error("each vision tile requires: x y hasPearl pearlIn");
        int const x = integer<int>(t[0]), y = integer<int>(t[1]);
        int const has_pearl = integer<int>(t[2]), pearl_time = integer<int>(t[3]);
        if (has_pearl != 0 && has_pearl != 1) throw std::runtime_error("hasPearl must be 0 or 1");
        if (x < 0 || y < 0 || x >= width || y >= height) throw std::runtime_error("vision tile outside the map");
        if (find_index(x, y) >= 0) throw std::runtime_error("duplicate vision tile");
        std::size_t const key = static_cast<std::size_t>(y) * width + x;
        stamp_of[key] = stamp;
        index_of[key] = static_cast<int>(tiles.size());
        tiles.emplace_back(Position(x, y), std::nullopt, pearl_time, has_pearl == 1);
    }

    int const num_parts = integer<int>(labelled(t, "DRAGON_BODIES"));
    if (num_parts < 0) throw std::runtime_error("DRAGON_BODIES cannot be negative");
    bool found_head = false;
    for (int index = 0; index < num_parts; index++) {
        need_tokens(t);
        if (t.n != 6) throw std::runtime_error("each dragon part requires: team dragonId x y facing isHead");
        Team const team(parse_util::read_char_safe(t[0]));
        int const dragon_id = integer<int>(t[1]);
        Position const position(integer<int>(t[2]), integer<int>(t[3]));
        Direction const facing(parse_util::read_char_safe(t[4]));
        int const head_flag = integer<int>(t[5]);
        if (head_flag != 0 && head_flag != 1) throw std::runtime_error("isHead must be 0 or 1");
        int const tile = find_index(position.x, position.y);
        if (tile < 0) throw std::runtime_error("dragon part is outside the vision tiles");
        DragonPart part(position, dragon_id, team, facing, head_flag == 1);
        if (dragon_id == controller.get_id() && head_flag == 1) {
            controller.head = part;
            controller.head.dir = current_direction;
            found_head = true;
        }
        tiles[tile].dragon_part = part;
    }
    if (!found_head) throw std::runtime_error("controller head is missing from DRAGON_BODIES");

    Position const head = controller.get_position();
    auto const wrap = [](int value, int size) { return (value % size + size) % size; };
    auto const tile_at = [&](int local_x, int local_y) -> Tile& {
        int const found = find_index(wrap(head.x + local_x - Constants::VISION_RADIUS, width),
                                     wrap(head.y + local_y - Constants::VISION_RADIUS, height));
        if (found < 0) throw std::runtime_error("vision is missing expected tile");
        return tiles[found];
    };
    for (int y = 0; y < SIDE + 1; y++) {  // north edge of each row, then the south edge of the last row
        need_tokens(t);
        if (t.n != SIDE) throw std::runtime_error("horizontal edge row requires 7 values");
        for (int x = 0; x < SIDE; x++) {
            Edge const edge = parse_util::parse_edge(t[x], true);
            if (y > 0) tile_at(x, y - 1).edges[2] = edge;
            if (y < SIDE) tile_at(x, y).edges[0] = edge;
        }
    }
    for (int y = 0; y < SIDE; y++) {      // west edge of each column, then the east edge of the last column
        need_tokens(t);
        if (t.n != SIDE + 1) throw std::runtime_error("vertical edge row requires 8 values");
        for (int x = 0; x < SIDE + 1; x++) {
            Edge const edge = parse_util::parse_edge(t[x], false);
            if (x > 0) tile_at(x - 1, y).edges[1] = edge;
            if (x < SIDE) tile_at(x, y).edges[3] = edge;
        }
    }
    controller.vision = Vision(std::move(tiles)); // the stock constructor indexes the 49 tiles for get_tile()
    return true;
}

} // namespace fastio
