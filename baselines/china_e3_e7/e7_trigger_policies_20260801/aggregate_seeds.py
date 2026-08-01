#!/usr/bin/env python3
"""Aggregate approved E7 pilots without filtering outcomes."""

from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


HERE = Path(__file__).resolve().parent
DEFAULT_SEEDS = (1, 2, 3)
ARMS = (
    "full_information_static_reference",
    "per_order",
    "fixed_30_minutes",
    "hybrid_500kg_or_30_minutes",
)
ARM_LABELS = {
    "full_information_static_reference": "全信息一次性静态参照",
    "per_order": "信息一到就重排",
    "fixed_30_minutes": "固定每30分钟重排",
    "hybrid_500kg_or_30_minutes": "累计500kg或最多等30分钟",
}
PER_ORDER_PAIRS = (
    ("per_order", "fixed_30_minutes"),
    ("per_order", "hybrid_500kg_or_30_minutes"),
)
ALL_DYNAMIC_PAIRS = (
    *PER_ORDER_PAIRS,
    ("hybrid_500kg_or_30_minutes", "fixed_30_minutes"),
)
DEFAULT_OUT = HERE / "pilot_50c_seeds1to3_eval8_aggregate_20260801"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _source(seed: int) -> Path:
    return HERE / f"pilot_50c_seed{seed}_eval8_v1_20260801"


