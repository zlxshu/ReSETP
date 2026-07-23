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
import re
from collections import Counter, defaultdict
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


def _normalise_formal_row(
    source: dict[str, str],
) -> dict[str, str]:
    """Map a sealed E3 task row onto the common E3--E7 raw schema.

    The formal E3 runner deliberately keeps detailed task fields such as
    ``arm_id`` and ``elapsed_seconds``.  This adapter adds only deterministic
    aliases; it never changes a metric value or drops an unsuccessful row.
    """

    row = dict(source)
    arm_id = str(row.get("arm_id", "")).strip()
    task_id = str(row.get("task_id", "")).strip()
    if arm_id:
        row.setdefault("family", "E3")
        row.setdefault("arm", arm_id)
    if task_id.startswith("E3__"):
        row.setdefault("record_type", "formal_run")
        row.setdefault(
            "experiment_id",
            "CHINA-E3-FORMAL-RELEASE-001",
        )
    if (
        str(row.get("status", "")).strip().upper() == "PASS"
    ):
        row["formal_task_status"] = "PASS"
        row["status"] = "complete"
        row.setdefault("feasible", "true")
    aliases = {
        "customer_size": "customer_count",
        "total_emissions": "total_emissions_kg",
        "runtime_seconds": "elapsed_seconds",
        "search_evaluations": "complete_candidate_attempts",
    }
    for target, source_field in aliases.items():
        if not str(row.get(target, "")).strip():
            value = row.get(source_field)
            if value is not None and str(value).strip():
                row[target] = str(value)
    if not str(row.get("map_index", "")).strip():
        match = re.search(
            r"-(\d\d)-V2-LOCATIONS$",
            str(row.get("instance_id", "")),
        )
        if match is not None:
            row["map_index"] = str(int(match.group(1)))
    return row


def _metric_value(row: dict[str, str], metric: str) -> float | None:
    if metric == "feasible":
        return _bool(row.get(metric))
    return _float(row.get(metric))


def _raw_primary_cell_id(row: dict[str, str]) -> str:
    """Return the raw-result cell id without using catalog-only field names."""

    raw_size = row.get("customer_size")
    if raw_size is None or str(raw_size).strip() == "":
        # Retain compatibility with catalog rows used by older unit helpers,
        # but formal RAW_FIELDS uses customer_size.
        raw_size = row.get("customer_count")
    if raw_size is None or str(raw_size).strip() == "":
        raise ValueError("raw row has no customer_size")
    region = str(row.get("region", "")).strip().lower()
    if not region:
        raise ValueError("raw row has no region")
    return f"{region}__{int(float(raw_size))}"


def _expected_pair_id(
    family_id: str,
    instance_id: str,
    seed: str,
) -> str:
    return f"{family_id}__{instance_id}__seed{int(float(seed))}"


