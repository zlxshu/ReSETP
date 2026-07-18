#!/usr/bin/env python3
"""Build the approved minimal freight-profile evidence package.

This does not build province graphs or run optimization. It derives two
isolated OSRM profiles from the frozen v5.27.1 car profile and records whether
the approved local runtime is available for the one-map smoke test.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    ROOT
    / "data/ChinaInstances/china_mc004_mc006_preclosure_v4_20260718"
    / "source_snapshots/osrm_v5.27.1_car.lua"
)
OUT = ROOT / "data/ChinaInstances/phase1_osrm_smoke_20260718"
RUNTIME = Path("/Users/zhouleixishu/.local/opt/osrm-v5.27.1/bin/osrm-extract")

VEHICLES = {
    "cv": {
        "height": 2.480,
        "width": 2.200,
        "length": 5.995,
        "weight": 4495,
    },
    "ev": {
        "height": 3.250,
        "width": 2.200,
        "length": 5.995,
        "weight": 4495,
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_profile(source: str, vehicle: dict[str, float | int]) -> str:
    result = source
    replacements = {
        "vehicle_height = 2.0": f"vehicle_height = {vehicle['height']:.3f}",
        "vehicle_width = 1.9": f"vehicle_width = {vehicle['width']:.3f}",
        "vehicle_length = 4.8": f"vehicle_length = {vehicle['length']:.3f}",
        "vehicle_weight = 2000": f"vehicle_weight = {vehicle['weight']}",
        "access_tags_hierarchy = Sequence {\n      'motorcar',": (
            "access_tags_hierarchy = Sequence {\n      'hgv',\n      'motorcar',"
        ),
        "restrictions = Sequence {\n      'motorcar',": (
            "restrictions = Sequence {\n      'hgv',\n      'motorcar',"
        ),
    }
    for old, new in replacements.items():
        if result.count(old) != 1:
            raise RuntimeError(f"Expected exactly one profile token: {old!r}")
        result = result.replace(old, new)
    return result


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    source_text = SOURCE.read_text(encoding="utf-8")
    rows: list[dict[str, object]] = []

    for label, vehicle in VEHICLES.items():
        profile = build_profile(source_text, vehicle)
        path = OUT / f"freight_{label}_v5271.lua"
        path.write_text(profile, encoding="utf-8")
        rows.append(
            {
                "check": f"profile_{label}",
                "status": "PASS_STATIC_PROFILE",
                "height_m": vehicle["height"],
                "width_m": vehicle["width"],
                "length_m": vehicle["length"],
                "weight_kg": vehicle["weight"],
                "hgv_hierarchy_count": profile.count("'hgv'"),
                "sha256": sha256(path),
            }
        )

    runtime_available = RUNTIME.is_file()
    rows.append(
        {
            "check": "pinned_runtime",
            "status": "PASS" if runtime_available else "HALT_RUNTIME_BUILD",
            "height_m": "",
            "width_m": "",
            "length_m": "",
            "weight_kg": "",
            "hgv_hierarchy_count": "",
            "sha256": sha256(RUNTIME) if runtime_available else "",
        }
    )

    with (OUT / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    metadata = {
        "schema": "resetp.phase1.osrm-smoke.v1",
        "approval_ids": ["P1-APP-01", "P1-APP-03", "P1-APP-04"],
        "source_profile": str(SOURCE.relative_to(ROOT)),
        "source_profile_sha256": sha256(SOURCE),
        "osrm_tag": "v5.27.1",
        "osrm_commit": "4f3ee609ec1af40eb1f445c6706cfa5beb04c990",
        "scope": "isolated profiles and one clipped-map smoke only",
        "full_province_graphs_allowed": False,
        "full_matrices_allowed": False,
        "solver_search_evaluations": 0,
    }
    (OUT / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    verdict = (
        "PASS_PROFILES_READY_RUNTIME_READY_FOR_CLIPPED_SMOKE"
        if runtime_available
        else "PASS_PROFILES_READY__HALT_PINNED_RUNTIME_BUILD"
    )
    decision = {
        "schema": "resetp.phase1.osrm-smoke-decision.v1",
        "verdict": verdict,
        "profile_static_checks": "PASS_2_OF_2",
        "runtime_available": runtime_available,
        "formal_method_approved": False,
        "full_matrix_allowed": False,
        "next_action": (
            "run one clipped-map smoke"
            if runtime_available
            else "resolve pinned runtime compatibility or obtain approval for a newer pinned OSRM release"
        ),
    }
    (OUT / "decision.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    report = f"""# 阶段一 OSRM 最小货车规则

判决：`{verdict}`

两份隔离 profile 已从冻结的 OSRM v5.27.1 `car.lua` 机械派生。柴油车使用
`5.995×2.200×2.480 m / 4495 kg`，纯电车使用
`5.995×2.200×3.250 m / 4495 kg`；访问和转向限制层级在原
`motorcar/motor_vehicle/vehicle` 前增加 `hgv`。没有自创中国速度。

本包只证明规则文件可复算，搜索评价为 0。固定运行时当前
`{'可用' if runtime_available else '不可用'}`；没有建立五省图、九城矩阵或正式算例。
"""
    (OUT / "report.md").write_text(report, encoding="utf-8")

    files = sorted(
        path
        for path in OUT.iterdir()
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    )
    hashes = {
        "schema": "resetp.artifact-hashes.v1",
        "files": [{"path": path.name, "sha256": sha256(path)} for path in files],
    }
    (OUT / "artifact_hashes.json").write_text(
        json.dumps(hashes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(verdict)


if __name__ == "__main__":
    main()
