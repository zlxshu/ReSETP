#!/usr/bin/env python3
"""Run the paper's collaboration and Shapley cost inputs sequentially."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
REPORT_ROOT = REPO / "solver/reports/paper_aligned_collaboration_20260829"
PYTHON = Path("/opt/anaconda3/bin/python3.13")
RUNNER = Path("solver/scripts/run_problem_hgs_private_technical.py")


@dataclass(frozen=True)
class Unit:
    name: str
    output: Path
    repeat: int
    enterprise_id: str | None
    mechanism_off: tuple[str, ...] = ()


def units() -> list[Unit]:
    result: list[Unit] = []
    for repeat in range(1, 4):
        result.extend(
            (
                Unit(
                    f"collaboration/independent/repeat_{repeat}",
                    REPORT_ROOT / "collaboration" / "independent" / f"repeat_{repeat}",
                    repeat,
                    None,
                    ("cross_depot",),
                ),
                Unit(
                    f"collaboration/joint/repeat_{repeat}",
                    REPORT_ROOT / "collaboration" / "joint" / f"repeat_{repeat}",
                    repeat,
                    None,
                ),
            )
        )
    for enterprise_id in ("ENT_A", "ENT_B"):
        for repeat in range(1, 4):
            result.append(
                Unit(
                    f"shapley/{enterprise_id}/repeat_{repeat}",
                    REPORT_ROOT / "shapley" / enterprise_id / f"repeat_{repeat}",
                    repeat,
                    enterprise_id,
                )
            )
    return result


def command(unit: Unit) -> list[str]:
    argv = [
        str(PYTHON),
        str(RUNNER),
        str(unit.output.relative_to(REPO)),
        "--instance-id",
        "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd",
        "--carbon-price",
        "0.07502",
        "--fleet-parameter-class",
        "endogenous",
        "--population-mode",
        "copied_hgs_defaults",
        "--charge-timing-policy",
        "cost_plus_carbon",
        "--frvcpy-charging",
        "--arm",
        unit.name.replace("/", "_"),
    ]
    if unit.enterprise_id is not None:
        argv.extend(("--enterprise-id", unit.enterprise_id))
    if unit.mechanism_off:
        argv.extend(("--mechanism-off", ",".join(unit.mechanism_off)))
    return argv


def runner_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = "solver/src:models/src:third_party/setp_hgs_kernel:."
    return environment


def main() -> int:
    results = []
    for unit in units():
        completed = subprocess.run(
            command(unit),
            cwd=REPO,
            env=runner_environment(),
            check=False,
        )
        accepted = json.loads(
            (unit.output / "decision.json").read_text(encoding="utf-8")
        )["accepted"]
        results.append(
            {
                "unit": unit.name,
                "repeat": unit.repeat,
                "return_code": completed.returncode,
                "accepted": accepted,
            }
        )
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    (REPORT_ROOT / "driver_summary.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0 if all(row["accepted"] for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
