// Imitation bot: plays like the team whose replays trained weights.hpp.
#include "model.hpp"

int main() {
    std::setvbuf(stdout, nullptr, _IOFBF, 1 << 16);
    mimic::Reader reader(stdin);
    mimic::Init init;
    if (!mimic::read_init(reader, init)) return 0;
    mimic::World world;
    world.reset(init);
    mimic::Obs obs;
    mimic::Scratch scratch;
    static mimic::Features f;
    float z[mimic::ACTIONS];
    while (mimic::read_round(reader, init.id, obs)) {
        world.observe(obs);
        mimic::features(world, obs, scratch, f);
        mimic::logits(f.v, z);
        int a = mimic::choose(f, z, obs.length);
#ifdef MIMIC_DEBUG
        std::fprintf(stderr, "R%d pos %d,%d dir %c ident %d cand %zu deadly %d%d%d%d split %d z %.2f %.2f %.2f %.2f %.2f -> %d\n",
                     obs.round, obs.hx, obs.hy, obs.dir, (int)world.identified, world.candidates.size(),
                     f.deadly[0], f.deadly[1], f.deadly[2], f.deadly[3], (int)f.can_split, z[0], z[1], z[2], z[3],
                     z[4], a);
#endif
        if (a == 4)
            std::printf("SPLIT 2\n");
        else
            std::printf("MOVE %c\n", mimic::DIRS[a]);
        world.last_action = a;
        std::printf("PROTOCOL 3\nENDTURN\n");
        std::fflush(stdout);
    }
    return 0;
}
