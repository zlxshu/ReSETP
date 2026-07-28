#!/usr/bin/env python3
"""Copy only complete five-arm units from the invalidated archive into a dry-run CSV."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from table_common import ARMS


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_directory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(args.task_directory.glob("*/result.json"))]
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["instance_id"], int(row["seed"]))].append(row)
    selected = []
    for unit_rows in grouped.values():
        if {row["arm"] for row in unit_rows} == set(ARMS) and len(unit_rows) == len(ARMS):
            for row in unit_rows:
                copied = dict(row)
                copied["selected_final_attempt"] = True
                selected.append(copied)
    if not selected:
        parser.error("archive contains no complete five-arm unit")
    selected.sort(key=lambda row: (row["instance_id"], int(row["seed"]), ARMS.index(row["arm"])))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(selected[0]))
        writer.writeheader()
        writer.writerows(selected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
