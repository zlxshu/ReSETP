#!/usr/bin/env python3
"""Build manuscript exhibits from the sealed 2026-07-15 evidence packages."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import pandas as pd
from fontTools.ttLib import TTCollection


ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "docs/paper_submission_final"
TABLES = MAIN / "generated_tables"
FIGURES = MAIN / "generated_figures"
E2B = ROOT / "baselines/e2_alns/e2b_component_ablation_formal_20260715"
E3 = ROOT / "baselines/e3_ablation/e3_medium_paired_cost_formal_20260715"
E6 = ROOT / "baselines/e6_fairness/e6_profit_guarantee_frontier_20260715"
E7_AUDIT = ROOT / "baselines/e7_dynamic/e7_multinetwork_independent_audit_20260715"
E7_REPLAY = ROOT / "baselines/e7_dynamic/e7_multiday_zero_search_replay_20260715"

E7_POLICY_TABLE_NAME = "e7_dynamic_policy_comparison.tex"
E7_DIAGNOSTICS_TABLE_NAME = "e7_dynamic_mechanism_diagnostics.tex"
E7_REPLAY_TABLE_NAME = "e7_dynamic_charging_replay.tex"
E7_INTERPRETATION_NAME = "e7_dynamic_interpretation.tex"
E7_CONCLUSION_NAME = "e7_dynamic_conclusion.tex"
E7_ABSTRACT_ZH_NAME = "e7_dynamic_abstract_zh.tex"
E7_ABSTRACT_EN_NAME = "e7_dynamic_abstract_en.tex"
E7_EXHIBIT_NAMES = (
    E7_POLICY_TABLE_NAME,
    E7_DIAGNOSTICS_TABLE_NAME,
    E7_REPLAY_TABLE_NAME,
    E7_INTERPRETATION_NAME,
    E7_CONCLUSION_NAME,
    E7_ABSTRACT_ZH_NAME,
    E7_ABSTRACT_EN_NAME,
)
E7_PROVENANCE_NAME = "e7_dynamic_paper_evidence_manifest.json"
E7_AUDIT_SOURCE_FILES = (
    "metadata.json",
    "raw_runs.csv",
    "decision.json",
    "artifact_hashes.json",
    "report.md",
    "task_status.csv",
    "paired_summary.csv",
    "replay_summary.csv",
)
E7_REPLAY_SOURCE_FILES = (
    "metadata.json",
    "raw_runs.csv",
    "decision.json",
    "artifact_hashes.json",
    "report.md",
    "summary.csv",
    "task_inventory.json",
)
E7_OPERATING_DAYS = tuple(f"2025-11-{day:02d}" for day in range(2, 30))
E7_TOL = 1e-6

E7_NETWORK_LABELS = {"N114": "50客户", "N221": "100客户", "N322": "150客户"}
E7_CONDITION_LABELS = {"geographic": "地理聚集", "historical_mixed": "空间交错"}
E7_ARM_LABELS = {
    "full": "完整机制",
    "no_cooperation": "禁合作",
    "no_participation": "无参与底线",
    "simple_insertion": "顺序插入基线",
}
E7_COMPARISONS = (
    (
        "禁合作",
        "full_minus_no_cooperation_net_profit",
        "full_minus_no_cooperation_revenue",
        "full_minus_no_cooperation_cost",
        "full_minus_no_cooperation_completed_customer_count",
        "full_minus_no_cooperation_completed_demand",
    ),
    (
        "无参与底线",
        "full_minus_no_participation_net_profit",
        "full_minus_no_participation_revenue",
        "full_minus_no_participation_system_cost",
        "full_minus_no_participation_completed_customer_count",
        "full_minus_no_participation_completed_demand",
    ),
    (
        "顺序插入基线",
        "full_minus_simple_insertion_net_profit",
        "full_minus_simple_insertion_revenue",
        "full_minus_simple_insertion_cost",
        "full_minus_simple_insertion_completed_customer_count",
        "full_minus_simple_insertion_completed_demand",
    ),
)


class E7PaperEvidenceError(RuntimeError):
    """Raised when sealed E7 evidence cannot reproduce the paper exhibits."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def write_table(name: str, lines: list[str]) -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    (TABLES / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def truthy(value: object) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def e7_cell_label(row: pd.Series) -> str:
    return (
        f"{E7_NETWORK_LABELS[str(row['network'])]}—"
        f"{E7_CONDITION_LABELS[str(row['condition'])]}—流{int(row['stream'])}"
    )


def e7_sign_counts(values: pd.Series, tolerance: float = 1e-6) -> tuple[int, int, int]:
    numeric = pd.to_numeric(values, errors="raise")
    return (
        int((numeric > tolerance).sum()),
        int((numeric < -tolerance).sum()),
        int((numeric.abs() <= tolerance).sum()),
    )


def _require_columns(frame: pd.DataFrame, fields: set[str], label: str) -> None:
    missing = sorted(fields - set(frame.columns))
    if missing:
        raise E7PaperEvidenceError(f"{label} columns are missing: {missing}")


def _ordered_cells(frame: pd.DataFrame) -> pd.DataFrame:
    ordered = frame.copy()
    ordered["_network_order"] = ordered["network"].map(
        {name: index for index, name in enumerate(E7_NETWORK_LABELS)}
    )
    ordered["_condition_order"] = ordered["condition"].map(
        {name: index for index, name in enumerate(E7_CONDITION_LABELS)}
    )
    if ordered[["_network_order", "_condition_order"]].isna().any().any():
        raise E7PaperEvidenceError("E7 evidence contains an unknown network or condition")
    sort_fields = ["_network_order", "_condition_order"]
    if "stream" in ordered:
        sort_fields.append("stream")
    if "arm" in ordered:
        ordered["_arm_order"] = ordered["arm"].map(
            {name: index for index, name in enumerate(E7_ARM_LABELS)}
        )
        if ordered["_arm_order"].isna().any():
            raise E7PaperEvidenceError("E7 evidence contains an unknown arm")
        sort_fields.append("_arm_order")
    return ordered.sort_values(sort_fields, kind="stable").drop(
        columns=[field for field in ("_network_order", "_condition_order", "_arm_order") if field in ordered]
    ).reset_index(drop=True)


