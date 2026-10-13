"""Render a round block as a 7x7 ASCII picture (debugging aid).

Letters: @ our head, o our body, A/a ally head/body, E/e enemy head/body,
* pearl; '|' and '-' are kelp edges, 'P'/'=' portal edges.
"""

from __future__ import annotations


def render(block: str, self_id: int) -> str:
    lines = [l for l in block.strip().splitlines()]
    i = 0
    header = []
    while len(lines[i].split()) != 4 or not all(t.lstrip("-").isdigit() for t in lines[i].split()):
        header.append(lines[i])
        i += 1
    tiles = [tuple(map(int, l.split())) for l in lines[i:i + 49]]
    i += 49
    n = int(lines[i].split()[1])
    parts = [l.split() for l in lines[i + 1:i + 1 + n]]
    i += 1 + n
    hedges = [l.split() for l in lines[i:i + 8]]
    vedges = [l.split() for l in lines[i + 8:i + 15]]
    my_team = next((p[0] for p in parts if int(p[1]) == self_id), "A")
    pos = {(t[0], t[1]): k for k, t in enumerate(tiles)}
    grid = [["*" if t[2] else "." for t in tiles[r * 7:(r + 1) * 7]] for r in range(7)]
    for team, pid, x, y, facing, head in parts:
        k = pos.get((int(x), int(y)))
        if k is None:
            continue
        if int(pid) == self_id:
            ch = "@" if head == "1" else "o"
        elif team == my_team:
            ch = "A" if head == "1" else "a"
        else:
            ch = "E" if head == "1" else "e"
        grid[k // 7][k % 7] = ch
    out = [" ".join(header)]
    for r in range(8):
        out.append("+" + "+".join("--" if hedges[r][c] == "w" else "==" if hedges[r][c] not in (".", "w") else "  "
                                  for c in range(7)) + "+")
        if r < 7:
            row = ""
            for c in range(8):
                e = vedges[r][c]
                row += "|" if e == "w" else "P" if e != "." else " "
                if c < 7:
                    row += grid[r][c] + " "
            out.append(row)
    return "\n".join(out)
