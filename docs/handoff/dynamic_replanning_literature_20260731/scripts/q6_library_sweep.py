#!/usr/bin/env python3
"""问题 6 的全库精确扫描（只读）。

Spotlight (`mdfind`) 对中文和词干做模糊匹配，命中数不可直接当证据。
本脚本把整个 Zotero 库的 PDF 逐个抽成文本，用精确正则统计：
  A) 时变/电网碳强度类词
  B) 预测/实际 对举类词
  C) 二者在同一篇内共现
输出 q6_library_sweep.json，供报告里的“未找到”给出可核对的分母。

用法：python3 q6_library_sweep.py <outjson>
"""
import json
import os
import re
import subprocess
import sys
import tempfile

BASE = "/Users/zhouleixishu/Zotero/storage"

A = [r"carbon intensity", r"grid emission factor", r"emission factor of the grid",
     r"marginal emission", r"time-varying carbon", r"碳强度", r"电网碳", r"排放因子"]
B = [r"forecast", r"predicted carbon", r"day-ahead", r"prediction error",
     r"预测", r"日前", r"事后结算", r"实际碳"]
# 更严的共现：预测/实际 直接修饰碳强度或排放因子
C = [r"forecast(ed)?\s+(average\s+|marginal\s+)?carbon intensity",
     r"predicted\s+(average\s+|marginal\s+)?carbon intensity",
     r"carbon intensity\s+(forecast|prediction)",
     r"forecast(ed)?\s+emission factor", r"emission factor\s+forecast",
     r"predicted\s+emission factor", r"actual\s+emission factor",
     r"realized\s+carbon", r"actual carbon intensity",
     r"碳强度预测", r"预测碳强度", r"预测的碳强度",
     r"碳排放因子预测", r"预测排放因子", r"预测碳排放因子", r"实际碳强度"]


def norm(s):
    s = ''.join(chr(ord(c) - 0xFEE0) if 0xFF01 <= ord(c) <= 0xFF5E else c for c in s)
    return re.sub(r"\s+", " ", s)


def main(out):
    pdfs = []
    for root, _dirs, files in os.walk(BASE):
        for f in files:
            if f.lower().endswith(".pdf") and not f.startswith("._"):
                pdfs.append(os.path.join(root, f))
    pdfs.sort()
    res = {"n_pdfs": len(pdfs), "unreadable": [], "hits_A": [], "hits_B": [],
           "hits_A_and_B": [], "hits_C": []}
    tmp = tempfile.mkdtemp()
    dst = os.path.join(tmp, "x.txt")
    for i, p in enumerate(pdfs):
        try:
            subprocess.run(["pdftotext", "-layout", p, dst], check=False,
                           timeout=120, stderr=subprocess.DEVNULL)
        except Exception:
            res["unreadable"].append(p)
            continue
        if not os.path.exists(dst):
            res["unreadable"].append(p)
            continue
        raw = open(dst, encoding="utf-8", errors="replace").read()
        if len(raw.strip()) < 1500:
            res["unreadable"].append(p)
            os.remove(dst)
            continue
        t = norm(raw)
        tc = re.sub(r"\s+", "", norm(raw))
        a = [k for k in A if (re.search(k, t, re.I) if k.isascii() else k in tc)]
        b = [k for k in B if (re.search(k, t, re.I) if k.isascii() else k in tc)]
        c = [k for k in C if (re.search(k, t, re.I) if k.isascii() else k in tc)]
        rel = os.path.relpath(p, BASE)
        if a:
            res["hits_A"].append({"file": rel, "terms": a})
        if b:
            res["hits_B"].append({"file": rel, "terms": b})
        if a and b:
            res["hits_A_and_B"].append({"file": rel, "A": a, "B": b})
        if c:
            res["hits_C"].append({"file": rel, "terms": c})
        os.remove(dst)
        if (i + 1) % 50 == 0:
            print(f"  ...{i+1}/{len(pdfs)}", flush=True)
    for k in ("hits_A", "hits_B", "hits_A_and_B", "hits_C"):
        print(f"{k}: {len(res[k])}")
    print(f"unreadable/empty text layer: {len(res['unreadable'])}")
    print("=== hits_C (预测/实际 直接修饰碳强度或排放因子) ===")
    for h in res["hits_C"]:
        print("  ", h["file"], h["terms"])
    with open(out, "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(sys.argv[1])
