#!/usr/bin/env python3
"""在抽出的文本里检索关键词，并给出 PDF 物理页号与该页头两行（用于定位版面印刷页码）。

只读。用法：python3 grep_pages.py <corpus_dir> <file_stem> <regex> [context_chars]
"""
import os
import re
import sys


def pages(path):
    raw = open(path, encoding="utf-8", errors="replace").read()
    return raw.split("\f")


def main():
    corpus, stem, pat = sys.argv[1], sys.argv[2], sys.argv[3]
    ctx = int(sys.argv[4]) if len(sys.argv) > 4 else 260
    path = os.path.join(corpus, stem + ".txt")
    pgs = pages(path)
    rx = re.compile(pat, re.I)
    for i, p in enumerate(pgs, 1):
        flat = re.sub(r"[ \t]+", " ", p)
        for m in rx.finditer(flat):
            s = max(0, m.start() - ctx)
            head = " | ".join(x.strip() for x in p.strip().splitlines()[:2])[:120]
            print(f"=== PDFpage {i} | head: {head}")
            print(flat[s:m.end() + ctx].replace("\n", " "))
            print()


if __name__ == "__main__":
    main()
