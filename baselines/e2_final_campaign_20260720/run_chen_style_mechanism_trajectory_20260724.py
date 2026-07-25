#!/usr/bin/env python3
"""Observation replay for the disclosed 100-customer mechanism case."""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import sys


REPO = Path(__file__).resolve().parents[2]
ROOT = Path(__file__).parent / "algorithm_repair_diagnostic_20260724"
ENDPOINTS = ROOT / "chen_style_mechanism_case_results.json"
CASE = ROOT / "chen_style_mechanism_case_trajectory"
S3 = CASE / "representative_gate"
RUNNER = (
    Path(__file__).parent
    / "corrected_china81_rerun_20260723/"
    "run_corrected_s3_trajectories.py"
)


def _prepare_sealed_inputs() -> None:
    payload = json.loads(ENDPOINTS.read_text(encoding="utf-8"))
    if payload["verdict"] != "PASS_CHEN_STYLE_MECHANISM_CASE_ENDPOINT_GATE":
        raise RuntimeError("endpoint gate is not PASS")
    S3.mkdir(parents=True, exist_ok=True)
    rows = []
    for row in payload["rows"]:
        for arm in ("HGS-F", "HGS-E", "HGS-M", "MV-HGS-SP"):
            rows.append(
                {
                    "arm": arm,
                    "seed": row["seed"],
                    "cost": row[f"{arm}_cost"],
                    "status": "PASS",
                }
            )
    with (S3 / "raw_runs.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (S3 / "decision.json").write_text(
        json.dumps(
            {
                "verdict": "PASS_CHEN_STYLE_MECHANISM_CASE_ENDPOINT_GATE",
                "representative_instance_id": payload["instance_id"],
                "terminology": (
                    "post-audit mechanism-illustration case; "
                    "not representative"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    _prepare_sealed_inputs()
    spec = importlib.util.spec_from_file_location(
        "chen_style_observation_runner",
        RUNNER,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load observation runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.CAMPAIGN = CASE
    module.S3 = S3
    module.OUT = S3 / "trajectories"
    return int(module.main())


if __name__ == "__main__":
    raise SystemExit(main())
