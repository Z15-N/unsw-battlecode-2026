#include "helper.hpp"
#include "fastio.hpp" // judge-cheap protocol reader (same parsed contents as unswbc::update)
#include "maps.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

using namespace unswbc;

namespace {

// ---------------------------------------------------------------- tuning
constexpr double GAMMA = 0.75;         // discount per step for pearl value
constexpr double EXPLORE = 0.01;       // value of an unseen / stale tile
constexpr int AREA_PER_UNIT = 12;   // v29: bigger army cap (screen 0.533; v24: 16)      // army cap = map area / this
constexpr int KING_SPLIT_LEN = 5;      // initial dragons split at this length...
constexpr int KING_CHILD = 2;          // ...giving the child this many segments
constexpr int KING_MAX_SPLITS = 20;
constexpr int CHILD_SPLIT_LEN = 4;     // spawned dragons split in half at this length
constexpr int SPLIT_FROM = 0;   // v29: split from round 0 (screen 0.567; v24: 3)
constexpr double FAST_PRIOR = 0.0;   // >0: value of an unseen fast fountain tile (gap <= 2)
constexpr bool EARLY_SPLIT = true;  // v29: every map (screen 0.55; v24: Default, Slithery, Trauma only) // starters split in half on their first turns (top teams double their heads in round 0)
constexpr bool KING_NO_CROWD = true; // the king ignores the crowding penalty while the army feeds it (its food is where the feeders are)
constexpr bool NOEAT_ALL = true;     // every non-king dragon keeps off the food around the king while the army feeds it
constexpr int FILL_CAP = 2500;       // flood-fill tile cap on maps larger than 64x64 (CPU guard; 128x128 max 52M -> 24M)
constexpr bool ALL_NO_BLIND = false; // every dragon: space behind a portal it cannot see does not count (75% of our fatal crossings had no other move)
constexpr int SPLIT_UNTIL = 400;
constexpr int RAM_MARGIN = 1;        // ram enemies at least as long as us (1000 = never). v11: 0 passed SPRT vs v10, 305-247 over 552 games (official + generated), elimination games 128-86
constexpr double ENEMY_ADJ = 1.0;    // penalty for ending next to an enemy head (it may ram)
// Hunting (v14). Online, v12 lost 11 games where the enemy was down to one or two long dragons for 100+
// rounds while we had 5-50, and 20 of the 50 games it led on total length at round 400. A head-on kills both
// dragons whatever their size, so a 3-segment dragon for their king is the best trade in the game.
constexpr int RAM_STEPS = 3;          // sprint reach of a ram (v12: 3)
// EXP-018 (Oct 5): full-reach queen strike. The enemy queen (id 0/1) has always moved before any of our non-queen
// dragons this round, and every other dragon that could block the path either already moved or moves after us, so a
// free path of length <= our sprint reach (ceil(L/4) free + L-2 paid steps) to her head is a certain trade. RAM_STEPS
// capped every ram at 3 steps (and L-1); top teams strike from a median 4 tiles. Against her, use the whole reach,
// up to QSTRIKE_MAX (Manhattan 6 = the edge of our 7x7 view).
constexpr bool QUEEN_STRIKE_FULL = true;
constexpr int QSTRIKE_MAX = 6;
// EXP-028 (Oct 6): lethal tiles, but never at the price of room. EXP-021 (penalty 60) and EXP-026 (25) cut our queen's
// head-on deaths vs the stalker significantly (-0.038, -0.029) but the same games turned into self-box deaths (+0.013,
// +0.016): with every non-lethal tile tight, the penalty pushed her into a pocket. Here a tile within the exact reach of
// an enemy that moves after her costs QLETHAL_PEN only when some other step is both outside every such reach and has
// room (flood fill >= length + 4), checked in a pre-pass over her four steps.
constexpr bool QUEEN_LETHAL = true;
constexpr double QLETHAL_PEN = 60.0;
// EXP-023 (Oct 6): free sprint steps. A dragon of length L moves ceil(L/4) steps a turn for free; ours took 1 step every
// turn (100% of moves with 2-4 free steps), the top teams 2+ steps in 55-68% of them. After the usual first step, keep
// walking along the pearl target's BFS path while it gets closer, with every step simulated as the engine does (our own
// body as that step finds it, other bodies), never into an enemy's reach (queen and protected dragons: reach + 1; others:
// next to an enemy head), only onto tiles we see, and only while the flood fill from there still holds our length.
constexpr bool FREE_SPRINT = true;
// CPU guard: the judge's clock advances 1 ns per point, so steady_clock measures this turn's spend; stop extending a
// sprint once the turn has used SPRINT_BUDGET points (EXP-023 peaked at 61M on 64x64 maps without it).
constexpr long long SPRINT_BUDGET = 30000000;
std::chrono::steady_clock::time_point turnT0;
// S2g (Oct 4): guard ram. Live v004: 29 of 52 losses = our queen killed head-on by a 2-3 long enemy that shadowed her
// (1 tile away, no safe option left). An ally that sees an enemy head within QGUARD_DIST of our queen's head and can
// reach it trades itself for it (the ram below), whatever their lengths, if it is at most QGUARD_MAXLEN long.
constexpr bool QUEEN_GUARD = true;
constexpr int QGUARD_DIST = 3;
constexpr int QGUARD_MAXLEN = 6;
constexpr bool PREY_HUNT = true;      // v29b (Ben's babies): endgame only, see PREY_FROM
// v40 (Ben's sonar network, Oct 2). The top teams fire ~3.9 sonar rays per dragon-turn all game; v29b fired 0.03 before
// round 200. Every dragon now fills its free rays every turn with the freshest enemy sightings it knows (its own vision
// or relayed), and our babies (short dragons, a share of the army) hunt the long enemies the network reports: favourable
// trades only (v32b's even trades lost on the ladder). Workers keep farming.
constexpr bool INTEL = true;
constexpr std::uint64_t INTEL_MAGIC = 0x3E7;
constexpr int INTEL_TTL = 6;          // rounds a sighting is relayed and acted on
constexpr int INTEL_MAX = 24;         // sightings kept
// v41 (Ben's chill & kick workers, over sonar): rays also carry food. Pearls the sender won't take now and tiles about
// to spawn reach allies that can't see them, so the pearl race (it decides games from round 50) uses the whole army's eyes.
constexpr bool FOOD_INTEL = true;
constexpr std::uint64_t FOOD_MAGIC = 0xF0D;
constexpr int FOOD_NEAR = 3;          // pearls this close to the sender are its own
constexpr int FOOD_SPAWN_WITHIN = 15; // share spawns due within this many rounds
constexpr bool BABY_HUNT = false; // REMOVED in the consolidation pass 2026-10-04 (ablation not worse: -0.009 / +0.056 / -0.010)
constexpr int BABY_MAXLEN = 4;        // babies: our dragons this short...
constexpr int BABY_GAP = 4;           // ...go after reported enemies at least this much longer...
constexpr int BABY_MIN_TARGET = 6;    // ...and at least this long...
constexpr int BABY_RANGE = 20;        // ...within this path distance
constexpr double BABY_SHARE = 0.25;   // share of our dragons (by id) that are babies
constexpr int PREY_FROM = 350;        // the longest dragon at 500 decides most games: hunt their late king
constexpr int PREY_MIN = 8;           // an enemy head showing this many segments is prey, shared by sonar
constexpr int PREY_TTL = 8;           // rounds a sighting stays usable
constexpr int HUNTER_MAXLEN = 6;      // our dragons up to this long hunt prey...
constexpr int HUNT_GAP = 4;           // ...at least this much longer than themselves...
constexpr int PREY_RANGE = 24;        // ...within this path distance
constexpr double PREY_W = 1.0;        // score per step closer to the prey
constexpr std::uint64_t PREY_MAGIC = 0x5A3;
// Space (v14). On Schooltime v12 lost ~250 small dragons a game boxed in by its own dragons (the C++ public bot: 4).
// A move needs SPACE_MULT x length + SPACE_ADD reachable tiles (v12: 1, 4); SPACE_SOFT scales the penalty below 2L+10.
constexpr int SPACE_MULT = 1;
constexpr int SPACE_ADD = 4;
constexpr double SPACE_SOFT = 0.5;
constexpr bool OTHERS_FREE = true;  // false: other bodies never free up in the flood fills (the C++ public bot's rule)
// Pessimistic room (the C++ public bot's rule): count the space a move leaves us with tiles next to any other head,
// or 1-2 ahead of it, blocked; want 2 x length + PESS_MARGIN. Stepping 1-2 ahead of an ally head is a cut.
constexpr bool PESS_ROOM = false;
constexpr int PESS_MARGIN = 10;
constexpr double PESS_W = 0.3;        // per tile short
constexpr double PESS_LETHAL = 20.0;  // room below length + 2
constexpr double CUT_PEN = 5.0;
// Mid-size safety: a shorter enemy ramming one of our 6+ dragons is a bad trade for us (the C++ public bot's scouts
// sprint into anything twice their length). Such dragons keep out of shorter enemies' sprint reach, like the king.
constexpr bool MID_SAFE = false;
constexpr int MID_SAFE_LEN = 6;
// Portal traffic (the C++ public bot's idea). Vs it, v12 lost 28-39 dragons a game on Portals to head-ons with its own
// dragons on the unseen far side of a portal (17 on Queen of Spades, 20 on Slithery). A portal that any other dragon was
// seen touching (a segment on a tile beside either end) in the last PT_TTL rounds costs PT_PEN to cross.
constexpr bool PT_ENABLE = false;
constexpr int PT_TTL = 3;
constexpr double PT_PEN = 8.0;
// Feeding like the C++ public bot's cash-in: never with an enemy head in view (they eat the drop), and a feeder may die
// beside any visible ally at least FEED_ANY_MIN long and 2 longer than itself, not only the elected king.
constexpr bool FEED_NO_ENEMY = false;
constexpr bool FEED_ANY = false;
constexpr int FEED_ANY_MIN = 6;
// King repulsion (the C++ public bot's KP_FAR_W): on Schooltime vs it our 18-long king walked into a crowd of their
// dragons and was rammed by a 3-long; late on, 8-18 long dragons of ours died to 2-3 long rammers five more times.
// A protected dragon pays cfg.kingRepel / distance for every enemy head in view.
constexpr double KING_REPEL = 0.0;
// Long dragons (the C++ public bot's "long"): from cfg.longFrom a dragon of LONG_LEN+ stops splitting and keeps eating, so
// there are 15-30 long dragons by the endgame instead of a king built from 2-4 segment dragons at round ~400. It still
// buds a 2-segment child while the army is below LONG_RESCUE of the cap, and only feeds a king 3+ longer than itself.
// v075 (Oct 12: both-dead endgames, copied from SSS). docs/structure.md: with both queens dead the longest living dragon
// wins. analysis/loss_types.py (v065, 350 ranked games): both queens died in 164 and we lost 99, our biggest loss bucket;
// analysis/both_dead.py: our longest ended 21.7 vs their 28.6 with total length 177 vs 114 (29.7 dragons vs 15.8). Top
// teams win 67-86% of their both-dead games: longest aAah 32, larp 35, chat gippy tea 34, SSS 91. SSS's final longest is a
// giant (136 on average) that ate per game after r150 54 drops of its own dead dragons and 25 spawns (giant_food.py), and
// it is a split child (it sheds a 2-long head stub to turn round). Ours never forms: every dragon that reaches
// CHILD_SPLIT_LEN splits until r400 or the unit cap (v074's local games: 63 dragons, longest 7-11 from r300 to r400).
// From LONG_FROM a dragon of LONG_LEN+ stops splitting, keeps eating and gets the king's safety rules (LONG_PROTECT), and
// a small dragon that sees a non-queen ally GIANT_MARGIN+ longer than itself (and GIANT_MIN+) within its feed radius,
// with no enemy head within TRICKLE_ENEMY_R of it and at most TRICKLE_PENDING pearls by its head, dies beside it while we
// keep TRICKLE_MIN_UNITS dragons; dragons within TRICKLE_NOEAT_R of it leave its food.
constexpr bool GIANT = true;
constexpr int GIANT_MIN = 10;
constexpr int GIANT_MARGIN = 6;
constexpr int LONG_FROM = 150;
constexpr bool PORTALS_LONG = false; // v030: the Portals-only long-dragon rule off
// v032 (copied from horse, SSS, forgot to mention; Ben's 'babies hunt on information'). Enemy queens killed per game
// (ranked since 07 Oct 15:06 UTC, 50 games each): us 0.36, horse 0.62, SSS 0.58, forgot to mention 0.58, aAah 0.52,
// always by 3-long dragons; their killers close in from a median 10 tiles 10 rounds before (ours 7). Since v020b went
// live we won 29 of 29 games where only their queen died. Our short dragons that see the enemy queen, or have a sighting
// of her at most QHUNT_TTL rounds old, within QHUNT_RANGE path steps walk at her (PREY_W a step); the full-reach strike
// on their queen finishes it.
// v036 (STRATEGY 1q; Ben: "our queen just got assassinated"). Since v020b enemies killed our queen in 109 of 235 ranked
// games (48% of our recent 60; the top teams' 22-37%; vs teams within 50 of us 50%, plus 26% by her own move). On the
// full board, at her last turn before a ram she was already cornered (every legal step inside some enemy's real reach)
// in 74 of 109: the move that lost her was made a turn or more earlier. Her terms look one move ahead with the enemies
// standing still (lethal tiles, exits outside today's reach). The look-ahead: for each step she can take, every place
// each nearby visible enemy can be after its free steps this round (or still there, splitting), and whether she then
// still has a safe step next turn (outside each enemy's reach along open paths, bodies as walls; or a split in place).
// A step from which some enemy placement leaves her no safe step costs QSAFE2_PEN, when another step is neither
// cornerable nor inside a reach now.
constexpr bool QSAFE2 = true;
constexpr double QSAFE2_PEN = 63.1615;
constexpr int QSAFE2_MAXE = 3;   // nearest enemy heads considered
constexpr int QSAFE2_RANGE = 9;  // Manhattan from her head
// v048 (STRATEGY 1r): the look-ahead's searches grow with the enemies' length (every place a long enemy reaches with its
// free steps, each searched to its full reach): 56.75M points on one ladder turn (Schooltime 1517642 r426), the judge
// kills a dragon at 100M. Past this many points into the turn the pre-pass stops and its results are dropped.
constexpr long long QSAFE2_BUDGET = 40000000;
// v037 (STRATEGY 1q). Of the 74 rams (since v020b) where our queen was cornered at her last turn - every single step
// inside some enemy's reach - 38 had a 2-step move to a tile outside every enemy's reach (full board): 20 free (she was
// 5+ long: ceil(L/4) = 2 free steps), 18 paying one segment (3-4 long). Our queen never moves 2 steps (FREE_SPRINT
// leaves her out: "the queen keeps single, fully scored steps"); SSS's queen does on 12.7% of her turns near enemies.
// The escape step: when her chosen step is inside a visible enemy's reach (open paths, bodies as walls), take the best
// 2-step move that ends outside every reach with room (free at 5+, one segment at 3-4; tiles in view, no portal).
constexpr bool QESCAPE = true;
constexpr bool QHUNT = true;
constexpr int QHUNT_RANGE = 12;
constexpr int QHUNT_MAXLEN = 5;
constexpr int QHUNT_TTL = 3;
constexpr int LONG_LEN = 10; // v075 (was 5, unused while LONG_FROM was 0)
constexpr double LONG_RESCUE = 0.25;
constexpr bool LONG_PROTECT = true;  // long dragons get the king's safety rules (v075; was false, unused)
// On Schooltime our 33-long king walked into a room whose only big exit was a portal, then died on the unseen far side.
// Protected dragons count no space (and no food) behind a portal whose far side is not in view.
constexpr bool KING_NO_BLIND = false;
// Portal busy (v14). All of our friendly head-ons on Portals are through portals, half with the victim already sitting
// at the far exit. A dragon beside a portal sends "portal P in use" through it; the ray reaches the first dragon on the
// far side, i.e. the one about to come through, which then pays PB_PEN to cross P for PB_TTL rounds.
// Ending next to an ally head: the C++ public bot charges any head (its HEAD_RISK) about a third of an adjacent pearl.
constexpr double ALLY_ADJ = 0.3;
constexpr bool ALLY_ADJ_ALL = false; // false: only allies that move after us this round
constexpr bool BODY_VIS_FIX = true;  // own segments in view always count as body (bug fix, v14)
constexpr bool PB_ENABLE = false;
constexpr int PB_TTL = 1;
constexpr double PB_PEN = 15.0;
constexpr double PB_DOOR = 0.0;     // cost of ending beside a portal that is busy
constexpr std::uint64_t PB_MAGIC = 0x6C1;
constexpr bool GROWER = false;      // keep one starter unsplit to win the length tiebreak

// ---------------------------------------------------------------- v5 switches
// Each switch was tested on its own against v2 (the live bot) over 40-72 local games.
// v5 turned on BODY_INFER, BOXED_SAVE, BIG_BORN (56% vs v2 together, 72 games, all 12 maps).
// v6 turns BIG_BORN off: online, the rescued grower sat in Dilemma's and Autarky's dead-end pocket
// at 13-18 segments all game, dying and re-splitting about 250 times per game.
// Off because they lost or did nothing: GROWER_FROM, PROTECT_FROM_END, HUNT, ESCAPE_SPLIT, KING_FIX.
constexpr int GROWER_FROM = 0;         // >0: from this round the first starter stops splitting and plays for length
constexpr int PROTECT_FROM_END = 0;    // >0: in the last N rounds, dragons of PROTECT_LEN+ play for survival
constexpr int PROTECT_LEN = 8;
constexpr double HUNT = 0.0;           // >0: army pull towards enemy heads HUNT_MARGIN+ longer than itself
constexpr int HUNT_MARGIN = 4;
constexpr int LAST_ROUND = 500;
// v2 found starters with `R == 1`; the engine now starts at round 0, so live v2's starters
// have been splitting like children. false keeps that live behaviour, true restores budding.
constexpr bool KING_FIX = false;
// Out-of-sight body segments: v2 ignored them, so long starters steered into their own unseen tail.
constexpr bool BODY_INFER = true;
// When even the best move leaves too little room, shed the tail as a new dragon instead of walking
// into a dead end. The child starts at the old tail, facing away, often with room to escape.
constexpr bool ESCAPE_SPLIT = false;
// When boxed in, v2 split 2 segments off the tail and kept the doomed head end long. The head
// end is the part that dies, so keep only 2 there and send the rest out as the child.
constexpr bool BOXED_SAVE = true;
// >0: a dragon that starts life this long (a long starter, or the tail saved from a trap) never
// splits and plays for survival. Army children are born at 2-4, so they never qualify.
constexpr int BIG_BORN = 0;

// ---------------------------------------------------------------- v6 switches
// Built from 81 online games of v5 (26 Sep) and local tournaments against v5, v2 and each other
// (48 games per line, every map, both colours). Head-to-head against v5: maps alone 40%, + endgame
// king 60%, + portal caution 69%. This file adds crowding control on open maps and king safety:
// 70% against v5 and 57% against the 69% bot on fresh seeds, 55% against v2.
//
// Every map played online is a bundled map, so dragons start with its kelp, portals and pearl
// spawn ranges instead of exploring blind (children are new processes and remembered nothing).
constexpr bool MAP_KNOWLEDGE = true;
// >0: only tiles spawning at least every BELIEF_FAST rounds get a pearl estimate before they are
// first seen (tested at 100: no better on Trophy or Queen of Spades, so off).
constexpr int BELIEF_FAST = 0;
// Long starters (Autarky 14, Dilemma 11) spawn in a dead-end corridor. Peel 2-segment children off
// the tail from turn 0 so each child starts further along the corridor, where the side exits are.
constexpr int PEEL_FROM_LEN = 8;
constexpr int PEEL_DOWN_TO = 4;
// Stepping through a portal is always blind: vision stops at it. With the maps built in, dragons
// used portals constantly and 13% of crossings killed a dragon, mostly our own heads meeting.
// v7: 12. In v6's 86 online games every one of our 221 ally-on-ally head-on crashes (two of our
// dragons lost each time) was a blind step through a portal onto an ally's head, 101 of them on
// Queen of Spades. Only step through when nothing else is sane.
// v9: a dragon heading for a portal sends one sonar ray through it; next turn the echo says
// whether any dragon lies on the far side of that line. A crossing probed clear costs only
// PORTAL_PROBED; an unprobed or occupied one keeps the blind penalty. Online, v8's blanket 12
// kept us out of Trophy's cup (the other team was inside by round 9) and out of every box on
// Portals, where the pearls are only reachable through portals.
constexpr bool PORTAL_PROBE = false;
constexpr double PORTAL_PROBED = 0.3;
constexpr int PROBE_RANGE = 6;        // look this far along each line for a portal to probe
constexpr double BLIND_PORTAL = 12.0; // v5: 0.5, when it rarely knew where a portal led; v6: 3.0. 12.0: 51-37 vs v6 (base 47-41)
// Crowding: score lost per allied segment within 2 tiles of the destination. Our dragons packed
// into Queen of Spades' rich room and died there 40 times in 300 rounds, boxing each other in.
constexpr int SPLIT_MIN_EXITS = 1;
// v17: crowding penalty 0.3 on every map (was 0.15 on open maps only, 0 on fountain maps; v16 put 0.3 on Queen of Spades).
// vs nick_cpp + v16, 320 games each: 221 vs 189 (seeds 2401+), 212 vs 182 (seeds 2701+); 0.2 206, 0.45 192. Not on Devil
// (11-21 vs 29-3: its 1-wide corridors need the crowd).
constexpr double CROWD_FORCE = 0.3;  // >0: crowding penalty of this weight on every map (per map: cfg.crowdForce)
constexpr double CROWD = 0.15;        // 0.3 was worse
// Crowding is how fountains get farmed (Stronghold, Devil, Trauma, Dilemma), so no crowding
// penalty within 2 tiles of a tile that spawns at least every 5 rounds.
constexpr bool CROWD_FOUNTAIN_EXEMPT = true;
// On a map with any fountain, no crowding penalty at all: every fountain map lost 0-4 with it
// (Stronghold, Trauma, Devil, Dilemma), while the open maps won with it (Default, Schooltime 4-0).
constexpr bool CROWD_OPEN_MAPS_ONLY = true;
// A tile some other head in view reaches first is worth less to us (54% vs 69% without it: off).
constexpr bool CLAIM = false;
constexpr int CLAIM_R = 8;
constexpr bool DEBUG_IND = false;     // per-move scores and king status in the replay's indicators

// ---------------------------------------------------------------- v7 switches
// Online, v6 never ate one of Stronghold's fountain pearls in 9 games (the other teams ate 1737)
// and ate 75 of Autarky's against 1234: fountains sit in dead-end corridors, and the room check
// scored every dead end as a death trap. A dragon that is (or will be, after the pocket's pearls)
// 4+ long can always leave one: at the end it splits, and its tail walks out as a new dragon.
// v021 (Ben, Oct 7-8: "our prawn dies at length 3 while fountain farming, and our worms still avoid doing it"). Dead-end
// entries (analysis/pockets.py, ranked, rounds 0-300, 15 games each; v013 07 Oct 15:06-22:47 UTC): we enter 11.7 a game
// and 36% end with a death at length 3 without splitting; aAah 28.0 (3%), Cultery 58.9 (0%), horse 24.3 (9%): the best
// teams go in 4+ long or long enough after eating, and split at the end so only a 2-stub dies. v016b's rules (Oct 7):
// (1) the U-turn on every map: go into a dead end for food if we will be 4+ long, then split out; (2) count pearls in
// view (ev.certain), not expected spawns; (3) never step onto a dead-end tile while shorter than 4 after that step,
// unless every move is that bad; plus v016e's no growth split inside a 1-wide corridor that ends in a dead end within 6
// (the mid-pocket split leaves a 2-long head half that eats once more and dies at 3).
constexpr bool UTURN = false;       // default; per-map in applyMapConfig (v025: unknown maps use FARM_UNSEEN)
// v025 (Oct 8): v021 and v023 (these fountain rules on every map) lost their ladder duels, -0.080 ± 0.063 and
// -0.100 ± 0.070. Their decided duel pairs: known maps 10 vs 19 for the champion (Slithery Fight 2-6, Trophy 1-5,
// Autarky 0-2), unseen maps 7 vs 8. The qualifier plays unseen maps (Ben: "don't forget we're playing on unseen maps"),
// and known maps carry their own tuned settings. So the fountain rules and the stall fix run on unrecognised maps only.
constexpr bool FARM_UNSEEN = true;
// v051 (Ben, Oct 10: "No need for unseen maps, we go on full hard code"): maps.hpp holds all 31 server maps. 21 of them
// the bot never knew (the 7 Oct 2 maps, played blind on purpose until v050, and the 14 that appeared after the Oct 9
// close); v050 played them with the unknown-map rules. NEW_MAP_RULES picks how they play with their map data loaded:
// 0 the known-map settings; 1 the unknown-map rules (applyUnknownConfig, the fountain rules, the stall breaker) on top
// of the map data; 2 as 1, and also on Default, Schooltime and Trophy, whose data changed on Oct 9 (v050's stale copy
// sends most of its dragons there into unknown-map play).
constexpr int NEW_MAP_RULES = 1;
// v051g: on those maps the data serves walls, portals, never-spawn tiles and recognition only; food values, exploring,
// fountain targets and the queen's portal price stay as on an unknown map. Screen vs v050 (all 31 maps, 124 games):
// v050 + the queen fixes alone 0.556, with the full map data in play 0.427-0.468.
constexpr bool NEW_MAP_FOOD_BLIND = true;
// v026 (Ben, Oct 8, on his screenshot: "we can't afford the 2:2: the last pearl gets eaten, it turns into 2:3, the 3 is
// dead, the 2 has to come back, and it repeats 2:3 instead of giving us anything"). v023/v025's no-growth-split rule
// only knew 1-wide corridors; his fountain is two rows deep. Now any closed space ahead of our head (kelp only, our
// neck blocked: bodies ignored, so crowds never trigger it, unlike v016c) of at most POCKET_REGION tiles counts as a
// pocket: no growth split there; the dragon eats to the end and the ceiling split leaves the 2-stub.
constexpr int POCKET_REGION = 12;
constexpr bool DEADEND_GUARD = true;
constexpr double DEADEND_GUARD_PEN = 60.0;
// v023 (Ben, Oct 8, with a screenshot: "still spinning and death on 3; when the worm hits the ceiling of the fountain its
// length stays at 2: after eating all 5 it splits and returns a worm of 3 and one of 2; the 3 goes to eat, now 6, splits
// 3:3, and repeat"). So a dragon goes into a dead-end pocket only if it will be POCKET_MIN_LEN+ long at the end (the
// pearls in view there counted), so the boxed split at the ceiling leaves the 2-stub and sends out a child of 3+.
constexpr int POCKET_MIN_LEN = 5;
// v023c (Ben: "when the worm hits the ceiling its length stays at 2"). Local v023: after the split at the ceiling the
// 2-stub sometimes still had a free tile, ate one more pearl and died at 3 (e.g. dragon 198, Autarky seed 11, r184-186).
// The stub left by a SAVE split eats nothing for STUB_TURNS turns, so it dies at 2 (one pearl) at the ceiling.
constexpr int STUB_TURNS = 6;
constexpr double STUB_NOEAT_PEN = 30.0;
int stubUntil = -1;
constexpr bool POCKET_NO_EARLY_SPLIT = true;
constexpr double UTURN_COST = 1.5;    // two segments and a turn
// Our dragons never came within 17 steps of Stronghold's fountains: at GAMMA 0.75 a pearl 20 steps
// away is worth 0.3% of one in reach. This pulls towards production (pearls per round) instead.
constexpr double PROD_W = 0.0;       // 1.0 still never reached Stronghold's fountains: too flat
constexpr double PROD_GAMMA = 0.93;
// Long-range expected pearls: the same belief the flood fill scores with GAMMA (0.75 a step, so a
// pearl 10 steps away is worth 6%), again with the slow PROD_GAMMA discount. Online the top teams
// swept whole maps and came back to areas unseen for 20+ rounds; ours stayed where they were.
constexpr double LONG_W = 0.0;
// Walk to the nearest fountain cluster within FPULL_MAX steps that no ally in view is working.
constexpr double FPULL = 0.0;         // score per step closer (default; per-map in applyMapConfig)
constexpr int FPULL_MAX = 40;
// Share of dragons (by id hash) that heed the pull. On Schooltime the pull to the 26-tile central
// fountain room (1-20 gap, 2.5 pearls a round) sent every dragon there: 600+ pearls from the room,
// ~270 elsewhere, lost to v11 (which never goes: 0 from the room, ~2300 elsewhere).
constexpr double FPULL_SHARE = 1.0;
constexpr bool FOUNTAIN_KEEPOUT = false; // 3.0 keep-out lost with the rest in c_all; untested alone
constexpr double KEEPOUT_COST = 3.0;
// Rich open patches (Queen of Spades' corners hold 30% of its pearls 9 steps from each team's
// start) get the same pull, a few dragons at a time. 0 = fountains only.
constexpr double RICH_RATE = 0.0;       // tiles making at least this many pearls a round
constexpr double RICH_PER_DRAGON = 0.2; // pearls a round one dragon can live on
// Endgame feeding limits. Online on Schooltime ten feeders died on one turn around a 7-long
// "king" 25-65 tiles from our longest dragon. But throttling (pending 1, king 10+ and 3 longer,
// range 25, crowd 2.0) lost 32-56 to v6 locally, 0-8 on Autarky and Trauma: the king ended
// shorter. Neutral values keep v6's feeding.
constexpr int FEED_PENDING_MAX = 1000; // die only while at most this many pearls lie within 3 of the king's head
constexpr int FEED_MIN_KING = 0;      // never feed a king shorter than this...
constexpr int FEED_KING_MARGIN = -1000; // ...or not this much longer than the feeder
constexpr int FEED_RANGE = 100000;    // farther than this from the king, keep growing instead of walking to it
constexpr double FEED_CROWD = 0.0;    // penalty for a waiting feeder stepping next to the king's head
// In a local v6 game our feeders dropped 44 pearls and the king ate 8 of them: other feeders ate
// 33, then died beside the king and dropped half again. Within NOEAT_R of the king's head a feeder
// sees no food and pays NOEAT_PEN to step on a pearl. -1 = off.
constexpr int NOEAT_R = 12;
constexpr bool KING_VISIBLE_MERGE = false; // step down for a visibly longer ally (45-43: worse than without)
constexpr bool SPLIT_SAFE = false;    // only split when the parent keeps a way out too (never fired: identical games)
constexpr bool DEADEND_CHECK = false; // one-wide dead ends as traps: starved the army on Trauma (pockets hold pearls worth a 2-segment stub)
// Our dragons hugged the map edges near spawn while the top teams took the rich middle: at GAMMA
// 0.75 nothing 10+ steps away counts. Climb the production density field instead, unless the
// area is already crowded with our own heads.
constexpr double DPULL = 0.0;         // score for moving from the poorest (0) to the richest (1) density
constexpr int DENS_R = 4;
constexpr int DPULL_CROWD = 4;        // allied heads in view at which the pull switches off
constexpr double DISP_W = 0.0;        // score per step closer to the dispersal target (0 = off)
constexpr double TABU_PEN = 0.0;      // penalty per recent visit of the destination (0 = off)
constexpr double EAT_BONUS = 2.0;     // bonus for a move that eats a pearl now (0 = off). vs v6: 1.0 28-16 (1.14x pearls by r300), 2.0 30-14 (1.19x)
// The top teams' kings grow all game (SSS on Schooltime: born round 159, never split, 79 long);
// ours stayed 3-6 long until the endgame. >0: elect the king from this round on (it stops
// splitting and keeps eating), long before feeding starts.
constexpr int KING_ELECT_ROUND = 200; // v020b: the queen announces herself from TRICKLE_FROM (was 250)
constexpr bool KING_BRAVE = false;    // the king fears only heads within 2 steps, with smaller penalties
constexpr int TABU_LEN = 20;          // turns of head history remembered
constexpr int DISP_MIN = 8;           // dispersal target at least this far...
constexpr int DISP_MAX = 30;          // ...and at most this far (path length)
constexpr double DISP_DIST_COST = 0.01; // preference for nearer targets
constexpr double DISP_NOISE = 0.6;    // per-child randomness so siblings spread out
constexpr int DISP_TURNS = 40;        // give up walking after this many turns
constexpr double NOEAT_PEN = 20.0;

// Endgame: the army feeds one king. The top teams end games with one 40-90 dragon built this way,
// while ours ended with 30-60 short ones. Every dragon relays the best king it knows (id, head,
// length, round) by sonar; the king keeps eating, and everyone else walks to it and dies beside
// it, dropping ceil(L/2) pearls where it will eat them.
constexpr bool CONSOLIDATE = true;
constexpr int CONS_BASE = 21; // EXP-030 sweep (Oct 6): later feeding (EXP-029: earlier was -0.13/-0.20)       // feeding starts CONS_BASE + (W+H)/2 rounds before the end
constexpr int KING_PREELECT = 30;   // elect (and protect) the king this many rounds before that
constexpr int CONS_WARMUP = 8;      // extra rounds of electing before anyone feeds
constexpr int KING_MARGIN = 3;      // take over a known king only when this much longer
constexpr int KING_STALE = 25;      // rounds without news before a king is presumed dead
// v012c (Ben, Oct 7: "did you trigger the merge?"). In 10 local games (rounds 400+), non-queen dragons that had not
// heard of the queen for KING_STALE rounds elected themselves king (1758 dragon-turns, 109 in the last 5 rounds) and
// were fed instead of her; in 87 ranked v008 games our longest other dragon ended longer than the queen in 24.
// Under QUEEN_RULES a non-queen elects itself only when the queen, once heard, has been silent QUEEN_DEAD_ROUNDS;
// news of the queen (she stays near home) is good for QKING_STALE rounds.
constexpr bool NO_FAKE_KING = true;
constexpr int QKING_STALE = 60;
constexpr int QUEEN_DEAD_ROUNDS = 60;
// v012d: the feeding starts at one round for everyone (~470 - (W+H)/2), so far dragons never arrive: 1024 'too far'
// dragon-turns at rounds 400+ in 10 local games, 262 in the last 5 rounds (median 26 tiles from the queen). From
// FAR_FROM, a dragon whose path to the queen is within FAR_SLACK of the rounds left starts walking to her, and stays.
constexpr bool FAR_FEED = true;
constexpr int FAR_FROM = 340;
constexpr int FAR_SLACK = 12;
bool farFeeding = false;
int heardQueenRound = -1;
constexpr int FEED_RADIUS = 3;      // die once the king's head is this close (path length)
// v020 (Oct 8): trickle feeding, copied from forgot to mention and horse. Their queens gain 10-23 segments per 100
// rounds from rounds 150-350, mostly pearls dropped by their own dragons dying beside her; ours gain 1-4 until the
// endgame feeding (~434), and a queen eats at most one pearl a turn, so a late feed caps her length.
// From TRICKLE_FROM until the feeding, a dragon that sees our queen within FEED_RADIUS dies beside her while little
// food is waiting there and no enemy is near her; our dragons that close leave her food to her.
constexpr bool TRICKLE = true;
constexpr int TRICKLE_FROM = 200;
constexpr int TRICKLE_MIN_UNITS = 10; // only while we have at least this many dragons
constexpr int TRICKLE_MINLEN = 3;     // a feeder drops ceil(L/2) pearls: at least 2
constexpr int TRICKLE_PENDING = 2;    // at most this many pearls already within 3 of her head
constexpr int TRICKLE_ENEMY_R = 5;    // no feeding with an enemy head this close to her
constexpr int TRICKLE_NOEAT_R = 3;
// v020b: v020 alone fed her 5 deaths per 100 rounds (forgot to mention 13-21): our dragons rarely pass her. One dragon
// in TRICKLE_SHARE (by id), within TRICKLE_NAV_R path steps of the announced queen, walks to her until it is within
// FEED_RADIUS (then the trickle rule above decides; no crowding her).
constexpr int TRICKLE_SHARE = 3;
constexpr int TRICKLE_NAV_R = 12;
constexpr double FEED_PULL = 1.0;   // score per step closer to the king
constexpr int FEED_RESERVE = 2;     // dragons besides the king that never feed, so a lost king is not a lost game
constexpr double KING_PORTAL = 3.0; // the king's blind-portal penalty, as a multiple of BLIND_PORTAL
// v9 king safety. Online, our best king (8+ long) died in 56 of 192 games and 27 of those were
// lost: 23 rammed, 16 into another body (a blind portal step, or boxed), 14 into itself.
// KSAVE_BELOW: when the king's best move scores below this (a trap, a blind portal, an enemy's
// reach), it splits off everything but 2 and the tail walks out as the new king.
constexpr double KSAVE_BELOW = -1e9;  // off
constexpr int KING_STRIKE_BONUS = 0;  // added to the enemy sprint range the king keeps out of
// Target pull: v8's flood fill sums discounted value over the whole reachable map, so on maps
// where every pearl sits behind a portal or down a corridor (Portals: 0 pearls in 200 rounds)
// all moves score alike and dragons circle. A dragon now picks the best tile it believes holds
// a pearl (value x TARGET_GAMMA^path length, through portals) and each move scores TARGET_W per
// step it gains towards it.
constexpr double TARGET_W = 0.0;
constexpr double TARGET_GAMMA = 0.85;
constexpr double TARGET_MIN = 0.25;
// v48 (Oct 2): exploration on maps we do not know. On the 7 maps added to the ranked pool that day, v46 had seen
// 27-39% of the map by round 100 and the opponents 60-73%; they had eaten 2-5x our pearls by round 50. An unseen tile
// is worth 0.01, far below TARGET_MIN, so with no pearl in view our dragons had nowhere to go and idled in a pack by
// the spawn. Now a dragon with no target walks to unexplored ground, each one its own way (id and nearby allies).
constexpr bool EXPLORE_TARGET = true;
constexpr double EXPLORE_W = 0.5;        // pull per step towards the exploration target (TARGET_W's scale)
constexpr int EXPLORE_STALE = 80;        // rounds after which a tile we saw counts as unexplored again
constexpr int EXPLORE_MIN = 5;           // ignore unexplored tiles closer than this (they come into view anyway)
constexpr double EXPLORE_GAMMA = 0.97;   // per step: near unexplored ground first
constexpr double EXPLORE_DIR = 0.7;      // weight of our own heading (id) and of the way away from allies in view
constexpr int EXPLORE_KEEP = 40;         // re-pick the target after this many rounds at most
// What an unexplored tile is worth on an unknown map: the share of tiles that already held a pearl when this dragon
// first saw them (pearls pile up where nobody goes). v46 used EXPLORE (0.01), so a remembered countdown (0.55) always
// won and our dragons waited by the spawn while the rest of the map filled up.
constexpr bool UNSEEN_RATE = true;
constexpr double UNSEEN_PRIOR = 0.03, UNSEEN_PRIOR_N = 50; // prior rate and its weight in tiles
constexpr double UNSEEN_SCALE = 1.0;
// >0: explore instead of a target whose discounted value (v x TARGET_GAMMA^steps) is below this
constexpr double EXPLORE_OVER = 0.15;
constexpr std::uint64_t MAGIC = 0xB7C;
// Queens (1 Oct rule change): dragons 0 and 1 are the two queens; at round 500 the longer queen wins (a dead queen
// counts 0), then the longest dragon, then total length. Ours never splits (except to seed an army when she is our
// only dragon), keeps the king's safety rules, and is the dragon the army feeds; any of our other dragons rams theirs.
constexpr bool QUEEN_RULES = true;
constexpr int QUEEN_SEED_UNITS = 3; // the queen may peel 2-segment children while we have fewer dragons than this
// Before this round the queen splits like any starter (she is one of the starters that build the army: frozen from
// round 0 we were wiped out on Devil by round 125); from it she only grows. She keeps the king's safety rules all game.
int queenGrowFrom = 150;
// v60: 15 -> 0.5 (3 still kept her circling). On Stripes (8 portal pairs) the penalty kept our queen circling a 2x2 square for 50 rounds beside
// fountains she rated highest (debug replay, rounds 9-58), and we were eliminated in 26 of 29 ladder games there. The
// friendly-fire risk it was added for is now handled by v52's portal warning (QUEEN_PB).
constexpr double QUEEN_PORTAL_PEN = 15.0;        // maps the bot knows (as v52)
constexpr double QUEEN_PORTAL_PEN_UNKNOWN = 0.5; // unknown maps (v60u)
// v52 (Oct 2, Ben: "our queen just got assassinated by our worms"). In 125 ladder games (09:48-10:00 UTC) our own dragons
// killed our queen head-on 4 times (Portals r83, r192; Trauma r53, r257), each time the same way: the queen (id 0/1, she
// moves first) ended her move beside a portal, then one of ours stepped blind through its far side onto her head. She now
// sends "queen here" through every portal beside her new head. Sonar from a lower id arrives the same round, so the
// dragon at the far side (always a higher id) hears it before it moves and will not cross that portal this round.
constexpr bool QUEEN_PB = true;
constexpr double QUEEN_PB_PEN = 200.0;
constexpr std::uint64_t QPB_MAGIC = 0x9B5;
// S2a (Oct 3, NOTES.md step 2): in 14 local and 38 of 53 ladder head-on deaths of our queen, every single step she had
// was already inside a visible enemy's reach: she was cornered before the killing turn (killers 2-5 long, sprinting
// 2-3 steps). She now pays QFLEE_W per tile inside (an enemy head's reach + QFLEE_RANGE), so she leaves early, and
// QEXIT_PEN per missing exit when her destination would leave fewer than 2 neighbours outside every enemy's reach.
constexpr bool QUEEN_REACH_EXACT = false; // S2c, REJECTED 2026-10-04 (overfit: -0.065 fresh seeds, held-out 0.469): the queen's danger band is each enemy's exact reach (see threat reach)
constexpr bool QUEEN_SPLIT_REACH = true; // S2d: the queen splits only outside every enemy's reach + 1
constexpr bool QUEEN_FLEE = true;
constexpr int QFLEE_RANGE = 3;
// v013 (Oct 7; copied from the teams best at queen survival, analysis/queen_encounters.py): with an enemy head within 4
// our ladder queen moved away 75% of the time (Big Bobs Bots, UnderTheC, Computers, SHINK: 62-68%) but ended with 0-1
// free exits 30.5% (theirs 17-20%; enemy at 1-2: 56.7% vs 24-33%) and died within 3 rounds after 4.2% of those turns
// (theirs 1.2-3.6%). Exits now weigh more than distance (were 3.0 and 8.0). Self-play cannot measure it: there our
// queen ends cornered after 6-7% of encounters (vs v008 or the clones), on the ladder 30.5%.
constexpr double QFLEE_W = 1.0852;
constexpr double QEXIT_PEN = 22.7713;
// v051 (Ben, Oct 10: "WHY IS OUR QUEEN GO INTO THE FOUNTAIN"). v050's 125 test games: our queen died by her own move in 30,
// most of them inside a one-wide dead end or a pocket behind a portal (fountains sit in them): weakhold r386, Islands
// r239, Trauma r294 (through a portal into a maze pocket), Portals, Stripes. The room check (reach >= L + 4) passes a
// dead end longer than she is, and the flood fill lets her own body free up behind her, which a one-wide corridor
// never gives back (replayed inputs: reach 592 on the move before a 15-tile dead end). Boxed, she shed 2 a round
// until she died (Slithery 31 -> 3, weakhold 14 -> 2, Trauma 13 -> 3). Now she counts the tiles past each move with her
// whole body as walls; fewer than QTRAP_MULT x her length + QTRAP_ADD (at least QTRAP_MIN) costs QTRAP_PEN plus
// QTRAP_W per missing tile.
constexpr bool QTRAP = true;
constexpr int QTRAP_MULT = 3, QTRAP_ADD = 10, QTRAP_MIN = 40;
constexpr double QTRAP_PEN = 75.8095, QTRAP_W = 2.0;
// v051: on Schooltime and Detention our queen starts walled into a 2x2 room with a pearl tile; eating to 4 fills it and
// only a split saves her. At r197 and r212 (team 357, Oct 10) we had 64 dragons, the split was illegal and she died;
// their queen split. Our other dragons now never take the 64th slot.
constexpr bool QUEEN_SLOT = true;
// v60 stall breaker (Oct 3; STRATEGY 1l). On Stripes our dragons circled 2x2 squares all game next to fountain pockets
// whose doors are portals: the room check sees 3 tiles behind the door and charges ~26. A dragon (not the queen) that
// has eaten nothing for STALL_ROUNDS turns with its head on at most STALL_TILES tiles pays only STALL_ROOM of the room
// penalty, and STALL_TABU for each recent visit of a tile, so it goes for the food and breaks the loop.
// v63 (Oct 3; STRATEGY 1i): Computers' home queen, once the army is built. v58 (leash from round 0) kept our queen
// alive at the end in 28 of 108 local games vs 14 but cut the army at r100 from 17 to 10; v58b (from round 150) did
// nothing. Here the queen pays QHOME_W per tile beyond QHOME_LEASH from her spawn once we have QHOME_UNITS dragons.
constexpr bool QUEEN_HOME = true;
constexpr int QHOME_LEASH = 5;
constexpr double QHOME_W = 1.9057;
constexpr int QHOME_UNITS = 8;
int homeTile = -1;
// v054 (Ben, Oct 11: "don't forget our hard code strategy"). Per map and queen id, maps.hpp carries her home learned from
// the top teams' replays (analysis/map_plans.py, 2480 winning games Oct 10-11: where the queens that survived to r500 on
// the winning side kept their head in r200-499; within 8 of her spawn, 5+ games). Those queens stay near home to the end
// (Maze 2/2 tiles from spawn over 29/32 games, Trauma 2/1 over 34/40, Ezam 1/2, Whale Song 1/0), while ours leaves when
// the feeding starts (her leash stopped at consStart): the leash now holds all game.
constexpr bool QHOME_LATE = true;
int learnedHome = -1;
// v022 (Ben, Oct 8: "before the merge completes the queen goes off discovering by herself"; "during the merge our queen
// went into a portal and killed herself"). Ranked games since 07 Oct 15:06 UTC with our queen alive when the feeding
// starts (98): she walked 10+ tiles from where she stood then in 41 (20+ in 10), and 1272 of our own-move deaths after
// it were more than 3 from her head (870 within 3). (Corrected Oct 8: the claim that the best teams' queens stay put was
// a bug in analysis/merge_queen.py; re-measured they wander about as much as ours, e.g. forgot to mention 19/25.) QUEEN_HOME's
// leash stops at the feeding, so ours roamed for food. Now from the feeding on she pays QANCHOR_W per tile beyond
// QANCHOR_R from where she stood when it started, and QANCHOR_PORTAL for crossing a portal (blind: bodies crowd her).
constexpr bool QANCHOR = false;  // v022 lost its duel (-0.050 ± 0.065); v023 is built on v020b
constexpr int QANCHOR_R = 3;   // = FEED_RADIUS: feeders die within 3 path steps of her
constexpr double QANCHOR_W = 3.0;
constexpr double QANCHOR_PORTAL = 100.0;
int qAnchor = -1;
// v65 (Oct 3; STRATEGY 1j, rams suffered): when one of our dragons is longer than an enemy head within 2, it dies
// head-on that round 4.2% of the time (v52+v60u, 145 ranked games); Cutlery's 0.8%, DESTINY 3's 1.9%. Cutlery's
// threatened longer dragons split: the head end left facing the enemy is 2 long and the bulk leaves from the tail,
// facing away, so a ram costs 2 segments, not the dragon. Ours now do the same when a shorter enemy head has it
// within its strike reach (ceil(n/4) free steps, then one segment a step down to 2).
// v66 (Oct 3; STRATEGY 1i): half our queen's deaths are self-collisions, and in 26 of 53 of those (ranked, 12:00-23:52
// UTC Oct 2) one of OUR dragons' heads sat beside her and closed her last way out (she moves first, so a dragon that
// ended its move beside her takes one of her exits for her next move). Our dragons now pay QGAP_PEN for ending beside
// our queen's head (QGAP_PEN_TIGHT when she has at most 2 free sides).
constexpr double EAT_NOW_BONUS = 2.8082;
constexpr bool QUEEN_GAP = true;
constexpr double QGAP_PEN = 4.0;
constexpr double QGAP_PEN_TIGHT = 15.0;
constexpr bool THREAT_SPLIT = true;
constexpr int TSPLIT_MIN_LEN = 4;
constexpr bool STALL_BREAK = true;
constexpr int STALL_ROUNDS = 12;
constexpr int STALL_TILES = 6;   // v021: 4 missed loops that widen to 6 tiles (Stripes: 6 of every 12)
constexpr double STALL_ROOM = 0.0;
constexpr double STALL_TABU = 1.0;
// v021 (Oct 8; Ben: "our worms are tweaking out"). Ranked v013 games (07 Oct 15:06 UTC on, rounds 0-300): our
// non-queen dragons spent 3.6% of their turns on <= 6 tiles over 12 turns without eating, weakhold 43.7%, Stripes
// 22.5%, Trauma 6.8%, Portals 6.4% (aAah 0.5%, Cultery 0.8%, horse 1.3%). The breaker never fired on them: the loops
// cover 6 tiles, and while stalled the dangling else below charged the soft room penalty once per history tile (~-9),
// cancelling STALL_ROOM. Re-played on the ladder loops (Stripes 1385290, weakhold 1384515) the fixed build steps into
// the pocket (+3.9 to +5.3 vs -1.5 to -3.1). Now up to 6 tiles and no soft penalty while stalled (v025: unknown maps only).
constexpr bool STALL_ALL_MAPS = false; // v025: unknown maps only (as in v60)
int stallLastL = -1, stallLastEat = 0;
std::vector<int> stallHist;
int sprintFree = 1;                 // a sprint's first ceil(L/4) steps are free (1 Oct rule change; was 1)
// v056 (Ben, Oct 11: "sprinting is super powerful, make use of it"; the speed-aware BFS). Ranked games Oct 10-11
// (analysis/queen_sprint_use.py): the top 10's queens move 2+ steps on 20.8% of their moves at length 5-8, 18.6% at 9-12
// and 31.1% at 13+ (+-50 Elo: 35.6 / 37.4 / 32.6%), and a multi-step move eats 0.466 pearls against 0.044 for a single
// step: they sprint to eat. Ours never sprints (FREE_SPRINT leaves the queen out) except QESC2's 2-step escape.
// docs/movement.md + execution-order.md: L is fixed when the move starts; each step checks her body as the last step left
// it (tail included) and eats; she is id 0/1 and moves first, so only the tile she ends on can be struck before her next
// turn; vision stops at portals, so no step crosses one.
// v065 (Ben, Oct 11-12: algorithm queue #12): v056 with its 10 core constants from SPSA (lab.spsa, spsa/v056_core.json, 40
// iterations x 44 self-play games, data/spsa_v056_core.json): QHOME_LEASH 4 -> 5, QHOME_W 2.0 -> 1.91, QTRAP_PEN 80.0 -> 75.81, QSAFE2_PEN 45.0 -> 63.16, QEXIT_PEN 25.0 -> 22.77, QFLEE_W 1.5 -> 1.09, QS_MIN_GAIN 1.0 -> 1.17, QS_DANGER_W 6.0 -> 5.99, EAT_NOW_BONUS 3.0 -> 2.81, CONS_BASE 30 -> 21.
constexpr bool QSPRINT = true;          // farming sprint: free steps that eat visible pearls
constexpr bool QESC_LONG = true;        // 9+: escape over up to 3 free steps into the safest territory
constexpr bool QRACE = true;            // her pearl target is discounted where an enemy arrives first
constexpr int QS_MAX_STEPS = 3;
constexpr int QS_HORIZON = 4;           // rounds the danger map looks ahead
constexpr int QS_FAR = 99;              // danger-map value of a tile no visible enemy reaches within the horizon
constexpr int QS_VIEW = 2;              // a farming sprint stays within this Chebyshev distance of her head (a seen ring beyond)
constexpr double QS_FIRST_SLACK = 3.0;  // a sprint may start with any step scored within this of her best single step
constexpr double QS_EAT_W = 3.0;        // per pearl eaten after the first step (= EAT_NOW_BONUS)
constexpr double QS_STEP_COST = 0.3;    // per extra step
constexpr double QS_MIN_GAIN = 1.1663;     // a sprint must beat her single step by this much
constexpr int QS_SAFE_T = 3;            // rounds of margin from every enemy that count as safe
constexpr double QS_DANGER_W = 5.9885;     // per round of margin lost below QS_SAFE_T
constexpr int QS_VERIFY = 6;            // farming candidates checked in full, best first
constexpr long long QS_BUDGET = 45000000;
constexpr double QRACE_MULT = 0.35;     // = the contention discount for a pearl another head gets to first
bool raceQueen = false;
// v070 (Ben, Oct 11-12: algorithm queue #9, space-time A* and beam search). analysis/queen_move_profile.py (ranked since
// Oct 11 12:00, 25 games a top team, 75 ours; queen moves only): the share of her eats that were spawned pearls eaten
// within 2 rounds of appearing: aAah 60%, chat gippy tea 38%, Cutlery 31%, larp 24%, WeHaveQuizzes 22%, horse 16%, SSS
// 14%, forgot to mention 9%, us 15%. At 13+ long, moves of 4+ steps: chat gippy tea 50%, aAah 25%, Cutlery 13%, horse
// 5%, WeHaveQuizzes 6%, us 0% (QS_MAX_STEPS 3).
// Space-time arrival (QSPACETIME): her fills valued a visible tile whose pearl spawns after she could get there at 0
// (a pearl at 2 steps spawning in 4 rounds was worth nothing until 2 rounds before); now she arrives when it spawns
// (waiting nearby, up to QST_WAIT rounds): worth 0.7 discounted by the rounds to the spawn instead of the steps.
// Beam search (QBEAM): with 4+ free steps (13+ long) her escape and farming sprints search paths of up to QS_MAX_LONG
// free steps, depth by depth keeping the QS_BEAM best partial paths by a cheap value (pearls eaten, rounds of margin
// at the end tile, steps).
constexpr bool QSPACETIME = true;
constexpr int QST_WAIT = 6;
constexpr bool QBEAM = true;
constexpr int QS_MAX_LONG = 5;
constexpr int QS_BEAM = 32;
bool qSpaceTime = false; // this turn: we are the queen
std::vector<int> dgT; // v056: the danger map (dangerMap below)
// Pocket farming. Online on Autarky the top teams ate 337 fountain pearls a game to our 30: their
// small dragons walk into the dead-end fountain pockets, eat to the end, split the tail side out
// as a new dragon and leave the 2-segment stub to die there (its pearl waits for the next visit).
// Ours scored pockets as traps (reach < length + 4) and walked past. A pocket is a tree of tiles
// cut off by pruning leaves of the open graph, entered through one tile, making fountain pearls.
constexpr bool POCKET = false;           // default; per-map cfg.pocket
constexpr int POCKET_MAXLEN = 4;         // only dragons this short go in
constexpr int POCKET_RANGE = 14;         // path length to the pocket's far end
constexpr double POCKET_W = 2.0;         // score per step closer to the far end
constexpr double POCKET_MIN_PROD = 0.5;  // pearls per round the pocket must make
constexpr int POCKET_MAX_SIZE = 10;      // tiles
constexpr int POCKET_UNIT_MARGIN = 1;    // go in only below unit_limit - this: the end split needs a free unit slot
// Corridor look-ahead. On Schooltime (rounds 25-150) we lost 51 small dragons a game to self-collision
// and 22 to other bodies, the top teams 9 and 6: two of our dragons walked into the same 1-wide kelp
// corridor from both ends and one could not turn. Before stepping into a corridor, walk it to the next
// junction; another dragon's head inside costs CORR_PEN, less the farther it is.
constexpr double CORR_PEN = 0.0;         // 0 = off
constexpr int CORR_MAX = 8;              // corridor tiles looked at

// ---------------------------------------------------------------- per-map settings
// The bot recognises every ranked map, and local tests show some features win on one map and
// lose on another (fountain pull: 7-1 on Stronghold, 0-8 on Autarky). Defaults are the constants
// above; applyMapConfig overrides them once the map is known.
struct Config {
    bool uturn = UTURN;
    double fpull = FPULL;
    bool keepout = FOUNTAIN_KEEPOUT;
    int consBase = CONS_BASE;
    double blindPortal = BLIND_PORTAL;
    int areaPerUnit = AREA_PER_UNIT;
    int feedRadius = FEED_RADIUS;
    int splitUntil = SPLIT_UNTIL;
    int noeatR = NOEAT_R;
    double dpull = DPULL;
    double tabuPen = TABU_PEN;
    double eatBonus = EAT_BONUS;
    double dispW = DISP_W;
    bool probe = PORTAL_PROBE;
    double targetW = TARGET_W;
    bool pocket = POCKET;
    int pocketRange = POCKET_RANGE;
    int ramMargin = RAM_MARGIN;
    // One-wide dead ends as traps (DEADEND_CHECK) per map, with the price of splitting back out. Off everywhere: on
    // Queen of Spades and Devil it never changed a move (identical games). The one-tile pockets our dragons die in
    // there are the last move of dragons already boxed in by the crowd (see crowdForce).
    bool deadend = DEADEND_CHECK;
    double deadendSplitCost = UTURN_COST;
    double slowBoost = 1.0;   // unseen slow beds (gap > 50) are worth this many times unseenPearl's estimate
    // >0: crowding penalty with this weight even on fountain maps (CROWD_OPEN_MAPS_ONLY turns it off there).
    // Queen of Spades: V2's dragons boxed each other in inside the 6x2 rich rooms (40 self-hits a game, top teams 7).
    double crowdForce = CROWD_FORCE;
    int feedReserve = FEED_RESERVE; // dragons besides the king that never feed (per map / unknown maps)
    // A split's child moves last in the round, after every other dragon: online on Slithery 85 children a game died on
    // their first move (22 on Devil). Free tiles needed next to our tail before we split.
    int splitMinExits = SPLIT_MIN_EXITS;
    double fpullProdW = 0.0; // fountain pull: weight of cluster production against distance
    double pocketShare = 1.0; // share of dragons (by id hash) that farm pockets
    bool earlySplit = EARLY_SPLIT;
    double fastPrior = FAST_PRIOR;
    int ramSteps = RAM_STEPS;
    bool preyHunt = PREY_HUNT;
    bool othersFree = OTHERS_FREE;
    bool pessRoom = PESS_ROOM;
    bool midSafe = MID_SAFE;
    bool ptEnable = PT_ENABLE;
    bool feedNoEnemy = FEED_NO_ENEMY;
    bool feedAny = FEED_ANY;
    double kingRepel = KING_REPEL;
    int longFrom = LONG_FROM;
    bool longProtect = LONG_PROTECT;
    bool kingNoBlind = KING_NO_BLIND;
    bool pbEnable = PB_ENABLE;
    int feedRange = FEED_RANGE;
    bool bodyVisFix = BODY_VIS_FIX;
    int feedKingMargin = FEED_KING_MARGIN;
    double allyAdj = ALLY_ADJ;
    bool allyAdjAll = ALLY_ADJ_ALL;
    double pessW = PESS_W;
    double pessLethal = PESS_LETHAL;
    double cutPen = CUT_PEN;
    double richRate = RICH_RATE;
    double richPerDragon = RICH_PER_DRAGON;
    int fpullMax = FPULL_MAX;
    double fpullShare = FPULL_SHARE;
};
Config cfg;
int consStart = 1 << 30; // round the endgame feeding starts (set once the map is known)

// Settings for a map we do not know (every Sprint and Qualifier map): the target pull (on for Default, Slithery,
// Portals, Dilemma) until the king election. SPRT vs v18: blind official maps 100-64 (LLR +2.79 after passing at 151),
// generated 105-64 (+3.26); vs nick on generated 72/120 (v18 59). Weak: blind Trauma 5-15, Trophy 7-13.
// v22: Devil's ally spacing (every ally head, 2.0) on unknown maps too. Screen of 12 per-map settings as unknown-map
// defaults (30 Sep): best of them, self 71-41, vs nick 57-55 (v21 48-64). SPRT vs blind_v21 on blind official maps
// 223-175 (56%, PASS at 391; Trauma 24-8, Default 20-10, Big Empty 19-11, Slithery 13-19).
extern int R;
void applyUnknownConfig() {
    cfg.targetW = R < 250 ? 0.5 : 0.0;
    cfg.allyAdj = 2.0;
    cfg.allyAdjAll = true;
    // v23 (30 Sep): our 6+ dragons keep out of shorter enemies' sprint reach (MID_SAFE). On blind official maps + random
    // maps (13 + 3, both colours) vs nick_cpp: 29/64 and 18/64 on seeds 1-2 / 3-4 (Last Sleep 23/64, 16/64); head to head
    // vs Last Sleep 38/64. In a random-map loss the endgame lost 16 dragons of 10+ to 2-3 long rammers.
    cfg.midSafe = false; // ablation (Oct 3)
}
void applyMapConfig(std::string const& name) {
    // Per-map overrides (local benchmarks against v6, 8 games per map per variant).
    if (name == "Stronghold") {
        // U-turn + fountain pull: 7-1 against v6 (the dead-end corridor factory).
        cfg.uturn = true;
        cfg.fpull = 0.5;
    }
    if (name == "Prisoners Dilemma" || name == "Queen Of Spades") {
        // Anti-circling: dragons lapped 2x2 squares beside the fountain channels. Pearls eaten by
        // round 300 vs v6: Dilemma 3.16x (0.4), Queen of Spades 1.60x (0.8); elsewhere it cost food.
        cfg.tabuPen = name == "Prisoners Dilemma" ? 0.4 : 0.8;
    }
    if (name == "Devil") {
        // Children walk to a rich spot 8-30 steps away before foraging: 2.96x v6's pearls by
        // round 300 here (0.96x over all maps).
        cfg.dispW = 0.3;
    }
    if (name == "Default") {
        // Portals are the way from the spawn edges to the rich middle: with the blind-portal
        // penalty at 12 we ate 0.55x v6's pearls here by round 300.
        cfg.blindPortal = 3.0;
    }
    // v9 grid, 10 games per map per setting against v8 (seeds 11-15, both colours): wins out of 10
    // for (v8 behaviour / probe / probe + target / target). Off by default everywhere else.
    if (name == "Trophy" || name == "Trauma") cfg.probe = true;            // 5/8/6/3, 5/8/5/5
    if (name == "Default" || name == "Slithery Fight") {                    // 5/6/8/7, 6/5/8/4
        cfg.probe = true;
        cfg.targetW = 0.5;
    }
    if (name == "Portals" || name == "Prisoners Dilemma") cfg.targetW = 0.5; // 0/2/6/8, 5/5/8/8
    // Pocket farming, 20 games per map against v9 (seeds 1-10, both colours): Autarky 16-4,
    // Dilemma 20-0, Trauma 17-3, Stronghold 10-10, Slithery Fight 0-20 (its 14 small pockets pulled
    // every dragon off the open fountains: other pearls 139 vs 867).
    // Stronghold too: Trauma dragons run on Stronghold settings until they tell the two apart, and with
    // pockets on for Trauma only, v10 lost 12 of 12 there (the factory never started).
    if (name == "Autarky" || name == "Prisoners Dilemma" || name == "Trauma" || name == "Stronghold") cfg.pocket = true;
    // Autarky's pockets are 20+ steps from much of the map: range 20 went 75-25 against v11 (100 games,
    // seeds 501-550). On Trauma the same range lost 7-33, so it stays at 14 elsewhere.
    if (name == "Autarky") cfg.pocketRange = 20;
    // Equal-length rams (RAM_MARGIN 0) passed overall, but on Dilemma v12 lost every game as team B against v9,
    // eliminated at round 52 (three dragons a side: a 1-for-1 trade leaves us outnumbered). Dilemma keeps v10's
    // margin. On Autarky pocket range 20 needs the rams: vs v8/v9 (80 games) range 14 / 20 with margin 1 scored
    // 57.5% / 32.5%, with margin 0 57.5% / 65.0%.
    if (name == "Prisoners Dilemma") cfg.ramMargin = 1;
    if (name == "Autarky") cfg.ramMargin = 0;
    // Hotfix 27 Sep: online, v12 lost all 16 Autarky games (15 by elimination, some by round 89-112). The top teams
    // farm their own pockets and fight us inside ours, which none of our local opponents did. Autarky goes back to
    // v9's play: no pocket farming, v9's ram margin.
    if (name == "Autarky") { cfg.pocket = false; cfg.pocketRange = POCKET_RANGE; cfg.ramMargin = 1; }
    // v15, measured against the C++ public bot (nick_cpp), which beats v12 on the same maps we lose online.
    // Schooltime: a third of its pearls come from the 26-tile fountain room at the bottom centre (gap 1-20), which
    // isFountain() never counted (gap <= 5), so we ate 0 there. 40% of our dragons walk to it (4 per cluster):
    // 17/32 vs 1/32 without (shares 0.2 / 0.3 / 0.5 / 0.6: 4/16, 7/16, 9/32, 15/32). All dragons (1.0) starve the rest.
    if (name == "Schooltime") {
        cfg.richRate = 0.09;
        cfg.richPerDragon = 0.6;
        cfg.fpullMax = 80;
        cfg.fpullShare = 0.4;
        cfg.fpull = 0.5;
    }
    // v34t: Trophy makes 2.4 pearls a round; its 11 centre tiles (gap 5-30) make 0.63 of them. Against the organisers'
    // dev test 1 (Oct 2) we lost 6/6 there, eliminated by round 35-137: it walks straight to the centre and had eaten
    // 37-55 pearls by round 50 to our 11-22. Half our dragons now head for the centre (Schooltime's fountain pull).
    if (name == "Trophy") {
        cfg.richRate = 0.05;
        cfg.richPerDragon = 0.2;
        cfg.fpullMax = 40;
        cfg.fpullShare = 0.5;
        cfg.fpull = 0.5;
    }
    // Portals: long dragons (5+ from round 80 stop splitting and keep eating): 16-16 and 14-18 vs 6-26 and 3-29.
    // On Slithery the same lost (7-25 vs 11-21); on Trauma too (13-19 vs 20-12).
    // v030 (Ben, Oct 8: "why is dude not splitting" / "why is dude still using the great wall of china strat"): on the
    // ladder these 15-20 long dragons line the corridors; the rule came from a September local test against our own old
    // bots and was never checked on the ladder (ranked Portals since 07 Oct 15:06 UTC: won 6/12). Off.
    if (name == "Portals" && PORTALS_LONG) cfg.longFrom = 80;
    // Slithery Fight: other dragons' bodies never free up in the flood fills (the C++ bot's rule): 12-20 and 12-20
    // vs 4-28 and 7-25 without (on Schooltime 29-35 vs 24-40 over two runs: too close, left off).
    if (name == "Slithery Fight") cfg.othersFree = false;
    // v16 (27-28 Sep, teammate's build, reconstructed from the site's copy): Autarky uturn, Queen of Spades crowding,
    // Slithery feeding 40 rounds earlier.
    if (name == "Autarky") cfg.uturn = true;
    if (name == "Queen Of Spades") cfg.crowdForce = 0.3;
    // v19: online QoS losses, the opponents ate 37-75 slow-bed pearls outside the two fast-bed rooms by r300 to our
    // 3-26 (by r200 ~20% of the 410 unseen slow beds hold a pearl). x2/x4/x8/x16 won 65/65/68/54 of 96 vs nick_cpp
    // (v18 59); x8 passed SPRT vs v18 on QoS, 102-62 (LLR +3.19).
    if (name == "Queen Of Spades") cfg.slowBoost = 8.0;
    if (name == "Slithery Fight") cfg.consBase = 100;
    // v17 (29 Sep). Online (v15+v16, 823 games) Autarky was 21-24%: the other team ate ~230 fountain pearls a game from the
    // home-corridor pockets (170 from theirs, 59 from ours), we ate ~10. Half our dragons farm pockets: vs nick_cpp 18/32 and
    // 14/32 (no pockets 7/32, 4/32; shares 0.3 8/32, 0.4 10/32, 0.6 12/32, all dragons 9/32 with 5 eliminations).
    if (name == "Autarky") {
        cfg.pocket = true;
        cfg.pocketShare = 0.5;
    }
    // Devil: online v16 won 22% (28 of 40 losses by elimination). Charging for ending next to any ally head: vs nick_cpp
    // 45/48 (base 37/48), vs v16 29/48 (base 24/48), eliminations 14 vs 21 per 64.
    if (name == "Devil") {
        cfg.allyAdj = 2.0;
        cfg.allyAdjAll = true;
        cfg.crowdForce = 0.0;
    }
    // v18: starters split in half on their first turn like the top teams (vs v17, 160 games: Default 12-4, Slithery 12-4,
    // Trauma 10-6; Devil 4-12, so not there).
    if (name == "Default" || name == "Slithery Fight" || name == "Trauma") cfg.earlySplit = true;
    // v18: an unseen gap-1 fountain is worth 0.7 of a pearl however long ago we looked (Portals 11-5 vs v17; 0.9 worse).
    if (name == "Portals") cfg.fastPrior = 0.7;
}

// ---------------------------------------------------------------- geometry
constexpr int DX[4] = {0, 1, 0, -1};
constexpr int DY[4] = {-1, 0, 1, 0};
constexpr char DC[4] = {'N', 'E', 'S', 'W'};
inline int opp(int d) { return d ^ 2; }

int W, H, N;
int R;

inline int X(int i) { return i % W; }
inline int Y(int i) { return i / W; }
inline int at(int x, int y) { return ((y % H + H) % H) * W + ((x % W + W) % W); }
// Speed: the wrapped neighbour of every tile in every direction, filled once in main() (same values as at()).
std::vector<int> nbT;
inline int nb(int i, int d) { return nbT[i * 4 + d]; }
inline int wrapDist(int a, int b, int size) {
    int d = std::abs(a - b);
    return std::min(d, size - d);
}
inline int manhattan(int a, int b) { return wrapDist(X(a), X(b), W) + wrapDist(Y(a), Y(b), H); }
inline int dirIndex(Direction d) {
    switch (d.value) {
    case Direction::NORTH: return 0;
    case Direction::EAST:  return 1;
    case Direction::SOUTH: return 2;
    default:               return 3;
    }
}

// ---------------------------------------------------------------- memory
std::vector<int> lastSeen;      // round the tile was last in vision, -1 never
double firstSeen = 0, firstPearl = 0; // tiles this dragon saw for the first time, and how many held a pearl
inline double unseenRate() { return (firstPearl + UNSEEN_PRIOR * UNSEEN_PRIOR_N) / (firstSeen + UNSEEN_PRIOR_N); }
std::vector<char> pearl;        // pearl present when last seen
std::vector<char> spawnState;   // 0 unknown, 1 observed, 2 inferred by symmetry
std::vector<char> never;        // tile never spawns
std::vector<int> spawnAt;       // round of the next spawn attempt
std::vector<int> spawnObs;      // round spawnAt was observed
std::vector<signed char> edgeT; // per tile*4+dir: -1 unknown, 0 open, 1 kelp, 2 portal
std::vector<char> edgeObs;
std::vector<int> portalId;
std::unordered_map<int, std::vector<int>> portals; // id -> canonical edge codes

// this turn's dragons
std::vector<int> occStamp;   // == R when another dragon's segment is on the tile
std::vector<int> ownStamp;   // == R when our own segment is on the tile
std::vector<int> ownIndex;   // index from the head of that segment
std::vector<int> otherFree;  // first step (1 = this move) at which that segment is surely gone
constexpr int NEVER_FREE = 1 << 29;

struct Head {
    int pos, id, len;
    bool enemy;
    int reach = 1; // S2c: tiles this head can strike this round (enemies only; set in the S2c block of takeTurn)
};

inline int canon(int i, int d) {
    if (d == 2) return nb(i, 2) * 4 + 0;
    if (d == 1) return nb(i, 1) * 4 + 3;
    return i * 4 + d;
}

void setEdge(int i, int d, int type, int pid) {
    int j = nb(i, d);
    edgeT[i * 4 + d] = static_cast<signed char>(type);
    edgeT[j * 4 + opp(d)] = static_cast<signed char>(type);
    edgeObs[i * 4 + d] = edgeObs[j * 4 + opp(d)] = 1;
    portalId[i * 4 + d] = portalId[j * 4 + opp(d)] = pid;
    if (type == 2 && pid >= 0) {
        auto& list = portals[pid];
        int c = canon(i, d);
        if (std::find(list.begin(), list.end(), c) == list.end())
            list.push_back(c);
    }
}

// Destination of stepping from i in direction d, or -1 when blocked/unknown.
int stepTo(int i, int d) {
    int e = edgeT[i * 4 + d];
    if (e == 1) return -1;
    if (e == 2) {
        int pid = portalId[i * 4 + d];
        if (pid < 0) return -1;
        auto it = portals.find(pid);
        if (it == portals.end()) return -1;
        int mine = canon(i, d);
        for (int c : it->second) {
            if (c == mine) continue;
            int t = c / 4, cd = c % 4;
            if (cd == 3) {
                if (d == 1) return t;
                if (d == 3) return nb(t, 3);
            } else {
                if (d == 2) return t;
                if (d == 0) return nb(t, 0);
            }
            return -1;
        }
        return -1;
    }
    return nb(i, d);
}

int openDegree(int t) {
    int k = 0;
    for (int d = 0; d < 4; d++)
        if (stepTo(t, d) >= 0) k++;
    return k;
}

// ---------------------------------------------------------------- symmetry
bool symAlive[3] = {true, true, true};
int symStrong[3] = {0, 0, 0};
bool symApplied[3] = {false, false, false};
constexpr int SYM_CONFIDENT = 6;

inline int mirrorTile(int s, int i) {
    int x = X(i), y = Y(i);
    if (s != 1) x = W - 1 - x;
    if (s != 0) y = H - 1 - y;
    return y * W + x;
}
inline int mirrorDir(int s, int d) {
    if (s == 2) return opp(d);
    bool horizontal = (d == 1 || d == 3);
    if (s == 0) return horizontal ? opp(d) : d;
    return horizontal ? d : opp(d);
}
inline int edgeClass(int e) { return e == 1 ? 1 : (e == 2 ? 2 : 0); }

void checkSymmetry(int t) {
    for (int s = 0; s < 3; s++) {
        if (!symAlive[s]) continue;
        int m = mirrorTile(s, t);
        if (m == t) continue;
        for (int d = 0; d < 4 && symAlive[s]; d++) {
            int md = mirrorDir(s, d);
            if (!edgeObs[t * 4 + d] || !edgeObs[m * 4 + md]) continue;
            int a = edgeClass(edgeT[t * 4 + d]), b = edgeClass(edgeT[m * 4 + md]);
            if (a != b) symAlive[s] = false;
            else if (a != 0) symStrong[s]++;
        }
        if (!symAlive[s]) continue;
        if (spawnState[t] == 1 && spawnState[m] == 1) {
            if (never[t] != never[m]) {
                symAlive[s] = false;
            } else if (!never[t] && spawnAt[t] > spawnObs[m] && spawnAt[m] > spawnObs[t]) {
                if (spawnAt[t] != spawnAt[m]) symAlive[s] = false;
                else symStrong[s]++;
            }
        }
    }
}

void inferFrom(int s, int t) {
    int m = mirrorTile(s, t);
    if (m == t) return;
    for (int d = 0; d < 4; d++) {
        int md = mirrorDir(s, d);
        if (edgeObs[t * 4 + d] && !edgeObs[m * 4 + md] && edgeT[m * 4 + md] < 0) {
            int e = edgeT[t * 4 + d];
            int j = nb(m, md);
            // Mirrored portals lead somewhere we do not know yet, so treat them as closed.
            edgeT[m * 4 + md] = edgeT[j * 4 + opp(md)] = static_cast<signed char>(e);
            portalId[m * 4 + md] = portalId[j * 4 + opp(md)] = -1;
        }
    }
    if (spawnState[t] == 1 && spawnState[m] != 1) {
        spawnState[m] = 2;
        never[m] = never[t];
        spawnAt[m] = spawnAt[t];
        spawnObs[m] = spawnObs[t];
    }
}

inline bool symUsable(int s) { return symAlive[s] && symStrong[s] >= SYM_CONFIDENT; }

// ---------------------------------------------------------------- known maps
int mapIdx = -1;             // index into maps::all once the map is recognised
bool unseenRules = true;     // play by the unknown-map rules: no map loaded, or a map NEW_MAP_RULES names
bool playsUnseen(std::string_view name) {
    static constexpr std::string_view fresh[] = {
        "Stripes", "Tower Defense", "Islands", "Around UNSW", "weakhold", "Maze", "Australia", "athena", "atlantis",
        "caution", "detention", "ezam", "hive", "maelstrom", "metro", "ouroboros", "thermopylae", "troll_australia",
        "trolley problem", "Trolley Problem (Buffed)", "whale_song",
        // v051j: Autarky too. Its tuned pocket farming with the Oct 9 data: 1/12 vs v050 (10 old maps, 3 seeds, 00:2x Oct 11),
        // with the unknown-map rules 7/12. Schooltime 8 vs 1, Trophy 6 vs 1, Slithery Fight 7 vs 3 keep their tuned settings
        // (Default and Prisoners Dilemma 4 either way).
        "Autarky"};
    static constexpr std::string_view changed[] = {"Default", "Schooltime", "Trophy"};
    // 3: also the other three maps the organisers changed on Oct 9 (v050's stale data sends its dragons to unknown-map
    // play there once they see a changed tile; local Autarky with the correct data and its tuned settings: 0/4).
    static constexpr std::string_view changed3[] = {"Autarky", "Prisoners Dilemma", "Slithery Fight"};
    if (NEW_MAP_RULES >= 3)
        for (auto f : changed3)
            if (name == f) return true;
    if (NEW_MAP_RULES >= 1)
        for (auto f : fresh)
            if (name == f) return true;
    if (NEW_MAP_RULES >= 2)
        for (auto f : changed)
            if (name == f) return true;
    return false;
}
std::vector<int> gapLo, gapHi; // spawn range of each tile (gapHi 0 = never spawns)
std::vector<char> nearFountain; // within 2 tiles of a tile spawning every <= 5 rounds
bool mapHasFountain = false;
std::vector<double> prodRate;   // pearls per round the tile makes while empty (mean of its spawn range)
std::vector<double> prodDensity; // production within DENS_R tiles, scaled so the map's richest spot is 1
// Fountain clusters (connected tiles spawning every <= 5 rounds) and the path length from every tile
// to each cluster through the map's kelp and portals.
std::vector<int> fountainCluster;            // cluster index per tile, -1 if not a fountain
std::vector<std::vector<int>> fountainDist;  // [cluster][tile]
std::vector<char> clusterIsFountain;         // false: a rich open patch rather than a fountain corridor
std::vector<int> clusterCap;                 // dragons the cluster can feed at once
std::vector<double> clusterProd;             // pearls a round the cluster makes
std::vector<char> clusterTaken;              // this turn: an ally in view is working the cluster
struct Pocket {
    std::vector<int> tiles;
    int entrance = -1; // the open tile the pocket hangs off
    int deep = -1;     // its far end
    double prod = 0;   // fountain pearls per round
    std::vector<int> dist; // path length from every tile to `deep`
};
std::vector<Pocket> pockets;
std::vector<int> pocketOf; // pocket index per tile, -1 outside
void findPockets();

inline int edgeKindOf(Edge const& e) {
    return e.edge_type == EdgeType::KELP ? 1 : (e.edge_type == EdgeType::PORTAL ? 2 : 0);
}

void loadMap(int m) {
    maps::MapRec const& M = maps::all[m];
    mapIdx = m;
    portals.clear();
    mapHasFountain = false;
    std::fill(nearFountain.begin(), nearFountain.end(), 0);
    for (int i = 0; i < N; i++) {
        gapLo[i] = M.pal[M.tile[i] * 2];
        gapHi[i] = M.pal[M.tile[i] * 2 + 1];
        never[i] = gapHi[i] <= 0;
        for (int d = 0; d < 4; d++) {
            edgeT[i * 4 + d] = 0;
            edgeObs[i * 4 + d] = 1;
            portalId[i * 4 + d] = -1;
        }
    }
    for (int k = 0; k < M.nEdges; k++) {
        maps::EdgeRec const& e = M.edges[k];
        setEdge(e.code / 4, e.code % 4, e.kind, e.kind == 2 ? e.pid : -1);
    }
    for (int i = 0; i < N; i++)
        prodRate[i] = gapHi[i] > 0 ? 2.0 / (std::max(1, gapLo[i]) + gapHi[i]) : 0.0;
    {
        // Box sum of production around each tile (wrapping), via row then column prefix passes.
        std::vector<double> rowSum(N, 0.0);
        for (int y = 0; y < H; y++)
            for (int x = 0; x < W; x++) {
                double sum = 0;
                for (int dx = -DENS_R; dx <= DENS_R; dx++) sum += prodRate[at(x + dx, y)];
                rowSum[y * W + x] = sum;
            }
        double mx = 1e-9;
        for (int y = 0; y < H; y++)
            for (int x = 0; x < W; x++) {
                double sum = 0;
                for (int dy = -DENS_R; dy <= DENS_R; dy++) sum += rowSum[at(x, y + dy)];
                prodDensity[y * W + x] = sum;
                mx = std::max(mx, sum);
            }
        for (int i = 0; i < N; i++) prodDensity[i] /= mx;
    }
    fountainCluster.assign(N, -1);
    fountainDist.clear();
    clusterIsFountain.clear();
    clusterCap.clear();
    clusterProd.clear();
    auto isFountain = [&](int t) { return gapHi[t] > 0 && gapHi[t] <= 5; };
    auto isRich = [&](int t) { return cfg.richRate > 0 && !isFountain(t) && prodRate[t] >= cfg.richRate; };
    for (int pass = 0; pass < 2; pass++)
    for (int i = 0; i < N; i++) {
        bool const fountain = pass == 0;
        if (fountainCluster[i] >= 0 || !(fountain ? isFountain(i) : isRich(i))) continue;
        int const c = static_cast<int>(fountainDist.size());
        std::vector<int> members{i};
        fountainCluster[i] = c;
        for (std::size_t h = 0; h < members.size(); h++)
            for (int d = 0; d < 4; d++) {
                int nx = stepTo(members[h], d);
                if (nx < 0 || fountainCluster[nx] >= 0 || !(fountain ? isFountain(nx) : isRich(nx))) continue;
                fountainCluster[nx] = c;
                members.push_back(nx);
            }
        double prod = 0;
        for (int m : members) prod += prodRate[m];
        clusterIsFountain.push_back(fountain);
        clusterCap.push_back(fountain ? 1 : std::max(1, static_cast<int>(prod / cfg.richPerDragon + 0.5)));
        clusterProd.push_back(prod);
        std::vector<int> dist(N, -1);
        std::vector<int> q(members);
        for (int m : members) dist[m] = 0;
        for (std::size_t h = 0; h < q.size(); h++)
            for (int d = 0; d < 4; d++) {
                int nx = stepTo(q[h], d);
                if (nx < 0 || dist[nx] >= 0) continue;
                dist[nx] = dist[q[h]] + 1;
                q.push_back(nx);
            }
        fountainDist.push_back(std::move(dist));
    }
    for (int i = 0; i < N; i++) {
        if (gapHi[i] <= 0 || gapHi[i] > 5) continue;
        mapHasFountain = true;
        for (int dy = -2; dy <= 2; dy++)
            for (int dx = -2; dx <= 2; dx++) nearFountain[at(X(i) + dx, Y(i) + dy)] = 1;
    }
    pockets.clear();
    pocketOf.clear();
    if (M.sym >= 0) {
        for (int s = 0; s < 3; s++) {
            symAlive[s] = s == M.sym;
            symStrong[s] = s == M.sym ? SYM_CONFIDENT : 0;
        }
    }
}

// Keeps every bundled map that agrees with everything seen so far: size, which tiles never
// spawn, and every edge. v6 loaded the first map that fitted the opening view, but Stronghold and
// Trauma are both 48x24 with identical spawn corners, so on Trauma it ran with Stronghold's walls
// and spawn ranges. Now the view is checked every turn while more than one map fits, and a
// contradicted map is swapped for the next candidate. Unknown maps fall back to exploring.
std::vector<int> mapCands;
bool mapCandsInit = false;
std::vector<std::vector<signed char>> candEdge; // per map: kind by canonical edge code, built lazily
std::size_t candsAtLoad = 0; // mapCands.size() when the map data was last loaded
constexpr bool CAND_BLANK = true; // edges the remaining candidates disagree on are unknown until seen

void identifyMap(Controller& ct) {
    if (!MAP_KNOWLEDGE) return;
    if (!mapCandsInit) {
        mapCandsInit = true;
        candEdge.resize(maps::count);
        // v050 (Ben, Oct 9: fountain farming bugs on Maze): Maze's start views fit Stronghold (toolkit map, not on the
        // ladder, same 48x24); our dragons there played with Stronghold's walls and the known-map settings (fountain rules
        // off) on 2-15% of turns until their view contradicted it. Stronghold is never a candidate.
        for (int m = 0; m < maps::count; m++)
            if (maps::all[m].W == W && maps::all[m].H == H && std::string_view(maps::all[m].name) != "Stronghold") mapCands.push_back(m);
    }
    if (mapCands.size() == 1 && mapIdx == mapCands[0]) { // settled
        if (unseenRules) applyUnknownConfig();           // its target pull ends at round 250
        return;
    }
    std::vector<int> keep;
    for (int m : mapCands) {
        maps::MapRec const& M = maps::all[m];
        std::vector<signed char>& kind = candEdge[m];
        if (kind.empty()) {
            kind.assign(N * 4, 0);
            for (int k = 0; k < M.nEdges; k++) kind[M.edges[k].code] = M.edges[k].kind;
        }
        bool ok = true;
        for (Tile const& tile : ct.get_tiles()) {
            int i = at(tile.position.x, tile.position.y);
            // v051: a countdown is drawn from [min_gap, max_gap] and only counts down (docs/pearls.md), so one above the
            // tile's max_gap rules the map out. Local captures (Ezam, Troll Australia, Detention, Devil; 7.3M readings,
            // round 0 included): never above max_gap; on its first turn a dragon's view rules out the look-alike map
            // for 62% (Ezam/Maze) to 98% (Devil) of dragons.
            int const pt = tile.get_pearl_time(), hi = M.pal[M.tile[i] * 2 + 1];
            if ((pt < 0) != (hi <= 0) || pt > hi) { ok = false; break; }
            for (int d = 0; d < 4 && ok; d++)
                if (kind[canon(i, d)] != edgeKindOf(tile.edges[d])) ok = false;
            if (!ok) break;
        }
        if (ok) keep.push_back(m);
    }
    mapCands = keep;
    if (mapCands.empty()) {
        // Not a map we know. v8 kept whichever map it had loaded, so on Portals (new on 26 Sep,
        // the same size as Devil and Dilemma) it played with another map's walls. Forget the
        // loaded map; the vision loop below re-learns edges from what we see.
        if (mapIdx >= 0) {
            mapIdx = -1;
            std::fill(edgeT.begin(), edgeT.end(), static_cast<signed char>(-1));
            std::fill(edgeObs.begin(), edgeObs.end(), 0);
            std::fill(portalId.begin(), portalId.end(), -1);
            portals.clear();
            std::fill(gapLo.begin(), gapLo.end(), 0);
            std::fill(gapHi.begin(), gapHi.end(), 0);
            std::fill(nearFountain.begin(), nearFountain.end(), 0);
            mapHasFountain = false;
            fountainCluster.assign(N, -1);
            fountainDist.clear();
            clusterIsFountain.clear();
            clusterCap.clear();
            clusterProd.clear();
    clusterProd.clear();
            pockets.clear();
            pocketOf.assign(N, -1);
            for (int t = 0; t < N; t++) never[t] = spawnState[t] == 1 ? never[t] : 0;
            for (int k = 0; k < 3; k++) { symAlive[k] = true; symStrong[k] = 0; symApplied[k] = false; }
            cfg = Config{};
            consStart = LAST_ROUND - cfg.consBase - (W + H) / 2;
        }
        unseenRules = true;
        learnedHome = -1;
        cfg = Config{};
        applyUnknownConfig();
        return;
    }
    // v051: maps that share a size and a start (Ezam/Maze, Troll Australia/Australia, Detention/Schooltime, Trolley Problem
    // (Buffed)/Trolley Problem) kept the dragons on the first one's walls: replayed ladder inputs (team 357, Oct 10) were on
    // the wrong map 62% of turns on Ezam, 70% on Troll Australia, 20% on Detention, 21% on Trolley Problem (Buffed). Each
    // time the candidates change the map is reloaded and every edge they disagree on is unknown until seen.
    if (mapIdx < 0 || std::find(mapCands.begin(), mapCands.end(), mapIdx) == mapCands.end() || mapCands.size() != candsAtLoad) {
        candsAtLoad = mapCands.size();
        cfg = Config{};
        unseenRules = playsUnseen(maps::all[mapCands[0]].name);
        learnedHome = ct.get_id() <= 1 ? maps::all[mapCands[0]].qhome[ct.get_id()] : -1;
        if (!unseenRules) applyMapConfig(maps::all[mapCands[0]].name); // before loadMap: the fountain clusters use cfg.richRate
        loadMap(mapCands[0]);
        for (std::size_t c = 1; CAND_BLANK && c < mapCands.size(); c++) {
            std::vector<signed char> const& k0 = candEdge[mapCands[0]];
            std::vector<signed char> const& kc = candEdge[mapCands[c]];
            for (int code = 0; code < N * 4; code++) {
                if (kc[code] == k0[code]) continue;
                int const i = code / 4, d = code % 4, j = nb(i, d);
                edgeT[i * 4 + d] = edgeT[j * 4 + opp(d)] = -1;
                edgeObs[i * 4 + d] = edgeObs[j * 4 + opp(d)] = 0;
                portalId[i * 4 + d] = portalId[j * 4 + opp(d)] = -1;
            }
        }
        if (cfg.pocket) findPockets(); // only where it is on: 14 pockets cost Slithery children 20M on turn one
        consStart = LAST_ROUND - cfg.consBase - (W + H) / 2;
    }
    if (unseenRules) applyUnknownConfig();
}

// Powers of the fixed discount bases, tabulated: the flood fills called std::pow for every tile
// of every candidate move. Same values as std::pow, so play is unchanged, only faster.
struct PowTable {
    double base;
    double v[1024];
    explicit PowTable(double b) : base(b) {
        for (int i = 0; i < 1024; i++) v[i] = std::pow(b, i);
    }
    double operator()(int e) const { return e >= 0 && e < 1024 ? v[e] : std::pow(base, e); }
};
PowTable const pow0985(0.985), pow099(0.99), pow0997(0.997), pow097(0.97);
PowTable const explorePow(EXPLORE_GAMMA); // chooseExplore's discount, tabulated (std::pow(EXPLORE_GAMMA, k) values)

// Chance that tile i, out of sight since lastSeen, holds a pearl when we arrive in round `arrive`.
double unseenPearl0(int i, int arrive);
double unseenPearl(int i, int arrive) {
    double const v = unseenPearl0(i, arrive);
    return gapHi[i] > 50 ? v * cfg.slowBoost : v;
}
double unseenPearl0(int i, int arrive) {
    if (gapHi[i] <= 0) return 0.0;
    // A fast fountain (gap 1-2) refills the round after it is emptied: in top-team games it holds a pearl 57-91% of
    // the time, however long ago we looked.
    if (cfg.fastPrior > 0 && gapHi[i] <= 2) return cfg.fastPrior;
    int const age = lastSeen[i] < 0 ? R : R - lastSeen[i];
    if (lastSeen[i] >= 0 && pearl[i]) return 0.75 * pow0985(age);
    if (spawnState[i] && spawnAt[i] >= 0) {
        if (spawnAt[i] > arrive) return 0.0;
        return 0.6 * pow099(std::max(0, R - spawnAt[i]));
    }
    if (BELIEF_FAST > 0 && lastSeen[i] < 0 && gapHi[i] > BELIEF_FAST) return EXPLORE;
    // Never seen: the first countdown is drawn from [gapLo, gapHi], so the pearl has appeared by
    // `arrive` with this chance, and someone may have eaten it since.
    double p = static_cast<double>(arrive + 1 - gapLo[i]) / (gapHi[i] - gapLo[i] + 1);
    p = std::max(0.0, std::min(1.0, p));
    return 0.55 * p * pow0997(R);
}

// ---------------------------------------------------------------- self
std::vector<int> body;      // our own segments, head first (may miss far tail parts)
std::vector<int> predicted; // what body should be next turn
bool isKing = false;
bool isFirst = false;   // each team's first starter (id 0 for A, 1 for B)
bool bigBorn = false;   // started life at BIG_BORN+ segments
int firstRound = -1;
// Portal probe: the ray sent last turn, and what its echo said.
int probeDir = -1, probeFrom = -1, probeRound = -10;
int verdictDir = -1, verdictFrom = -1, verdictRound = -10;
bool verdictClear = false;
int nextHead = -1, nextFacing = -1; // where our head will be after this turn's action (-1 unknown)

// Did last turn's probe clear a crossing from `head` in direction d? The ray left from the head we
// had after last turn's move, along d; it covers this crossing if we are still on that line.
bool probedClear(int head, int d) {
    if (!cfg.probe || verdictRound != R || !verdictClear || verdictDir != d || verdictFrom < 0) return false;
    int t = verdictFrom;
    for (int k = 0; k <= PROBE_RANGE; k++) {
        if (t == head) return edgeT[head * 4 + d] == 2;
        if (edgeT[t * 4 + d] != 0) return false; // the ray met kelp or another portal before us
        t = nb(t, d);
    }
    return false;
}

// The line from `from` to probe this turn: the nearest portal straight ahead or to a side.
int chooseProbe(int from, int facing) {
    int bestK = PROBE_RANGE + 1, bestD = -1;
    for (int d = 0; d < 4; d++) {
        if (facing >= 0 && d == opp(facing)) continue; // that ray would leave through our tail
        int t = from;
        for (int k = 0; k <= PROBE_RANGE; k++) {
            int const e = edgeT[t * 4 + d];
            if (e == 2) {
                if (k < bestK || (k == bestK && d == facing)) { bestK = k; bestD = d; }
                break;
            }
            if (e == 1) break;
            t = nb(t, d);
            if (occStamp[t] == R || ownStamp[t] == R) break;
        }
    }
    return bestD;
}
int kingSplits = 0;
int exploreTgt = -1, exploreSet = -1000;
std::vector<int> exploreDist;
int bornLen = 0;
// Dispersal: a new child walks to a rich spot some distance away before it forages.
std::vector<int> recentHeads; // our head position on each of the last TABU_LEN turns
int dispTarget = -1;
int pocketTarget = -1; // the pocket this dragon is farming, -1 none
int dispUntil = -1;
std::vector<int> dispDist;

std::unordered_map<int, int> ptAlly, ptEnemy; // portal id -> last round another dragon touched it
std::unordered_map<int, int> pbRx; // portal id -> last round an ally on its far side said it is using it
std::unordered_map<int, int> qpbRx; // v52: portal id -> last round our queen said she is at its far side

// ---------------------------------------------------------------- endgame king
struct KingInfo {
    int id = -1, pos = -1, len = 0, round = -1000;
};
KingInfo king;
int teamIdx = 0;
std::vector<int> distKing;

std::uint64_t checksum(std::uint64_t v) {
    v ^= 0x9E3779B97F4A7C15ULL * static_cast<std::uint64_t>(teamIdx + 1);
    v ^= v >> 29;
    v *= 0xBF58476D1CE4E5B9ULL;
    v ^= v >> 32;
    return v & 0xFF;
}
std::uint64_t encodeKing(KingInfo const& k) {
    std::uint64_t v = MAGIC | (static_cast<std::uint64_t>(k.id & 0x1FFF) << 12) |
                      (static_cast<std::uint64_t>(X(k.pos)) << 25) | (static_cast<std::uint64_t>(Y(k.pos)) << 31) |
                      (static_cast<std::uint64_t>(std::min(k.len, 1023)) << 37) |
                      (static_cast<std::uint64_t>(k.round & 0x1FF) << 47);
    return v | (checksum(v) << 56);
}
bool decodeKing(std::uint64_t v, KingInfo& k) {
    std::uint64_t const b = v & ((1ULL << 56) - 1);
    if ((b & 0xFFF) != MAGIC || (v >> 56) != checksum(b)) return false;
    int const x = static_cast<int>((b >> 25) & 63), y = static_cast<int>((b >> 31) & 63);
    if (x >= W || y >= H) return false;
    k.id = static_cast<int>((b >> 12) & 0x1FFF);
    k.pos = at(x, y);
    k.len = static_cast<int>((b >> 37) & 1023);
    k.round = static_cast<int>((b >> 47) & 0x1FF);
    return true;
}
// v40 intel: enemy head sightings (id, head tile, visible length, round), kept per enemy id and relayed until stale.
struct Sighting {
    int id = -1, pos = -1, len = 0, round = -1000;
};
std::vector<Sighting> intel;
void noteSighting(int id, int pos, int len, int rnd) {
    if (rnd > R || R - rnd > INTEL_TTL || pos < 0) return;
    for (Sighting& s : intel)
        if (s.id == id) {
            if (rnd > s.round || (rnd == s.round && len > s.len)) s = {id, pos, len, rnd};
            return;
        }
    if (static_cast<int>(intel.size()) < INTEL_MAX) {
        intel.push_back({id, pos, len, rnd});
        return;
    }
    auto oldest = std::min_element(intel.begin(), intel.end(), [](Sighting const& a, Sighting const& b) { return a.round < b.round; });
    if (oldest->round < rnd) *oldest = {id, pos, len, rnd};
}
void pruneIntel() {
    intel.erase(std::remove_if(intel.begin(), intel.end(), [](Sighting const& s) { return R - s.round > INTEL_TTL || s.round > R; }),
                intel.end());
}
// Prey sightings use the king's layout under their own magic: (enemy id, head tile, visible length, round).
KingInfo prey;
bool preyToSend = false;
std::vector<int> preyDist;
std::uint64_t encodePrey(KingInfo const& k) {
    std::uint64_t v = (encodeKing(k) & ~0xFFFULL & ((1ULL << 56) - 1)) | PREY_MAGIC;
    return v | (checksum(v) << 56);
}
bool decodePrey(std::uint64_t v, KingInfo& k) {
    std::uint64_t const b = v & ((1ULL << 56) - 1);
    if ((b & 0xFFF) != PREY_MAGIC || (v >> 56) != checksum(b)) return false;
    return decodeKing((b & ~0xFFFULL) | MAGIC | (checksum((b & ~0xFFFULL) | MAGIC) << 56), k);
}
std::uint64_t encodeIntel(Sighting const& s) {
    KingInfo k;
    k.id = s.id; k.pos = s.pos; k.len = s.len; k.round = s.round;
    std::uint64_t v = (encodeKing(k) & ~0xFFFULL & ((1ULL << 56) - 1)) | INTEL_MAGIC;
    return v | (checksum(v) << 56);
}
bool decodeIntel(std::uint64_t v, Sighting& s) {
    std::uint64_t const b = v & ((1ULL << 56) - 1);
    if ((b & 0xFFF) != INTEL_MAGIC || (v >> 56) != checksum(b)) return false;
    KingInfo k;
    if (!decodeKing((b & ~0xFFFULL) | MAGIC | (checksum((b & ~0xFFFULL) | MAGIC) << 56), k)) return false;
    s.id = k.id; s.pos = k.pos; s.len = k.len; s.round = k.round;
    return true;
}
// Food: two (tile, round, present) items. present: a pearl lay there at `round`; else the tile spawns at `round`.
struct Food {
    int tile = -1, round = 0;
    bool present = false;
};
std::vector<Food> foodOut;
std::uint64_t encodeFood(Food const& a, Food const& b) {
    auto item = [](Food const& f) -> std::uint64_t {
        return (static_cast<std::uint64_t>(f.tile & 0xFFF)) | (static_cast<std::uint64_t>(f.round & 0x1FF) << 12) |
               (static_cast<std::uint64_t>(f.present ? 1 : 0) << 21);
    };
    std::uint64_t v = FOOD_MAGIC | (item(a) << 12) | (item(b) << 34);
    return v | (checksum(v) << 56);
}
int unwrapRound(int r9) {
    // 9-bit rounds: the one closest to now.
    int best = r9;
    for (int k = -1; k <= 1; k++) {
        int c = (R & ~0x1FF) + k * 512 + r9;
        if (std::abs(c - R) < std::abs(best - R)) best = c;
    }
    return best;
}
void takeFood(std::uint64_t v) {
    std::uint64_t const b = v & ((1ULL << 56) - 1);
    if ((b & 0xFFF) != FOOD_MAGIC || (v >> 56) != checksum(b)) return;
    for (int k = 0; k < 2; k++) {
        std::uint64_t const it = (b >> (12 + 22 * k)) & ((1ULL << 22) - 1);
        int const tile = static_cast<int>(it & 0xFFF), rnd = unwrapRound(static_cast<int>((it >> 12) & 0x1FF));
        bool const present = (it >> 21) & 1;
        if (tile >= N || (k == 1 && tile == static_cast<int>(b >> 12 & 0xFFF))) continue;
        if (present) {
            if (rnd > R || R - rnd > 8 || lastSeen[tile] >= rnd) continue;
            pearl[tile] = 1;
            lastSeen[tile] = std::min(rnd, R - 1);
        } else {
            if (spawnState[tile] == 1 && spawnObs[tile] >= R - 1) continue;
            if (rnd < R) continue;
            spawnState[tile] = 2;
            never[tile] = 0;
            spawnAt[tile] = rnd;
            spawnObs[tile] = R - 1;
        }
    }
}
std::uint64_t encodePB(int pid) {
    std::uint64_t v = PB_MAGIC | (static_cast<std::uint64_t>(pid & 0xFFF) << 12) | (static_cast<std::uint64_t>(R & 0x1FF) << 24);
    return v | (checksum(v) << 56);
}
std::uint64_t encodeQPB(int pid) {
    std::uint64_t v = QPB_MAGIC | (static_cast<std::uint64_t>(pid & 0xFFF) << 12) | (static_cast<std::uint64_t>(R & 0x1FF) << 24);
    return v | (checksum(v) << 56);
}
bool decodeQPB(std::uint64_t v, int& pid, int& rnd) {
    std::uint64_t const b = v & ((1ULL << 56) - 1);
    if ((b & 0xFFF) != QPB_MAGIC || (v >> 56) != checksum(b)) return false;
    pid = static_cast<int>((b >> 12) & 0xFFF);
    rnd = static_cast<int>((b >> 24) & 0x1FF);
    return true;
}
// v64 (Oct 3): the ladder had 3 more friendly queen kills after v52 (Portals r317, Trauma r398, Default r168). In all
// three the killer HAD the queen's warning for that portal, sent that round, but the portal was its only move that
// was not certain death (kelp, its own body or an ally's body on the other three sides), so the 200 penalty decided
// nothing. A warned portal is now never a move: the dragon splits or dies where it is instead of on her head.
bool qpbWarned(int head, int d) {
    if (edgeT[head * 4 + d] != 2 || portalId[head * 4 + d] < 0) return false;
    auto b = qpbRx.find(portalId[head * 4 + d]);
    return b != qpbRx.end() && R - b->second <= 1;
}
bool decodePB(std::uint64_t v, int& pid, int& rnd) {
    std::uint64_t const b = v & ((1ULL << 56) - 1);
    if ((b & 0xFFF) != PB_MAGIC || (v >> 56) != checksum(b)) return false;
    pid = static_cast<int>((b >> 12) & 0xFFF);
    rnd = static_cast<int>((b >> 24) & 0x1FF);
    return true;
}
inline bool preyFresh() { return prey.id >= 0 && R - prey.round <= PREY_TTL && prey.round <= R; }
// A fresher sighting replaces an older one of the same dragon; a stale one, or one much shorter, gives way.
void considerPrey(KingInfo const& k, bool relay) {
    if (R - k.round > PREY_TTL || k.round > R) return;
    bool take = !preyFresh() || (k.id == prey.id ? k.round > prey.round : (k.len > prey.len + 2 || (k.len >= prey.len && k.round > prey.round)));
    if (!take) return;
    prey = k;
    if (relay) preyToSend = true;
}
inline bool kingStale() {
    int const stale = (NO_FAKE_KING && QUEEN_RULES && king.id >= 0 && king.id <= 1) ? QKING_STALE : KING_STALE;
    return king.id < 0 || R - king.round > stale;
}
void considerKing(KingInfo const& k) {
    int const stale = (NO_FAKE_KING && QUEEN_RULES && k.id >= 0 && k.id <= 1) ? QKING_STALE : KING_STALE;
    if (R - k.round > stale || k.round > R) return;
    if (k.id >= 0 && k.id <= 1) heardQueenRound = std::max(heardQueenRound, k.round);
    if (k.id == king.id) {
        if (k.round > king.round) king = k;
        return;
    }
    if (QUEEN_RULES) {
        // v46: the queens are dragons 0 and 1, one per team, and the server lists either team first: in 327 of our
        // last 652 ladder games our queen was id 1 as team A (or 0 as B) and had none of her rules (survived 4% vs 18%).
        // King messages are ours (team key), so an id of 0 or 1 here is our queen.
        if (king.id <= 1 && king.id >= 0 && !kingStale()) return; // a live queen is never replaced
        if (k.id <= 1) { king = k; return; }
    }
    if (kingStale() || k.len > king.len || (k.len == king.len && k.id < king.id)) king = k;
}
// Path length from every tile to `src`, through known kelp and portals (moves are reversible).
void bfsFrom(int src, std::vector<int>& d) {
    std::fill(d.begin(), d.end(), -1);
    static std::vector<int> q;
    if (q.size() != static_cast<std::size_t>(N)) q.assign(N, 0);
    int qh = 0, qt = 0;
    q[qt++] = src;
    d[src] = 0;
    while (qh < qt) {
        int cur = q[qh++];
        for (int dir = 0; dir < 4; dir++) {
            int nx = stepTo(cur, dir);
            if (nx < 0 || d[nx] >= 0) continue;
            d[nx] = d[cur] + 1;
            q[qt++] = nx;
        }
    }
}

void findPockets() {
    pockets.clear();
    pocketOf.assign(N, -1);
    auto nbrs = [&](int t, int* out) {
        int k = 0;
        for (int d = 0; d < 4; d++) {
            int s = stepTo(t, d);
            if (s < 0 || s == t) continue;
            bool dup = false;
            for (int j = 0; j < k; j++) dup = dup || out[j] == s;
            if (!dup) out[k++] = s;
        }
        return k;
    };
    int buf[4];
    std::vector<int> deg(N, 0), q;
    std::vector<char> removed(N, 0), seen(N, 0);
    for (int t = 0; t < N; t++) {
        deg[t] = nbrs(t, buf);
        if (deg[t] <= 1) q.push_back(t);
    }
    for (std::size_t h = 0; h < q.size(); h++) {
        int t = q[h];
        if (removed[t]) continue;
        removed[t] = 1;
        int k = nbrs(t, buf);
        for (int j = 0; j < k; j++)
            if (!removed[buf[j]] && --deg[buf[j]] <= 1) q.push_back(buf[j]);
    }
    std::vector<int> comp, dist;
    for (int t = 0; t < N; t++) {
        if (!removed[t] || seen[t]) continue;
        comp.assign(1, t);
        seen[t] = 1;
        int entrance = -1;
        bool multi = false;
        for (std::size_t h = 0; h < comp.size(); h++) {
            int k = nbrs(comp[h], buf);
            for (int j = 0; j < k; j++) {
                int s = buf[j];
                if (removed[s]) {
                    if (!seen[s]) { seen[s] = 1; comp.push_back(s); }
                } else {
                    if (entrance >= 0 && entrance != s) multi = true;
                    entrance = s;
                }
            }
        }
        if (entrance < 0 || multi || static_cast<int>(comp.size()) > POCKET_MAX_SIZE) continue;
        double prod = 0;
        for (int c : comp)
            if (gapHi[c] > 0 && gapHi[c] <= 10) prod += prodRate[c];
        if (prod < POCKET_MIN_PROD) continue;
        Pocket p;
        p.tiles = comp;
        p.entrance = entrance;
        p.prod = prod;
        dist.assign(N, -1);
        bfsFrom(entrance, dist);
        p.deep = comp[0];
        for (int c : comp)
            if (dist[c] > dist[p.deep]) p.deep = c;
        p.dist.assign(N, -1);
        bfsFrom(p.deep, p.dist);
        for (int c : comp) pocketOf[c] = static_cast<int>(pockets.size());
        pockets.push_back(std::move(p));
    }
}

void rebuildBody(int head, int headDir, int len, std::vector<std::pair<int, int>> const& mine) {
    // mine: (pos, facing) of our non-head segments in vision.
    body.assign(1, head);
    std::vector<char> used(mine.size(), 0);
    int cur = head;
    int lastDir = headDir;
    while (true) {
        int found = -1;
        for (std::size_t k = 0; k < mine.size(); k++) {
            if (used[k]) continue;
            if (nb(mine[k].first, mine[k].second) == cur) {
                found = static_cast<int>(k);
                break;
            }
        }
        if (found < 0) break;
        used[found] = 1;
        cur = mine[found].first;
        lastDir = mine[found].second;
        body.push_back(cur);
    }
    if (!BODY_INFER) return;
    // Segments beyond the 7x7 window: assume the body carries on the way its last seen segment
    // points, which is how every map lays out its starters. Real history (`predicted`) replaces
    // this as soon as we have moved. A guess that lands inside the window where we saw no segment
    // of ours is wrong, so stop there rather than invent more.
    while (static_cast<int>(body.size()) < len) {
        int nx = nb(cur, opp(lastDir));
        bool inView = std::max(wrapDist(X(nx), X(head), W), wrapDist(Y(nx), Y(head), H)) <= 3;
        if (inView || std::find(body.begin(), body.end(), nx) != body.end()) break;
        cur = nx;
        body.push_back(cur);
    }
}

// ---------------------------------------------------------------- search
std::vector<int> dist;
std::vector<int> queueBuf;
int noEatCenter = -1; // this turn: the king's head, when we are a feeder
int noEatR = 0;       // this turn: the radius around noEatCenter (cfg.noeatR, or TRICKLE_NOEAT_R)
std::vector<int> claimD;        // manhattan distance to the nearest other head in view (capped)

struct Eval {
    double score;
    int reach;
    double pearls; // expected pearls in the reachable area, undiscounted
    int certain = 0; // v016: pearls in view in the reachable area, the start tile excluded
};

// Scores standing on `start` after the first move, with our body `bodyLen` long
// and every old segment shifted one further from the head (`shift`).
// What a tile is worth to a dragon arriving `t` steps from now (same rules as the flood fill).
double tileValue(int cur, int t, std::vector<double> const& contention) {
    int const arriveRound = R + t - 1;
    double v = 0;
    if (lastSeen[cur] == R) {
        if (pearl[cur]) v = 1.0 * contention[cur];
        else if (spawnState[cur] && !never[cur] && spawnAt[cur] > R && spawnAt[cur] <= arriveRound) v = 0.7;
        else if (qSpaceTime && spawnState[cur] && !never[cur] && spawnAt[cur] > arriveRound && spawnAt[cur] - arriveRound <= QST_WAIT)
            v = 0.7 * std::pow(TARGET_GAMMA, spawnAt[cur] - arriveRound); // v070: she waits for it
    } else if (mapIdx >= 0 && !(NEW_MAP_FOOD_BLIND && unseenRules)) {
        v = unseenPearl(cur, arriveRound);
    } else {
        int age = lastSeen[cur] < 0 ? 1000 : R - lastSeen[cur];
        if (lastSeen[cur] >= 0 && pearl[cur]) v = 0.7 * pow097(age);
        if (spawnState[cur] && !never[cur] && spawnAt[cur] > lastSeen[cur] && spawnAt[cur] <= arriveRound)
            v = std::max(v, 0.55);
    }
    if (noEatCenter >= 0 && manhattan(cur, noEatCenter) <= noEatR) v = 0;
    return v;
}

std::vector<int> targetDist;
// The tile worth heading for, or -1: best value x TARGET_GAMMA^steps over everything reachable.
int chooseTarget(int head, int L, std::vector<double> const& contention) {
    std::fill(dist.begin(), dist.end(), -1);
    int qh = 0, qt = 0;
    queueBuf[qt++] = head;
    dist[head] = 0;
    int best = -1;
    double bestSc = 0;
    double g = 1.0;
    int gk = 0;
    while (qh < qt) {
        int cur = queueBuf[qh++];
        int k = dist[cur];
        if (k > 0) {
            while (gk < k) { g *= TARGET_GAMMA; gk++; }
            double v = tileValue(cur, k, contention);
            // v056 QRACE: an enemy strikes the tile in fewer rounds than she needs to get there (she moves first: ties are hers)
            if (raceQueen && v > 0 && dgT[cur] < (k + sprintFree - 1) / sprintFree) v *= QRACE_MULT;
            if (v >= TARGET_MIN && v * g > bestSc) { bestSc = v * g; best = cur; }
        }
        if (k >= 60) continue;
        for (int d = 0; d < 4; d++) {
            int nx = stepTo(cur, d);
            if (nx < 0 || dist[nx] >= 0) continue;
            if (occStamp[nx] == R && (!cfg.othersFree || k + 2 < otherFree[nx])) continue;
            if (ownStamp[nx] == R && k + 1 < L - ownIndex[nx]) continue;
            dist[nx] = k + 1;
            queueBuf[qt++] = nx;
        }
    }
    return best;
}

// v48: the unexplored tile to walk to, or -1. Uses `dist` as left by chooseTarget (from our head, same rules).
// Score: staleness x EXPLORE_GAMMA^steps x preference for our heading, where the heading is our id's direction plus
// the way away from the allies we can see (so a pack fans out instead of all taking the nearest gap).
int chooseExplore(int head, double hx, double hy) {
    int best = -1;
    double bestSc = 0;
    double const n = std::sqrt(hx * hx + hy * hy);
    if (n > 1e-9) { hx /= n; hy /= n; }
    for (int t = 0; t < N; t++) {
        int const k = dist[t];
        if (k < EXPLORE_MIN) continue;
        double const stale = lastSeen[t] < 0 ? 1.0 : std::min(1.0, (R - lastSeen[t]) / static_cast<double>(EXPLORE_STALE));
        if (stale <= 0) continue;
        int dx = X(t) - X(head), dy = Y(t) - Y(head);
        if (dx > W / 2) dx -= W; else if (dx < -W / 2) dx += W;
        if (dy > H / 2) dy -= H; else if (dy < -H / 2) dy += H;
        double const len = std::sqrt(static_cast<double>(dx * dx + dy * dy));
        double const pref = 1.0 + EXPLORE_DIR * (len > 0 ? (dx * hx + dy * hy) / len : 0.0);
        double const sc = stale * pref * explorePow(k);
        if (sc > bestSc) { bestSc = sc; best = t; }
    }
    return best;
}

bool evalNoBlindPortal = false; // protected dragons: space behind a portal we cannot see does not count
Eval evaluate(int start, int bodyLen, int shift, std::vector<double> const& contention) {
    std::fill(dist.begin(), dist.end(), -1);
    int qh = 0, qt = 0;
    queueBuf[qt++] = start;
    dist[start] = 0;
    double score = 0;
    double pearls = 0;
    int certain = 0;
    int reach = 0;
    // CPU guard for maps larger than any official one (64x64 costs ~17M a turn; 128x128 ~52M; the engine allows 256x256):
    // there the fill stops growing at FILL_CAP tiles, far more than any space check needs.
    int const fillCap = N > 4096 ? FILL_CAP : N;
    double gpow[512];
    gpow[0] = 1;
    for (int k = 1; k < 512; k++) gpow[k] = gpow[k - 1] * GAMMA;
    static double gslow[512];
    if (gslow[0] == 0) {
        gslow[0] = 1;
        for (int k = 1; k < 512; k++) gslow[k] = gslow[k - 1] * PROD_GAMMA;
    }

    while (qh < qt) {
        int cur = queueBuf[qh++];
        int k = dist[cur];
        reach++;
        int t = k + 1; // total steps from now
        int arriveRound = R + t - 1;

        double v = 0;
        if (cur != start && lastSeen[cur] == R && pearl[cur]) certain++;
        if (lastSeen[cur] == R) {
            if (pearl[cur]) v = 1.0 * contention[cur];
            else if (spawnState[cur] && !never[cur] && spawnAt[cur] > R && spawnAt[cur] <= arriveRound) v = 0.7;
            else if (qSpaceTime && spawnState[cur] && !never[cur] && spawnAt[cur] > arriveRound && spawnAt[cur] - arriveRound <= QST_WAIT)
                v = 0.7 * gpow[spawnAt[cur] - arriveRound]; // v070: she waits for it
        } else if (mapIdx >= 0 && !(NEW_MAP_FOOD_BLIND && unseenRules)) {
            v = unseenPearl(cur, arriveRound);
        } else {
            int age = lastSeen[cur] < 0 ? 1000 : R - lastSeen[cur];
            if (lastSeen[cur] >= 0 && pearl[cur]) v = 0.7 * pow097(age);
            if (spawnState[cur] && !never[cur] && spawnAt[cur] > lastSeen[cur] && spawnAt[cur] <= arriveRound)
                v = std::max(v, 0.55);
            v += EXPLORE * std::min(1.0, age / 60.0);
            if (UNSEEN_RATE && lastSeen[cur] < 0) v = std::max(v, UNSEEN_SCALE * unseenRate());
        }
        // Feeders leave the food around the king to the king (see NOEAT_R).
        if (noEatCenter >= 0 && manhattan(cur, noEatCenter) <= noEatR) v = 0;
        if (CLAIM && v > 0 && !(lastSeen[cur] == R && pearl[cur])) {
            if (claimD[cur] < t) v *= 0.35;
            else if (claimD[cur] == t) v *= 0.7;
        }
        score += v * gpow[std::min(k, 511)];
        if (LONG_W > 0) score += LONG_W * v * gslow[std::min(k, 511)];
        pearls += v;
        // Long range: head for where pearls are made. The short discount above cannot see a
        // fountain 20 steps away; this one can.
        if (PROD_W > 0) score += PROD_W * prodRate[cur] * gslow[std::min(k, 511)];

        for (int d = 0; d < 4; d++) {
            int nx = stepTo(cur, d);
            if (nx < 0 || dist[nx] >= 0) continue;
            if (evalNoBlindPortal && edgeT[cur * 4 + d] == 2 && lastSeen[nx] != R) continue;
            if (occStamp[nx] == R && (!cfg.othersFree || k + 2 < otherFree[nx])) continue;
            if (fountainCluster[nx] >= 0 && fountainCluster[nx] < static_cast<int>(clusterTaken.size()) &&
                clusterTaken[fountainCluster[nx]])
                continue;
            if (ownStamp[nx] == R) {
                int idx = ownIndex[nx] + shift;
                if (idx < bodyLen && k + 1 < bodyLen - idx + 1) continue;
            }
            if (qt >= fillCap) continue;
            dist[nx] = k + 1;
            queueBuf[qt++] = nx;
        }
    }
    return {score, reach, pearls, certain};
}

// v051 QTRAP: tiles reachable from start, up to cap, with every tile of `walls` (her body) blocked for good.
std::vector<int> trapMark, trapQ;
int trapStamp = 0;
int roomStatic(int start, int cap, std::vector<int> const& walls) {
    if (trapMark.size() != static_cast<std::size_t>(N)) { trapMark.assign(N, 0); trapQ.assign(N, 0); }
    int const wall = ++trapStamp * 2, seen = wall + 1;
    for (int b : walls) trapMark[b] = wall;
    if (trapMark[start] == wall) return 0;
    int qh = 0, qt = 0;
    trapMark[start] = seen;
    trapQ[qt++] = start;
    while (qh < qt && qt < cap)
        for (int d = 0, cur = trapQ[qh++]; d < 4; d++) {
            int const nx = stepTo(cur, d);
            if (nx < 0 || trapMark[nx] == seen || trapMark[nx] == wall) continue;
            trapMark[nx] = seen;
            trapQ[qt++] = nx;
        }
    return std::min(qt, cap);
}

// Tiles reachable from start (counted) up to `need`, with `blocked` tiles and other bodies walls; our own body
// frees up tail first as in evaluate().
std::vector<int> pessMark, pessQ;
int pessStampNow = 0;
int roomPess(int start, int need, int bodyLen, std::vector<int> const& blocked) {
    if (pessMark.size() != static_cast<std::size_t>(N)) { pessMark.assign(N, 0); pessQ.assign(N * 2, 0); }
    int const mark = ++pessStampNow * 2, seen = mark + 1;
    for (int b : blocked) pessMark[b] = mark;
    int qh = 0, qt = 0, count = 0;
    pessMark[start] = seen;
    pessQ[qt++] = start;
    pessQ[qt++] = 0;
    while (qh < qt) {
        int const cur = pessQ[qh++], k = pessQ[qh++];
        if (++count >= need) return count;
        for (int d = 0; d < 4; d++) {
            int nx = stepTo(cur, d);
            if (nx < 0 || pessMark[nx] == seen || pessMark[nx] == mark) continue;
            if (occStamp[nx] == R && (!cfg.othersFree || k + 2 < otherFree[nx])) continue;
            if (ownStamp[nx] == R) {
                int idx = ownIndex[nx] + 1;
                if (idx < bodyLen && k + 1 < bodyLen - idx + 1) continue;
            }
            pessMark[nx] = seen;
            pessQ[qt++] = nx;
            pessQ[qt++] = k + 1;
        }
    }
    return count;
}

// v036: path distances for the queen's look-ahead. From src, up to cap steps, over stepTo edges. A tile with another
// dragon's segment (occStamp) or stamped in qsWall (our queen's body as it will stand) is reached but not walked
// through. Results in qsDist, valid where qsSeen == qsSeenNow.
std::vector<int> qsDist, qsSeen, qsWall, qsQueue;
int qsSeenNow = 0, qsWallNow = 0;
void qsBfs(int src, int cap) {
    if (static_cast<int>(qsDist.size()) != N) { qsDist.assign(N, 0); qsSeen.assign(N, 0); qsWall.assign(N, 0); qsQueue.assign(N, 0); }
    ++qsSeenNow;
    int qh = 0, qt = 0;
    qsSeen[src] = qsSeenNow;
    qsDist[src] = 0;
    qsQueue[qt++] = src;
    while (qh < qt) {
        int const cur = qsQueue[qh++];
        if (qsDist[cur] >= cap) continue;
        for (int d = 0; d < 4; d++) {
            int const nx = stepTo(cur, d);
            if (nx < 0 || qsSeen[nx] == qsSeenNow) continue;
            qsSeen[nx] = qsSeenNow;
            qsDist[nx] = qsDist[cur] + 1;
            if (occStamp[nx] == R || qsWall[nx] == qsWallNow) continue;
            qsQueue[qt++] = nx;
        }
    }
}
inline int qsReached(int t) { return qsSeen[t] == qsSeenNow ? qsDist[t] : (1 << 20); }

// The tiles a head at src can stand on after up to `steps` moves over free tiles (src included: it may split instead).
std::vector<int> qsPlaces(int src, int steps, int banned) {
    std::vector<int> out{src};
    std::vector<int> frontier{src};
    for (int k = 0; k < steps; k++) {
        std::vector<int> nxt;
        for (int c : frontier)
            for (int d = 0; d < 4; d++) {
                int const t = stepTo(c, d);
                if (t < 0 || t == banned || occStamp[t] == R || qsWall[t] == qsWallNow) continue;
                if (std::find(out.begin(), out.end(), t) != out.end()) continue;
                out.push_back(t);
                nxt.push_back(t);
            }
        frontier.swap(nxt);
    }
    return out;
}

// v056: per tile, the rounds until some visible enemy head can strike it (Ben, Oct 11: speed-aware BFS). An enemy n long
// covers ceil(n/4) tiles a round for free and its whole reach (free + paid steps) in the round it strikes
// (docs/movement.md), so a tile at path distance d is struck in round 1 when d <= reach, else in round
// 1 + ceil((d - reach) / free). Paths follow portals; other dragons' segments and the tiles in `walls` (her body) are
// reached but not walked through. dgT = QS_FAR where no visible enemy gets within QS_HORIZON rounds.
std::vector<int> dgDist, dgQ, dgSeen, dgWall, dgList;
int dgSeenNow = 0, dgWallNow = 0;
void dangerMap(std::vector<Head> const& hs, std::vector<int> const& walls) {
    if (static_cast<int>(dgT.size()) != N) { dgT.assign(N, QS_FAR); dgDist.assign(N, 0); dgQ.assign(N, 0); dgSeen.assign(N, 0); dgWall.assign(N, 0); }
    for (int t : dgList) dgT[t] = QS_FAR;
    dgList.clear();
    ++dgWallNow;
    for (int t : walls) dgWall[t] = dgWallNow;
    for (Head const& h : hs) {
        if (!h.enemy) continue;
        int const fr = std::max(1, (h.len + 3) / 4), reach = std::max(1, h.reach);
        int const cap = reach + fr * (QS_HORIZON - 1);
        ++dgSeenNow;
        int qh = 0, qt = 0;
        dgSeen[h.pos] = dgSeenNow;
        dgDist[h.pos] = 0;
        dgQ[qt++] = h.pos;
        while (qh < qt) {
            int const cur = dgQ[qh++];
            int const k = dgDist[cur];
            if (k >= cap) continue;
            for (int d = 0; d < 4; d++) {
                int const nx = stepTo(cur, d);
                if (nx < 0 || dgSeen[nx] == dgSeenNow) continue;
                dgSeen[nx] = dgSeenNow;
                dgDist[nx] = k + 1;
                int const T = k + 1 <= reach ? 1 : 1 + (k + 1 - reach + fr - 1) / fr;
                if (T < dgT[nx]) {
                    if (dgT[nx] == QS_FAR) dgList.push_back(nx);
                    dgT[nx] = T;
                }
                if (occStamp[nx] == R || dgWall[nx] == dgWallNow) continue;
                dgQ[qt++] = nx;
            }
        }
    }
}
// v056: her safe territory from `start` (the Voronoi side of the danger map): tiles she reaches, `speed` tiles a round,
// strictly before any visible enemy can strike them, walked only through such tiles, `walls` (her body) and other
// dragons' segments blocked; counted up to cap.
std::vector<int> stMark, stDist, stQ;
int stStamp = 0;
int safeRoom(int start, int cap, int speed, std::vector<int> const& walls) {
    if (static_cast<int>(stMark.size()) != N) { stMark.assign(N, 0); stDist.assign(N, 0); stQ.assign(N, 0); }
    int const wall = ++stStamp * 2, seen = wall + 1;
    for (int t : walls) stMark[t] = wall;
    int qh = 0, qt = 0;
    stMark[start] = seen;
    stDist[start] = 0;
    stQ[qt++] = start;
    while (qh < qt && qt < cap) {
        int const cur = stQ[qh++];
        for (int d = 0; d < 4; d++) {
            int const nx = stepTo(cur, d);
            if (nx < 0 || stMark[nx] == seen || stMark[nx] == wall || occStamp[nx] == R) continue;
            int const k = stDist[cur] + 1;
            if ((k + speed - 1) / speed >= dgT[nx]) continue; // an enemy gets there first (or with her)
            stMark[nx] = seen;
            stDist[nx] = k;
            stQ[qt++] = nx;
        }
    }
    return std::min(qt, cap);
}

// ---------------------------------------------------------------- ramming
struct Ram {
    std::vector<int> dirs;
    int gain = -1000000;
};

void searchRam(int cur, std::vector<int>& simBody, std::vector<char>& eaten, std::vector<int>& path,
               int maxSteps, int target, Ram& best, int gain) {
    for (int d = 0; d < 4; d++) {
        int nx = stepTo(cur, d);
        if (nx < 0) continue;
        if (QUEEN_PB && qpbWarned(cur, d)) continue; // v64: never through a portal our queen is behind
        if (std::find(simBody.begin(), simBody.end(), nx) != simBody.end()) continue;
        path.push_back(d);
        if (nx == target) {
            if (gain > best.gain || (gain == best.gain && path.size() < best.dirs.size())) {
                best.gain = gain;
                best.dirs = path;
            }
        } else if (static_cast<int>(path.size()) < maxSteps && occStamp[nx] != R) {
            std::vector<int> saved = simBody;
            bool ate = lastSeen[nx] == R && pearl[nx] && !eaten[nx];
            simBody.insert(simBody.begin(), nx);
            if (!ate && !simBody.empty()) simBody.pop_back();
            if (static_cast<int>(path.size()) > sprintFree && !simBody.empty()) simBody.pop_back();
            if (ate) eaten[nx] = 1;
            searchRam(nx, simBody, eaten, path, maxSteps, target, best, gain);
            if (ate) eaten[nx] = 0;
            simBody = saved;
        }
        path.pop_back();
    }
}

// ---------------------------------------------------------------- turn
void takeTurn(Controller& ct, Game& game) {
    turnT0 = std::chrono::steady_clock::now();
    evalNoBlindPortal = false;
    R = game.get_round_num();
    int const L = ct.get_length();
    int const head = at(ct.get_position().x, ct.get_position().y);
    int const units = ct.get_unit_count();
    Team const me = ct.get_team();
    if (firstRound < 0) {
        firstRound = R;
        // No child can exist before SPLIT_FROM, whichever number the first round has.
        bool const starter = R < SPLIT_FROM;
        isKing = KING_FIX ? starter : (R == 1);
        isFirst = starter && ct.get_id() <= 1;
        bigBorn = BIG_BORN > 0 && L >= BIG_BORN;
        bornLen = L;
        homeTile = head;
    }
    nextHead = -1;
    nextFacing = -1;
    if (cfg.probe && probeRound == R - 1 && probeDir >= 0) {
        SonarEchoes const e = ct.get_sonar_echoes();
        verdictClear = e.ally + e.ally_head + e.enemy + e.enemy_head == 0;
        verdictDir = probeDir;
        verdictFrom = probeFrom;
        verdictRound = R;
    }
    identifyMap(ct); // every turn until only one known map fits what we have seen
    bool const amQueen = QUEEN_RULES && ct.get_id() <= 1;   // v46: dragons 0 and 1 are the queens, whichever team is listed first
    auto canSplit = [&](int n) { return ct.can_split(n) && (!QUEEN_SLOT || amQueen || units < ct.unit_limit - 1); };
    if (stallLastL < 0 || L > stallLastL) stallLastEat = R;
    stallLastL = L;
    stallHist.push_back(head);
    if (static_cast<int>(stallHist.size()) > STALL_ROUNDS) stallHist.erase(stallHist.begin());
    bool stalled = false;
    if (STALL_BREAK && (STALL_ALL_MAPS || unseenRules) && !amQueen && R - stallLastEat >= STALL_ROUNDS && static_cast<int>(stallHist.size()) >= STALL_ROUNDS) {
        std::vector<int> u = stallHist;
        std::sort(u.begin(), u.end());
        stalled = std::unique(u.begin(), u.end()) - u.begin() <= STALL_TILES;
    }
    sprintFree = (L + 3) / 4;
    if (amQueen) {
        // Locally the queen died in 10 of 10 games, 9 by her own move: boxed in by allies and the bodies she expected
        // to move away, then a SAVE split left her as the 2-segment stub. Every dragon is its own process, so these
        // settings only change the queen: other bodies never free up in her flood fills, the pessimistic room check,
        // and the full charge for ending beside any ally head.
        cfg.othersFree = false;
        cfg.pessRoom = true;
        cfg.allyAdj = std::max(cfg.allyAdj, 2.0);
        cfg.allyAdjAll = true;
    }
    if (DEBUG_IND && R == firstRound)
        ct.set_indicator_string(std::string("MAP ") + (mapIdx >= 0 ? maps::all[mapIdx].name : "unknown"));
    bool const growing = (GROWER_FROM > 0 && isFirst && R >= GROWER_FROM) || bigBorn;

    // Endgame election: adopt the best king heard of, or claim the crown.
    bool const electing = CONSOLIDATE && (R >= consStart - KING_PREELECT || (KING_ELECT_ROUND > 0 && R >= KING_ELECT_ROUND));
    bool const consolidating = CONSOLIDATE && R >= consStart;
    if (CONSOLIDATE) {
        for (std::uint64_t v : ct.get_sonar_messages()) {
            KingInfo k;
            if (decodeKing(v, k)) considerKing(k);
        }
        if (electing && QUEEN_RULES && amQueen)
            king = {ct.get_id(), head, L, R};
        else if (electing && !(QUEEN_RULES && king.id >= 0 && king.id <= 1 && !kingStale()) &&
                 (!(NO_FAKE_KING && QUEEN_RULES) || (heardQueenRound >= 0 && R - heardQueenRound > QUEEN_DEAD_ROUNDS)) &&
                 (king.id == ct.get_id() || kingStale() || L >= king.len + KING_MARGIN))
            king = {ct.get_id(), head, L, R};
    }
    preyToSend = false;
    for (std::uint64_t v : ct.get_sonar_messages()) {
        KingInfo k;
        if (decodePrey(v, k)) considerPrey(k, true);
        Sighting sg;
        if (INTEL && decodeIntel(v, sg)) noteSighting(sg.id, sg.pos, sg.len, sg.round);
        if (FOOD_INTEL && N <= 4096) takeFood(v);
        int pid, rnd;
        if (cfg.pbEnable && decodePB(v, pid, rnd) && rnd <= R && (pbRx.find(pid) == pbRx.end() || pbRx[pid] < rnd)) pbRx[pid] = rnd;
        if (QUEEN_PB && decodeQPB(v, pid, rnd) && rnd <= R && (qpbRx.find(pid) == qpbRx.end() || qpbRx[pid] < rnd)) qpbRx[pid] = rnd;
    }

    // Memory from vision.
    std::vector<int> visible;
    visible.reserve(49);
    for (Tile const& tile : ct.get_tiles()) {
        int i = at(tile.position.x, tile.position.y);
        visible.push_back(i);
        if (lastSeen[i] < 0) { firstSeen += 1; firstPearl += tile.has_pearl() ? 1 : 0; }
        lastSeen[i] = R;
        pearl[i] = tile.has_pearl();
        int pt = tile.get_pearl_time();
        spawnState[i] = 1;
        never[i] = pt < 0;
        spawnAt[i] = pt < 0 ? -1 : R + pt;
        spawnObs[i] = R;
        for (int d = 0; d < 4; d++) {
            Edge const& e = tile.edges[d];
            int type = e.edge_type == EdgeType::KELP ? 1 : (e.edge_type == EdgeType::PORTAL ? 2 : 0);
            setEdge(i, d, type, e.get_portal_id());
        }
    }

    if (FOOD_INTEL && N <= 4096) {
        foodOut.clear();
        std::vector<Food> soon;
        for (int i : visible) {
            if (pearl[i] && manhattan(i, head) >= FOOD_NEAR) foodOut.push_back({i, R, true});
            else if (!pearl[i] && spawnAt[i] > R && spawnAt[i] - R <= FOOD_SPAWN_WITHIN) soon.push_back({i, spawnAt[i], false});
        }
        std::sort(soon.begin(), soon.end(), [](Food const& a, Food const& b) { return a.round < b.round; });
        foodOut.insert(foodOut.end(), soon.begin(), soon.end());
    }

    // Dragons in view.
    std::vector<Head> heads;
    std::vector<std::pair<int, int>> mine;
    std::unordered_map<int, int> lens;
    struct Seg {
        int tile, id, dir;
        bool enemy;
    };
    std::vector<Seg> others;
    for (Tile const& tile : ct.get_tiles()) {
        DragonPart const* part = tile.get_dragon();
        if (!part) continue;
        int i = at(tile.position.x, tile.position.y);
        if (part->dragon_id == ct.get_id()) {
            if (!part->is_head()) mine.push_back({i, dirIndex(part->dir)});
            continue;
        }
        occStamp[i] = R;
        otherFree[i] = NEVER_FREE;
        if (cfg.ptEnable)
            for (int d = 0; d < 4; d++)
                if (edgeT[i * 4 + d] == 2 && portalId[i * 4 + d] >= 0)
                    (part->team == me ? ptAlly : ptEnemy)[portalId[i * 4 + d]] = R;
        lens[part->dragon_id]++;
        others.push_back({i, part->dragon_id, dirIndex(part->dir), !(part->team == me)});
        if (part->is_head()) heads.push_back({i, part->dragon_id, 0, !(part->team == me)});
    }
    for (Head& h : heads) h.len = lens[h.id];
    // S2c: one threat reach per enemy head, used by every queen-safety term: ceil(n/4) free steps + (n - 2) paid ones,
    // n = visible length + the visible pearls it can eat on the way (each adds a payable segment, at most 2), and one
    // more only when its body may continue out of view (a segment on the edge of our 7x7 view or beside a portal).
    if (QUEEN_REACH_EXACT)
        for (Head& h : heads) {
            if (!h.enemy) continue;
            auto reachLen = [](int n) { return std::max(1, (n + 3) / 4 + n - 2); };
            bool partial = false;
            for (auto const& sg : others) {
                if (sg.id != h.id) continue;
                if (std::max(wrapDist(X(sg.tile), X(head), W), wrapDist(Y(sg.tile), Y(head), H)) >= 3) partial = true;
                for (int d = 0; d < 4; d++)
                    if (edgeT[sg.tile * 4 + d] == 2) partial = true;
            }
            int const base = reachLen(h.len);
            int food = 0;
            for (int t : visible)
                if (pearl[t] && manhattan(h.pos, t) <= base) food++;
            h.reach = reachLen(h.len + std::min(2, food)) + (partial ? 1 : 0);
        }
    else
        for (Head& h : heads) h.reach = std::max(1, h.len - 2 + (h.len + 3) / 4);
    if (INTEL) {
        pruneIntel();
        for (Head const& h : heads)
            if (h.enemy) noteSighting(h.id, h.pos, h.len, R);
    }
    for (Head const& h : heads)
        if (h.enemy && h.len >= PREY_MIN) considerPrey({h.id, h.pos, h.len, R}, false), preyToSend = preyToSend || prey.round == R;
    // A sighting whose tile we can see, with its dragon no longer there, is over.
    if (preyFresh() && prey.round < R && lastSeen[prey.pos] == R) prey.id = -1;

    // A segment with k segments trailing it is gone after k+1 of its dragon's moves.
    // Walk forward from every tail we can prove is a tail (not on the vision rim).
    {
        auto segAt = [&](int tile, int id) -> int {
            for (std::size_t k = 0; k < others.size(); k++)
                if (others[k].tile == tile && others[k].id == id) return static_cast<int>(k);
            return -1;
        };
        auto onRim = [&](int tile) {
            return std::max(wrapDist(X(tile), X(head), W), wrapDist(Y(tile), Y(head), H)) >= 3;
        };
        std::vector<char> hasBehind(others.size(), 0);
        for (auto const& s : others) {
            int f = segAt(nb(s.tile, s.dir), s.id);
            if (f >= 0 && f != static_cast<int>(&s - &others[0])) hasBehind[f] = 1;
        }
        for (std::size_t k = 0; k < others.size(); k++) {
            if (hasBehind[k] || onRim(others[k].tile)) continue;
            int cur = static_cast<int>(k), behind = 0;
            while (cur >= 0 && behind <= static_cast<int>(others.size())) {
                otherFree[others[cur].tile] = behind + 3; // +1 margin in case it eats
                int next = segAt(nb(others[cur].tile, others[cur].dir), others[cur].id);
                if (next == cur) break;
                cur = next;
                behind++;
            }
        }
    }

    // Our own body.
    bool predOk = !predicted.empty() && predicted[0] == head && static_cast<int>(predicted.size()) <= L;
    rebuildBody(head, dirIndex(ct.get_dir()), L, mine);
    if (predOk && predicted.size() >= body.size()) {
        // The remembered body must agree with what we see: every own segment in view on it, and none of it in view
        // where we see no segment of ours. On Schooltime a 37-long king whose memory had drifted stepped onto its own
        // body, the only move the stale model allowed.
        bool agrees = true;
        if (cfg.bodyVisFix) {
            auto inView = [&](int t) { return std::max(wrapDist(X(t), X(head), W), wrapDist(Y(t), Y(head), H)) <= 3; };
            for (auto const& m : mine)
                if (std::find(predicted.begin(), predicted.end(), m.first) == predicted.end()) agrees = false;
            for (std::size_t k = 1; k < predicted.size() && agrees; k++) {
                if (!inView(predicted[k])) continue;
                bool seen = false;
                for (auto const& m : mine)
                    if (m.first == predicted[k]) seen = true;
                if (!seen) agrees = false;
            }
        }
        if (agrees) body = predicted;
    }
    if (static_cast<int>(body.size()) > L) body.resize(L);
    for (std::size_t k = 0; k < body.size(); k++) {
        ownStamp[body[k]] = R;
        ownIndex[body[k]] = static_cast<int>(k);
    }
    // Any own segment in view is a wall whatever the model says (treated as freeing last).
    if (cfg.bodyVisFix)
        for (auto const& m : mine)
            if (ownStamp[m.first] != R) {
                ownStamp[m.first] = R;
                ownIndex[m.first] = 0;
            }

    // Two regions can each elect a king (sonar stops at kelp), and the food splits between them.
    // A king, or a would-be feeder, that can see an ally clearly longer than itself (its visible
    // segments alone, a lower bound) backs that ally instead.
    if (KING_VISIBLE_MERGE && electing) {
        for (Head const& h : heads) {
            if (h.enemy) continue;
            int const vis = lens[h.id];
            if (vis >= L + KING_MARGIN && (king.id == ct.get_id() || kingStale() || vis > king.len))
                king = {h.id, h.pos, vis, R};
        }
    }
    bool const amKing = electing && king.id == ct.get_id();
    bool const isLong = cfg.longFrom > 0 && R >= cfg.longFrom && L >= LONG_LEN;
    if (FAR_FEED && QUEEN_RULES && !farFeeding && R >= FAR_FROM && !amQueen && !amKing && king.id >= 0 && king.id <= 1 &&
        !kingStale() && units > cfg.feedReserve + 1 && king.pos >= 0) {
        bfsFrom(king.pos, distKing);
        int const d = distKing[head];
        if (d >= 0 && d >= LAST_ROUND - R - FAR_SLACK) farFeeding = true;
    }
    if (farFeeding && (amKing || amQueen || kingStale())) farFeeding = false;
    bool const feeding = (consolidating && !amKing && !kingStale() && R >= consStart + CONS_WARMUP && units > cfg.feedReserve + 1 &&
                          !(isLong && king.len < L + 3)) || farFeeding;
    bool const protectMe = growing || amKing || amQueen || (cfg.longProtect && isLong) || (PROTECT_FROM_END > 0 && R > LAST_ROUND - PROTECT_FROM_END && L >= PROTECT_LEN);

    // Symmetry.
    for (int t : visible) checkSymmetry(t);
    for (int s = 0; s < 3; s++) {
        if (!symUsable(s)) continue;
        if (!symApplied[s]) {
            symApplied[s] = true;
            for (int t = 0; t < N; t++)
                if (lastSeen[t] >= 0) inferFrom(s, t);
        } else {
            for (int t : visible) inferFrom(s, t);
        }
    }

    // Who else is close to each tile.
    if (CLAIM) {
        std::fill(claimD.begin(), claimD.end(), 1 << 20);
        for (Head const& h : heads) {
            for (int dy = -CLAIM_R; dy <= CLAIM_R; dy++)
                for (int dx = -CLAIM_R; dx <= CLAIM_R; dx++) {
                    int md = std::abs(dx) + std::abs(dy);
                    if (md > CLAIM_R) continue;
                    int t = at(X(h.pos) + dx, Y(h.pos) + dy);
                    claimD[t] = std::min(claimD[t], md);
                }
        }
    }

    // Contention for visible pearls. (Speed: one buffer for the game; only last turn's visible tiles need resetting.)
    static std::vector<double> contention;
    static std::vector<int> contentionSet;
    if (contention.size() != static_cast<std::size_t>(N)) contention.assign(N, 1.0);
    for (int t : contentionSet) contention[t] = 1.0;
    contentionSet = visible;
    for (int t : visible) {
        if (!pearl[t]) continue;
        int myd = manhattan(head, t);
        for (Head const& h : heads) {
            int hd = manhattan(h.pos, t);
            if (hd < myd) contention[t] = std::min(contention[t], 0.35);
            else if (hd == myd && (h.enemy || h.id < ct.get_id())) contention[t] = std::min(contention[t], 0.7);
        }
    }

    // Fountain to work: the nearest cluster in range that no ally in view is already working.
    // Inside one, a dragon's 2+2 splits turn it into a factory: one child faces the dead end and
    // eats, the other walks out with the tail.
    int fTarget = -1;
    clusterTaken.assign(fountainDist.size(), 0);
    if (mapIdx >= 0 && !(NEW_MAP_FOOD_BLIND && unseenRules)) {
        for (int c = 0; c < static_cast<int>(fountainDist.size()); c++) {
            if (fountainCluster[head] == c || !clusterIsFountain[c]) continue;
            for (auto const& sg : others)
                if (!sg.enemy && fountainCluster[sg.tile] == c) {
                    clusterTaken[c] = cfg.keepout;
                    break;
                }
        }
    }
    bool const fpuller = cfg.fpullShare >= 1.0 || ((static_cast<std::uint32_t>(ct.get_id()) * 2654435761u) >> 8) % 1000 < cfg.fpullShare * 1000;
    if (cfg.fpull > 0 && mapIdx >= 0 && !protectMe && !consolidating && fpuller) {
        int bestD = cfg.fpullMax + 1;
        double bestV = 1e18;
        for (int c = 0; c < static_cast<int>(fountainDist.size()); c++) {
            int const dd = fountainDist[c][head];
            if (dd < 0 || dd > cfg.fpullMax || clusterTaken[c]) continue;
            // Nearest cluster first (v9), or with fpullProdW > 0 the one with the best production for its distance: on Devil
            // the top teams hold the central 2x2 fountains (they ate 62 there in 150 rounds of one game, we ate 1).
            double const v = dd - cfg.fpullProdW * clusterProd[c];
            if (v >= bestV) continue;
            bool taken = false;
            if (fountainCluster[head] != c) {
                if (clusterIsFountain[c]) {
                    for (auto const& sg : others)
                        if (!sg.enemy && fountainCluster[sg.tile] == c) {
                            taken = true;
                            break;
                        }
                } else {
                    // An open patch feeds a few dragons: full once enough allies are on or next to it.
                    int there = 0;
                    for (Head const& h : heads)
                        if (!h.enemy && fountainDist[c][h.pos] >= 0 && fountainDist[c][h.pos] <= 2) there++;
                    taken = there >= clusterCap[c];
                }
            }
            if (taken) continue;
            bestD = dd;
            bestV = v;
            fTarget = c;
        }
    }

    // 0. Feed the king: walk to it, and die beside it once close.
    // Dispersal target, chosen once on a child's first turn. The top teams' children were 10-20
    // tiles from where they were born after 20-40 turns and ate 5.6 pearls per 100 turns; ours
    // stayed 2-8 tiles away and ate 3.8.
    if (cfg.dispW > 0 && mapIdx >= 0 && R == firstRound && firstRound >= SPLIT_FROM && dispTarget < 0) {
        bfsFrom(head, dispDist);
        double best = -1e18;
        std::uint32_t const idHash = static_cast<std::uint32_t>(ct.get_id()) * 2654435761u;
        for (int t = 0; t < N; t++) {
            int const dd = dispDist[t];
            if (dd < DISP_MIN || dd > DISP_MAX || prodDensity[t] <= 0) continue;
            std::uint32_t h = idHash ^ (static_cast<std::uint32_t>(t) * 40503u);
            h ^= h >> 13; h *= 0x5bd1e995u; h ^= h >> 15;
            double const noise = (h % 1000) / 1000.0;
            double const sc = prodDensity[t] + DISP_NOISE * noise - DISP_DIST_COST * dd;
            if (sc > best) { best = sc; dispTarget = t; }
        }
        if (dispTarget >= 0) {
            bfsFrom(dispTarget, dispDist);
            dispUntil = R + DISP_TURNS;
        }
    }
    bool const dispersing = dispTarget >= 0 && R < dispUntil && !protectMe && dispDist[head] > 3;
    if (dispTarget >= 0 && R < dispUntil && dispDist[head] <= 3) dispUntil = R; // arrived

    // Pocket to farm: inside one, keep going to its end; otherwise the nearest free, stocked pocket
    // in range. Busy = any dragon on its tiles or entrance. The end is a dead end: BOXED_SAVE
    // splits the tail side out there, so we must arrive at 4+ segments and have room for a unit.
    if (cfg.pocket && mapIdx >= 0 && !pocketOf.empty()) {
        int const inside = pocketOf[head];
        if (inside >= 0) pocketTarget = inside;
        else {
            // Only a share of the army farms pockets (by id hash, like the fountain pull): online on Autarky v12 sent every
            // small dragon in, ate as many fountain pearls as the top teams (175 vs 189) but half the rest (93 vs 181).
            bool const pocketer = cfg.pocketShare >= 1.0 || ((static_cast<std::uint32_t>(ct.get_id()) * 2246822519u) >> 8) % 1000 < cfg.pocketShare * 1000;
            bool const eligible = pocketer && !protectMe && !consolidating && !amKing && L <= POCKET_MAXLEN && units < ct.unit_limit - POCKET_UNIT_MARGIN;
            int best = -1, bestD = cfg.pocketRange + 1;
            for (int p = 0; eligible && p < static_cast<int>(pockets.size()); p++) {
                Pocket const& pk = pockets[p];
                int const dd = pk.dist[head];
                if (dd < 0 || dd >= bestD) continue;
                bool busy = occStamp[pk.entrance] == R;
                double stock = 0;
                for (int c : pk.tiles) {
                    if (occStamp[c] == R) busy = true;
                    if (gapHi[c] <= 0) continue;
                    if (lastSeen[c] == R) stock += pearl[c] || (spawnAt[c] >= 0 && spawnAt[c] <= R + dd) ? 1.0 : 0.0;
                    else stock += gapHi[c] <= 10 ? 0.9 : 0.0;
                }
                if (busy || L + stock < 4.0) continue;
                best = p;
                bestD = dd;
            }
            pocketTarget = best;
        }
    } else {
        pocketTarget = -1;
    }
    bool feedNav = false;
    int feedKingHead = -1;
    noEatCenter = -1;
    noEatR = cfg.noeatR;
    if (feeding && king.len >= FEED_MIN_KING && king.len >= L + cfg.feedKingMargin) {
        int kingHead = -1;
        for (Head const& h : heads)
            if (!h.enemy && h.id == king.id) kingHead = h.pos;
        if (cfg.noeatR >= 0) noEatCenter = kingHead >= 0 ? kingHead : king.pos;
        bfsFrom(kingHead >= 0 ? kingHead : king.pos, distKing);
        int const myDist = distKing[head];
        // The king eats at most one pearl a turn. Online, ten feeders died on the same turn and
        // the other team ate as many endgame pearls as we did, so wait while food is still lying there.
        int pending = 0;
        if (kingHead >= 0)
            for (int t : visible)
                if (pearl[t] && manhattan(t, kingHead) <= 3) pending++;
        bool enemyInView = false;
        for (Head const& h : heads)
            if (h.enemy) enemyInView = true;
        bool nearBig = false;
        if (cfg.feedAny)
            for (Head const& h : heads)
                if (!h.enemy && h.len >= std::max(FEED_ANY_MIN, L + 2) && manhattan(h.pos, head) <= cfg.feedRadius) nearBig = true;
        if (((kingHead >= 0 && myDist >= 0 && myDist <= cfg.feedRadius) || nearBig) && units >= 2 && pending <= FEED_PENDING_MAX &&
            !(cfg.feedNoEnemy && enemyInView)) {
            // Stepping back into our own neck kills us where we stand: pearls on every second segment.
            ct.make_move(Direction(DC[opp(dirIndex(ct.get_dir()))]));
            ct.set_indicator_string("FEED");
            predicted.clear();
            return;
        }
        feedNav = myDist >= 0 && myDist <= (LAST_ROUND - R) - 2 && myDist <= cfg.feedRange;
        feedKingHead = kingHead;
    }
    // Online (v17, 22 games) the king ate 10-25% of the pearls our dying dragons dropped after round 380 and the rest
    // of the army 50-80%: only active feeders kept off the king's food. Now every non-king dragon does.
    if (NOEAT_ALL && consolidating && !amKing && !kingStale() && noEatCenter < 0 && cfg.noeatR >= 0) {
        int kingHead = -1;
        for (Head const& h : heads)
            if (!h.enemy && h.id == king.id) kingHead = h.pos;
        noEatCenter = kingHead >= 0 ? kingHead : king.pos;
    }
    if (TRICKLE && QUEEN_RULES && !feeding && !consolidating && !amQueen && !amKing && R >= TRICKLE_FROM && units >= TRICKLE_MIN_UNITS) {
        int qHead = -1;
        for (Head const& h : heads)
            if (!h.enemy && h.id <= 1) qHead = h.pos;
        if (qHead >= 0) {
            bool enemyNear = false;
            for (Head const& h : heads)
                if (h.enemy && manhattan(h.pos, qHead) <= TRICKLE_ENEMY_R) enemyNear = true;
            if (manhattan(head, qHead) <= TRICKLE_NOEAT_R) {
                noEatCenter = qHead;
                noEatR = TRICKLE_NOEAT_R;
            }
            if (L >= TRICKLE_MINLEN && !enemyNear && manhattan(head, qHead) <= cfg.feedRadius) {
                int pending = 0;
                for (int t : visible)
                    if (pearl[t] && manhattan(t, qHead) <= 3) pending++;
                if (pending <= TRICKLE_PENDING) {
                    bfsFrom(qHead, distKing);
                    int const myDist = distKing[head];
                    if (myDist >= 0 && myDist <= cfg.feedRadius) {
                        ct.make_move(Direction(DC[opp(dirIndex(ct.get_dir()))]));
                        ct.set_indicator_string("TFEED");
                        predicted.clear();
                        return;
                    }
                }
            }
        }
        if (GIANT && L >= TRICKLE_MINLEN && L < GIANT_MIN) { // v075: feed the longest visible non-queen ally
            int gHead = -1, gLen = 0;
            for (Head const& h : heads)
                if (!h.enemy && h.id > 1 && h.len >= std::max(GIANT_MIN, L + GIANT_MARGIN) && h.len > gLen) { gHead = h.pos; gLen = h.len; }
            if (gHead >= 0) {
                if (noEatCenter < 0 && manhattan(head, gHead) <= TRICKLE_NOEAT_R) { noEatCenter = gHead; noEatR = TRICKLE_NOEAT_R; }
                bool enemyNearG = false;
                for (Head const& h : heads)
                    if (h.enemy && manhattan(h.pos, gHead) <= TRICKLE_ENEMY_R) enemyNearG = true;
                int pendingG = 0;
                for (int t : visible)
                    if (pearl[t] && manhattan(t, gHead) <= 3) pendingG++;
                if (!enemyNearG && pendingG <= TRICKLE_PENDING) {
                    bfsFrom(gHead, distKing);
                    int const gDist = distKing[head];
                    if (gDist >= 0 && gDist <= cfg.feedRadius) {
                        ct.make_move(Direction(DC[opp(dirIndex(ct.get_dir()))]));
                        ct.set_indicator_string("GFEED");
                        predicted.clear();
                        return;
                    }
                }
            }
        }
        if (!feedNav && TRICKLE_SHARE > 0 && ct.get_id() % TRICKLE_SHARE == 0 && L >= TRICKLE_MINLEN && king.id >= 0 && king.id <= 1 &&
            !kingStale() && king.pos >= 0 && manhattan(head, qHead >= 0 ? qHead : king.pos) <= TRICKLE_NAV_R) {
            bfsFrom(qHead >= 0 ? qHead : king.pos, distKing);
            int const myDist = distKing[head];
            if (myDist > cfg.feedRadius && myDist <= TRICKLE_NAV_R) feedNav = true;
        }
    }

    // 1. Ram an enemy head when the trade favours us.
    {
        Ram best;
        int maxSteps = std::min(cfg.ramSteps, L - 1);
        int ourQueen = -1;
        if (QUEEN_GUARD && QUEEN_RULES && !amQueen)
            for (Head const& a : heads)
                if (!a.enemy && a.id <= 1) ourQueen = a.pos;
        for (Head const& h : heads) {
            if (!h.enemy) continue;
            int const steps = (QUEEN_STRIKE_FULL && QUEEN_RULES && h.id <= 1 && !amQueen && units >= 2)
                                  ? std::min(QSTRIKE_MAX, (L + 3) / 4 + L - 2) : maxSteps;
            if (manhattan(head, h.pos) > steps) continue;
            // A ram kills us too, so our last dragon never trades (that is a draw at best).
            bool want = !protectMe && units >= 2 && cfg.ramMargin < 100 && h.len >= L + cfg.ramMargin;
            if (QUEEN_RULES && h.id <= 1 && !amQueen && units >= 2) want = true; // their queen (an enemy with id 0 or 1): any trade wins
            if (ourQueen >= 0 && units >= 3 && L <= QGUARD_MAXLEN && manhattan(h.pos, ourQueen) <= QGUARD_DIST) want = true; // S2g
            if (!want) continue;
            std::vector<int> sim = body;
            std::vector<char> eaten(N, 0);
            std::vector<int> path;
            searchRam(head, sim, eaten, path, steps, h.pos, best, h.len - L);
        }
        if (!best.dirs.empty()) {
            std::vector<Direction> dirs;
            for (int d : best.dirs) dirs.push_back(Direction(DC[d]));
            if (dirs.size() == 1) ct.make_move(dirs[0]);
            else ct.make_moves(dirs);
            ct.set_indicator_string("RAM");
            predicted.clear();
            return;
        }
    }

    // v016e: no growth split inside a real pocket: our head in a 1-wide corridor (<= 2 open sides) that, walked forward
    // from our neck, ends in a dead end within 6 (v016c's room test also fired in crowds and cut the army).
    bool inPocket = false;
    if (POCKET_NO_EARLY_SPLIT && FARM_UNSEEN && unseenRules && !amQueen && L >= 2 && static_cast<int>(body.size()) >= 2 && openDegree(head) <= 2) {
        int prev = body[1], cur = head;
        for (int k = 0; k < 6; k++) {
            int const deg = openDegree(cur);
            if (deg == 1) { inPocket = true; break; }
            if (deg != 2) break;
            int nxt = -1;
            for (int dd = 0; dd < 4; dd++) {
                int const nx = stepTo(cur, dd);
                if (nx >= 0 && nx != prev) { nxt = nx; break; }
            }
            if (nxt < 0) break;
            prev = cur;
            cur = nxt;
        }
    }
    if (!inPocket && POCKET_REGION > 0 && FARM_UNSEEN && unseenRules && !amQueen && L >= 2 && static_cast<int>(body.size()) >= 2) {
        static std::vector<int> mark;
        static int stamp = 0;
        if (static_cast<int>(mark.size()) != N) mark.assign(N, 0);
        ++stamp;
        std::vector<int> qq{head};
        mark[head] = stamp;
        mark[body[1]] = stamp;
        for (std::size_t h = 0; h < qq.size() && static_cast<int>(qq.size()) <= POCKET_REGION; h++)
            for (int dd = 0; dd < 4; dd++) {
                int const nx = stepTo(qq[h], dd);
                if (nx >= 0 && mark[nx] != stamp) { mark[nx] = stamp; qq.push_back(nx); }
            }
        if (static_cast<int>(qq.size()) <= POCKET_REGION) inPocket = true;
    }
    // v026c (Ben's 2:2, re-played: Stripes seed 11 dragon 99 r162): the threat split below also cut a dragon 2:2 inside
    // a pocket, and the 2-stub was forced onto the dead end and died at 3. Inside a pocket (unseen maps) it doesn't fire.
    // v65: a threatened longer dragon sheds all but its 2 head segments; the bulk leaves from the tail.
    if (THREAT_SPLIT && !inPocket && !amQueen && !amKing && L >= TSPLIT_MIN_LEN && units < ct.unit_limit &&
        static_cast<int>(body.size()) == L && canSplit(L - 2)) {
        bool threat = false;
        for (Head const& h : heads)
            if (h.enemy && h.len < L && manhattan(h.pos, head) <= std::max(2, h.len - 2 + (h.len + 3) / 4 + 1)) threat = true;
        if (threat) {
            int const tail = body[L - 1];
            bool tailFree = false;
            for (int dd = 0; dd < 4; dd++) {
                int nx = stepTo(tail, dd);
                if (nx >= 0 && occStamp[nx] != R && ownStamp[nx] != R && lastSeen[nx] == R) tailFree = true;
            }
            if (tailFree) {
                ct.do_split(L - 2);
                ct.set_indicator_string("TSPLIT");
                predicted.assign(body.begin(), body.begin() + 2);
                return;
            }
        }
    }

    // 2. Split to grow the army.
    bool const queenSplits = amQueen && R < queenGrowFrom;
    {
        int cap = std::min(ct.unit_limit, std::max(2, (W * H) / cfg.areaPerUnit));
        int child = 0;
        bool const peel = PEEL_FROM_LEN > 0 && firstRound < SPLIT_FROM && bornLen >= PEEL_FROM_LEN && L > PEEL_DOWN_TO;
        if (peel && units < ct.unit_limit && static_cast<int>(body.size()) == L) {
            child = 2;
        } else if (cfg.earlySplit && firstRound < SPLIT_FROM && R < SPLIT_FROM && bornLen >= 4 && L >= 4 && (!protectMe || queenSplits) && units < cap && static_cast<int>(body.size()) == L) {
            child = L / 2;
        } else if (isLong && !consolidating && units < LONG_RESCUE * cap && units < ct.unit_limit && static_cast<int>(body.size()) == L) {
            child = 2;
        } else if (!isLong && !inPocket && (!protectMe || queenSplits) && !consolidating && !(pocketTarget >= 0 && pocketOf[head] == pocketTarget) && R >= SPLIT_FROM && R <= cfg.splitUntil && units < cap && static_cast<int>(body.size()) == L) {
            if (isKing) {
                // Our lowest-id starter (0 for team A, 1 for team B) never splits.
                if (GROWER && ct.get_id() <= 1) child = 0;
                else if (L >= KING_SPLIT_LEN && kingSplits < KING_MAX_SPLITS) child = KING_CHILD;
            } else if (L >= CHILD_SPLIT_LEN) {
                child = L / 2;
            }
        }
        if (amQueen && !queenSplits) child = (units < QUEEN_SEED_UNITS && L >= 5 && R >= SPLIT_FROM) ? 2 : 0;
        if (child > 0 && canSplit(child)) {
            bool safe = true;
            int tail = body[L - 1];
            // S2d: the queen stays put while splitting and the enemies move after her: she splits only outside every
            // enemy's reach + 1 (S2c's shared threat reach); other dragons keep the 2-tile check.
            for (Head const& h : heads) {
                int const keep = (QUEEN_SPLIT_REACH && amQueen) ? h.reach + 1 : 2;
                if (h.enemy && (manhattan(h.pos, head) <= keep || manhattan(h.pos, tail) <= keep)) safe = false;
            }
            int exits = 0, childExit = -1;
            for (int d = 0; d < 4 && safe; d++) {
                int nx = stepTo(tail, d);
                if (nx < 0 || occStamp[nx] == R || ownStamp[nx] == R) continue;
                exits++;
                childExit = nx;
            }
            if ((SPLIT_SAFE || amQueen) && safe && exits > 0) {
                // The parent stays put with only its head and neck, and the child's body now sits
                // where its tail was. In a local game 70 of 184 boxed deaths were parents that had
                // just split with nowhere left to go: require a way out for the parent too, and not
                // the child's only one.
                int parentExits = 0, parentExit = -1;
                for (int d = 0; d < 4; d++) {
                    int nx = stepTo(head, d);
                    if (nx < 0 || occStamp[nx] == R || ownStamp[nx] == R) continue;
                    parentExits++;
                    parentExit = nx;
                }
                if (parentExits == 0 || (parentExits == 1 && exits == 1 && parentExit == childExit)) safe = false;
                if (amQueen && parentExits < 2) safe = false; // the queen keeps two ways out
            }
            if (safe && exits >= cfg.splitMinExits) {
                ct.do_split(child);
                ct.set_indicator_string("SPLIT");
                if (isKing) kingSplits++;
                predicted.assign(body.begin(), body.begin() + (L - child));
                nextHead = head;
                nextFacing = dirIndex(ct.get_dir());
                return;
            }
        }
    }

    // 3. Move.
    // Small dragons walk towards a shared sighting of a much longer enemy; the ram above finishes the job.
    bool hunting = false;
    if (cfg.preyHunt && R >= PREY_FROM && preyFresh() && !protectMe && !amKing && L <= HUNTER_MAXLEN && units >= 2 && prey.len >= L + HUNT_GAP) {
        bfsFrom(prey.pos, preyDist);
        hunting = preyDist[head] >= 0 && preyDist[head] <= PREY_RANGE;
    }
    if (BABY_HUNT && INTEL && !hunting && !protectMe && !amKing && L <= BABY_MAXLEN && units >= 4 &&
        ((static_cast<std::uint32_t>(ct.get_id()) * 2654435761u) >> 8) % 1000 < BABY_SHARE * 1000) {
        // A baby: the nearest reported enemy much longer than us. The ram above makes the kill once its head is in reach.
        int bestPos = -1, bestD = BABY_RANGE + 1;
        for (Sighting const& sg : intel) {
            if (sg.len < std::max(BABY_MIN_TARGET, L + BABY_GAP)) continue;
            int const dd = manhattan(sg.pos, head);
            if (dd < bestD) { bestD = dd; bestPos = sg.pos; }
        }
        if (bestPos >= 0) {
            bfsFrom(bestPos, preyDist);
            hunting = preyDist[head] >= 0 && preyDist[head] <= BABY_RANGE;
            if (hunting) ct.set_indicator_string("BABY");
        }
    }
    if (QHUNT && QUEEN_RULES && !hunting && !protectMe && !amKing && !feeding && L <= QHUNT_MAXLEN && units >= 3) {
        int eqPos = -1;
        for (Head const& h : heads)
            if (h.enemy && h.id <= 1) eqPos = h.pos;
        if (eqPos < 0)
            for (Sighting const& sg : intel)
                if (sg.id <= 1 && sg.id >= 0 && R - sg.round <= QHUNT_TTL) eqPos = sg.pos;
        if (eqPos >= 0 && manhattan(eqPos, head) <= QHUNT_RANGE) {
            bfsFrom(eqPos, preyDist);
            hunting = preyDist[head] >= 0 && preyDist[head] <= QHUNT_RANGE;
            if (hunting) ct.set_indicator_string("QHUNT");
        }
    }
    if (hunting) feedNav = false;
    // v056: the queen's danger map (her body as walls), for QRACE, QESC_LONG and QSPRINT.
    raceQueen = QRACE && amQueen;
    qSpaceTime = QSPACETIME && amQueen; // v070
    if (amQueen && (QSPRINT || QESC_LONG || QRACE)) dangerMap(heads, std::vector<int>(body.begin() + (body.empty() ? 0 : 1), body.end()));
    int target = -1;
    if (cfg.targetW > 0 && !feedNav && !consolidating) {
        target = chooseTarget(head, L, contention);
        // v48: on an unknown map a far or doubtful target loses to unexplored ground
        if (EXPLORE_OVER > 0 && EXPLORE_TARGET && (mapIdx < 0 || (NEW_MAP_FOOD_BLIND && unseenRules)) && target >= 0 && !hunting && !amQueen && !amKing &&
            tileValue(target, dist[target], contention) * std::pow(TARGET_GAMMA, dist[target]) < EXPLORE_OVER)
            target = -1;
        if (target >= 0) bfsFrom(target, targetDist);
    }
    int explore = -1;
    if (EXPLORE_TARGET && (mapIdx < 0 || (NEW_MAP_FOOD_BLIND && unseenRules)) && target < 0 && !feedNav && !consolidating && !hunting && !amQueen && !amKing) {
        // chooseTarget fills `dist` from our head; after round 250 (targetW 0) it is only asked whether a pearl is in reach
        bool const pearlKnown = cfg.targetW <= 0 && chooseTarget(head, L, contention) >= 0;
        bool const keep = exploreTgt >= 0 && R - exploreSet < EXPLORE_KEEP && lastSeen[exploreTgt] != R && dist[exploreTgt] >= 0;
        if (!keep) {
            double const ang = ((static_cast<std::uint32_t>(ct.get_id()) * 2654435761u) >> 16) % 6283 / 1000.0;
            double hx = std::cos(ang), hy = std::sin(ang);
            for (Head const& h : heads) {
                if (h.enemy || h.pos == head) continue;
                int dx = X(head) - X(h.pos), dy = Y(head) - Y(h.pos);
                if (dx > W / 2) dx -= W; else if (dx < -W / 2) dx += W;
                if (dy > H / 2) dy -= H; else if (dy < -H / 2) dy += H;
                double const d2 = std::max(1, dx * dx + dy * dy);
                hx += 3.0 * dx / d2;
                hy += 3.0 * dy / d2;
            }
            exploreTgt = chooseExplore(head, hx, hy);
            exploreSet = R;
        }
        explore = pearlKnown ? -1 : exploreTgt;
        if (explore >= 0) bfsFrom(explore, exploreDist);
    }
    if (cfg.tabuPen > 0) {
        recentHeads.push_back(head);
        if (static_cast<int>(recentHeads.size()) > TABU_LEN) recentHeads.erase(recentHeads.begin());
    }
    int allyHeadsInView = 0;
    for (Head const& h : heads)
        if (!h.enemy) allyHeadsInView++;
    std::vector<int> pessTiles, cutTiles;
    if (cfg.pessRoom) {
        for (Head const& h : heads) {
            for (int dd = 0; dd < 4; dd++) {
                int nx = stepTo(h.pos, dd);
                if (nx >= 0) pessTiles.push_back(nx);
            }
            int hd = -1;
            for (auto const& sg : others)
                if (sg.tile == h.pos && sg.id == h.id) hd = sg.dir;
            int j = hd >= 0 ? stepTo(h.pos, hd) : -1;
            for (int k = 0; k < 2 && j >= 0; k++) {
                pessTiles.push_back(j);
                if (!h.enemy) cutTiles.push_back(j);
                j = stepTo(j, hd);
            }
        }
    }
    std::string dbg;
    if (DEBUG_IND && consolidating) dbg = "K" + std::to_string(king.id) + "/" + std::to_string(king.len) + "@" + std::to_string(R - king.round) + (amKing ? " ME " : " ");
    int bestDir = -1;
    double bestScore = -1e18;
    int bestDest = -1;
    bool bestAte = false;
    int bestReach = 0, bestNeed = 0;
    evalNoBlindPortal = (cfg.kingNoBlind && protectMe) || ALL_NO_BLIND;
    auto lethalTile = [&](int t) {
        for (Head const& h : heads)
            if (h.enemy && h.id > ct.get_id() && manhattan(h.pos, t) <= std::max(1, h.len - 2 + (h.len + 3) / 4)) return true;
        return false;
    };
    bool safeRoomyExists = false; // EXP-028
    if (QUEEN_LETHAL && amQueen)
        for (int d = 0; d < 4 && !safeRoomyExists; d++) {
            int const dest = stepTo(head, d);
            if (dest < 0 || occStamp[dest] == R || ownStamp[dest] == R || lethalTile(dest)) continue;
            int const nl2 = (lastSeen[dest] == R && pearl[dest]) ? L + 1 : L;
            if (evaluate(dest, nl2, 1, contention).reach >= SPACE_MULT * nl2 + SPACE_ADD) safeRoomyExists = true;
        }
    // v036: the queen's look-ahead (QSAFE2). qsCorner[d]: some placement of the nearest enemies after their free steps
    // leaves her no safe step from that destination next turn. qsAnyGood: some step is neither cornerable nor inside an
    // enemy's reach (along open paths) now.
    bool qsCorner[4] = {false, false, false, false};
    bool qsAnyGood = false;
    if (QSAFE2 && amQueen && !body.empty()) {
        struct QE { int pos, free, reach; };
        std::vector<QE> qe;
        {
            std::vector<std::pair<int, int>> near;
            for (int k = 0; k < static_cast<int>(heads.size()); k++)
                if (heads[k].enemy && manhattan(heads[k].pos, head) <= QSAFE2_RANGE) near.push_back({manhattan(heads[k].pos, head), k});
            std::sort(near.begin(), near.end());
            for (int k = 0; k < static_cast<int>(near.size()) && k < QSAFE2_MAXE; k++) {
                Head const& h = heads[near[k].second];
                qe.push_back({h.pos, std::max(1, (h.len + 3) / 4), std::max(1, h.reach)});
            }
        }
        if (!qe.empty()) {
            if (static_cast<int>(qsDist.size()) != N) { qsDist.assign(N, 0); qsSeen.assign(N, 0); qsWall.assign(N, 0); qsQueue.assign(N, 0); }
            int const Lb = static_cast<int>(body.size());
            bool qsAbort = false; // v048: out of budget
            auto qsOver = [&]() { return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now() - turnT0).count() > QSAFE2_BUDGET; };
            for (int d = 0; d < 4 && !qsAbort; d++) {
                int const dest = stepTo(head, d);
                if (dest < 0 || occStamp[dest] == R || ownStamp[dest] == R) continue;
                bool const grows = lastSeen[dest] == R && pearl[dest];
                // her body after this step: dest + body[0 .. Lb-2] (all of it when she eats)
                ++qsWallNow;
                qsWall[dest] = qsWallNow;
                int const keep = grows ? Lb : Lb - 1;
                for (int k = 0; k < keep; k++) qsWall[body[k]] = qsWallNow;
                bool nowL = false;
                for (QE const& e : qe) {
                    if (qsOver()) { qsAbort = true; break; }
                    qsBfs(e.pos, e.reach);
                    if (qsReached(dest) <= e.reach) { nowL = true; break; }
                }
                if (qsAbort) break;
                // her options next turn: steps onto free tiles, or a split in place when 4+ long
                std::vector<int> opts;
                for (int d2 = 0; d2 < 4; d2++) {
                    int const t = stepTo(dest, d2);
                    if (t < 0 || occStamp[t] == R || qsWall[t] == qsWallNow) continue;
                    opts.push_back(t);
                }
                if (L + (grows ? 1 : 0) >= 4) opts.push_back(dest);
                bool corner = opts.empty();
                if (!corner) {
                    // per enemy, per place it can reach this round: which of her options its strike covers
                    std::vector<std::vector<std::uint32_t>> hits(qe.size());
                    for (std::size_t i = 0; i < qe.size() && !qsAbort; i++)
                        for (int P : qsPlaces(qe[i].pos, qe[i].free, dest)) {
                            if (qsOver()) { qsAbort = true; break; }
                            qsBfs(P, qe[i].reach);
                            std::uint32_t m = 0;
                            for (std::size_t j = 0; j < opts.size() && j < 31; j++)
                                if (opts[j] == P || qsReached(opts[j]) <= qe[i].reach) m |= 1u << j;
                            hits[i].push_back(m);
                        }
                    if (qsAbort) break;
                    std::uint32_t const all = (1u << std::min<std::size_t>(opts.size(), 31)) - 1u;
                    // some combination of places (one per enemy) covering every option
                    std::vector<std::uint32_t> reachable{0u};
                    for (std::size_t i = 0; i < qe.size() && !corner; i++) {
                        std::vector<std::uint32_t> nxt;
                        for (std::uint32_t a : reachable)
                            for (std::uint32_t hm : hits[i]) {
                                std::uint32_t const m = a | hm;
                                if (m == all) { corner = true; break; }
                                if (std::find(nxt.begin(), nxt.end(), m) == nxt.end()) nxt.push_back(m);
                            }
                        reachable.swap(nxt);
                    }
                }
                qsCorner[d] = corner;
                if (!corner && !nowL) qsAnyGood = true;
            }
            if (qsAbort) { // v048: no look-ahead this turn
                qsAnyGood = false;
                for (int d = 0; d < 4; d++) qsCorner[d] = false;
            }
        }
    }
    double dirScore[4] = {-1e18, -1e18, -1e18, -1e18}; // v056: each single step's score, for the queen's sprints
    for (int d = 0; d < 4; d++) {
        int dest = stepTo(head, d);
        if (dest < 0) continue;
        if (occStamp[dest] == R) continue;
        if (ownStamp[dest] == R) continue;
        if (QUEEN_PB && !amQueen && qpbWarned(head, d)) continue;
        bool ate = lastSeen[dest] == R && pearl[dest];
        int newLen = ate ? L + 1 : L;
        Eval ev = evaluate(dest, newLen, 1, contention);
        double score = ev.score;
        // A pearl on the destination is certain; the flood fill's total is mostly spawn guesses
        // spread over hundreds of tiles. Our dragons passed up an uncontested adjacent pearl 25% of
        // the time (the top teams 17%), mostly for directions with a bigger total of guesses.
        // v67 (Oct 3; STRATEGY 1l): a pearl on the destination is ours for certain: lower ids already moved this round,
        // higher ids move after us. With a pearl next to it our dragon took it 48% of the time, chaoliangUNSW's 54%
        // (rounds 1-100, same maps). The contention discount (0.35-0.7) no longer applies to it, and the bonus is 3.
        if (ate) score += EAT_NOW_BONUS;
        if (ate && L == 2 && R <= stubUntil) score -= STUB_NOEAT_PEN; // v023c: the ceiling stub stays at 2

        int need = SPACE_MULT * newLen + SPACE_ADD;
        // A dead end is not a death trap for a dragon that can split its way back out: at the end
        // the tail side leaves as a new dragon (BOXED_SAVE) and only a 2-segment stub is lost.
        bool const farmHere = FARM_UNSEEN && unseenRules;
        bool const canTurn = (cfg.uturn || farmHere) && !protectMe && units < ct.unit_limit - 1 &&
                             (farmHere ? newLen + ev.certain >= POCKET_MIN_LEN   // v016: pearls in view; v023: 5 (Ben)
                                       : newLen + static_cast<int>(ev.pearls) >= 4);
        bool const pocketMove = pocketTarget >= 0 && (pocketOf[dest] == pocketTarget || dest == pockets[pocketTarget].entrance);
        if (ev.reach < need && !pocketMove) score -= (canTurn ? UTURN_COST : 20.0 + (need - ev.reach) * 2.0) * (stalled ? STALL_ROOM : 1.0);
        if (DEADEND_GUARD && farmHere && !amQueen && openDegree(dest) == 1 && newLen + ev.certain < POCKET_MIN_LEN) score -= DEADEND_GUARD_PEN;
        if (QUEEN_LETHAL && amQueen && safeRoomyExists && lethalTile(dest)) score -= QLETHAL_PEN; // EXP-028
        // (v021: the soft room penalty that used to sit in a dangling else here only ever ran while stalled, once per
        // history tile; outside a stall it never applied, so dropping it keeps every other move's score as it was.)
        if (stalled)
            for (int p : stallHist)
                if (p == dest) score -= STALL_TABU;
        // The queen never ends beside a portal: a dragon crossing it blind arrives on that tile. Locally 4 of 20 queens
        // were killed head-on by our own dragons, all on portal maps (Default, Portals, Queen of Spades).
        if (amQueen)
            for (int dd = 0; dd < 4; dd++)
                if (edgeT[dest * 4 + dd] == 2) { score -= (mapIdx >= 0 && !(NEW_MAP_FOOD_BLIND && unseenRules)) ? QUEEN_PORTAL_PEN : QUEEN_PORTAL_PEN_UNKNOWN; break; }
        if (QSAFE2 && amQueen && qsAnyGood && qsCorner[d]) score -= QSAFE2_PEN;
        if (QTRAP && amQueen) {
            int const cap = std::max(QTRAP_MIN, QTRAP_MULT * newLen + QTRAP_ADD);
            int const room = roomStatic(dest, cap, body);
            if (room < cap) score -= QTRAP_PEN + QTRAP_W * (cap - room);
        }
        int const qHome = learnedHome >= 0 ? learnedHome : homeTile;
        if (QUEEN_HOME && amQueen && qHome >= 0 && units >= QHOME_UNITS && (QHOME_LATE || R < consStart)) {
            int const over = manhattan(dest, qHome) - QHOME_LEASH;
            if (over > 0) score -= QHOME_W * over;
        }
        if (QANCHOR && amQueen && R >= consStart) {
            if (qAnchor < 0) qAnchor = head;
            int const over = manhattan(dest, qAnchor) - QANCHOR_R;
            if (over > 0) score -= QANCHOR_W * over;
            if (edgeT[head * 4 + d] == 2) score -= QANCHOR_PORTAL;
        }
        if (cfg.pessRoom && !pocketMove) {
            int const need2 = std::min(2 * newLen + PESS_MARGIN, 100);
            int const r2 = roomPess(dest, need2, newLen, pessTiles);
            if (r2 < need2) score -= cfg.pessW * (need2 - r2);
            if (r2 < newLen + 2) score -= cfg.pessLethal;
            if (std::find(cutTiles.begin(), cutTiles.end(), dest) != cutTiles.end()) score -= cfg.cutPen;
        }
        if (cfg.deadend && !pocketMove && ev.reach >= need) {
            // The flood fill lets our own body clear out of the way, but not the body we lay down
            // as we go: it walks us into one-wide dead ends it thinks we can walk back out of.
            // Follow the corridor by its walls; a dead end with no junction is a trap unless we
            // can split our way back out.
            int prev = head, cur = dest, depth = 0, pocketPearls = 0;
            bool trap = false;
            while (depth < 40) {
                if (lastSeen[cur] == R && pearl[cur]) pocketPearls++;
                int nextTile = -1, ways = 0;
                for (int dd = 0; dd < 4; dd++) {
                    int nx = stepTo(cur, dd);
                    if (nx < 0 || nx == prev) continue;
                    ways++;
                    nextTile = nx;
                }
                if (ways == 0) { trap = true; break; }
                if (ways > 1) break;
                prev = cur;
                cur = nextTile;
                depth++;
            }
            bool const canSplitOut = !protectMe && units < ct.unit_limit - 1 && newLen + pocketPearls >= 4;
            if (trap) score -= canSplitOut ? cfg.deadendSplitCost : 20.0;
        }

        // S2a: the queen keeps away from enemy heads before they can corner her, and keeps two safe exits.
        if (QUEEN_FLEE && amQueen) {
            for (Head const& h : heads) {
                if (!h.enemy) continue;
                int const md = manhattan(h.pos, dest), r = h.reach;
                if (md <= r + QFLEE_RANGE) score -= QFLEE_W * (r + QFLEE_RANGE + 1 - md);
            }
            int safeExits = 0;
            for (int dd = 0; dd < 4; dd++) {
                int const nx = stepTo(dest, dd);
                if (nx < 0 || nx == head || occStamp[nx] == R || (ownStamp[nx] == R && ownIndex[nx] < L - 1)) continue;
                bool reached = false;
                for (Head const& h : heads)
                    if (h.enemy && manhattan(h.pos, nx) <= h.reach) { reached = true; break; }
                if (!reached) safeExits++;
            }
            if (safeExits < 2) score -= QEXIT_PEN * (2 - safeExits);
        }
        // v66: keep our queen's exits open (she moves first next round).
        if (QUEEN_GAP && !amQueen)
            for (Head const& h : heads)
                if (!h.enemy && h.id <= 1 && manhattan(h.pos, dest) == 1) {
                    int freeSides = 0;
                    for (int dd = 0; dd < 4; dd++) {
                        int nx = stepTo(h.pos, dd);
                        if (nx >= 0 && nx != dest && occStamp[nx] != R && ownStamp[nx] != R) freeSides++;
                    }
                    score -= freeSides <= 2 ? QGAP_PEN_TIGHT : QGAP_PEN;
                }
        // Heads that move after us this round can close the tile's exits.
        for (Head const& h : heads) {
            if (!h.enemy && (cfg.allyAdjAll || h.id > ct.get_id()) && manhattan(h.pos, dest) == 1) score -= cfg.allyAdj;
        }

        for (Head const& h : heads) {
            if (!h.enemy) continue;
            int md = manhattan(h.pos, dest);
            if (protectMe) score -= cfg.kingRepel / std::max(1, md);
            if (protectMe) {
                // A dragon of length n can sprint n-1 tiles in one turn, and one head-on
                // collision costs us the whole tiebreak. Stay out of every enemy's strike range.
                int strike = std::max(1, std::min(KING_BRAVE ? 2 : 4, h.len - 1 + KING_STRIKE_BONUS));
                // The queen keeps out of an enemy's real reach under the 1 Oct sprint rule (ceil(n/4) free steps, then
                // one segment a step down to 2: n - 2 + ceil(n/4) tiles; n is only the visible length, so one more).
                // Locally a 3-long enemy rammed our 9-long queen from 2 tiles at round 283 (her penalty was 10).
                if (amQueen) strike = QUEEN_REACH_EXACT ? h.reach : std::max(2, h.len - 2 + (h.len + 3) / 4 + 1);
                if (md <= strike) score -= (amQueen ? 40.0 : (KING_BRAVE ? 4.0 : 10.0)) + 0.2 * L + 2.0 * (strike - md);
                else if (md == strike + 1) score -= amQueen ? 8.0 : (KING_BRAVE ? 1.0 : 3.0);
                else if (md == strike + 2) score -= amQueen ? 2.0 : (KING_BRAVE ? 0.3 : 0.8);
            } else if (cfg.midSafe && L >= MID_SAFE_LEN && h.len < L && md <= std::max(1, std::min(4, h.len - 1))) {
                score -= 3.0 + 0.2 * L + 1.0 * (std::min(4, h.len - 1) - md);
            } else if (md == 1) {
                if (isKing) score -= 6.0 + 0.1 * L;
                else score -= ENEMY_ADJ + 0.3 * std::max(0, L - h.len);
            } else if (md == 2 && h.len >= 3) {
                score -= isKing ? 1.0 : ENEMY_ADJ * 0.3;
            }
            if (HUNT > 0 && !isKing && units >= 2 && h.len >= L + HUNT_MARGIN && md >= 2)
                score += HUNT * std::max(0, 7 - md) / 7.0;
        }
        // Stepping through a portal is always blind: vision stops at it. With the maps built in our
        // dragons use portals all the time, and walked onto allies' heads on the far side.
        if (cfg.pbEnable && edgeT[head * 4 + d] == 2 && portalId[head * 4 + d] >= 0) {
            auto b = pbRx.find(portalId[head * 4 + d]);
            if (b != pbRx.end() && R - b->second <= PB_TTL) score -= PB_PEN;
        }
        // v52: our queen is at the far side of this portal (she said so this round): crossing it rams her.
        if (QUEEN_PB && !amQueen && edgeT[head * 4 + d] == 2 && portalId[head * 4 + d] >= 0) {
            auto b = qpbRx.find(portalId[head * 4 + d]);
            if (b != qpbRx.end() && R - b->second <= 1) score -= QUEEN_PB_PEN;
        }
        // Waiting at the door of a busy portal blocks the only way out of the room behind it.
        if (cfg.pbEnable && PB_DOOR > 0)
            for (int dd = 0; dd < 4; dd++)
                if (edgeT[dest * 4 + dd] == 2 && portalId[dest * 4 + dd] >= 0) {
                    auto b = pbRx.find(portalId[dest * 4 + dd]);
                    if (b != pbRx.end() && R - b->second <= PB_TTL + 1) score -= PB_DOOR;
                }
        if (cfg.ptEnable && edgeT[head * 4 + d] == 2 && portalId[head * 4 + d] >= 0) {
            int const pid = portalId[head * 4 + d];
            auto a = ptAlly.find(pid), e = ptEnemy.find(pid);
            if ((a != ptAlly.end() && R - a->second <= PT_TTL) || (e != ptEnemy.end() && R - e->second <= PT_TTL)) score -= PT_PEN;
        }
        if (lastSeen[dest] != R) {
            bool const probed = edgeT[head * 4 + d] == 2 && probedClear(head, d);
            score -= (probed ? PORTAL_PROBED : cfg.blindPortal) * (amKing ? KING_PORTAL : 1.0);
            if (DEBUG_IND) dbg += std::string(probed ? "[P+]" : "[P-]") + "v" + std::to_string(verdictRound == R ? (verdictClear ? verdictDir : 9) : -1);
        }
        if (feedNav && distKing[dest] >= 0) score -= FEED_PULL * distKing[dest];
        if (hunting && preyDist[dest] >= 0) score -= PREY_W * preyDist[dest];
        if (target >= 0 && targetDist[dest] >= 0) score -= cfg.targetW * targetDist[dest];
        if (explore >= 0 && exploreDist[dest] >= 0) score -= EXPLORE_W * exploreDist[dest];
        if (pocketTarget >= 0 && pockets[pocketTarget].dist[dest] >= 0) score -= POCKET_W * pockets[pocketTarget].dist[dest];
        if (CORR_PEN > 0 && openDegree(dest) == 2) {
            int prev = head, cur = dest;
            for (int k = 0; k < CORR_MAX; k++) {
                bool hit = false;
                for (Head const& h : heads)
                    if (h.pos == cur) hit = true;
                if (hit) { score -= CORR_PEN / (1.0 + 0.25 * k); break; }
                if (openDegree(cur) != 2) break;
                int nxt = -1;
                for (int dd = 0; dd < 4; dd++) {
                    int nx = stepTo(cur, dd);
                    if (nx >= 0 && nx != prev) { nxt = nx; break; }
                }
                if (nxt < 0) break;
                prev = cur;
                cur = nxt;
            }
        }
        // A feeder waiting for the king to finish eating must not wall it in.
        if (feedKingHead >= 0 && manhattan(dest, feedKingHead) <= 1) score -= FEED_CROWD;
        // ...nor eat the king's food: stepping on a pearl eats it.
        if (noEatCenter >= 0 && lastSeen[dest] == R && pearl[dest] && manhattan(dest, noEatCenter) <= noEatR)
            score -= NOEAT_PEN;
        if (fTarget >= 0 && fountainDist[fTarget][dest] >= 0) score -= cfg.fpull * fountainDist[fTarget][dest];
        if (dispersing && !feedNav && dispDist[dest] >= 0) score -= cfg.dispW * dispDist[dest];
        // Online our dragons lapped 2x2 squares beside fountain channels for 20-50 rounds: the
        // pearls in view kept the score up, the dead end kept them out. Revisits cost a little.
        if (cfg.tabuPen > 0 && !feedNav)
            for (int p : recentHeads)
                if (p == dest) score -= cfg.tabuPen;
        if (cfg.dpull > 0 && mapIdx >= 0 && !protectMe && !feedNav && allyHeadsInView < DPULL_CROWD)
            score += cfg.dpull * (prodDensity[dest] - prodDensity[head]);
        // Keep out of a fountain an ally is working, and off its doorstep: one dragon walking in
        // against the flow jams the whole factory.
        for (int c = 0; c < static_cast<int>(clusterTaken.size()); c++)
            if (clusterTaken[c] && fountainDist[c][dest] >= 0 && fountainDist[c][dest] <= 1) score -= KEEPOUT_COST;
        double const crowdW = cfg.crowdForce > 0 ? cfg.crowdForce : (CROWD_OPEN_MAPS_ONLY && mapHasFountain ? 0.0 : CROWD);
        if (crowdW > 0 && !feedNav && !(KING_NO_CROWD && amKing && consolidating) && !(CROWD_FOUNTAIN_EXEMPT && nearFountain[dest])) {
            int crowd = 0;
            for (auto const& sg : others)
                if (!sg.enemy && std::max(wrapDist(X(sg.tile), X(dest), W), wrapDist(Y(sg.tile), Y(dest), H)) <= 2) crowd++;
            score -= crowdW * crowd;
        }

        if (DEBUG_IND) dbg += std::string(1, DC[d]) + ":" + std::to_string(static_cast<int>(ev.score * 1000)) + "/" + std::to_string(static_cast<int>(score * 1000)) + "/" + std::to_string(ev.reach) + " ";
        dirScore[d] = score;
        if (score > bestScore) {
            bestScore = score;
            bestDir = d;
            bestDest = dest;
            bestAte = ate;
            bestReach = ev.reach;
            bestNeed = need;
        }
    }

