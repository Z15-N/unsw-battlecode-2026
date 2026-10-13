# Strategy archive (full history to Oct 3, 12:50 AEST): every analysis and experiment, kept for reference. The live strategy is STRATEGY.md.

**Ben's direction (Oct 1):** play aggressively. When we have information about where they are, we send our **baby dragons** to hunt. Meanwhile the **workers keep chilling and farming**. **Abuse sonar, splitting and everything else the game gives us.**
Claude's job: turn that into rules, code and numbers. This file is the source of truth for *what* the bot does; GOALS.md is *why*. Update both when Ben changes direction.

---

## 1. What the data says right now (top-10 vs top-10, Oct 1 11:00–12:10 UTC, 80 games)
- **Both queens died in 77 of 80 games.** Median queen death: **round 37** (25% are dead by round 5).
- Queen killers: walls **63**, head-on collisions **71**, self/no-valid-action **22**.
- So the top teams have **not adapted to the queen rule yet**. A queen that simply survives wins tiebreak #1 against almost all of them. This window closes as they patch, so **queen safety ships first**.

### 1b. Our own ladder games (v24, 207 games to Oct 2 00:30)
- **Both queens die in 183 of 207 games.** So most games are decided by the **longest dragon** at round 500, or by elimination.
- When our queen survives we win **13 of 16**, so queen survival is the jackpot wherever it is possible.
- **Queens are doomed by design on Autarky, Prisoners Dilemma and Slithery Fight.** Each queen spawns facing a 1-wide dead end with kelp on every side, so she can only stall by shedding 2 segments a turn. There, play for the longest dragon and the elimination.
- On Default, Queen of Spades, Trophy and Devil our queen dies head-on around rounds 100–160, **at length 2–3**: v24 lets her split like a starter until round 150. Fix: the queen stops splitting (v26).
- Weakest maps by rating (Oct 1): Autarky 1538, Default 1556, Queen of Spades 1559, Devil 1578.

### 1c. Why v24 loses (Oct 2: 207 ladder games, compared with top-10 replays)
- **How our 99 losses ended:** 42 by elimination, 53 on the longest dragon at round 500 (we win 69 that way).
- **Eliminations are early trade wars**, not endgame feeding: we're wiped out at rounds 41–300 with a peak army of 4–18, almost all head-on deaths. This happens on Trophy (10), Queen of Spades (9), Devil (7), Dilemma (6) and Autarky (5), and never on Portals, Schooltime, Slithery or Trauma.
- **The economy gap starts at round ~50.** We match the top teams' army size until then. After that they keep growing to 30–36 dragons by round 150 (Devil, Portals, Trophy, Trauma) while ours stalls at 15–20.
- **The cause is food, not the army cap.** They eat 20–60% more pearls in rounds 50–150 (Portals by r150: 335 vs our 203; Trauma 144 vs 88).
- In games we lose, the opponent's army is 1.5× ours at round 100 and 2× at round 300.
- **Implication for Ben's plan:** the workers' farming ("chill & kick") is the biggest lever; babies come second. Babies win the longest-dragon tiebreak by trading head-on with their king late, since a head-on collision kills both whatever the lengths.
- v24 deliberately leaves 2-segment stubs to die in one-wide pockets after farming them (~100 self-kills per game). That is by design, and it happens more in our wins than our losses.

