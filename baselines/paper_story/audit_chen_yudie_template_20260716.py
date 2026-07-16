#!/usr/bin/env python3
"""Extract reproducible structural and typography facts from the Chen Yudie PDF.

This is a descriptive audit only. It records layout/style facts and short labels;
it does not reproduce the article text.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import fitz


PDF = Path("/Users/zhouleixishu/Zotero/storage/AYDB6KXP/陈雨蝶 等 _ 2025 _ 双碳背景下复杂冷链物流模型及求解算法.pdf")
OUT = Path("docs/handoff/chen_yudie_2025_typography_audit_20260716.json")

HEADING_RE = re.compile(r"^(摘要|关键词|[1-5](?:\.\d+(?:\.\d+)?)?\s*[^\d].*|图\s*\d+.*|表\s*\d+.*)$")
EQNO_RE = re.compile(r"^\(\d+\)$")


def rounded(v: float) -> float:
    return round(float(v), 2)


def main() -> None:
    doc = fitz.open(PDF)
    font_size_chars: Counter[tuple[str, float]] = Counter()
    page_modes: dict[str, list[dict]] = {}
    labels: list[dict] = []
    eq_numbers: list[dict] = []

    for pno, page in enumerate(doc, start=1):
        page_counter: Counter[tuple[str, float]] = Counter()
        data = page.get_text("dict")
        for block in data.get("blocks", []):
            if "lines" not in block:
                continue
            for line in block["lines"]:
                spans = line.get("spans", [])
                line_text = "".join(s.get("text", "") for s in spans).strip()
                if not line_text:
                    continue
                for span in spans:
                    text = span.get("text", "")
                    if not text.strip():
                        continue
                    key = (span.get("font", ""), rounded(span.get("size", 0)))
                    n = len(text.strip())
                    font_size_chars[key] += n
                    page_counter[key] += n
                compact = re.sub(r"\s+", " ", line_text)
                if HEADING_RE.match(compact) and len(compact) <= 80:
                    lead = max(spans, key=lambda s: len(s.get("text", "")))
                    labels.append({
                        "page": pno,
                        "text": compact[:80],
                        "font": lead.get("font", ""),
                        "size_pt": rounded(lead.get("size", 0)),
                        "bbox": [rounded(x) for x in line.get("bbox", (0, 0, 0, 0))],
                    })
                if EQNO_RE.match(compact):
                    lead = spans[0]
                    eq_numbers.append({
                        "page": pno,
                        "number": compact,
                        "font": lead.get("font", ""),
                        "size_pt": rounded(lead.get("size", 0)),
                        "bbox": [rounded(x) for x in line.get("bbox", (0, 0, 0, 0))],
                    })
        page_modes[str(pno)] = [
            {"font": f, "size_pt": s, "characters": n}
            for (f, s), n in page_counter.most_common(8)
        ]

    payload = {
        "source": str(PDF),
        "page_count": len(doc),
        "page_size_pt": [rounded(doc[0].rect.width), rounded(doc[0].rect.height)],
        "dominant_font_size_pairs": [
            {"font": f, "size_pt": s, "characters": n}
            for (f, s), n in font_size_chars.most_common(30)
        ],
        "page_modes": page_modes,
        "detected_labels": labels,
        "equation_numbers": eq_numbers,
        "counts": {
            "detected_equation_numbers": len(eq_numbers),
            "detected_figure_captions": sum(1 for x in labels if x["text"].startswith("图")),
            "detected_table_captions": sum(1 for x in labels if x["text"].startswith("表")),
        },
        "interpretation_warning": "PDF contains CNKI/header/overlay fonts. Use semantic labels and dominant body spans, not pdffonts alone, to infer article typography.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["counts"], ensure_ascii=False))
    print(OUT)


if __name__ == "__main__":
    main()
