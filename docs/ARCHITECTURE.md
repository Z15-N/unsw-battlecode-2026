# Bot architecture

The bot is one C++20 program ([`bot/main.cpp`](../bot/main.cpp), about 3,700 lines). Every dragon on the team runs
its own copy. The copies share no memory, so everything a dragon knows comes from three sources: what it sees (the
7×7 square around its head), what it hears over sonar, and the map data compiled into the binary.

## Constraints that shaped the design

| Constraint | Consequence |
|---|---|
| No shared memory; sonar is the only channel, and a ping stops at the first wall or body | Each dragon decides its role for itself. Team-level decisions (who is king, where the enemy queen is) are built from relayed messages and can be wrong or stale. |
| 7×7 vision | Enemies are often only partly visible. The bot estimates how long a half-seen enemy is (and so how far it can reach) from the segments on the edge of its view. |
| 100M CPU points per dragon per turn; running out kills the dragon | Searches are bounded: exhaustive search only for short sprints, beam search for long ones, and stamped arrays instead of clearing buffers each turn. The peak turn uses about 37M. |
| Sprinting: the first ceil(L/4) steps of a turn are free, then each step costs a segment | Long dragons are fast. The queen's danger map is speed-aware: each enemy reaches as far as its free steps plus the segments it can afford to spend. |
| Queen = lowest id; ids move in order | Our queen moves before the rest of our team, so allies plan around where she has just gone and keep off her sides. |

## One turn

`takeTurn` runs top to bottom once per dragon per turn:

1. **Parse the input** with [`fastio.hpp`](../bot/fastio.hpp), a replacement for the stock parser. The stock one built a
   string stream and a vector of strings per line, about 1.1M points a turn.
2. **Read sonar.** Decode king announcements, prey sightings, enemy intel, food reports and portal warnings. Each
   message is a 56-bit payload plus an 8-bit checksum, so garbage and enemy pings are dropped.
3. **Update memory from vision:** walls, portals, pearls and spawn countdowns, and the positions of visible dragons. A
   remembered enemy segment with k segments behind it expires after k+1 of its dragon's moves.
4. **Identify the map.** Every ladder map is compiled into [`maps.hpp`](../bot/maps.hpp) by
   [`tools/gen_maps.py`](../tools/gen_maps.py). Candidates are filtered by board size, then by every edge the dragon
   sees, until one map is left. On a map the bot doesn't know, it infers symmetry instead: it tests mirror-x, mirror-y
   and rotation against what it has seen and fills in the unseen half.
5. **Model threats.** Every visible enemy head gets a reach: free steps, plus the segments it can spend, plus pearls it
   can eat on the way, plus one more if its body may continue out of view.
6. **Score targets.** A breadth-first flood fill from the head values each tile by the pearls expected there when the
   dragon would arrive (a pearl in view, a spawn whose countdown ends in time, or a learned prior for unseen tiles). The
   value is discounted per step and divided by how many allies are closer (contention).
7. **Decide, in priority order:**
   1. *Feed the king* (endgame): walk to the chosen long dragon and die beside it, leaving pearls for it.
   2. *Ram* an enemy head when the trade favours us. A depth-limited search over free-step paths simulates eating and
      body shifts.
   3. *Threat split*: a threatened long dragon sheds all but its 2 head segments and the bulk escapes from the tail.
   4. *Growth split* to build the army, with rules against splitting inside dead-end pockets, where the stub dies.
   5. *Move*: score each direction by target value, safety, room (how much space is reachable before our own body or
      enemies close it), and role-specific penalties.

## The queen

Most of the code, and most of the experiments, went into keeping the queen alive. With our queen alive we won about
93% of ranked games (79 of 88 in one early sample).

- **Danger map:** for every tile, how many turns before some visible enemy can reach it, counting sprint speed.
- **Look-ahead:** a step costs extra if some placement of the three nearest enemies, after their free steps, could
  leave her with no safe step next turn.
- **Escape search:** when her best single step is inside an enemy's reach, search 2- and 3-step sprints for one that
  ends outside every reach with the most safe territory, meaning tiles she reaches before any enemy does.
- **Farming sprints:** an exhaustive search over 2–3-step free paths, or a beam search (the 32 best partial paths at
  each depth, up to 5 steps) once she is 13+ long. A sprint is taken only if it beats her best single step and, checked
  in full, leaves her no less safe.
- **Space-time targeting:** spawn countdowns are public, so she values a pearl spawn by whether she can arrive just as
  it appears, and waits up to 6 rounds for it.
- **Learned home:** each map has two queen "homes" (one per queen id, since each has a fixed spawn): where the queens
  that survived to round 500 on the winning side kept their heads during rounds 200–499, over 2,480 winning
  top-team games ([`analysis/map_plans.py`](../tools/analysis/map_plans.py)). A soft leash keeps her near it.

## Sonar protocol

| Message | Purpose |
|---|---|
| King | Endgame election: "I am the longest dragon, feed me". The best king heard wins; stale kings expire. |
| Prey | A sighting of a much longer enemy (or the enemy queen), relayed so small dragons converge on it |
| Intel | Enemy positions and lengths, relayed beyond the 7×7 view |
| Food | Two tile reports: a pearl seen there at a given round, or a spawn due there at a given round |
| Queen portal warning | Sent by the queen through a portal she stands beside, so allies on the far side don't come through onto her |

A general "portal in use" warning between any two allies also exists, but it is switched off in the final version.

A ray stops at the first body it hits, so messages travel by relay. Dragons forward what they hear, and the payload
carries the round it was sent so stale news can be dropped.

## Endgame

If both queens are dead after 500 rounds, the game goes to the team with the longest dragon. We were losing those
games: our total length was larger, but it was spread over many short dragons (our longest averaged 21.7 against their
28.6). The endgame "giant" (v075, copied from a top team's replays) changes the army's behaviour from round 150:
dragons of 10+ stop splitting and get the queen's safety rules. From round 200, small dragons that see a much longer
ally nearby die beside it to feed it. It needs no messages, so it still works when sonar can't reach.

## Generated map knowledge

[`tools/gen_maps.py`](../tools/gen_maps.py) turns the server's map list into `maps.hpp`. For each map it writes a
palette-compressed tile grid of pearl spawn timers, the wall and portal edges, the symmetry, and the learned queen
homes. The bot embeds all of it; per-map tuning lives in `applyMapConfig` in `main.cpp`. A strategy note on why we went all-in on this ("full hard code") is in
[`notebook/STRATEGY.md`](../notebook/STRATEGY.md), section 1s.
