# Workflow: one loop per release (Ben, Oct 2)

**Re-read this whole file at the start of every version, before anything else** (Ben, Oct 3: "Always read workflow before each version of bot"). Say in the version's first message that it was read.

Claude follows this loop for every version. Every version gets **at least 1 hour live** before the next one is published, and every version must carry an improvement that comes from the refined strategy (step 4). [GOALS.md](GOALS.md) is the why, [STRATEGY.md](STRATEGY.md) is the what, and this file is the how.

**Full hard code (Ben, Oct 10-11: "No need for unseen maps, we go on full hard code"; "don't forget our hard code and new workflow").**
- Every version carries the data of every current server map (walls, portals, pearl timers). Before each version, re-fetch `/maps` into `data/maps_current/` and regenerate maps.hpp with `tools/gen_maps.py` (new maps get swapped twins in `data/maps_new/`).
- There is no held-out or unseen map set any more: local gates and screens play all current maps (`--maps current`).
- The baseline is the last hard-code version (v051j = 21958 from Oct 11). Never duel against, revert to or re-activate a non-hard-code version (v050 or older).
- **Gate with SPRT** (Ben, Oct 11: "find the best algorithm we can use"): `python -m lab.sprt <cand> --against <last hard-code version>` (pairs on all current maps, H0 +0 / H1 **+20** Elo (Ben, Oct 11 ~00:20: lowered from +40 so small real gains can ship), alpha = beta = 0.05, max **1600** games). H1 accepted = better (release); H0 accepted = not better (no release); inconclusive at 1600 = treat as "not worse" (release only with a mechanism gain, step 5). A change that only acts on some maps may be gated on those maps (both sides), its other maps shown identical. Constants are tuned with SPSA (`lab.spsa`, when built).
- Ranked battles may be requested freely (Ben, Oct 11): `POST /battles {"teamId", "ranked": true}`, no map picks (random maps, 5 games each).

## 1. Read the strategy
- Read [STRATEGY.md](STRATEGY.md) in full, plus [GOALS.md](GOALS.md).
- Ben's direction comes first: sonar network, babies hunting on information (favourable trades only), workers that keep farming. Copying top teams is welcome. Our own old versions are not the model.

## 2. Analyse the replays: top 10 and every team within 50 Elo of us
The data is refreshed every 4 hours by the scheduled `lab.refresh`. Run `python -m lab.refresh` by hand if `data/refresh_status.json` is more than 4 hours old.

| Where | What |
|---|---|
| `data/scout.db`: tables `games`, `ladder`, `teams`, `game_stats` | every game of the top 10 and the ±50 teams; per-team, per-game stats |
| `data/replays/<game>.replay` | the replays themselves (48 h kept; our own games kept for good) |
| `data/study/latest.md` | `python -m lab.study`: top 10, the ±50 group and us, behaviour by behaviour (sonar, army, eating, splits, spacing, sprints, rams, king growth, openings) |
| `python -m lab.diagnose` | our live bot's games: per-game timelines, rams, eliminations, per map; `--boards 200,250` draws the board |
| `python -m lab.ladder status` | rating, rank, per-map ratings |
| `data/arena.db`, `data/duels.json`, `data/releases.json`, `data/dev_bench.json` | local games, ladder duels, release log, benchmark results |
| `opponents/clones/` | imitation bots of the top 10 (rebuilt every refresh) |

| `data/skills/latest.md` | `python -m lab.skills`: who is better than us at which skill, on the same maps (see below) |

**Check our rating before every analysis** (Ben, Oct 3: "we are 1927 and you're still fighting 17xx elo").
- Our team rating is `/team` → `team.elo` (the ladder's number). It is not the live submission's rating.
- The ±50 group must come from today's rating. `lab.skills` checks it on every run and re-scouts (fresh ladder snapshot, plus the new group's games and replays) when the snapshot is over 2 hours old or we have moved more than 25.
- Ad-hoc analyses state the rating and the snapshot they used.
- **Every 30 minutes** (Ben, Oct 3) the scheduled task `battlecode-elowatch` (`python -m lab.elowatch`) logs our team rating and the live submission to `data/elo_history.jsonl`, and re-scouts the top 10 and the ±50 group from today's rating. Before publishing the next version, read `python -m lab.elowatch --show` to see how the live one moved.

