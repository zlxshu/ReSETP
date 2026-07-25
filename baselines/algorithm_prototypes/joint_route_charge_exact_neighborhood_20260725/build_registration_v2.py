"""Freeze JRC v2 as a path-only execution of the v1 scientific contract."""

from __future__ import annotations

from pathlib import Path

from .common import REGISTRATION as REGISTRATION_V1
from .common import verify_registration
from .v2_common import (
    ENGINEERING_CONFIG_V2,
    ENGINEERING_MONITOR_V2,
    ENGINEERING_OUT_V2,
    G0_CONFIG_V2,
    G0_MONITOR_V2,
    G0_OUT_V2,
    PACKAGE,
    PROJECT_ROOT,
    REGISTRATION_V2,
    read_json,
    sha256,
    write_json,
)


PYTHON_INVOCATION = (
    PROJECT_ROOT / "build/python_envs/pyvrp-hgs-0.12.2/bin/python"
)
MONITOR_CLI = Path(
    "/Users/zhouleixishu/.codex/plugins/cache/personal/"
    "codex-experiment-monitor/0.1.1+codex.20260714203900/"
    "scripts/experiment_monitor.py"
)
V2_SOURCE_NAMES = (
    "v2_common.py",
    "engineering_worker_v2.py",
    "build_registration_v2.py",
    "build_monitor_configs_v2.py",
    "run_engineering_gate_v2.py",
    "run_g0_v2.py",
    "independent_replay_v2.py",
)


def require_file(path: Path, label: str) -> Path:
    if not path.is_absolute() or not path.is_file():
        raise RuntimeError(f"{label} is not an absolute existing file: {path}")
    return path


def main() -> None:
    v1 = verify_registration()
    if len(v1["tasks"]) != 6:
        raise RuntimeError("JRC v1 scientific registration is not six tasks")
    python_invocation = require_file(PYTHON_INVOCATION, "Python invocation")
    monitor_cli = require_file(MONITOR_CLI, "monitor CLI")
    harness_decision = (
        PROJECT_ROOT
        / "baselines/experiment_infrastructure/"
        "absolute_execution_harness_20260725/"
        "integration_gate_v2/decision.json"
    )
    harness_status = (
        PROJECT_ROOT
        / "baselines/experiment_infrastructure/"
        "absolute_execution_harness_20260725/"
        ".absolute-execution-harness-v2.monitor/status.json"
    )
    if read_json(harness_decision).get("pass") is not True:
        raise RuntimeError("absolute execution harness is not PASS")
    if read_json(harness_status).get("state") != "COMPLETED":
        raise RuntimeError("absolute execution harness monitor is not COMPLETED")
    v2_sources = [
        require_file(PACKAGE / name, f"v2 source {name}")
        for name in V2_SOURCE_NAMES
    ]
    authorization = require_file(
        PROJECT_ROOT
        / "docs/handoff/"
        "e2_joint_route_charge_exact_neighborhood_v2_execution_authorization_20260725.md",
        "v2 authorization",
    )
    protected_paths = {
        Path(raw).resolve()
        for raw in v1["protected_sha256"]
    }
    protected_paths.update(
        {
            REGISTRATION_V1.resolve(),
            *[path.resolve() for path in v2_sources],
            monitor_cli.resolve(),
            harness_decision.resolve(),
            harness_status.resolve(),
            authorization.resolve(),
        }
    )
    payload = {
        "schema": "resetp.jrc-exact-nh-g0.v2",
        "contract_id": v1["contract_id"],
        "execution_version": "v2_absolute_harness",
        "project_root": str(PROJECT_ROOT),
        "python_invocation": str(python_invocation),
        "python_resolved": str(python_invocation.resolve()),
        "monitor_cli": str(monitor_cli),
        "engineering_runner": str(
            (PACKAGE / "run_engineering_gate_v2.py").resolve()
        ),
        "g0_runner": str((PACKAGE / "run_g0_v2.py").resolve()),
        "engineering_output": str(ENGINEERING_OUT_V2.resolve()),
        "g0_output": str(G0_OUT_V2.resolve()),
        "engineering_monitor_config": str(
            ENGINEERING_CONFIG_V2.resolve()
        ),
        "g0_monitor_config": str(G0_CONFIG_V2.resolve()),
        "engineering_monitor_run_dir": str(
            ENGINEERING_MONITOR_V2.resolve()
        ),
        "g0_monitor_run_dir": str(G0_MONITOR_V2.resolve()),
        "scientific_registration_v1": str(REGISTRATION_V1.resolve()),
        "scientific_registration_v1_sha256": sha256(REGISTRATION_V1),
        "tasks": v1["tasks"],
        "limits": v1["limits"],
        "pass_rules": v1["pass_rules"],
        "protected_fallback": v1["protected_fallback"],
        "scientific_contract_unchanged": True,
        "v1_evidence_preserved": True,
        "protected_sha256": {
            str(path): sha256(path)
            for path in sorted(protected_paths)
        },
    }
    write_json(REGISTRATION_V2, payload)
    print(f"wrote {REGISTRATION_V2.resolve()}")


if __name__ == "__main__":
    main()
