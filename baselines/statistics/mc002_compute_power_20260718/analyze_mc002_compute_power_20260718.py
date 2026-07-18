#!/usr/bin/env python3
"""Build the result-blind MC-002 compute and power analysis package.

This script does not run any solver.  It reads frozen historical evidence only,
counts the China-81 draft structure, estimates runtime anchors, and calculates
variance-only power diagnostics for the still-unapproved MC-002 choices.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median, variance

from scipy.optimize import brentq
from scipy.stats import nct, t


REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = Path(__file__).resolve().parent
CHINA81_DIR = REPO_ROOT / "data/ChinaInstances/CHINA81_DRAFT_20260717_source_bound"
CONTRACT_PATH = (
    REPO_ROOT / "data/ChinaInstances/china_e3_e7_significance_contract_v2_20260718.json"
)
E3_HIGH_PATH = (
    REPO_ROOT / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713/raw_runs.csv"
)
E3_MEDIUM_PATH = (
    REPO_ROOT / "baselines/e3_ablation/e3_medium_paired_cost_formal_20260715/raw_runs.csv"
)
E4_PATH = (
    REPO_ROOT / "baselines/e4_e5/e4_forecast_timing_formal_20260713/raw_runs.csv"
)
E6_PATH = (
    REPO_ROOT / "baselines/e6_fairness/e6_participation_formal_20260714/raw_runs.csv"
)
E6_FRONTIER_PATH = (
    REPO_ROOT
    / "baselines/e6_fairness/e6_profit_guarantee_frontier_20260715/raw_runs.csv"
)
E7_PATH = (
    REPO_ROOT / "baselines/e7_dynamic/e7_multinetwork_formal_20260715/raw_runs.csv"
)

PRIMARY_UNITS = 27
MAPS_PER_UNIT = 3
DEFAULT_SEEDS = 5
STATIC_BUDGET = 4_000
ALGORITHM_GATE_BUDGET = 1_600
HOLM_FAMILIES = 5
FAMILYWISE_ALPHA = 0.05


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def exact_standardized_mde(
    *,
    n_units: int,
    alpha: float,
    target_power: float,
) -> float:
    degrees_freedom = n_units - 1
    critical = t.ppf(1 - alpha, degrees_freedom)

    def power_gap(effect: float) -> float:
        power = 1 - nct.cdf(
            critical,
            degrees_freedom,
            effect * math.sqrt(n_units),
        )
        return power - target_power

    return float(brentq(power_gap, 0.0, 5.0))


def paired_percent_rows(
    path: Path,
    *,
    baseline_arm: str,
    candidate_arm: str,
) -> dict[tuple[str, str], list[float]]:
    paired: dict[tuple[str, str, str], dict[str, float]] = defaultdict(dict)
    for row in read_csv(path):
        key = (row["instance"], row["condition"], row["seed"])
        paired[key][row["arm"]] = float(row["total_cost"])

    by_cell: dict[tuple[str, str], list[float]] = defaultdict(list)
    for (instance, condition, _seed), arms in paired.items():
        if baseline_arm not in arms or candidate_arm not in arms:
            continue
        baseline = arms[baseline_arm]
        candidate = arms[candidate_arm]
        by_cell[(instance, condition)].append(100 * (baseline - candidate) / baseline)
    return by_cell


def e4_paired_percent_rows() -> dict[tuple[str, str], list[float]]:
    daily: dict[tuple[str, str, str, str, str], dict[str, float]] = defaultdict(dict)
    for row in read_csv(E4_PATH):
        key = (
            row["instance"],
            row["condition"],
            row["arm"],
            row["seed"],
            row["operating_day"],
        )
        daily[key][row["timing_rule"]] = float(row["actual_charging_emissions_kg"])

    by_seed: dict[tuple[str, str, str, str], list[float]] = defaultdict(list)
    for (instance, condition, arm, seed, _day), rules in daily.items():
        if "immediate" not in rules or "forecast_timed" not in rules:
            continue
        immediate = rules["immediate"]
        if immediate <= 0:
            continue
        by_seed[(instance, condition, arm, seed)].append(
            100 * (immediate - rules["forecast_timed"]) / immediate
        )

    by_cell: dict[tuple[str, str], list[float]] = defaultdict(list)
    for (instance, condition, arm, _seed), values in by_seed.items():
        by_cell[(instance, f"{condition}::{arm}")].append(mean(values))
    return by_cell


def variance_components(
    by_cell: dict[tuple[str, str], list[float]],
) -> tuple[float, float, int, int]:
    within_df = sum(len(values) - 1 for values in by_cell.values())
    within_ss = sum(
        sum((value - mean(values)) ** 2 for value in values)
        for values in by_cell.values()
    )
    within_variance = within_ss / within_df
    cell_means = [mean(values) for values in by_cell.values()]
    average_seed_count = mean([len(values) for values in by_cell.values()])
    between_variance = max(
        0.0,
        variance(cell_means) - within_variance / average_seed_count,
    )
    return within_variance, between_variance, len(by_cell), sum(
        len(values) for values in by_cell.values()
    )


def runtime_by_size(path: Path) -> dict[int, dict[str, float]]:
    grouped: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for row in read_csv(path):
        match = re.search(r"-(\d+)c-", row.get("instance", ""))
        if not match:
            continue
        evaluations = float(row.get("evaluations", "0") or 0)
        if evaluations <= 0:
            continue
        grouped[int(match.group(1))].append(
            (float(row["elapsed_seconds"]), evaluations)
        )
    result: dict[int, dict[str, float]] = {}
    for size, values in grouped.items():
        elapsed = [item[0] for item in values]
        result[size] = {
            "n": len(values),
            "median_seconds": median(elapsed),
            "mean_seconds": mean(elapsed),
            "max_seconds": max(elapsed),
            "median_seconds_per_evaluation": median(
                item[0] / item[1] for item in values
            ),
        }
    return result


def e7_runtime_by_size() -> dict[int, dict[str, float]]:
    network_size = {"N114": 50, "N221": 100, "N322": 150}
    tasks: dict[tuple[str, str, str, str], float] = defaultdict(float)
    for row in read_csv(E7_PATH):
        key = (
            row["network"],
            row["responsibility_condition"],
            row["stream_seed"],
            row["arm"],
        )
        tasks[key] += float(row["elapsed_seconds"])
    grouped: dict[int, list[float]] = defaultdict(list)
    for key, elapsed in tasks.items():
        grouped[network_size[key[0]]].append(elapsed)
    return {
        size: {
            "n": len(values),
            "median_seconds": median(values),
            "mean_seconds": mean(values),
            "max_seconds": max(values),
        }
        for size, values in grouped.items()
    }


def count_china81() -> tuple[int, Counter[int], Counter[str]]:
    instances = sorted(CHINA81_DIR.glob("*/instance.json"))
    sizes: Counter[int] = Counter()
    regions: Counter[str] = Counter()
    pattern = re.compile(r"cn-(jjj|prd|cy)-(\d+)c-")
    for path in instances:
        match = pattern.search(path.parent.name)
        if not match:
            raise RuntimeError(f"unparseable China-81 instance name: {path.parent.name}")
        regions[match.group(1)] += 1
        sizes[int(match.group(2))] += 1
    return len(instances), sizes, regions


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if contract["formal_search_allowed"] is not False:
        raise RuntimeError("MC-002 analysis requires formal_search_allowed=false")

    instance_count, size_counts, region_counts = count_china81()
    if instance_count != 81:
        raise RuntimeError(f"expected 81 China draft instances, found {instance_count}")
    if set(size_counts.values()) != {9} or set(region_counts.values()) != {27}:
        raise RuntimeError(
            f"unexpected China-81 structure: sizes={size_counts}, regions={region_counts}"
        )

    matrix_specs = [
        ("E3", 2, "search", "status_quo_vs_optimized_responsibility"),
        ("E4", 2, "fixed_route_replay", "immediate_vs_carbon_aware_charging"),
        ("E5", 2, "search", "linear_replay_vs_integrated_nonlinear"),
        ("E6", 3, "search", "independent_unrestricted_fair"),
        ("E7", 5, "dynamic_search", "five_arms_including_carbon_blind"),
    ]
    matrix_rows: list[dict[str, object]] = []
    for experiment, arms, mode, contrast in matrix_specs:
        runs = instance_count * DEFAULT_SEEDS * arms
        matrix_rows.append(
            {
                "experiment": experiment,
                "primary_units": PRIMARY_UNITS,
                "maps_per_unit": MAPS_PER_UNIT,
                "instances": instance_count,
                "seeds_per_map": DEFAULT_SEEDS,
                "arms": arms,
                "task_or_replay_mode": mode,
                "arm_runs": runs,
                "complete_evaluations_at_B4000": (
                    runs * STATIC_BUDGET if mode == "search" else ""
                ),
                "fixed_route_day_replays": (
                    runs * 28 if experiment == "E4" else ""
                ),
                "contrast": contrast,
                "approval_status": "PROPOSAL_NOT_FROZEN",
            }
        )
    matrix_rows.append(
        {
            "experiment": "ALGORITHM_6_ARM_GATE",
            "primary_units": 9,
            "maps_per_unit": 1,
            "instances": 9,
            "seeds_per_map": DEFAULT_SEEDS,
            "arms": 6,
            "task_or_replay_mode": "search",
            "arm_runs": 9 * DEFAULT_SEEDS * 6,
            "complete_evaluations_at_B4000": 9 * DEFAULT_SEEDS * 6 * STATIC_BUDGET,
            "fixed_route_day_replays": "",
            "contrast": "three_regions_x_three_representative_sizes",
            "approval_status": "PROPOSAL_NOT_FROZEN",
        }
    )
    write_csv(
        OUT_DIR / "compute_matrix.csv",
        matrix_rows,
        list(matrix_rows[0]),
    )

    e3_high = paired_percent_rows(
        E3_HIGH_PATH,
        baseline_arm="ownership_fixed",
        candidate_arm="reassignment_allowed",
    )
    e3_medium = paired_percent_rows(
        E3_MEDIUM_PATH,
        baseline_arm="ownership_fixed",
        candidate_arm="reassignment_allowed",
    )
    e6 = paired_percent_rows(
        E6_PATH,
        baseline_arm="independent",
        candidate_arm="no_loss",
    )
    variance_sources = {
        "E3_HIGH_UK_PROXY": (e3_high, 5.0),
        "E3_MEDIUM_UK_PROXY": (e3_medium, 5.0),
        "E4_UK_PROXY": (e4_paired_percent_rows(), 3.0),
        "E6_UK_PROXY": (e6, 2.0),
    }
    conservative_alpha = FAMILYWISE_ALPHA / HOLM_FAMILIES
    conservative_mde_d = exact_standardized_mde(
        n_units=PRIMARY_UNITS,
        alpha=conservative_alpha,
        target_power=0.80,
    )
    power_rows: list[dict[str, object]] = []
    variance_summary: dict[str, dict[str, float | int]] = {}
    for label, (cells, proposed_threshold) in variance_sources.items():
        within_var, between_var, historical_cells, historical_seed_rows = (
            variance_components(cells)
        )
        variance_summary[label] = {
            "within_seed_variance": within_var,
            "between_cell_variance": between_var,
            "historical_cells": historical_cells,
            "historical_seed_rows": historical_seed_rows,
        }
        for seeds in range(1, 11):
            predictive_sd = math.sqrt(between_var + within_var / seeds)
            standardized_threshold = proposed_threshold / predictive_sd
            conservative_mde_percent = conservative_mde_d * predictive_sd
            power_rows.append(
                {
                    "variance_proxy": label,
                    "seeds_per_map": seeds,
                    "historical_cells": historical_cells,
                    "historical_seed_rows": historical_seed_rows,
                    "within_seed_variance": f"{within_var:.12f}",
                    "between_cell_variance": f"{between_var:.12f}",
                    "predictive_unit_sd_percent": f"{predictive_sd:.12f}",
                    "proposed_material_threshold_percent": proposed_threshold,
                    "standardized_threshold_d": f"{standardized_threshold:.12f}",
                    "conservative_holm_alpha": conservative_alpha,
                    "target_power": 0.80,
                    "conservative_mde_d": f"{conservative_mde_d:.12f}",
                    "conservative_mde_percent": f"{conservative_mde_percent:.12f}",
                    "threshold_reaches_conservative_80pct_power_proxy": (
                        standardized_threshold >= conservative_mde_d
                    ),
                    "boundary": (
                        "variance-only UK historical proxy; not China effect forecast"
                    ),
                }
            )
    write_csv(OUT_DIR / "power_analysis.csv", power_rows, list(power_rows[0]))

    runtime_sources: list[dict[str, object]] = []
    for label, path in [
        ("E3_HIGH_4000", E3_HIGH_PATH),
        ("E3_MEDIUM_4000", E3_MEDIUM_PATH),
        ("E6_4000", E6_PATH),
        ("E6_FRONTIER_4000", E6_FRONTIER_PATH),
    ]:
        for size, stats in sorted(runtime_by_size(path).items()):
            runtime_sources.append(
                {
                    "source": label,
                    "client_size": size,
                    **{key: f"{value:.12f}" for key, value in stats.items()},
                    "boundary": "M1 historical static-search runtime anchor",
                }
            )
    e7_runtime = e7_runtime_by_size()
    for size, stats in sorted(e7_runtime.items()):
        runtime_sources.append(
            {
                "source": "E7_OLD_4_ARM_DYNAMIC",
                "client_size": size,
                **{key: f"{value:.12f}" for key, value in stats.items()},
                "median_seconds_per_evaluation": "",
                "boundary": (
                    "old UK dynamic task runtime; China task is not yet measurable"
                ),
            }
        )
    write_csv(
        OUT_DIR / "runtime_sources.csv",
        runtime_sources,
        [
            "source",
            "client_size",
            "n",
            "median_seconds",
            "mean_seconds",
            "max_seconds",
            "median_seconds_per_evaluation",
            "boundary",
        ],
    )

    conservative_static_medians = runtime_by_size(E6_FRONTIER_PATH)
    static_runs_per_size = 3 * 3 * DEFAULT_SEEDS * (2 + 2 + 3)
    static_cpu_seconds = sum(
        conservative_static_medians[size]["median_seconds"] * static_runs_per_size
        for size in sorted(size_counts)
    )

    # Use only observed 50/100/150-c dynamic task means.  For <=50, clamp to
    # the 50-c anchor; for 75 use the geometric midpoint; for 200 use the
    # 150-c mean as an explicit lower-bound proxy, not an ETA.
    e7_anchor_seconds = {
        10: e7_runtime[50]["mean_seconds"],
        15: e7_runtime[50]["mean_seconds"],
        20: e7_runtime[50]["mean_seconds"],
        25: e7_runtime[50]["mean_seconds"],
        50: e7_runtime[50]["mean_seconds"],
        75: math.sqrt(
            e7_runtime[50]["mean_seconds"] * e7_runtime[100]["mean_seconds"]
        ),
        100: e7_runtime[100]["mean_seconds"],
        150: e7_runtime[150]["mean_seconds"],
        200: e7_runtime[150]["mean_seconds"],
    }
    dynamic_tasks_per_size = 3 * 3 * DEFAULT_SEEDS * 5
    dynamic_anchor_cpu_seconds = sum(
        e7_anchor_seconds[size] * dynamic_tasks_per_size for size in sorted(size_counts)
    )
    fifth_arm_anchor_cpu_seconds = dynamic_anchor_cpu_seconds / 5

    raw_rows = [
        {
            "record_type": "STRUCTURE",
            "metric": "china81_instance_count",
            "value": instance_count,
            "unit": "instances",
            "assumption_or_boundary": "counted from draft structure only; not formal-ready",
        },
        {
            "record_type": "COMPUTE",
            "metric": "static_E3_E5_E6_arm_runs_k5",
            "value": 2_835,
            "unit": "arm_runs",
            "assumption_or_boundary": "2+2+3 arms across 81 maps and 5 seeds",
        },
        {
            "record_type": "COMPUTE",
            "metric": "static_E3_E5_E6_complete_evaluations_B4000",
            "value": 11_340_000,
            "unit": "complete_evaluations",
            "assumption_or_boundary": "illustrative budget; China budget not frozen",
        },
        {
            "record_type": "COMPUTE",
            "metric": "static_E3_E5_E6_cpu_hours_anchor",
            "value": f"{static_cpu_seconds / 3600:.6f}",
            "unit": "cpu_hours",
            "assumption_or_boundary": (
                "E6 frontier median at 4000 evaluations; excludes nonlinear slowdown"
            ),
        },
        {
            "record_type": "COMPUTE",
            "metric": "E4_fixed_route_replays_k5",
            "value": 81 * 5 * 2 * 28,
            "unit": "day_replays",
            "assumption_or_boundary": "zero route search; charging scheduler cost not timed",
        },
        {
            "record_type": "COMPUTE",
            "metric": "E7_five_arm_tasks_k5",
            "value": 81 * 5 * 5,
            "unit": "dynamic_tasks",
            "assumption_or_boundary": "one frozen event stream per common seed",
        },
        {
            "record_type": "COMPUTE",
            "metric": "E7_fifth_arm_increment_k5",
            "value": 81 * 5,
            "unit": "dynamic_tasks",
            "assumption_or_boundary": "correct China-81 increment; old +30 claim is invalid",
        },
        {
            "record_type": "COMPUTE",
            "metric": "E7_five_arm_cpu_hours_anchor_not_eta",
            "value": f"{dynamic_anchor_cpu_seconds / 3600:.6f}",
            "unit": "cpu_hours",
            "assumption_or_boundary": (
                "old UK 50/100/150 means; 200 uses 150 mean lower-bound proxy"
            ),
        },
        {
            "record_type": "COMPUTE",
            "metric": "E7_fifth_arm_cpu_hours_anchor_not_eta",
            "value": f"{fifth_arm_anchor_cpu_seconds / 3600:.6f}",
            "unit": "cpu_hours",
            "assumption_or_boundary": (
                "one fifth of five-arm anchor; China nonlinear runtime unknown"
            ),
        },
        {
            "record_type": "COMPUTE",
            "metric": "algorithm_six_arm_gate_runs_k5",
            "value": 3 * 3 * 5 * 6,
            "unit": "arm_runs",
            "assumption_or_boundary": "representative sizes not yet frozen",
        },
        {
            "record_type": "COMPUTE",
            "metric": "algorithm_six_arm_gate_evaluations_B1600",
            "value": 3 * 3 * 5 * 6 * ALGORITHM_GATE_BUDGET,
            "unit": "complete_evaluations",
            "assumption_or_boundary": "recommended low-cost mechanism gate proposal",
        },
        {
            "record_type": "POWER",
            "metric": "standardized_MDE_n27_alpha0.01_power0.80",
            "value": f"{conservative_mde_d:.12f}",
            "unit": "paired_SD",
            "assumption_or_boundary": "one-sided paired t proxy; Holm worst first threshold",
        },
        {
            "record_type": "POWER",
            "metric": "standardized_MDE_n27_alpha0.01_power0.90",
            "value": f"{exact_standardized_mde(n_units=27, alpha=0.01, target_power=0.90):.12f}",
            "unit": "paired_SD",
            "assumption_or_boundary": "one-sided paired t proxy; Holm worst first threshold",
        },
    ]
    write_csv(
        OUT_DIR / "raw_runs.csv",
        raw_rows,
        [
            "record_type",
            "metric",
            "value",
            "unit",
            "assumption_or_boundary",
        ],
    )

    now = datetime.now(UTC).isoformat()
    input_paths = [
        CONTRACT_PATH,
        CHINA81_DIR / "build_manifest.json",
        E3_HIGH_PATH,
        E3_MEDIUM_PATH,
        E4_PATH,
        E6_PATH,
        E6_FRONTIER_PATH,
        E7_PATH,
    ]
    metadata = {
        "schema": "resetp.mc002.compute-power-analysis.v1",
        "created_at_utc": now,
        "status": "DRAFT_MC002_COMPUTE_POWER_ANALYSIS_READY_FOR_USER_APPROVAL",
        "formal_search_allowed": False,
        "solver_search_evaluations_run_by_analysis": 0,
        "china81_structure": {
            "instances": instance_count,
            "sizes": dict(sorted(size_counts.items())),
            "regions": dict(sorted(region_counts.items())),
        },
        "approved_principles_preserved": contract["partial_approval"][
            "approved_principles"
        ],
        "deferred_items_remain_unfrozen": contract["partial_approval"][
            "deferred_until_compute_table_and_power_analysis"
        ],
        "power_model": {
            "independent_primary_units": PRIMARY_UNITS,
            "familywise_alpha": FAMILYWISE_ALPHA,
            "holm_families": HOLM_FAMILIES,
            "conservative_first_threshold_alpha": conservative_alpha,
            "test_proxy": "one-sided paired t noncentral-t power",
            "target_power": [0.80, 0.90],
            "variance_rule": (
                "historical variance only; historical mean direction is not used"
            ),
        },
        "input_sha256": {
            str(path.relative_to(REPO_ROOT)): sha256(path) for path in input_paths
        },
    }
    write_json(OUT_DIR / "metadata.json", metadata)

    decision = {
        "schema": "resetp.mc002.compute-power-decision.v1",
        "status": "DRAFT_MC002_COMPUTE_POWER_ANALYSIS_READY_FOR_USER_APPROVAL",
        "formal_search_allowed": False,
        "whole_mc002_contract_frozen": False,
        "findings": {
            "china81_count_verified": True,
            "primary_inferential_n": 27,
            "seeds_do_not_increase_primary_n": True,
            "minimum_common_seeds_recommendation": 5,
            "variance_blind_escalation_cap_recommendation": 7,
            "single_seed_count_guarantees_all_five_families_power": False,
            "e7_fifth_arm_increment_tasks_at_k5": 405,
            "old_plus_30_claim_valid_for_china81": False,
            "full_e7_eta_claim_allowed": False,
        },
        "result_blind_freeze_recommendation": {
            "within_cell_estimator": (
                "mean over three mutually exclusive maps; within each map mean over "
                "common seeds; each of 27 cells contributes one value"
            ),
            "initial_common_seeds_per_map": 5,
            "top_up_rule": (
                "compute only within-map paired residual variance and runtime/failure "
                "rates; if the predeclared conservative MDE target is not met and "
                "within-seed variance remains material, add all maps uniformly to 7"
            ),
            "stop_rule": (
                "at 7 seeds, do not add more seeds to chase p-values; HALT and revisit "
                "independent-unit count, endpoint variance, or material threshold"
            ),
            "e7_rule": (
                "do not launch 2025 tasks directly; first run a result-hidden runtime "
                "pilot on one predeclared small/medium/large cell and all five arms"
            ),
            "algorithm_gate_rule": (
                "if approved, use 3 regions x 3 predeclared representative sizes x "
                "5 common seeds x 6 arms at B1600 before any full mechanism matrix"
            ),
        },
        "remaining_user_approvals": [
            "within-cell three-map mean estimator",
            "five initial common seeds and variance-only top-up cap of seven",
            "E7 carbon-blind fifth arm after the runtime pilot",
            "six-arm algorithm mechanism gate at B1600",
            "numeric material-effect thresholds",
            "primary paired test statistic in addition to Holm correction",
        ],
    }
    write_json(OUT_DIR / "decision.json", decision)

    report = f"""# MC-002 算力表与功效分析