def _pairing_violations(
    rows: list[dict[str, str]],
    *,
    family_id: str,
    control: str,
    treatment: str,
) -> list[str]:
    """Fail closed unless the two arms share byte-bound pair identities."""

    rows = [_normalise_formal_row(row) for row in rows]
    selected = [
        row
        for row in rows
        if row.get("family") == family_id
        and row.get("arm") in {control, treatment}
        and row.get("status") == "complete"
    ]
    if not selected:
        return []
    grouped: dict[
        tuple[str, str],
        dict[str, list[dict[str, str]]],
    ] = defaultdict(lambda: defaultdict(list))
    violations: list[str] = []
    for row in selected:
        instance_id = str(row.get("instance_id", "")).strip()
        seed = str(row.get("seed", "")).strip()
        if not instance_id or not seed:
            violations.append(
                f"{family_id}:row_missing_instance_or_seed"
            )
            continue
        grouped[(instance_id, seed)][row["arm"]].append(row)

    paired_identity_fields = (
        "region",
        "customer_size",
        "map_index",
        "pair_id",
        "input_manifest_sha256",
        "contract_sha256",
    )
    if any(row.get("arm_id") for row in selected):
        paired_identity_fields += (
            "spatiotemporal_crosswalk_sha256",
            "responsibility_map_sha256",
            "initial_solution_sha256",
            "algorithm_source_sha256",
            "evaluator_source_sha256",
            "go_decision_sha256",
        )
    for (instance_id, seed), by_arm in sorted(grouped.items()):
        label = f"{family_id}:{instance_id}:seed{seed}"
        if set(by_arm) != {control, treatment}:
            violations.append(
                f"{label}:arms={sorted(by_arm)}"
            )
            continue
        if any(len(by_arm[arm]) != 1 for arm in (control, treatment)):
            violations.append(
                f"{label}:duplicate_arm_rows="
                f"{ {arm: len(by_arm[arm]) for arm in (control, treatment)} }"
            )
            continue
        control_row = by_arm[control][0]
        treatment_row = by_arm[treatment][0]
        expected_pair = _expected_pair_id(
            family_id,
            instance_id,
            seed,
        )
        if (
            control_row.get("pair_id") != expected_pair
            or treatment_row.get("pair_id") != expected_pair
        ):
            violations.append(
                f"{label}:pair_id_not_canonical"
            )
        for field in paired_identity_fields:
            left = str(control_row.get(field, "")).strip()
            right = str(treatment_row.get(field, "")).strip()
            if not left or not right:
                violations.append(
                    f"{label}:{field}=missing"
                )
            elif left != right:
                violations.append(
                    f"{label}:{field}=mismatch"
                )
    return violations


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
    expected_seeds: set[str] | None = None,
) -> tuple[dict[str, float], list[str]]:
    rows = [_normalise_formal_row(row) for row in rows]
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
    missing: list[str] = []
    seen_rows: Counter[tuple[str, str, str]] = Counter()
    for row in selected:
        cell = _raw_primary_cell_id(row)
        instance_id = row["instance_id"]
        seed = row["seed"]
        seen_key = (cell, instance_id, seed)
        seen_rows[seen_key] += 1
        if seen_rows[seen_key] > 1:
            missing.append(
                f"{family_id}:{arm_id}:{instance_id}:"
                f"seed{seed}:duplicate_formal_row"
            )
            continue
        if metric != "feasible" and _bool(row.get("feasible")) != 1.0:
            missing.append(
                f"{family_id}:{arm_id}:{instance_id}:"
                f"seed{seed}:{metric}=infeasible_without_registered_rule"
            )
            continue
        value = _metric_value(row, metric)
        if value is None:
            missing.append(
                f"{family_id}:{arm_id}:{instance_id}:"
                f"seed{seed}:{metric}=missing"
            )
            continue
        by_map[cell][instance_id][seed].append(value)
    means: dict[str, float] = {}
    for cell, instances in by_map.items():
        if len(instances) != 3:
            missing.append(f"{family_id}:{arm_id}:{cell}:maps={len(instances)}")
            continue
        seed_sets = [set(seeds) for seeds in instances.values()]
        if len({tuple(sorted(seeds)) for seeds in seed_sets}) != 1:
            missing.append(f"{family_id}:{arm_id}:{cell}:non_common_seeds")
            continue
        if (
            expected_seeds is not None
            and any(seeds != expected_seeds for seeds in seed_sets)
        ):
            observed = sorted(set().union(*seed_sets))
            missing.append(
                f"{family_id}:{arm_id}:{cell}:"
                f"seeds={observed}:expected={sorted(expected_seeds)}"
            )
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
    expected_seeds: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    control = contrast["control"]
    treatment = contrast["treatment"]
    direction = contrast.get("direction", family["direction"])
    metrics = [family["primary_metric"], *family.get("secondary_metrics", [])]
    all_summary: list[dict[str, Any]] = []
    missing: list[str] = []
    for metric_index, metric in enumerate(metrics):
        controls, control_missing = _cell_map_means(
            rows,
            metric=metric,
            family_id=family["id"],
            arm_id=control,
            expected_seeds=expected_seeds,
        )
        treatments, treatment_missing = _cell_map_means(
            rows,
            metric=metric,
            family_id=family["id"],
            arm_id=treatment,
            expected_seeds=expected_seeds,
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
    rows = (
        [
            _normalise_formal_row(row)
            for row in read_csv(raw_path)
        ]
        if raw_path.is_file()
        else []
    )
    data_rows = [row for row in rows if row.get("record_type") == "formal_run"]
    certificate_path = out_dir / "independent_recalc_certificate.json"
    certificate: dict[str, Any] = {}
    if certificate_path.is_file():
        try:
            certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            certificate = {}
    accepted_contract_ids = {
        str(contract["contract_id"]),
        str(contract["experiment_id"]),
    }
    certificate_valid = bool(
        data_rows
        and certificate.get("status") == "PASS_INDEPENDENT_RECALC"
        and certificate.get("contract_id") in accepted_contract_ids
        and certificate.get("raw_runs_sha256") == _sha256(raw_path)
    )
    summaries: list[dict[str, Any]] = []
    missing: list[str] = []
    active_families = {
        str(row.get("family", "")).strip()
        for row in data_rows
        if str(row.get("family", "")).strip()
    }
    expected_seeds = {
        str(seed)
        for seed in contract["paired_sampling"][
            "initial_common_seeds"
        ]
    }
    for family in contract["families"]:
        if family["id"] not in active_families:
            continue
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
            if contrast_role == "primary":
                missing.extend(
                    _pairing_violations(
                        data_rows,
                        family_id=family["id"],
                        control=contrast["control"],
                        treatment=contrast["treatment"],
                    )
                )
            family_summary, family_missing = _contrast_rows(
                data_rows,
                family,
                contrast=contrast,
                contrast_role=contrast_role,
                repo_root=repo_root,
                expected_seeds=expected_seeds,
            )
            summaries.extend(family_summary)
            if contrast_role == "primary":
                missing.extend(family_missing)
    missing = list(dict.fromkeys(missing))
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
        "active_families": sorted(active_families),
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
