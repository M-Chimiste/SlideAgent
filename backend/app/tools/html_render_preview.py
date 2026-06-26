"""Standalone visual-iteration harness for the HTML slide renderer.

Loads a job's persisted render-input outlines (or an arbitrary render-input.json)
and renders them through HtmlSlideRenderer, then builds a contact sheet so the
output can be compared against the reference deck without invoking the model.

Usage (from backend/):
    python -m app.tools.html_render_preview \
        --render-input ../data/jobs/<id>/outline/render-input.json \
        --out /tmp/html-preview

    python -m app.tools.html_render_preview --job <job-id> --out /tmp/html-preview
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.models.brand import BrandDNA
from app.models.outline import SlideOutline
from app.services.html_rendering import HtmlSlideRenderer


def _load_outlines(path: Path) -> list[SlideOutline]:
    data = json.loads(path.read_text())
    outlines = []
    for entry in data:
        # render-input.json rows already match the SlideOutline schema
        outlines.append(SlideOutline.model_validate(entry))
    return outlines


def _contact_sheet(pages_prefix_dir: Path, stem: str, out_path: Path, cols: int = 3) -> None:
    from PIL import Image

    images = sorted(
        pages_prefix_dir.glob(f"{stem}-pages-*.png"),
        key=lambda p: int("".join(c for c in p.stem.split("-")[-1] if c.isdigit()) or 0),
    )
    if not images:
        print("no page images for contact sheet")
        return
    cw, ch, pad = 600, 338, 8
    rows = (len(images) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cw + (cols + 1) * pad, rows * ch + (rows + 1) * pad), (205, 205, 210))
    for i, p in enumerate(images):
        im = Image.open(p).convert("RGB").resize((cw, ch))
        r, c = divmod(i, cols)
        sheet.paste(im, (pad + c * (cw + pad), pad + r * (ch + pad)))
    sheet.save(out_path.as_posix())
    print("contact sheet:", out_path, sheet.size)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--render-input", type=str, default=None)
    ap.add_argument("--job", type=str, default=None)
    ap.add_argument("--data-dir", type=str, default="../data")
    ap.add_argument("--out", type=str, default="/tmp/html-preview")
    ap.add_argument("--dpi", type=int, default=160)
    args = ap.parse_args()

    if args.job:
        ri = Path(args.data_dir) / "jobs" / args.job / "outline" / "render-input.json"
    elif args.render_input:
        ri = Path(args.render_input)
    else:
        raise SystemExit("provide --render-input or --job")

    outlines = _load_outlines(ri)
    print(f"loaded {len(outlines)} outlines from {ri}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / "deck.pptx"
    renderer = HtmlSlideRenderer(dpi=args.dpi)
    warnings = renderer.render(outlines, BrandDNA(), output_path)
    print("warnings:", json.dumps(warnings, indent=1) if warnings else "none")
    print("pptx:", output_path)
    print("html:", out_dir / "deck.html")
    _contact_sheet(out_dir, "deck", out_dir / "contact-sheet.png")


if __name__ == "__main__":
    main()
