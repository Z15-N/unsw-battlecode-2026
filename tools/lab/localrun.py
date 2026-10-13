"""Play one match in the judge's sandbox and return structured results.

Mirrors `unswbc.run.execute` (same pools, bots, engine and seed handling) but
returns data instead of printing, and can record every round block a dragon
was sent, which is the ground truth the replay tracker is tested against.
"""

from __future__ import annotations

import pathlib
import secrets
import time
from dataclasses import dataclass, field

from unswbc import clangtool
from unswbc.engine import DEBUG_ALL, EngineModule
from unswbc.sandbox import SandboxBot, SandboxPool, WasmPool, warm_interpreter

DEATH_REASONS = {"W": "wall", "S": "self", "O": "body", "H": "head", "A": "action"}


@dataclass
class Match:
    map: str
    bot_a: str
    bot_b: str
    seed: int
    winner: str | None = None          # "A", "B" or None for a draw
    rounds: int = 0
    end_reason: int = 0                # 0 elimination, 1 round limit
    queen: tuple = (0, 0)
    longest: tuple = (0, 0)
    total: tuple = (0, 0)
    dragons: tuple = (0, 0)
    deaths: dict = field(default_factory=dict)       # team -> {reason: count}
    points: dict = field(default_factory=dict)       # team -> sorted per-turn points
    errors: list = field(default_factory=list)       # (round, dragon, team, message)
    seconds: float = 0.0
    replay: bytes | None = None
    blocks: dict | None = None         # dragon id -> [init block, round block, ...] (bytes)


def resolve(bot: str | pathlib.Path) -> tuple[list[str], pathlib.Path, str]:
    """A bot directory (C/C++ sources or main.py), a main.wasm directory, or a .wasm file."""
    path = pathlib.Path(bot)
    if path.is_file() and path.suffix == ".wasm":
        return [str(path.resolve())], path.parent, "wasm"
    if (path / "main.py").is_file():
        return [], path, "python"
    if (path / "main.wasm").is_file():
        return [str((path / "main.wasm").resolve())], path, "wasm"
    if clangtool.sources(path):
        return [str(clangtool.build(path))], path, "wasm"
    raise ValueError(f"{bot}: not a runnable bot")


def play(map_path: str | pathlib.Path, bot_a: str, bot_b: str, seed: int | None = None,
         replay: bool = False, capture: bool = False, debug: int = 0) -> Match:
    map_path = pathlib.Path(map_path)
    seed = secrets.randbits(64) if seed is None else seed
    result = Match(map=map_path.stem, bot_a=str(bot_a), bot_b=str(bot_b), seed=seed)
    resolved = {"A": resolve(bot_a), "B": resolve(bot_b) if bot_b != bot_a else None}
    resolved["B"] = resolved["B"] or resolved["A"]
    if any(kind == "python" for _, _, kind in resolved.values()):
        warm_interpreter()

    pools = {}
    try:
        for team, (argv, botdir, kind) in resolved.items():
            maker = WasmPool if kind == "wasm" else SandboxPool
            pools[team] = maker(argv or ["python"], cwd=str(botdir), key=f"{seed:016x}-{team.lower()}")
    except BaseException:
        for pool in pools.values():
            pool.close()
        raise

    live: dict[int, SandboxBot] = {}
    teams: dict[int, str] = {}
    blocks: dict[int, list] | None = {} if capture else None
    started = time.monotonic()

    def spawn(dragon_id: int, init: bytes) -> None:
        team = next((l.split()[1] for l in init.decode().splitlines() if l.startswith("TEAM")), "A")
        teams[dragon_id] = team
        live[dragon_id] = SandboxBot(pools[team], init=init, name=str(dragon_id))
        if blocks is not None:
            blocks.setdefault(dragon_id, []).append(init)

    def reply(dragon_id: int, block: bytes) -> bytes:
        if blocks is not None:
            blocks.setdefault(dragon_id, []).append(block)
        bot = live[dragon_id]
        out = bot.ask(block)
        if bot.error is not None:
            head = block.split(b"\n", 1)[0].split()
            rnd = int(head[1]) if len(head) > 1 and head[0] == b"ROUND" else -1
            result.errors.append((rnd, dragon_id, teams.get(dragon_id, "?"), bot.error))
        spent = getattr(bot, "live", None)
        if spent and spent[0]:
            result.points.setdefault(teams.get(dragon_id, "?"), []).append(spent[0])
        return out

    def death(dragon_id: int, round_num: int, reason: str) -> None:
        team = teams.get(dragon_id, "?")
        bucket = result.deaths.setdefault(team, {})
        key = DEATH_REASONS.get(reason, reason)
        bucket[key] = bucket.get(key, 0) + 1
        bot = live.pop(dragon_id, None)
        if bot is not None:
            bot.stop()

    engine = EngineModule()
    try:
        r = engine.run(map_path.read_bytes(), reply, death, spawn, lambda line: None,
                       DEBUG_ALL if debug else 0, seed)
    finally:
        for bot in live.values():
            bot.stop()
        for pool in pools.values():
            pool.close()

    result.winner, result.rounds, result.end_reason = r.winner, r.rounds + 1, r.end_reason
    result.queen, result.longest = (r.a_queen, r.b_queen), (r.a_longest, r.b_longest)
    result.total, result.dragons = (r.a_length, r.b_length), (r.a_dragons, r.b_dragons)
    for team in result.points:
        result.points[team].sort()
    result.seconds = time.monotonic() - started
    if replay:
        result.replay = engine.replay(pathlib.Path(bot_a).name, pathlib.Path(bot_b).name)
    result.blocks = blocks
    return result
