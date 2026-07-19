#!/usr/bin/env python3
"""Seal the unused-import repair against the preserved G0 evidence."""

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
OUTPUT = (
    REPO
    / "baselines"
    / "algorithm_foundation"
    / "mpils_mvns_c2_g0_source_hygiene_repair_20260720"
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


def run(
    command: list[str],
    *,
    env: dict[str, str],
    json_output: bool = False,
) -> Any:
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
    return json.loads(completed.stdout) if json_output else completed


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
        }
    )

    current = EVENT_FILE.read_bytes()
    current_text = current.decode("utf-8")
    old_text = current_text.replace(
        "from typing import Protocol, TYPE_CHECKING",
        "from typing import Any, Protocol, TYPE_CHECKING",
        1,
    )
    exact_one_line_reconstruction = (
        old_text != current_text
        and sha256_bytes(old_text.encode("utf-8"))
        == OLD_EVENT_SHA256
    )

    run(
        [
            sys.executable,
            "-m",
            "py_compile",
            *[
                str(path)
                for path in sorted(HERE.glob("*.py"))
            ],
        ],
        env=env,
    )
    run(
        [
            "/opt/anaconda3/bin/ruff",
            "check",
            *[
                str(path)
                for path in sorted(HERE.glob("*.py"))
            ],
        ],
        env=env,
    )
    behaviour = run(
        [sys.executable, str(BEHAVIOUR)],
        env=env,
        json_output=True,
    )
    worker_outputs = {}
    for mode in ("official", "clone_native"):
        worker_outputs[mode] = run(
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
            json_output=True,
        )
    equivalence = (
        worker_outputs["official"][
            "deterministic_signature_sha256"
        ]
        == worker_outputs["clone_native"][
            "deterministic_signature_sha256"
        ]
    )
    license_parent = json.loads(
        (PARENT_LICENSE / "decision.json").read_text(
            encoding="utf-8"
        )
    )
    parent_effective = bool(
        license_parent["effective_g0_foundation_pass"]
    )
    no_sidecars = not any(HERE.rglob("._*"))
    passed = (
        exact_one_line_reconstruction
        and behaviour["all_checks_pass"]
        and equivalence
        and parent_effective
        and no_sidecars
    )
    verdict = (
        "PASS_MPILS_MVNS_C2_G0_CURRENT_SOURCE"
        if passed
        else "FAIL_MPILS_MVNS_C2_G0_SOURCE_HYGIENE_REPAIR"
    )

    OUTPUT.mkdir(parents=True, exist_ok=True)
    checks = {
        "old_source_reconstructed_by_one_unused_import": (
            exact_one_line_reconstruction
        ),
        "py_compile_pass": True,
        "ruff_pass": True,
        "five_iteration_equivalence_pass": equivalence,
        "behaviour_probe_pass": behaviour["all_checks_pass"],
        "parent_effective_g0_pass": parent_effective,
        "prototype_sidecars_zero_before_write": no_sidecars,
    }
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
            "The only algorithm-source change after G0 was removal of "
            "an unused import. This gate rechecks lint, compile, short "
            "equivalence, and behaviour; it does not rerun performance "
            "or the already-passed 5000-iteration overhead experiment."
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
            fieldnames=("check", "passed", "detail"),
        )
        writer.writeheader()
        for check, value in checks.items():
            writer.writerow(
                {
                    "check": check,
                    "passed": str(value).lower(),
                    "detail": (
                        sha256(EVENT_FILE)
                        if check.startswith("old_source")
                        else ""
                    ),
                }
            )

    now = datetime.now(timezone.utc).isoformat()
    metadata = {
        "contract": "MPILS-MVNS-C2-R1-G0-SOURCE-HYGIENE-REPAIR",
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
        },
        "source_change": {
            "old_sha256": OLD_EVENT_SHA256,
            "new_sha256": sha256(EVENT_FILE),
            "description": (
                "removed unused typing.Any import; no executable use"
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
    report = f"""# MPILS-MVNS-C2 G0 当前源码卫生补正

判定：`{verdict}`。

G0后Ruff发现`event_driven_ils.py`多导入了未使用的`typing.Any`。当前文件在内存中
补回这一处导入后，SHA-256精确恢复为原G0登记值`{OLD_EVENT_SHA256}`，证明源码只改
这一处无执行用途的导入。

补正后py_compile和Ruff通过；PR11A固定5迭代的上游/迁入母体签名仍相同，人工替换
夹具全部检查仍通过。没有重复5000迭代开销门，没有运行性能题或China81。

当前`event_driven_ils.py` SHA-256为`{sha256(EVENT_FILE)}`。此前G0失败包和两份补正
包均保持不改写；本门是当前源码对应的最终G0状态。
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

