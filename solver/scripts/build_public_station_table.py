#!/usr/bin/env python3
"""生成公共充电站信息表（用户 2026-09-06 指出表 3 缺 97 个公共充电站节点）。

只读算例 nodes.csv（node_type=station），按 node_id 排序编为 S01–S97，输出三栏并排的 supertabular* 片段
docs/paper_v2/generated_tables/public_station_table.tex，并写编号↔OSM 节点对照 public_station_mapping.csv。
功率、桩数、服务费在表 5，不重复。
"""
from __future__ import annotations
import csv
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
NODES = REPO / "data/ChinaInstances/china81_final_suite_v2_20260815/instances/cn-jjj-50c-01-DEPOTSEARCH-d996f755bd/nodes.csv"
OUT = REPO / "docs/paper_v2/generated_tables/public_station_table.tex"
MAP = REPO / "docs/paper_v2/generated_tables/public_station_mapping.csv"
rows = sorted((r for r in csv.DictReader(open(NODES, encoding="utf-8")) if r["node_type"] == "station"), key=lambda r: r["node_id"])
assert len(rows) == 97, len(rows)
labels = [(f"S{i+1:02d}", r) for i, r in enumerate(rows)]
with open(MAP, "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f); w.writerow(["label", "node_id", "source_identity", "longitude", "latitude"])
    for lab, r in labels: w.writerow([lab, r["node_id"], r["source_identity"], r["longitude"], r["latitude"]])
n = len(labels); per = (n + 2) // 3
lines = []
for i in range(per):
    cells = []
    for g in range(3):
        k = i + g * per
        if k < n:
            lab, r = labels[k]
            cells += [lab, f"{float(r['longitude']):.4f}", f"{float(r['latitude']):.4f}"]
        else:
            cells += ["", "", ""]
    lines.append(" & ".join(cells) + r"\\")
OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"已写出 {OUT}（{per} 行 × 3 栏）与 {MAP}")
