# Goals: read this before every release

Team **Weneedmoretokens** (id 135) · UNSW Battlecode 2026 · tournament runs **Sep 21 – Oct 17, 2026**

## What we are here to do (Ben's words, Claude's job)
1. **Beat this competition.** Win the ladder, the Sprint and the Grand Finals. A version that doesn't move us towards that is not worth shipping.
2. **Release an improved bot about every hour on average** (Ben, Oct 2; was 30 min). Every release must be *measurably better*, not just different. Speed comes from the pipeline, not from skipping checks. Claude releases on its own; Ben doesn't need to approve each one.
3. **Ben brings the strategy ideas; Claude powers them.** Implement them faithfully, test them, tune them, and report honestly what the numbers say. Don't silently swap in a different strategy.
4. **Our opponents are the top 10 teams.** Imitation bots of the current top 10 are rebuilt from their public replays every 4 hours (`opponents/clones/`), and every release is tested against them.
5. **Set up whatever this needs.** Storage is not a constraint. Tools, compilers and data are all fair game.
6. **The qualifier plays on UNSEEN maps, not the 10 ladder maps.** The bot must play well on maps it has never seen. Built-in map knowledge is only a bonus for the ladder. Every release is tested on generated unseen maps as well as the pool maps.
7. The old submissions (army-v1 … v23) are **no longer used**. Don't build on them. At most use them as test fixtures.

## Rules that decide games (Slay Queen update, Oct 1)
- **Queen = dragon id 0 or 1.** After 500 rounds the longer queen wins; a dead queen has length 0. Tiebreaks: longest dragon, then total length.
- A dragon of length L moves **ceil(L/4) steps per turn for free**; each step after that costs a segment.
- Death drops **ceil(L/2) pearls** (every second segment). Workers that die next to the queen feed her.
- 100M CPU points per dragon turn (judge); a turn that runs out kills the dragon. Keep the max under **85M** (Ben, Oct 7: "push the limit to max, we use way less than the judge gives"; it was 50M).
- Ranked pool (17 maps from Oct 2): schooltime, portals, slithery_fight, queen_of_spades, default, trophy, dilemma, autarky, devil, trauma, plus the 7 our bot has no data for (Stripes, Tower Defense, Islands, Around UNSW, weakhold, Maze, Australia). Those 7 stay unseen on purpose: they are our stand-in for the qualifier's unseen maps.

## Release checklist (`python -m lab.release` runs it)
The full loop around it is in [WORKFLOW.md](WORKFLOW.md):
- analyse the top 10 and the teams within 50 Elo of us, and refine the strategy before every version;
- every version gets at least 1 hour live, and each must carry an improvement from the refined strategy.

1. Re-read this file and [STRATEGY.md](STRATEGY.md). Does the change serve goals 1–3 and follow Ben's strategy?
2. **Re-read the docs** (`docs/*.md`) for every mechanic the change touches, and check `data/docs_changes/` for rule changes since the last release. The docs beat our assumptions.
3. The build passes in the judge sandbox (judge clang, `-O2 -msimd128`).
4. **Local gate against the live champion** (pool + generated unseen maps, both sides, up to 240 games):
   - **pass**: the 95% interval is above 0.5 (proven better), or
   - **trial**: score ≥ 0.5 with no measurable regression (most real gains are a few % and hide in the noise of self-play),
   - otherwise **fail**, and nothing is uploaded.
   - Exception (Oct 2, after Ben asked for the sonar network on the ladder): `--ladder-trial "<reason>"` sends a release whose self-play score is just under 0.5 straight to the ladder trial. Use it only when self-play can't measure the feature, e.g. communication the opponent lacks. It never overrides crashes, timeouts, CPU or the smoke test. The reason is logged.
5. **No regression against the top-10 imitation bots:** gauntlet score not lower than the champion's.
6. **Zero crashes, zero timeouts.** Max CPU under 85M points per turn (judge 100M).
7. Write the release note: what changed, the numbers, which of Ben's ideas it implements.
8. Submit and record it in the release log.
9. **Paired ladder duel** (`python -m lab.duel --candidate <id> --champion <id> --dev`, WORKFLOW 6.2). The candidate and the champion play the same ladder teams and the dev bot on the same maps, unranked. **Keep only if the difference is ≥ 0** (Oct 3, after a ~235 Elo slide; it was "revert only below −1.5 SE").
   - Removed Oct 3 (Ben: "delete rules that no longer benefit us"): the old ranked trial (`lab.trial` compared a 10-minute-old rating with the champion's settled one; it reverted v66 after 10 minutes and 12 ranked scrims against much stronger teams). Releases are logged "awaiting duel", so `lab.trial` leaves them alone. To bring it back: log a release with `"trial": "running"`.