def _assert_close(observed: object, expected: float, label: str) -> None:
    try:
        numeric = float(observed)
    except (TypeError, ValueError) as exc:
        raise E7PaperEvidenceError(f"{label} is not numeric") from exc
    if not math.isfinite(numeric) or not math.isclose(
        numeric, expected, rel_tol=1e-10, abs_tol=1e-8
    ):
        raise E7PaperEvidenceError(
            f"{label} differs from recomputation: {numeric!r} != {expected!r}"
        )


def verify_e7_source_manifest(root: Path) -> None:
    manifest_path = root / "artifact_hashes.json"
    if not manifest_path.is_file():
        raise E7PaperEvidenceError(f"E7 source manifest is missing: {root}")
    sidecars = list(root.rglob("._*"))
    if sidecars:
        raise E7PaperEvidenceError(f"E7 source contains AppleDouble files: {root}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise E7PaperEvidenceError(f"E7 source manifest is not a mapping: {root}")
    observed = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and ".tasks" not in path.parts
    }
    if observed != set(manifest):
        raise E7PaperEvidenceError(
            f"E7 source inventory differs at {root}: "
            f"unlisted={sorted(observed - set(manifest))}, "
            f"missing={sorted(set(manifest) - observed)}"
        )
    drift = [
        relative
        for relative, expected in manifest.items()
        if sha256(root / relative) != expected
    ]
    if drift:
        raise E7PaperEvidenceError(f"E7 source hash drift at {root}: {drift}")


def validate_e7_pair_evidence(
    pair_rows: pd.DataFrame,
    task_status: pd.DataFrame,
    paired_summary: pd.DataFrame,
) -> None:
    """Recompute every table field except the sealed cross-site diagnostic.

    The independent audit's pair rows do not expose per-stream cross-site counts.
    Therefore ``full_streams_with_cross_site_service`` remains an explicitly
    sealed derived field: it is range-checked here and bound by the audit source
    manifest, but is not misrepresented as a bottom-level recomputation.
    """

    _require_columns(
        pair_rows,
        {
            "network",
            "condition",
            "stream",
            "all_four_arms_executable",
            "full_day_participation_floor_met",
            *{field for comparison in E7_COMPARISONS for field in comparison[1:]},
        },
        "E7 pair rows",
    )
    _require_columns(
        task_status,
        {
            "network",
            "condition",
            "stream",
            "arm",
            "execution_status",
            "deadline_comparable_stage_count",
            "stage_deadline_miss_count",
            "maximum_stage_elapsed_seconds",
        },
        "E7 task status",
    )
    _require_columns(
        paired_summary,
        {
            "network",
            "condition",
            "expected_stream_count",
            "paired_complete_stream_count",
            "full_day_participation_floor_met_count",
            "full_streams_with_cross_site_service",
            "full_deadline_comparable_stage_count",
            "full_stage_deadline_miss_count",
            "full_maximum_stage_elapsed_seconds",
            *{
                field
                for comparison in E7_COMPARISONS
                for field in (f"{name}_mean" for name in comparison[1:])
            },
            "full_vs_no_cooperation_better_worse_tied",
            "full_vs_no_participation_better_worse_tied",
            "full_vs_simple_insertion_better_worse_tied",
            *{
                f"{arm}_executable_stream_count"
                for arm in E7_ARM_LABELS
            },
        },
        "E7 paired summary",
    )
    expected_pairs = {
        (network, condition, stream)
        for network in E7_NETWORK_LABELS
        for condition in E7_CONDITION_LABELS
        for stream in range(1, 6)
    }
    observed_pairs = {
        (str(row.network), str(row.condition), int(row.stream))
        for row in pair_rows.itertuples(index=False)
    }
    if len(pair_rows) != 30 or observed_pairs != expected_pairs:
        raise E7PaperEvidenceError("E7 pair rows do not contain the exact 3 x 2 x 5 design")
    expected_tasks = {
        (*pair, arm) for pair in expected_pairs for arm in E7_ARM_LABELS
    }
    observed_tasks = {
        (str(row.network), str(row.condition), int(row.stream), str(row.arm))
        for row in task_status.itertuples(index=False)
    }
    if len(task_status) != 120 or observed_tasks != expected_tasks:
        raise E7PaperEvidenceError("E7 task status does not contain the exact 120-task design")
    observed_cells = {
        (str(row.network), str(row.condition))
        for row in paired_summary.itertuples(index=False)
    }
    expected_cells = {
        (network, condition)
        for network in E7_NETWORK_LABELS
        for condition in E7_CONDITION_LABELS
    }
    if len(paired_summary) != 6 or observed_cells != expected_cells:
        raise E7PaperEvidenceError("E7 paired summary does not contain the exact six cells")

    bwt_fields = (
        "full_vs_no_cooperation_better_worse_tied",
        "full_vs_no_participation_better_worse_tied",
        "full_vs_simple_insertion_better_worse_tied",
    )
    for network, condition in sorted(expected_cells):
        pair_cell = pair_rows[
            pair_rows["network"].astype(str).eq(network)
            & pair_rows["condition"].astype(str).eq(condition)
        ].copy()
        task_cell = task_status[
            task_status["network"].astype(str).eq(network)
            & task_status["condition"].astype(str).eq(condition)
        ].copy()
        summary_rows = paired_summary[
            paired_summary["network"].astype(str).eq(network)
            & paired_summary["condition"].astype(str).eq(condition)
        ]
        if len(pair_cell) != 5 or len(task_cell) != 20 or len(summary_rows) != 1:
            raise E7PaperEvidenceError(f"E7 cell multiplicity differs: {network}/{condition}")
        summary = summary_rows.iloc[0]
        if int(summary["expected_stream_count"]) != 5:
            raise E7PaperEvidenceError(f"E7 expected-stream count differs: {network}/{condition}")
        complete = pair_cell[pair_cell["all_four_arms_executable"].map(truthy)].copy()
        if complete.empty:
            raise E7PaperEvidenceError(f"E7 cell has no complete four-arm pair: {network}/{condition}")
        if int(summary["paired_complete_stream_count"]) != len(complete):
            raise E7PaperEvidenceError(f"E7 complete-pair count differs: {network}/{condition}")
        participation = int(complete["full_day_participation_floor_met"].map(truthy).sum())
        if int(summary["full_day_participation_floor_met_count"]) != participation:
            raise E7PaperEvidenceError(f"E7 participation count differs: {network}/{condition}")

        for comparison, bwt_field in zip(E7_COMPARISONS, bwt_fields):
            profit_field = comparison[1]
            for field in comparison[1:]:
                numeric = pd.to_numeric(complete[field], errors="raise")
                _assert_close(
                    summary[f"{field}_mean"],
                    float(numeric.mean()),
                    f"E7 paired summary {network}/{condition}/{field}",
                )
            better, worse, tied = e7_sign_counts(complete[profit_field], E7_TOL)
            expected_bwt = f"{better}/{worse}/{tied}"
            if str(summary[bwt_field]) != expected_bwt:
                raise E7PaperEvidenceError(
                    f"E7 sign counts differ: {network}/{condition}/{bwt_field}"
                )

        for arm in E7_ARM_LABELS:
            expected_count = int(
                (
                    task_cell["arm"].astype(str).eq(arm)
                    & task_cell["execution_status"].astype(str).eq("PASS")
                ).sum()
            )
            if int(summary[f"{arm}_executable_stream_count"]) != expected_count:
                raise E7PaperEvidenceError(
                    f"E7 executable count differs: {network}/{condition}/{arm}"
                )
        full_tasks = task_cell[task_cell["arm"].astype(str).eq("full")]
        expected_comparable = int(
            pd.to_numeric(full_tasks["deadline_comparable_stage_count"], errors="raise").sum()
        )
        expected_misses = int(
            pd.to_numeric(full_tasks["stage_deadline_miss_count"], errors="raise").sum()
        )
        if int(summary["full_deadline_comparable_stage_count"]) != expected_comparable:
            raise E7PaperEvidenceError(f"E7 deadline denominator differs: {network}/{condition}")
        if int(summary["full_stage_deadline_miss_count"]) != expected_misses:
            raise E7PaperEvidenceError(f"E7 deadline misses differ: {network}/{condition}")
        _assert_close(
            summary["full_maximum_stage_elapsed_seconds"],
            float(
                pd.to_numeric(full_tasks["maximum_stage_elapsed_seconds"], errors="raise").max()
            ),
            f"E7 maximum stage time {network}/{condition}",
        )
        cross_site = int(summary["full_streams_with_cross_site_service"])
        full_executable = int(summary["full_executable_stream_count"])
        if not 0 <= cross_site <= full_executable <= 5:
            raise E7PaperEvidenceError(
                f"E7 sealed cross-site diagnostic is out of range: {network}/{condition}"
            )