    if (bestDir < 0) {
        // Boxed in. Take an adjacent enemy head with us if there is one...
        for (int d = 0; d < 4; d++) {
            int dest = stepTo(head, d);
            if (dest < 0) continue;
            for (Head const& h : heads) {
                if (h.enemy && h.pos == dest) {
                    ct.make_move(Direction(DC[d]));
                    predicted.clear();
                    return;
                }
            }
        }
        // ...otherwise a split keeps us still for a turn and frees tail space.
        // The queen keeps her head end: shedding all but 2 leaves her as the doomed stub (the queen is the parent).
        int shed = (BOXED_SAVE && !amQueen) ? L - 2 : 2;
        if (shed >= 2 && canSplit(shed)) {
            ct.do_split(shed);
            if (!amQueen && L - shed == 2 && unseenRules) stubUntil = R + STUB_TURNS;
            ct.set_indicator_string("SAVE");
            predicted.assign(body.begin(), body.begin() + std::max<int>(1, static_cast<int>(body.size()) - shed));
            return;
        }
        // We die whatever we do; never take an ally's head with us.
        int fallback = -1;
        // v051: a portal whose far side we do not know beats our own body (Caution, v050: our queen stepped into her neck
        // at r1 in 3 of 3 games, the unknown portal beside her head being her only way on).
        for (int d = 0; d < 4 && fallback < 0; d++)
            if (edgeT[head * 4 + d] == 2 && stepTo(head, d) < 0 && !(QUEEN_PB && !amQueen && qpbWarned(head, d))) fallback = d;
        for (int d = 0; d < 4 && fallback < 0; d++) {
            int dest = stepTo(head, d);
            bool allyHead = false;
            for (Head const& h : heads)
                if (!h.enemy && dest >= 0 && h.pos == dest) allyHead = true;
            if (allyHead) continue;
            if (QUEEN_PB && !amQueen && qpbWarned(head, d)) continue;
            if (dest >= 0) { fallback = d; break; }
        }
        for (int d = 0; d < 4 && fallback < 0; d++) {
            bool allyHead = false;
            int const dest = stepTo(head, d);
            for (Head const& h : heads)
                if (!h.enemy && dest >= 0 && h.pos == dest) allyHead = true;
            if (!allyHead && !(QUEEN_PB && !amQueen && qpbWarned(head, d))) fallback = d;
        }
        if (fallback < 0)
            for (int d = 0; d < 4 && fallback < 0; d++)
                if (!(QUEEN_PB && !amQueen && qpbWarned(head, d))) fallback = d;
        bestDir = fallback < 0 ? 0 : fallback;
        ct.make_move(Direction(DC[bestDir]));
        predicted.clear();
        return;
    }

