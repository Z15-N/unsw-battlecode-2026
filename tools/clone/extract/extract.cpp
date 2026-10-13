// Training-side twin of the imitation bot: the same parser, memory and
// features, run over dragon sessions rebuilt from replays.
//
//   extract.exe out.bin < sessions.txt
//
// Input: "@SESSION" + init block, then per turn "@TURN <label>" + round block,
// where <label> (0-3 move, 4 split, -1 other) is what the dragon did that turn.
// Output: per turn FEATURES floats, then deadly[4] and can_split as floats.
#include "../bot/clone.hpp"

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(stderr, "usage: extract out.bin < sessions.txt\n");
        return 2;
    }
    std::FILE* out = std::fopen(argv[1], "wb");
    if (!out) return 3;
    mimic::Reader reader(stdin);
    mimic::Init init;
    mimic::World world;
    mimic::Obs obs;
    mimic::Scratch scratch;
    static mimic::Features f;
    long turns = 0;
    bool open = false;
    while (reader.next()) {
        if (mimic::starts(reader.line, "@SESSION")) {
            if (!mimic::read_init(reader, init)) break;
            world.reset(init);
            open = true;
        } else if (mimic::starts(reader.line, "@TURN") && open) {
            int label = std::atoi(reader.line.c_str() + 5);
            if (!mimic::read_round(reader, init.id, obs)) break;
            world.observe(obs);
            mimic::features(world, obs, scratch, f);
            float tail[5] = {(float)f.deadly[0], (float)f.deadly[1], (float)f.deadly[2],
                             (float)f.deadly[3], (float)f.can_split};
            std::fwrite(f.v, sizeof(float), mimic::FEATURES, out);
            std::fwrite(tail, sizeof(float), 5, out);
            world.last_action = label >= 0 && label < mimic::ACTIONS ? label : -1;
            turns++;
        }
    }
    std::fclose(out);
    std::fprintf(stderr, "%ld turns, %d features\n", turns, mimic::FEATURES);
    return 0;
}
