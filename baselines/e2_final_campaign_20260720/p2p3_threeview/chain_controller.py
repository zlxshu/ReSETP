#!/usr/bin/env python3
"""Advance S2->S5 only after sealed PASS gates.

This controller is deliberately outside the algorithm runners. It reads
stage decisions, starts the already-reviewed monitor commands, and performs
the required post-stage AppleDouble cleanup/hash refresh. It never changes
solver inputs, evaluator code, paper TeX, or experiment parameters.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "baselines/e2_final_campaign_20260720/p2p3_threeview"
PYTHON = ROOT / "build/python_envs/pyvrp-hgs-0.12.2/bin/python"
MONITOR = Path(
    "/Users/zhouleixishu/.codex/plugins/cache/personal/"
    "codex-experiment-monitor/0.1.1+codex.20260714203900/scripts/experiment_monitor.py"
)
POLL_SECONDS = 30
READY_NOTICE_SECONDS = 300
APPLEDOUBLE_FLAG = "HASH_CONTAMINATED_APPLEDOUBLE"


def _stage(name: str, directory: Path, expected: str) -> dict[str, Any]:
    config = directory / "monitor.json"
    config_payload = json.loads(config.read_text(encoding="utf-8"))
    return {
        "name": name,
        "dir": directory,
        "expected": expected,
        "config": config,
        "runner": directory / config_payload["required_command_substrings"][0],
        "monitor_dir": Path(config_payload["monitor_dir"]),
        "required_files": [
            directory / "decision.json",
            directory / "metadata.json",
            directory / "artifact_hashes.json",
            directory / "report.md",
            directory / "done.json",
        ],
    }


STAGES = [
    _stage("S2", BASE / "full_gate", "PASS_S2_FULL_THREEVIEW"),
    _stage("S3", BASE / "representative_gate", "PASS_S3_REPRESENTATIVE"),
    _stage("S4", BASE / "table4_gate", "PASS_S4_ROUTE_DETAIL"),
    _stage("S5", BASE / "artifacts", "PASS_S5_ARTIFACTS"),
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _decision(stage: dict[str, Any]) -> dict[str, Any] | None:
    path = stage["dir"] / "decision.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _ready(stage: dict[str, Any]) -> dict[str, Any] | None:
    payload = _decision(stage)
    if payload is None or not all(path.is_file() for path in stage["required_files"]):
        return None
    return payload


def _wait_for_monitor_quiet(stage: dict[str, Any]) -> None:
    status_path = stage["monitor_dir"] / "status.json"
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            status = {}
        if status.get("state") in {"COMPLETED", "FAILED", "STOPPED"}:
            return
        time.sleep(5)


def _sanitize(stage: dict[str, Any]) -> list[str]:
    _wait_for_monitor_quiet(stage)
    sidecars = [
        path for path in stage["dir"].rglob("._*")
        if path.is_file()
    ]
    if not sidecars:
        return []
    for path in sidecars:
        path.unlink()
    flags = [APPLEDOUBLE_FLAG]
    for name in ("decision.json", "metadata.json"):
        path = stage["dir"] / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        integrity_flags = list(payload.get("integrity_flags", []))
        if APPLEDOUBLE_FLAG not in integrity_flags:
            integrity_flags.append(APPLEDOUBLE_FLAG)
        payload["integrity_flags"] = integrity_flags
        _write_json(path, payload)
    report = stage["dir"] / "report.md"
    report.write_text(
        report.read_text(encoding="utf-8")
        + "\nIntegrity flag: " + APPLEDOUBLE_FLAG
        + "; AppleDouble sidecars were removed before the final hash refresh. "
        + "Raw data files were not overwritten.\n",
        encoding="utf-8",
    )
    hash_path = stage["dir"] / "artifact_hashes.json"
    hash_payload = json.loads(hash_path.read_text(encoding="utf-8"))
    hash_payload["integrity_flags"] = list(
        dict.fromkeys([*hash_payload.get("integrity_flags", []), APPLEDOUBLE_FLAG])
    )
    refreshed: dict[str, str] = {}
    for relative in hash_payload.get("files", {}):
        path = Path(relative)
        if not path.is_absolute():
            path = ROOT / path
        if path.is_file() and not path.name.startswith("._"):
            refreshed[str(relative)] = _sha256(path)
    hash_payload["files"] = refreshed
    _write_json(hash_path, hash_payload)
    print(
        f"[CHAIN] {stage['name']} removed {len(sidecars)} AppleDouble sidecars; "
        f"flagged {APPLEDOUBLE_FLAG} and refreshed hashes",
        flush=True,
    )
    return flags


def _launch(stage: dict[str, Any]) -> None:
    if stage["monitor_dir"].exists():
        raise RuntimeError(
            f"{stage['name']} monitor directory already exists; refusing to "
            "overwrite or relaunch an ambiguous stage"
        )
    command = [
        sys.executable,
        str(MONITOR),
        "start",
        "--config",
        str(stage["config"]),
        "--",
        str(PYTHON),
        str(stage["runner"]),
    ]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout.rstrip(), flush=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"{stage['name']} monitor start failed rc={result.returncode}: "
            f"{result.stderr.strip()}"
        )
    print(f"[CHAIN] launched {stage['name']}", flush=True)


def _wait_pass(stage: dict[str, Any]) -> dict[str, Any]:
    last_notice = 0.0
    while True:
        decision = _decision(stage)
        if decision is not None and str(decision.get("decision", "")).startswith("HALT_"):
            raise RuntimeError(
                f"{stage['name']} halted: {decision.get('decision')}: "
                f"{decision.get('reason', decision.get('error', ''))}"
            )
        ready = _ready(stage)
        if ready is not None:
            if ready.get("decision") != stage["expected"]:
                raise RuntimeError(
                    f"{stage['name']} completed with unexpected decision "
                    f"{ready.get('decision')!r}"
                )
            print(f"[CHAIN] {stage['name']} PASS", flush=True)
            return ready
        now = time.monotonic()
        if now - last_notice >= READY_NOTICE_SECONDS:
            print(f"[CHAIN] waiting for {stage['name']} completion", flush=True)
            last_notice = now
        time.sleep(POLL_SECONDS)


def main() -> int:
    print(
        f"[CHAIN] started {datetime.now(timezone.utc).isoformat()}; "
        "S2->S5 PASS-only progression",
        flush=True,
    )
    previous = STAGES[0]
    _wait_pass(previous)
    _sanitize(previous)
    for current in STAGES[1:]:
        if _decision(current) is None:
            _launch(current)
        else:
            print(
                f"[CHAIN] {current['name']} already has a decision; resuming "
                "without overwriting it",
                flush=True,
            )
        _wait_pass(current)
        _sanitize(current)
    done = BASE / "chain_done.json"
    _write_json(
        done,
        {
            "decision": "PASS_S2_TO_S5_CHAIN",
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "stage_decisions": {
                stage["name"]: json.loads(
                    (stage["dir"] / "decision.json").read_text(encoding="utf-8")
                )["decision"]
                for stage in STAGES
            },
        },
    )
    print("[CHAIN] PASS_S2_TO_S5_CHAIN", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
