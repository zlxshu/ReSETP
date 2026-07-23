"""Result-blind-safe aggregation for future China E3--E7 raw runs.

The module is intentionally independent of the solver.  It consumes only a
sealed raw-runs CSV and never invents a value for a missing endpoint.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

try:
    from .contract import ROOT, family_by_id, load_contract, primary_cell_id, read_csv
except ImportError:  # pragma: no cover - direct script compatibility
    from contract import ROOT, family_by_id, load_contract, primary_cell_id, read_csv


RAW_FIELDS = (
    "record_type",
    "experiment_id",
    "family",
    "instance_id",
    "region",
    "customer_size",
    "map_index",
    "seed",
    "arm",
    "pair_id",
    "calendar_date",
    "stage_index",
    "event_id",
    "diagnostic_metric",
    "diagnostic_value",
    "status",
    "feasible",
    "total_cost",
    "charging_emissions",
    "total_emissions",
    "infeasibility_count",
    "cross_site_service_count",
    "service_level",
    "member_min_benefit",
    "fairness_ratio",
    "participation_activation",
    "dynamic_completed_customers",
    "participation_violation_count",
    "carbon_aware_charging_share",
    "movable_energy_kwh",
    "git_head",
    "contract_sha256",
    "input_manifest_sha256",
    "algorithm_id",
    "evaluator_id",
    "search_evaluations",
    "runtime_seconds",
    "solution_path",
    "certificate_path",
    "source_hash",
    "status_reason",
)


def mean(values: Iterable[float]) -> float:
    items = list(values)
    if not items:
        raise ValueError("mean requires at least one value")
    return sum(items) / len(items)


def median(values: Iterable[float]) -> float:
    items = sorted(values)
    if not items:
        raise ValueError("median requires at least one value")
    middle = len(items) // 2
    if len(items) % 2:
        return items[middle]
    return (items[middle - 1] + items[middle]) / 2.0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _float(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _bool(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "pass", "feasible"}:
        return 1.0
    if text in {"0", "false", "no", "fail", "infeasible"}:
        return 0.0
    return _float(value)


def _metric_value(row: dict[str, str], metric: str) -> float | None:
    if metric == "feasible":
        return _bool(row.get(metric))
    return _float(row.get(metric))


def _exact_sign_test(values: list[float]) -> float | None:
    nonzero = [value for value in values if abs(value) > 1.0e-12]
    n = len(nonzero)
    if n == 0:
        return 1.0
    positive = sum(value > 0 for value in nonzero)
    lower = sum(math.comb(n, k) for k in range(positive + 1)) / (2**n)
    upper = sum(math.comb(n, k) for k in range(positive, n + 1)) / (2**n)
    return min(1.0, 2.0 * min(lower, upper))


def _randomization_p(values: list[float], seed: int) -> float | None:
    if not values:
        return None
    observed = abs(mean(values))
    n = len(values)
    if n <= 20:
        exceed = 0
        total = 1 << n
        for mask in range(total):
            signed = [value if mask & (1 << index) else -value for index, value in enumerate(values)]
            if abs(mean(signed)) >= observed - 1.0e-15:
                exceed += 1
        return exceed / total
    rng = random.Random(seed)
    samples = 200_000
    exceed = 0
    for _ in range(samples):
        signed = [value if rng.getrandbits(1) else -value for value in values]
        if abs(mean(signed)) >= observed - 1.0e-15:
            exceed += 1
    return (exceed + 1) / (samples + 1)


def _wilcoxon(values: list[float]) -> float | None:
    try:
        from scipy.stats import wilcoxon  # type: ignore
    except ImportError:
        return None
    if not values:
        return None
    try:
        return float(wilcoxon(values, alternative="two-sided", zero_method="wilcox").pvalue)
    except ValueError:
        return 1.0


def _bootstrap_ci(values: list[float], seed: int) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    rng = random.Random(seed)
    samples = []
    for _ in range(10_000):
        samples.append(mean(rng.choice(values) for _ in values))
    samples.sort()
    return samples[250], samples[9_749]


def _holm(p_values: list[float | None]) -> list[float | None]:
    usable = [(index, p) for index, p in enumerate(p_values) if p is not None]
    adjusted: list[float | None] = [None] * len(p_values)
    running = 0.0
    for rank, (index, p_value) in enumerate(sorted(usable, key=lambda item: item[1])):
        value = min(1.0, (len(usable) - rank) * p_value)
        running = max(running, value)
        adjusted[index] = running
    return adjusted


def _cell_map_means(
    rows: list[dict[str, str]],
    *,
    metric: str,
    family_id: str,
    arm_id: str,
) -> tuple[dict[str, float], list[str]]:
    selected = [
        row
        for row in rows
        if row.get("family") == family_id
        and row.get("arm") == arm_id
        and row.get("status") == "complete"
    ]
    by_map: dict[str, dict[str, dict[str, list[float]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    for row in selected:
        value = _metric_value(row, metric)
        if value is None:
            continue
        by_map[primary_cell_id(row)][row["instance_id"]][row["seed"]].append(value)
    means: dict[str, float] = {}
    missing: list[str] = []
    for cell, instances in by_map.items():
        if len(instances) != 3:
            missing.append(f"{family_id}:{arm_id}:{cell}:maps={len(instances)}")
            continue
        seed_sets = [set(seeds) for seeds in instances.values()]
        if len({tuple(sorted(seeds)) for seeds in seed_sets}) != 1:
            missing.append(f"{family_id}:{arm_id}:{cell}:non_common_seeds")
            continue
        if any(
            len(values) != 1
            for seeds in instances.values()
            for values in seeds.values()
        ):
            missing.append(f"{family_id}:{arm_id}:{cell}:duplicate_or_missing_seed_row")
            continue
        map_values = [
            mean(value for values in seeds.values() for value in values)
            for seeds in instances.values()
            if seeds
        ]
        if len(map_values) != 3:
            missing.append(f"{family_id}:{arm_id}:{cell}:empty_map")
            continue
        means[cell] = mean(map_values)
    return means, missing


def _contrast_rows(
    rows: list[dict[str, str]],
    family: dict[str, Any],
    *,
    contrast: dict[str, Any],
    contrast_role: str,
    repo_root: Path,
) -> tuple[list[dict[str, Any]], list[str]]:
    control = contrast["control"]
    treatment = contrast["treatment"]
    direction = contrast.get("direction", family["direction"])
    metrics = [family["primary_metric"], *family.get("secondary_metrics", [])]
    all_summary: list[dict[str, Any]] = []
    missing: list[str] = []
    for metric_index, metric in enumerate(metrics):
        controls, control_missing = _cell_map_means(
            rows, metric=metric, family_id=family["id"], arm_id=control
        )
        treatments, treatment_missing = _cell_map_means(
            rows, metric=metric, family_id=family["id"], arm_id=treatment
        )
        missing.extend(control_missing + treatment_missing)
        cells = sorted(set(controls) & set(treatments))
        if len(cells) != 27:
            missing.append(f"{family['id']}:{metric}:paired_cells={len(cells)}")
        signs = []
        reductions = []
        for cell in cells:
            control_value = controls[cell]
            treatment_value = treatments[cell]
            if direction == "lower_is_better":
                delta = control_value - treatment_value
            else:
                delta = treatment_value - control_value
            signs.append(delta)
            reductions.append(
                100.0 * delta / abs(control_value)
                if abs(control_value) > 1.0e-12
                else float("nan")
            )
        if not signs:
            all_summary.append(
                {
                    "family": family["id"],
                    "contrast_role": contrast_role,
                    "contrast": f"{treatment}_vs_{control}",
                    "metric": metric,
                    "status": "NO_FORMAL_RESULTS",
                    "n_cells": 0,
                }
            )
            continue
        ci_low, ci_high = _bootstrap_ci(signs, 20260723 + metric_index)
        finite_reductions = [value for value in reductions if math.isfinite(value)]
        all_summary.append(
            {
                "family": family["id"],
                "contrast_role": contrast_role,
                "contrast": f"{treatment}_vs_{control}",
                "metric": metric,
                "status": "PASS_DATA_COMPLETE" if len(cells) == 27 else "HALT_MISSING_PAIRED_CELL",
                "n_cells": len(signs),
                "mean_delta": mean(signs),
                "median_delta": median(signs),
                "mean_reduction_percent": mean(finite_reductions) if finite_reductions else None,
                "median_reduction_percent": median(finite_reductions) if finite_reductions else None,
                "randomization_p": _randomization_p(signs, 20260723 + metric_index),
                "wilcoxon_p": _wilcoxon(signs),
                "sign_p": _exact_sign_test(signs),
                "ci_low": ci_low,
                "ci_high": ci_high,
                "repo_root": str(repo_root),
            }
        )
    return all_summary, missing


def aggregate_raw(
    raw_path: Path,
    out_dir: Path,
    *,
    repo_root: Path = ROOT,
) -> dict[str, Any]:
    """Aggregate a future raw-runs file without treating placeholders as data."""

    contract = load_contract(repo_root)
    rows = read_csv(raw_path) if raw_path.is_file() else []
    data_rows = [row for row in rows if row.get("record_type") == "formal_run"]
    certificate_path = out_dir / "independent_recalc_certificate.json"
    certificate: dict[str, Any] = {}
    if certificate_path.is_file():
        try:
            certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            certificate = {}
    certificate_valid = bool(
        data_rows
        and certificate.get("status") == "PASS_INDEPENDENT_RECALC"
        and certificate.get("contract_id") == contract["contract_id"]
        and certificate.get("raw_runs_sha256") == _sha256(raw_path)
    )
    summaries: list[dict[str, Any]] = []
    missing: list[str] = []
    for family in contract["families"]:
        primary_contrast = family.get(
            "primary_contrast",
            {
                "control": family["arms"][0]["id"],
                "treatment": family["arms"][1]["id"],
            },
        )
        contrast_specs = [("primary", primary_contrast)]
        contrast_specs.extend(
            ("secondary", contrast)
            for contrast in family.get("secondary_contrasts", [])
        )
        for contrast_role, contrast in contrast_specs:
            family_summary, family_missing = _contrast_rows(
                data_rows,
                family,
                contrast=contrast,
                contrast_role=contrast_role,
                repo_root=repo_root,
            )
            summaries.extend(family_summary)
            if contrast_role == "primary":
                missing.extend(family_missing)
    primary = [
        row
        for row in summaries
        if row["contrast_role"] == "primary"
        and row["metric"] == family_by_id(contract, row["family"])["primary_metric"]
    ]
    p_values = [row.get("randomization_p") for row in primary]
    for row, adjusted in zip(primary, _holm(p_values)):
        row["holm_adjusted_p"] = adjusted
    primary_by_key = {(row["family"], row["metric"]): row for row in primary}
    for row in summaries:
        row.setdefault("holm_adjusted_p", primary_by_key.get((row["family"], row["metric"]), {}).get("holm_adjusted_p"))
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(out_dir / "summary.csv", summaries, sorted({key for row in summaries for key in row}) or ["status"])
    decision = {
        "schema": "resetp.china.e3-e7-aggregate-decision.v1",
        "raw_path": str(raw_path),
        "formal_rows": len(data_rows),
        "search_evaluations": sum(int(float(row.get("search_evaluations") or 0)) for row in data_rows),
        "formal_search_allowed": False,
        "independent_recalc_complete": certificate_valid,
        "independent_recalc_certificate": _display_path(certificate_path, repo_root) if certificate_path.is_file() else None,
        "status": "NO_FORMAL_RESULTS" if not data_rows else ("HALT_MISSING_PAIRED_CELL" if missing else "AGGREGATE_READY_FOR_REVIEW"),
        "missing_or_incomplete": missing,
        "scientific_claim_allowed": False,
        "note": "统计器只汇总封存 raw_runs；它不改变正式闸门，也不把预检记录当成结果。",
    }
    write_json(out_dir / "decision.json", decision)
    (out_dir / "report.md").write_text(
        "\n".join(
            [
                "# 中国 E3–E7 统计汇总",
                "",
                f"状态：`{decision['status']}`。",
                f"正式 raw 行数：`{len(data_rows)}`；搜索评价次数：`{decision['search_evaluations']}`。",
                "",
                "本目录由固定合同驱动；若缺少配对 cell 或端点，统计停止，不删除不利单元。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    files = [out_dir / name for name in ("summary.csv", "decision.json", "report.md")]
    if certificate_path.is_file():
        files.append(certificate_path)
    write_json(
        out_dir / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "algorithm": "sha256",
            "files": {_display_path(path, repo_root): _sha256(path) for path in files},
        },
    )
    return decision
