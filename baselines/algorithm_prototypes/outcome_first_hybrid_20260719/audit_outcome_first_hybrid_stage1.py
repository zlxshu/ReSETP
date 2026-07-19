#!/usr/bin/env python3
"""Independent, zero-search audit of the phase-1 hybrid evidence."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUT = HERE / "independent_stage1_audit_v5_authoritative"
BEHAVIOR = HERE / "bounded_segment_behavior_gate_v3_china81_scope"
CORE_GATE = HERE / "public_bks_core_microgate"
WARM_GATE = HERE / "public_bks_alns_warm_hgs_gate"
DUAL_GATE = HERE / "public_bks_dual_elite_hgs_gate"
CHINA_PREFLIGHT = HERE / "china81_private_fair_gate_preflight"
APPLEDOUBLE_REPAIR = HERE / "appledouble_hash_manifest_repair_v1"
PUBLIC_BUNDLES = (
    REPO
    / "baselines/e2_alns/"
    "solomon_sintef_formal_bundles_20260717_v3"
)
SOURCE_REGISTER = REPO / (
    "docs/handoff/algorithm_source_and_license_register_20260719.md"
)
CONTRACT = REPO / (
    "docs/handoff/outcome_first_multiengine_hybrid_contract_20260719.md"
)
HANDOFF = REPO / "HANDOFF.md"
APPROVAL_REGISTER = (
    REPO / "docs/handoff/model_change_approval_register_20260718.md"
)
PROJECT_MEMORY = REPO / "docs/handoff/memory/project-prd-execution-v2.md"
DEDICATED_MEMORY = (
    REPO / "docs/handoff/memory/outcome_first_hybrid_20260719.md"
)


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite: {OUT}")
    checks: list[dict[str, Any]] = []
    for label, root in (
        ("seg_gen_02_behavior", BEHAVIOR),
        ("public_core", CORE_GATE),
        ("warm_hgs_01", WARM_GATE),
        ("dual_elite_02", DUAL_GATE),
        ("china81_preflight", CHINA_PREFLIGHT),
    ):
        _check(
            checks,
            f"{label}.five_piece",
            _has_five_piece(root),
            str(root.relative_to(REPO)),
        )
        _check(
            checks,
            f"{label}.artifact_hashes",
            _verify_artifact_hashes(root),
            str(root.relative_to(REPO)),
        )

    behavior_decision = _json(BEHAVIOR / "decision.json")
    _check(
        checks,
        "seg_gen_02.behavior_verdict",
        behavior_decision.get("verdict")
        == "PASS_SEG_GEN_02_BEHAVIOR",
        str(behavior_decision.get("verdict")),
    )
    _check(
        checks,
        "seg_gen_02.private_scope",
        behavior_decision.get("next_allowed_step")
        == "await_china81_physical_and_search_gate",
        str(behavior_decision.get("next_allowed_step")),
    )

    _audit_public_gate(
        checks,
        root=CORE_GATE,
        expected_instances=(
            "C109", "C208", "R112", "R211", "RC108", "RC208"
        ),
        expected_algorithms=(
            "pyvrp_0_12_2_hgs",
            "pyvrp_0_13_4_ils",
            "project_alns",
        ),
        expected_verdict="STRONG_POSITIVE_PUBLIC_CORE_SELECTED",
        expected_strong=True,
    )
    _audit_public_gate(
        checks,
        root=WARM_GATE,
        expected_instances=(
            "C108", "C207", "R111", "R210", "RC107", "RC207"
        ),
        expected_algorithms=(
            "pyvrp_0_12_2_hgs",
            "project_alns",
            "alns_warm_hgs_01",
        ),
        expected_verdict="STOP_ALNS_WARM_HGS_NO_QUALITY_WIN",
        expected_strong=False,
    )
    _audit_public_gate(
        checks,
        root=DUAL_GATE,
        expected_instances=(
            "C107", "C206", "R110", "R209", "RC106", "RC206"
        ),
        expected_algorithms=(
            "pyvrp_0_12_2_hgs",
            "project_alns",
            "alns_dual_elite_hgs_02",
        ),
        expected_verdict="STOP_DUAL_ELITE_HGS_NO_QUALITY_WIN",
        expected_strong=False,
    )
    all_public_instances = {
        row["instance"]
        for root in (CORE_GATE, WARM_GATE, DUAL_GATE)
        for row in _csv(root / "raw_runs.csv")
    }
    _check(
        checks,
        "public.instance_sets_disjoint",
        len(all_public_instances) == 18,
        f"unique_instances={len(all_public_instances)}",
    )
    no_bks_leak = all(
        "bks" not in (
            (PUBLIC_BUNDLES / name / "instance.json")
            .read_text(encoding="utf-8")
            .lower()
        )
        for name in all_public_instances
    )
    _check(
        checks,
        "public.solver_inputs_bks_blind",
        no_bks_leak,
        f"instances={len(all_public_instances)}",
    )

    china = _json(CHINA_PREFLIGHT / "decision.json")
    _check(
        checks,
        "china81.preflight_halted",
        china.get("verdict")
        == "HALT_CHINA81_PRIVATE_GATE_NOT_ARMED"
        and china.get("formal_search_allowed") is False,
        str(china.get("verdict")),
    )
    _check(
        checks,
        "china81.zero_search",
        int(china.get("search_evaluations", -1)) == 0,
        f"search_evaluations={china.get('search_evaluations')}",
    )
    _check(
        checks,
        "china81.only_private_scope",
        china.get("planned_scope", {}).get("private_instances")
        == "China81 only"
        and china.get("planned_scope", {}).get(
            "other_private_instances_allowed"
        )
        is False,
        json.dumps(china.get("planned_scope", {}), ensure_ascii=False),
    )

    cancellation = (
        HERE / "fresh_segment_v2_bundles/CANCELLED_ZERO_SEARCH.md"
    )
    canceled_runner = HERE / "run_segment_v2_gate.py"
    _check(
        checks,
        "donor03.cancel_record",
        cancellation.is_file()
        and "次数为 0" in cancellation.read_text(encoding="utf-8"),
        str(cancellation.relative_to(REPO)),
    )
    _check(
        checks,
        "donor03.fail_closed_runner",
        "CANCELLED_SCOPE_PRIVATE_PERFORMANCE_CHINA81_ONLY"
        in canceled_runner.read_text(encoding="utf-8"),
        str(canceled_runner.relative_to(REPO)),
    )

    register = SOURCE_REGISTER.read_text(encoding="utf-8")
    _check(
        checks,
        "sources.licenses_and_citations",
        all(
            token in register
            for token in (
                "PyVRP",
                "N-Wouda ALNS",
                "MIT",
                "10.1287/opre.1120.1048",
                "10.1287/trsc.1050.0135",
                "ALNS-DUAL-ELITE-HGS-02",
            )
        ),
        str(SOURCE_REGISTER.relative_to(REPO)),
    )
    contract = CONTRACT.read_text(encoding="utf-8")
    _check(
        checks,
        "contract.latest_scope",
        "公开算例只考虑带BKS的原始开源算例" in contract
        and "私有算例只考虑china81" in contract
        and "公开融合开发到此停止" in contract
        and "造第三个候选" in contract,
        str(CONTRACT.relative_to(REPO)),
    )
    _check(
        checks,
        "records.handoff_updated",
        "结果优先混合算法阶段一已按" in HANDOFF.read_text(encoding="utf-8")
        and "公开总胜目标未达成" in HANDOFF.read_text(encoding="utf-8"),
        str(HANDOFF.relative_to(REPO)),
    )
    approval = APPROVAL_REGISTER.read_text(encoding="utf-8")
    _check(
        checks,
        "records.approval_register_updated",
        "PHASE1_EXECUTED_PUBLIC_HYBRID_STOPPED__CHINA81_HELD" in approval
        and "HALT_CHINA81_PRIVATE_GATE_NOT_ARMED" in approval,
        str(APPROVAL_REGISTER.relative_to(REPO)),
    )
    _check(
        checks,
        "records.project_memory_updated",
        DEDICATED_MEMORY.is_file()
        and "公开融合开发到此停止"
        in DEDICATED_MEMORY.read_text(encoding="utf-8")
        and "结果优先混合算法阶段一执行终局"
        in PROJECT_MEMORY.read_text(encoding="utf-8"),
        str(DEDICATED_MEMORY.relative_to(REPO)),
    )
    _check(
        checks,
        "records.artifact_manifests_exclude_appledouble",
        all(
            not any(
                Path(name).name.startswith("._")
                for name in _json(path)
            )
            for path in HERE.rglob("artifact_hashes.json")
        ),
        str(HERE.relative_to(REPO)),
    )
    repair_decision = _json(APPLEDOUBLE_REPAIR / "decision.json")
    _check(
        checks,
        "records.appledouble_repair_no_rerun",
        repair_decision.get("verdict")
        == "PASS_APPLEDOUBLE_HASH_MANIFEST_REPAIR_NO_RERUN"
        and repair_decision.get("algorithm_reruns") == 0
        and repair_decision.get("search_evaluations") == 0,
        str(APPLEDOUBLE_REPAIR.relative_to(REPO)),
    )

    failures = [row for row in checks if not bool(row["passed"])]
    decision = {
        "verdict": (
            "PASS_OUTCOME_FIRST_HYBRID_STAGE1_EVIDENCE_AUDIT"
            if not failures
            else "FAIL_OUTCOME_FIRST_HYBRID_STAGE1_EVIDENCE_AUDIT"
        ),
        "checks": len(checks),
        "passed": len(checks) - len(failures),
        "failed": len(failures),
        "failures": failures,
        "search_evaluations": 0,
        "public_hybrid_goal_achieved": False,
        "china81_performance_executed": False,
        "stage2_allowed": False,
    }
    metadata = {
        "schema_version": "resetp.outcome-first-hybrid-stage1-audit.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git("rev-parse", "HEAD"),
        "git_status_short": _git("status", "--short"),
        "audit_script_sha256": _sha(Path(__file__).resolve()),
        "search_evaluations": 0,
        "claim_boundary": (
            "Zero-search evidence audit only. It verifies recorded artifacts "
            "and scope; it does not turn stopped hybrid candidates into wins."
        ),
    }
    report = "\n".join(
        [
            "# 结果优先混合算法阶段一独立证据审计",
            "",
            f"- 判决：`{decision['verdict']}`",
            f"- 检查：{decision['passed']}/{decision['checks']} 通过。",
            "- 审计新增搜索：0。",
            "- 公开混合算法目标未达成：两个融合候选都未总胜纯HGS。",
            "- China81性能未运行；正式门和公开强阳性均未满足。",
            "- 通过仅表示证据、范围、哈希和停止线自洽，不表示算法优化成功。",
            "",
        ]
    )
    OUT.mkdir(parents=True)
    _write_csv(OUT / "raw_runs.csv", checks)
    _write_json(OUT / "metadata.json", metadata)
    _write_json(OUT / "decision.json", decision)
    (OUT / "report.md").write_text(
        report,
        encoding="utf-8",
    )
    _write_json(
        OUT / "artifact_hashes.json",
        {
            path.name: _sha(path)
            for path in sorted(OUT.iterdir())
            if path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if not failures else 1


def _audit_public_gate(
    checks: list[dict[str, Any]],
    *,
    root: Path,
    expected_instances: tuple[str, ...],
    expected_algorithms: tuple[str, ...],
    expected_verdict: str,
    expected_strong: bool,
) -> None:
    label = root.name
    rows = _csv(root / "raw_runs.csv")
    decision = _json(root / "decision.json")
    comparisons = _json(root / "comparisons.json")
    _check(
        checks,
        f"{label}.row_count",
        len(rows) == 18,
        f"rows={len(rows)}",
    )
    _check(
        checks,
        f"{label}.scope",
        {row["instance"] for row in rows} == set(expected_instances)
        and {row["algorithm"] for row in rows} == set(expected_algorithms),
        "instances/algorithms",
    )
    _check(
        checks,
        f"{label}.feasible_recomputed",
        all(
            row["feasible"] == "True"
            and row["independent_recompute_pass"] == "True"
            and row["status"] == "OK"
            for row in rows
        ),
        "all rows",
    )
    recomputed = _recompute_comparisons(
        rows,
        expected_instances,
        expected_algorithms,
    )
    _check(
        checks,
        f"{label}.comparisons_recomputed",
        _normalise_comparisons(recomputed)
        == _normalise_comparisons(comparisons),
        "lexicographic vehicle/distance",
    )
    _check(
        checks,
        f"{label}.decision_preserved",
        decision.get("verdict") == expected_verdict
        and decision.get("strong_positive") is expected_strong,
        str(decision.get("verdict")),
    )
    _check(
        checks,
        f"{label}.no_scope_escalation",
        decision.get("formal_56_instance_run_allowed") is False
        and decision.get("china81_run_allowed") is False
        and decision.get("stage2_allowed") is False,
        "all escalation flags false",
    )


def _recompute_comparisons(
    rows: list[dict[str, str]],
    instances: tuple[str, ...],
    algorithms: tuple[str, ...],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for name in instances:
        arms = {
            row["algorithm"]: row
            for row in rows
            if row["instance"] == name
        }
        scores = {
            algorithm: [
                int(arms[algorithm]["route_count"]),
                float(arms[algorithm]["distance_double"]),
            ]
            for algorithm in algorithms
        }
        best = min(tuple(value) for value in scores.values())
        worst = max(tuple(value) for value in scores.values())
        any_row = next(iter(arms.values()))
        output.append(
            {
                "instance": name,
                "bks": [
                    int(any_row["bks_vehicles"]),
                    float(any_row["bks_distance_double"]),
                ],
                "scores": {
                    algorithm: scores[algorithm]
                    for algorithm in algorithms
                },
                "best_algorithms": [
                    algorithm
                    for algorithm in algorithms
                    if tuple(scores[algorithm]) == best
                ],
                "last_algorithms": [
                    algorithm
                    for algorithm in algorithms
                    if tuple(scores[algorithm]) == worst
                ],
            }
        )
    return output


def _normalise_comparisons(
    comparisons: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            **item,
            "best_algorithms": sorted(item["best_algorithms"]),
            "last_algorithms": sorted(item["last_algorithms"]),
        }
        for item in comparisons
    ]


def _has_five_piece(root: Path) -> bool:
    return all(
        (root / name).is_file()
        for name in (
            "metadata.json",
            "raw_runs.csv",
            "decision.json",
            "artifact_hashes.json",
            "report.md",
        )
    )


def _verify_artifact_hashes(root: Path) -> bool:
    expected = _json(root / "artifact_hashes.json")
    return all(
        (root / name).is_file()
        and _sha(root / name) == digest
        for name, digest in expected.items()
    )


def _check(
    rows: list[dict[str, Any]],
    check: str,
    passed: bool,
    detail: str,
) -> None:
    rows.append(
        {
            "check": check,
            "passed": bool(passed),
            "detail": detail,
            "search_evaluations": 0,
        }
    )


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _csv(path: Path) -> list[dict[str, str]]:
    return list(
        csv.DictReader(path.open(encoding="utf-8", newline=""))
    )


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row})
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buffer.getvalue(), encoding="utf-8")


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=REPO,
        text=True,
    ).strip()


if __name__ == "__main__":
    raise SystemExit(main())
