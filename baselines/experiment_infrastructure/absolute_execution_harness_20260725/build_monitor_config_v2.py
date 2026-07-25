"""Build the v2 all-absolute monitor contract."""

from __future__ import annotations

from pathlib import Path

from .build_registration_v2 import (
    MONITOR_CONFIG_V2,
    REGISTRATION_V2,
)
from .paths import read_json, write_json


def main() -> None:
    registration = read_json(REGISTRATION_V2)
    root = Path(registration["project_root"]).resolve()
    output = Path(registration["output_dir"]).resolve()
    protected = [
        {"path": path, "kind": "experiment_contract"}
        for path in registration["protected_sha256"]
    ]
    protected.append(
        {"path": str(REGISTRATION_V2.resolve()), "kind": "primary_config"}
    )
    config = {
        "schema_version": 1,
        "name": "absolute-execution-harness-v2",
        "objective": (
            "Verify absolute monitor/main/worker paths with six spawned "
            "workers and no real instance"
        ),
        "workdir": str(root),
        "monitor_dir": registration["monitor_run_dir"],
        "poll_seconds": 2,
        "stale_seconds": 60,
        "max_runtime_seconds": 180,
        "pause_on_anomaly": True,
        "required_command_substrings": [
            registration["python_invocation"],
            (
                registration["main_script"]
                + " --workers 6"
            ),
        ],
        "forbidden_command_substrings": [
            "--tune",
            "--rescue",
            "--full",
        ],
        "min_cpu_percent_when_active": 0.1,
        "cpu_grace_seconds": 30,
        "low_cpu_consecutive_checks": 10,
        "max_rss_mb": 1024,
        "min_system_memory_free_percent": 5,
        "logs": [],
        "progress_files": [],
        "result_files": [
            str((output / "raw_runs.csv").resolve()),
            str((output / "decision.json").resolve()),
            str((output / "artifact_hashes.json").resolve()),
        ],
        "completion_files": [
            str((output / "done.json").resolve()),
        ],
        "checkpoint_paths": [str(output.resolve())],
        "protected_files": protected,
        "csv_rules": [
            {
                "path": str((output / "raw_runs.csv").resolve()),
                "required": True,
                "required_after_seconds": 120,
                "required_fields": [
                    "worker_index",
                    "pid",
                    "module",
                    "module_file",
                    "cwd",
                    "project_root",
                    "python",
                    "real_instance_loaded",
                ],
                "duplicate_key_fields": ["worker_index"],
                "max_duplicate_fraction": 0,
            }
        ],
        "milestones": [],
        "ai": {"enabled": False, "timeout_seconds": 300},
    }
    all_paths = [
        config["workdir"],
        *config["result_files"],
        *config["completion_files"],
        *[item["path"] for item in config["protected_files"]],
    ]
    if any(not Path(value).is_absolute() for value in all_paths):
        raise RuntimeError("v2 monitor config contains a relative path")
    write_json(MONITOR_CONFIG_V2, config)
    print(f"wrote {MONITOR_CONFIG_V2.resolve()}")


if __name__ == "__main__":
    main()