## 结论

本包只做结果盲的算力与方差分析，未启动求解搜索。中国任务结构核为
`27个地区×规模单元 × 3个互斥地图 = 81个实例`。五种子时，E3、E5、
E6按2/2/3臂计共有2,835个搜索臂；若每臂仍用旧正式口径4,000次完整
评价，就是11,340,000次完整评价。E4是固定路线复算，2臂×28日产生
22,680个日重放，不应混入ALNS搜索评价账。

E7第五臂不是旧英国矩阵的“多30项”。中国81实例、每图五种子下，
第五臂单独增加`81×5=405`个动态任务；五臂合计2,025个动态任务。
旧E7的50/100/150客户任务耗时随规模急剧上升，200客户没有实测锚，
因此本包拒绝给出单一ETA。把200客户仅按旧150客户均值作明显偏乐观的
下界代理，五臂仍约{dynamic_anchor_cpu_seconds / 3600:.1f} CPU小时，
其中第五臂约{fifth_arm_anchor_cpu_seconds / 3600:.1f} CPU小时；六
worker的理想无损下界分别约{dynamic_anchor_cpu_seconds / 3600 / 6:.1f}
和{fifth_arm_anchor_cpu_seconds / 3600 / 6:.1f}小时。它们不是中国正式
运行预测。

