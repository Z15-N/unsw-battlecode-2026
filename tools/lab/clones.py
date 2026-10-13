"""Imitation opponents: one bot per top team, trained on that team's replays.

    python -m lab.clones build-extractor
    python -m lab.clones dataset --team 314 [--games 150]
    python -m lab.clones train   --team 314
    python -m lab.clones export  --team 314
    python -m lab.clones all     --top 10        # everything, for every top team

Data flow: data/replays/*.replay -> track.py (round blocks per dragon) ->
extract.exe (the bot's own feature code) -> data/datasets/<team>/<game>.npz ->
PyTorch MLP -> weights.hpp -> opponents/clones/<team>/ (a normal bot folder).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from .common import DATA, ROOT
from .track import track

CLONE_SRC = ROOT / "tools" / "clone"
BOT_SRC = CLONE_SRC / "bot"
EXTRACTOR = DATA / "bin" / "extract.exe"
DATASETS = DATA / "datasets"
MODELS = DATA / "models"
OPPONENTS = ROOT / "opponents" / "clones"
LLVM_GLOB = "MartinStorsjo.LLVM-MinGW.UCRT_*"
ACTIONS = 5


# ---------------------------------------------------------------- toolchain
def native_cxx() -> str:
    found = shutil.which("clang++")
    if found:
        return found
    base = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    for pkg in sorted(base.glob(LLVM_GLOB)):
        for exe in pkg.glob("*/bin/clang++.exe"):
            return str(exe)
    raise RuntimeError("no native clang++: install LLVM-MinGW (winget install MartinStorsjo.LLVM-MinGW.UCRT)")


def feature_version() -> str:
    """Datasets are only valid for the feature code that produced them."""
    h = hashlib.sha256()
    for name in ("clone.hpp", "known_maps.hpp"):
        h.update((BOT_SRC / name).read_bytes())
    return h.hexdigest()[:12]


def build_extractor() -> pathlib.Path:
    stamp = EXTRACTOR.with_suffix(".version")
    version = feature_version()
    if EXTRACTOR.is_file() and stamp.is_file() and stamp.read_text() == version:
        return EXTRACTOR
    EXTRACTOR.parent.mkdir(parents=True, exist_ok=True)
    cmd = [native_cxx(), "-std=c++20", "-O2", "-static", str(CLONE_SRC / "extract" / "extract.cpp"),
           "-o", str(EXTRACTOR)]
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(done.stderr)
    stamp.write_text(version)
    return EXTRACTOR


def feature_count() -> int:
    text = (BOT_SRC / "clone.hpp").read_text()
    consts = dict(re.findall(r"constexpr int (\w+) = ([^;]+);", text))

    def value(name: str) -> int:
        expr = consts[name]
        for key in sorted(consts, key=len, reverse=True):
            if re.search(rf"\b{key}\b", expr):
                expr = re.sub(rf"\b{key}\b", str(value(key)), expr)
        return int(eval(expr, {"__builtins__": {}}))

    return value("FEATURES")


# ---------------------------------------------------------------- datasets
def label(action) -> int:
    if not action:
        return -1
    if action[0] == "move" and action[1]:
        return "NESW".index(action[1][0])
    if action[0] == "split":
        return 4
    return -1


def sessions_for(replay_path: pathlib.Path, team_letter: str) -> tuple[str, list]:
    """Round blocks of one team's dragons, grouped into process lifetimes."""
    tracker = track(replay_path, strict=False)
    sessions: dict[int, list] = {}
    order: list = []
    for turn in tracker.run():
        if turn.team != team_letter:
            continue
        if turn.first or turn.id not in sessions:
            sessions[turn.id] = []
            order.append((turn.id, sessions[turn.id], turn))
        sessions[turn.id].append(turn)
    parts, meta = [], []
    for dragon_id, turns, first in order:
        parts.append("@SESSION\n" + first.init_block())
        for t in turns:
            lab = label(t.action)
            parts.append(f"@TURN {lab}\n" + t.block())
            act = t.action or ("none",)
            meta.append((t.round, t.id, lab, act[1] if act[0] in ("move", "split") else ""))
    return "".join(parts), meta