def _load_seed(
    seed: int, source: Path | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source = source or _source(seed)
    manifest_path = source / "artifact_hashes.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual = {
        path.name: _sha256(path)
        for path in source.iterdir()
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    if manifest != actual:
        raise RuntimeError(f"seed {seed} artifact manifest mismatch")
    metadata = json.loads((source / "metadata.json").read_text(encoding="utf-8"))
    if int(metadata["stream_seed"]) != seed:
        raise RuntimeError(f"seed {seed} metadata mismatch")
    with (source / "raw_runs.csv").open(encoding="utf-8", newline="") as handle:
        source_rows = list(csv.DictReader(handle))
    if len(source_rows) != 4 or {row["arm"] for row in source_rows} != set(ARMS):
        raise RuntimeError(f"seed {seed} does not contain the four approved schemes")
    rows = [
        {
            "stream_seed": seed,
            "stream_sha256": metadata["stream_sha256"],
            "arm": row["arm"],
            "total_cost_with_lost_revenue_cny": float(
                row["total_cost_with_lost_revenue_cny"]
            ),
            "completion_rate_pct": float(row["completion_rate_pct"]),
            "rejected_customer_count": int(row["rejected_customer_count"]),
            "evaluation_count": int(row["evaluation_count"]),
            "legal": row["legal"].lower() == "true",
            "status": row["status"],
            "source_raw_runs_sha256": _sha256(source / "raw_runs.csv"),
        }
        for row in source_rows
    ]
    evidence = {
        "directory": source.name,
        "artifact_manifest_sha256": _sha256(manifest_path),
        "stream_sha256": metadata["stream_sha256"],
    }
    return rows, evidence


def comparison_rows(
    rows: Sequence[Mapping[str, Any]],
    pairs: Sequence[tuple[str, str]] = PER_ORDER_PAIRS,
    *,
    seeds: Sequence[int] | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    selected_seeds = tuple(seeds) if seeds is not None else tuple(
        sorted({int(row["stream_seed"]) for row in rows})
    )
    for seed in selected_seeds:
        by_arm = {
            str(row["arm"]): row for row in rows if int(row["stream_seed"]) == seed
        }
        for left_arm, right_arm in pairs:
            left = by_arm[left_arm]
            right = by_arm[right_arm]
            cost_delta = float(left["total_cost_with_lost_revenue_cny"]) - float(
                right["total_cost_with_lost_revenue_cny"]
            )
            outcome = (
                "win" if cost_delta < 0.0 else "loss" if cost_delta > 0.0 else "tie"
            )
            result.append(
                {
                    "stream_seed": seed,
                    "left_arm": left_arm,
                    "right_arm": right_arm,
                    "total_cost_delta_cny": cost_delta,
                    "completion_rate_delta_percentage_points": float(
                        left["completion_rate_pct"]
                    )
                    - float(right["completion_rate_pct"]),
                    "rejected_count_delta": int(left["rejected_customer_count"])
                    - int(right["rejected_customer_count"]),
                    "evaluation_count_delta": int(left["evaluation_count"])
                    - int(right["evaluation_count"]),
                    "left_cost_outcome": outcome,
                }
            )
    return result


def _report(
    rows: Sequence[Mapping[str, Any]],
    comparisons: Sequence[Mapping[str, Any]],
    all_legal: bool,
    seeds: Sequence[int] = DEFAULT_SEEDS,
) -> str:
    seed_text = "、".join(str(seed) for seed in seeds)
    seed_count_text = "三个" if len(seeds) == 3 else f"{len(seeds)}个"
    lines = [
        f"# E7 {seed_count_text}订单流种子汇总",
        "",
        f"seed {seed_text} 都使用同一个50客户算例、500kg阈值、30分钟上限、"
        "1.5元/kg拒单损失、原车型上限和每候选8次评价。",
        "",
        "本汇总是当前读者入口。旧单种子报告作为历史产物保留；其中的“全信息静态参照”"
        "在这里统一称为“全信息一次性静态参照”。该方案是邱莹莹式一次启发式排程，"
        "不是数学最优或理论上界。",
        "",
        "| 种子 | 方案 | 总口径成本(元) | 完成率 | 拒单数 | 总评价次数 | 合法 |",
        "|---:|---|---:|---:|---:|---:|:---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['stream_seed']} | {ARM_LABELS[str(row['arm'])]} | "
            f"{float(row['total_cost_with_lost_revenue_cny']):.2f} | "
            f"{float(row['completion_rate_pct']):.2f}% | "
            f"{row['rejected_customer_count']} | {row['evaluation_count']} | "
            f"{'是' if row['legal'] else '否'} |"
        )
    if not all_legal:
        lines.extend(
            [
                "",
                "至少一个方案的完整检查未通过。按约定保留原始结果，不生成胜负结论。",
            ]
        )
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "",
            "下表的差值均为“左侧方案 减 右侧方案”；成本差为负即左侧方案更省钱。",
            "",
            "| 种子 | 左侧方案 | 右侧方案 | 成本差(元) | 完成率差(百分点) | 拒单数差 | 评价次数差 | 成本胜负 |",
            "|---:|---|---|---:|---:|---:|---:|---|",
        ]
    )
    outcome_label = {"win": "左侧胜", "loss": "左侧负", "tie": "持平"}
    for row in comparisons:
        lines.append(
            f"| {row['stream_seed']} | {ARM_LABELS[str(row['left_arm'])]} | "
            f"{ARM_LABELS[str(row['right_arm'])]} | "
            f"{float(row['total_cost_delta_cny']):+.2f} | "
            f"{float(row['completion_rate_delta_percentage_points']):+.2f} | "
            f"{int(row['rejected_count_delta']):+d} | "
            f"{int(row['evaluation_count_delta']):+d} | "
            f"{outcome_label[str(row['left_cost_outcome'])]} |"
        )
    lines.append("")
    pairs = list(
        dict.fromkeys(
            (str(row["left_arm"]), str(row["right_arm"]))
            for row in comparisons
        )
    )
    for left_arm, right_arm in pairs:
        group = [
            row
            for row in comparisons
            if row["left_arm"] == left_arm and row["right_arm"] == right_arm
        ]
        wins = sum(row["left_cost_outcome"] == "win" for row in group)
        losses = sum(row["left_cost_outcome"] == "loss" for row in group)
        ties = sum(row["left_cost_outcome"] == "tie" for row in group)
        lines.append(
            f"{ARM_LABELS[left_arm]} 对 {ARM_LABELS[right_arm]}："
            f"左侧方案 {wins} 胜、{losses} 负、{ties} 平。"
        )
    hybrid_fixed = [
        row
        for row in comparisons
        if row["left_arm"] == "hybrid_500kg_or_30_minutes"
        and row["right_arm"] == "fixed_30_minutes"
    ]
    if hybrid_fixed:
        lower_cost = sum(row["total_cost_delta_cny"] < 0.0 for row in hybrid_fixed)
        fewer_rejections = sum(row["rejected_count_delta"] < 0 for row in hybrid_fixed)
        lines.extend(
            [
                "",
                f"混合触发相对固定30分钟：{lower_cost}/{len(hybrid_fixed)} 个种子的总口径成本更低，"
                f"其中 {fewer_rejections}/{len(hybrid_fixed)} 个种子拒单更少。",
            ]
        )
    lines.extend(
        [
            "",
            f"本汇总是{seed_count_text}种子的低成本小试事实表，不是正式结果，也不是实验成功门。",
        ]
    )
    return "\n".join(lines) + "\n"


