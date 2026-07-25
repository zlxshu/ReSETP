"""Build all-absolute JRC v2 engineering and G0 monitor contracts."""

from __future__ import annotations

from pathlib import Path

from .v2_common import (
    ENGINEERING_CONFIG_V2,
    ENGINEERING_MONITOR_V2,
    ENGINEERING_OUT_V2,
    G0_CONFIG_V2,
    G0_MONITOR_V2,
    G0_OUT_V2,
    PROJECT_ROOT,
    REGISTRATION_V2,
    read_json,
    write_json,
)


def base_config(
    *,
    name: str,
    objective: str,
    runner: str,
    monitor_dir: Path,
    output: Path,
    max_runtime: int,
    registration: dict,
) -> dict:
    protected = [
        {"path": raw, "kind": "experiment_contract"}
        for raw in registration["protected_sha256"]
    ]
    protected.append(
        {"path": str(REGISTRATION_V2.resolve()), "kind": "primary_config"}
    )
    config = {
        "schema_version": 1,
        "name": name,
        "objective": objective,
        "workdir": str(PROJECT_ROOT),
        "monitor_dir": str(monitor_dir.resolve()),
        "poll_seconds": 5,
        "stale_seconds": 300,
        "max_runtime_seconds": max_runtime,
        "pause_on_anomaly": True,
        "required_command_substrings": [
            registration["python_invocation"],
            runner + " --workers 6",
        ],
        "forbidden_command_substrings": [
            "--tune",
            "--rescue",
            "--full",
        ],
        "min_cpu_percent_when_active": 0.1,
        "cpu_grace_seconds": 120,
        "low_cpu_consecutive_checks": 10,
        "max_rss_mb": 4096,
        "min_system_memory_free_percent": 5,
        "logs": [],
        "progress_files": [],
        "result_files": [
            str((output / "raw_runs.csv").resolve()),
            str((output / "decision.json").resolve()),
            str((output / "artifact_hashes.json").resolve()),
        ],
        "completion_files": [str((output / "done.json").resolve())],
        "checkpoint_paths": [str(output.resolve())],
        "protected_files": protected,
        "csv_rules": [],
        "milestones": [],
        "ai": {"enabled": False, "timeout_seconds": 300},
    }
    paths = [
        config["workdir"],
        *config["result_files"],
        *config["completion_files"],
        *[item["path"] for item in protected],
    ]
    if any(not Path(raw).is_absolute() for raw in paths):
        raise RuntimeError(f"{name}: relative monitor path detected")
    return config


def main() -> None:
    registration = read_json(REGISTRATION_V2)
    engineering = base_config(
        name="jrc-exact-neighborhood-engineering-v2",
        objective=(
            "Run frozen six-customer proof and zero-objective/resource "
            "gates through the verified absolute harness"
        ),
        runner=registration["engineering_runner"],
        monitor_dir=ENGINEERING_MONITOR_V2,
        output=ENGINEERING_OUT_V2,
        max_runtime=1200,
        registration=registration,
    )
    g0 = base_config(
        name="jrc-exact-neighborhood-g0-v2",
        objective=(
            "Run the frozen six-task exact-neighborhood G0 with six workers"
        ),
        runner=registration["g0_runner"],
        monitor_dir=G0_MONITOR_V2,
        output=G0_OUT_V2,
        max_runtime=600,
        registration=registration,
    )
    g0["csv_rules"] = [
        {
            "path": str((G0_OUT_V2 / "raw_runs.csv").resolve()),
            "required": True,
            "required_after_seconds": 480,
            "required_fields": [
                "task_id",
                "instance_id",
                "arm",
                "start_cost",
                "final_cost",
                "complete_candidate_scores",
                "optimality_proven",
            ],
            "duplicate_key_fields": ["task_id"],
            "max_duplicate_fraction": 0,
        }
    ]
    write_json(ENGINEERING_CONFIG_V2, engineering)
    write_json(G0_CONFIG_V2, g0)
    print(
        f"wrote {ENGINEERING_CONFIG_V2.resolve()} and "
        f"{G0_CONFIG_V2.resolve()}"
    )


if __name__ == "__main__":
    main()
