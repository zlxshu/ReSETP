#!/usr/bin/env python3
"""Export the simulation-instance node table (52 rows) as a two-column tex body.

Read-only over sealed inputs; no optimization, no evaluator import.
"""
import csv
from pathlib import Path

ROOT = Path("/Volumes/移动硬盘（512G）/ReSETP")
IID = "cn-prd-50c-01-V2-LOCATIONS"
ORDERS = ROOT / "data/ChinaInstances/china81_order_attributes_mc001_v1_20260718/orders.csv"
NODES = (ROOT / "data/ChinaInstances/china81_local_directed_matrices_v9_20260718"
         / "instances" / IID / "cv" / "nodes.csv")
OUT = Path(__file__).parent / "instance_table_body.tex"


def hhmm(minute: float) -> str:
    m = int(round(minute))
    return f"{m // 60:02d}:{m % 60:02d}"


rows = []
with ORDERS.open() as f:
    for r in csv.DictReader(f):
        if r["instance_id"] != IID:
            continue
        num = int(r["customer_id"].lstrip("C"))
        rows.append((
            num,
            f"{float(r['longitude']):.4f}",
            f"{float(r['latitude']):.4f}",
            f"{hhmm(float(r['time_window_early_minute']))}--{hhmm(float(r['time_window_late_minute']))}",
            f"{int(float(r['demand_kg']))}",
            f"{int(float(r['service_minutes']))}",
        ))
rows.sort()
assert len(rows) == 50, len(rows)

depots = []
with NODES.open() as f:
    for r in csv.DictReader(f):
        if r["node_type"] != "depot":
            continue
        num = {"D_guangzhou": 51, "D_shenzhen": 52}[r["node_id"]]
        depots.append((
            num,
            f"{float(r['longitude']):.4f}",
            f"{float(r['latitude']):.4f}",
            "06:00--22:00",
            "-",
            "-",
        ))
depots.sort()
assert len(depots) == 2, depots

all_rows = rows + depots  # 1..50 then 51,52
left, right = all_rows[:26], all_rows[26:]
lines = []
for i in range(26):
    a = left[i]
    b = right[i] if i < len(right) else ("", "", "", "", "", "")
    lines.append(
        f"{a[0]} & {a[1]} & {a[2]} & {a[3]} & {a[4]} & {a[5]} & "
        f"{b[0]} & {b[1]} & {b[2]} & {b[3]} & {b[4]} & {b[5]} \\\\"
    )
OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"wrote {OUT} rows={len(all_rows)} (left 26 / right {len(right)})")
print("spot check first/last:", all_rows[0], all_rows[-1])
