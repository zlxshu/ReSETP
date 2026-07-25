"""Freeze source and absolute path identities for the harness."""

from __future__ import annotations

import sys
from pathlib import Path

from .paths import (
    DEFAULT_PROJECT_ROOT,
    MONITOR_CONFIG,
    MONITOR_RUN_DIR,
    OUTPUT,
    PACKAGE,
    REGISTRATION,
    require_absolute_file,
    sha256,
    validate_project_root,
    write_json,
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
    "build_registration.py",
    "build_monitor_config.py",
    "run_no_instance_gate.py",
)


def main() -> None:
    root = validate_project_root(DEFAULT_PROJECT_ROOT)
    python = require_absolute_file(Path(sys.executable), "Python")
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
        "schema": "resetp.absolute-execution-harness.v1",
        "contract_id": "EXPERIMENT-ABSOLUTE-HARNESS-001",
        "project_root": str(root),
        "python": str(python),
        "monitor_cli": str(monitor),
        "main_script": str((PACKAGE / "run_no_instance_gate.py").resolve()),
        "monitor_config": str(MONITOR_CONFIG.resolve()),
        "monitor_run_dir": str(MONITOR_RUN_DIR.resolve()),
        "output_dir": str(OUTPUT.resolve()),
        "workers": 6,
        "real_instance_allowed": False,
        "protected_sha256": {
            str(path.resolve()): sha256(path.resolve())
            for path in protected
        },
    }
    write_json(REGISTRATION, payload)
    print(f"wrote {REGISTRATION.resolve()}")


if __name__ == "__main__":
    main()
