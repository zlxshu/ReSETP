#!/usr/bin/env python3
"""Run and aggregate the approved 6-instance by 10-seed E6-A panel."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
for path in (HERE, REPO / "solver/src", REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_e6a_formal as formal
import run_pilot06_direct_15 as runner

INSTANCES = tuple(formal.APPROVED_MAPPING_SHA256)
SEEDS = tuple(range(1, 11))


def panel_units(output: Path) -> list[tuple[str, int, Path]]:
    return [
        (instance, seed, output / "units" / instance / f"seed_{seed:02d}")
        for instance in INSTANCES
        for seed in SEEDS
    ]


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_unit(
    instance: str, seed: int, output: Path
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    if not runner.verify_manifest(output):
        raise RuntimeError("artifact manifest mismatch")
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    decision = json.loads((output / "decision.json").read_text(encoding="utf-8"))
    expected = (
        instance,
        seed,
        "FORMAL_PANEL_UNIT",
        formal.FORMAL_ITERATIONS,
        formal.FORMAL_ARCHIVE,
        formal.FORMAL_SP_SECONDS,
    )
    observed = (
        metadata["instance_id"],
        metadata["seed"],
        metadata["evidence_role"],
        metadata["iterations_per_view"],
        metadata["archive_candidates_per_view"],
        metadata["route_pool_sp_seconds"],
    )
    if observed != expected:
        raise RuntimeError("unit metadata differs from approved formal contract")
    if (
        decision["status"] != "PASS_E6A_FORMAL_UNIT"
        or decision["coalitions_solved"] != 15
        or not decision["all_coalitions_legal"]
    ):
        raise RuntimeError("unit decision is not technically complete")
    with (output / "raw_runs.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 15:
        raise RuntimeError("unit raw_runs.csv does not contain 15 coalitions")
    return decision, rows


def _unit_command(instance: str, seed: int, output: Path) -> list[str]:
    return [
        sys.executable,
        str(HERE / "run_e6a_formal.py"),
        "--instance",
        instance,
        "--seed",
        str(seed),
        "--output",
        str(output),
    ]


def _failed_unit(
    instance: str,
    seed: int,
    output: Path,
    command: list[str],
    error: str,
    result: Any = None,
) -> dict[str, Any]:
    _atomic_write(
        output / "last_error.json",
        _json_text(
            {
                "instance_id": instance,
                "seed": seed,
                "error": error,
                "returncode": None if result is None else result.returncode,
                "stdout": "" if result is None else result.stdout,
                "stderr": "" if result is None else result.stderr,
                "command": command,
            }
        ),
    )
    return {"instance_id": instance, "seed": seed, "ok": False, "error": error}


def run_subprocess_unit(instance: str, seed: int, output: Path) -> dict[str, Any]:
    command = _unit_command(instance, seed, output)
    environment = os.environ.copy()
    environment.update(
        OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        VECLIB_MAXIMUM_THREADS="1",
        PYTHONHASHSEED="0",
    )
    try:
        result = subprocess.run(
            command,
            cwd=REPO,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        error = f"{type(exc).__name__}: {exc}"
        return _failed_unit(instance, seed, output, command, error)
    error = ""
    if result.returncode == 0:
        try:
            validate_unit(instance, seed, output)
        except Exception as exc:  # noqa: BLE001 - preserve exact failed unit
            error = f"{type(exc).__name__}: {exc}"
    else:
        error = f"child exit {result.returncode}"
    if error:
        return _failed_unit(instance, seed, output, command, error, result)
    (output / "last_error.json").unlink(missing_ok=True)
    return {"instance_id": instance, "seed": seed, "ok": True}


def finalize_panel(output: Path) -> dict[str, Any]:
    decisions: list[dict[str, Any]] = []
    rows: list[dict[str, str]] = []
    unit_hashes: dict[str, str] = {}
    for instance, seed, unit_output in panel_units(output):
        decision, unit_rows = validate_unit(instance, seed, unit_output)
        decisions.append(decision)
        rows.extend(unit_rows)
        manifest = unit_output / "artifact_hashes.json"
        unit_hashes[str(manifest.relative_to(output))] = runner.sha256(manifest)

    summaries = [
        {
            "instance_id": row["instance_id"],
            "seed": row["seed"],
            "grand_saving_percent": row["grand_saving_percent"],
            "grand_cross_contractor_customers": row["grand_cross_contractor_customers"],
            "core_nonempty": row["method_A_core_nonempty"],
            "shapley_in_core": row["method_A_shapley_in_core"],
        }
        for row in decisions
    ]
    saving = [float(row["grand_saving_percent"]) for row in decisions]
    panel_decision = {
        "schema": "resetp.e6a-panel-decision.v1",
        "status": "PASS_E6A_PANEL_COMPLETE",
        "unit_count": len(decisions),
        "coalition_row_count": len(rows),
        "instances": list(INSTANCES),
        "seeds": list(SEEDS),
        "descriptive_summary": {
            "grand_saving_percent_min": min(saving),
            "grand_saving_percent_mean": sum(saving) / len(saving),
            "grand_saving_percent_max": max(saving),
            "core_nonempty_units": sum(
                row["method_A_core_nonempty"] for row in decisions
            ),
            "shapley_in_core_units": sum(
                row["method_A_shapley_in_core"] for row in decisions
            ),
        },
        "units": summaries,
    }

    csv_buffer = io.StringIO(newline="")
    writer = csv.DictWriter(csv_buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    report_lines = [
        "# E6-A formal panel",
        "",
        "状态：PASS_E6A_PANEL_COMPLETE。",
        "",
        f"完整单元 {len(decisions)}/60，联盟结果 {len(rows)}/900。",
        (
            "大联盟相对四家单干成本合计的变化范围为 "
            f"{min(saving):.3f}% 至 {max(saving):.3f}%，均值 {sum(saving) / len(saving):.3f}%。"
        ),
        (
            f"核非空 {panel_decision['descriptive_summary']['core_nonempty_units']}/60；"
            f"Shapley 在核内 {panel_decision['descriptive_summary']['shapley_in_core_units']}/60。"
        ),
        "",
        "| 算例 | seed | 合作节省/% | 跨承包商客户 | 核非空 | Shapley在核内 |",
        "|---|---:|---:|---:|---|---|",
    ]
    report_lines.extend(
        f"| {row['instance_id']} | {row['seed']} | {float(row['grand_saving_percent']):.3f} | "
        f"{row['grand_cross_contractor_customers']} | {row['core_nonempty']} | "
        f"{row['shapley_in_core']} |"
        for row in summaries
    )
    created = datetime.now(UTC).isoformat()
    complete = {
        "schema": "resetp.e6a-panel-complete.v1",
        "status": "PASS_E6A_PANEL_COMPLETE",
        "created_at_utc": created,
        "unit_count": 60,
        "unit_artifact_hashes": unit_hashes,
    }
    contents = {
        "panel_raw_runs.csv": csv_buffer.getvalue(),
        "panel_decision.json": _json_text(panel_decision),
        "report.md": "\n".join(report_lines) + "\n",
        "panel_complete.json": _json_text(complete),
    }
    manifest = _json_text(
        {
            "schema": "resetp.artifact-hashes.v1",
            "artifacts": {name: _sha256_text(text) for name, text in contents.items()},
        }
    )
    for name in ("panel_raw_runs.csv", "panel_decision.json", "report.md"):
        _atomic_write(output / name, contents[name])
    _atomic_write(output / "artifact_hashes.json", manifest)
    _atomic_write(output / "panel_complete.json", contents["panel_complete.json"])
    return panel_decision


def completed_panel(output: Path) -> dict[str, Any] | None:
    terminal = output / "panel_complete.json"
    if not terminal.exists():
        return None
    try:
        if not runner.verify_manifest(output):
            raise RuntimeError("panel artifact manifest mismatch")
        complete = json.loads(terminal.read_text(encoding="utf-8"))
        for instance, seed, unit_output in panel_units(output):
            validate_unit(instance, seed, unit_output)
            name = str((unit_output / "artifact_hashes.json").relative_to(output))
            if (
                runner.sha256(unit_output / "artifact_hashes.json")
                != complete["unit_artifact_hashes"][name]
            ):
                raise RuntimeError("unit manifest changed after panel completion")
        return json.loads((output / "panel_decision.json").read_text(encoding="utf-8"))
    except (OSError, KeyError, ValueError, RuntimeError):
        terminal.unlink()
        return None


def run_panel(output: Path, workers: int = 4) -> tuple[int, dict[str, Any]]:
    complete = completed_panel(output)
    if complete is not None:
        return 0, complete
    output.mkdir(parents=True, exist_ok=True)
    results = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(run_subprocess_unit, instance, seed, unit_output): (
                instance,
                seed,
            )
            for instance, seed, unit_output in panel_units(output)
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    failed = [row for row in results if not row["ok"]]
    if failed:
        return 1, {"status": "HALT_E6A_PANEL_UNIT_FAILURE", "failed_units": failed}
    return 0, finalize_panel(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    code, result = run_panel(args.output, args.workers)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