def summarize_e7_replay(replay_rows: pd.DataFrame) -> pd.DataFrame:
    """Purely rebuild the six 28-day cells from the 840 sealed day rows."""

    required = {
        "network",
        "condition",
        "stream",
        "arm",
        "operating_day",
        "actual_charging_saving_kg",
        "immediate_actual_charging_emissions_kg",
        "direct_emissions_kg",
        "charging_reduction_pct",
        "route_hash_preserved",
        "energy_hash_preserved",
    }
    _require_columns(replay_rows, required, "E7 replay raw rows")
    expected = {
        (network, condition, stream, "full", day)
        for network in E7_NETWORK_LABELS
        for condition in E7_CONDITION_LABELS
        for stream in range(1, 6)
        for day in E7_OPERATING_DAYS
    }
    observed = {
        (
            str(row.network),
            str(row.condition),
            int(row.stream),
            str(row.arm),
            str(row.operating_day),
        )
        for row in replay_rows.itertuples(index=False)
    }
    if len(replay_rows) != 840 or observed != expected:
        raise E7PaperEvidenceError("E7 replay rows do not contain the exact 3 x 2 x 5 x 28 design")
    if not replay_rows["route_hash_preserved"].map(truthy).all() or not replay_rows[
        "energy_hash_preserved"
    ].map(truthy).all():
        raise E7PaperEvidenceError("E7 replay changes a sealed route or charging-energy hash")

    rows: list[dict[str, Any]] = []
    for network in E7_NETWORK_LABELS:
        for condition in E7_CONDITION_LABELS:
            group = replay_rows[
                replay_rows["network"].astype(str).eq(network)
                & replay_rows["condition"].astype(str).eq(condition)
            ].copy()
            if len(group) != 140:
                raise E7PaperEvidenceError(f"E7 replay cell is not 140 rows: {network}/{condition}")
            savings = pd.to_numeric(group["actual_charging_saving_kg"], errors="raise")
            immediate = pd.to_numeric(
                group["immediate_actual_charging_emissions_kg"], errors="raise"
            )
            direct = pd.to_numeric(group["direct_emissions_kg"], errors="raise")
            day_reduction = pd.to_numeric(group["charging_reduction_pct"], errors="raise")
            for field, values in (
                ("savings", savings),
                ("immediate", immediate),
                ("direct", direct),
                ("charging_reduction_pct", day_reduction),
            ):
                if not values.map(math.isfinite).all():
                    raise E7PaperEvidenceError(
                        f"E7 replay contains non-finite {field}: {network}/{condition}"
                    )
            saving_total = float(savings.sum())
            immediate_total = float(immediate.sum())
            direct_total = float(direct.sum())

            def pct(delta: float, baseline: float) -> float:
                return 100.0 * delta / baseline if abs(baseline) > E7_TOL else 0.0

            rows.append(
                {
                    "network": network,
                    "condition": condition,
                    "arm": "full",
                    "stream_day_count": len(group),
                    "pooled_charging_reduction_pct": pct(saving_total, immediate_total),
                    "pooled_total_operational_reduction_pct": pct(
                        saving_total, direct_total + immediate_total
                    ),
                    "mean_day_task_charging_reduction_pct": float(day_reduction.mean()),
                    "improved": int((savings > E7_TOL).sum()),
                    "worsened": int((savings < -E7_TOL).sum()),
                    "tied": int((savings.abs() <= E7_TOL).sum()),
                }
            )
    return pd.DataFrame(rows)


def validate_e7_replay_summary(
    observed: pd.DataFrame, recomputed: pd.DataFrame, label: str
) -> None:
    fields = list(recomputed.columns)
    _require_columns(observed, set(fields), label)
    actual = _ordered_cells(observed[fields])
    expected = _ordered_cells(recomputed[fields])
    if len(actual) != 6:
        raise E7PaperEvidenceError(f"{label} does not contain six cells")
    for index in range(6):
        for field in fields:
            actual_value = actual.iloc[index][field]
            expected_value = expected.iloc[index][field]
            if field in {"network", "condition", "arm"}:
                if str(actual_value) != str(expected_value):
                    raise E7PaperEvidenceError(f"{label} identity differs: {field}")
            elif field in {"stream_day_count", "improved", "worsened", "tied"}:
                if int(actual_value) != int(expected_value):
                    raise E7PaperEvidenceError(f"{label} count differs: {field}")
            else:
                _assert_close(actual_value, float(expected_value), f"{label}/{field}")


