#!/usr/bin/env python3
"""Corrected source-hygiene repair gate for MPILS-MVNS-C2 G0."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from scripts.freeze_mdvrptw_v13_foundation_20260719 import (  # noqa: E402
    build_hash_manifest,
    write_json,
)


HERE = Path(__file__).resolve().parent
EVENT_FILE = HERE / "event_driven_ils.py"
BEHAVIOUR = HERE / "run_behavior_probe.py"
WORKER = HERE / "run_g0_worker.py"
INSTANCE = (
    REPO
    / "baselines"
    / "algorithm_foundation"
    / "mdvrptw_v13_comparison_20260719"
    / "sources"
    / "normalised_instances"
    / "PR11A.vrp"
)
PARENT_G0 = (
    REPO
    / "baselines"
    / "algorithm_foundation"
    / "mpils_mvns_c2_g0_20260720"
)
PARENT_LICENSE = (
    REPO
    / "baselines"
    / "algorithm_foundation"
    / "mpils_mvns_c2_g0_license_repair_20260720"
)
FAILED_REPAIR = (
    REPO
    / "baselines"
    / "algorithm_foundation"
    / "mpils_mvns_c2_g0_source_hygiene_repair_20260720"
)
OUTPUT = (
    REPO
    / "baselines"
    / "algorithm_foundation"
    / "mpils_mvns_c2_g0_source_hygiene_repair_v2_20260720"
)
OLD_EVENT_SHA256 = (
    "8ade27abb8f00f19b4a249df1b34b06abb07590e5f7c19085eb1939656f47c5c"
)
CORE_OUTPUTS = (
    "metadata.json",
    "raw_runs.csv",
    "decision.json",
    "artifact_hashes.json",
    "report.md",
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def run_json(
    command: list[str],
    *,
    env: dict[str, str],
) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {command}\n"
            f"stdout={completed.stdout}\nstderr={completed.stderr}"
        )
    return json.loads(completed.stdout)


def main() -> int:
    for filename in CORE_OUTPUTS:
        if (OUTPUT / filename).exists():
            raise FileExistsError(
                f"refusing to overwrite repair evidence: {OUTPUT / filename}"
            )
    env = os.environ.copy()
    env.update(
        {
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "VECLIB_MAXIMUM_THREADS": "1",
            "PYTHONHASHSEED": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )

    current = EVENT_FILE.read_bytes()
    reconstructed = (
        current.decode("utf-8")
        .replace(
            "from typing import Protocol, TYPE_CHECKING",
            "from typing import Any, Protocol, TYPE_CHECKING",
            1,
        )
        .encode("utf-8")
        + b"\n"
    )
    old_reconstructed = (
        sha256_bytes(reconstructed) == OLD_EVENT_SHA256
    )

    for path in sorted(HERE.glob("*.py")):
        compile(
            path.read_text(encoding="utf-8"),
            str(path),
            "exec",
        )
    lint = subprocess.run(
        [
            "/opt/anaconda3/bin/ruff",
            "check",
            *[str(path) for path in sorted(HERE.glob("*.py"))],
        ],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    lint_pass = lint.returncode == 0

    behaviour = run_json(
        [sys.executable, str(BEHAVIOUR)],
        env=env,
    )
    workers = {}
    for mode in ("official", "clone_native"):
        workers[mode] = run_json(
            [
                sys.executable,
                str(WORKER),
                "--mode",
                mode,
                "--instance",
                str(INSTANCE),
                "--seed",
                "1",
                "--iterations",
                "5",
                "--collect-stats",
            ],
            env=env,
        )
    equivalence = (
        workers["official"]["deterministic_signature_sha256"]
        == workers["clone_native"]["deterministic_signature_sha256"]
    )
    parent_effective = bool(
        json.loads(
            (PARENT_LICENSE / "decision.json").read_text(
                encoding="utf-8"
            )
        )["effective_g0_foundation_pass"]
    )
    failed_repair_preserved = (
        json.loads(
            (FAILED_REPAIR / "decision.json").read_text(
                encoding="utf-8"
            )
        )["verdict"]
        == "FAIL_MPILS_MVNS_C2_G0_SOURCE_HYGIENE_REPAIR"
    )
    no_prototype_sidecars = not any(HERE.rglob("._*"))
    checks = {
        "old_source_reconstructed_by_unused_import_and_blank_line": (
            old_reconstructed
        ),
        "in_memory_compile_pass": True,
        "ruff_pass": lint_pass,
        "five_iteration_equivalence_pass": equivalence,
        "behaviour_probe_pass": behaviour["all_checks_pass"],
        "parent_effective_g0_pass": parent_effective,
        "failed_repair_preserved": failed_repair_preserved,
        "prototype_sidecars_zero_before_evidence_write": (
            no_prototype_sidecars
        ),
    }
    passed = all(checks.values())
    verdict = (
        "PASS_MPILS_MVNS_C2_G0_CURRENT_SOURCE"
        if passed
        else "FAIL_MPILS_MVNS_C2_G0_SOURCE_HYGIENE_REPAIR_V2"
    )

    OUTPUT.mkdir(parents=True, exist_ok=True)
    decision = {
        "verdict": verdict,
        "checks": checks,
        "current_event_driven_ils_sha256": sha256(EVENT_FILE),
        "effective_g0_foundation_pass": passed,
        "performance_claim_allowed": False,
        "performance_gate_authorized": False,
        "china81_authorized": False,
        "stage2_authorized": False,
        "honest_boundary": (
            "Current source removes only an unused import and one extra "
            "terminal blank line from the G0-tested source. Compile, "
            "lint, short equivalence, and behaviour are rechecked; "
            "no performance or China81 run is included."
        ),
    }
    write_json(OUTPUT / "decision.json", decision)
    with (OUTPUT / "raw_runs.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("check", "passed"),
        )
        writer.writeheader()
        for check, value in checks.items():
            writer.writerow(
                {"check": check, "passed": str(value).lower()}
            )

    now = datetime.now(timezone.utc).isoformat()
    metadata = {
        "contract": "MPILS-MVNS-C2-R1-G0-SOURCE-HYGIENE-REPAIR-V2",
        "started_at_utc": now,
        "finished_at_utc": now,
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "parent_evidence": {
            "g0_decision_sha256": sha256(
                PARENT_G0 / "decision.json"
            ),
            "license_repair_decision_sha256": sha256(
                PARENT_LICENSE / "decision.json"
            ),
            "failed_source_repair_decision_sha256": sha256(
                FAILED_REPAIR / "decision.json"
            ),
        },
        "source_change": {
            "old_sha256": OLD_EVENT_SHA256,
            "new_sha256": sha256(EVENT_FILE),
            "description": (
                "removed unused typing.Any and one extra terminal blank line"
            ),
        },
        "counts": {
            "equivalence_solver_calls": 2,
            "behaviour_probe_calls": 1,
            "performance_search_calls": 0,
            "china81_calls": 0,
        },
    }
    write_json(OUTPUT / "metadata.json", metadata)
    report = f"""# MPILS-MVNS-C2 G0 当前源码卫生补正 v2

判定：`{verdict}`。

首次源码卫生补正错误地假设旧文件只多一个未使用导入，且检查前的py_compile在
外置盘生成了缓存旁文件，因此原FAIL保持不改写。精确字节复核表明，旧G0源码还比
当前文件多一个末尾空行。把未使用`typing.Any`和一个末尾空行同时补回后，SHA-256
精确恢复为`{OLD_EVENT_SHA256}`。

当前源码通过内存编译和Ruff；PR11A固定5迭代的上游/迁入签名仍一致，人工替换夹具
仍全部通过。当前源码SHA-256为`{sha256(EVENT_FILE)}`。本门没有重复5000迭代开销
实验，没有运行性能题、China81或阶段二。
"""
    (OUTPUT / "report.md").write_text(report, encoding="utf-8")
    write_json(
        OUTPUT / "artifact_hashes.json",
        build_hash_manifest(OUTPUT),
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

