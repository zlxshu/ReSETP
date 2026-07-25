"""Freeze v2 identities with distinct invocation and resolved Python paths."""

from __future__ import annotations

from pathlib import Path

from .paths import (
    DEFAULT_PROJECT_ROOT,
    PACKAGE,
    require_absolute_file,
    sha256,
    validate_project_root,
    write_json,
)


REGISTRATION_V2 = PACKAGE / "registration_v2.json"
MONITOR_CONFIG_V2 = PACKAGE / "monitor_integration_v2.json"
MONITOR_RUN_DIR_V2 = PACKAGE / ".absolute-execution-harness-v2.monitor"
OUTPUT_V2 = PACKAGE / "integration_gate_v2"
PYTHON_INVOCATION = (
    DEFAULT_PROJECT_ROOT
    / "build/python_envs/pyvrp-hgs-0.12.2/bin/python"
)
MONITOR_CLI = Path(
    "/Users/zhouleixishu/.codex/plugins/cache/personal/"
    "codex-experiment-monitor/0.1.1+codex.20260714203900/"
    "scripts/experiment_monitor.py"
)
SOURCE_NAMES = (
    "__init__.py",
    "paths.py",
    "worker_probe.py",
    "run_no_instance_gate.py",
    "build_registration_v2.py",
    "build_monitor_config_v2.py",
)


def main() -> None:
    root = validate_project_root(DEFAULT_PROJECT_ROOT)
    python_invocation = PYTHON_INVOCATION
    if not python_invocation.is_absolute() or not python_invocation.is_file():
        raise RuntimeError(
            f"Python invocation is not an absolute existing file: "
            f"{python_invocation}"
        )
    python_resolved = require_absolute_file(
        python_invocation.resolve(), "resolved Python"
    )
    monitor = require_absolute_file(MONITOR_CLI, "monitor CLI")
    sources = [
        require_absolute_file(PACKAGE / name, f"source {name}")
        for name in SOURCE_NAMES
    ]
    protected = [
        *sources,
        monitor,
        root
        / "docs/handoff/"
        "experiment_execution_harness_absolute_paths_contract_20260725.md",
        root / "HANDOFF.md",
        root / "docs/handoff/READ_ME_FIRST_FOR_AGENTS.md",
    ]
    payload = {
        "schema": "resetp.absolute-execution-harness.v2",
        "contract_id": "EXPERIMENT-ABSOLUTE-HARNESS-001",
        "project_root": str(root),
        "python_invocation": str(python_invocation),
        "python_resolved": str(python_resolved),
        "python": str(python_resolved),
        "monitor_cli": str(monitor),
        "main_script": str((PACKAGE / "run_no_instance_gate.py").resolve()),
        "monitor_config": str(MONITOR_CONFIG_V2.resolve()),
        "monitor_run_dir": str(MONITOR_RUN_DIR_V2.resolve()),
        "output_dir": str(OUTPUT_V2.resolve()),
        "workers": 6,
        "real_instance_allowed": False,
        "v1_incident": (
            "monitor command check compared resolved Python with invocation "
            "symlink and could not see a tail argument in truncated ps text"
        ),
        "protected_sha256": {
            str(path.resolve()): sha256(path.resolve())
            for path in protected
        },
    }
    write_json(REGISTRATION_V2, payload)
    print(f"wrote {REGISTRATION_V2.resolve()}")


if __name__ == "__main__":
    main()