### 1d. Mobility: the top teams sprint (Oct 2, 15:00, WORKFLOW step 2)
- Rules (docs/movement.md): a dragon takes its first ceil(L/4) steps of a turn **free**, so a 5–8 long dragon can move 2 tiles a turn, a 9–12 one 3, and so on.
- Share of moves that are multi-step, by dragon length:

  | team | 5–7 | 8–15 | 16+ |
  |---|---|---|---|
  | Cutlery (#1) | 41% | 47% | 59% |
  | horse (#6) | 50% | 51% | 54% |
  | Stockfish | 1% | 2.5% | 0.2% |
  | Sponge | 0.1% | 6% | 7% |
  | our ±50 opponents | 13% | 15% | 28% |
  | **us (v29b)** | **0.0%** | **0.0%** | **0.0%** |

- Cutlery's king on Default grew 7 → 64 from r300: it sprinted on 58 moves in ~50 rounds, ate 7–15 pearls per 25 rounds roaming the whole map, and "shed its head" (2 + long child) to turn around.
- Our king sat in the map centre, ate 2–5 per 25 rounds and never sprinted.
- Copy: long dragons use their free steps to reach food (v44) and to travel towards it (v44b).

### 1e. Rams: the top teams' babies strike smaller heads from 2 tiles (Oct 2, 15:30)
- Head-on kills started per game: Cutlery 34, horse 27, Sponge 24, calc 24, Stockfish 23, us 19.
- Most of theirs are **2-step strikes by a 3–4 long dragon on an enemy head of 2–3**: Cutlery's (rammer, victim) pairs are mostly (3, 2) ×43, (3, 3) ×27, (4, 3) ×15. They pay one segment for the second step, and most of these rams come before round 200 (Cutlery 99 of 169).
- Ours are the opposite: 44% single-step rams by the **shorter** dragon, because `RAM_MARGIN 1` only rams enemies at least one longer.
- v32b's even trades (victims ≥ our length) lost on the ladder. The copy is to strike victims **≤** our length within 2 steps, early, preferably when we outnumber them locally. Next version after v44b.

### 1f. Our queen had no queen rules in half our games (Oct 2, 16:00; Ben: "why is our queen murdered by ourselves")
- `docs/structure.md`: "One team has dragon id 0 and the other has dragon id 1". The server lists either team first. v24 assumed our queen was `id == team index` (A = 0, B = 1).
- **In 327 of our last 652 ladder games the ids were swapped.** There our real queen played as an ordinary dragon: she split, fed the king, walked into dead ends. She survived 4% of those games (18% otherwise), and we won 37% (41% otherwise).
- How the queen died over those 652 games: her own body 152, an enemy ram 125, kelp 120, survived 111, **our own dragons rammed her 43, she ran into our heads 39**, a body 38.
- Fix (v46): `amQueen = id <= 1`; an enemy with id ≤ 1 is their queen; king messages with id ≤ 1 come from our queen.
- On side-swapped pool maps v46 scored 0.575 vs v41 (40 games), with the queen alive at the end 11 vs 1.
- The gate now includes `data/maps_swapped` (half the ladder looks like that).

### 1g. Blind play: we don't explore (Oct 2, 18:00; WORKFLOW step 2; Ben: "the qualifier will use unseen maps")
- **The ranked pool grew from 10 to 17 maps on Oct 2:** Stripes, Tower Defense, Islands, Around UNSW, weakhold, Maze, Australia. That is about 40% of ladder games on maps our bot has no data for, the closest thing we have to the qualifier.
- **They stay unseen on purpose.** They are not in `maps.hpp` (`tools/gen_maps.py` leaves them out). They live in `data/maps_unseen` (with side-swapped twins) and are part of every gate (`--maps unseen`, also in `all`).
- v46's first 12 games there: 4 wins (61% on the old maps), including losses to 1600-rated teams.
  - Opponents ate 2–5× our pearls by round 50: Around UNSW 94–111 vs 18–63; Australia 18–20 vs 14–17 at r50, then 108–124 vs 39–41 by r100.
  - They had 38–49 dragons at round 50 to our 16–28.
- **Cause: exploration.** Share of the map ever seen by round 100, from the replays (`explore.py`): **us 27–39%, them 60–73%** in all 5 games. At round 50 all our dragons were packed into one 20×15 patch by the spawn.
- **Why, in the code:**
  - On an unknown map an unseen tile is worth `EXPLORE` = 0.01.
  - A remembered countdown is worth 0.55, so almost every turn (95%, debug replay) has a nearby target and nobody leaves.
  - Unexplored ground is exactly where pearls pile up: a tile spawns, and the pearl waits until someone eats it.
- **v48: explore on unknown maps.**
  - A dragon values a never-seen tile at the share of tiles that held a pearl when it first saw them (prior 3%).
  - A dragon with no worthwhile target walks to unexplored ground, each in its own direction (id angle plus away from allies in view).
  - It changes nothing on maps the bot knows.

### 1h. Maze: half our dragons idle; the food is in dead-end fountains (Oct 2, 19:00; Ben: "more than half of our dragons ain't doing anything")
- Per 50-round window on Maze (3 ladder games): **46–59% of our dragons eat nothing** and 18–39% keep their head on ≤ 10 tiles. No timeouts. The opponents idle about as much, but they eat more.
- Maze has 2 open home rooms per side. One holds only slow tiles (gap 1–200, ~1.2 pearls a round for the whole room), the other none. **The 30 fountains (gap 1–1) sit at the ends of 3-tile one-wide dead ends** inside the maze.
- Fountain pearls eaten per game (scout replays, gaps from `data/maps_unseen/maze.map`): **Cutlery 436–910, horse 358–461, Cache me outside 423–546; us 9–37.** Mid-table teams get 150–450. Slow tiles: ~400–500 for everyone. The map is new, so these teams farm it blind.
- **How Cutlery does it** (game 863703):
  - A 2–3 long dragon walks into a pocket and eats its 3 fountains.
  - At the end it splits: a 2-segment stub stays, the rest walks out.
  - The stub dies (no valid action), dropping a pearl for the next visitor.
  - 263 visits in one game, so +1 length per visit plus 3 pearls each.
- That is our POCKET play (Autarky/Dilemma), which only ran on known maps.
- **v49:** a tile seen at countdown ≤ 1 in 2 different rounds and never higher is a fountain (a fountain reads 1 every round). Pockets are rebuilt from the walls seen, and pocket farming is on for unknown maps (half the army, as on Schooltime).

### 1i. When a queen dies: what actually happens (Oct 2, 20:30; Ben: "if our queen dies what will we do?", "only real data")
Measured only; no projections. Scripts in `tools/analysis/`.

**Our games.** v46's 134 ladder games, 06:40–09:47 UTC (the only bot active then; `queen_facts.py`, exact lengths from `lab.track`, data in `data/queen_facts_v46.json`).
- We won 72. Our queen alive at the end: 48 games, won 44. Our queen died: 86 games, won 28.
- **Their queen died while ours was alive in 96 of 134 games.** From that moment we only had to keep ours alive.
  - She survived in 38 of them, and we won all 38.
  - She died in 58, and we won 16. An enemy dragon rammed her head-on in 36; she moved into her own body in 19; our own dragon rammed her in 1; other causes 2.
  - Her length when she died: median 3, and 45 of the 58 were 2–4 long.
- Our queen's exact length, averaged over the games she was alive: 2.5 at rounds 25–150, 3.3 at r200, 4.0 at r300, 6.5 at r400, 30.2 at r499 (the endgame feed).
- Our queen died first, or theirs never died: 26 games, won 11. Their queen lived to the end in 7 of those, and we won none.
- Both queens dead and the game reached round 500 (46 games):
  - lost 29: our longest 20.1 vs their 48.0, total 56 vs 170, dragons left 5.0 vs 16.2;
  - won 17: our longest 36.2 vs 19.1.
- Our queen died and we were eliminated: 26 games, won 0.

**Her last turn, when she died after theirs** (`queen_last_turn.py`, same 58 games; positions at the start of her final turn).
- Rammed by an enemy (36; killer identified in 34):
  - The killer was in her 7×7 view in 32 of 34.
  - It was 2 tiles away (Manhattan) in 19, 3 in 7, 1 in 2, and 4–5 in 6.
  - It was 2 long in 16 and 3 long in 11, and it took 1 step in 19 and 2 steps in 8.
  - She had 1 open move in 9, 2 in 13, and 3 in 12.
- Moved into her own body (19): **she had no open move in 18 of them** (all four neighbours were kelp or bodies). Length 2 in 9, 3 in 6.

**How the rammer approached her** (`queen_approach.py`, the 36 rams above). Its distance to her head at the start of her turn:
- two rounds before: mostly 6 (11 of 32);
- one round before: mostly 4 (16 of 33);
- at her last move: 2 (19 of 34).

For a 2-long enemy (reach 2), her move penalty at 3 tiles was 8 and at 4 tiles was 2, against 40 inside its reach. **v53** raised these to 30 and 15, added 5 at 5 tiles, and counted enemies our dragons reported this round, not only the ones in her view.
- **Result: no effect.** 48 local games vs v52:
  - wins 24–24;
  - queen rammed 22 vs 22;
  - queen ran into herself 15 vs 19, within noise.
  - Not shipped.
- **Why, from debug replays** (`analysis/qram_debug.py`, per-move scores in the indicators; 8 rams on the queen):
  - **Unseen approach (2 of 8).** Default r15 and r44: the rammer came from 10 tiles to 2 in four rounds. One round before the ram it was still outside her 7×7 view and nobody had reported it. Her move towards it scored positive.
  - **Cornered (6 of 8).** Queen of Spades ×2, Devil, Trophy ×2, Islands: she saw it at 4 tiles, but every option scored −29 to −140. She was in a corridor or against an edge with 1–2 moves, so penalties had nothing to choose between.
- So the queen needs escape planning, not bigger penalties: move early towards open ground she can reach before the enemy can, and get warning of enemies beyond her view.
- **v54 tried exactly that** and failed. Each of the queen's moves was scored by the tiles she can reach before any enemy within 10 (in view or relayed in the last 2 rounds). In 48 local games vs v52: wins 21–27, queen rammed 24 vs 20, queen deaths 42 vs 42. Not shipped.
- In these local games our queen died in 42 of 48 games for both versions. The opponent there is our own bot, whose babies hunt the queen ("any trade wins").

**Our own dragons killing our queen.** 125 games, 09:48–10:00 UTC (v48b's and v46's duel arms; `friendly_queen.py`). Our dragon rammed our queen head-on 4 times: Portals r83 (v48b), Portals r192, Trauma r53, Trauma r257 (v46).
- All 4 were the same move. The queen (id 0/1, she moves first in the round) ended beside a portal. Then one of ours, on the far side, stepped through blind and came out on her head: (8,2)→E landed on (23,14), (31,16)→E on (37,23).
- The "portal busy" warning built for this in v14 is switched off (`PB_ENABLE = false`).
- **v52:** the queen sends a warning through every portal beside her new head. Sonar from a lower id arrives in the same round, so the dragon on the far side hears it before it moves, and crossing costs 200.

**Top-10 teams** (scout.db; top 10 of the 08:06 UTC snapshot; `queen_after.py`).
- Their queen died in 4,383 of their games, and they won 66% of those.
- When their queen died and the opponent's lived to the end: 256 games, won 0.
- After the opponent's queen died first, their own queen survived in 443 of 2,166 games (20%). They won 76% of those 2,166 games.
- Both queens dead at round 500: their longest 45.5 vs 33.8, total 124 vs 97.
- Replays of 2,072 of their queen deaths in rounds 40–360. The other queen was already dead in 987 (48%), died later in 882 (43%), and lived in 203 (10%).
  - Of the 882 later deaths: rammed by the top team 424; the queen moved into kelp, a body or a head, or had no valid action, 432; rammed by her own team 26.
  - Median 60 rounds after their own queen died.
- Before and after their queen died, compared with same-map games where it lived at least 120 rounds longer (40 rounds before / 40 after / rounds 40–120 after):

  | | before | after | 40–120 after |
  |---|---|---|---|
  | head-on rams per 10 rounds | 0.60 | 0.94 | 0.94 |
  | comparison games | 0.49 | 0.56 | 0.39 |
  | their dragons within 10 tiles of the enemy queen | 1.39 | 1.32 | 0.88 |
  | comparison games | 0.81 | 0.45 | 0.17 |
  | their dragons alive | 17 | 22 | 26 |
  | comparison games | 13 | 16 | 14 |

- **v52 on the ladder:** 0 friendly queen kills in 104 games from 12:02 UTC (up to 30 of them are v48b's duel games against the dev bot), against 4 in 125 before. At the old rate we'd expect 2–3, so this is encouraging, not proof.
- **Ben's replay reports, checked (Oct 3, 11:15–11:40 AEST; ranked games 20:14 UTC Oct 2 → 01:20 UTC Oct 3, v63c–v66; `analysis/queen_escort_endgame.py`, `analysis/queen_portal_kills.py`):**
  - **"On small maps / Maze our queen roams alone and gets assassinated" — supported on small maps.** Small maps (≤ 1024 tiles) and Maze, 18 games where an enemy rammed her: at her last turn none of our heads was within 3 in **78%**. In games she survived, she was that alone on 58% of her turns (r1–300). On large maps there's no link (60% at death vs 68%). Escorts must stand off: our heads beside her caused 26 of 53 self-collisions.
  - **"Merge the worms into the queen late" — partly.** With her alive at r400 (53 games) she grows 6.8 → 21.5 (r450) → 30.2 (r499). We have 41 dragons at r400, and only 5.7% of our dragon-turns in r400–500 eat.
    - Both queens alive at the end: 11 games, **won 7**.
    - 2 losses were on queen length by 3 and 5 (Autarky 39 vs 42, Slithery 32 vs 37). 2 more were on Schooltime, where both queens ended at length 3 (no feeding at all) and longest dragon decided (30 vs 48, 3 vs 65).
    - Counter-point: a death drops ceil(L/2), so feeding converts only part of a worker (Ben, Oct 3: a 3-long drops 2; 2 → 1, 3 → 2, 10 → 5, so short worms convert better); v42 (feeding from r300) lost 0.383 vs v41. Feed harder only when the enemy queen is known alive late; find why Schooltime never feeds.
    - **Schooltime game 910428** (lost; queens 3 vs 3, longest 30 vs 48): our queen sat in her corner at (2,1), length 3, from r300 to r500. Our army fell from 63 dragons (r300) to 14 (r499), but the nearest dragon moved away (6 tiles at r420, 15 at r450, 20+ at r480) while another dragon grew 11 → 30. **The feeding went to a different king.** **Confirmed** (king messages decoded from the replay, r380–500): our dragons sent 17,254 king messages. Only 474 named the queen, exactly the ones she sent herself; nobody relayed her. The other 16,780 named another dragon. `considerKing()` adopts a queen message at once, so **her rays never reached anyone**: she was in a corner, kelp around her, the army far away. Fix to design: either she goes to the army before the feeding, or the feeders come to her (on known maps her spawn tile is known).
    - **Systematic on Schooltime, every version since at least v52** (`analysis/queen_king_reach.py`, ranked games 06:32 UTC Oct 2 → 01:22 UTC Oct 3, our queen alive past r450):
      - all 20 Schooltime games: **0 relayed king messages named her, and she ended at length 3** (won 10, lost 10);
      - other maps: 50–100% name her in most games, but low in some (Australia 12%, Tower Defense 13%, Trauma 21%, weakhold 21%);
      - since 20:14 UTC: 26 of 78 games where the army mostly crowned another dragon.
    - Locally (v67 vs v67, Schooltime, 4 seeds) the army does name her (9,142 vs 2,264), so self-play doesn't reproduce it.
    - Ben: the qualifier is on unseen maps, so the fix must be general: a queen cut off from her army, not a Schooltime patch.
    - Two wrong guesses first, both corrected: `FEED_MIN_KING` (0, margin −1000) and the `isLong` exemption (only active on Portals) are not the cause.
    - In all 4 Schooltime games of the 11 with both queens alive, ours ended at 3. Feeding a non-queen king is wrong whenever both queens are alive, since queen length is the first tiebreak.
  - **"A shrimp came through the portal into our chamber"**: in 60 enemy rams on our queen, the killer never crossed a portal on the killing move; **in its last 5 rounds, 2 of 60** (`analysis/queen_portal_kills5.py`): Queen of Spades r115 (crossed r110), Islands r124 (crossed r123, struck the next round). Real but rare (3%). Follow-up: a wider portal margin for the queen.
  - **"Our worms are scared of the maze; not all fountains found" (vs fandagong, weakhold, game 921098, lost):** we ate 73 (72 from fountains) from 9 of the 22 fountains; our heads visited 125 of 600 tiles. fandagong ate 290 (141 fountains, 108 slow, 41 drops) from 17 of 22 fountains and visited 500 of 600. Our dragons farm the first fountains they find and never explore the rest; one-wide corridors cost room penalties.
- **More of Ben's replay reports, checked (Oct 3, 11:50–12:10 AEST):**
  - **"Our queen went through the map into our worms' heads"** (`analysis/queen_into_ours.py`): 0 cases in 335 ranked games since 12:00 UTC Oct 2. **Counting unranked games too (since 23:00 UTC): 3, all on Portals (r262, r379, r462), each time she stepped north through a portal, blind, onto one of our heads.** 9 more ranked deaths came from her stepping into an enemy head. **v69:** the queen never steps through a portal.
  - **"Our dragons collapse for nothing" (Prisoners Dilemma vs Cutlery, game 922352, lost)** (`analysis/game_sides.py`):
    - us: map covered 29%, ate 26 (2 death drops); deaths 12 rammed, 6 into ourselves, 1 our ram: 47 segments, dropping 27 pearls;
    - Cutlery: covered 62%, ate 78 (12 death drops); 12 its own rams, 17 "no valid action" (its pocket stubs), 1 rammed: 72 segments, dropping 40.
    - Cutlery's losses are deliberate and it eats the drops; ours feed it.
  - **"calc's worms swarm the whole map"** (5 games, lost 0–5, v65). Map coverage, us vs calc: Schooltime 58% vs 76%, **weakhold 22% vs 92%, Autarky 44% vs 99%**, Slithery 69% vs 71%, Australia 71% vs 90%.
    - On weakhold our army was 4 at r100 and 1 at r300, with 27 of 31 deaths into ourselves; calc went 18 → 51 and ate 360 to our 76.
    - On Autarky our army went 16 → 8 → 1; calc 34 → 63, ate 540 to our 81. calc's dragons die into kelp a lot (94 and 115) but keep splitting and spreading.
  - **Self-collision deaths by version** (`analysis/self_deaths.py`, ranked, per game, v46–v52 vs v60u–v65): weakhold 58.7 → 50.6, Maze 187 → 188, Dilemma 27.7 → 19.6, Autarky 32 → 41, Stripes 4.5 → 12.3 (but winning 8 of 14, against 1 of 6). The stall breaker didn't raise them. Most are the 2-segment stubs our own splits leave.
- **Our own heads box the queen in** (Oct 3, 10:10 AEST; `analysis/queen_boxed_live.py`; her four neighbours at her last turn, from her own pre-move view; ranked games only).
  - v52 + v60u (12:00–20:14 UTC): 39 self-collision deaths; **one of our heads beside her in 17**. Neighbours in total: kelp 89, her own body 41, our heads 18, our bodies 8.
  - v63c–v65 (20:14–23:52 UTC): 14 self-collision deaths; **one of our heads beside her in 9**. Neighbours: kelp 31, her own body 13, our heads 10. E.g. Trophy r88: N her own body, E and S our heads, W kelp.
  - She moves first, so a dragon of ours that ended its move beside her takes one of her exits. With her last exit gone, her fallback (never take an ally's head) moves her into herself.
  - **v66:** our dragons pay 4 for ending beside our queen's head, 15 when she has at most 2 free sides. v56's version (3, no tight case) showed nothing locally, where enemy babies, not our crowd, kill the queen.
- **The warning arrives, but a boxed dragon crosses anyway** (Oct 3, 07:35 AEST; `analysis/friendly_queen.py`, 343 games since 17:35 UTC Oct 2 incl. duel games, so v52/v60u/v63c mixed). 3 friendly queen kills, all on known portal maps: Portals r317, Trauma r398, Default r168. All three were blind portal crossings.
  - **In all three the killer had received the queen's warning for that exact portal in that round** (inbox decoded from the replays).
  - The portal was its only move that wasn't certain death. The other three sides were kelp, its own body or an ally's body: Portals N kelp, E own body, S ally body; Trauma N own body, S and W kelp; Default N and E own body, W ally body. So the 200 penalty changed nothing.
  - **v64:** a warned portal is never a move, nor a step of a ram. A boxed dragon splits or dies where it is.
- **But our queen dies more, not less** (Oct 3 00:50 AEST; `analysis/queen_deaths_live.py`; ranked battles only, live windows from `data/releases.json`). Ben spotted it in the replays before I reported it. I had reported only the friendly-kill number, which was misleading.

  | version, window (UTC) | ranked games | our queen died | enemy queen died | killed by enemy / herself / our dragon | won with her alive | won with her dead |
  |---|---|---|---|---|---|---|
  | v46, 06:32–09:47 | 135 | 88 (65%) | 117 (87%) | 54 / 32 / 2 | 43 of 47 | 28 of 88 |
  | v48b, 09:47–12:00 | 80 | 53 (66%) | 63 (79%) | 32 / 21 / 0 | 23 of 27 | 12 of 53 |
  | v52, 12:00–14:40 | 50 | 36 (72%) | 39 (78%) | 22 / 14 / 0 | 13 of 14 | 14 of 36 |

  - The v52 rise (72% vs 65%) is within noise at 50 games (±6% SE), but it is no improvement.
  - **When our queen lives we win 93% (79 of 88 across the three versions). When she dies, 39% (54 of 177).** Her survival is the biggest single factor in our results.
  - "Herself" means she moved into her own body (hitSelf): 14 of v52's 36. In the v46 sample she had no open move in 18 of 19 such deaths (boxed).
  - Her length at her last turn (v52, 36 deaths): 2 in 16, 3 in 11, 4–7 in 8, 11 in 1. Nearest enemy head at her last turn: 1–2 tiles in 21.
- **Everyone's queen dies a lot** (scout.db `game_stats`, ranked games since Oct 1 12:00 UTC, teams with 40+ games, to 12:21 UTC Oct 2). Queen dead before round 500: Cutlery 71.9% (185 games), :3 72.4%, Computers 73.3%, Cache me outside 80.5%, Sponge 86.7%, us 87.6% (105 games against the scouted teams), horse 93.5%, calc 95.9%, WeHaveQuizzes 100%.
- **How the queens that survive live** (`analysis/queen_style.py`; exact bodies from `lab.track`). Us = our 265 ranked games of v46–v52 (06:32–14:41 UTC Oct 2). Them = each team's 80 newest ranked games with a replay (other opponents than ours, so survival rates are not directly comparable; `lab.skills` compares on the same maps).

  | queen | alive at the end | length r51–150 / r151–300 / r301–500 | distance from her spawn r51–300 | ≤1 open neighbour r51–300 | own segments within 2 | enemy head within 4 r51–300 | sprints r301–500 |
  |---|---|---|---|---|---|---|---|
  | us | 33% | 2.5 / 3.3 / 10.6 | 9.6–9.8 | 15–19% | 1.5–1.9 | 14–16% | 0% |
  | **Computers** | **52%** | 2.5 / 2.6 / 5.2 | **4.3–4.6** | **9%** | 0.9–1.5 | 20–26% | 11% |
  | Sponge | 44% | 4.6 / 10.7 / 22.2 | 11.0–12.8 | 18–21% | 1.1–1.6 | 11–17% | 12% |
  | :3 | 39% | 2.9 / 5.8 / 12.6 | 10.5–10.9 | 13–18% | 2.1–2.4 | 17–22% | 25% |
  | Cutlery | 19% | 5.3 / 8.4 / 19.1 | 10.1–11.5 | 26–34% | 1.6–2.2 | 15–16% | 12% |
  | calc | 11% | 2.8 / 2.7 / 2.9 | 6.2–10.4 | 28–49% | 1.8–3.0 | 15–20% | 0% |

  - `lab.skills`: Computers' queen lives 85 rounds longer than ours on the same maps (all maps, 1.7 SE) and 76 longer on the new maps (2.3 SE, "better"). Computers is the teacher for queen survival.
  - What Computers' queen does (traces of games 878326–878328): she peels a 2-segment child every time she reaches length 4, and between pearls she **circles a 2×2 square near her spawn** (Trophy r14–26: (19,13)→(20,13)→(20,14)→(19,14)→…). She stays home in open ground even though enemies come within 4 more often than to ours.
- **When an enemy head comes within 3 of the queen** (`analysis/queen_threats.py`, rounds 1–300, same samples; an episode starts after 5 quiet turns; outcomes within 5 rounds):

  | | episodes per game | queen died | intruder killed by the queen's team | both lived |
  |---|---|---|---|---|
  | us | 2.6 (683) | **9.5%** (by a 2-long 35, 3-long 25) | 1.5% | 76% |
  | Computers | 3.8 (303) | 5.6% | 3.0% | 89% |
  | :3 | 3.1 (246) | 3.7% | 4.5% | 80% |
  | Sponge | 2.7 (217) | 7.4% | 3.7% | 68% |

  - The rest are intruders dying on their own (walls, own bodies, other heads); many are stubs.
  - So per close encounter our queen dies 1.3–2.6× as often as theirs, and our dragons kill an intruder near her half as often.
  - Added 06:35 AEST for the new `lab.skills` queen teachers (Cutlery +132 rounds, Big Bobs Bots +115; us = our newest 200 ranked games 16:07–19:06 UTC, v52 + v60u):

    | | episodes per game | queen died | intruder killed by her team |
    |---|---|---|---|
    | Big Bobs Bots | **6.5** (520) | **1.3%** | 0.2% |
    | Cutlery | 4.3 (343) | 2.9% | 4.1% |

    - Big Bobs Bots' queen (alive at the end in 42 of its 80 games, none dead before r51) roams 10–11 tiles from spawn, stays 3.5–4 long, and has an enemy head within 4 on 21–32% of turns. Drawn episodes (`analysis/queen_episode.py`, Australia r89–93, r135–137): enemy heads 2–3 tiles away don't strike.
    - **Not settled:** her escapes, or opponents that don't hunt queens? Their samples have other opponents than ours.
    - Common opponents only (`analysis/queen_common.py`, 06:47 AEST): just 2 (Peanut Butter, chaoliangUNSW), 15 games each. Our queen died in 6 of 27 close encounters (22%), Big Bobs Bots' in 5 of 60 (8%). Same direction, far too few to call. Redo as data accumulates.
- **v58 = v52 + a home leash for the queen:** she pays 2 per tile she ends beyond 4 tiles (Manhattan) from her spawn tile.

**Boxed in: does our army know who the queen is?** (Ben, 22:55; `analysis/queen_boxed.py`, all 30 deaths in the v46 sample where she moved into her own body).
- What the code does:
  - Other dragons recognise our queen only when she is in their 7×7 view (id 0/1 and our team), or from round 250 through her king messages.
  - They give her no room. The "don't end beside an ally head" penalty only covers allies that move later in the round, and she always moves first.
- Her 4 neighbours at her last turn, in total: kelp 66, her own body 33, **our dragons 20**, enemies 0, free 1.
  - One-wide dead end (kelp on 3 sides): 11.
  - Curled up in a corridor: 3.
  - Corridor whose way out **one of our dragons** blocked: 12.
  - Surrounded by our dragons: 3.
  - So our dragons are part of the trap in 15 of 30.
- The room check flood-fills from the next tile as if she could turn around. A short dragon can't turn in a one-wide corridor.
- **v56:**
  - she doesn't step into a one-wide corridor that ends closed (−60);
  - our other dragons pay 3 for ending next to her head or on the 2 tiles straight ahead of her.
  - **Result: no effect on her deaths, and fewer wins.** 48 games on 8 maps: wins 22–26, into herself 16 vs 18. 32 games on the ladder's boxed-death maps: wins 12–20, into herself 9 vs 11. Not shipped.
- **Four queen-survival candidates failed (v53, v54, v56; v55 was the army).** In local games the queen dies in 80–90% of games for both versions, against 64% on the ladder (v46). Our own bot as the opponent hunts her ("any trade wins"), so local tests may not reproduce the ladder's queen deaths.
- v52 local check: 72 games on 6 portal maps (Portals, Trauma, Default, Schooltime, Autarky, Queen of Spades), v52 vs v48b, both sides. **Neither version's queen was killed by its own dragon**, so the fix can't be measured locally. Wins 35–37 (noise). The ladder is the only place it showed (4 in 125 games).

**Tried and dropped: v51 (queen heartbeat and successor king).**
- The queen sent her king message on one ray a turn, every dragon relayed it, and when it went stale a successor was crowned.
- 4 local games vs v48b, lost 4.
- While the queen was alive, 9–50% of our dragons' turns believed she was dead (Default, Islands, Stripes, Trophy). The relay doesn't reach the whole army.
- On Islands, 31 different dragons acted as king in the 25 rounds before round 250.

### 1j. Learn each skill only from teams that are better at it (Oct 2, 20:20; Ben's rule)
**Rule.**
- Copy a skill only from a team that measurably beats us at that skill.
- A team weaker than us at a skill teaches nothing there, even if it is strong overall. That skill is learned from whoever is better at it.

**Re-check it after every replay analysis** (Ben, Oct 2: "at a point we might even surpass them").
- Run `python -m lab.skills --strategy` after every analysis of replays. The 4-hour refresh runs it too.
- Every run is compared with the previous one. The block below lists which teams stopped or started being better than us at each skill.
- A team that is no longer better at a skill **stops being copied there**.
- History is kept in `data/skills/history.jsonl`, reports in `data/skills/`.

**How it measures** (`lab.skills`).
- Us: our newest 200 ladder games, whichever version was live.
- Them: the top 10 and the teams within 50 Elo, up to 40 recent games each.
- Each of their games is compared with our mean **on the same map**. "Better" means ahead by more than 2 standard errors.
- Limits:
  - They played other opponents than we did.
  - "Eaten" counts turns where the tail stayed put, so eats during a multi-step move are missed.
  - Trades started and win rate are shown in the report but are not skills, so they are never a reason to copy anyone.

The block between the markers is rewritten by every run; edit the text outside it.

**Checked by hand: rams suffered** (Oct 2, 21:10; `analysis/ram_exposure.py`, `analysis/common_opponents.py`; us = our newest 200 games, them = 40 games each).
- Exposure (an enemy head within 2 at the start of a round) is similar: us 5.0% of dragon-rounds, DESTINY 3 3.9%, SSS 4.1%, Cutlery 4.1%, horse 4.7%.
- What exposure costs is not: **we are rammed 6.1 times per 100 exposed rounds, they 2.6–3.6.**
- It isn't turn order. The share of exposed rounds where the enemy moves after us is 53% for us and 47–60% for them, and so is the share of rams by a later mover.
- Against the **same** opponents (only 3–4 shared opponents each, so indicative), rams suffered per game minus ours:
  - DESTINY 3 −18.7 (all 3 opponents agree);
  - Cutlery −13.6 (all 3 agree);
  - horse −15.5 (3 of 4 agree);
  - **SSS +1.6.** SSS's lead in the table came from its opponent mix, so it is not a teacher for this skill.
- **What a dragon does with an enemy head within 2** (Oct 3, 07:40 AEST; `analysis/exposed_moves.py`; non-queen dragons, rounds 1–300, before/after its own move; us = ranked games 12:00–20:14 UTC = v52 + v60u, 145 games; them = 40 newest ranked games each):

  | | exposed turns per game | died head-on that round: shorter / equal / longer than the enemy | when longer: stepped away / kept distance / closer |
  |---|---|---|---|
  | us | **346** | 1.4% / 7.6% / **4.2%** | 75% / 9% / 10% |
  | Cutlery | 238 | 0.8% / 13.3% / **0.8%** | 58% / 27% / 12% |
  | horse | 233 | 2.1% / 15.3% / 3.1% | 67% / 19% / 10% |
  | DESTINY 3 | 364 | 0.6% / 8.1% / **1.9%** | 57% / 25% / 11% |

  - Per exposed turn we die less overall (5.1% vs Cutlery 5.7%, horse 8.7%); their deaths are mostly equal-length trades they choose.
  - **Our extra losses: our longer dragons dying to shorter rammers (4.2% vs Cutlery 0.8%).** We are also exposed ~45% more per game, but **per dragon-turn it is ordinary** (09:55 AEST re-run: us 5.2% of 6,775 dragon-turns a game, Cutlery 4.3% of 5,480, DESTINY 3 5.5% of 6,592, horse 3.2% of 7,320). We simply have more dragon-turns, and DESTINY 3 is exposed more than us yet suffers fewer rams. So it's the reaction, not the exposure. Cutlery's and DESTINY 3's longer dragons keep their distance a quarter of the time.
  - **Why** (`analysis/exposed_episode.py`, Cutlery's first 6 such episodes, Portals): in 3 of 6 the threatened dragon **split** (5 → split 3, 4 → split 2, 6 → split 4). The head end left facing the enemy is 2 long, and the bulk leaves from the tail, facing away. A ram then costs 2 segments, not the dragon.
  - **Split rates** (same method, 08:05 AEST): of exposed turns shorter / equal / longer than the enemy, Cutlery splits 6.8% / 5.7% / **17.8%**, we split 0.2% / 0.0% / **1.8%** (155 games).
  - **v65:** a non-queen, non-king dragon of length ≥ 4 with a shorter enemy head inside that enemy's strike reach, and room behind its tail, splits off all but its 2 head segments. The child moves later the same round (docs/splitting.md).

<!-- skills:begin (lab.skills --strategy writes this block) -->
Run 2026-10-03T12:40: ladder snapshot 2026-10-03T02:09:06+00:00; us = our newest 197 ladder games (2026-10-03T00:30 to 2026-10-03T02:12 UTC, 17 maps); them = the top 10 and the teams within 50 Elo, up to 40 games each since 2026-10-01T12:00, plus 37 teachers of the last 3 runs that left those groups. Better = ahead of us by > 2 standard errors on the same maps.

| skill | us | learn it from (better than us on the same maps, strongest evidence first) |
|---|---|---|
| pearls eaten by r100 | 97.68 | chaoliangUNSW +99.59, Cache me outside +62.61, solo😎 +43.82, Deer Park +42.64, forgot to mention +45.20, WeHaveQuizzes +37.89 and 12 more |
| pearls eaten by r200 | 289.58 | chaoliangUNSW +223.70, ddabap +112.94, forgot to mention +129.03, larp stock zi balls +91.86, Cache me outside +150.42, solo😎 +115.35 and 10 more |
| pearls per dragon-turn r0-200 | 0.06 | chaoliangUNSW +0.04, solo😎 +0.03, Kaizen +0.03, Nitronics +0.02, ddabap +0.02, Z-A +0.03 and 13 more |
| dragons alive r100 | 21.58 | Cache me outside +9.42, WeHaveQuizzes +8.23, Sponge(Albert and Bob) +7.13, calc +8.25, horse +8.22, :3 +8.32 and 7 more |
| map covered by r200 (% of tiles our heads stood on) | 44.58 | larp stock zi balls +17.92, ComTamSuonNuong +15.79, ddabap +18.45, forgot to mention +17.22, CookAgent +11.13, 1234 +20.52 and 19 more |
| kelp/self/no-action deaths per 100 dragon-turns | 1.01 | **nobody better: copy no one here** |
| deaths into a body per 100 dragon-turns | 0.28 | doofenshmirtz good incorporated -0.39, Bot -0.29, aAah -0.35, 龙虎豹 -0.19, Deer Park -0.24, PoGang -0.25 and 26 more |
| head-on trades suffered per game | 34.21 | SilverSamurai -21.62, chaoliangUNSW -21.27, SHINK AI 6500 -21.21, python.io -19.73, Team SKKU -18.96, Bhole Chature -15.47 and 7 more |
| queen death round (500 = lived) | 326.72 | **nobody better: copy no one here** |
| longest dragon at round 500 | 30.91 | Cache me outside +22.39, WeHaveQuizzes +28.48, ddabap +17.61, horse +22.07, forgot to mention +20.63, test4 +18.25 and 5 more |

Changes since the previous run (2026-10-03T11:33):
- 𓎼𓃭𓅱𓂋𓇌 𓏏𓅱 𓂋𓄿 is now better than us at pearls eaten by r100 (+41.04; was no measurable difference)
- WeHaveQuizzes is now better than us at pearls eaten by r100 (+37.89; was no measurable difference)
- larp stock zi balls is now better than us at pearls eaten by r100 (+20.98; was no measurable difference)
- Nitronics is no longer measurably better at pearls eaten by r100 (+31.02): stop copying it there
- 1234 is now better than us at pearls eaten by r100 (+26.04; was no measurable difference)
- WeLikCoding is no longer measurably worse at pearls eaten by r100 (-22.80)
- 龙虎豹 is no longer measurably better at pearls eaten by r100 (+9.04): stop copying it there
- horse is no longer measurably better at pearls eaten by r200 (+66.09): stop copying it there
- 𓎼𓃭𓅱𓂋𓇌 𓏏𓅱 𓂋𓄿 is now better than us at pearls eaten by r200 (+128.07; was no measurable difference)
- WeHaveQuizzes is now better than us at pearls eaten by r200 (+111.15; was no measurable difference)
- larp stock zi balls is now better than us at pearls eaten by r200 (+91.86; was no measurable difference)
- pizza is now better than us at pearls eaten by r200 (+102.88; was no measurable difference)
- 🔴🔵⚪️ is no longer measurably better at pearls eaten by r200 (+52.02): stop copying it there
- Lozer is now better than us at pearls eaten by r200 (+67.35; was no measurable difference)
- WeLikCoding is no longer measurably worse at pearls eaten by r200 (-53.12)
- 𓎼𓃭𓅱𓂋𓇌 𓏏𓅱 𓂋𓄿 is now better than us at pearls per dragon-turn r0-200 (+0.02; was no measurable difference)
- Cache me outside is now better than us at pearls per dragon-turn r0-200 (+0.01; was no measurable difference)
- we love gru is now better than us at pearls per dragon-turn r0-200 (+0.02; was no measurable difference)
- Peanut Butter is now better than us at pearls per dragon-turn r0-200 (+0.01; was no measurable difference)
- dev test 1 :P is now better than us at pearls per dragon-turn r0-200 (+0.02; was no measurable difference)
- forgot to mention is now better than us at dragons alive r100 (+5.86; was no measurable difference)
- SSS is now better than us at dragons alive r100 (+4.88; was no measurable difference)
- WeHaveQuizzes is now better than us at dragons alive r100 (+8.23; was no measurable difference)
- Cache me outside is now better than us at dragons alive r100 (+9.42; was no measurable difference)
- ddabap is now better than us at dragons alive r100 (+5.73; was no measurable difference)
- larp stock zi balls is now better than us at dragons alive r100 (+4.81; was no measurable difference)
- pizza is now better than us at dragons alive r100 (+6.14; was no measurable difference)
- chaoliangUNSW is now better than us at dragons alive r100 (+6.90; was no measurable difference)
- we are now better than doofenshmirtz good incorporated at dragons alive r100 (-8.03; was no measurable difference)
- we are now better than STAR at dragons alive r100 (-5.54; was no measurable difference)
- Sponge(Albert and Bob) is no longer measurably worse at kelp/self/no-action deaths per 100 dragon-turns (+0.25)
- SSS is no longer measurably better at kelp/self/no-action deaths per 100 dragon-turns (-0.24): stop copying it there
- Computers is no longer measurably worse at kelp/self/no-action deaths per 100 dragon-turns (+0.15)
- we are now better than we love gru at kelp/self/no-action deaths per 100 dragon-turns (+0.62; was no measurable difference)
- we are now better than larp stock zi balls at kelp/self/no-action deaths per 100 dragon-turns (+0.42; was no measurable difference)
- EternalWisdom is no longer measurably worse at kelp/self/no-action deaths per 100 dragon-turns (+0.65)
- SilverSamurai is no longer measurably worse at kelp/self/no-action deaths per 100 dragon-turns (+0.48)
- horse is no longer measurably better at deaths into a body per 100 dragon-turns (-0.14): stop copying it there
- we are now better than Cache me outside at deaths into a body per 100 dragon-turns (+0.16; was no measurable difference)
- calc is no longer measurably better at deaths into a body per 100 dragon-turns (-0.09): stop copying it there
- larp stock zi balls is no longer measurably better at deaths into a body per 100 dragon-turns (-0.05): stop copying it there
- Nitronics is no longer measurably better at deaths into a body per 100 dragon-turns (-0.06): stop copying it there
- Lozer is no longer measurably better at deaths into a body per 100 dragon-turns (-0.16): stop copying it there
- 中国人不准飞😡😡😡😡😡😡😡 is no longer measurably better at deaths into a body per 100 dragon-turns (-0.09): stop copying it there
- WeLikCoding is no longer measurably better at deaths into a body per 100 dragon-turns (-0.08): stop copying it there
- EternalWisdom is no longer measurably better at deaths into a body per 100 dragon-turns (-0.15): stop copying it there
- ComTamSuonNuong is no longer measurably better at deaths into a body per 100 dragon-turns (-0.15): stop copying it there
- Cutlery is no longer measurably better at head-on trades suffered per game (-10.00): stop copying it there
- calc is now better than us at head-on trades suffered per game (-13.69; was no measurable difference)
- test4 is now better than us at head-on trades suffered per game (-12.44; was no measurable difference)
- we love gru is no longer measurably better at head-on trades suffered per game (-6.39): stop copying it there
- larp stock zi balls is now better than us at head-on trades suffered per game (-14.16; was no measurable difference)
- pizza is now better than us at head-on trades suffered per game (-13.86; was no measurable difference)
- we are now better than Kaizen at head-on trades suffered per game (+13.65; was no measurable difference)
- POFPOF is no longer measurably better at head-on trades suffered per game (-6.82): stop copying it there
- err404 is no longer measurably better at head-on trades suffered per game (-12.79): stop copying it there
- forgot to mention is no longer measurably worse at queen death round (500 = lived) (-29.05)
- SSS is no longer measurably worse at queen death round (500 = lived) (-54.74)
- we are now better than we love gru at queen death round (500 = lived) (-103.46; was no measurable difference)
- we are now better than doofenshmirtz good incorporated at queen death round (500 = lived) (-111.50; was no measurable difference)
- we are now better than POFPOF at queen death round (500 = lived) (-93.56; was no measurable difference)
- 𓎼𓃭𓅱𓂋𓇌 𓏏𓅱 𓂋𓄿 is now better than us at longest dragon at round 500 (+13.47; was no measurable difference)
- calc is no longer measurably better at longest dragon at round 500 (+8.75): stop copying it there
- 中国人不准飞😡😡😡😡😡😡😡 is no longer measurably worse at longest dragon at round 500 (-8.41)
- we are now better than doofenshmirtz good incorporated at longest dragon at round 500 (-10.71; was no measurable difference)
- 龙虎豹 is no longer measurably better at longest dragon at round 500 (+6.91): stop copying it there
- 3.14159265 is no longer in the comparison (left the top 10 / +-50 group)
- Check Raise is no longer in the comparison (left the top 10 / +-50 group)
- Kamikaze is no longer in the comparison (left the top 10 / +-50 group)
- bread first search is no longer in the comparison (left the top 10 / +-50 group)
- nsw seng is no longer in the comparison (left the top 10 / +-50 group)
- tozoman is no longer in the comparison (left the top 10 / +-50 group)
- 😹 is no longer in the comparison (left the top 10 / +-50 group)
<!-- skills:end -->

Example from the 20:19 run: SSS (#1) was **not** better than us at farming (+10 pearls by r200, within noise). So we learn its survival against rams and its king growth, not its farming.

### 1k. Farming gap = army gap (Oct 2, 22:20; teachers from §1j)
Real data only. Us: our newest 200 ladder games. Them: up to 40 games each since Oct 1 12:00 UTC, on maps we also played.
- **Every team that out-farms us has more dragons at round 100**: 5.6–10.1 more than our 20.9 (lab.skills, same maps).
  - Only three also eat more **per dragon**: dev test 1 :P +0.026, Cutlery +0.017, forgot to mention +0.014 pearls per dragon-turn (ours 0.066).
  - Cache me outside, horse, Sponge and WeHaveQuizzes eat at our rate per dragon; they simply have more dragons.
- **Where the round-100 army comes from** (`analysis/army_growth.py`, per game, rounds 1–100):

  | | splits | deaths | into a body | kelp/self/no action | army r100 |
  |---|---|---|---|---|---|
  | us | 43.4 | 26.7 | 5.1 | 15.3 | 20.7 |
  | Sponge | 45.0 | 21.7 | 2.1 | 13.7 | 26.9 |
  | WeHaveQuizzes | 46.6 | 26.1 | 1.9 | 15.6 | 24.3 |
  | horse | 52.6 | 29.4 | 3.8 | 16.6 | 26.6 |
  | Cutlery | 66.6 | 42.8 | 0.3 | 35.1 | 28.1 |
  | Cache me outside | 65.3 | 42.6 | 9.1 | 26.9 | 26.4 |
  | forgot to mention | 59.8 | 37.7 | 0.5 | 27.2 | 26.0 |

  - Two ways to a bigger army. Sponge and WeHaveQuizzes split like us but lose fewer dragons. Cutlery, Cache me outside and forgot to mention split 40–50% more and lose more; Cutlery's losses are its pocket stubs.
- **Our early body deaths are our dragons boxed in by our own** (`analysis/body_deaths.py`, rounds 1–100, per game):
  - Into the tail of an own dragon that moves later this round: us 2.76, Sponge 0.72.
  - Into the tail of one that already moved: us 1.30, Sponge 0.65.
  - Into enemy bodies: under 0.1 for both.
  - In the cases checked, the dying dragon could see the tail. It had no free neighbour, and the boxed-in fallback (ram an enemy head, else split, else the first direction that isn't an ally head) moved it north into the tail. A 2-long dragon can't split, so a boxed one always dies.
- **Crowding doesn't explain it** (`analysis/crowding.py`, share of heads with an own head within 2, rounds 5–100):
  - us 33.6%, Sponge 20.8%, DESTINY 3 21.5%, Cutlery 28.8%, pizza 28.6%, forgot to mention 32.6%;
  - **tungtung67 40.4%**, the most crowded, yet the best at avoiding body deaths.
  - So the teachers avoid being boxed even when crowded.
- v55a/v55b test the room check: the queen's pessimistic check for every dragon, and other bodies never freeing up in the flood fill. Both were switched off in v14, with no recorded reason.

### 1l. Rating by version and by map type (Oct 2, 23:45; our ranked battles from the API)
- Ladder snapshots: 1717 (rank 44) at 03:53 UTC, **1803 (rank 27) at 08:06**, **1673 (rank 64) at 12:06**. At 13:30 UTC: 1724, rank 42 of 956.

  | version, live window (UTC) | ranked battles | games won–lost | rating change |
  |---|---|---|---|
  | v46, 06:32–09:47 | 27 | 71–64 (53%) | +57 |
  | v48b, 09:47–12:00 | 16 | 35–45 (44%) | −91 |
  | v52, 12:00–17:35 | 21 | 43–62 (41%) | +50 |
  | v60u, 17:35–20:14 | 10 | 24–26 (48%) | +72 |
  | v63c, 20:14–22:38 | 8 | 22–18 (55%) | +29 |
  | v64, 22:38–23:39 | 3 | 8–7 | −48 (Bot 2–3: −42) |
  | v65, 23:39– (to 23:52) | 0 | — | — |

- By map type:
  - v46: old maps 51/80 (64%), new maps 20/55 (36%).
  - v48b: old maps 24/51 (47%), new maps 11/29 (38%).
- **v48b's loss was on the old maps, where its code plays exactly like v46.** On the new maps, the only place it differs, it scored the same as v46. So the −91 isn't v48b's change. It's the opponents it drew (tozoman 5 of its 16 battles, 11–14) or chance; the data can't separate the two.
- **We win 37% of ranked games on the 7 new maps (31 of 84, v46 + v48b) vs 57% (75 of 131) on the maps the bot knows.** The qualifier is on unseen maps.
- **Who is better than us on the new maps** (`lab.skills --maps new`, run 23:55; report `data/skills/maps-new_latest.md`).
  - Us: 192 games on the 7 new maps, 04:33–13:38 UTC (v41, v46, v48b and v52 mixed). Them: up to 40 games each on those maps.

  | skill on new maps | us | teams better | strongest |
  |---|---|---|---|
  | pearls eaten by r100 | 89.7 | 29 | Cache me outside +88, forgot to mention +63, 🔴🔵⚪️ +63, chaoliangUNSW +61, SSS +59 |
  | pearls per dragon-turn | 0.06 | 19 | SilverSamurai +0.07, Cache me outside +0.04, solo😎 / chaoliangUNSW / CookAgent / dev test 1 :P +0.03 |
  | dragons alive at r100 | 23.3 | 22 | forgot to mention +13.9, WeHaveQuizzes +11.9, calc +11.6, SSS +10.9 |
  | trades suffered per game | 38.2 | 11 | POFPOF −23.0, solo😎 −18.5, nsw seng −17.4, y −17.2 |
  | queen death round | 264 | 2 | **Cutlery +81, Computers +76** (on all maps together nobody is better) |
  | longest at r500 | 34.5 | 11 | WeHaveQuizzes +32.5, forgot to mention +31.9, Cutlery +28.0 |

- **Why they out-eat us on the new maps**, narrowed step by step (Oct 3, 00:30). Us: v48b + v52 ladder games from 09:47 UTC. Them: Cache me outside, chaoliangUNSW, solo😎, Cutlery, up to 60 games each on the new maps.
  1. **Not exploration (any more).** Map seen by round 100 (`explore_compare.py`): v46 53.4%, v48b+v52 61.1%, Cache me outside 60.5%, chaoliangUNSW 67.7%, solo😎 65.4%, Cutlery 71.5%.
     - v48b's exploration raised our pearls eaten by r100 from 72.2 to 87.4. Cache me outside, seeing the same share, eats 178.2.
  2. **Not less food around.** Pearls within 3 of a head, rounds 30/50/70/90 (`food_near.py`): us 0.76, them 0.67–0.81. A third of heads have food within 3 for everyone. Eaten per dragon-round: us 0.066, them 0.087–0.109.
  3. **Not speed.** Rounds 1–100 (`move_speed.py`): tiles per move 1.00–1.02 for everyone, mean length 2.3–2.6. solo😎 never sprints and still eats 9.3 per 100 moves to our 6.6.
  4. **It's where we go.** Moves made with a pearl within 3 (`food_chase.py`):

     | | step closer | eat now | eat within 3 moves |
     |---|---|---|---|
     | us | 51.0% | 17.3% | 27.9% |
     | them | 56.4–57.7% | 23.0–27.6% | 35.4–40.6% |

     Two own heads aiming at the same pearl: 47.6% for us, 43.0–51.9% for them (not the cause).
  5. **The skipped pearls are in pockets.** Debug games, v52 on all 7 new maps, 2,022 moves with a pearl one step away (`skip_pearl.py`):
     - ate it 73.4%;
     - skipped because its direction leads into a pocket or dead end (room ≤ 8) 18.6%;
     - skipped for other penalties 1.1%;
     - skipped because the flood fill preferred elsewhere 6.8%.

     A 2–3 long dragon can't get out of a pocket, so the room check rightly refuses. The teams that out-eat us farm pockets: Cutlery goes in short, eats, and splits the rest back out (§1h).
- **Stripes: we starve and get eliminated** (Oct 3, 02:00 AEST; `lab.diagnose --map Stripes`, our games since v46, ranked and duel).
  - **Won 3 of 29; eliminated in 26.** By round 50 we had 1–3 dragons and had eaten 0–5 pearls; they had 5–11 dragons and 14–36 pearls. Ladder rating on Stripes 1587 (1–0–10), our worst map.
  - The map (`data/maps_unseen/stripes.map`): 70 pearl tiles, 42 of them slow (gap 1–500), 16 medium (1–10), 12 fountains (1–1). The fast ones sit in 2–3 tile pockets whose doors are portals (8 portal pairs).
  - Debug replay, v52 vs v52, team A (`experimental/v52dbg`): **both our dragons circled 2×2 squares from round 9 to round 60+ and ate nothing.**
    - The queen's best-valued move (west, towards fountains 3–4 steps away) paid `QUEEN_PORTAL_PEN` (15) for ending beside a portal.
    - Dragon 2's best-valued move (eval 2.3, into a fountain pocket through a portal) paid ~26 for room: only 3 tiles behind the door.
  - **v60 = v52 + `QUEEN_PORTAL_PEN` 15 → 0.5 + stall breaker** (a non-queen dragon that ate nothing for 12 turns on ≤ 4 tiles ignores the room penalty and pays 1 per recently visited tile). 3 was still too much (she still circled), and so was a stall room penalty at 20% (dragon 2 still circled).
  - Stripes, v60 vs v52, both sides, 4 seeds: **15 of 16 (0.938 [0.815, 1.000])**, total length 34–44 vs 0–5, queen alive at the end 7 vs 0.
  - **Stalling is a general habit of ours** (`analysis/stall_share.py`; share of dragon-turns, rounds 1–300, in which the dragon has eaten nothing for 12+ turns with its head on ≤ 4 tiles; us = 265 ranked games v46–v52, them = 80 newest ranked games each):

    | | new maps | old maps |
    |---|---|---|
    | us | 2.53% | 2.58% |
    | Cache me outside | 2.26% | 1.73% |
    | Cutlery | 0.51% | 1.25% |
    | Computers | 0.28% | 1.01% |
    | solo😎 | 0.41% | 0.42% |
    | chaoliangUNSW | 0.06% | 0.12% |
- **The farming gap is conversion, not sight** (Oct 3, 10:55 AEST; teacher = chaoliangUNSW, best in `lab.skills` at pearls by r100 (+94), r200 (+226) and per dragon-turn (+0.04)).
  - Opening, rounds 1–50, the 17 maps we played (`analysis/opening_eat.py`; us = 75 ranked games, v63c–v65): pearls per 100 dragon-turns: us 8.16, chaoliangUNSW 12.68, Cache me outside 10.67, forgot to mention 9.59, solo😎 9.56, Computers 8.16. Dragon-turns per game are similar (us 475, them 381–538).
  - Not timing: pearls are about the same age when eaten (mean 7–9 rounds, 41–49% within 2 rounds of appearing; `analysis/pearl_age.py`).
  - Not split habits: about 90% of everyone's splits are length 4 → 2 + 2 (`analysis/split_habits.py`). They split more because they eat more.
  - Where, rounds 1–100: chaoliangUNSW eats 124 a game on its own half and 63 on the enemy's; us 84 and 28; Cache me outside 85 and 40.
  - Per dragon-turn, rounds 1–100 (`analysis/pearl_view.py`, 40 games each): a pearl in view 58.1% (them 63.6%, 60.9%); nearest pearl adjacent 27% (31%, 28%); **took the adjacent pearl that turn 48% (54%, 51%)**. The three together give them ~1.4× our rate.
  - **v67:** a pearl on the destination is certain (lower ids already moved, higher ids move after us), so the immediate-eat bonus drops the contention discount (0.35–0.7) and rises from 2 to 3.
- **Australia: we don't eat the fast tiles** (Oct 3, 05:45 AEST; `analysis/eat_tiles.py`; gaps from `data/maps_unseen/australia.map`, because replays carry the map with every gap zeroed).
  - Pearls eaten per game, rounds 1–300, by tile type. Us = our 5 ranked Australia games since 06:32 UTC Oct 2; them = 61 games of Cache me outside, chaoliangUNSW, solo😎 and Cutlery.

    | | fast tiles (gap ≤ 10) | slow tiles | no spawn (death drops) |
    |---|---|---|---|
    | us | **10** | 22 | 220 |
    | them | **508** | 246 | 193 |

  - The map has 36 fast tiles in two mirrored clusters, each 13–20 tiles from one side's spawn (ours: x 0–15, y 24–31). Their top tiles are in both clusters.
  - **It isn't navigation.** In self-play (v60u vs v60u, seed 5) each side eats 161–162 on fast tiles, and team A's dragons are within 3 of their cluster on 10–25% of turns from round 50.
  - ~~So on the ladder the opponents take our cluster~~ **(corrected 05:55: wrong).** "Them" are the teams' own games against other opponents, not games against us. In our 5 ranked Australia games (all v46–v52 vs tozoman), an enemy head came within 3 of our fast cluster in only 1. Our dragons got there by round 10 in 1 game, at rounds 140 and 200 in 2, and never by round 200 in 2 (heads sampled every 10 rounds).
  - **Those 5 games are one ranked battle at 08:47 UTC, played by v46**, before v48b's exploration on unknown maps (§1g). v52 in self-play reaches the cluster like v60u (10–25% of turns within 3 from round 50). So this table describes v46 and says nothing reliable about the live line. There are no ranked Australia games of v48b–v60u in the API's last 200 battles. To redo once v60u has some.
- **v57 = v52 + v50b's blind pocket farming** (fountains and pockets learned on unknown maps, half the army farms them; the queen and king never do).
  - **Result: neutral, 0.487 over 112 games vs v52.** It helps on Maze (where the food really is in fountain pockets) and costs on Stripes swapped, weakhold and Tower Defense swapped. Not shipped. Next: find what it does wrong on those three maps, e.g. dragons dying in pockets that hold no fountain.

## 2. How a game is won (rules we optimise for)
1. Our queen alive and theirs dead → **we win**, whatever else happens.
2. Both alive → the longer queen wins. So feed the queen late (§5.4).
3. Both dead → longest dragon, then total length. Avoid this outcome.
4. Elimination ends the game early. Never let the worker count drop to zero.

## 3. Roles
| Role | Who | Job | Never |
|---|---|---|---|
| **Queen** | our id 0 or 1 | survive → grow → eat the endgame sacrifices | trade, split (length is score), end a turn inside an enemy strike range |
| **Workers** ("chill & kick") | most dragons | farm pearls on our side, relay sonar, act as walls around the queen, feed her at the end | pick fights; wander into enemy territory |
| **Babies** (hunters) | split off workers, 3–6 segments | given a target by sonar: rush it and trade head-on, enemy queen first | farm; protect themselves at a target's expense |

Baby size matters because a dragon of length L can strike **ceil(L/4) + (L−2) steps away** in one turn (free steps + paid steps). Length 3 → 2 steps, length 4 → 3, length 6 → 6, length 10 → 11. Babies are kamikazes, so their length is their range.

## 4. Exploits ("abuse everything")
1. **Turn order = assassination.** Dragons act in id order. Queens (0/1) move *first* every round, and our babies (high ids) move *after* the enemy queen with its fresh position. A baby whose strike range reaches the enemy queen's head **always gets the kill** (both die, a 3-segment baby for their whole game).
   - The same applies to us. Our queen ends each turn **outside every enemy head's strike range**, and preferably behind our own bodies (strike paths must be clear).
2. **Symmetry gives free intel.** Maps are mirrored, so at round 0 we know exactly where the enemy queen spawns and where their farms are. The first babies go there blind.
3. **Sonar as radar.** Echoes say what each ray hit (kelp / ally / ally head / enemy / enemy head). With the known map and our own positions, each "enemy" echo pins an enemy to one line segment. Rays from several dragons intersect into positions.
4. **Sonar as a network.** 64-bit messages, 4 directions per dragon per turn, free apart from output bytes. Workers relay fresh sightings outward (flood with a time-to-live and de-duplication), so a sighting anywhere reaches the hunters.
5. **Split + sonar = a briefing at birth.** A ray fired backwards leaves through the tail. Right after a split, the parent's tail touches the child, so the parent can hand the newborn its mission (target x,y, map id, symmetry) **in the same round**. *(to verify in the sandbox)*
6. **Split as escape.** The child leaves head-first from the old tail, facing away. A dragon trapped in a dead end splits and the child walks out.
7. **Death drops are food.** A dead dragon leaves ceil(L/2) pearls along its body. Babies trade near our workers so the workers harvest the enemy's corpse. In the endgame, workers die next to the queen on purpose (§5.4).
8. **Pearl timers are public.** Every visible tile shows its countdown, and mirrored tiles share one. Workers arrive just as pearls spawn, and our side's timers tell us the enemy side's.
9. **Sprinting scales with length.** A long queen takes ceil(L/4) free steps per turn: length 24 → 6 steps. She can eat a line of sacrifice pearls in a few turns.
10. **Portals.** Vision doesn't cross portals, so they're good for ambushes at exits and shortcuts for hunters.
11. **Their sonar hits our dragons too.** We receive their messages. Decoding them (positions in their protocol) or answering with fakes is a later-stage weapon. *(stretch)*

## 4b. Unseen maps (the qualifier)
The qualifier uses maps nobody has seen, so **everything must work without `mapdata.hpp`**:
- Edges and pearl timers are learned from vision and shared over sonar.
- **Symmetry is inferred:** of the three possibilities (mirror x, mirror y, rotate), keep the ones consistent with every edge, timer and spawn observed. Mirrored tiles share pearl countdowns, which is a strong clue. Once known, the enemy queen's spawn and our "home" side follow.
- Territory without symmetry: home = closer to our spawn than to the middle.
- Testing: a generator makes random symmetric maps (sizes 10–64, kelp walls, portals, pearl gaps, spawns), and every release is scored on them as well as on the ladder pool.

## 5. Behaviour spec (v1 target)
### 5.1 Queen
- Each turn, pick a move that (a) is not deadly, (b) leaves room ≥ length (no dead-end traps), (c) ends **outside the strike range of every known enemy head**, using known or estimated lengths (unknown = assume 8 → range 8), and (d) then maximises safe farming.
- Stay in the home zone (our half by symmetry). Prefer cells shielded by our bodies or kelp.
- Broadcast her position every few turns (workers need it for escort and the endgame).

### 5.2 Workers
- Farm on our side using pearl timers, keep a safety margin from enemy heads (lower priority than the queen's).
- Fire sonar every turn: radar rays plus relaying fresh intel.
- Split a baby when (a) we have a target sighting ≤ N turns old within reach of travel, (b) the worker is long enough to stay useful (≥ baby + 3), and (c) the baby cap allows it.

### 5.3 Babies
- Target priority: **enemy queen** > long enemy heads near our queen > long enemy heads near our workers > anything visible.
- Move along the BFS path to the target's predicted head. Strike when in range (§4.1).
- With no target: scout towards the mirrored enemy spawn or farms, and report everything seen.

### 5.4 Endgame feeding (rounds ~440–500)
- Workers converge on the queen's broadcast position. From the round when the queen can still eat everything (pearls ÷ free steps), they die in a line next to her (step into kelp or their own tail on cue).
- Only if our queen is alive. Otherwise workers maximise longest/total length instead (tiebreaks 2–3).

## 6. Sonar protocol v1 (64 bits)
`[16 key | 4 type | 9 round | 35 payload]`
- **key** = hash(team, secret). Drops enemy messages and stale replays of ours.
- **types:** ENEMY_QUEEN(x6 y6 len7 dir2), ENEMY(x6 y6 id7 len7), OUR_QUEEN(x6 y6 len7), PEARLS(x6 y6 count5), TARGET(baby orders: x6 y6 id7), MAP(id6 symmetry2).
- Relay rule: rebroadcast messages younger than T rounds and not yet relayed, at most 2 relays per turn.

## 7. Ladder plan (climbing)
- Oct 2, 09:00: rank 50, rating 1655 (v24). The top 10 are at 1960–2040. v29b (faster early army + late baby hunters) is on ladder trial.
- Ratings are per bot and per map. A new upload inherits the last rating ±75 and moves fast, re-uploading identical code restores its exact rating, and the team rating = overall + **average over the 10 pool maps**. The weakest map costs as much as the strongest earns, so fix the worst map first.
- Volume: autoscrims plus our 12 ranked scrims/hour. After every release, `lab.ladder` (to build) spends the ranked allowance on teams just above us. That converges the rating fast and gives us replays of our bot losing to stronger teams.
- Every one of our games is downloaded and analysed (deaths, queen fate, per map, per opponent). Losses drive the next fix.
- Never ship ungated (GOALS.md checklist). Reactivate the previous version if live results disappoint.
- **Game-format update (Oct 2, 12:22):** autoscrims are now continuous, up to 3 ranked battles (15 games) per rolling hour, against teams up to 50 places either side, fewest-played first. Together with our 12 ranked scrims, a trial gets ~75 ranked games an hour.
- **Ladder trials (Ben approved Oct 2):** each release goes live after the local no-regression gate. `lab.trial` (scheduled every 10 min) spends our 12 ranked scrims an hour on teams rated from 50 below us to 200 above, then after ~60 ranked games keeps the release or re-activates the champion.
- **ELO docs update (Oct 2, 02:06):** a new upload starts from the rating of the submission it takes over from (±75), and switching the active submission moves the team rating to the new one *immediately*. So a ladder trial is reversible at no cost: re-activating the old bot restores its rating at once.

## 8. Build order
| Version | Content | Ship when |
|---|---|---|
| v0 | queen safety + trap-free farming + dead-end split escape | today, ASAP (the window) |
| v1 | sonar protocol, radar, relay, sightings → baby hunters | after v0 is gated |
| v2 | endgame feeding, queen escort/shield | v1 + local tests |
| v3 | per-map tuning from our ladder losses, enemy sonar decoding | continuous |

### 8b. The live line (v24 → …), Oct 2
| Version | What changed | Local | Ladder |
|---|---|---|---|
| v29b | splits from round 0, army cap area/12, babies hunt their long dragons from round 350 | 0.52 vs v24 (423 games) | **+93** (1655 → 1748, 65 games): kept |
| v32b | army cap area/8, babies from round 200, rams take even trades | **0.63 vs v29b** (129 games, proven) | **−49** (1700, 28–37): reverted |
| v33a | pearls in one-wide dead ends are worth nothing where pocket farming is off | 0.45 vs v32b | not shipped |
| v33b | dispersal on Queen of Spades and Trophy | 0.50 (40 games on those maps) | not shipped |
| v32a | v32b without the even-trade rams | 0.52 vs v29b (120) | **−46** (1710, 39–36): reverted. A bigger cap and earlier babies don't help on the ladder |
| v34t | Trophy: half the army walks to the centre (11 tiles = ¼ of the map's pearls) | **0.825** on Trophy (40), gate 0.588 (160) | reverted (−139 over 25 games: one underrated new bot, tozoman, beat us 16–4 in 5 minutes) |
| v37s | Slithery: endgame 50 rounds earlier (their king is 19–24 at r350, ours 4–6) | 0.225 on Slithery (40) | not shipped |
| v40 | **Ben's sonar network**: 4 rays every turn from round 0 with relayed enemy sightings; babies hunt reports 4+ longer | 0.467 vs v34t (60) | — |
| v40b | v40 with babies after targets 2+ longer and 4+ long (they hunt ~6× more) | 0.483 vs v29b (240) | **live on trial** (`--ladder-trial`: Ben wants the network live; self-play can't measure it) |
| v40b (ladder) | — | — | **−130** (17–43 ranked; eliminations on Devil, Dilemma, Trophy): reverted. Babies chasing targets cost us; the top teams only ram at contact range |
| v41 | v40 + food intel: rays also carry pearls and spawn times the sender won't take. Strict babies | gate **0.575** vs v29b (120), unseen 0.59 | **duel vs v29b: 0.383 vs 0.383** over 60 paired games: **kept, live champion (Ben's sonar on)** |
| v42 | v41 + feeding ramp from r300 (a share of the army feeds the king early, like Cutlery) | 0.383 vs v41; king 25.5 vs 29.6 | not shipped |
| v43 | v41 + the army leaves the king's food from the election (r250) | 0.400 vs v41 | not shipped |
| v34q | same pull for Queen of Spades' beds | 0.475 on QoS (40) | not shipped |
| v35 | king feast: the king sprints through the drops (free steps) | 0.45 on Slithery (40); king 45 vs 49 | not shipped (debug later) |
| v44 | v41 + sprint-forage: dragons of 8+ take free-step paths to pearls a single step can't reach | 0.483 vs v41; king 28.2 vs 28.6 | not shipped (fires rarely) |
| v44b | v44 + roaming: dragons of 12+ travel on free steps towards their food target | **0.517** vs v41 (pool 0.55); king 30.1 vs 29.4 | **this hour's version** (WORKFLOW step 5–6) |
| v44c | v44b from length 6 | 0.517 vs v41 but pool 0.30 | not shipped |
| v44b (gate) | — | gate 0.542 vs v41 (120) | not shipped: 12 harness crashes in the smoke test while the machine was overloaded (now retried once) |
| v45 | v44b + the top teams' baby strikes (≤ our length, 2 steps, before r200, outnumbering them) | 0.450 vs v44b | not shipped |
| v46 | v41 + **queen-id fix** (STRATEGY 1f) | swapped maps 0.575, queen alive 11 vs 1; gate 0.530 (200, all 40 maps) | duel −0.033 ± 0.082 (noise): **live champion** from 16:40 |
| v47 | v46 + the queen avoids one-wide corridors (Devil) | Devil 0.512, queen alive 10 vs 10 | not shipped |
| v48a | v46 + unexplored tiles worth the first-sight pearl rate; explore when no target (unknown maps only) | new maps 0.455 (56) | dropped: a remembered countdown still always won |
| v48b | v48a + exploring beats a target worth < 0.15 after discount | **new maps 0.714 [0.60, 0.83]** (56): Around UNSW 7/8, Islands 7/8, Tower Defense 7/8, Australia 6/8, Maze 5/8, weakhold 5/8, Stripes 3/8 | gate on new + generated maps (known maps unchanged) |
| v49 | v46 + fountains learned from countdowns, pocket farming on unknown maps (STRATEGY 1h) | Maze: fountain pearls 127 / 214 vs v46's 54 / 15 (2 games, 1-1) | merged into v50 |
| v48b (gate) | — | gate 0.518 [0.464, 0.572] vs v46 (328 games: new maps 0.566, generated 0.469); clone smoke 0.904 = 0.904 | uploaded 09:47 UTC as a trial; **duel vs v46: 0.467 vs 0.500, diff −0.033 ± 0.082** over 60 paired games (noise): kept, live |
| v50 | v48b + v49 | **0.406** [0.233, 0.579] vs v48b (32 games on Maze, weakhold, Tower Defense, Stripes): pocket farming pulled our queen into dead ends | not shipped |
| v50b | v50 + the queen and king never farm pockets | built, not yet tested | — |
| v57 | v52 + v50b's blind pocket farming (STRATEGY 1l: on new maps 70% of the adjacent pearls we skip are in pockets) | screen vs v52 on the new maps + swapped twins: **0.487 [0.394, 0.579]** (112). Maze 5/8 (total length 103 vs 84), but Stripes swapped 2/8 (13 vs 41), weakhold 3/8 (29 vs 50), Tower Defense swapped 3/8 (33 vs 59); Australia identical (never fired) | not shipped |
| v51 | v48b + queen heartbeat, successor king, short dragons hunt their queen (STRATEGY 1i) | lost 4 of 4 vs v48b; 9–50% of turns thought the live queen dead | dropped |
| v52 | v48b + the queen warns our dragons through portals beside her (STRATEGY 1i) | 72 local games on portal maps: no friendly queen kills for either version (not measurable locally), wins 35–37; gate vs v48b 0.500 after 216 games | gating |
| v53 | v52 + the queen keeps small enemies 1–3 tiles beyond their reach, incl. relayed sightings (STRATEGY 1i) | 48 games vs v52: wins 24–24, queen rammed 22 vs 22 (no effect): unseen approaches and corridors | not shipped |
| v52 (ladder) | — | gate 0.502 vs v48b (432 games: pool 0.506, new 0.500, generated 0.500); smoke 0.867 = 0.867 | live 21:50 as submission 14908. Duel vs v48b: 0.533 vs 0.500, +0.033 ± 0.112, **only 30 pairs** (dev bot games; the server refused the other battle requests): kept |
| v54 | v52 + queen escape planner: each move scored by the tiles she reaches before any enemy within 10 (seen or relayed) | 48 games vs v52: **wins 21–27, queen rammed 24 vs 20**, queen deaths 42 vs 42 | not shipped |
| v55a | v52 + the pessimistic room check for every dragon (STRATEGY 1k) | 48 games vs v52: deaths into bodies by r100 2.2 vs 4.6, kelp/self 6.3 vs 13.0, but splits 39.6 vs 48.6: army r100 29.2 vs 28.8; wins 22–26 | not shipped |
| v55b | v55a + other bodies never free up in flood fills | 48 games vs v52: body deaths r100 2.0 vs 4.3, kelp/self 6.5 vs 14.0, splits 40.6 vs 49.5: army r100 30.6 vs 29.7; wins 25–23 (neutral) | not shipped |
| v58 | v52 + home leash: the queen pays 2 per tile beyond 4 from her spawn (copied from Computers, STRATEGY 1i) | screen vs v52, all 54 maps both sides: **0.472 [0.378, 0.567]** (108), pool 0.529. **Queen alive at the end 28 vs 14.** But wiped out (total length 0) on 5 generated maps; on 4 bad maps (16 games) army r100 10.1 vs 17.2, splits 18.1 vs 25.9: until r150 the queen is one of our army's growers, and the leash keeps her off food | not shipped |
| v60 | v52 + `QUEEN_PORTAL_PEN` 15 → 0.5 + stall breaker (STRATEGY 1l, Stripes) | Stripes 15/16 (0.938); all 54 maps **0.477 [0.383, 0.571]** (108), pool 0.522; losses on Default 1/4 and Portals 1/4 (known portal maps) and some generated maps | not shipped; v60u = the same only on unknown maps |
| v60u | v60's two changes on unknown maps only (known maps play exactly like v52) | screen vs v52 on the 7 new maps + swapped twins + 20 generated, 2 seeds both sides: **0.551 [0.468, 0.635]** (136), new ladder maps 0.589; Stripes 8/8 (total length 47 vs 0); queen alive at the end 22 vs 13; gen_1_9 0/4 (there queen 0 is rammed at r1 in every game, both versions). Gate vs v52 on unseen+gen: **0.515 [0.455, 0.574]** (272; new maps 0.536, generated 0.500), clone smoke 0.900 vs 0.883, max CPU 20M | **live 03 Oct 03:35 AEST (17:35 UTC Oct 2) as submission 15140** (gate verdict "trial"). Duel vs v52 (3 ladder teams + dev bot, 17 maps, 60 pairs): 0.517 vs 0.500, **+0.017 ± 0.084** (noise): kept. **Stripes 3/4 vs 0/4.** On known maps (identical code) the arms differ by up to 2 of 4 (Default 3 vs 1, Slithery 3 vs 1): that is the duel's noise per map |
| v61 | v60u + bodyguards: our dragons of length ≤ 8 that see our queen ram any enemy head that has her within its strike reach + 1 (STRATEGY 1i: our dragons kill intruders near her 1.5% vs Computers 3.0%, :3 4.5%) | vs v60u, all 54 maps: 0.519 [0.424, 0.613] (108), queen alive at the end 11 vs 10; most maps played identically. Debug count (`experimental/v61dbg`, 16 games on 8 maps): **9 guard rams vs 353 other rams**, our queen still died in 13 of 16. Our dragons are rarely beside the queen when an intruder comes | not shipped (it almost never fires) |
| v62 | v60u + the stall breaker on known maps too (we stall 2.58% of dragon-turns there) | vs v60u on the 10 known maps + swapped twins, 3 seeds both sides: **0.508 [0.419, 0.598]** (120); Autarky 8/12, Schooltime total length 164 vs 123 but 5/12; queen alive at the end 23 vs 27 | not shipped (no measurable gain) |
| v63 | v60u + v58's 4-tile home leash once we have 8+ dragons (the army is built first) | vs v60u, all 54 maps: **0.519 [0.424, 0.613]** (108), non-generated maps 0.559; **queen alive at the end 22 vs 12**; Queen of Spades 3/4 (total length 67 vs 15), weakhold swapped 2/2; but **Trauma 0/4**: both queens lived in all 4 and the leashed one was shorter | not shipped |
| v63b | v63, leash only until r250 | vs v60u: 0.519 [0.424, 0.613] (108), non-generated 0.544; queen alive at the end 17 vs 14; Trauma 3/4 | not shipped (survival gain gone) |
| v63c | v63, leash only until the endgame feeding starts (`consStart`) | vs v60u: **0.528 [0.433, 0.622]** (108), non-generated 0.574; **queen alive at the end 24 vs 12**; Trauma 1/4. Gate vs v60u (live 15140), all maps: **0.502 [0.455, 0.549]** (432), clone smoke 0.883 vs 0.867, max CPU 30M. In the 324 gate games against submission 15140: known pool 0.575 (queen alive 31 vs 19, 120 games), new ladder maps 0.476 (16 vs 12, 84), **generated 0.425** (8 vs 7, 120) | **live 03 Oct 06:14 AEST (20:14 UTC Oct 2) as submission 15223** (gate verdict "trial"). Duel vs v60u (60 pairs): 0.383 vs 0.367, **+0.017 ± 0.073** (noise): kept. Known maps 14 vs 11 of 35, new maps 9 vs 11 of 25 (same direction as the local gate) |
| v63c (ladder) | — | — | **Full live window, ranked only (20:14–22:38 UTC): 40 games, our queen died in 23 (58%)**, vs v52 79 of 105 (75%) and v60u 39 of 50 (78%), about 2 SE: promising, not proven (40 games, opponent mix varies). Won 22 of 40 (55%), 14 of 17 with her alive. First hour (20:14–21:16): 20 games, queen died 65% (v60u 78% of 50, v52 75% of 105), won 11 (55%). Rating: v63c +22 over its first 5 ranked battles (13–12 in games) to 1817, rank 31; v60u had taken it 1723 → ~1795 (+72). Small samples |
| v63k | v63c with the leash only on known maps (unknown maps play like v60u) | dry-run gate vs v63c: **0.493 [0.446, 0.540]** (432), new maps 0.455, generated 0.513, known 0.500 (same code): removing the leash on unknown maps doesn't help, so the v63c-gate split (generated 0.425) was noise | fail, not shipped |
| v64 | v63c + never cross a portal our queen warned about (STRATEGY 1i, 3 ladder friendly kills) | gate vs v63c: **0.500 [0.433, 0.567]** (216; the case is too rare to show locally), clone smoke 0.897 vs 0.882, max CPU 29M | **live 03 Oct 08:38 AEST (22:38 UTC Oct 2) as submission 15288**. Duel vs v63c (60 pairs): 0.383 vs 0.483, **−0.100 ± 0.097** (−1.0 SE; revert below −1.5): kept. The code differs only when a boxed dragon faces a warned portal (~1% of games), so a gap this size is noise, but it is a negative result |
| v70r | v69r + queen makes contact (as v70, without v68's escort) | screening vs v69r | — |
| v69r | v67 + the queen never steps through a portal (as v69, without v68's escort) | screening vs v67 | — |
| v70 | v69 + queen makes contact: from 40 rounds before the feeding, if she hasn't seen one of our dragons for 15 rounds, she drops the home leash and walks to the middle (STRATEGY 1i: Schooltime king messages never named her, queen length 3 in all 20 games) | built on v68: dropped, rebuilt as v70r | — |
| v69 | v68 + the queen never steps through a portal (Ben: 3 deaths on Portals, blind onto our own heads) | built on v68: dropped, rebuilt as v69r | — |
| v68 | v67 + stand-off escort on maps ≤ 1200 tiles (short dragons that see her stay 2–3 tiles away, at most 2) + guard rams (STRATEGY 1i: on small maps / Maze she was alone at 78% of enemy rams vs 58% of turns when surviving) | vs v67, all 54 maps: **0.454 [0.360, 0.547]** (108). **Escort maps (≤ 1200 tiles): 0.417, queen alive at the end 6 vs 14**; large 0.550 (7 vs 4); generated 0.450 (1 vs 7). In self-play the escort more than halves her survival on small maps | not shipped. Against Ben's escort idea: crowding her hurts (with our heads boxing her in 26 of 53 self-collisions) |
| v67 | v66 + immediate eats at full value: no contention discount, bonus 3 (STRATEGY 1l: adjacent pearl taken 48% vs chaoliangUNSW 54%) | screen vs v66: **0.593 [0.499, 0.686]** (108), pool 0.603, queen alive 20 vs 21. Gate vs v65 (v66 had been reverted): 0.505 [0.438, 0.572] (216); pool 0.55, generated 0.525, **new maps 0.41**; clone smoke 0.941 vs 0.912 | **live 12:03 AEST (02:03 UTC) as 15411**. Duel vs v65 (50 pairs, 2 teams + dev bot): 0.48 vs 0.46, **+0.02 ± 0.078** (noise): kept |
| v66 | v65 + keep the queen's exits open: our dragons pay 4 for ending beside her head, 15 when she has ≤ 2 free sides (STRATEGY 1i: our heads beside her in 26 of 53 self-collision deaths) | vs v65, all 54 maps: 0.537 [0.443, 0.632] (108), queen alive at the end 18 vs 21. Mechanism check (`analysis/local_boxed.py`, 48 games each on 8 maps): queen self-collisions with our head beside her **7 → 2**, but queen deaths 36 = 36 (in self-play enemy babies kill her instead) | gate vs v65: **0.514 [0.447, 0.581]** (216), clone smoke 0.926 vs 0.912; live 11:08 AEST as 15379. **Reverted at 11:21 by the old ranked trial (`lab.trial`)**, because I did not start its duel. That trial spent 12 ranked scrims on teams up to 200 above us and compared v66's 10-minute rating (1782 after 68 games, 53–75) with v65's settled 1927. Not a fair judgement. Releases are now marked 'awaiting duel', which `lab.trial` ignores. v66's change is inside v67, which the duel judges instead |
| v65 | v64 + threat split: a threatened longer dragon sheds all but 2 head segments (STRATEGY 1j, Cutlery splits 17.8% of such turns, we 1.8%) | 4 local games: 152 threat splits (38 a game). Screen vs v64, all 54 maps: **0.667 [0.577, 0.756]** (108; proven better in self-play), pool 0.632, queen alive at the end 28 vs 13; Default 4/4, Portals 4/4, Devil 3/4; v64 wiped out on 5 generated maps where v65 thrived (gen_1_13 285 vs 0, gen_1_14 293 vs 0); losses weakhold 0/2, Maze 0/2, gen_1_7 0/2, Trauma 1/4. **Gate PASS** vs v64 (the 108 games, interval above 0.5; new maps 0.643, generated 0.725), clone smoke 0.912 = 0.912, max CPU 29M | uploaded 09:06 AEST as submission 15299. **Mistake:** that replaced v64 after 28 minutes, against WORKFLOW's 1 hour (the gate reused the screen games and passed at once). v64 was re-activated at 09:07, and **v65 went live at 09:39:10 AEST (23:39 UTC)**. Duel vs v64 (60 pairs): 0.483 vs 0.450, **+0.033 ± 0.075** (noise): kept. On the ladder its threat split fires ~26 times a game (516 `TSPLIT` indicators in its first 20 ranked games; Cutlery splits ~24 times a game when exposed). **First 20 ranked games (23:39–00:50 UTC): our queen died in 9 (45%), won 16 (80%)**: 11 of 11 with her alive, 5 of 9 with her dead. Small sample. (v64's window, 15 ranked games: queen died 10, won 8.) `lab.release` now waits for the live version's hour before uploading |
| v58b | v58 with the leash only from r150 (after the queen stops splitting) | 0.500 [0.405, 0.595] (108), queen alive at the end 14 vs 12 (no effect) | not shipped |
| v58d | v58 with a 7-tile leash | 0.537 [0.443, 0.632] (108), queen alive at the end 17 vs 18 (no effect); wiped out on Queen of Spades 0/4 | not shipped. The leash only saves the queen when it is tight and early, and that costs the army |
| v56 | v52 + the queen avoids one-wide dead ends; our dragons give her room (STRATEGY 1i) | 48 games vs v52 (8 maps incl. Dilemma and Slithery, where queens spawn in dead ends): wins 22–26, queen into herself 16 vs 18, deaths 41 vs 39 (no measurable change). Rerun on the ladder's boxed-death maps (Islands, Tower Defense, Portals, Trophy; 32 games): **wins 12–20**, queen deaths 28 vs 27, into herself 9 vs 11, into a body 7 vs 4 | not shipped |

**Evaluation, from Oct 2 14:38: `lab.duel`.**
- The candidate and the champion play the same 3 ladder teams plus the dev bot, on all 10 maps, unranked. Pairs are compared.
- Ranked trials compared a fresh rating with a settled one against stronger scrim opponents: every candidate lost 40–140 while the champion itself slid 1755 → 1717.

**Study, 14:00 (`lab.study`, top 10 vs us):**
- Kings: top teams' longest dragon is 10–50 at r400 and 19–61 at r499; ours is 9 and 29.
- Their kings grow by **eating**, not by sacrifices: only 2–27% of their deaths are within 3 of their king (ours 5–70%).
- Sonar volume isn't what makes a top team: #2 Cache me outside fires 0.1–0.8 rays per dragon-turn.
- Their rams are mostly by an equal or longer dragon (70–80%); 64% of ours are by the shorter one.

**Benchmark (Oct 2): `dev test 1 :P`**, an organisers' bot rated 1827:
- v29b scores 0.30 over 60 unranked games. It wins 0/6 on Slithery, Queen of Spades, Trophy and Dilemma, and 5/6 on Portals and Trauma.
- Trophy: they take the centre fountain by round 20.
- Queen of Spades: they farm our edge beds across the wrap.
- Slithery: we out-eat them, but their king ends 43–68 to our 24–46.
- Dilemma: a melee from round 1 (the spawns are interleaved).
- Unseen maps: the fountain pull uses map knowledge. A version that learns rich tiles from observed pearl timers is still to build.

**Lesson (v32b):**
- Self-play can point the wrong way. v32b beat v29b 0.63 locally and lost on the ladder, which is why every release faces a ladder trial.
- Even trades cost us. We started 77 head-on trades a game on Schooltime (won 2 of 8) and 45 on Slithery (0 of 5).
- Ben's aggression means **favourable** trades only: a small baby against a much longer dragon.

### 8b'. Sonar: what the replays say (Oct 2, Ben: "I can barely see any sonar on the replay")
- Sonar rays per dragon-turn:

  | rounds | v29b | 3.14159265 | calc | Stockfish | Sabotage-d | Sponge | WeHaveQuizzes |
  |---|---|---|---|---|---|---|---|
  | 0–200 | **0.03** | ~3.8 | ~3.95 | ~3.9 | ~3.9 | 0.1 | 0.6–1.1 |
  | 200–500 | 1.9–3.8 | ~3.7 | ~3.95 | ~3.9 | ~3.9 | 1.4–2.9 | 1.0–1.8 |

  Four of the top six fire all four rays every turn from round 0.
- **v40 does it too:** 2.9–4.0 rays per dragon-turn all game, carrying enemy sightings (id, head, length, round), relayed for 6 rounds. Babies (¼ of the army) use them to hunt.
- 3.14159265's messages: the top byte is always 0xA7, bits 20–21 are always 0, and two values make up 27% of the traffic (heartbeats?). Bits 22+ read as a tile index match one of their own heads 23% of the time (chance ~8%), so they probably broadcast their own positions. Decoding further, and reading their rays when they hit us, is a later weapon.

### 8c. Next big build: sonar intel for unseen maps (qualifier)
Every dragon is its own process. A newborn child knows nothing, so on an unseen map map-knowledge features like the fountain pull, symmetry and pocket lists don't work. Fix it with Ben's sonar (§4.3–4.5, §6):
1. **Birth briefing:** right after a split the parent sends a backwards ray through its tail into the child. It carries the symmetry, the map's hash, and the richest tile known.
   - **Verified Oct 2** (`experimental/brief_test`, sandbox): the child gets it on its first turn in 88/213 growth splits on Default and 21/54 on Trauma (~41%).
   - The ray leaves the tail in a straight line, so it misses when the old body bent at the split point.
   - To do: the parent picks a ray that hits a child segment (its old body tells it where), and retries the next turn.
2. **Rich-tile beacons:** dragons that see a tile respawn fast broadcast it, and others relay with a time-to-live.
3. **Learned fountain pull:** a share of the army walks to the richest broadcast tile, as v34t does on Trophy with built-in data.
Test on the generated maps (`--maps gen`) against the champion and the dev benchmark.

## 9. Open questions for Ben
- Baby size: cheap (3) or long-range (6)? Default 4, then tune by arena results.
- How many hunters at once? Default ≤ 25% of our dragons.
- Should the queen ever leave the home zone to chase pearls when no enemy is around?