def render_e7_policy_comparison(paired_summary: pd.DataFrame) -> str:
    paired = _ordered_cells(paired_summary)
    comparisons = tuple(
        (label, *(f"{field}_mean" for field in fields))
        for label, *fields in E7_COMPARISONS
    )
    lines = [
        r"\begin{tabular*}{0.99\linewidth}{@{\extracolsep{\fill}}lllrrrrr@{}}",
        r"\toprule",
        r"网络 & 客户责任 & 完整机制相对 & $\Delta$净收益 & $\Delta$收入 & $\Delta$成本 & $\Delta$客户 & $\Delta$需求 \\",
        r"\midrule",
    ]
    for row in paired.itertuples(index=False):
        if int(row.paired_complete_stream_count) <= 0:
            raise E7PaperEvidenceError(
                f"E7 cell has no complete pair: {row.network}/{row.condition}"
            )
        for label, profit, revenue, cost, customers, demand in comparisons:
            lines.append(
                f"{E7_NETWORK_LABELS[str(row.network)]} & "
                f"{E7_CONDITION_LABELS[str(row.condition)]} & {label} & "
                f"{float(getattr(row, profit)):+.1f} & "
                f"{float(getattr(row, revenue)):+.1f} & "
                f"{float(getattr(row, cost)):+.1f} & "
                f"{float(getattr(row, customers)):+.2f} & "
                f"{float(getattr(row, demand)):+.1f} " + r"\\"
            )
    lines.extend([r"\bottomrule", r"\end{tabular*}"])
    return "\n".join(lines) + "\n"


def render_e7_mechanism_diagnostics(paired_summary: pd.DataFrame) -> str:
    paired = _ordered_cells(paired_summary)
    lines = [
        r"\begin{tabular*}{0.99\linewidth}{@{\extracolsep{\fill}}llrrrrrrr@{}}",
        r"\toprule",
        r"网络 & 客户责任 & 四种机制可执行 & 配对/参与 & 跨场流 & 超时阶段 & 完整/禁合作 & 完整/无底线 & 完整/顺序插入 \\",
        r"\midrule",
    ]
    for row in paired.itertuples(index=False):
        executable = "/".join(
            str(int(getattr(row, f"{arm}_executable_stream_count")))
            for arm in E7_ARM_LABELS
        )
        lines.append(
            f"{E7_NETWORK_LABELS[str(row.network)]} & "
            f"{E7_CONDITION_LABELS[str(row.condition)]} & {executable} & "
            f"{int(row.paired_complete_stream_count)}/"
            f"{int(row.full_day_participation_floor_met_count)} & "
            f"{int(row.full_streams_with_cross_site_service)}/"
            f"{int(row.full_executable_stream_count)} & "
            f"{int(row.full_stage_deadline_miss_count)}/"
            f"{int(row.full_deadline_comparable_stage_count)} & "
            f"{row.full_vs_no_cooperation_better_worse_tied} & "
            f"{row.full_vs_no_participation_better_worse_tied} & "
            f"{row.full_vs_simple_insertion_better_worse_tied} " + r"\\"
        )
    lines.extend([r"\bottomrule", r"\end{tabular*}"])
    return "\n".join(lines) + "\n"


def render_e7_charging_replay(replay_summary: pd.DataFrame) -> str:
    replay = _ordered_cells(replay_summary)
    lines = [
        r"\begin{tabular*}{0.92\linewidth}{@{\extracolsep{\fill}}llrrrr@{}}",
        r"\toprule",
        r"网络 & 客户责任 & 充电排放降幅/\% & 总运营排放降幅/\% & 改善/变差/持平 & 配对数 \\",
        r"\midrule",
    ]
    for row in replay.itertuples(index=False):
        lines.append(
            f"{E7_NETWORK_LABELS[str(row.network)]} & "
            f"{E7_CONDITION_LABELS[str(row.condition)]} & "
            f"{float(row.pooled_charging_reduction_pct):.2f} & "
            f"{float(row.pooled_total_operational_reduction_pct):.2f} & "
            f"{int(row.improved)}/{int(row.worsened)}/{int(row.tied)} & "
            f"{int(row.stream_day_count)} " + r"\\"
        )
    lines.extend([r"\bottomrule", r"\end{tabular*}"])
    return "\n".join(lines) + "\n"


