# Results: what shipped and what didn't

Every candidate was built on the live version and tested against it. **Score** is the candidate's share of points
against the live version (win 1, draw ½) over side-swapped pairs on every ladder map. Under the SPRT, "H1" means it is
better by about 20 Elo with 95% confidence. "H0" means it is not, which is a different claim from "worse". The full
reasoning and data behind each row are in [`notebook/STRATEGY.md`](../notebook/STRATEGY.md), section 0b.

## Shipped (final line, Oct 10–13)

| Version | Change | Evidence | Ladder |
|---|---|---|---|
| v051j | Every ladder map compiled into the bot (walls, portals, pearl timers) | 0.503 over 367 local games | Live Oct 11 |
| v054 | Learned queen home per map, from 2,480 winning top-team games | 0.508 over 248; queen alive at the end 29% vs 26% | Live Oct 11 |
| v056 | Queen sprint search: speed-aware danger map, pearl race, 3-step escape | SPRT inconclusive, 0.527 [0.500, 0.553] over 836 | 140 of 285 ranked games won (49%) |
| v065 | SPSA-tuned constants (10 at once) | SPRT inconclusive, 0.507 over 1,628; total length +5% | 240 of 569 won (incl. duel games) |
| v075 | Endgame giant (copied from a top team) | **SPRT H1, 0.524 over 1,584** | First 55 ranked games: 35 won (64%); rating peak |
| v076 | Space-time arrival at pearl spawns + beam search for long queens | **SPRT H1, 0.528 over 1,408** | Final live version |

v076's queen change had first been tested alone (v070). It was **even in self-play** (0.502 over 1,496), but **ahead in
two ladder duels**: +0.05 ± 0.045, with the queen alive at the end in 38 of 120 games against 29 of 119. That is
another case where the ladder saw what self-play didn't.

## Rejected (selected)

| Version | Idea | Result | Why it failed, as far as the data shows |
|---|---|---|---|
| v057, v057b | Door guards at each map's narrowest choke (min vertex cut / max-flow) | H0, 0.447 and 0.460 | A guard is a farmer lost: total length 110.6 vs 119.1 on door maps |
| v058 | Voronoi pursuit: hunters minimise the enemy queen's escape room | H0, 0.470 | Enemy queen killed no more often (66% vs 67%); chasing cost farming |
| v059, b, c | Queen avoids Tarjan dead ends and corridors | 0.520 undecided / H0 0.432 / H0 0.505 | Most enemy kills happen in the open; leaving her home room got her killed there |
| v061a | Split later (at length 8) for faster sprinting | H0, 0.318 (88 games) | Army size mattered more than speed |
| v062, v062b | Use pearl spawn timers on the 22 maps where the bot otherwise ignored food data | H0, 0.375 and 0.459 | The queen walked after predicted pearls and was shadowed and killed |
| v066 | Max-min (alpha-beta style) check on sprint ends | Identical in all 67 pairs | The existing reach checks already dropped those ends |
| v067 | Penalise each map's known queen death tiles (from 22,903 replays) | H0, 0.499 over 1,232 | Changed play in 27 of 44 pairs, not results |
| v068 | SPSA run 2 on army constants | H0, 0.477 | No gradient; those constants weren't the bottleneck |
| v069 | Dijkstra navigation with danger- and corridor-weighted tiles | H0, 0.490; ladder duel even | Fewer self-inflicted queen deaths, more enemy kills: same total |
| v072 | Escape split (the child's body walls off the corridor) | H0, 0.481 | Killers come at her head, not her tail; the shed segments cost more |
| v074 | Elect a king when the queen was never heard | H0, 0.477 | No king actually grew: every dragon reaching 4 kept splitting |
| v077–v079 | Giant follow-ups (seeding, reverse split, keep everything eaten) | H0, 0.491 / 0.495 / 0.482 | No gain on top of v075 |
| v080 | Looser home leash | Two ladder duels, rejected | Fewer self-inflicted deaths, more enemy kills; queen alive 29/120 vs 34/118 |
| v081 | SPSA run 3 on the giant's constants | H0, 0.475 | The hand-set values stayed |
| v082 | Neural-network queen: an MLP (753 features, 64-32 hidden) trained on the queen moves of the one team measurably better than us at queen survival | H0, 0.459; ladder duel even | 80% held-out move accuracy, but it copied that team's tiny-queen style: ours ended 10.9 long vs 12.8 and lost the round-500 tiebreaks |

## Earlier highlights (Oct 2–9)

- **Threat split (v65):** a threatened long dragon sheds all but its head and escapes from the tail. It scored 0.667
  [0.577, 0.756] against the previous version, one of the biggest single gains of the project.
- **Queen look-ahead and 2-step escape (v037):** offline, on 109 real ladder rams, it turned 24 into safe moves. It
  was kept on a ladder duel of +0.083 ± 0.072.
- **v70c:** it won our internal tournament, then lost its ladder duel by −0.25 ± 0.093 (−2.7 standard errors).
  Results like this are why the internal tournament was later dropped and the ladder duel stayed the judge.

## Where we lost, at the end

Over 350 ranked games of v065:

- Both queens died in 47% of games, and we lost 60% of those. Our total length was larger, but our longest dragon was
  shorter. v075 and v076 targeted this, and the both-dead share won rose from 40% to 50%.
- Queen safety stayed the main gap to the top teams. In an Oct 11 sample, enemies came within 6 tiles of our queen
  on 45% of her turns, against 13–32% for the top teams.
