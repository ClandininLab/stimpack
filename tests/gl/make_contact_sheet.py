"""Assemble GL stimulus renders into one labeled contact sheet for a quick visual overview.

By default it montages the committed reference images (tests/gl/reference/*.png) — i.e. exactly what
the golden tests render and check against. Point --from at tests/gl/_output to review a
`pytest -m gl --save-renders` run instead.

Usage:
    python tests/gl/make_contact_sheet.py                 # references -> _output/contact_sheet.png
    python tests/gl/make_contact_sheet.py --from tests/gl/_output --out /tmp/sheet.png
"""
import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="src", default=str(HERE / "reference"),
                    help="directory of PNGs to montage (default: tests/gl/reference)")
    ap.add_argument("--out", default=str(HERE / "_output" / "contact_sheet.png"),
                    help="output path (default: tests/gl/_output/contact_sheet.png)")
    ap.add_argument("--cols", type=int, default=4, help="columns in the grid")
    args = ap.parse_args()

    src = Path(args.src)
    paths = sorted(src.glob("*.png"))
    if not paths:
        raise SystemExit(f"No PNGs found in {src}")

    thumbs = [(p.stem, Image.open(p).convert("RGB")) for p in paths]
    tw, th = thumbs[0][1].size
    pad, label_h = 8, 20
    cols = min(args.cols, len(thumbs))
    rows = math.ceil(len(thumbs) / cols)
    cell_w, cell_h = tw + pad, th + pad + label_h

    sheet = Image.new("RGB", (cols * cell_w + pad, rows * cell_h + pad), (28, 28, 30))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    for i, (name, img) in enumerate(thumbs):
        row, col = divmod(i, cols)
        x = pad + col * cell_w
        y = pad + row * cell_h
        sheet.paste(img, (x, y))
        draw.text((x + 1, y + th + 4), name, fill=(225, 225, 228), font=font)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(f"wrote {out} — {len(thumbs)} images in a {cols}x{rows} grid")


if __name__ == "__main__":
    main()