def game_dataset(args) -> tuple[int, str, int]:
    game_id, team_letter, out_path, extractor, n_features = args
    replay = DATA / "replays" / f"{game_id}.replay"
    try:
        text, meta = sessions_for(replay, team_letter)
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "f.bin"
            done = subprocess.run([str(extractor), str(out)], input=text.encode(), capture_output=True)
            if done.returncode != 0:
                return game_id, f"extract failed: {done.stderr[-300:]!r}", 0
            raw = np.fromfile(out, dtype=np.float32).reshape(-1, n_features + 5)
        if len(raw) != len(meta):
            return game_id, f"row mismatch {len(raw)} vs {len(meta)}", 0
        y = np.array([m[2] for m in meta], dtype=np.int8)
        np.savez_compressed(out_path, x=raw[:, :n_features].astype(np.float16),
                            mask=raw[:, n_features:].astype(np.uint8), y=y,
                            round=np.array([m[0] for m in meta], dtype=np.int16),
                            dragon=np.array([m[1] for m in meta], dtype=np.int16),
                            detail=np.array([m[3] for m in meta]))
        return game_id, "", len(meta)
    except Exception as error:  # a bad replay must not stop the batch
        return game_id, f"{type(error).__name__}: {error}", 0


def team_games(db, team_id: int, limit: int) -> list[tuple[int, str, str]]:
    from .scout import RULES_EPOCH
    rows = db.execute("""SELECT id, team_a, team_b, at FROM games
                         WHERE (team_a = ? OR team_b = ?) AND replay_bytes IS NOT NULL AND at >= ?
                         ORDER BY at DESC LIMIT ?""",
                      (team_id, team_id, RULES_EPOCH.isoformat(), limit)).fetchall()
    return [(gid, "A" if a == team_id else "B", at) for gid, a, b, at in rows]


def build_dataset(team_id: int, games: int, workers: int = 4) -> pathlib.Path:  # 4 (was 10): Ben's laptop, Oct 13
    from .scout import connect
    extractor = build_extractor()
    n_features = feature_count()
    folder = DATASETS / feature_version() / str(team_id)
    folder.mkdir(parents=True, exist_ok=True)
    db = connect()
    todo = []
    for gid, letter, _ in team_games(db, team_id, games):
        out = folder / f"{gid}.npz"
        if not out.is_file():
            todo.append((gid, letter, out, extractor, n_features))
    started = time.monotonic()
    rows = errors = 0
    if todo:
        with ProcessPoolExecutor(workers) as pool:
            for gid, error, n in pool.map(game_dataset, todo):
                rows += n
                if error:
                    errors += 1
                    print(f"  game {gid}: {error}", flush=True)
    print(f"team {team_id}: {len(todo)} new games, {rows} turns, {errors} errors, "
          f"{time.monotonic() - started:.0f}s -> {folder}")
    return folder


# ---------------------------------------------------------------- training
MAX_ROWS = 600_000

def load_team(team_id: int, games: int):
    from .scout import connect
    folder = DATASETS / feature_version() / str(team_id)
    picked = team_games(connect(), team_id, games)
    xs, ys, ms, gids = [], [], [], []
    cap = MAX_ROWS // max(1, len(picked))           # per game: 1.4M x 753 rows ran out of memory on Oct 2
    rng = np.random.default_rng(team_id)
    for gid, _, _ in reversed(picked):            # oldest first
        path = folder / f"{gid}.npz"
        if not path.is_file():
            continue
        d = np.load(path)
        keep = d["y"] >= 0
        idx = np.flatnonzero(keep)
        if len(idx) > cap:
            keep = np.zeros_like(keep)
            keep[np.sort(rng.choice(idx, cap, replace=False))] = True
        xs.append(d["x"][keep]); ys.append(d["y"][keep]); ms.append(d["mask"][keep])
        gids.append(np.full(int(keep.sum()), gid, dtype=np.int64))
    if not xs:
        raise RuntimeError(f"no dataset for team {team_id}: run `dataset` first")
    return np.concatenate(xs), np.concatenate(ys), np.concatenate(ms), np.concatenate(gids)


