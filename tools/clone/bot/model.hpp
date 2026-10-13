// A small MLP: standardise, two ReLU layers, action logits.
// Weights come from weights.hpp, written by `python -m lab.clones export`.
#pragma once

#include "clone.hpp"
#include "weights.hpp"

namespace mimic {

static_assert(weights::INPUTS == FEATURES, "weights.hpp was trained on a different feature set");
static_assert(weights::OUTPUTS == ACTIONS, "weights.hpp has a different action set");

inline void dense(const float* in, int n_in, const float* w, const float* b, int n_out, float* out, bool relu) {
    for (int o = 0; o < n_out; o++) {
        const float* row = w + (long)o * n_in;
        float acc = b[o];
        for (int i = 0; i < n_in; i++) acc += row[i] * in[i];
        out[o] = relu && acc < 0.f ? 0.f : acc;
    }
}

inline void logits(const float* features_in, float* out) {
    static float x[weights::INPUTS], h1[weights::H1], h2[weights::H2];
    for (int i = 0; i < weights::INPUTS; i++) x[i] = (features_in[i] - weights::mean[i]) * weights::inv_std[i];
    dense(x, weights::INPUTS, weights::w1, weights::b1, weights::H1, h1, true);
    dense(h1, weights::H1, weights::w2, weights::b2, weights::H2, h2, true);
    dense(h2, weights::H2, weights::w3, weights::b3, weights::OUTPUTS, out, false);
}

// Best action the rules allow: no move into kelp or a body when another move
// survives, no move into a pocket smaller than our body when a roomier move
// exists, and a split only when it is legal.
inline int choose(const Features& f, const float* z, int length) {
    bool any_safe = !f.deadly[0] || !f.deadly[1] || !f.deadly[2] || !f.deadly[3];
    bool any_roomy = false;
    for (int d = 0; d < 4; d++) any_roomy |= !f.deadly[d] && f.reach[d] >= length;
    int best = -1;
    for (int a = 0; a < ACTIONS; a++) {
        if (a < 4 && any_safe && f.deadly[a]) continue;
        if (a < 4 && any_roomy && f.reach[a] < length) continue;
        if (a == 4 && !f.can_split) continue;
        if (best < 0 || z[a] > z[best]) best = a;
    }
    return best < 0 ? 0 : best;
}

} // namespace mimic