    if (amKing && bestScore < KSAVE_BELOW && L >= 6 && static_cast<int>(body.size()) == L && canSplit(L - 2)) {
        int const tail = body[L - 1];
        bool tailFree = false;
        for (int dd = 0; dd < 4; dd++) {
            int nx = stepTo(tail, dd);
            if (nx >= 0 && occStamp[nx] != R && ownStamp[nx] != R && lastSeen[nx] == R) tailFree = true;
        }
        if (tailFree) {
            ct.do_split(L - 2);
            ct.set_indicator_string("KSAVE");
            predicted.assign(body.begin(), body.begin() + 2);
            return;
        }
    }
    if (ESCAPE_SPLIT && bestReach < bestNeed && L >= 4 && static_cast<int>(body.size()) == L) {
        // Keep only what the room we can reach will hold.
        int keep = std::max(2, std::min(L - 2, bestReach - 3));
        int child = L - keep;
        if (child >= 2 && canSplit(child)) {
            ct.do_split(child);
            ct.set_indicator_string("ESCAPE");
            predicted.assign(body.begin(), body.begin() + keep);
            return;
        }
    }
    if (DEBUG_IND) ct.set_indicator_string(dbg);
    std::vector<int> simBody;
    simBody.push_back(bestDest);
    simBody.insert(simBody.end(), body.begin(), body.end());
    int curLen = bestAte ? L + 1 : L;
    if (static_cast<int>(simBody.size()) > curLen) simBody.resize(curLen);
    std::vector<int> stepDirs{bestDir};
    // v056: the queen's sprints. Every path of 2..n free steps (n = min(ceil(L/4), QS_MAX_STEPS)) over visible tiles, no
    // portal crossing, no tile held by another dragon or by her body as the step before left it.
    struct QPath { std::vector<int> dirs, body; int len, eatenLater; double val; };
    auto qsCheb = [&](int a, int b) { return std::max(wrapDist(X(a), X(b), W), wrapDist(Y(a), Y(b), H)); };
    auto qsElapsed = [&]() { return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now() - turnT0).count(); };
    auto qsPaths = [&](int maxSteps, int view, bool const* firstOk) {
        std::vector<QPath> out;
        std::vector<int> dirs;
        auto rec = [&](auto&& self, int cur, std::vector<int> const& bb, int len, int eatenLater) -> void {
            if (static_cast<int>(dirs.size()) >= 2) out.push_back({dirs, bb, len, eatenLater, 0.0});
            if (static_cast<int>(dirs.size()) >= maxSteps) return;
            for (int d = 0; d < 4; d++) {
                if (dirs.empty() && !firstOk[d]) continue;
                int const nx = stepTo(cur, d);
                if (nx < 0 || occStamp[nx] == R || lastSeen[nx] != R || edgeT[cur * 4 + d] == 2) continue;
                if (view > 0 && qsCheb(nx, head) > view) continue;
                if (std::find(bb.begin(), bb.end(), nx) != bb.end()) continue; // her body, tail included
                bool const ate = pearl[nx] != 0;
                std::vector<int> nb{nx};
                nb.insert(nb.end(), bb.begin(), bb.end());
                int const nl = len + (ate ? 1 : 0);
                if (static_cast<int>(nb.size()) > nl) nb.resize(nl);
                dirs.push_back(d);
                self(self, nx, nb, nl, eatenLater + (ate && dirs.size() > 1 ? 1 : 0));
                dirs.pop_back();
            }
        };
        rec(rec, head, body, L, 0);
        return out;
    };
    // v070 QBEAM: the same paths, depth by depth, keeping the QS_BEAM best partial paths by a cheap value.
    auto qsBeam = [&](int maxSteps, int view, bool const* firstOk) {
        std::vector<QPath> out, layer;
        layer.push_back({{}, body, L, 0, 0.0});
        for (int depth = 0; depth < maxSteps && !layer.empty(); depth++) {
            std::vector<QPath> next;
            for (QPath const& p : layer) {
                int const cur = p.dirs.empty() ? head : p.body[0];
                for (int d = 0; d < 4; d++) {
                    if (p.dirs.empty() && !firstOk[d]) continue;
                    int const nx = stepTo(cur, d);
                    if (nx < 0 || occStamp[nx] == R || lastSeen[nx] != R || edgeT[cur * 4 + d] == 2) continue;
                    if (view > 0 && qsCheb(nx, head) > view) continue;
                    if (std::find(p.body.begin(), p.body.end(), nx) != p.body.end()) continue; // her body, tail included
                    bool const ate = pearl[nx] != 0;
                    QPath q{p.dirs, {nx}, p.len + (ate ? 1 : 0), p.eatenLater + (ate && !p.dirs.empty() ? 1 : 0), 0.0};
                    q.dirs.push_back(d);
                    q.body.insert(q.body.end(), p.body.begin(), p.body.end());
                    if (static_cast<int>(q.body.size()) > q.len) q.body.resize(q.len);
                    q.val = QS_EAT_W * (q.len - L) + std::min(dgT[nx], QS_SAFE_T + 1) - QS_STEP_COST * static_cast<double>(q.dirs.size());
                    next.push_back(std::move(q));
                }
            }
            std::sort(next.begin(), next.end(), [](QPath const& x, QPath const& y) { return x.val > y.val; });
            if (static_cast<int>(next.size()) > QS_BEAM) next.resize(QS_BEAM);
            for (QPath const& q : next)
                if (q.dirs.size() >= 2) out.push_back(q);
            layer.swap(next);
        }
        for (QPath& q : out) q.val = 0.0;
        return out;
    };
    // v070: 4+ free steps (13+ long) search up to QS_MAX_LONG steps by beam; shorter queens keep v056's DFS
    auto qsSearch = [&](int view, bool const* firstOk) {
        return (QBEAM && sprintFree >= 4) ? qsBeam(std::min(sprintFree, QS_MAX_LONG), view, firstOk)
                                          : qsPaths(std::min(sprintFree, QS_MAX_STEPS), view, firstOk);
    };
    // inside some visible enemy's reach when she stands at `tile` with body `hb` (head first)?
    auto qsInReach = [&](int tile, std::vector<int> const& hb) -> bool {
        if (static_cast<int>(qsDist.size()) != N) { qsDist.assign(N, 0); qsSeen.assign(N, 0); qsWall.assign(N, 0); qsQueue.assign(N, 0); }
        ++qsWallNow;
        for (int t : hb) qsWall[t] = qsWallNow;
        for (Head const& h : heads) {
            if (!h.enemy) continue;
            qsBfs(h.pos, h.reach);
            if (qsReached(tile) <= h.reach) return true;
        }
        return false;
    };
    bool const qsEnemy = std::any_of(heads.begin(), heads.end(), [](Head const& h) { return h.enemy; });
    // v056 QESC_LONG: at 9+ (3 free steps) her chosen step inside an enemy's reach: the path of up to 3 free steps that
    // ends outside every reach with the most safe territory (tiles she reaches before any enemy), then rounds of margin.
    if (QESC_LONG && amQueen && sprintFree >= 3 && qsEnemy && static_cast<int>(body.size()) == L && qsElapsed() <= QS_BUDGET &&
        qsInReach(bestDest, simBody)) {
        bool anyFirst[4] = {true, true, true, true};
        std::vector<QPath> paths = qsSearch(0, anyFirst); // v070
        int best = -1;
        double bestVal = -1e18;
        for (int i = 0; i < static_cast<int>(paths.size()); i++) {
            if (qsElapsed() > QS_BUDGET) break;
            QPath& p = paths[i];
            int const e = p.body[0];
            if (qsInReach(e, p.body)) continue;
            int const need = 2 * p.len + PESS_MARGIN;
            std::vector<int> walls(p.body.begin() + 1, p.body.end());
            int const room = roomPess(e, need, p.len, walls);
            if (room < p.len + 4) continue;
            int const terr = safeRoom(e, need, std::max(1, (p.len + 3) / 4), walls);
            p.val = terr + 3.0 * std::min(dgT[e] - 1, QS_SAFE_T) + QS_EAT_W * p.eatenLater - 0.5 * static_cast<double>(p.dirs.size());
            if (p.val > bestVal) { bestVal = p.val; best = i; }
        }
        if (best >= 0) {
            QPath const& p = paths[best];
            bestDir = p.dirs[0];
            bestDest = stepTo(head, bestDir);
            stepDirs = p.dirs;
            simBody = p.body;
            curLen = p.len;
            ct.set_indicator_string("QESC3");
        }
    }
    // v037: the queen's escape step (QESCAPE).
    if (QESCAPE && amQueen && L >= 3 && static_cast<int>(body.size()) == L && stepDirs.size() == 1) {
        if (static_cast<int>(qsDist.size()) != N) { qsDist.assign(N, 0); qsSeen.assign(N, 0); qsWall.assign(N, 0); qsQueue.assign(N, 0); }
        // inside some visible enemy's reach when she stands at `tile` with body `hb` (head first)?
        auto inReach = [&](int tile, std::vector<int> const& hb) -> bool {
            ++qsWallNow;
            for (int t : hb) qsWall[t] = qsWallNow;
            for (Head const& h : heads) {
                if (!h.enemy) continue;
                qsBfs(h.pos, h.reach); // paths follow portals, so they can be shorter than the Manhattan distance
                if (qsReached(tile) <= h.reach) return true;
            }
            return false;
        };
        if (inReach(bestDest, simBody)) {
            int const freeSteps = (L + 3) / 4;
            int bestA = -1, bestB = -1, bestD1 = -1, bestD2 = -1, bestLen = 0;
            double bestVal = -1e18;
            std::vector<int> bestBody;
            for (int d1 = 0; d1 < 4; d1++) {
                int const a = stepTo(head, d1);
                if (a < 0 || occStamp[a] == R || ownStamp[a] == R || lastSeen[a] != R || edgeT[head * 4 + d1] == 2) continue;
                bool const ateA = pearl[a] != 0;
                std::vector<int> b1{a};
                b1.insert(b1.end(), body.begin(), body.end());
                int const len1 = L + (ateA ? 1 : 0);
                if (static_cast<int>(b1.size()) > len1) b1.resize(len1);
                for (int d2 = 0; d2 < 4; d2++) {
                    int const b = stepTo(a, d2);
                    if (b < 0 || occStamp[b] == R || lastSeen[b] != R || edgeT[a * 4 + d2] == 2) continue;
                    if (std::find(b1.begin(), b1.end(), b) != b1.end()) continue; // her body after step 1, tail included
                    bool const ateB = pearl[b] != 0;
                    int const len2 = len1 + (ateB ? 1 : 0) - (freeSteps >= 2 ? 0 : 1); // the 2nd step costs a segment below 5
                    if (len2 < 2) continue;
                    std::vector<int> b2{b};
                    b2.insert(b2.end(), b1.begin(), b1.end());
                    if (static_cast<int>(b2.size()) > len2) b2.resize(len2);
                    if (inReach(b, b2)) continue;
                    // room from there (other bodies and the tiles she just walked as walls)
                    std::vector<int> walked{a, head};
                    int const need = 2 * len2 + PESS_MARGIN;
                    int const room = roomPess(b, need, len2, walked);
                    if (room < len2 + 4) continue;
                    int nearest = 99;
                    for (Head const& h : heads)
                        if (h.enemy) nearest = std::min(nearest, manhattan(h.pos, b) - h.reach);
                    double const val = std::min(room, need) + 3.0 * std::min(nearest, 4) - (freeSteps >= 2 ? 0.0 : 2.0);
                    if (val > bestVal) { bestVal = val; bestA = a; bestB = b; bestD1 = d1; bestD2 = d2; bestLen = len2; bestBody = b2; }
                }
            }
            if (bestB >= 0) {
                bestDir = bestD1;
                bestDest = bestA;
                stepDirs.assign({bestD1, bestD2});
                simBody = bestBody;
                curLen = bestLen;
                ct.set_indicator_string("QESC2");
            }
        }
    }
    // v056 QSPRINT: the farming sprint. A path of 2..3 free steps starting with a step scored within QS_FIRST_SLACK of
    // her best, ending within QS_VIEW of her head, worth QS_EAT_W per pearl eaten after the first step (and her target's
    // pull), less the danger margin and leash it loses; taken when it beats her single step by QS_MIN_GAIN and, checked in
    // full, ends no less safe: outside every reach, no closer in rounds to an enemy, no tighter room, no new portal edge or
    // ally head beside her.
    if (QSPRINT && amQueen && stepDirs.size() == 1 && sprintFree >= 2 && !stalled && static_cast<int>(body.size()) == L &&
        edgeT[head * 4 + bestDir] != 2 && qsElapsed() <= QS_BUDGET) {
        bool firstOk[4];
        for (int d = 0; d < 4; d++) firstOk[d] = dirScore[d] > -1e17 && dirScore[d] >= bestScore - QS_FIRST_SLACK;
        std::vector<QPath> paths = qsSearch(QS_VIEW, firstOk); // v070
        int const qHomeS = learnedHome >= 0 ? learnedHome : homeTile;
        bool const leashOn = QUEEN_HOME && qHomeS >= 0 && units >= QHOME_UNITS && (QHOME_LATE || R < consStart);
        auto leashPen = [&](int t) { return leashOn ? QHOME_W * std::max(0, manhattan(t, qHomeS) - QHOME_LEASH) : 0.0; };
        auto dangerPen = [&](int t) { return QS_DANGER_W * std::max(0, QS_SAFE_T - dgT[t]); };
        for (QPath& p : paths) {
            int const a = stepTo(head, p.dirs[0]), e = p.body[0];
            double v = dirScore[p.dirs[0]] - bestScore + QS_EAT_W * p.eatenLater - QS_STEP_COST * (static_cast<double>(p.dirs.size()) - 1.0);
            if (target >= 0 && targetDist[a] >= 0 && targetDist[e] >= 0) v += cfg.targetW * (targetDist[a] - targetDist[e]);
            v -= (dangerPen(e) - dangerPen(a)) + (leashPen(e) - leashPen(a));
            p.val = v;
        }
        std::sort(paths.begin(), paths.end(), [](QPath const& x, QPath const& y) { return x.val > y.val; });
        auto portalBeside = [&](int t) { for (int dd = 0; dd < 4; dd++) if (edgeT[t * 4 + dd] == 2) return true; return false; };
        auto allyBeside = [&](int t) { for (Head const& h : heads) if (!h.enemy && manhattan(h.pos, t) == 1) return true; return false; };
        int const capB = std::max(QTRAP_MIN, QTRAP_MULT * curLen + QTRAP_ADD);
        std::vector<int> wallsB(simBody.begin() + 1, simBody.end());
        int const needB = std::min(2 * curLen + PESS_MARGIN, 100);
        int roomB = -1, trapB = -1; // the single step's, computed on first use
        for (int i = 0; i < static_cast<int>(paths.size()) && i < QS_VERIFY; i++) {
            QPath const& p = paths[i];
            if (p.val < QS_MIN_GAIN || qsElapsed() > QS_BUDGET) break;
            int const e = p.body[0];
            if (qsEnemy && (qsInReach(e, p.body) || dgT[e] < std::min(dgT[bestDest], QS_SAFE_T))) continue;
            if (portalBeside(e) && !portalBeside(bestDest)) continue;
            if (allyBeside(e) && !allyBeside(bestDest)) continue;
            std::vector<int> walls(p.body.begin() + 1, p.body.end());
            int const cap = std::max(QTRAP_MIN, QTRAP_MULT * p.len + QTRAP_ADD);
            if (trapB < 0) trapB = roomStatic(bestDest, capB, wallsB); // her body after the move, head excluded
            if (roomStatic(e, cap, walls) < std::min(cap, trapB)) continue;
            int const need = std::min(2 * p.len + PESS_MARGIN, 100);
            if (roomB < 0) roomB = roomPess(bestDest, needB, curLen, wallsB);
            if (roomPess(e, need, p.len, walls) < std::min(need, roomB)) continue;
            bestDir = p.dirs[0];
            bestDest = stepTo(head, bestDir);
            stepDirs = p.dirs;
            simBody = p.body;
            curLen = p.len;
            ct.set_indicator_string("QSPR");
            break;
        }
    }
    if (FREE_SPRINT && !amQueen && sprintFree >= 2 && !stalled && static_cast<int>(body.size()) == L) { // e023b: the queen keeps single, fully scored steps
        std::vector<int> path; // tiles this sprint walked before the current head, newest first
        // Flood-fill value of standing on `h` after `taken` steps, the walked tiles as body segments freeing from the tail.
        auto evalAt = [&](int h, int lenAt, int taken) {
            std::vector<std::pair<int, std::pair<int, int>>> saved;
            for (int j = 0; j < static_cast<int>(path.size()); j++) {
                int const t = path[j];
                saved.push_back({t, {ownStamp[t], ownIndex[t]}});
                ownStamp[t] = R;
                ownIndex[t] = j + 1 - taken; // path[j] ends at index j + 1
            }
            Eval ev = evaluate(h, lenAt, taken, contention);
            for (auto it = saved.rbegin(); it != saved.rend(); ++it) {
                ownStamp[it->first] = it->second.first;
                ownIndex[it->first] = it->second.second;
            }
            return ev;
        };
        bool const roomy = std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now() - turnT0).count() <= SPRINT_BUDGET;
        double stopScore = (target >= 0 || !roomy) ? 0.0 : evalAt(bestDest, curLen, 1).score;
        for (int k = 1; k < sprintFree; k++) {
            if (std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now() - turnT0).count() > SPRINT_BUDGET) break;
            int const cur = simBody[0];
            path.insert(path.begin(), cur);
            int const steps = k + 1;
            int bestNx = -1, bestNd = -1, bestTd = target >= 0 ? targetDist[cur] : 0;
            double bestSc = stopScore;
            bool bestAte2 = false;
            for (int d = 0; d < 4; d++) {
                int const nx = stepTo(cur, d);
                if (nx < 0 || occStamp[nx] == R || lastSeen[nx] != R) continue;
                if (std::find(simBody.begin(), simBody.end(), nx) != simBody.end()) continue; // own body, tail included
                if (QUEEN_PB && !amQueen && qpbWarned(cur, d)) continue;
                if (edgeT[cur * 4 + d] == 2) continue; // no blind portal crossings mid-sprint
                if (target >= 0 && (targetDist[nx] < 0 || targetDist[nx] >= bestTd)) continue;
                bool unsafe = false;
                for (Head const& h : heads) {
                    if (!h.enemy) continue;
                    int const md = manhattan(h.pos, nx);
                    if ((amQueen || protectMe) ? md <= h.reach + 1 : md <= 1) unsafe = true;
                }
                if (unsafe) continue;
                if (std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now() - turnT0).count() > SPRINT_BUDGET) break;
                bool const ate2 = lastSeen[nx] == R && pearl[nx];
                int const len2 = curLen + (ate2 ? 1 : 0);
                Eval ev = evalAt(nx, len2, steps);
                if (ev.reach < SPACE_MULT * len2 + SPACE_ADD) continue;
                double const sc = ev.score + (ate2 ? EAT_NOW_BONUS : 0.0);
                if (target >= 0) {
                    bestTd = targetDist[nx];
                } else if (sc <= bestSc) {
                    continue;
                }
                bestSc = sc;
                bestNx = nx;
                bestNd = d;
                bestAte2 = ate2;
            }
            if (bestNx < 0) { path.erase(path.begin()); break; }
            stopScore = bestSc;
            int const len2 = curLen + (bestAte2 ? 1 : 0);
            simBody.insert(simBody.begin(), bestNx);
            if (!bestAte2 && static_cast<int>(simBody.size()) > len2) simBody.pop_back();
            curLen = len2;
            stepDirs.push_back(bestNd);
        }
    }
    if (stepDirs.size() == 1) ct.make_move(Direction(DC[bestDir]));
    else {
        std::vector<Direction> dirs;
        for (int d : stepDirs) dirs.push_back(Direction(DC[d]));
        ct.make_moves(dirs);
    }
    nextHead = simBody[0];
    nextFacing = stepDirs.back();
    predicted = simBody;
}

} // namespace