def render_e7_interpretation(
    pair_rows: pd.DataFrame,
    task_status: pd.DataFrame,
    paired_summary: pd.DataFrame,
    replay_summary: pd.DataFrame,
    decision: dict[str, object],
) -> str:
    """Render result-first E7 prose without smoothing failures or cell extrema."""
    pair_rows = _ordered_cells(pair_rows)
    task_status = _ordered_cells(task_status)
    paired_summary = _ordered_cells(paired_summary)
    replay_summary = _ordered_cells(replay_summary)
    if len(pair_rows) != 30 or len(task_status) != 120:
        raise RuntimeError("E7 narrative requires 30 stream pairs and 120 task statuses")
    if len(paired_summary) != 6 or len(replay_summary) != 6:
        raise RuntimeError("E7 narrative requires six dynamic and six replay cells")
    expected_pairs = {
        (network, condition, stream)
        for network in E7_NETWORK_LABELS
        for condition in E7_CONDITION_LABELS
        for stream in range(1, 6)
    }
    observed_pairs = {
        (str(row.network), str(row.condition), int(row.stream))
        for row in pair_rows.itertuples(index=False)
    }
    if observed_pairs != expected_pairs:
        raise RuntimeError("E7 narrative pair identities are incomplete or unexpected")
    observed_tasks = {
        (str(row.network), str(row.condition), int(row.stream), str(row.arm))
        for row in task_status.itertuples(index=False)
    }
    expected_tasks = {
        (*pair, arm) for pair in expected_pairs for arm in E7_ARM_LABELS
    }
    if observed_tasks != expected_tasks:
        raise RuntimeError("E7 narrative task identities are incomplete or unexpected")
    complete = pair_rows[pair_rows["all_four_arms_executable"].map(truthy)].copy()
    if complete.empty:
        raise RuntimeError("E7 narrative has no four-arm executable stream")
    if int(paired_summary["paired_complete_stream_count"].sum()) != len(complete):
        raise RuntimeError("E7 pair rows disagree with the six-cell complete-pair counts")

    failures = task_status[task_status["execution_status"] != "PASS"].copy()
    controlled = int(decision.get("controlled_arm_failure_count", -1))
    if controlled != len(failures):
        raise RuntimeError(
            "E7 controlled failure count disagrees with the task-status evidence"
        )
    failure_text = ""
    if controlled:
        identities = "、".join(
            f"{E7_NETWORK_LABELS[str(row.network)]}—"
            f"{E7_CONDITION_LABELS[str(row.condition)]}—流{int(row.stream)}—"
            f"{E7_ARM_LABELS[str(row.arm)]}"
            for row in failures.itertuples(index=False)
        )
        failure_text = (
            f"其中{controlled}个受控不可执行单元为{identities}；这些单元保留在"
            "可执行率中，不进入四种机制的成对均值。"
        )
    else:
        failure_text = "120个正式任务全部完成，未观察到受控不可执行单元。"

    deadline_misses = int(paired_summary["full_stage_deadline_miss_count"].sum())
    deadline_total = int(paired_summary["full_deadline_comparable_stage_count"].sum())
    maximum_elapsed = float(paired_summary["full_maximum_stage_elapsed_seconds"].max())
    if deadline_misses:
        timing_text = (
            f"完整机制有{deadline_misses}个阶段超过下一触发间隔，"
            f"可比较阶段共{deadline_total}个，最长阶段用时{maximum_elapsed:.1f} s；"
            "因此本批结果只能解释为批量滚动决策支持，不能改称实时求解。"
        )
    else:
        timing_text = (
            f"完整机制的{deadline_total}个可比较阶段均满足实时响应条件，"
            f"最长阶段用时{maximum_elapsed:.1f} s。"
        )
    cross_site = int(paired_summary["full_streams_with_cross_site_service"].sum())
    full_executable = int(paired_summary["full_executable_stream_count"].sum())
    floor_met = int(paired_summary["full_day_participation_floor_met_count"].sum())
    opening = (
        f"正式矩阵包含120个任务，其中{len(complete)}/30个订单流的四种机制均可执行；完整机制在"
        f"{cross_site}/{full_executable}条可执行订单流中实际发生跨场服务，并在"
        f"{floor_met}/{len(complete)}个完整配对中满足全日参与底线。{failure_text}"
        f"{timing_text}"
    )

    comparison_paragraphs: list[str] = []
    for label, profit, revenue, cost, customers, demand in E7_COMPARISONS:
        for field in (profit, revenue, cost, customers, demand):
            complete[field] = pd.to_numeric(complete[field], errors="raise")
        better, worse, tied = e7_sign_counts(complete[profit])
        best = complete.loc[complete[profit].idxmax()]
        worst = complete.loc[complete[profit].idxmin()]
        comparison_paragraphs.append(
            f"在{len(complete)}个完整配对中，完整机制相对{label}的净收益差均值为"
            f"{complete[profit].mean():+.1f}，改善/变差/持平为"
            f"{better}/{worse}/{tied}；收入、成本、完成客户数和完成需求差均值分别为"
            f"{complete[revenue].mean():+.1f}、{complete[cost].mean():+.1f}、"
            f"{complete[customers].mean():+.2f}和{complete[demand].mean():+.1f}。"
            f"最有利单元是{e7_cell_label(best)}（{float(best[profit]):+.1f}），"
            f"最不利单元是{e7_cell_label(worst)}（{float(worst[profit]):+.1f}）。"
            "净收益差必须与服务收入和工作量差共同解释；这里报告的是观察到的全日结果，"
            "不把均值方向直接解释成单一机制的因果效应。"
        )

    replay = replay_summary.copy()
    for field in (
        "pooled_charging_reduction_pct",
        "pooled_total_operational_reduction_pct",
        "improved",
        "worsened",
        "tied",
        "stream_day_count",
    ):
        replay[field] = pd.to_numeric(replay[field], errors="raise")
    replay_count = int(replay["stream_day_count"].sum())
    improved = int(replay["improved"].sum())
    worsened = int(replay["worsened"].sum())
    tied = int(replay["tied"].sum())
    if replay_count != 840 or improved + worsened + tied != replay_count:
        raise RuntimeError("E7 replay narrative does not contain an exact 840-row partition")
    if not (replay["stream_day_count"] == 140).all():
        raise RuntimeError("E7 replay narrative does not contain 140 rows in every cell")
    charge_min = replay.loc[replay["pooled_charging_reduction_pct"].idxmin()]
    charge_max = replay.loc[replay["pooled_charging_reduction_pct"].idxmax()]
    replay_text = (
        f"28个电网日的充电择时复算形成{replay_count}组配对，改善/变差/持平为"
        f"{improved}/{worsened}/{tied}。六个网络—责任单元的充电排放降幅介于"
        f"{replay['pooled_charging_reduction_pct'].min():.2f}\\%和"
        f"{replay['pooled_charging_reduction_pct'].max():.2f}\\%之间，最低出现在"
        f"{E7_NETWORK_LABELS[str(charge_min['network'])]}—"
        f"{E7_CONDITION_LABELS[str(charge_min['condition'])]}，最高出现在"
        f"{E7_NETWORK_LABELS[str(charge_max['network'])]}—"
        f"{E7_CONDITION_LABELS[str(charge_max['condition'])]}；总运营排放降幅范围为"
        f"{replay['pooled_total_operational_reduction_pct'].min():.2f}\\%--"
        f"{replay['pooled_total_operational_reduction_pct'].max():.2f}\\%。"
        "该结果固定路径、车辆、服务客户和充电电量，只识别合法窗口内充电择时的增量作用，"
        "不构成路径—充电联合优化的证据。"
    )
    return "\n\n".join([opening, *comparison_paragraphs, replay_text]) + "\n"


