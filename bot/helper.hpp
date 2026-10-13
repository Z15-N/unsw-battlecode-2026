#pragma once

#include <array>
#include <charconv>
#include <cstdint>
#include <cstdio>
#include <iostream>
#include <memory>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <tuple>
#include <unordered_map>
#include <utility>
#include <vector>

namespace unswbc {

// Limits the engine holds every game to.
struct Constants {
    static constexpr int MAX_ROUNDS = 500;
    static constexpr int VISION_RADIUS = 3;
    static constexpr int VISION_SIZE = 2 * VISION_RADIUS + 1;
    static constexpr int INITIAL_LENGTH = 3;
    static constexpr int MIN_SIZE = 2;
    static constexpr int PROTOCOL_MAJOR = 3;
};

// The protocol's direction letters.
class Direction {
  public:
    enum Value : char {
        NORTH = 'N',
        EAST = 'E',
        SOUTH = 'S',
        WEST = 'W'
    };
    Value value;

    // Throws if the letter is not one of N, E, S or W.
    Direction(Value value) : value(value) {
        if (value != NORTH && value != EAST && value != SOUTH && value != WEST)
            throw std::invalid_argument("invalid direction");
    }
    Direction(char value) : Direction(static_cast<Value>(value)) {}
    constexpr bool operator==(Direction const&) const = default;

    // North, east, south and west, in that order.
    static std::array<Direction, 4> get_direction_list() {
        static std::array<Direction, 4> const direction_list{NORTH, EAST, SOUTH, WEST};
        return direction_list;
    }

    // The step this direction makes, as dx east and dy south.
    std::pair<int, int> get_offset() const {
        switch (value) {
        case NORTH: return {0, -1};
        case EAST:  return {1, 0};
        case SOUTH: return {0, 1};
        default:    return {-1, 0};
        }
    }

    Direction get_opposite() const {
        return value == NORTH ? Direction(SOUTH)
             : value == EAST  ? Direction(WEST)
             : value == SOUTH ? Direction(NORTH)
                              : Direction(EAST);
    }
    Direction get_left() const {
        return value == NORTH ? Direction(WEST)
             : value == EAST  ? Direction(NORTH)
             : value == SOUTH ? Direction(EAST)
                              : Direction(SOUTH);
    }
    Direction get_right() const {
        return value == NORTH ? Direction(EAST)
             : value == EAST  ? Direction(SOUTH)
             : value == SOUTH ? Direction(WEST)
                              : Direction(NORTH);
    }
};

inline std::ostream& operator<<(std::ostream& stream, Direction direction) {
    return stream << direction.value;
}

// The protocol's team letters.
class Team {
  public:
    enum Value : char {
        A = 'A',
        B = 'B'
    };
    Value value;

    // Throws if the letter is not A or B.
    Team(Value value) : value(value) {
        if (value != A && value != B)
            throw std::invalid_argument("invalid team");
    }
    Team(char value) : Team(static_cast<Value>(value)) {}
    constexpr bool operator==(Team const&) const = default;

    Team get_enemy_team() const {
        return value == B ? A : B;
    }
};

class Game;
class Controller;

inline Game* game = nullptr;
inline Controller* ct = nullptr;

// Board coordinates, with y growing south from 0 at the top.
struct Position {
    int x = 0, y = 0;

    Position() = default;
    Position(int x, int y) : x(x), y(y) {}
    constexpr bool operator==(Position const&) const = default;

    // The tile one step away, wrapped around the map.
    Position add_dir(Direction direction) const;
    bool is_in_map() const;
    // True if the position is inside the dragon's window this turn.
    bool is_in_vision() const;
};

struct PositionHash {
    std::size_t operator()(Position const& position) const {
        auto const x = static_cast<std::uint32_t>(position.x);
        auto const y = static_cast<std::uint32_t>(position.y);
        return (static_cast<std::uint64_t>(x) << 32U) | y;
    }
};

// The board, and the round being played.
class Game {
  public:
    int round_num = 1;
    int width, height;
    int unit_limit;

    Game(int width, int height, int unit_limit) : width(width), height(height), unit_limit(unit_limit) {}

