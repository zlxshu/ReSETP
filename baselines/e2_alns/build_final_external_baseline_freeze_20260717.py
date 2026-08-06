#!/usr/bin/env python3
"""Create the immutable PyVRP freeze only after E7 steps 1--6 close."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping


REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "baselines/e2_alns/final_external_baseline_freeze/external_baseline_freeze.json"
PROBE = REPO / "baselines/e2_alns/pyvrp_0134_tool_probe_20260717_v3"
WHEEL = (
    REPO
    / "baselines/e2_alns/external_tools/pyvrp-0.13.4/"
    "pyvrp-0.13.4-cp313-cp313-macosx_11_0_arm64.whl"
)
RUNNER = REPO / "baselines/e2_alns/run_solomon_external_strong_baselines_20260717.py"
PREFLIGHT = REPO / "baselines/e2_alns/audit_solomon_external_strong_baseline_preflight_20260717.py"
PROBE_SOURCE = REPO / "baselines/e2_alns/probe_pyvrp_0134_api_20260717.py"
FORMAL_HELPER = REPO / "baselines/e2_alns/run_solomon_sintef_formal_20260717.py"
BUILDER = Path(__file__).resolve()
E7_ATTESTATION = REPO / "baselines/e7_dynamic/e7_steps_1_to_6_attestation_20260717.json"
E7_BUILDER = REPO / "baselines/e7_dynamic/build_e7_steps_1_to_6_attestation_20260717.py"
CPU_CONTRACT = REPO / "baselines/e2_alns/solomon_cpu_contract_20260717.json"
EXPECTED_PYTHON = REPO / "build/python_envs/pyvrp-ils-0.13.4/bin/python"
EXPECTED_VERSION = "0.13.4"
EXPECTED_WHEEL_SHA256 = "49b84319fcfcd2206c05f55e970d090ab054d577a1d82cbac276d376fe89970c"
HISTORICAL_PROBE_SOURCE_SHA256 = "a3b313c73e96938b02d17e81f6bbaf4c679b35675b5edf8d1456ee2d8fd45e5d"
CURRENT_PROBE_SOURCE_SHA256 = "378152c847fe9d6d4b16c53cc0ec1f28e7b8c8995b7c45d86048de8ebfdc3976"
CURRENT_ADAPTER_SHA256 = "08a541b77a222fb1cfba7121a850b0d3ac7216c8cb001302bea39d04c4f19a67"
AUTHORIZATION = "CREATE_FINAL_PYVRP_FREEZE_AFTER_E7_STEPS_1_TO_6"
SCHEMA = "resetp.e2.external-baseline-freeze.v1"
REFERENCE_SECONDS_1000_CLIENTS = 7200.0
REFERENCE_CLIENTS = 1000
TARGET_CLIENTS = 100
PASSMARK_TIME_FACTOR = 1.837
STANDARDIZED_SECONDS = REFERENCE_SECONDS_1000_CLIENTS * TARGET_CLIENTS / REFERENCE_CLIENTS
LOCAL_SECONDS = STANDARDIZED_SECONDS / PASSMARK_TIME_FACTOR


class FreezeError(RuntimeError):
    """A prerequisite for the immutable final freeze is not satisfied."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def verify_hash_map(root: Path, records: Mapping[str, str]) -> None:
    if not records:
        raise FreezeError(f"empty artifact manifest: {root}")
    for relative, expected in records.items():
        path = root / relative
        if not path.is_file() or sha256(path) != expected:
            raise FreezeError(f"artifact hash differs: {path}")


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise FreezeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def verify_probe() -> dict[str, Any]:
    required = ("metadata.json", "raw_runs.csv", "decision.json", "artifact_hashes.json", "report.md")
    if not all((PROBE / name).is_file() for name in required):
        raise FreezeError("PyVRP v3 candidate tool probe is incomplete")
    verify_hash_map(PROBE, json.loads((PROBE / "artifact_hashes.json").read_text(encoding="utf-8")))
    metadata = json.loads((PROBE / "metadata.json").read_text(encoding="utf-8"))
    decision = json.loads((PROBE / "decision.json").read_text(encoding="utf-8"))
    if decision.get("verdict") != "PASS_PYVRP_0134_CANDIDATE_TOOL_PROBE":
        raise FreezeError("PyVRP candidate tool probe did not pass")
    if decision.get("formal_search_authorized") is not False:
        raise FreezeError("candidate probe unexpectedly authorizes search")
    if decision.get("time_to_best_extractor_verified") is not True:
        raise FreezeError("time-to-best extractor is not verified")
    if metadata.get("pyvrp_version") != EXPECTED_VERSION:
        raise FreezeError("candidate probe version differs")
    if metadata.get("wheel_sha256") != EXPECTED_WHEEL_SHA256:
        raise FreezeError("candidate probe wheel differs")
    if metadata.get("adapter_sha256") != CURRENT_ADAPTER_SHA256:
        raise FreezeError("historical candidate probe adapter anchor differs")
    if sha256(RUNNER) != CURRENT_ADAPTER_SHA256:
        raise FreezeError("current external adapter differs from the W2 anchor")
    if metadata.get("probe_sha256") != HISTORICAL_PROBE_SOURCE_SHA256:
        raise FreezeError("historical candidate probe source anchor differs")
    if sha256(PROBE_SOURCE) != CURRENT_PROBE_SOURCE_SHA256:
        raise FreezeError("current probe source differs from the W2 anchor")
    return metadata


