#!/usr/bin/env python3
"""Seal the byte-exact MIT-license repair without rerunning solver work."""

from __future__ import annotations

import csv
import hashlib
import json
import platform
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
PARENT = (
    REPO
    / "baselines"
    / "algorithm_foundation"
    / "mpils_mvns_c2_g0_20260720"
)
OUTPUT = (
    REPO
    / "baselines"
    / "algorithm_foundation"
    / "mpils_mvns_c2_g0_license_repair_20260720"
)
UPSTREAM_LICENSE = (
    REPO
    / "build"
    / "python_envs"
    / "pyvrp-0.13.4"
    / "lib"
    / "python3.13"
    / "site-packages"
    / "pyvrp-0.13.4.dist-info"
    / "licenses"
    / "LICENSE.md"
)
LOCAL_LICENSE = HERE / "LICENSE-PYVRP.md"
CORE_OUTPUTS = (
    "metadata.json",
    "raw_runs.csv",
    "decision.json",
    "artifact_hashes.json",
    "report.md",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    for filename in CORE_OUTPUTS:
        if (OUTPUT / filename).exists():
            raise FileExistsError(
                f"refusing to overwrite repair evidence: {OUTPUT / filename}"
            )
    parent_decision_path = PARENT / "decision.json"
    if not parent_decision_path.is_file():
        raise FileNotFoundError(parent_decision_path)
    parent = json.loads(parent_decision_path.read_text(encoding="utf-8"))

    parent_expected_shape = (
        parent["verdict"] == "FAIL_MPILS_MVNS_C2_G0_FOUNDATION"
        and parent["equivalence"]["pass"]
        and parent["overhead"]["pass"]
        and parent["behaviour"]["pass"]
        and not parent["provenance"]["pass"]
        and parent["provenance"]["checks"][
            "installed_upstream_hash_matches_register"
        ]
        and not parent["provenance"]["checks"][
            "mit_license_preserved_exactly"
        ]
        and parent["provenance"]["checks"][
            "upstream_manifest_present"
        ]
        and parent["provenance"]["checks"][
            "modified_copy_notice_present"
        ]
    )
    upstream_hash = sha256(UPSTREAM_LICENSE)
    local_hash = sha256(LOCAL_LICENSE)
    exact = LOCAL_LICENSE.read_bytes() == UPSTREAM_LICENSE.read_bytes()
    passed = parent_expected_shape and exact
    verdict = (
        "PASS_MPILS_MVNS_C2_G0_AFTER_LICENSE_REPAIR"
        if passed
        else "FAIL_MPILS_MVNS_C2_G0_LICENSE_REPAIR"
    )

    OUTPUT.mkdir(parents=True, exist_ok=True)
    decision: dict[str, Any] = {
        "verdict": verdict,
        "parent_g0_verdict_preserved": parent["verdict"],
        "parent_technical_gates_all_pass": (
            parent["equivalence"]["pass"]
            and parent["overhead"]["pass"]
            and parent["behaviour"]["pass"]
        ),
        "parent_failure_was_only_license_byte_identity": (
            parent_expected_shape
        ),
        "mit_license_now_byte_exact": exact,
        "effective_g0_foundation_pass": passed,
        "performance_claim_allowed": False,
        "performance_gate_authorized": False,
        "china81_authorized": False,
        "stage2_authorized": False,
        "honest_boundary": (
            "This repair closes only the byte-exact MIT license defect. "
            "It reuses the preserved parent G0 technical evidence and "
            "does not rerun or reinterpret solver performance."
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
            fieldnames=(
                "check",
                "upstream_sha256",
                "local_sha256",
                "byte_exact",
            ),
        )
        writer.writeheader()
        writer.writerow(
            {
                "check": "MIT_LICENSE_BYTE_IDENTITY",
                "upstream_sha256": upstream_hash,
                "local_sha256": local_hash,
                "byte_exact": str(exact).lower(),
            }
        )

    now = datetime.now(timezone.utc).isoformat()
    metadata = {
        "contract": "MPILS-MVNS-C2-R1-G0-LICENSE-REPAIR",
        "started_at_utc": now,
        "finished_at_utc": now,
        "host": {"platform": platform.platform()},
        "parent_evidence": {
            "directory": PARENT.relative_to(REPO).as_posix(),
            "decision_sha256": sha256(parent_decision_path),
            "artifact_manifest_sha256": sha256(
                PARENT / "artifact_hashes.json"
            ),
        },
        "repair": {
            "defect": "one extra terminal newline in local MIT copy",
            "solver_calls": 0,
            "performance_search_calls": 0,
            "china81_calls": 0,
        },
    }
    write_json(OUTPUT / "metadata.json", metadata)

    report = f"""# MPILS-MVNS-C2 G0 许可证补正门

判定：`{verdict}`。

原 G0 证据保持不改写。原门的母体等价、独立复算、0.811% 空闲开销、
替换式动作和预算账均已通过，唯一失败是本地 MIT 文本末尾多了一个空行。

本补正只删除该多余空行。补正后本地许可证与 PyVRP 0.13.4 安装包内许可证
逐字节相同，SHA-256 均为 `{upstream_hash}`。没有重跑求解器，也没有借补正
改变任何算法判据。

因此 G0 基础设施的有效状态为
`{"PASS" if passed else "FAIL"}`。这仍不构成性能证据，不授权公开性能门、
China81、完整 28 题或阶段二。
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