    int get_round_num() const { return round_num; }
    // Width then height.
    std::pair<int, int> get_map_size() const { return {width, height}; }
    int get_unit_limit() const { return unit_limit; }
};

inline Position Position::add_dir(Direction direction) const {
    if (!game)
        throw std::runtime_error("game is not initialised");
    auto const [dx, dy] = direction.get_offset();
    auto const wrap = [](int value, int size) { return (value % size + size) % size; };
    return {wrap(x + dx, game->width), wrap(y + dy, game->height)};
}

inline bool Position::is_in_map() const {
    if (!game)
        throw std::runtime_error("game is not initialised");
    return x >= 0 && y >= 0 && x < game->width && y < game->height;
}

// A segment of a dragon, standing on a tile.
class DragonPart {
  public:
    Position position;
    int dragon_id;
    Team team;
    Direction dir;
    bool is_dragon_head;

    DragonPart(Position position, int dragon_id, Team team, Direction direction, bool is_dragon_head)
        : position(position), dragon_id(dragon_id), team(team), dir(direction), is_dragon_head(is_dragon_head) {}

    Position get_position() const { return position; }
    int get_id() const { return dragon_id; }
    Team get_team() const { return team; }
    // The way this segment faces.
    // A head's facing is its heading, a body segment's points towards the head.
    Direction get_dir() const { return dir; }
    bool is_head() const { return is_dragon_head; }
};

// What lies on the edge between two tiles.
enum class EdgeType {
    EMPTY,
    KELP,
    PORTAL,
};

// One side of a tile, which a dragon crosses to leave it.
class Edge {
  public:
    bool is_horizontal = false;
    EdgeType edge_type = EdgeType::EMPTY;
    std::optional<int> portal_id;

    Edge() = default;
    Edge(bool is_horizontal, EdgeType edge_type, std::optional<int> portal_id = std::nullopt)
        : is_horizontal(is_horizontal), edge_type(edge_type), portal_id(portal_id) {}

    // False for kelp.
    bool is_passable() const { return edge_type != EdgeType::KELP; }
    // True if crossing the edge teleports the dragon to the partner edge.
    bool is_portal() const { return edge_type == EdgeType::PORTAL; }
    EdgeType get_edge_type() const { return edge_type; }
    // -1 when the edge is not a portal.
    int get_portal_id() const { return portal_id.value_or(-1); }
};

// One of the 49 tiles the dragon can see this turn.
class Tile {
  public:
    Position position;
    int pearl_time = 0;
    bool pearl = false;
    std::optional<DragonPart> dragon_part;
    std::array<Edge, 4> edges{}; // {NORTH, EAST, SOUTH, WEST}

    Tile(Position position, std::optional<DragonPart> dragon_part = std::nullopt, int pearl_time = 0, bool has_pearl = false,
         std::array<Edge, 4> edges = {})
        : position(position), pearl_time(pearl_time), pearl(has_pearl), dragon_part(std::move(dragon_part)),
          edges(std::move(edges)) {}

    Edge const& get_edge(Direction direction) const {
        return edges[get_direction_index(direction)];
    }
    Edge& get_edge(Direction direction) {
        return edges[get_direction_index(direction)];
    }
    // Null if no dragon segment is on the tile.
    DragonPart const* get_dragon() const {
        return dragon_part.has_value() ? &*dragon_part : nullptr;
    }
    DragonPart* get_dragon() {
        return dragon_part.has_value() ? &*dragon_part : nullptr;
    }
    bool has_pearl() const { return pearl; }
    // Rounds until a pearl tries to spawn; -1 if it never does.
    int get_pearl_time() const { return pearl_time; }
    Position get_position() const { return position; }

  private:
    static std::size_t get_direction_index(Direction direction) {
        switch (direction.value) {
        case Direction::NORTH: return 0;
        case Direction::EAST:  return 1;
        case Direction::SOUTH: return 2;
        default:               return 3;
        }
    }
};

// The 7x7 window of tiles the dragon can see.
class Vision {
  public:
    std::vector<Tile> tiles;
    std::unordered_map<Position, std::size_t, PositionHash> tiles_by_position;