def verify_e7_attestation() -> dict[str, Any]:
    if not E7_ATTESTATION.is_file():
        raise FreezeError("E7 steps 1-6 attestation is missing")
    payload = json.loads(E7_ATTESTATION.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "resetp.e7.steps-1-to-6-attestation.v1":
        raise FreezeError("E7 attestation schema differs")
    if payload.get("steps_1_to_6_complete") is not True or payload.get("search_version_closed") is not True:
        raise FreezeError("E7 steps 1-6 are not closed")
    builder_hash = sha256(E7_BUILDER)
    builder_key = str(E7_BUILDER.relative_to(REPO))
    if payload.get("builder_sha256") != builder_hash:
        raise FreezeError("E7 attestation builder differs")
    evidence_hashes = payload.get("evidence_hashes", {})
    if evidence_hashes.get(builder_key) != builder_hash:
        raise FreezeError("E7 attestation does not bind its builder")
    for raw_path, expected in evidence_hashes.items():
        path = Path(raw_path)
        if not path.is_absolute():
            path = REPO / path
        if not path.is_file() or sha256(path) != expected:
            raise FreezeError(f"E7 attested evidence differs: {raw_path}")
    return payload


def installed_distribution_hashes() -> dict[str, str]:
    distribution = importlib.metadata.distribution("pyvrp")
    records: dict[str, str] = {}
    for entry in distribution.files or ():
        path = Path(distribution.locate_file(entry)).resolve()
        if not path.is_file() or path.suffix == ".pyc" or "__pycache__" in path.parts or path.name.startswith("._"):
            continue
        records[str(path)] = sha256(path)
    if len(records) < 10:
        raise FreezeError("PyVRP distribution file map is unexpectedly small")
    return dict(sorted(records.items()))


def build_payload() -> dict[str, Any]:
    if Path(sys.executable).resolve() != EXPECTED_PYTHON.resolve():
        raise FreezeError("final freeze must use the isolated PyVRP interpreter")
    if importlib.metadata.version("pyvrp") != EXPECTED_VERSION:
        raise FreezeError("installed PyVRP version differs")
    if not WHEEL.is_file() or sha256(WHEEL) != EXPECTED_WHEEL_SHA256:
        raise FreezeError("official PyVRP wheel is missing or differs")
    probe = verify_probe()
    e7 = verify_e7_attestation()
    if not CPU_CONTRACT.is_file():
        raise FreezeError("Solomon CPU contract is missing")
    cpu = json.loads(CPU_CONTRACT.read_text(encoding="utf-8"))
    factor = float(cpu["dimacs_time_standardization"]["time_factor"])
    if abs(factor - PASSMARK_TIME_FACTOR) > 1e-12:
        raise FreezeError("CPU time factor differs from the pre-registered contract")

    tool_hashes = {str(WHEEL.relative_to(REPO)): sha256(WHEEL), **installed_distribution_hashes()}
    interface_paths = (RUNNER, PREFLIGHT, PROBE_SOURCE, FORMAL_HELPER, BUILDER, CPU_CONTRACT)
    interface_hashes = {str(path.relative_to(REPO)): sha256(path) for path in interface_paths}
    payload = {
        "schema_version": SCHEMA,
        "formal_search_authorized": True,
        "baseline_id": "PyVRP",
        "version": EXPECTED_VERSION,
        "python_executable": str(EXPECTED_PYTHON.resolve()),
        "workers": 4,
        "single_thread_per_solver": True,
        "wall_clock_seconds": LOCAL_SECONDS,
        "standardized_wall_clock_seconds": STANDARDIZED_SECONDS,
        "wall_clock_derivation": {
            "official_pyvrp_vrptw_reference_clients": REFERENCE_CLIENTS,
            "official_pyvrp_vrptw_reference_seconds": REFERENCE_SECONDS_1000_CLIENTS,
            "target_clients": TARGET_CLIENTS,
            "size_scaling_assumption": "linear client-count extrapolation; not an official Solomon protocol",
            "passmark_time_factor": PASSMARK_TIME_FACTOR,
            "local_formula": "7200 * 100 / 1000 / 1.837",
            "official_protocol_url": "https://pyvrp.org/dev/benchmarking.html",
        },
        "seeds": list(range(1, 11)),
        "distance_scale": 1000000,
        "time_to_best_extractor_verified": True,
        "tool_source_hashes": tool_hashes,
        "interface_source_hashes": interface_hashes,
        "candidate_probe_artifact_hashes_sha256": sha256(PROBE / "artifact_hashes.json"),
        "candidate_probe_metadata_sha256": sha256(PROBE / "metadata.json"),
        "candidate_probe_adapter_sha256": probe["adapter_sha256"],
        "e7_attestation_sha256": sha256(E7_ATTESTATION),
        "e7_search_version": e7["search_version"],
        "cpu_contract_sha256": sha256(CPU_CONTRACT),
        "notes": (
            "External PyVRP uses same-machine, single-thread, matched wall-clock comparison. "
            "Internal ALNS/LNS/ablation results remain on the separate complete-candidate evaluation axis."
        ),
    }
    return payload


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorization", default="")
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    if args.authorization != AUTHORIZATION:
        raise FreezeError("exact final-freeze authorization string is required")
    if args.output.exists():
        raise FreezeError(f"refuse to overwrite final freeze: {args.output}")
    payload = build_payload()
    payload["freeze_payload_sha256"] = canonical_sha256(payload)
    atomic_json(args.output, payload)
    print(json.dumps({"verdict": "PASS_FINAL_EXTERNAL_BASELINE_FREEZE", "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
