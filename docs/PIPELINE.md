# The testing and release pipeline

Game results are noisy. Two equal bots trade wins, maps favour one side, and the ladder's opponents change by the
hour. Most of the work in this project went into answering one question reliably and quickly: **is this version
actually better than the live one?** The tools live in [`tools/lab/`](../tools/lab/) and run as
`python -m lab.<tool>` from `tools/`.

## 1. Know the opponents

| Tool | What it does |
|---|---|
| [`scout`](../tools/lab/scout.py) | Pulls the public games and replays of the top 10 and of every team within 50 Elo of us into SQLite. Over the competition: about 250,000 games indexed. |
| [`elowatch`](../tools/lab/elowatch.py) | Every 30 minutes (Windows scheduled task): logs our rating and the live submission, and re-scouts the teams near our *current* rating. |
| [`track`](../tools/lab/track.py) | Rebuilds, from a replay's event stream alone, the exact text input each dragon received each turn. Server replays can't be re-simulated (pearl spawns differ from the local engine), so this is the only way to see the board as a dragon saw it. [`test_track.py`](../tools/lab/test_track.py) checks it against ground truth recorded from local games. |
| [`study`](../tools/lab/study.py) | Compares the top teams with us, behaviour by behaviour: sonar use, army size, eating, splits, spacing, sprints, rams, openings. |
| [`skills`](../tools/lab/skills.py) | For each measurable skill, which teams beat us by more than 2 standard errors **on the same maps**. A skill is copied only from a team that is measurably better at it, and the list is re-checked after every analysis, because we overtook some teams at some skills. |
| [`diagnose`](../tools/lab/diagnose.py) | Our own recent games: per-game timelines, rams, eliminations, per-map results. |

## 2. Build realistic opponents

[`clones`](../tools/lab/clones.py) trains an **imitation bot for each top team**:

```
replays -> track.py (each dragon's input) -> extract.exe (the bot's own C++ feature code)
        -> .npz datasets -> PyTorch MLP -> weights.hpp -> a normal bot folder
```

Using the bot's own feature code in the extractor ([`clone/extract`](../tools/clone/extract/extract.cpp)) means the
features seen in training are exactly the ones computed at play time. The clones are retrained every 4 hours by
[`refresh`](../tools/lab/refresh.py). They aren't strong, but they play *differently* from our bot, which self-play
can't provide. Every release had to pass a smoke test against them.

## 3. Test locally

| Tool | What it does |
|---|---|
| [`localrun`](../tools/lab/localrun.py) | One match in the judge's WebAssembly sandbox, priced in CPU points exactly as the judge does |
| [`arena`](../tools/lab/arena.py) | Many sandboxed games in parallel. Every (map, seed) is played twice with the sides swapped, so neither bot gains from moving first or from the map. |
| [`mapgen`](../tools/lab/mapgen.py) | Random symmetric maps (mirror or rotation, kelp and portals, connected spawns), used for testing before the bot hard-coded the ladder maps |
| [`screen`](../tools/lab/screen.py) | A quick 60-game screen to drop broken ideas before the full gate |

### The SPRT gate ([`sprt.py`](../tools/lab/sprt.py))

A fixed-size test either wastes games on obvious results or stops too early on close ones. Chess engines solve this
with a **sequential probability ratio test**, and so did we:

- The unit is a **pair**: one (map, seed) played from both sides, which cancels side and map luck.
- H0: the candidate is +0 Elo. H1: it is +20 Elo. α = β = 0.05. At most 1,600 games.
- After each round of pairs, the generalised SPRT log-likelihood ratio is updated with a normal approximation:
  `LLR = n · (s1 − s0) · (2·mean − s0 − s1) / (2·var)`, where s0 and s1 are the expected pair scores under each
  hypothesis.
- It stops as soon as the LLR crosses either bound. Over the project the runs took anywhere from 88 games (a clear
  loss) to 1,628 (inconclusive).

An inconclusive result counted as "not worse". Such a version shipped only if a separate check showed that the
mechanism it targets had actually changed (for example, the queen surviving longer in replays).

### SPSA tuning ([`spsa.py`](../tools/lab/spsa.py))

Simultaneous perturbation stochastic approximation tunes many constants at once from noisy win rates:

1. Each iteration perturbs every constant by ±c_k at random.
2. It builds the "+" and "−" bots by rewriting the declarations in `main.cpp`.
3. It plays them against each other in pairs.
4. It steps along the estimated gradient.

The specs are in [`tools/spsa/`](../tools/spsa/). We ran it three times (40 iterations × 44 games each):

- The first run's constants shipped (v065, total length +5%).
- The second run found no gradient: scores sat near 0.5 throughout, and its constants lost their SPRT (0.477).
  That is itself a useful finding, because those constants weren't what limited us.
- The third run's constants lost their SPRT (0.475).

## 4. Release and judge on the ladder

[`release`](../tools/lab/release.py) gates and uploads a candidate:

1. Download whatever submission is live. That is the champion, even if a teammate uploaded it.
2. Build in the judge's sandbox.
3. Require zero crashes, zero timeouts, and a peak under 85M of the 100M CPU points.
4. Run the smoke test against the clones.
5. Upload and log the release.

Every version then got at least an hour live.

[`duel`](../tools/lab/duel.py) is the final judge. A ranked trial compares a fresh rating with a settled one against
different opponents, which is meaningless. Instead, the candidate and the champion each play the **same** ladder
teams (plus the organisers' dev bot) on the **same** maps in unranked games, and the paired difference decides. The
rule is to **keep only if the difference is ≥ 0**.

That rule came from experience. The earlier rule was "revert only if it loses by 1.5 standard errors". Under it,
slightly-losing versions kept being kept, and the rating slid about 235 points in a day.

## 5. Debug real losses offline

When a ladder game shows the queen dying, [`analysis/why_move.py`](../tools/analysis/why_move.py) and
[`analysis/queen_offline.py`](../tools/analysis/queen_offline.py) rebuild that dragon's exact inputs from the replay
(via `track`), feed them to a native debug build, and print the score of each direction at the fatal turn. Before
trusting the scores, they check that the re-played move matches the move in the replay.

This, together with replay statistics from `track`, found problems that self-play never showed. Examples:

- In 26 of 44 queen kills, her 7×7 view had cut off the killer's body, so she under-rated its reach: it looked 1 long
  and was really up to 19.
- On one map, the leash toward her learned home pulled her down a dead-end corridor where every step was already a
  trap.
- On Maze, the opening views also fit another map of the same size, so 2–15% of our dragons' turns ran with the wrong
  walls.

It also killed false hope. A change that "won" a ladder duel by 0.2 turned out, when replayed on real cornered
situations, never to alter a single cornered move.

## 6. Automation

Two Windows scheduled tasks ([`elowatch_task.pyw`](../tools/elowatch_task.pyw),
[`refresh_task.pyw`](../tools/refresh_task.pyw)) kept the data fresh around the clock:

- every 30 minutes: rating and re-scout;
- every 4 hours: re-sync the rules pages (rule changes were diffed and flagged), scrape replays, retrain clones and
  prune old replays.

[`chain`](../tools/lab/chain.py) ran queues of long steps (screen, then release, then duel) detached from any terminal.