Questions to answer before every version:
1. Where do we lose (maps, eliminations, the longest-dragon tiebreak) and what changed since the last version?
2. What do the top teams do there that we don't? Measure it, don't guess: draw the board, trace a dragon, compare the numbers.
3. What do the ±50 teams do to us (rams, openings, sonar)?

**Learn a skill only from a team that is better than us at that skill** (Ben, Oct 2).
- **After every replay analysis, run `python -m lab.skills --strategy`.**
  - It re-measures who is better than us at what and rewrites the skills block in STRATEGY.md.
  - It lists what changed since the last run: a team we have caught up with stops being copied at that skill (Ben: "at a point we might even surpass them").
  - The 4-hour refresh runs it too.
- Read its "who to learn each skill from" list before choosing what to copy.
- A skill is something measured: farming (pearls eaten, pearls per dragon-turn), army growth, navigation deaths, rams, queen survival, longest dragon.
- `lab.skills` compares each team with our live line **on the same maps**. A team counts as better only when it beats us by more than 2 standard errors.
- A team that is weaker than us at a skill is not copied there, even if it is strong overall. Learn that skill from the teams that are better at it.

**Only real data** (Ben, Oct 2: "only tell me what actually happens, DO NOT LIE").
- Every number written down or reported comes from a run on a stated sample: games, time window, bot version.
- Fix the sample before counting: don't mix pulls taken at different times.
- When an earlier number turns out wrong, correct it and say so.
- **Report the bad numbers with the good ones.** A fix's own metric never goes out without the outcome it serves. Example (Oct 3): "0 friendly queen kills in v52's 50 ranked games" was true but misleading on its own, because our queen still died in 36 of those 50 (72%, worse than v46's 65%). Every status report includes the queen death rate and the win rate of the live version, from ranked games only.
- Ranked games only for a live version's numbers. Unranked duel battles mix the candidate and the champion.

Write the findings down (step 4).

## 3. Read the documents
- Read `docs/*.md` for every mechanic the change touches.
- Read `data/docs_changes/` for anything new since the last release (`lab.release` prints it too).
- The docs beat our assumptions.

## 4. Refine the strategy
- Update [STRATEGY.md](STRATEGY.md) with the findings: what we copy, what we change, and the numbers behind it (sections 1c, 8b).
- Pick the one improvement this version carries and say which finding it comes from.

## 5. Build the version and gate it (no tournament)
**Time budget: build and publish within 0–1:30 hours (Ben, Oct 3; reaffirmed Oct 8: "still keep the 0-1:30 hours budget for each version")**, because rivals improve fast. The bug hunt (step 3) is inside this budget.
**Only a version that is better than our last one gets more time or a release** (Ben, Oct 8, 22:4x: "I will only allow you to spend more time on a new version of bot that is more superior than our last one"). A candidate whose gate only shows "not worse" (95% interval across 0.5) and whose mechanism check shows no gain is not published (v035, 0.512 [0.464, 0.559], was stopped before upload). For changes self-play can't measure (queen safety), the superiority evidence is the offline re-play of real ladder situations, reported with its sample.