    Vision(std::vector<Tile> tiles = {},
           std::unordered_map<Position, std::size_t, PositionHash> tiles_by_position = {})
        : tiles(std::move(tiles)), tiles_by_position(std::move(tiles_by_position)) {
        if (this->tiles_by_position.empty()) {
            for (std::size_t index = 0; index < this->tiles.size(); index++) {
                auto const [_, inserted] = this->tiles_by_position.emplace(this->tiles[index].position, index);
                if (!inserted)
                    throw std::runtime_error("duplicate tile position");
            }
        }
    }

    // Row by row, starting three tiles north and three west of the head.
    std::vector<Tile> const& get_tiles() const { return tiles; }
    
    // Null outside the 7x7 window.
    Tile const* get_tile(Position position) const {
        auto const tile_index = tiles_by_position.find(position);
        return tile_index == tiles_by_position.end() ? nullptr : &tiles[tile_index->second];
    }
    Tile* get_tile(Position position) {
        auto const tile_index = tiles_by_position.find(position);
        return tile_index == tiles_by_position.end() ? nullptr : &tiles[tile_index->second];
    }
};

struct SonarEchoes {
    int kelp = 0;
    int ally = 0;
    int ally_head = 0;
    int enemy = 0;
    int enemy_head = 0;
};

// What the dragon knows about itself and what it can see this turn.
class Controller {
  public:
    int length = Constants::INITIAL_LENGTH;
    int unit_count = 1;
    int unit_limit;
    DragonPart head;
    Vision vision;
    std::vector<std::uint64_t> sonar_messages;
    SonarEchoes sonar_echoes;

    Controller(int dragon_id, Team team, Direction direction, Vision vision, int unit_limit,
               std::vector<std::uint64_t> sonar_messages = {})
        : unit_limit(unit_limit), head(Position(0, 0), dragon_id, team, direction, true),
          vision(std::move(vision)), sonar_messages(std::move(sonar_messages)) {}

    // Segments, head included.
    int get_length() const { return length; }
    // Living dragons on this dragon's team.
    int get_unit_count() const { return unit_count; }
    DragonPart& get_head() { return head; }
    DragonPart const& get_head() const { return head; }
    // Unique within the game, and a split child gets the next one.
    int get_id() const { return head.dragon_id; }
    Team get_team() const { return head.team; }
    Direction get_dir() const { return head.dir; }
    // Where the dragon's head is.
    Position get_position() const { return head.get_position(); }

    Vision& get_vision() { return vision; }
    Vision const& get_vision() const { return vision; }

    std::vector<Tile> const& get_tiles() const { return vision.get_tiles(); }
    // Null outside the 7x7 window.
    Tile const* get_tile(Position position) const { return vision.get_tile(position); }
    Tile* get_tile(Position position) { return vision.get_tile(position); }