def train(team_id: int, games: int = 150, epochs: int = 6, hidden=(256, 128), quiet=False) -> dict:
    import torch
    import torch.nn as nn

    x, y, mask, gids = load_team(team_id, games)
    order = np.unique(gids)
    held = set(order[-max(1, len(order) // 10):].tolist())     # newest 10% of games
    val = np.isin(gids, list(held))
    device = "cuda" if torch.cuda.is_available() else "cpu"
    mean = x[~val].astype(np.float32).mean(0)
    std = x[~val].astype(np.float32).std(0)
    inv_std = np.where(std > 1e-4, 1.0 / np.maximum(std, 1e-4), 0.0).astype(np.float32)

    model = nn.Sequential(nn.Linear(x.shape[1], hidden[0]), nn.ReLU(), nn.Linear(hidden[0], hidden[1]),
                          nn.ReLU(), nn.Linear(hidden[1], ACTIONS)).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-4)
    m_t = torch.tensor(mean, device=device)
    s_t = torch.tensor(inv_std, device=device)
    xt = torch.tensor(x[~val])
    yt = torch.tensor(y[~val].astype(np.int64))
    xv = torch.tensor(x[val])
    yv = torch.tensor(y[val].astype(np.int64))
    mv = torch.tensor(mask[val])
    steps = epochs * (len(xt) // 4096 + 1)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=3e-3, total_steps=steps)
    loss_fn = nn.CrossEntropyLoss()
    started = time.monotonic()

    def evaluate():
        model.eval()
        correct = masked = total = 0
        with torch.no_grad():
            for i in range(0, len(xv), 16384):
                xb = (xv[i:i + 16384].to(device).float() - m_t) * s_t
                z = model(xb)
                yb = yv[i:i + 16384].to(device)
                correct += (z.argmax(1) == yb).sum().item()
                mb = mv[i:i + 16384].to(device).bool()
                zz = z.clone()
                deadly = mb[:, :4]
                any_safe = (~deadly).any(1, keepdim=True)
                zz[:, :4] = zz[:, :4].masked_fill(deadly & any_safe, -1e9)
                zz[:, 4] = zz[:, 4].masked_fill(~mb[:, 4], -1e9)
                masked += (zz.argmax(1) == yb).sum().item()
                total += len(yb)
        model.train()
        return correct / max(total, 1), masked / max(total, 1)

    for epoch in range(epochs):
        perm = torch.randperm(len(xt))
        for i in range(0, len(xt), 4096):
            idx = perm[i:i + 4096]
            xb = (xt[idx].to(device).float() - m_t) * s_t
            loss = loss_fn(model(xb), yt[idx].to(device))
            opt.zero_grad()
            loss.backward()
            opt.step()
            sched.step()
        acc, acc_masked = evaluate()
        if not quiet:
            print(f"  epoch {epoch + 1}: loss {loss.item():.3f}  held-out accuracy {acc:.3f} "
                  f"(with rule mask {acc_masked:.3f})", flush=True)
    baseline = float(np.bincount(y[val], minlength=ACTIONS).max() / max(val.sum(), 1))
    metrics = {"team": team_id, "games": int(len(order)), "train_turns": int((~val).sum()),
               "val_turns": int(val.sum()), "accuracy": round(acc, 4), "accuracy_masked": round(acc_masked, 4),
               "majority_baseline": round(baseline, 4), "seconds": round(time.monotonic() - started, 1),
               "features": feature_version(), "trained_at": dt.datetime.now().isoformat(timespec="seconds"),
               "hidden": list(hidden)}
    out = MODELS / str(team_id)
    out.mkdir(parents=True, exist_ok=True)
    state = {k: v.detach().cpu().numpy() for k, v in model.state_dict().items()}
    np.savez(out / "model.npz", mean=mean, inv_std=inv_std, **{k.replace(".", "_"): v for k, v in state.items()})
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1))
    print(f"team {team_id}: {metrics}")
    return metrics


# ---------------------------------------------------------------- export
def _array(name: str, values: np.ndarray) -> str:
    flat = values.astype(np.float32).ravel()

    def literal(v: float) -> str:
        s = f"{v:.6g}"
        return (s if ("." in s or "e" in s) else s + ".") + "f"

    body = ",".join(literal(v) for v in flat)
    return f"inline const float {name}[{len(flat)}] = {{{body}}};\n"


def write_weights(model_dir: pathlib.Path, out: pathlib.Path) -> None:
    d = np.load(model_dir / "model.npz")
    w1, b1, w2, b2, w3, b3 = (d["0_weight"], d["0_bias"], d["2_weight"], d["2_bias"], d["4_weight"], d["4_bias"])
    text = ["// Generated by lab.clones export -- do not edit.", "#pragma once", "namespace weights {",
            f"constexpr int INPUTS = {w1.shape[1]};", f"constexpr int H1 = {w1.shape[0]};",
            f"constexpr int H2 = {w2.shape[0]};", f"constexpr int OUTPUTS = {w3.shape[0]};",
            _array("mean", d["mean"]), _array("inv_std", d["inv_std"]),
            _array("w1", w1), _array("b1", b1), _array("w2", w2), _array("b2", b2),
            _array("w3", w3), _array("b3", b3), "}  // namespace weights"]
    out.write_text("\n".join(text) + "\n")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "team"


def export(team_id: int, name: str) -> pathlib.Path:
    folder = OPPONENTS / f"{team_id}_{slug(name)}"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    for f in ("clone.hpp", "known_maps.hpp", "model.hpp", "main.cpp"):
        shutil.copy(BOT_SRC / f, folder / f)
    write_weights(MODELS / str(team_id), folder / "weights.hpp")
    (folder / "bot.toml").write_text('[project]\nlanguage = "c++"\ninclude = [ "*.cpp", "*.hpp" ]\n')
    metrics = json.loads((MODELS / str(team_id) / "metrics.json").read_text())
    (folder / "clone.json").write_text(json.dumps({"team_id": team_id, "team": name, **metrics}, indent=1))
    print(f"exported {folder}")
    return folder


def run_all(top: int, games: int) -> None:
    from .scout import connect
    db = connect()
    snap = db.execute("SELECT MAX(at) FROM ladder").fetchone()[0]
    teams = db.execute("""SELECT l.team_id, t.name FROM ladder l JOIN teams t ON t.id = l.team_id
                          WHERE l.at = ? ORDER BY l.rank IS NULL, l.rank, l.elo DESC LIMIT ?""", (snap, top + 5)).fetchall()
    done = 0
    for team_id, name in teams:
        if done >= top:
            break
        if not team_games(db, team_id, 1):
            continue
        build_dataset(team_id, games)
        train(team_id, games, quiet=True)
        export(team_id, name)
        done += 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="lab.clones")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build-extractor")
    for cmd in ("dataset", "train", "export"):
        s = sub.add_parser(cmd)
        s.add_argument("--team", type=int, required=True)
        s.add_argument("--games", type=int, default=150)
        s.add_argument("--name", default="")
    a = sub.add_parser("all")
    a.add_argument("--top", type=int, default=10)
    a.add_argument("--games", type=int, default=150)
    args = p.parse_args(argv)
    if args.cmd == "build-extractor":
        print(build_extractor(), feature_count(), "features")
    elif args.cmd == "dataset":
        build_dataset(args.team, args.games)
    elif args.cmd == "train":
        train(args.team, args.games)
    elif args.cmd == "export":
        export(args.team, args.name or str(args.team))
    else:
        run_all(args.top, args.games)
    return 0


if __name__ == "__main__":
    sys.exit(main())
