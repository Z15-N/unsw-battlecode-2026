"""Render a replay as an animated GIF: walls, portals, pearls and both armies, round by round.

    python render_replay.py <replay> <out.gif> [--every 4] [--cell 10] [--us A] [--title "..."]

The board at the start of each round is rebuilt from the replay's events by lab.track. Side `--us` is drawn blue
and the other side orange; each team's queen (its lowest id) gets a gold ring.
"""
import argparse
import pathlib
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lab.common import KELP, PORTAL, load_replay  # noqa: E402
from lab.track import Tracker  # noqa: E402

BG = (15, 23, 32)
KELP_C = (46, 125, 79)
PORTAL_C = (144, 133, 233)
PEARL_C = (240, 230, 200)
TEXT = (240, 239, 236)
TEXT2 = (168, 167, 160)
GOLD = (237, 161, 0)
TEAM_C = {"us": ((57, 135, 229), (160, 200, 255)), "them": ((217, 89, 38), (255, 176, 138))}
FONTS = pathlib.Path("C:/Windows/Fonts")


def font(bold, size):
    try:
        return ImageFont.truetype(str(FONTS / ("segoeuib.ttf" if bold else "segoeui.ttf")), size)
    except OSError:
        return ImageFont.load_default()


def snapshots(replay):
    """(round, pearls, {id: (team, body)}) at the start of every round, then the final board."""
    t = Tracker(replay, strict=False)
    last = None
    for _ in t.run():
        if t.round != last:
            last = t.round
            yield t.round, set(t.pearls), {i: (d.team, [(x, y) for x, y, _ in d.body]) for i, d in t.dragons.items()}
    yield last + 1, set(t.pearls), {i: (d.team, [(x, y) for x, y, _ in d.body]) for i, d in t.dragons.items()}


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("replay")
    p.add_argument("out")
    p.add_argument("--every", type=int, default=4, help="draw every n-th round")
    p.add_argument("--cell", type=int, default=10, help="pixels per tile")
    p.add_argument("--us", default="A", help="the side drawn blue (A or B)")
    p.add_argument("--title", default="")
    p.add_argument("--us-name", default="Our bot")
    p.add_argument("--them-name", default="Opponent")
    a = p.parse_args(argv)

    replay = load_replay(a.replay)
    t0 = Tracker(replay, strict=False)
    gm, W, H, c = t0.map, t0.w, t0.h, a.cell
    queens = {}
    for i, (team, _) in enumerate(gm.dragons):
        queens.setdefault(team, i)                          # each team's lowest id
    side = {a.us: "us", ("B" if a.us == "A" else "A"): "them"}

    top, bottom = 44, 72
    size = (W * c, H * c + top + bottom)
    board = Image.new("RGB", size, BG)
    d = ImageDraw.Draw(board)
    for y in range(H):
        for x in range(W):
            for e, (x0, y0, x1, y1) in ((gm.hedge[y][x], (x, y, x + 1, y)), (gm.vedge[y][x], (x, y, x, y + 1))):
                if e.kind in (KELP, PORTAL):
                    d.line([(x0 * c, top + y0 * c), (x1 * c, top + y1 * c)],
                           fill=KELP_C if e.kind == KELP else PORTAL_C, width=2 if e.kind == KELP else 3)

    f_title, f_text, f_small = font(True, 15), font(False, 13), font(False, 12)
    frames = []
    queen_death = {}                                        # team -> the round its queen died in
    final = None
    for rnd, pearls, dragons in snapshots(replay):
        for team, qid in queens.items():
            if qid not in dragons:
                queen_death.setdefault(team, rnd - 1)           # missing at the start of rnd: died during rnd - 1
        final = (rnd, dragons)
        if rnd % a.every and rnd < 500:
            continue
        im = board.copy()
        d = ImageDraw.Draw(im)
        for x, y in pearls:
            cx, cy = x * c + c / 2, top + y * c + c / 2
            d.ellipse([cx - c * 0.18, cy - c * 0.18, cx + c * 0.18, cy + c * 0.18], fill=PEARL_C)
        stats = {"us": [0, 0, None], "them": [0, 0, None]}     # dragons, longest, queen length
        for i, (team, body) in sorted(dragons.items()):
            who = side[team]
            col, head_col = TEAM_C[who]
            s = stats[who]
            s[0] += 1
            s[1] = max(s[1], len(body))
            if queens.get(team) == i:
                s[2] = len(body)
            for k, (x, y) in enumerate(body):
                if k + 1 < len(body):
                    nx, ny = body[k + 1]
                    if abs(nx - x) + abs(ny - y) == 1:          # draw the joint, not across a wrap or portal
                        lo_x, hi_x, lo_y, hi_y = min(x, nx), max(x, nx), min(y, ny), max(y, ny)
                        d.rectangle([lo_x * c + 2, top + lo_y * c + 2, (hi_x + 1) * c - 3, top + (hi_y + 1) * c - 3], fill=col)
                d.rounded_rectangle([x * c + 1, top + y * c + 1, (x + 1) * c - 2, top + (y + 1) * c - 2],
                                    radius=max(1, c // 4), fill=head_col if k == 0 else col)
            if queens.get(team) == i and body:
                x, y = body[0]
                d.ellipse([x * c - 3, top + y * c - 3, (x + 1) * c + 2, top + (y + 1) * c + 2], outline=GOLD, width=2)
        d.rectangle([0, 0, size[0], top - 1], fill=BG)
        d.text((10, 12), a.title, font=f_title, fill=TEXT)
        d.text((size[0] - 10, 13), f"round {min(rnd, 500)}/500", font=f_text, fill=TEXT2, anchor="ra")
        y0 = top + H * c + 8
        for k, (who, name) in enumerate((("us", a.us_name), ("them", a.them_name))):
            n, longest, q = stats[who]
            x0 = 10 + k * (size[0] // 2)
            d.rounded_rectangle([x0, y0 + 3, x0 + 12, y0 + 15], radius=3, fill=TEAM_C[who][0])
            d.text((x0 + 18, y0), name, font=f_text, fill=TEXT)
            queen = f"queen {q} long" if q is not None else "queen dead"
            d.text((x0 + 18, y0 + 19), f"{n} dragons · longest {longest} · {queen}", font=f_small, fill=TEXT2)
        d.text((10, y0 + 42), "gold ring = queen   ·   dots = pearls   ·   green = kelp walls   ·   violet = portals",
               font=f_small, fill=TEXT2)
        frames.append(im)

    # result banner on the last frame
    rnd, dragons = final
    ql = {team: len(dragons[qid][1]) if qid in dragons else 0 for team, qid in queens.items()}
    us_team = a.us
    them_team = "B" if us_team == "A" else "A"
    won = ql[us_team] > ql[them_team]
    line1 = "We win" if won else "We lose"
    parts = [f"our queen {ql[us_team]} long" if ql[us_team] else f"our queen killed in round {queen_death.get(us_team)}",
             f"theirs {ql[them_team]} long" if ql[them_team] else f"theirs killed in round {queen_death.get(them_team)}"]
    line2 = ", ".join(parts)
    im = frames[-1].copy().convert("RGBA")
    over = Image.new("RGBA", im.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(over)
    bw, bh = int(size[0] * 0.72), 74
    bx, by = (size[0] - bw) // 2, top + (H * c - bh) // 2
    od.rounded_rectangle([bx, by, bx + bw, by + bh], radius=10, fill=(15, 23, 32, 235), outline=GOLD, width=2)
    od.text((size[0] // 2, by + 14), line1, font=font(True, 20), fill=TEXT, anchor="ma")
    od.text((size[0] // 2, by + 44), line2, font=f_text, fill=TEXT2, anchor="ma")
    frames[-1] = Image.alpha_composite(im, over).convert("RGB")

    palette = frames[-1].quantize(colors=64, method=Image.Quantize.MEDIANCUT)
    out = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
    durations = [1200] + [70] * (len(out) - 2) + [3500]
    out[0].save(a.out, save_all=True, append_images=out[1:], duration=durations, loop=0, optimize=True)
    print(f"{a.out}: {len(out)} frames, {size[0]}x{size[1]}, {pathlib.Path(a.out).stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