## 功效事实

主要推断样本数是27，不是81，也不是81乘种子数。增加种子只降低同一
地图上随机求解噪声，不增加独立地区×规模单元。按五个检验族中最保守
的Holm首序阈值`0.05/5=0.01`、单侧配对t近似和80%功效，27个独立单元
需要标准化效应至少`d={conservative_mde_d:.3f}`；90%功效需
`d={exact_standardized_mde(n_units=27, alpha=0.01, target_power=0.90):.3f}`。

旧英国配对差只作为方差代理，不用于预测中国方向。该代理显示：E3中
等暴露的5%候选阈值约到6--7种子才接近保守80%门；E3高暴露异质性较大，
即使无限增加种子也无法靠种子把5%阈值送过该门；E6的2%候选阈值同样
无法靠增加种子解决。E4的3%充电侧阈值在旧方差代理下余量很大，但中国
非线性核心尚无方差数据。详细逐种子结果见`power_analysis.csv`。

## 冻结建议

建议把“最低稳定种子”和“主要检验功效”分开。每图先固定5个共同种子；
三图先分别按种子取均值，再在格内取三图均值，最终27格各贡献一个值。
只能读取成对残差方差、运行失败和耗时做结果盲扩样；若预注册精度门未
达到且种子噪声仍占实质比例，则所有地图统一补到7种子。到7仍不足就
HALT，不再用更多种子追p值，而应重新审批独立单元数、主要终点方差或
效应阈值。

