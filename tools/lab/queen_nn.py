"""A queen-move network (Ben, Oct 13: "try and use the neural network method"). Same pipeline as lab.clones (replays ->
extract.exe features -> PyTorch MLP -> weights header), trained only on one team's queen turns (dragon id 0 or 1 of
that team), for the team that is measurably better than us at queen survival (lab.skills: free trip to sydney pls,
team 82, queen death round +127.9). The weights go into our bot, where the queen adds QNN_W x log p(move) to her own
move scores; our hard rules keep the last word.
    python -m lab.queen_nn --team 82 --games 300 [--hidden 64 32] [--epochs 12] --out <bot folder>/nnq_weights.hpp
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

import numpy as np

from .clones import ACTIONS, DATASETS, MODELS, _array, feature_version, team_games


def load_queen(team_id: int, games: int):
    from .scout import connect
    folder = DATASETS / feature_version() / str(team_id)
    picked = team_games(connect(), team_id, games)
    xs, ys, ms, gids = [], [], [], []
    for gid, _, _ in reversed(picked):
        path = folder / f"{gid}.npz"
        if not path.is_file():
            continue
        d = np.load(path)
        keep = (d["y"] >= 0) & (d["dragon"] <= 1)
        if not keep.any():
            continue
        xs.append(d["x"][keep]); ys.append(d["y"][keep]); ms.append(d["mask"][keep])
        gids.append(np.full(int(keep.sum()), gid, dtype=np.int64))
    if not xs:
        raise RuntimeError(f"no queen rows for team {team_id}")
    return np.concatenate(xs), np.concatenate(ys), np.concatenate(ms), np.concatenate(gids)


def main(argv=None) -> int:
    import torch
    import torch.nn as nn
    p = argparse.ArgumentParser(prog="lab.queen_nn")
    p.add_argument("--team", type=int, required=True)
    p.add_argument("--games", type=int, default=300)
    p.add_argument("--hidden", type=int, nargs=2, default=[64, 32])
    p.add_argument("--epochs", type=int, default=12)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    torch.set_num_threads(2)  # Ben's laptop
    x, y, mask, gids = load_queen(a.team, a.games)
    order = np.unique(gids)
    held = set(order[-max(1, len(order) // 10):].tolist())    # newest 10% of games
    val = np.isin(gids, list(held))
    mean = x[~val].astype(np.float32).mean(0)
    std = x[~val].astype(np.float32).std(0)
    inv_std = np.where(std > 1e-4, 1.0 / np.maximum(std, 1e-4), 0.0).astype(np.float32)
    model = nn.Sequential(nn.Linear(x.shape[1], a.hidden[0]), nn.ReLU(), nn.Linear(a.hidden[0], a.hidden[1]), nn.ReLU(),
                          nn.Linear(a.hidden[1], ACTIONS))
    opt = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-3)
    m_t, s_t = torch.tensor(mean), torch.tensor(inv_std)
    xt, yt = torch.tensor(x[~val]), torch.tensor(y[~val].astype(np.int64))
    xv, yv, mv = torch.tensor(x[val]), torch.tensor(y[val].astype(np.int64)), torch.tensor(mask[val])
    loss_fn = nn.CrossEntropyLoss()
    started = time.monotonic()

    def evaluate():
        model.eval()
        with torch.no_grad():
            z = model((xv.float() - m_t) * s_t)
            acc = (z.argmax(1) == yv).float().mean().item()
            zz = z.clone()
            deadly = mv[:, :4].bool()
            any_safe = (~deadly).any(1, keepdim=True)
            zz[:, :4] = zz[:, :4].masked_fill(deadly & any_safe, -1e9)
            zz[:, 4] = zz[:, 4].masked_fill(~mv[:, 4].bool(), -1e9)
            acc_m = (zz.argmax(1) == yv).float().mean().item()
            # moves only (the queen's prior uses N/E/S/W), among rows whose label is a move
            mv_rows = yv < 4
            zm = zz[mv_rows][:, :4]
            acc_moves = (zm.argmax(1) == yv[mv_rows]).float().mean().item() if mv_rows.any() else 0.0
        model.train()
        return acc, acc_m, acc_moves

    for epoch in range(a.epochs):
        perm = torch.randperm(len(xt))
        for i in range(0, len(xt), 2048):
            idx = perm[i:i + 2048]
            loss = loss_fn(model((xt[idx].float() - m_t) * s_t), yt[idx])
            opt.zero_grad()
            loss.backward()
            opt.step()
        acc, acc_m, acc_moves = evaluate()
        print(f"  epoch {epoch + 1}: loss {loss.item():.3f}  held-out {acc:.3f} (rule mask {acc_m:.3f}, moves only {acc_moves:.3f})", flush=True)
    base = float(np.bincount(y[val], minlength=ACTIONS).max() / max(val.sum(), 1))
    metrics = {"team": a.team, "games": int(len(order)), "train_turns": int((~val).sum()), "val_turns": int(val.sum()),
               "accuracy": round(acc, 4), "accuracy_masked": round(acc_m, 4), "accuracy_moves": round(acc_moves, 4),
               "majority_baseline": round(base, 4), "hidden": a.hidden, "seconds": round(time.monotonic() - started, 1),
               "features": feature_version()}
    out_dir = MODELS / f"queen_{a.team}"
    out_dir.mkdir(parents=True, exist_ok=True)
    st = {k: v.detach().numpy() for k, v in model.state_dict().items()}
    np.savez(out_dir / "model.npz", mean=mean, inv_std=inv_std, **{k.replace(".", "_"): v for k, v in st.items()})
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=1))
    w1, b1, w2, b2, w3, b3 = (st["0.weight"], st["0.bias"], st["2.weight"], st["2.bias"], st["4.weight"], st["4.bias"])
    text = [f"// Generated by lab.queen_nn (team {a.team}, queen turns only) -- do not edit.", "#pragma once",
            "namespace qnnw {", f"constexpr int INPUTS = {w1.shape[1]};", f"constexpr int H1 = {w1.shape[0]};",
            f"constexpr int H2 = {w2.shape[0]};", f"constexpr int OUTPUTS = {w3.shape[0]};",
            _array("mean", mean), _array("inv_std", inv_std), _array("w1", w1), _array("b1", b1),
            _array("w2", w2), _array("b2", b2), _array("w3", w3), _array("b3", b3), "}  // namespace qnnw"]
    pathlib.Path(a.out).write_text("\n".join(text) + "\n")
    print(json.dumps(metrics))
    return 0


if __name__ == "__main__":
    sys.exit(main())
