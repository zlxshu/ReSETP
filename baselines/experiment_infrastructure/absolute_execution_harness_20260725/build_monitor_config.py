"""Build a monitor configuration containing absolute paths only."""

from __future__ import annotations

from pathlib import Path

from .paths import (
    MONITOR_CONFIG,
    REGISTRATION,
    read_json,
    write_json,
)


def main() -> None:
    registration = read_json(REGISTRATION)
    root = Path(registration["project_root"]).resolve()
    output = Path(registration["output_dir"]).resolve()
    protected = [
        {"path": path, "kind": "experiment_contract"}
        for path in registration["protected_sha256"]
    ]
    protected.append(
        {"path": str(REGISTRATION.resolve()), "kind": "primary_config"}
    )
    config = {
        "schema_version": 1,
        "name": "absolute-execution-harness-v1",
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
            registration["python"],
            registration["main_script"],
            "--workers",
            "6",
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
        "checkpoint_paths": [
            str(output.resolve()),
        ],
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
    values = [config["workdir"], *config["result_files"]]
    values.extend(config["completion_files"])
    values.extend(item["path"] for item in config["protected_files"])
    if any(not Path(value).is_absolute() for value in values):
        raise RuntimeError("monitor config contains a relative filesystem path")
    write_json(MONITOR_CONFIG, config)
    print(f"wrote {MONITOR_CONFIG.resolve()}")


if __name__ == "__main__":
    main()