int main() {
    auto [ct, game] = fastio::init();
    W = game.width;
    H = game.height;
    N = W * H;
    nbT.resize(static_cast<std::size_t>(N) * 4);
    for (int i = 0; i < N; i++)
        for (int d = 0; d < 4; d++) nbT[i * 4 + d] = at(X(i) + DX[d], Y(i) + DY[d]);
    lastSeen.assign(N, -1);
    pearl.assign(N, 0);
    spawnState.assign(N, 0);
    never.assign(N, 0);
    spawnAt.assign(N, -1);
    spawnObs.assign(N, -1);
    edgeT.assign(N * 4, -1);
    edgeObs.assign(N * 4, 0);
    portalId.assign(N * 4, -1);
    occStamp.assign(N, -1);
    ownStamp.assign(N, -1);
    ownIndex.assign(N, 0);
    otherFree.assign(N, NEVER_FREE);
    dist.assign(N, -1);
    queueBuf.assign(N, 0);
    gapLo.assign(N, 0);
    gapHi.assign(N, 0);
    nearFountain.assign(N, 0);
    prodRate.assign(N, 0.0);
    prodDensity.assign(N, 0.0);
    dispDist.assign(N, -1);
    fountainCluster.assign(N, -1);
    distKing.assign(N, -1);
    preyDist.assign(N, -1);
    targetDist.assign(N, -1);
    exploreDist.assign(N, -1);
    claimD.assign(N, 1 << 20);
    consStart = LAST_ROUND - cfg.consBase - (W + H) / 2; // refined once the map is recognised
    teamIdx = ct.get_team() == Team(Team::A) ? 0 : 1;

    while (fastio::update(ct, game)) {
        try {
            takeTurn(ct, game);
            // One probe ray through the nearest portal on our next head's lines. Echoes come back
            // pooled over every ray sent, so a probing turn sends nothing else.
            probeDir = -1;
            if (cfg.probe && nextHead >= 0) {
                int const d = chooseProbe(nextHead, nextFacing);
                if (d >= 0) {
                    std::uint64_t const pv = cfg.pbEnable && edgeT[nextHead * 4 + d] == 2 && portalId[nextHead * 4 + d] >= 0 ? encodePB(portalId[nextHead * 4 + d]) : 0;
                    ct.send_sonar(Direction(DC[d]), pv);
                    probeDir = d;
                    probeFrom = nextHead;
                    probeRound = R;
                }
            }
            bool const kingMsg = probeDir < 0 && CONSOLIDATE && (R >= consStart - KING_PREELECT || (KING_ELECT_ROUND > 0 && R >= KING_ELECT_ROUND)) && !kingStale();
            bool const preyMsg = cfg.preyHunt && R >= PREY_FROM - PREY_TTL && probeDir < 0 && preyToSend && preyFresh();
            if (kingMsg || preyMsg) {
                // Both to pass on: alternate which pair of rays carries which.
                std::uint64_t const km = kingMsg ? encodeKing(king) : 0, pm = preyMsg ? encodePrey(prey) : 0;
                for (int d = 0; d < 4; d++)
                    ct.send_sonar(Direction(DC[d]), kingMsg && preyMsg ? ((d + R) % 2 ? km : pm) : (kingMsg ? km : pm));
            }
            if (INTEL && probeDir < 0 && !kingMsg && !preyMsg && (!intel.empty() || !foodOut.empty())) {
                // Freshest and longest sightings first; food on the other rays (all four when there is no sighting).
                std::vector<Sighting> order = intel;
                std::sort(order.begin(), order.end(), [](Sighting const& a, Sighting const& b) {
                    return a.len - 2 * (R - a.round) > b.len - 2 * (R - b.round);
                });
                int const k = std::min<int>(4, static_cast<int>(order.size()));
                int fi = 0;
                for (int d = 0; d < 4; d++) {
                    bool const foodRay = FOOD_INTEL && !foodOut.empty() && (k == 0 || (d + R) % 2 == 0);
                    if (foodRay) {
                        Food const a = foodOut[fi % foodOut.size()];
                        Food const b = foodOut[(fi + 1) % foodOut.size()];
                        fi += 2;
                        ct.send_sonar(Direction(DC[d]), encodeFood(a, b));
                    } else if (k > 0) {
                        ct.send_sonar(Direction(DC[d]), encodeIntel(order[(d + R) % k]));
                    }
                }
            }
            if (cfg.pbEnable && probeDir < 0 && nextHead >= 0)
                for (int d = 0; d < 4; d++)
                    if (d != opp(nextFacing) && edgeT[nextHead * 4 + d] == 2 && portalId[nextHead * 4 + d] >= 0)
                        ct.send_sonar(Direction(DC[d]), encodePB(portalId[nextHead * 4 + d]));
            // v52: the queen warns the far side of every portal beside her new head (sent last, so these rays win).
            if (QUEEN_PB && QUEEN_RULES && ct.get_id() <= 1 && nextHead >= 0) {
                bool sent = false;
                for (int d = 0; d < 4; d++)
                    if (edgeT[nextHead * 4 + d] == 2 && portalId[nextHead * 4 + d] >= 0) {
                        ct.send_sonar(Direction(DC[d]), encodeQPB(portalId[nextHead * 4 + d]));
                        sent = true;
                    }
                if (sent) probeDir = -1; // the probe's echoes would be mixed with these rays
            }
        } catch (...) {
            ct.make_move(ct.get_dir());
        }
        unswbc::end_turn();
    }
}