def render_e7_conclusion(
    pair_rows: pd.DataFrame,
    paired_summary: pd.DataFrame,
    replay_summary: pd.DataFrame,
    decision: dict[str, object],
) -> str:
    pair_rows = _ordered_cells(pair_rows)
    paired_summary = _ordered_cells(paired_summary)
    replay_summary = _ordered_cells(replay_summary)
    complete = pair_rows[pair_rows["all_four_arms_executable"].map(truthy)].copy()
    controlled = int(decision.get("controlled_arm_failure_count", -1))
    misses = int(paired_summary["full_stage_deadline_miss_count"].sum())
    direction_parts: list[str] = []
    for label, profit, *_ in E7_COMPARISONS:
        complete[profit] = pd.to_numeric(complete[profit], errors="raise")
        better, worse, tied = e7_sign_counts(complete[profit])
        direction_parts.append(
            f"相对{label}净收益差均值为{complete[profit].mean():+.1f}"
            f"（{better}/{worse}/{tied}）"
        )
    replay = replay_summary.copy()
    replay["pooled_charging_reduction_pct"] = pd.to_numeric(
        replay["pooled_charging_reduction_pct"], errors="raise"
    )
    timing = (
        f"另有{misses}个阶段超过下一触发间隔，故只支持批量滚动决策解释"
        if misses
        else "全部可比较阶段均满足实时响应条件"
    )
    return (
        f"动态实验中，{len(complete)}/30个订单流的四种机制均可执行，"
        + "，".join(direction_parts)
        + f"；保留{controlled}个受控不可执行单元，{timing}。"
        f"固定配送方案在28个电网日的充电择时复算显示，六个单元的充电排放降幅为"
        f"{replay['pooled_charging_reduction_pct'].min():.2f}\\%--"
        f"{replay['pooled_charging_reduction_pct'].max():.2f}\\%。"
        "这些结果共同说明动态协同的收益、参与保障、可执行性、计算时限和充电减排"
        "必须分项判断，不能压缩成单一优化目标。\n"
    )


def render_e7_abstracts(
    pair_rows: pd.DataFrame,
    paired_summary: pd.DataFrame,
    replay_summary: pd.DataFrame,
    decision: dict[str, object],
) -> tuple[str, str]:
    """Render compact bilingual abstract evidence without selecting a favourable arm."""
    pair_rows = _ordered_cells(pair_rows)
    paired_summary = _ordered_cells(paired_summary)
    replay_summary = _ordered_cells(replay_summary)
    complete = pair_rows[pair_rows["all_four_arms_executable"].map(truthy)].copy()
    if complete.empty:
        raise RuntimeError("E7 abstract has no four-arm executable stream")
    if int(paired_summary["paired_complete_stream_count"].sum()) != len(complete):
        raise RuntimeError("E7 abstract complete-pair counts disagree")
    for label, profit, *_ in E7_COMPARISONS:
        complete[profit] = pd.to_numeric(complete[profit], errors="raise")
        mean_profit = float(complete[profit].mean())
        if not math.isfinite(mean_profit):
            raise RuntimeError(f"E7 abstract contains non-finite {label} profit evidence")
    controlled = int(decision.get("controlled_arm_failure_count", -1))
    if controlled < 0:
        raise RuntimeError("E7 abstract lacks the controlled-failure count")
    misses = int(paired_summary["full_stage_deadline_miss_count"].sum())
    comparable = int(paired_summary["full_deadline_comparable_stage_count"].sum())
    if misses < 0 or comparable < 0 or misses > comparable:
        raise RuntimeError("E7 abstract timing counts are inconsistent")
    replay = replay_summary.copy()
    replay["pooled_charging_reduction_pct"] = pd.to_numeric(
        replay["pooled_charging_reduction_pct"], errors="raise"
    )
    replay_count = int(pd.to_numeric(replay["stream_day_count"], errors="raise").sum())
    if replay_count != 840:
        raise RuntimeError("E7 abstract does not summarize exactly 840 replay pairs")
    low = float(replay["pooled_charging_reduction_pct"].min())
    high = float(replay["pooled_charging_reduction_pct"].max())
    if not math.isfinite(low) or not math.isfinite(high) or low > high:
        raise RuntimeError("E7 abstract charging-reduction range is inconsistent")
    zh = (
        "在“双碳”目标和配送集约化要求下，多车场混合车队既要通过跨场协同降低路径成本，又需依据时变电网碳强度安排电动车充电，并保证各车场愿意参与；动态订单进一步增加了方案执行难度。"
        "针对上述问题，建立可行配送趟—实体车排班两层路径优化模型，以运营成本和碳结算成本之和最小为目标，刻画多趟衔接、连续充电、成员参与和滚动状态继承。"
        "设计含跨场重组算子的自适应大邻域搜索，并在固定排班内进行碳感知充电重调度。"
        "通过区域配送网络、连续电网日和动态事件流检验模型与算法。"
        "结果表明，充电择时是路径与车型减排的补充，协同价值受客户空间组织和参与条件共同约束；滚动重规划还需同时满足状态可继承性和计算时限。"
    )
    en = (
        "Under carbon-peaking, carbon-neutrality, and delivery-consolidation requirements, a multi-depot mixed fleet must coordinate routes across depots, "
        "schedule electric-vehicle charging according to time-varying grid carbon intensity, and maintain depot participation, while dynamic orders further complicate execution. "
        "A two-layer routing model is established to link feasible delivery trips with physical-vehicle schedules. The model minimizes operating and carbon-settlement costs "
        "and represents multi-trip connections, continuous charging, participation constraints, and rolling state inheritance. An adaptive large neighborhood search with "
        "cross-depot operators is designed, followed by carbon-aware charging rescheduling within each fixed vehicle schedule. Regional delivery networks, consecutive grid days, "
        "and dynamic event streams are used to examine the model and algorithm. The results show that charging timing complements route- and fleet-based "
        "abatement, collaborative value is jointly constrained by customer organization and participation conditions, and rolling replanning must satisfy both state inheritance "
        "and computational time limits."
    )
    visible_zh_length = len(zh.replace("\\%", "%").strip())
    if not 200 <= visible_zh_length <= 300:
        raise RuntimeError(
            f"final Chinese abstract length {visible_zh_length} is outside the 200--300 character target"
        )
    return zh + "\n", en + "\n"