**The internal tournament is removed** (Ben, Oct 7: "remove the tournament, it already exceeds our 1 hour per version and per fix"). It took 20–50 min per version, and self-play didn't predict the ladder anyway (v70c won T1 and lost its duel at −2.7 SE). [TOURNAMENT.md](TOURNAMENT.md) and `lab.tournament` are kept only as a record; don't run them.
1. **Build the version's candidate** on top of the live bot: the one improvement from step 4.
   - Quick screens (`python -m lab.screen ... --against <champion>`) are allowed to drop broken ideas early.
   - **Check the mechanism, not only the score** (Oct 7): measure the behaviour the change targets in local replays (e.g. `analysis/pockets.py`, `food_taking.py`, `queen_encounters.py` on games played with `replay=True`). Oct 7: v012b and v014 screened 0.500 and 0.556 while changing nothing they aimed at.
   - **Re-play ladder situations offline** (Oct 7): `analysis/why_move.py` rebuilds one of our ladder dragons' exact inputs and runs a native debug build (per-direction scores); `analysis/queen_offline.py` re-plays the turns where our ladder queen got cornered into old and new builds. Self-play can't judge queen safety: our queen ends cornered after 6-7% of encounters locally (vs v008 or the clones), 30.5% on the ladder.
   - Website numbers differ from ours (the API's `version` field): website v37 = our v67.
2. **Latest vs our last version, on all current server maps (replaces the tournament; Ben, Oct 7; baseline changed Oct 8; hard code from Oct 10: the unseen/held-out set below is retired, use `lab.screen <cand> --against <last hard-code version> --maps current`):** the candidate plays **our last new version** (the live champion it is built on, as submitted in `versions/server/`) head to head on the current ladder pool maps AND on unseen maps (the 7 held-out ladder maps plus generated ones). Report both scores separately with their game counts. The release gate (step 4) plays exactly this match (pool + held-out + generated, both sides), so its per-map-set scores are the report; no separate run is needed.
   - Ben (Oct 8): "If v65 already lost to our new version, then don't compare our new version against it; compare it to our last new version." v65 (15299) lost to every version from v009a on (0.565-0.639 over 108 games each), so it is retired as a baseline.
   - If the candidate loses to the last version on both map sets, don't publish it; say so.
3. **Hunt for bugs before submitting (Ben, Oct 8: "add the finding possible bugs part before submitting").** Inside the 0-1:30 h budget, before `lab.release`:
   - **Read the whole diff** against the live bot (`diff -u <live>/main.cpp <cand>/main.cpp`), line by line: conditions that bind wrongly (the Oct 7 dangling else ran for months), wrong variable or direction index, a rule that also fires for the queen or the last dragon, wraparound and portal tiles (`stepTo`), unit limit, rounds where it switches on/off.
   - **Compile with warnings** (`clang++ -std=c++20 -O2 -Wall -Wextra -fsyntax-only main.cpp`) and read every warning the change adds.
   - **Check it changes only what it should:** where a rule must not fire (e.g. known maps, the queen), play the same seed against the live bot and confirm identical ends (Oct 8: v025 was identical on Slithery Fight, Trophy, Autarky); where it should fire, the mechanism check (step 1) shows it.
   - **Check the measuring tools too:** a number that looks too good or too strange gets one game looked at by hand (Oct 8: `merge_queen.py` counted games that ended before the feeding as "0 moves", and a truncated output was reported as a full count).
   - Write what was checked and what was found into the release note.
4. **Gate and publish it:** `python -m lab.release <cand> --name ... --desc ...` (crashes, timeouts, CPU, the clone smoke test, the local gate against the live champion on pool + unseen maps, the 1-hour rule).
5. The ladder duel (step 6.2) is the judge.

## 6. Publish and track
1. **Publish** (the upload goes live).
2. **Judge it with the paired duel** (hard code: only against the last hard-code version; ranked battles, now free to request, are the live measure, ranked games only, counted by the submission id in each replay): `python -m lab.duel --candidate <id> --champion <id> --dev`. The candidate and the champion play the same ladder teams and the dev bot on the same maps, unranked, and the paired difference decides. **Keep the candidate only if the difference is ≥ 0; otherwise revert** (Ben, Oct 3: "we dropped more than 200 Elo in a day, adjust is needed").
   - The old rule (revert only below −1.5 SE) kept v76 (−0.117) and v77 (−0.067), and small losses piled up release after release.
   - The cost of the new rule: with 60 pairs (SE ~0.08), a small real gain is kept only about half the time.
   - **Regression checks:** `lab.duel --candidate <old id> --champion <live id> --dev --no-decide` compares an older version with the live one on the ladder without changing what is live.
3. **Track it live for at least 1 hour:**
   - `lab.ladder status` (rating, per-map ratings);
   - `lab.diagnose` on its games;
   - check that the improvement it carries actually shows up in the replays (e.g. sprint share, king length, sonar rays).
4. Write the release note and log it.

## 7. Repeat
The loop never stops: analysis (step 2) runs while the live version is tracked (step 6).
