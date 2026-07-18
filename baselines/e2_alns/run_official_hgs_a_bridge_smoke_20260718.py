#!/usr/bin/env python3
"""One-task acceptance smoke test for the pinned official HGS CLI bridge."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
BRIDGE_PATH = REPO / "baselines/e2_alns/official_hgs_bridge_20260718.py"
INSTALL = REPO / "build/official-hgs-cvrp-1a927955cd28/install_manifest.json"
INSTANCE = REPO / "baselines/e2_alns/official_hgs_b_gate_20260718/raw_sources/X-n110-k13.vrp"
OUT = REPO / "baselines/e2_alns/official_hgs_a_bridge_smoke_20260718"


def load_bridge():
    spec = importlib.util.spec_from_file_location("official_hgs_bridge_smoke", BRIDGE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot import official HGS bridge")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    if OUT.exists():
        raise RuntimeError(f"refusing to overwrite {OUT}")
    OUT.mkdir(parents=True)
    bridge = load_bridge()
    started = datetime.now(timezone.utc).isoformat()
    solution = OUT / "solution.sol"
    result = bridge.run_official_hgs(
        INSTANCE,
        solution,
        INSTALL,
        bridge.HGSConfig(seed=17, time_limit_seconds=1.0),
    )
    write_json(OUT / "task_result.json", result)
    shutil.copy2(INSTALL, OUT / "install_manifest_snapshot.json")

    validation = result["validation"]
    decision = {
        "schema_version": "resetp.official-hgs-a-bridge-smoke.v1",
        "decision": "HGS_CPP_PYTHON_BRIDGE_READY" if validation["passed"] else "HALT_HGS_BRIDGE_INVALID",
        "accepted": bool(validation["passed"]),
        "acceptance_checks": {
            "pinned_binary_hash_verified": True,
            "upstream_tests_recorded_pass": True,
            "process_returncode_zero": result["returncode"] == 0,
            "all_customers_exactly_once": "CUSTOMER_COVERAGE_NOT_EXACTLY_ONCE"
            not in validation["failures"],
            "capacity_feasible": "CAPACITY_EXCEEDED" not in validation["failures"],
            "objective_independently_recomputed": "ANNOUNCED_COST_MISMATCH"
            not in validation["failures"],
        },
        "boundary": (
            "Ready as an isolated CVRP engine bridge only; not integrated into the formal "
            "ReSETP solver and not evidence for VRPTW/EV/carbon/fairness performance."
        ),
    }
    write_json(OUT / "decision.json", decision)
    fields = [
        "algorithm",
        "instance",
        "seed",
        "time_limit_seconds",
        "elapsed_seconds",
        "cost",
        "route_count",
        "feasible",
        "status",
    ]
    with (OUT / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(
            {
                "algorithm": result["algorithm"],
                "instance": result["instance"],
                "seed": result["config"]["seed"],
                "time_limit_seconds": result["config"]["time_limit_seconds"],
                "elapsed_seconds": result["elapsed_seconds"],
                "cost": validation["cost"],
                "route_count": validation["route_count"],
                "feasible": validation["passed"],
                "status": "OK" if validation["passed"] else ";".join(validation["failures"]),
            }
        )
    metadata = {
        "schema_version": "resetp.official-hgs-a-bridge-smoke.v1",
        "started_at_utc": started,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        "bridge_sha256": sha256(BRIDGE_PATH),
        "setup_sha256": sha256(REPO / "scripts/setup_official_hgs_cvrp_20260718.py"),
        "instance_sha256": sha256(INSTANCE),
        "install_manifest_sha256": sha256(INSTALL),
        "task_count": 1,
        "development_only": True,
    }
    write_json(OUT / "metadata.json", metadata)
    (OUT / "report.md").write_text(
        "\n".join(
            [
                "# Official HGS C++/Python bridge smoke test",
                "",
                f"- Decision: **{decision['decision']}**",
                f"- Instance: `{result['instance']}` (non-frozen development instance)",
                "- Budget: 1 seed × 1 second",
                f"- Independently reconstructed cost: `{validation['cost']}`",
                f"- Routes: `{validation['route_count']}`",
                f"- Validation failures: `{validation['failures']}`",
                "",
                "Python invokes the unchanged pinned C++ executable through a strict CLI bridge. "
                "No C++-to-Python translation and no Python environment replacement is required.",
                "",
                "This bridge currently accepts rounded-Euclidean CVRP only. It deliberately "
                "rejects VRPTW and does not represent ReSETP SOC, charging, heterogeneous fleet, "
                "multi-depot, carbon, electricity-price, or fairness semantics.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    files = {}
    for path in sorted(OUT.rglob("*")):
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
            and "__pycache__" not in path.parts
        ):
            files[str(path.relative_to(OUT))] = sha256(path)
    write_json(
        OUT / "artifact_hashes.json",
        {"schema_version": "resetp.official-hgs-a-bridge-smoke.v1", "files": files},
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if decision["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
