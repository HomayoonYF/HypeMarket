"""Price chart rendered with Pillow (Latin text only, so no Persian shaping is needed)."""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

from . import config as C


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # very old Pillow
        return ImageFont.load_default()


def render(ticker: str, points: list[tuple[int, int]], span_label: str) -> bytes:
    """points: [(unix_ts, price_units)], oldest first. Returns PNG bytes."""
    W, H, PAD_L, PAD_R, PAD_T, PAD_B = 800, 420, 78, 24, 56, 44
    bg, grid, fg = (18, 22, 33), (45, 52, 70), (230, 235, 245)
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    f_big, f_small = _font(26), _font(15)
    d.text((PAD_L, 14), f"${ticker}  -  {span_label}", fill=fg, font=f_big)
    if len(points) < 2:
        points = points * 2 if points else [(0, 0), (1, 0)]
    xs = [p[0] for p in points]
    ys = [p[1] / C.UNIT for p in points]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    if y1 - y0 < 1e-9:
        y0, y1 = y0 * 0.95, y1 * 1.05 + 0.01
    pad = (y1 - y0) * 0.08
    y0, y1 = y0 - pad, y1 + pad
    px = lambda x: PAD_L + (x - x0) / max(1, x1 - x0) * (W - PAD_L - PAD_R)
    py = lambda y: H - PAD_B - (y - y0) / (y1 - y0) * (H - PAD_T - PAD_B)
    for i in range(5):
        yy = y0 + (y1 - y0) * i / 4
        d.line([(PAD_L, py(yy)), (W - PAD_R, py(yy))], fill=grid)
        d.text((8, py(yy) - 8), f"{yy:,.2f}", fill=(150, 160, 185), font=f_small)
    up = ys[-1] >= ys[0]
    color = (46, 204, 113) if up else (231, 76, 60)
    pts = [(px(x), py(y)) for x, y in zip(xs, ys)]
    area = pts + [(pts[-1][0], H - PAD_B), (pts[0][0], H - PAD_B)]
    d.polygon(area, fill=tuple(int(c * 0.22 + b * 0.78) for c, b in zip(color, bg)))
    d.line(pts, fill=color, width=3, joint="curve")
    d.ellipse([pts[-1][0] - 5, pts[-1][1] - 5, pts[-1][0] + 5, pts[-1][1] + 5], fill=color)
    chg = (ys[-1] - ys[0]) * 100 / ys[0] if ys[0] else 0
    d.text((W - PAD_R - 170, 20), f"{ys[-1]:,.2f}  ({chg:+.1f}%)", fill=color, font=f_big)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()
