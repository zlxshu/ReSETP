#!/usr/bin/env python3
"""Zero-search preflight for the Solomon external strong-baseline lane.

This audit deliberately does not import or invoke a solver.  It records local
dependency availability and the existence (not the contents) of the two
authorisation attestations that are created only after E7 and tool freezing.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
BUNDLES = REPO / "baselines/e2_alns/solomon_sintef_formal_bundles_20260717_v3"
CPU_PREFLIGHT = REPO / "baselines/e2_alns/solomon_cpu_preflight_20260717_v5"
E7_ATTESTATION = REPO / "baselines/e7_dynamic/e7_steps_1_to_6_attestation_20260717.json"
TOOL_FREEZE = REPO / "baselines/e2_alns/final_external_baseline_freeze/external_baseline_freeze.json"
DEFAULT_OUT = REPO / "baselines/e2_alns/e2_solomon_external_baseline_preflight_20260717"
SCHEMA = "resetp.e2.solomon-external-baseline-preflight.v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path: Path, payload: Any) -> None:
    atomic_text(path, json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n")


def atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(rows[0]) if rows else []
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    atomic_text(path, buffer.getvalue())


def discover_pyvrp() -> dict[str, Any]:
    spec = importlib.util.find_spec("pyvrp")
    if spec is None:
        return {
            "baseline_id": "PyVRP",
            "available": False,
            "version": "",
            "module_origin": "",
            "compatibility": "VRPTW_CAPABLE_BUT_NOT_INSTALLED",
        }
    try:
        version = importlib.metadata.version("pyvrp")
    except importlib.metadata.PackageNotFoundError:
        version = "UNKNOWN"
    return {
        "baseline_id": "PyVRP",
        "available": True,
        "version": version,
        "module_origin": str(Path(spec.origin).resolve()) if spec.origin else "",
        "compatibility": "REQUIRES_FROZEN_API_AND_OBJECTIVE_ADAPTER",
    }


def discover_hgs_vrptw() -> dict[str, Any]:
    configured = os.environ.get("RESET_HGS_VRPTW_BINARY", "")
    binary = Path(configured).expanduser() if configured else None
    if binary is None or not binary.is_file():
        located = shutil.which("hgs-vrptw")
        binary = Path(located) if located else None
    available = bool(binary and binary.is_file())
    return {
        "baseline_id": "HGS-VRPTW",
        "available": available,
        "version": "UNFROZEN" if available else "",
        "module_origin": str(binary.resolve()) if available and binary else "",
        "compatibility": (
            "REQUIRES_FROZEN_VRPTW_CLI_ADAPTER"
            if available
            else "OFFICIAL_HGS_CVRP_IS_NOT_A_VRPTW_BASELINE"
        ),
    }


def zero_search_gate_failures() -> list[str]:
    failures: list[str] = []
    bundle_decision = BUNDLES / "decision.json"
    bundle_manifest = BUNDLES / "manifest.json"
    cpu_decision = CPU_PREFLIGHT / "decision.json"
    for path in (bundle_decision, bundle_manifest, cpu_decision):
        if not path.is_file():
            failures.append(f"MISSING_ZERO_SEARCH_GATE:{path.relative_to(REPO)}")
    if bundle_decision.is_file():
        payload = json.loads(bundle_decision.read_text(encoding="utf-8"))
        if payload.get("verdict") != "PASS_SOLOMON_SINTEF_BUNDLE_GATE" or payload.get("search_evaluations") != 0:
            failures.append("INVALID_SINTEF_BUNDLE_GATE")
    if bundle_manifest.is_file():
        payload = json.loads(bundle_manifest.read_text(encoding="utf-8"))
        if payload.get("bundle_count") != 56 or payload.get("search_performed") is not False:
            failures.append("INVALID_SINTEF_BUNDLE_MANIFEST")
    if cpu_decision.is_file():
        payload = json.loads(cpu_decision.read_text(encoding="utf-8"))
        if payload.get("verdict") != "PASS_SOLOMON_CPU_CONTRACT":
            failures.append("INVALID_CPU_PREFLIGHT")
    return failures


def build_preflight() -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    tools = [discover_pyvrp(), discover_hgs_vrptw()]
    failures = zero_search_gate_failures()
    if not E7_ATTESTATION.is_file():
        failures.append("E7_STEPS_1_TO_6_ATTESTATION_MISSING")
    if not TOOL_FREEZE.is_file():
        failures.append("EXTERNAL_BASELINE_TOOL_FREEZE_MISSING")
    if not any(row["available"] for row in tools):
        failures.append("NO_COMPATIBLE_EXTERNAL_STRONG_BASELINE_INSTALLED")

    metadata = {
        "schema_version": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_executable": str(Path(sys.executable).resolve()),
        "bundle_root": str(BUNDLES.relative_to(REPO)),
        "bundle_manifest_sha256": sha256(BUNDLES / "manifest.json") if (BUNDLES / "manifest.json").is_file() else "",
        "cpu_preflight": str(CPU_PREFLIGHT.relative_to(REPO)),
        "e7_attestation_path": str(E7_ATTESTATION.relative_to(REPO)),
        "e7_attestation_content_read": False,
        "tool_freeze_path": str(TOOL_FREEZE.relative_to(REPO)),
        "tool_freeze_content_read": False,
        "search_performed": False,
        "search_evaluations": 0,
        "fairness_axes": {
            "external": "same-machine single-thread wall-clock",
            "internal": "same complete-candidate evaluation budget",
            "must_be_separate": True,
        },
    }
    rows = [
        {
            **row,
            "e7_attestation_exists": E7_ATTESTATION.is_file(),
            "tool_freeze_exists": TOOL_FREEZE.is_file(),
            "search_evaluations": 0,
        }
        for row in tools
    ]
    decision = {
        "verdict": "PASS_EXTERNAL_BASELINE_PREFLIGHT" if not failures else "HALT_EXTERNAL_BASELINE_PREREQUISITES",
        "failures": failures,
        "formal_search_authorized": False,
        "search_evaluations": 0,
        "external_and_internal_axes_separated": True,
    }
    return metadata, rows, decision


def write_evidence(out: Path, metadata: dict[str, Any], rows: list[dict[str, Any]], decision: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    if any(item for item in out.iterdir() if not item.name.startswith("._")):
        raise RuntimeError(f"refuse to overwrite non-empty preflight output: {out}")
    atomic_json(out / "metadata.json", metadata)
    atomic_csv(out / "raw_runs.csv", rows)
    atomic_json(out / "decision.json", decision)
    atomic_text(
        out / "report.md",
        "# Solomon现代强基线零搜索预检\n\n"
        f"判定：`{decision['verdict']}`。本预检没有导入或调用求解器，搜索评价为0。"
        "PyVRP/HGS类外部强基线只按同机、单线程、相同墙钟上限比较；本文ALNS、LNS与消融仍按"
        "相同完整候选评价预算比较，两类结果不得混成同一公平轴。\n\n"
        "官方HGS-CVRP只支持CVRP，不能直接作为Solomon硬时间窗基线。若采用HGS，必须另行冻结"
        "一个明确支持VRPTW的实现及命令适配器。PyVRP也须冻结版本、源码哈希、建模API、距离"
        "缩放与固定车辆成本的字典序实现，再由独立双精度评价器复算输出路线。\n\n"
        "当前缺口：" + ("、".join(decision["failures"]) if decision["failures"] else "无") + "。\n",
    )
    subprocess.run(["dot_clean", "-m", str(out)], check=True)
    sidecars = list(out.rglob("._*"))
    if sidecars:
        raise RuntimeError(f"AppleDouble remains: {sidecars}")
    hashes = {
        str(path.relative_to(out)): sha256(path)
        for path in sorted(out.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }
    atomic_json(out / "artifact_hashes.json", hashes)
    subprocess.run(["dot_clean", "-m", str(out)], check=True)
    if list(out.rglob("._*")):
        raise RuntimeError("AppleDouble remains after writing the artifact manifest")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--write-evidence", action="store_true")
    args = parser.parse_args()
    metadata, rows, decision = build_preflight()
    if args.write_evidence:
        write_evidence(args.output, metadata, rows, decision)
    print(canonical_json(decision))
    return 0 if decision["verdict"] == "PASS_EXTERNAL_BASELINE_PREFLIGHT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
