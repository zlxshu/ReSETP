#!/usr/bin/env python3
"""Materialize factual E2 V7 result prose from sealed PASS evidence only."""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


REPO = Path(__file__).resolve().parents[2]
CAMPAIGN = (
    REPO
    / "baselines/e2_final_campaign_20260720"
    / "corrected_china81_rerun_v7_small_archive_ledger_20260724"
)
FULL = CAMPAIGN / "full_gate"
REPLAY = CAMPAIGN / "full_witness_replay"
STRENGTH = CAMPAIGN / "result_strength_gate"
S3 = CAMPAIGN / "s3_trajectory_gate"
S4 = CAMPAIGN / "table4_gate"
S5 = CAMPAIGN / "artifacts"
OUT = CAMPAIGN / "paper_text_gate"
PREREGISTRATION = CAMPAIGN / "paper_text_preregistration_v1.json"
ARMS = ("HGS-F", "HGS-E", "HGS-M")
ALL_METHODS = (*ARMS, "MV-HGS-SP")
EPS = 1.0e-9


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("cannot write an empty CSV")
    fieldnames: list[str] = []
    for row in rows:
        for field in row:
            if field not in fieldnames:
                fieldnames.append(field)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def verify_manifest(root: Path) -> None:
    manifest = read_json(root / "artifact_hashes.json")
    for relative, expected in manifest["artifacts"].items():
        path = root / relative
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"artifact hash drift: {path}")


def require_pass(
    root: Path,
    expected_verdict: str,
    *,
    extra_flag: str | None = None,
) -> dict[str, Any]:
    decision = read_json(root / "decision.json")
    if decision.get("verdict") != expected_verdict:
        raise RuntimeError(
            f"{root.name}: expected {expected_verdict}, "
            f"got {decision.get('verdict')}"
        )
    if extra_flag is not None and not bool(decision.get(extra_flag)):
        raise RuntimeError(f"{root.name}: false gate {extra_flag}")
    verify_manifest(root)
    return decision


def outcome(differences: Iterable[float]) -> dict[str, int]:
    values = list(differences)
    wins = sum(value > EPS for value in values)
    losses = sum(value < -EPS for value in values)
    return {
        "paired_units": len(values),
        "wins": wins,
        "ties": len(values) - wins - losses,
        "losses": losses,
    }


def outcome_text(payload: dict[str, Any]) -> str:
    return (
        f"{int(payload['wins'])}/{int(payload['ties'])}/"
        f"{int(payload['losses'])}"
    )


def p_text(value: float) -> str:
    if value < 0.001:
        return r"$p<0.001$"
    return rf"$p={value:.3f}$"


def _validate_upstream() -> tuple[dict[str, Any], dict[str, Any]]:
    preregistration = read_json(PREREGISTRATION)
    if (
        preregistration.get("operation")
        != "ZERO_SEARCH_SEALED_RESULT_TEXT_MATERIALIZATION"
        or preregistration.get("result_rows_read_before_freeze") != 0
        or preregistration.get("search_executions") != 0
    ):
        raise RuntimeError("paper-text preregistration is invalid")
    for relative, expected in preregistration["source_hashes"].items():
        path = REPO / relative
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"paper-text source drift: {relative}")
    require_pass(
        FULL,
        (
            "PASS_D6_CORRECTED_CHINA81_E2_STAGED_V7_"
            "SMALL_ARCHIVE_LEDGER"
        ),
    )
    require_pass(
        REPLAY,
        "PASS_D6_STAGED_FULL_WITNESS_REPLAY",
    )
    require_pass(
        STRENGTH,
        "PASS_E2_STAGED_PORTFOLIO_PAPER_STRENGTH",
        extra_flag="paper_strength_pass",
    )
    s3_decision = require_pass(
        S3,
        "PASS_S3_STAGED_GENUINE_ITERATION_CURVES",
        extra_flag="trajectory_gate_pass",
    )
    require_pass(
        S4,
        "PASS_D6_CORRECTED_S4_ROUTE_DETAIL",
    )
    require_pass(
        S5,
        "PASS_E2_STAGED_V7_S5_ARTIFACTS",
    )
    summary = read_json(STRENGTH / "result_summary.json")
    return summary, s3_decision


