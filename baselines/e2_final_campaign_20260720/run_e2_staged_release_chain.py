#!/usr/bin/env python3
"""Run the preregistered post-formal E2 release stages in fail-closed order."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


REPO = Path(__file__).resolve().parents[2]
CAMPAIGN = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v7_small_archive_ledger_20260724"
)
OUT = CAMPAIGN / "release_chain"
MONITOR = Path(
    "/Users/zhouleixishu/.codex/plugins/cache/personal/"
    "codex-experiment-monitor/0.1.1+codex.20260714203900/"
    "scripts/experiment_monitor.py"
)
PYTHON = REPO / "build/python_envs/pyvrp-hgs-0.12.2/bin/python"
FORMAL_MONITOR = (
    CAMPAIGN / ".d6-corrected-china81-e2-staged-v7-formal.monitor"
)
FORMAL_DECISION = CAMPAIGN / "full_gate/decision.json"
FORMAL_DONE = CAMPAIGN / "full_gate/done.json"
FORMAL_PASS = (
    "PASS_D6_CORRECTED_CHINA81_E2_STAGED_V7_SMALL_ARCHIVE_LEDGER"
)
POLL_SECONDS = 60


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def heartbeat(stage: str, status: str, detail: str = "") -> None:
    write_json(
        OUT / "progress.json",
        {
            "schema": "resetp.e2-staged-release-chain-progress.v1",
            "stage": stage,
            "status": status,
            "detail": detail,
            "updated_at_epoch": time.time(),
        },
    )


def verdict(path: Path) -> str | None:
    if not path.exists():
        return None
    return read_json(path).get("verdict")


def wait_for_formal() -> None:
    while True:
        monitor_status_path = FORMAL_MONITOR / "status.json"
        monitor_done_path = FORMAL_MONITOR / "done.json"
        state = "WAITING"
        if monitor_status_path.exists():
            state = str(read_json(monitor_status_path).get("state", "UNKNOWN"))
            status_age = time.time() - monitor_status_path.stat().st_mtime
            if status_age > 600:
                raise RuntimeError(
                    f"formal E2 monitor status is stale for {status_age:.0f}s"
                )
        heartbeat("formal_e2", "WAITING", f"monitor_state={state}")
        if state == "ANOMALY":
            raise RuntimeError("formal E2 monitor reported ANOMALY")
        if (
            monitor_done_path.exists()
            and FORMAL_DONE.exists()
            and FORMAL_DECISION.exists()
        ):
            monitor_done = read_json(monitor_done_path)
            if monitor_done.get("state") != "COMPLETED":
                raise RuntimeError(
                    "formal E2 monitor ended without COMPLETED state"
                )
            if verdict(FORMAL_DECISION) != FORMAL_PASS:
                raise RuntimeError(
                    "formal E2 decision did not reach the frozen PASS verdict"
                )
            heartbeat("formal_e2", "PASS", FORMAL_PASS)
            return
        time.sleep(POLL_SECONDS)


def clean_appledouble() -> int:
    removed = 0
    for path in sorted(CAMPAIGN.rglob("._*")):
        if path.is_file():
            path.unlink()
            removed += 1
    return removed


def run_stage(
    name: str,
    config_name: str,
    command: list[str],
    decision_name: str,
    done_name: str,
    expected_verdict: str,
) -> None:
    decision_path = CAMPAIGN / decision_name
    done_path = CAMPAIGN / done_name
    if (
        decision_path.exists()
        and done_path.exists()
        and verdict(decision_path) == expected_verdict
    ):
        heartbeat(name, "PASS_ALREADY_PRESENT", expected_verdict)
        return

    config = CAMPAIGN / config_name
    run_dir = CAMPAIGN / f".{read_json(config)['name']}.monitor"
    if run_dir.exists():
        raise RuntimeError(
            f"{name} has an existing incomplete monitor directory: {run_dir}"
        )
    heartbeat(name, "STARTING", " ".join(command))
    completed = subprocess.run(
        [
            sys.executable,
            str(MONITOR),
            "start",
            "--foreground",
            "--config",
            str(config),
            "--",
            *command,
        ],
        cwd=REPO,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{name} monitor returned {completed.returncode}"
        )
    if not done_path.exists():
        raise RuntimeError(f"{name} completion marker is missing")
    actual = verdict(decision_path)
    if actual != expected_verdict:
        raise RuntimeError(
            f"{name} verdict mismatch: expected {expected_verdict}, got {actual}"
        )
    heartbeat(name, "PASS", expected_verdict)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        wait_for_formal()
        removed = clean_appledouble()
        heartbeat("appledouble_cleanup", "PASS", f"removed={removed}")
        common_env = [
            "env",
            "OMP_NUM_THREADS=1",
            "OPENBLAS_NUM_THREADS=1",
            "MKL_NUM_THREADS=1",
            "VECLIB_MAXIMUM_THREADS=1",
        ]
        run_stage(
            "full_witness_replay",
            "monitor_full_witness_replay_v3.json",
            common_env
            + [
                str(PYTHON),
                "baselines/e2_final_campaign_20260720/"
                "replay_corrected_d6_staged_witnesses.py",
            ],
            "full_witness_replay/decision.json",
            "full_witness_replay/done.json",
            "PASS_D6_STAGED_FULL_WITNESS_REPLAY",
        )
        run_stage(
            "result_strength",
            "monitor_result_strength_v3.json",
            common_env
            + [
                str(PYTHON),
                "baselines/e2_final_campaign_20260720/"
                "run_e2_staged_result_strength_audit.py",
            ],
            "result_strength_gate/decision.json",
            "result_strength_gate/done.json",
            "PASS_E2_STAGED_PORTFOLIO_PAPER_STRENGTH",
        )
        run_stage(
            "s3_trajectory",
            "monitor_s3_trajectory_v2.json",
            common_env
            + [
                str(PYTHON),
                "baselines/e2_final_campaign_20260720/"
                "run_e2_staged_s3_trajectory_gate.py",
                "--workers",
                "3",
            ],
            "s3_trajectory_gate/decision.json",
            "s3_trajectory_gate/done.json",
            "PASS_S3_STAGED_GENUINE_ITERATION_CURVES",
        )
        run_stage(
            "s4_route_detail",
            "monitor_s4_route_detail_v3.json",
            common_env
            + [
                str(PYTHON),
                "baselines/e2_final_campaign_20260720/"
                "run_e2_staged_s4_route_detail_v3.py",
            ],
            "table4_gate/decision.json",
            "table4_gate/done.json",
            "PASS_D6_CORRECTED_S4_ROUTE_DETAIL",
        )
        run_stage(
            "s5_artifacts",
            "monitor_s5_artifacts_v1.json",
            common_env
            + [
                str(PYTHON),
                "baselines/e2_final_campaign_20260720/"
                "run_e2_staged_s5_artifacts.py",
            ],
            "artifacts/decision.json",
            "artifacts/done.json",
            "PASS_E2_STAGED_V7_S5_ARTIFACTS",
        )
        decision = {
            "schema": "resetp.e2-staged-release-chain-decision.v1",
            "verdict": "PASS_E2_STAGED_V7_RELEASE_CHAIN",
            "formal_verdict": FORMAL_PASS,
            "stages": [
                "full_witness_replay",
                "result_strength",
                "s3_trajectory",
                "s4_route_detail",
                "s5_artifacts",
            ],
        }
        write_json(OUT / "decision.json", decision)
        (OUT / "report.md").write_text(
            "# E2 staged-v7 release chain\n\n"
            "All preregistered release stages passed in fail-closed order. "
            "No stage was allowed to continue after a failed decision.\n",
            encoding="utf-8",
        )
        artifacts = {
            str(path.relative_to(OUT)): sha256(path)
            for path in sorted(OUT.rglob("*"))
            if (
                path.is_file()
                and path.name not in {"artifact_hashes.json", "done.json"}
                and not path.name.startswith("._")
            )
        }
        write_json(
            OUT / "artifact_hashes.json",
            {
                "schema": "resetp.artifact-hashes.v1",
                "exclusions": ["artifact_hashes.json", "done.json", "._*"],
                "artifacts": artifacts,
            },
        )
        write_json(
            OUT / "done.json",
            {
                "schema": "resetp.e2-staged-release-chain-done.v1",
                "verdict": decision["verdict"],
                "decision_sha256": sha256(OUT / "decision.json"),
            },
        )
        heartbeat("release_chain", "PASS", decision["verdict"])
        return 0
    except Exception as exc:
        write_json(
            OUT / "decision.json",
            {
                "schema": "resetp.e2-staged-release-chain-decision.v1",
                "verdict": "HALT_E2_STAGED_V7_RELEASE_CHAIN",
                "reason": str(exc),
            },
        )
        (OUT / "report.md").write_text(
            "# E2 staged-v7 release chain\n\n"
            f"Decision: `HALT_E2_STAGED_V7_RELEASE_CHAIN`.\n\n{exc}\n",
            encoding="utf-8",
        )
        heartbeat("release_chain", "HALT", str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
