#!/usr/bin/env python3
"""Audit final-size fonts, vector content and colour encoding of SETP figures."""

from __future__ import annotations

import json
import re
from pathlib import Path

import fitz


ROOT = Path(__file__).resolve().parents[2]
PAPER = ROOT / "docs/paper_submission_final/paper_main.tex"
OUT = ROOT / "docs/paper_submission_final/visual_contract_audit_20260716.json"
TEXT_WIDTH_PT = (210.0 - 22.5 - 22.5) * 72.0 / 25.4
MIN_FINAL_FONT_PT = 7.9  # numerical tolerance around the journal's nominal 8 pt
EXPECTED_FONTS = {"TimesNewRomanPSMT", "STSongti-SC-Regular"}


def is_non_gray(colour: tuple[float, ...] | None) -> bool:
    if colour is None or len(colour) < 3:
        return False
    red, green, blue = colour[:3]
    return max(red, green, blue) - min(red, green, blue) > 0.03


def main() -> None:
    tex = PAPER.read_text(encoding="utf-8")
    inclusions = re.findall(
        r"\\includegraphics\[width=([0-9.]+)\\linewidth\]\{([^}]+\.pdf)\}",
        tex,
    )
    if len(inclusions) != 6:
        raise SystemExit(f"expected 6 active external PDF figures, found {len(inclusions)}")

    rows: list[dict[str, object]] = []
    failures: list[str] = []
    for fraction_text, relative in inclusions:
        fraction = float(fraction_text)
        path = PAPER.parent / relative
        document = fitz.open(path)
        page = document[0]
        spans = [
            span
            for block in page.get_text("dict")["blocks"]
            for line in block.get("lines", [])
            for span in line.get("spans", [])
            if span.get("text", "").strip()
        ]
        if not spans:
            failures.append(f"{path.name}: no extractable figure text")
            continue
        source_min = min(float(span["size"]) for span in spans)
        scale = fraction * TEXT_WIDTH_PT / float(page.rect.width)
        final_min = source_min * scale
        fonts = sorted({str(span["font"]).split("+")[-1] for span in spans})
        drawings = page.get_drawings()
        coloured = any(
            is_non_gray(drawing.get("color")) or is_non_gray(drawing.get("fill"))
            for drawing in drawings
        )
        images = len(page.get_images(full=True))
        font_ok = set(fonts).issubset(EXPECTED_FONTS)
        row = {
            "figure": path.name,
            "include_fraction": fraction,
            "native_width_pt": round(float(page.rect.width), 3),
            "source_min_font_pt": round(source_min, 3),
            "estimated_final_min_font_pt": round(final_min, 3),
            "fonts": fonts,
            "font_ok": font_ok,
            "has_non_gray_colour": coloured,
            "embedded_raster_image_count": images,
        }
        rows.append(row)
        if final_min < MIN_FINAL_FONT_PT:
            failures.append(f"{path.name}: final minimum text {final_min:.3f} pt < 7.9 pt")
        if not font_ok:
            failures.append(f"{path.name}: unexpected fonts {fonts}")
        if not coloured:
            failures.append(f"{path.name}: no non-gray colour encoding")
        if images:
            failures.append(f"{path.name}: contains {images} raster image objects")

    result = {
        "status": "PASS" if not failures else "FAIL",
        "text_width_pt": round(TEXT_WIDTH_PT, 3),
        "nominal_final_figure_text_pt": 8.0,
        "tolerance_floor_pt": MIN_FINAL_FONT_PT,
        "figures": rows,
        "failures": failures,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