E7不能直接支付2,025任务。先在预先锁定的小/中/大各一格、每格一张图、
五种子、五臂上做结果隐藏的耗时/失败/预算活性门；只有运行时可承受且
第五臂确实有独立机制差异，才放大全矩阵。算法六臂门建议先按
`3地区×3代表规模×5种子×6臂×B1600=432,000`次完整评价执行，代表规模
在看结果前锁定。

## 依据和边界

Campelo与Wanner（2020）把多算法比较拆为跨问题实例的成对比较，并明确
区分“需要多少独立实例”和“每实例需要多少重复运行”；这正是本包不把
种子冒充独立样本的依据。Holm（1979）控制五族FWER；保守功效账使用首序
阈值0.01。优化算法基准的可复现、同实例配对和完整报告原则参照
Bartz-Beielstein等（2020）。

- Campelo & Wanner: https://doi.org/10.1007/s10732-020-09454-w
- Holm: https://doi.org/10.2307/4615733
- Bartz-Beielstein et al.: https://arxiv.org/abs/2007.03488

本包不批准任何统计方法，不冻结中国搜索预算，不预测中国非线性运行时，
也不允许正式搜索。E5和E7尚无中国非线性方差，不能给出诚实的唯一最低
种子数；这正是保留结果盲方差门的原因。
"""
    (OUT_DIR / "report.md").write_text(report, encoding="utf-8")

    hash_paths = [
        Path(__file__),
        OUT_DIR / "compute_matrix.csv",
        OUT_DIR / "power_analysis.csv",
        OUT_DIR / "runtime_sources.csv",
        OUT_DIR / "raw_runs.csv",
        OUT_DIR / "metadata.json",
        OUT_DIR / "decision.json",
        OUT_DIR / "report.md",
        *input_paths,
    ]
    artifact_hashes = {
        str(path.relative_to(REPO_ROOT)): sha256(path)
        for path in hash_paths
        if path.name != "artifact_hashes.json"
    }
    write_json(OUT_DIR / "artifact_hashes.json", artifact_hashes)


if __name__ == "__main__":
    main()