def run(
    output: Path,
    *,
    seed3_source: Path | None = None,
    all_pairwise: bool = False,
    seeds: Sequence[int] = DEFAULT_SEEDS,
) -> None:
    if output.exists():
        raise RuntimeError(f"refusing to overwrite {output}")
    seeds = tuple(seeds)
    if not seeds:
        raise ValueError("at least one stream seed is required")
    rows: list[dict[str, Any]] = []
    sources: dict[str, Any] = {}
    for seed in seeds:
        seed_rows, evidence = _load_seed(
            seed, seed3_source if seed == 3 else None
        )
        rows.extend(seed_rows)
        sources[str(seed)] = evidence
    rows.sort(key=lambda row: (int(row["stream_seed"]), ARMS.index(str(row["arm"]))))
    all_legal = all(bool(row["legal"]) and row["status"] == "PASS" for row in rows)
    pairs = ALL_DYNAMIC_PAIRS if all_pairwise else PER_ORDER_PAIRS
    comparisons = comparison_rows(rows, pairs, seeds=seeds) if all_legal else []

    output.mkdir(parents=True)
    _write_csv(output / "raw_runs.csv", rows)
    _write_json(
        output / "metadata.json",
        {
            "schema": "resetp.e7.qiu-trigger-seed-aggregate.v1",
            "evidence_role": (
                "LOW_COST_THREE_SEED_PILOT_AGGREGATE"
                if seeds == DEFAULT_SEEDS
                else "LOW_COST_MULTI_SEED_PILOT_AGGREGATE"
            ),
            "created_at_utc": datetime.now(UTC).isoformat(),
            "stream_seeds": list(seeds),
            "source_artifacts": sources,
            "row_count": len(rows),
            "comparison_pairs": [list(pair) for pair in pairs],
        },
    )
    counts = {
        f"{left_arm}_minus_{right_arm}": {
            outcome: sum(
                row["left_arm"] == left_arm
                and row["right_arm"] == right_arm
                and row["left_cost_outcome"] == outcome
                for row in comparisons
            )
            for outcome in ("win", "loss", "tie")
        }
        for left_arm, right_arm in pairs
    }
    per_order_counts = {
        right_arm: counts[f"per_order_minus_{right_arm}"]
        for left_arm, right_arm in pairs
        if left_arm == "per_order"
    }
    seed_tag = f"{seeds[0]}TO{seeds[-1]}"
    decision = {
        "verdict": (
            f"PASS_E7_QIU_50C_SEEDS{seed_tag}_TECHNICAL_AGGREGATE"
            if all_legal
            else f"HALT_E7_QIU_50C_SEEDS{seed_tag}_TECHNICAL_CHECK"
        ),
        "formal_result": False,
        "success_gate": False,
        "all_candidates_retained": True,
        "all_summary_rows_technical_legal": all_legal,
        "comparison_generated": all_legal,
        "comparison_scope": (
            "all_three_dynamic_pairwise" if all_pairwise else "per_order_only"
        ),
        "pairwise_cost_outcome_counts": counts if all_legal else {},
        "per_order_cost_outcome_counts": per_order_counts if all_legal else {},
    }
    if seeds == DEFAULT_SEEDS:
        decision["all_twelve_summaries_technical_legal"] = all_legal
    _write_json(
        output / "decision.json",
        decision,
    )
    (output / "report.md").write_text(
        _report(rows, comparisons, all_legal, seeds), encoding="utf-8"
    )
    artifacts = {
        path.name: _sha256(path)
        for path in output.iterdir()
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    _write_json(output / "artifact_hashes.json", artifacts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--seed3-source", type=Path)
    parser.add_argument("--all-pairwise", action="store_true")
    parser.add_argument("--seeds", type=int, nargs="+", default=DEFAULT_SEEDS)
    args = parser.parse_args()
    run(
        args.output.resolve(),
        seed3_source=(
            args.seed3_source.resolve() if args.seed3_source is not None else None
        ),
        all_pairwise=args.all_pairwise,
        seeds=args.seeds,
    )


if __name__ == "__main__":
    main()