def load_e7_evidence(
    audit_root: Path | None = None,
    replay_root: Path | None = None,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    dict[str, Any],
]:
    """Load sealed sources and independently rebuild every reproducible summary."""

    audit_root = E7_AUDIT if audit_root is None else audit_root
    replay_root = E7_REPLAY if replay_root is None else replay_root
    for root, required in (
        (audit_root, E7_AUDIT_SOURCE_FILES),
        (replay_root, E7_REPLAY_SOURCE_FILES),
    ):
        missing = [name for name in required if not (root / name).is_file()]
        if missing:
            raise E7PaperEvidenceError(f"E7 source files are missing at {root}: {missing}")
        verify_e7_source_manifest(root)

    independent = json.loads((audit_root / "decision.json").read_text(encoding="utf-8"))
    replay_decision = json.loads(
        (replay_root / "decision.json").read_text(encoding="utf-8")
    )
    if (
        independent.get("verdict")
        != "PASS_E7_MULTINETWORK_FORMAL_AND_REPLAY_INDEPENDENT_AUDIT"
    ):
        raise E7PaperEvidenceError("E7 independent audit is not complete")
    if replay_decision.get("status") != "PASS_E7_28DAY_ZERO_SEARCH_CHARGING_REPLAY":
        raise E7PaperEvidenceError("E7 28-day replay is not complete")
    if int(replay_decision.get("paired_day_row_count", -1)) != 840 or int(
        replay_decision.get("route_search_evaluations", -1)
    ) != 0:
        raise E7PaperEvidenceError("E7 replay count or zero-search contract differs")

    pair_rows = pd.read_csv(audit_root / "raw_runs.csv")
    task_status = pd.read_csv(audit_root / "task_status.csv")
    paired_summary = pd.read_csv(audit_root / "paired_summary.csv")
    replay_raw = pd.read_csv(replay_root / "raw_runs.csv")
    replay_summary = summarize_e7_replay(replay_raw)
    validate_e7_replay_summary(
        pd.read_csv(replay_root / "summary.csv"), replay_summary, "E7 replay summary"
    )
    validate_e7_replay_summary(
        pd.read_csv(audit_root / "replay_summary.csv"),
        replay_summary,
        "E7 independent-audit replay summary",
    )
    validate_e7_pair_evidence(pair_rows, task_status, paired_summary)
    return pair_rows, task_status, _ordered_cells(paired_summary), replay_summary, independent


def render_e7_bundle(
    pair_rows: pd.DataFrame,
    task_status: pd.DataFrame,
    paired_summary: pd.DataFrame,
    replay_summary: pd.DataFrame,
    decision: dict[str, object],
) -> dict[str, str]:
    """Purely render the seven reader-facing E7 exhibits."""

    validate_e7_pair_evidence(pair_rows, task_status, paired_summary)
    abstract_zh, abstract_en = render_e7_abstracts(
        pair_rows, paired_summary, replay_summary, decision
    )
    exhibits = {
        E7_POLICY_TABLE_NAME: render_e7_policy_comparison(paired_summary),
        E7_DIAGNOSTICS_TABLE_NAME: render_e7_mechanism_diagnostics(paired_summary),
        E7_REPLAY_TABLE_NAME: render_e7_charging_replay(replay_summary),
        E7_INTERPRETATION_NAME: render_e7_interpretation(
            pair_rows, task_status, paired_summary, replay_summary, decision
        ),
        E7_CONCLUSION_NAME: render_e7_conclusion(
            pair_rows, paired_summary, replay_summary, decision
        ),
        E7_ABSTRACT_ZH_NAME: abstract_zh,
        E7_ABSTRACT_EN_NAME: abstract_en,
    }
    if tuple(exhibits) != E7_EXHIBIT_NAMES:
        raise E7PaperEvidenceError("E7 exhibit inventory differs from the seven-file contract")
    return exhibits


def e7_source_hashes(audit_root: Path, replay_root: Path) -> dict[str, str]:
    return {
        **{
            f"independent_audit/{name}": sha256(audit_root / name)
            for name in E7_AUDIT_SOURCE_FILES
        },
        **{
            f"28day_replay/{name}": sha256(replay_root / name)
            for name in E7_REPLAY_SOURCE_FILES
        },
    }