def _s3_facts(
    s3_decision: dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    rows = read_csv(S3 / "raw_runs.csv")
    if (
        len(rows) != 10
        or {int(row["seed"]) for row in rows} != set(range(1, 11))
        or any(row["status"] != "PASS" for row in rows)
    ):
        raise RuntimeError("S3 raw ledger is not ten unique PASS seeds")

    means: dict[str, dict[str, float]] = {}
    for method in ALL_METHODS:
        means[method] = {
            "cost": statistics.fmean(
                float(row[f"{method}_cost"]) for row in rows
            ),
            "cpu_min": statistics.fmean(
                float(row[f"{method}_cpu_seconds"]) / 60.0
                for row in rows
            ),
        }
    s3_outcomes = {
        arm: outcome(
            float(row[f"{arm}_cost"])
            - float(row["MV-HGS-SP_cost"])
            for row in rows
        )
        for arm in ARMS
    }

    audit_rows = read_csv(S3 / "trajectory_audit.csv")
    if (
        len(audit_rows) != 4
        or {row["algorithm"] for row in audit_rows}
        != set(ALL_METHODS)
    ):
        raise RuntimeError("S3 trajectory audit is not four methods")
    audit = {row["algorithm"]: row for row in audit_rows}
    selected = {
        method: int(seed)
        for method, seed in s3_decision["selected_seeds"].items()
    }
    if set(selected) != set(ALL_METHODS):
        raise RuntimeError("S3 selected-seed ledger is incomplete")

    comparison = "、".join(
        f"对{arm}为{outcome_text(s3_outcomes[arm])}"
        for arm in ARMS
    )
    cost_text = "、".join(
        f"{method}为{means[method]['cost']:.3f}"
        for method in ALL_METHODS
    )
    cpu_text = "、".join(
        f"{method}为{means[method]['cpu_min']:.2f}"
        for method in ALL_METHODS
    )
    seed_text = "、".join(
        f"{method}为种子{selected[method]}" for method in ALL_METHODS
    )
    curve_text = "、".join(
        (
            f"{method}含{int(audit[method]['displayed_rows'])}个观测点、"
            f"{int(audit[method]['registered_strict_decreases'])}次严格下降"
        )
        for method in ALL_METHODS
    )
    paragraph = (
        "在迭代展示算例"
        f"{s3_decision['selected_instance_id']}的10次运行中，"
        f"MV-HGS-SP的胜/平/负{comparison}。"
        f"四种方法的平均成本依次为{cost_text}元，平均CPU时间依次为"
        f"{cpu_text}~min。该对比同时报告了解质量和额外计算代价，"
        "不把运行时间更长解释为更快收敛。"
        f"图\\ref{{fig:convergence}}按预登记规则选择的展示种子依次为"
        f"{seed_text}；{curve_text}。"
        "这些点均为运行时已经执行完整模型核算"
        "并登记的真实观测，"
        "图中仅以普通直线相连，未进行平滑、插值或断轴，"
        "各曲线终点与表\\ref{tab:algorithm-comparison}"
        "相应种子的正式结果一致。"
    )
    facts = [
        {
            "scope": "s3_ten_seed",
            "comparison": f"MV-HGS-SP_vs_{arm}",
            **s3_outcomes[arm],
            "mean_single_view_cost_cny": means[arm]["cost"],
            "mean_mv_hgs_sp_cost_cny": means["MV-HGS-SP"]["cost"],
            "mean_single_view_cpu_min": means[arm]["cpu_min"],
            "mean_mv_hgs_sp_cpu_min": means["MV-HGS-SP"]["cpu_min"],
        }
        for arm in ARMS
    ]
    return paragraph, facts


def _full_facts(
    summary: dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    tasks = summary["task_pair_outcomes"]
    instances = summary["instance_pair_outcomes"]
    layers = summary["layer_pair_outcomes"]
    reductions = summary["overall_mean_cost_reduction_percent"]
    task_text = "、".join(
        f"对{arm}为{outcome_text(tasks[arm])}" for arm in ARMS
    )
    instance_text = "、".join(
        f"对{arm}为{outcome_text(instances[arm])}" for arm in ARMS
    )
    layer_text = "、".join(
        f"对{arm}为{outcome_text(layers[arm])}" for arm in ARMS
    )
    reduction_text = "、".join(
        f"相对{arm}降低{float(reductions[arm]):.3f}\\%"
        for arm in ARMS
    )
    p_values = "、".join(
        (
            f"对{arm}为"
            f"{p_text(float(instances[arm]['holm_adjusted_p_value']))}"
        )
        for arm in ARMS
    )
    stage_1_count = int(
        summary["strict_improvements_over_protected_stage_1"]
    )
    fusion_count = int(
        summary[
            "strict_route_fusion_improvements_descriptive_only"
        ]
    )
    paragraph = (
        "在405个实例--种子描述性单元上，MV-HGS-SP的胜/平/负"
        f"{task_text}；以81个算例的5种子平均成本为主要配对单位时，"
        f"三组结果{instance_text}；在27个城市群--规模层上，"
        f"三组结果{layer_text}。总体平均成本{reduction_text}。"
        "81算例配对检验的Holm校正结果"
        f"{p_values}。"
        "相对阶段1受保护解，最终方法在"
        f"{stage_1_count}/405个任务中严格改善；"
        "其中限时MIP路线组合本身产生严格增量改善的任务为"
        f"{fusion_count}/405。"
        "因此，结果支持两阶段多视角搜索与最终择优的整体作用，"
        "但不把全部增益归因于路线组合，"
        "也不据此宣称稳定超加性或等计算量优势。"
    )
    facts = [
        {
            "scope": "formal_e2",
            "comparison": f"MV-HGS-SP_vs_{arm}",
            "task_paired_units": int(tasks[arm]["paired_units"]),
            "task_wins": int(tasks[arm]["wins"]),
            "task_ties": int(tasks[arm]["ties"]),
            "task_losses": int(tasks[arm]["losses"]),
            "instance_paired_units": int(
                instances[arm]["paired_units"]
            ),
            "instance_wins": int(instances[arm]["wins"]),
            "instance_ties": int(instances[arm]["ties"]),
            "instance_losses": int(instances[arm]["losses"]),
            "layer_paired_units": int(layers[arm]["paired_units"]),
            "layer_wins": int(layers[arm]["wins"]),
            "layer_ties": int(layers[arm]["ties"]),
            "layer_losses": int(layers[arm]["losses"]),
            "overall_mean_reduction_pct": float(reductions[arm]),
            "holm_adjusted_p_value": float(
                instances[arm]["holm_adjusted_p_value"]
            ),
            "strict_improvements_over_protected_stage_1": (
                stage_1_count
            ),
            "strict_route_fusion_improvements_descriptive_only": (
                fusion_count
            ),
        }
        for arm in ARMS
    ]
    return paragraph, facts


def main() -> int:
    summary, s3_decision = _validate_upstream()
    s3_paragraph, s3_facts = _s3_facts(s3_decision)
    full_paragraph, full_facts = _full_facts(summary)
    OUT.mkdir(parents=True, exist_ok=True)

    narrative = (
        "% Generated from sealed V7 PASS evidence; do not hand-edit.\n"
        "\\paragraph{迭代展示算例结果。}\n"
        f"{s3_paragraph}\n\n"
        "\\paragraph{全量算例结果。}\n"
        f"{full_paragraph}\n"
    )
    narrative_path = OUT / "e2_result_narrative.tex"
    narrative_path.write_text(narrative, encoding="utf-8")
    write_csv(OUT / "raw_runs.csv", [*s3_facts, *full_facts])

    decision = {
        "schema": "resetp.e2-v7-paper-text.decision.v1",
        "verdict": "PASS_E2_V7_PAPER_TEXT_MATERIALIZATION",
        "search_executions": 0,
        "source_result_rows_changed": 0,
        "paper_claims": {
            "route_fusion_superadditivity": False,
            "equal_compute_advantage": False,
            "mip_guaranteed_improvement": False,
        },
        "narrative_sha256": sha256(narrative_path),
        "formal_e3_search_allowed": False,
    }
    write_json(OUT / "decision.json", decision)
    source_paths = (
        FULL / "decision.json",
        FULL / "raw_runs.csv",
        REPLAY / "decision.json",
        STRENGTH / "decision.json",
        STRENGTH / "result_summary.json",
        S3 / "decision.json",
        S3 / "raw_runs.csv",
        S3 / "trajectory_audit.csv",
        S4 / "decision.json",
        S5 / "decision.json",
        Path(__file__).resolve(),
    )
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.e2-v7-paper-text.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "source_hashes": {
                str(path.relative_to(REPO)): sha256(path)
                for path in source_paths
            },
        },
    )
    (OUT / "report.md").write_text(
        "# E2 V7 paper text materialization\n\n"
        f"Decision: `{decision['verdict']}`.\n\n"
        "The two Chinese result paragraphs were generated without search "
        "from the sealed formal, independent replay, strength, S3, S4 and "
        "S5 PASS records. No result row, selected case, seed, score, "
        "statistical unit or claim boundary was changed.\n",
        encoding="utf-8",
    )
    artifacts = {
        path.name: sha256(path)
        for path in (
            narrative_path,
            OUT / "raw_runs.csv",
            OUT / "decision.json",
            OUT / "metadata.json",
            OUT / "report.md",
        )
    }
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": [
                "artifact_hashes.json",
                "done.json",
                "._*",
                "__pycache__",
                "*.tmp",
            ],
            "artifacts": artifacts,
        },
    )
    write_json(
        OUT / "done.json",
        {
            "schema": "resetp.e2-v7-paper-text-done.v1",
            "verdict": decision["verdict"],
            "decision_sha256": sha256(OUT / "decision.json"),
            "narrative_sha256": sha256(narrative_path),
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