    // The last action printed in a turn is the one the engine applies.
    void make_move(Direction direction) {
        std::cout << "MOVE " << direction.value << "\n";
    }
    // One tile per direction, all in this turn.
    // The helper sends whatever you pass. A dragon of length L takes its first
    // ceil(L / 4) steps free and pays a segment for each step after them, and it
    // must keep at least 2 segments.
    void make_moves(std::vector<Direction> const& directions) {
        std::cout << "MOVE ";
        for (Direction direction : directions)
            std::cout << direction.value;
        std::cout << "\n";
    }
    // True if child_size segments can be split off this turn.
    bool can_split(int child_size) const {
        return Constants::MIN_SIZE <= child_size && length - child_size >= Constants::MIN_SIZE && unit_count < unit_limit;
    }
    // Splits child_size segments off the tail as a new dragon.
    // The child is those segments reversed, and takes its own turn later in
    // the same round.
    void do_split(int child_size) {
        std::cout << "SPLIT " << child_size << "\n";
    }
    // Attaches a message to this turn, which the replay shows.
    // Each line costs points, see the Timeouts page.
    template <typename... Messages> void output_log(Messages const&... messages) {
        std::cout << "LOG";
        ((std::cout << " " << messages), ...);
        std::cout << "\n";
    }
    // Draws a dot on the board in the replay.
    void draw_indicator_dot(Position position, int r, int g, int b) {
        std::cout << "DOT " << position.x << " " << position.y << " " << r << " " << g << " " << b << "\n";
    }
    // Draws a line on the board in the replay.
    void draw_indicator_line(Position start, Position end, int r, int g, int b) {
        std::cout << "LINE " << start.x << " " << start.y << " " << end.x << " " << end.y << " " << r << " " << g << " " << b << "\n";
    }
    // Labels the dragon for this turn in the replay.
    void set_indicator_string(std::string_view message) {
        std::cout << "INDICATOR " << message << "\n";
    }
    // This turn's messages, in the order they were sent.
    std::vector<std::uint64_t> get_sonar_messages() const { return sonar_messages; }
    SonarEchoes get_sonar_echoes() const { return sonar_echoes; }
    void send_sonar(Direction direction, std::uint64_t message) {
        std::cout << "SONAR " << static_cast<char>(direction.value) << " " << message << "\n";
    }
    bool send_sonar(std::uint64_t message) {
        if (message > UINT32_MAX)
            return false;
        std::cout << "SONAR " << message << "\n";
        return true;
    }
};

inline bool Position::is_in_vision() const {
    if (!game || !ct)
        throw std::runtime_error("game and controller are not initialised");
    if (!is_in_map())
        return false;
    Position const centre = ct->get_position();
    auto const wrap = [](int value, int size) { return (value % size + size) % size; };
    int const column = wrap(x - (centre.x - Constants::VISION_RADIUS), game->width);
    int const row = wrap(y - (centre.y - Constants::VISION_RADIUS), game->height);
    return column < Constants::VISION_SIZE && row < Constants::VISION_SIZE;
}

namespace parse_util {

inline std::unique_ptr<Controller> controller_storage;
inline std::unique_ptr<Game> game_storage;

inline std::vector<std::string> read_data_line() {
    for (std::string line; std::getline(std::cin, line);) {
        if (auto const comment = line.find('#'); comment != std::string::npos)
            line.erase(comment);
        std::istringstream stream(line);
        std::vector<std::string> parts;
        for (std::string part; stream >> part;)
            parts.push_back(std::move(part));

        if (!parts.empty())
            return parts;
    }
    throw std::runtime_error("unexpected end of controller input");
}

inline std::vector<std::string> read_labelled(std::string_view label, std::size_t value_count = 1) {
    auto parts = read_data_line();
    if (parts.front() != label)
        throw std::runtime_error("expected " + std::string(label) + ", got " + parts.front());
    if (parts.size() != value_count + 1)
        throw std::runtime_error(std::string(label) + " requires " + std::to_string(value_count) + " value(s)");
    parts.erase(parts.begin());
    return parts;
}

template <typename T> T parse_integer(std::string_view text) {
    T value{};
    auto const [end, error] = std::from_chars(text.data(), text.data() + text.size(), value);
    if (error != std::errc{} || end != text.data() + text.size())
        throw std::runtime_error("invalid integer: " + std::string(text));
    return value;
}

inline Edge parse_edge(std::string_view value, bool is_horizontal) {
    if (value == ".")
        return Edge(is_horizontal, EdgeType::EMPTY);
    if (value == "w")
        return Edge(is_horizontal, EdgeType::KELP);
    int const portal_id = parse_integer<int>(value);
    if (portal_id < 0)
        throw std::runtime_error("portal IDs cannot be negative");
    return Edge(is_horizontal, EdgeType::PORTAL, portal_id);
}

inline char read_char_safe(std::string_view str) {
    if (str.empty())
        throw std::runtime_error("expected non-empty character token");
    return str.front();
}

} // end namespace parse_util

// Reads the spawn block. The full buffer it sets is what makes a turn's
// output cost one write.
inline std::tuple<Controller&, Game&> init() {
    // The judge's stdout looks like a terminal, so it is line buffered unless
    // we ask otherwise, and every line costs a write. One buffer, one write a
    // turn, flushed by end_turn. Leave sync_with_stdio alone: it is what puts
    // std::cout through this buffer.
    std::setvbuf(stdout, nullptr, _IOFBF, 1 << 16);
    int const dragon_id = parse_util::parse_integer<int>(parse_util::read_labelled("ID").front());
    Team const team(parse_util::read_char_safe(parse_util::read_labelled("TEAM").front()));

    auto const dimensions = parse_util::read_labelled("MAP", 2);
    int const width = parse_util::parse_integer<int>(dimensions[0]);
    int const height = parse_util::parse_integer<int>(dimensions[1]);
    if (width <= 0 || height <= 0)
        throw std::runtime_error("map dimensions must be positive");
    int const unit_limit = parse_util::parse_integer<int>(parse_util::read_labelled("UNIT_LIMIT").front());
    if (unit_limit <= 0)
        throw std::runtime_error("UNIT_LIMIT must be positive");

    parse_util::game_storage = std::make_unique<Game>(width, height, unit_limit);
    parse_util::controller_storage = std::make_unique<Controller>(dragon_id, team, Direction::NORTH, Vision{}, unit_limit);
    ct = parse_util::controller_storage.get();
    game = parse_util::game_storage.get();
    return {*ct, *game};
}

// Reads the next turn into the controller. False once the game is over or the
// dragon has died.
inline bool update(Controller& controller, Game& game_state) {
    auto const continue_flag = parse_util::read_data_line();
    if (continue_flag.front() == "ENDGAME")
        return false;
    if (continue_flag.size() != 2)
        throw std::runtime_error("malformed: no round number");

    game_state.round_num = parse_util::parse_integer<int>(continue_flag[1]);

    Direction const current_direction(parse_util::read_char_safe(parse_util::read_labelled("DIR").front()));
    controller.head.dir = current_direction;
    controller.length = parse_util::parse_integer<int>(parse_util::read_labelled("LENGTH").front());
    controller.unit_count = parse_util::parse_integer<int>(parse_util::read_labelled("UNIT_COUNT").front());
    if (controller.unit_count <= 0 || controller.unit_count > controller.unit_limit)
        throw std::runtime_error("UNIT_COUNT must be between 1 and UNIT_LIMIT");

    int const num_sonar_msgs = parse_util::parse_integer<int>(parse_util::read_labelled("NUM_MSGS").front());
    if (num_sonar_msgs < 0)
        throw std::runtime_error("NUM_MSGS cannot be negative");
    controller.sonar_messages.clear();
    controller.sonar_messages.reserve(static_cast<std::size_t>(num_sonar_msgs));
    for (int index = 0; index < num_sonar_msgs; index++) {
        auto const line = parse_util::read_data_line();
        if (line.size() != 1)
            throw std::runtime_error("missing sonar message value");
        controller.sonar_messages.push_back(parse_util::parse_integer<std::uint64_t>(line.front()));
    }

    auto first_tile_values = parse_util::read_data_line();
    controller.sonar_echoes = {};
    if (first_tile_values.front() == "ECHOES") {
        if (first_tile_values.size() != 6)
            throw std::runtime_error("ECHOES requires 5 values");
        auto const echo = [&](std::size_t index) { return parse_util::parse_integer<int>(first_tile_values[index]); };
        controller.sonar_echoes = {echo(1), echo(2), echo(3), echo(4), echo(5)};
        first_tile_values = parse_util::read_data_line();
    }

    std::vector<Tile> tiles;
    std::unordered_map<Position, std::size_t, PositionHash> tile_indices;
    tiles.reserve(Constants::VISION_SIZE * Constants::VISION_SIZE);
    for (int index = 0; index < Constants::VISION_SIZE * Constants::VISION_SIZE; index++) {
        auto const values = index == 0 ? first_tile_values : parse_util::read_data_line();
        if (values.size() != 4)
            throw std::runtime_error("each vision tile requires: x y hasPearl pearlIn");

        int const x = parse_util::parse_integer<int>(values[0]);
        int const y = parse_util::parse_integer<int>(values[1]);
        int const has_pearl = parse_util::parse_integer<int>(values[2]);
        int const pearl_time = parse_util::parse_integer<int>(values[3]);
        if (has_pearl != 0 && has_pearl != 1)
            throw std::runtime_error("hasPearl must be 0 or 1");

        Position const position(x, y);
        if (tile_indices.contains(position))
            throw std::runtime_error("duplicate vision tile");

        tile_indices.emplace(position, tiles.size());
        tiles.emplace_back(position, std::nullopt, pearl_time, has_pearl == 1);
    }

    int const num_dragon_parts = parse_util::parse_integer<int>(parse_util::read_labelled("DRAGON_BODIES").front());
    if (num_dragon_parts < 0)
        throw std::runtime_error("DRAGON_BODIES cannot be negative");

    bool found_controller_head = false;
    for (int index = 0; index < num_dragon_parts; index++) {
        auto const values = parse_util::read_data_line();
        if (values.size() != 6)
            throw std::runtime_error("each dragon part requires: team dragonId x y facing isHead");

        Team const team(parse_util::read_char_safe(values[0]));
        int const dragon_id = parse_util::parse_integer<int>(values[1]);
        Position const position(parse_util::parse_integer<int>(values[2]), parse_util::parse_integer<int>(values[3]));
        Direction const facing(parse_util::read_char_safe(values[4]));

        int const head_flag = parse_util::parse_integer<int>(values[5]);
        if (head_flag != 0 && head_flag != 1)
            throw std::runtime_error("isHead must be 0 or 1");

        auto const tile = tile_indices.find(position);
        if (tile == tile_indices.end())
            throw std::runtime_error("dragon part is outside the vision tiles");

        DragonPart part(position, dragon_id, team, facing, head_flag == 1);
        if (dragon_id == controller.get_id() && head_flag == 1) {
            controller.head = part;
            controller.head.dir = current_direction;
            found_controller_head = true;
        }
        tiles[tile->second].dragon_part = part;
    }
    if (!found_controller_head)
        throw std::runtime_error("controller head is missing from DRAGON_BODIES");

    Position const head_position = controller.get_position();
    auto const wrap = [](int value, int size) { return (value % size + size) % size; };
    auto const tile_at = [&](int local_x, int local_y) -> Tile& {
        Position const position(wrap(head_position.x + local_x - Constants::VISION_RADIUS, game_state.width),
                                wrap(head_position.y + local_y - Constants::VISION_RADIUS, game_state.height));
        auto const found = tile_indices.find(position);
        if (found == tile_indices.end())
            throw std::runtime_error("vision is missing expected tile");
        return tiles[found->second];
    };

    for (int y = 0; y < Constants::VISION_SIZE + 1; y++) {
        auto const line = parse_util::read_data_line();
        if (line.size() != Constants::VISION_SIZE)
            throw std::runtime_error("horizontal edge row requires 7 values");

        for (int x = 0; x < Constants::VISION_SIZE; x++) {
            Edge edge = parse_util::parse_edge(line[x], true);
            if (y > 0)
                tile_at(x, y - 1).edges[2] = edge;
            if (y < Constants::VISION_SIZE)
                tile_at(x, y).edges[0] = edge;
        }
    }

    for (int y = 0; y < Constants::VISION_SIZE; y++) {
        auto const line = parse_util::read_data_line();
        if (line.size() != Constants::VISION_SIZE + 1)
            throw std::runtime_error("vertical edge row requires 8 values");

        for (int x = 0; x < Constants::VISION_SIZE + 1; x++) {
            Edge edge = parse_util::parse_edge(line[x], false);
            if (x > 0)
                tile_at(x - 1, y).edges[1] = edge;
            if (x < Constants::VISION_SIZE)
                tile_at(x, y).edges[3] = edge;
        }
    }

    controller.vision = Vision(std::move(tiles), std::move(tile_indices));
    return true;
}

// Ends the turn and flushes, which is the one write a turn costs.
inline void end_turn() {
    std::cout << "PROTOCOL " << Constants::PROTOCOL_MAJOR << "\nENDTURN" << std::endl;
}

} // end namespace unswbc