def source_root_label(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def publish_e7_bundle(
    output: Path,
    exhibits: dict[str, str],
    provenance: dict[str, Any],
) -> None:
    """Publish seven files as one version; the readiness manifest is last."""

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".e7-paper-stage-", dir=output.parent) as directory:
        stage = Path(directory)
        for name in E7_EXHIBIT_NAMES:
            atomic_text(stage / name, exhibits[name])
        atomic_text(
            stage / E7_PROVENANCE_NAME,
            json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        output.mkdir(parents=True, exist_ok=True)
        # Removing the manifest first makes any interrupted replacement unreadable
        # to the manuscript; publishing the new manifest last closes the version.
        (output / E7_PROVENANCE_NAME).unlink(missing_ok=True)
        for name in E7_EXHIBIT_NAMES:
            os.replace(stage / name, output / name)
        os.replace(stage / E7_PROVENANCE_NAME, output / E7_PROVENANCE_NAME)


def build_e2b() -> None:
    decision = json.loads((E2B / "decision.json").read_text(encoding="utf-8"))
    if decision.get("verdict") != "E2B_FORMAL_EVIDENCE_READY":
        raise RuntimeError("E2b formal evidence is not ready")
    summary = decision["arm_summary"]
    labels = {
        "A_continuous": "连续搜索",
        "B_staged": "分阶段搜索",
        "C_staged_cross": "分阶段+专用跨场算子",
    }
    lines = [
        r"\begin{tabular*}{0.84\linewidth}{@{\extracolsep{\fill}}lrrr@{}}",
        r"\toprule",
        r"方案 & 平均总成本 & 相对前档变化 & 可行单元 \\",
        r"\midrule",
    ]
    previous_cost: float | None = None
    for arm in ("A_continuous", "B_staged", "C_staged_cross"):
        row = summary[arm]
        cost = float(row["mean_total_cost"])
        delta = "---" if previous_cost is None else f"{100.0 * (cost - previous_cost) / previous_cost:+.2f}\\%"
        lines.append(
            f"{labels[arm]} & {cost:.1f} & {delta} & "
            f"{int(row['valid_count'])}/{int(row['row_count'])} " + r"\\"
        )
        previous_cost = cost
    lines += [r"\bottomrule", r"\end{tabular*}"]
    write_table("e2b_component_ablation.tex", lines)


def build_e3() -> None:
    data = pd.read_csv(E3 / "trend_summary.csv")
    if len(data) != 9:
        raise RuntimeError("E3 trend table must contain nine networks")
    rows = [
        (
            "地理聚集",
            data["geographic_mismatch_index"].mean(),
            data["geographic_raw_saving_pct"].mean(),
        ),
        (
            "中等责任偏离",
            data["medium_mismatch_index"].mean(),
            data["medium_raw_saving_pct"].mean(),
        ),
        (
            "空间交错",
            data["mixed_mismatch_index"].mean(),
            data["mixed_raw_saving_pct"].mean(),
        ),
    ]
    lines = [
        r"\begin{tabular*}{0.76\linewidth}{@{\extracolsep{\fill}}lrr@{}}",
        r"\toprule",
        r"客户责任结构 & 平均责任偏离指数 & 平均协同节省/\% \\",
        r"\midrule",
    ]
    lines.extend(f"{label} & {mismatch:.3f} & {saving:.2f} " + r"\\" for label, mismatch, saving in rows)
    lines += [r"\bottomrule", r"\end{tabular*}"]
    write_table("e3_responsibility_gradient.tex", lines)


def build_e6() -> None:
    decision = json.loads((E6 / "decision.json").read_text(encoding="utf-8"))
    if decision.get("status") != "PASS_E6_PROFIT_GUARANTEE_FRONTIER":
        raise RuntimeError("E6 frontier evidence is not complete")
    data = pd.read_csv(E6 / "selected_frontier.csv")
    network = (
        data.groupby(["instance", "condition", "alpha"], as_index=False)
        .agg(
            cost_increment_pct=("cost_increment_pct", "mean"),
            minimum_profit_ratio=("selected_minimum_profit_ratio", "mean"),
        )
    )
    summary = (
        network.groupby(["condition", "alpha"], as_index=False)
        .agg(
            cost_increment_pct=("cost_increment_pct", "mean"),
            minimum_profit_ratio=("minimum_profit_ratio", "mean"),
        )
    )
    labels = {"geographic": "地理聚集", "mixed": "空间交错"}
    lines = [
        r"\begin{tabular*}{0.86\linewidth}{@{\extracolsep{\fill}}lrrr@{}}",
        r"\toprule",
        r"客户责任结构 & 保障推进比例 & 系统成本增幅/\% & 最低收益比 \\",
        r"\midrule",
    ]
    for condition in ("geographic", "mixed"):
        block = summary[summary["condition"] == condition]
        for row in block.itertuples(index=False):
            lines.append(
                f"{labels[condition]} & {float(row.alpha):.2f} & "
                f"{float(row.cost_increment_pct):.2f} & "
                f"{float(row.minimum_profit_ratio):.3f} " + r"\\"
            )
    lines += [r"\bottomrule", r"\end{tabular*}"]
    write_table("e6_profit_guarantee_frontier.tex", lines)

    FIGURES.mkdir(parents=True, exist_ok=True)
    # Matplotlib otherwise selects the Black face from Apple's Songti TTC.
    # Extract and register the regular face so this figure matches every other
    # SETP figure in font family and weight.
    songti_ttc = Path("/System/Library/Fonts/Supplemental/Songti.ttc")
    songti_regular = Path(tempfile.gettempdir()) / "resetp-songti-sc-regular.ttf"
    if songti_ttc.exists() and not songti_regular.exists():
        TTCollection(songti_ttc).fonts[6].save(songti_regular)
    if songti_regular.exists():
        font_manager.fontManager.addfont(songti_regular)
    plt.rcParams.update(
        {
            "font.family": ["Times New Roman", "Songti SC"],
            "font.size": 7,
            "axes.unicode_minus": False,
            "pdf.fonttype": 42,
        }
    )
    fig, ax = plt.subplots(figsize=(3.65, 2.25))
    styles = {
        "geographic": dict(color="#1F77B4", marker="o", linestyle="-"),
        "mixed": dict(color="#D55E00", marker="s", linestyle="--"),
    }
    for condition in ("geographic", "mixed"):
        block = summary[summary["condition"] == condition]
        ax.plot(
            block["minimum_profit_ratio"],
            block["cost_increment_pct"],
            linewidth=0.8,
            markersize=3.2,
            label=labels[condition],
            **styles[condition],
        )
    ax.axvline(1.0, color="#555555", linestyle=":", linewidth=0.7)
    ax.set_xlabel("最低车场收益比")
    ax.set_ylabel("系统成本增幅/%")
    ax.set_xticks([0.98, 1.00, 1.02, 1.04, 1.06, 1.08])
    ax.annotate(
        "双方均不劣",
        xy=(1.008, 1.35),
        xytext=(0.986, 1.35),
        arrowprops=dict(arrowstyle="->", color="#555555", linewidth=0.6),
        fontsize=6.5,
        ha="left",
        va="center",
        color="#333333",
    )
    ax.legend(frameon=False)
    ax.tick_params(direction="out", length=2, width=0.5)
    for spine in ax.spines.values():
        spine.set_linewidth(0.5)
    fig.tight_layout()
    fig.savefig(FIGURES / "e6_profit_guarantee_frontier.pdf", bbox_inches="tight")
    fig.savefig(FIGURES / "e6_profit_guarantee_frontier.png", dpi=450, bbox_inches="tight")
    plt.close(fig)


def build_e7() -> dict[str, Any]:
    pair_rows, task_status, paired, replay, decision = load_e7_evidence()
    exhibits = render_e7_bundle(pair_rows, task_status, paired, replay, decision)
    provenance = {
        "schema_version": "resetp.e7.paper-evidence.v1",
        "source_roots": {
            "independent_audit": source_root_label(E7_AUDIT),
            "28day_replay": source_root_label(E7_REPLAY),
        },
        "source_hashes": e7_source_hashes(E7_AUDIT, E7_REPLAY),
        "generated_hashes": {
            name: text_sha256(text) for name, text in exhibits.items()
        },
        "builder_sha256": sha256(Path(__file__).resolve()),
        "coverage": {
            "formal_tasks": 120,
            "stream_pairs": 30,
            "network_condition_cells": 6,
            "replay_pairs": 840,
            "reader_facing_exhibits": 7,
        },
        "reconstruction_boundary": (
            "policy and 28-day values are recomputed from sealed raw rows; "
            "mechanism diagnostics are recomputed except cross-site stream counts, "
            "which remain manifest-bound derived fields because the independent-audit "
            "raw schema does not expose per-stream cross-site counts"
        ),
    }
    publish_e7_bundle(TABLES, exhibits, provenance)
    return provenance


def main() -> int:
    build_e2b()
    build_e3()
    build_e6()
    if (E7_AUDIT / "decision.json").is_file() and (
        E7_REPLAY / "decision.json"
    ).is_file():
        build_e7()
        print("built E2b/E3/E6/E7 manuscript exhibits")
    else:
        print("built E2b/E3/E6 manuscript exhibits; E7 evidence not sealed yet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
