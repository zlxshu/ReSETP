#!/usr/bin/env python3
"""Audit manuscript claims against sealed ReSETP experiment evidence."""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
import statistics
import subprocess
import sys
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from baselines.paper_story import build_20260715_formal_evidence as evidence_builder  # noqa: E402

TEX = ROOT / "docs/paper_submission_final/paper_main.tex"
PAPER_DIR = TEX.parent
PAPER_PDF = PAPER_DIR / "paper_main.pdf"
PAPER_LOG = PAPER_DIR / "paper_main.log"
PAPER_FLS = PAPER_DIR / "paper_main.fls"
QUALITY_GATES = (
    ROOT / "docs/handoff/resetp_research_experiment_writing_quality_gates_20260715.md"
)
COMPLETION_MATRIX = ROOT / "docs/handoff/resetp_goal_completion_matrix_20260716.md"
HANDOFF = ROOT / "HANDOFF.md"
PROJECT_MEMORY = ROOT / "docs/handoff/memory/MEMORY.md"
DYNAMIC_MEMORY = ROOT / "docs/handoff/memory/dynamic-demand-integration.md"
PRD_MEMORY = ROOT / "docs/handoff/memory/project-prd-execution-v2.md"
FINAL_RECORD_MARKER = "E7正式结果终验"
TABLES = ROOT / "docs/paper_submission_final/generated_tables"
E1 = ROOT / "baselines/e1_model/e1_submission_20260711_committed/formal"
E1_SEAL_COMMIT = "28c91128855e50c5e6e6ebcafa6cfeb089ecddf5"
E2 = ROOT / "baselines/e2_alns/e2_final_10seed_20260711/formal"
E2_SEAL_COMMIT = "1180abf3e3bb6a69442403fc7521801babd7b4ac"
E2_SEAL_TAG = "e2-10seed-final-20260712"
E2_LEGACY_UNLISTED = {
    "baselines/e2_alns/e2_final_10seed_20260711/formal/baseline_parameter_appendix.csv",
    "baselines/e2_alns/e2_final_10seed_20260711/formal/baseline_parameter_appendix.md",
}
E2B = ROOT / "baselines/e2_alns/e2b_component_ablation_formal_20260715"
E2_PUBLIC = ROOT / "baselines/algorithm_foundation/remix_v13_formal"
E2_PUBLIC_REQUIRED_SOURCE_FILES = (
    "metadata.json",
    "raw_runs.csv",
    "decision.json",
    "artifact_hashes.json",
    "report.md",
)
E2_PUBLIC_GENERATED_EXHIBITS = (
    "e2_v13_mdvrptw_results.tex",
    "e2_v13_mdvrptw_summary.tex",
    "e2_v13_mdvrptw_interpretation.tex",
)
E2_PUBLIC_MANIFEST = "e2_v13_mdvrptw_paper_evidence_manifest.json"
E2_PUBLIC_EXHIBITS = (
    *E2_PUBLIC_GENERATED_EXHIBITS,
    E2_PUBLIC_MANIFEST,
)
E2_V13_MAIN_TABLE_FORBIDDEN_TERMS = (
    "Solomon",
    "SINTEF公开解",
    "先最小化车辆数",
    "共计560次",
    "DIMACS",
    "PassMark",
    "截断至1位小数",
    "CPU标准化墙钟时间",
)
E2_V13_MAIN_TABLE_REQUIRED_TERMS = (
    "全部28个V13-MDVRPTW算例",
    "不按本文结果删题",
    "当前可独立复算的最好值",
    "VCGP",
    "PyVRP",
    "MDFIHA-ETGA",
    "同机算法才比较运行时间",
    "任何单题落后均保留",
)
E3 = ROOT / "baselines/e3_ablation/e3_medium_paired_cost_formal_20260715"
E4 = ROOT / "baselines/e4_e5/e4_forecast_timing_formal_20260713"
E6 = ROOT / "baselines/e6_fairness/e6_profit_guarantee_frontier_20260715"
E4_ACTIVE_SOURCE_REANCHOR_SHA256 = {
    "solver/src/setp_solver/search/multitrip_schedule.py": "1274da792bdf03d9544f0f3afc74612f06f2d1324e9e75d1bc225e5bb3e94d13",
    "solver/src/setp_solver/cost.py": "e7ea406da87a3172cd1ff7dc87fe7def536e74f197f6c67b29da2394fe42b00d",
    "solver/src/setp_solver/check.py": "86b813152b2fc7f89500468cc3d73178cb1bdafe9dc659852b437c5fdb07702b",
    "solver/src/setp_solver/search/e3_multitrip_runtime.py": "8a221addc26807a9a54603999cd5f47d276351bc03907b364c9e0f7886e360e3",
    "solver/src/setp_solver/search/formal_runner.py": "4d80f576f540ccbc64d10dba711fd14332968756524f50fa69a8805ab092aa8a",
}
PUBLIC_ADAPTER = ROOT / "baselines/e2_alns/goeke_public_benchmark_adapter_gate_20260716"
EXPECTED_STATIC_INSTANCES = (
    "L-main-threeshift-10c-01",
    "L-main-threeshift-15c-01",
    "L-main-threeshift-20c-01",
    "L-main-threeshift-25c-01",
    "L-main-threeshift-50c-01",
    "L-main-threeshift-75c-01",
    "L-main-threeshift-100c-01",
    "L-main-threeshift-150c-01",
    "L-main-threeshift-200c-01",
)
EXPECTED_STATIC_SEEDS = (1, 2, 3)
EXPECTED_E2B_SEEDS = (1, 2, 3, 4, 5)
EXPECTED_E4_DAYS = tuple(f"2025-11-{day:02d}" for day in range(2, 30))
EXPECTED_E6_ALPHAS = (0.0, 0.25, 0.5, 0.75, 1.0)
E7_FORMAL = ROOT / "baselines/e7_dynamic/e7_multinetwork_formal_20260715"
E7_REPLAY = ROOT / "baselines/e7_dynamic/e7_multiday_zero_search_replay_20260715"
E7_REPLAY_INVARIANTS = (
    ROOT / "baselines/e7_dynamic/e7_replay_invariants_audit_20260715"
)
E7_AUDIT = ROOT / "baselines/e7_dynamic/e7_multinetwork_independent_audit_20260715"
E7_EXHIBITS = evidence_builder.E7_EXHIBIT_NAMES
E7_PROVENANCE = evidence_builder.E7_PROVENANCE_NAME
E7_REQUIRED_PAPER_FILES = (*E7_EXHIBITS, E7_PROVENANCE)
E7_REPLAY_INVARIANT_COUNTS = {
    "full_task_count": 30,
    "task_day_row_count": 840,
    "window_violation_count": 0,
    "station_capacity_violation_count": 0,
    "route_hash_failure_count": 0,
    "energy_hash_failure_count": 0,
    "emissions_recalculation_failure_count": 0,
    "route_search_evaluations": 0,
}
E7_REQUIRED_INDEPENDENT_CHECKS = (
    "external_monitor_pause_timing_uncontaminated",
    "replay_invariants_decision_pass",
    "replay_invariants_artifact_hashes_pass",
    "replay_invariant_row_count_840",
    "replay_charger_capacity_and_trigger_windows_pass",
)
CURRENT_TITLE_ZH = "时变碳强度下多车场协同路径优化模型及算法"
FORBIDDEN_PATH_GLYPHS = ("路经", "路劲", "路徑", "路迳", "路逕")
CURRENT_TITLE_EN = (
    "Multi-depot Collaborative Routing Model and Algorithm under Time-varying Carbon Intensity"
)
REQUIRED_EXPERIMENT_SURFACES = (
    "metadata.json",
    "raw_runs.csv",
    "decision.json",
    "artifact_hashes.json",
    "report.md",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def verify_manifest(root: Path) -> list[str]:
    manifest_path = root / "artifact_hashes.json"
    if not manifest_path.is_file():
        return [f"{display_path(root)}: artifact_hashes.json missing"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        return [f"{display_path(root)}: artifact_hashes.json is not an object"]
    label = display_path(root)
    observed = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and path.name != ".DS_Store"
        and ".tasks" not in path.parts
    }
    failures = [
        f"{label}: unlisted {relative}"
        for relative in sorted(observed - set(manifest))
    ]
    failures.extend(
        f"{label}: missing {relative}"
        for relative in sorted(set(manifest) - observed)
    )
    failures.extend(
        f"{label}: hash drift {relative}"
        for relative, expected in manifest.items()
        if (root / relative).is_file() and sha256(root / relative) != expected
    )
    return failures


def required_surface_failures(root: Path) -> list[str]:
    """Require the five user-facing experiment record surfaces, not only a manifest."""
    label = display_path(root)
    return [
        f"{label}: required experiment surface missing {name}"
        for name in REQUIRED_EXPERIMENT_SURFACES
        if not (root / name).is_file()
    ]


def global_hash_manifest_failures(path: Path, *, expected_count: int) -> list[str]:
    """Verify a historical manifest whose paths span several repository roots."""
    failures: list[str] = []
    try:
        manifest = read_json(path)
        rows = manifest["files"]
    except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        return [f"E4 global manifest could not be read: {exc}"]
    if not isinstance(rows, list) or len(rows) != expected_count:
        return [f"E4 global manifest does not contain exactly {expected_count} files"]
    observed: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            failures.append(f"E4 global manifest row {index} is not an object")
            continue
        relative = str(row.get("path", ""))
        historical_expected = str(row.get("sha256", ""))
        expected = (
            E4_ACTIVE_SOURCE_REANCHOR_SHA256.get(relative, historical_expected)
            if path.resolve() == (E4 / "artifact_hashes.json").resolve()
            else historical_expected
        )
        if relative in observed:
            failures.append(f"E4 global manifest contains duplicate path {relative}")
            continue
        observed.add(relative)
        candidate = (ROOT / relative).resolve()
        try:
            candidate.relative_to(ROOT.resolve())
        except ValueError:
            failures.append(f"E4 global manifest path escapes repository: {relative}")
            continue
        if not candidate.is_file():
            failures.append(f"E4 global manifest path is missing: {relative}")
        elif sha256(candidate) != expected:
            failures.append(f"E4 global manifest hash drift: {relative}")
    for required in (
        "baselines/e4_e5/e4_forecast_timing_formal_20260713/metadata.json",
        "baselines/e4_e5/e4_forecast_timing_formal_20260713/raw_runs.csv",
        "baselines/e4_e5/e4_forecast_timing_formal_20260713/decision.json",
        "baselines/e4_e5/e4_forecast_timing_formal_20260713/report.md",
        "baselines/e4_e5/e4_forecast_timing_formal_20260713/verification.json",
    ):
        if required not in observed:
            failures.append(f"E4 global manifest omits required evidence {required}")
    return failures


def e2b_identity_failures(root: Path) -> list[str]:
    """Recompute the exact 45-unit/180-row component-ablation design."""
    failures: list[str] = []
    try:
        decision = read_json(root / "decision.json")
        raw = pd.read_csv(root / "raw_runs.csv")
        manifest = pd.read_csv(root / "task_manifest.csv")
    except (FileNotFoundError, KeyError, ValueError, pd.errors.ParserError) as exc:
        return [f"E2b identity audit could not read formal evidence: {exc}"]

    expected_units = {
        (instance, "mixed", seed)
        for instance in EXPECTED_STATIC_INSTANCES
        for seed in EXPECTED_E2B_SEEDS
    }
    search_arms = ("A_continuous", "B_staged", "C_staged_cross")
    all_arms = (*search_arms, "D_full")
    expected_raw = {(*unit, arm) for unit in expected_units for arm in all_arms}
    expected_manifest = {(*unit, arm) for unit in expected_units for arm in search_arms}
    try:
        def identities(frame: pd.DataFrame) -> set[tuple[str, str, int, str]]:
            return {
                (
                    str(row.instance),
                    str(row.condition),
                    int(row.seed),
                    str(row.group_id),
                )
                for row in frame.itertuples(index=False)
            }

        if len(raw) != 180 or identities(raw) != expected_raw:
            failures.append("E2b raw_runs does not contain the exact 9 x 5 x 4 design")
        if len(manifest) != 135 or identities(manifest) != expected_manifest:
            failures.append("E2b task_manifest does not contain the exact 9 x 5 x 3 search design")
        if not (raw["valid"].eq(True).all() and raw["violation_count"].eq(0).all()):  # noqa: E712
            failures.append("E2b formal rows contain a validity or feasibility failure")

        searched = raw["group_id"].isin(search_arms)
        replayed = raw["group_id"].eq("D_full")
        if not (
            raw.loc[searched, "configured_search_budget"].eq(4000).all()
            and raw.loc[searched, "actual_search_evals"].eq(4000).all()
            and raw.loc[searched, "search_performed"].eq(True).all()  # noqa: E712
            and raw.loc[replayed, "configured_search_budget"].eq(0).all()
            and raw.loc[replayed, "actual_search_evals"].eq(0).all()
            and raw.loc[replayed, "search_performed"].eq(False).all()  # noqa: E712
            and raw.loc[replayed, "source_search_evals"].eq(4000).all()
        ):
            failures.append("E2b search and charging-replay budgets differ from the frozen contract")

        raw_indexed = raw.set_index(["instance", "condition", "seed", "group_id"])
        comparisons = {
            "B_minus_A_total_cost": ("A_continuous", "B_staged", "total_cost"),
            "C_minus_B_total_cost": ("B_staged", "C_staged_cross", "total_cost"),
            "D_minus_C_ev_indirect": ("C_staged_cross", "D_full", "E_ev_indirect"),
        }
        tolerance = 1e-6
        for name, (left_arm, right_arm, metric) in comparisons.items():
            deltas: list[float] = []
            for unit in sorted(expected_units):
                left = float(raw_indexed.loc[(*unit, left_arm), metric])
                right = float(raw_indexed.loc[(*unit, right_arm), metric])
                deltas.append(right - left)
            observed = decision["paired_summary"][name]
            expected_summary = {
                "pair_count": len(deltas),
                "right_better": sum(value < -tolerance for value in deltas),
                "ties": sum(abs(value) <= tolerance for value in deltas),
                "right_worse": sum(value > tolerance for value in deltas),
            }
            if any(int(observed[key]) != value for key, value in expected_summary.items()):
                failures.append(f"E2b paired summary counts do not recompute for {name}")
            if abs(float(observed["mean_delta"]) - statistics.fmean(deltas)) > 1e-9:
                failures.append(f"E2b paired mean does not recompute for {name}")

        c = raw.loc[raw["group_id"].eq("C_staged_cross")].set_index(
            ["instance", "condition", "seed"]
        )
        d = raw.loc[raw["group_id"].eq("D_full")].set_index(
            ["instance", "condition", "seed"]
        )
        for field in ("route_signature", "route_vehicle_sha256", "electricity_kwh"):
            if not c[field].equals(d[field]):
                failures.append(f"E2b D replay changes frozen C field {field}")
        if bool((d["E_ev_indirect"] > c["E_ev_indirect"] + 1e-6).any()):
            failures.append("E2b D replay increases EV indirect emissions in a paired unit")
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        failures.append(f"E2b identity audit schema failure: {exc}")
    return failures


def e3_identity_failures(root: Path) -> list[str]:
    """Recompute the exact 27-pair/54-run E3 design from CSV identities."""
    failures: list[str] = []
    try:
        decision = read_json(root / "decision.json")
        paired = pd.read_csv(root / "paired_results.csv")
        raw = pd.read_csv(root / "raw_runs.csv")
        manifest = pd.read_csv(root / "task_manifest.csv")
        trend = pd.read_csv(root / "trend_summary.csv")
    except (FileNotFoundError, KeyError, ValueError, pd.errors.ParserError) as exc:
        return [f"E3 identity audit could not read formal evidence: {exc}"]

    expected_pairs = {
        (instance, "medium", seed)
        for instance in EXPECTED_STATIC_INSTANCES
        for seed in EXPECTED_STATIC_SEEDS
    }
    try:
        observed_pairs = {
            (str(row.instance), str(row.condition), int(row.seed))
            for row in paired.itertuples(index=False)
        }
        if len(paired) != 27 or observed_pairs != expected_pairs:
            failures.append("E3 paired_results does not contain the exact 9-network x 3-seed design")
        if paired["pair_id"].nunique() != 27:
            failures.append("E3 paired_results pair_id values are not unique")

        expected_tasks = {
            (*pair, arm)
            for pair in expected_pairs
            for arm in ("ownership_fixed", "reassignment_allowed")
        }
        observed_raw = {
            (str(row.instance), str(row.condition), int(row.seed), str(row.arm))
            for row in raw.itertuples(index=False)
        }
        observed_manifest = {
            (str(row.instance), str(row.condition), int(row.seed), str(row.arm))
            for row in manifest.itertuples(index=False)
        }
        if len(raw) != 54 or observed_raw != expected_tasks:
            failures.append("E3 raw_runs does not contain exactly two arms for every formal pair")
        if len(manifest) != 54 or observed_manifest != expected_tasks:
            failures.append("E3 task_manifest identity set differs from the formal 54-run design")
        if not (raw["status"].eq("PASS").all() and raw["evaluations"].eq(4000).all()):
            failures.append("E3 formal runs are not all PASS at the frozen 4000-evaluation budget")
        if not (raw["violation_count"].eq(0).all() and raw["coverage_ok"].eq(True).all()):  # noqa: E712
            failures.append("E3 formal runs contain a feasibility or customer-coverage failure")
        contract = str(decision.get("contract_sha256", ""))
        if set(raw["contract_sha256"].astype(str)) != {contract} or set(
            manifest["contract_sha256"].astype(str)
        ) != {contract}:
            failures.append("E3 raw runs or task manifest drift from the frozen contract")
        raw_formula = 100.0 * (
            paired["raw_fixed_total_cost"] - paired["raw_open_total_cost"]
        ) / paired["raw_fixed_total_cost"]
        selected_formula = 100.0 * (
            paired["selected_fixed_total_cost"] - paired["selected_open_total_cost"]
        ) / paired["selected_fixed_total_cost"]
        if float((raw_formula - paired["raw_search_saving_pct"]).abs().max()) > 1e-9:
            failures.append("E3 raw paired savings do not recompute from paired costs")
        if float((selected_formula - paired["selected_saving_pct"]).abs().max()) > 1e-9:
            failures.append("E3 selected paired savings do not recompute from paired costs")
        if len(trend) != 9 or set(trend["instance"].astype(str)) != set(
            EXPECTED_STATIC_INSTANCES
        ):
            failures.append("E3 trend_summary does not contain exactly the nine frozen networks")
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        failures.append(f"E3 identity audit schema failure: {exc}")
    return failures


def e4_identity_failures(root: Path) -> list[str]:
    """Recompute the fixed-schedule, 28-grid-day charging-timing evidence."""
    failures: list[str] = []
    try:
        decision = read_json(root / "decision.json")
        verification = read_json(root / "verification.json")
        raw = pd.read_csv(root / "raw_runs.csv")
        actions = pd.read_csv(root / "action_runs.csv")
        paired = pd.read_csv(root / "paired_by_seed_day.csv")
        cell = pd.read_csv(root / "cell_summary.csv")
        network = pd.read_csv(root / "network_summary.csv")
        day = pd.read_csv(root / "day_summary.csv")
        aggregate = pd.read_csv(root / "aggregate_summary.csv")
        interaction = pd.read_csv(root / "interaction_overall.csv")
    except (FileNotFoundError, KeyError, ValueError, pd.errors.ParserError) as exc:
        return [f"E4 identity audit could not read formal evidence: {exc}"]

    conditions = ("geographic", "mixed")
    arms = ("ownership_fixed", "reassignment_allowed")
    rules = ("immediate", "forecast_timed", "actual_oracle")
    base_keys = ["instance", "condition", "arm", "seed", "operating_day"]
    action_keys = [*base_keys, "timing_rule"]
    expected_pairs = {
        (instance, condition, arm, seed, operating_day)
        for instance in EXPECTED_STATIC_INSTANCES
        for condition in conditions
        for arm in arms
        for seed in EXPECTED_STATIC_SEEDS
        for operating_day in EXPECTED_E4_DAYS
    }
    expected_raw = {(*pair, rule) for pair in expected_pairs for rule in rules}
    expected_cells = {
        (instance, condition, arm, operating_day)
        for instance in EXPECTED_STATIC_INSTANCES
        for condition in conditions
        for arm in arms
        for operating_day in EXPECTED_E4_DAYS
    }
    try:
        raw_ids = {
            (
                str(row.instance),
                str(row.condition),
                str(row.arm),
                int(row.seed),
                str(row.operating_day),
                str(row.timing_rule),
            )
            for row in raw.itertuples(index=False)
        }
        paired_ids = {
            (
                str(row.instance),
                str(row.condition),
                str(row.arm),
                int(row.seed),
                str(row.operating_day),
            )
            for row in paired.itertuples(index=False)
        }
        cell_ids = {
            (str(row.instance), str(row.condition), str(row.arm), str(row.operating_day))
            for row in cell.itertuples(index=False)
        }
        if len(raw) != 9072 or raw_ids != expected_raw:
            failures.append("E4 raw_runs does not contain the exact 9 x 2 x 2 x 3 x 28 x 3 design")
        if len(paired) != 3024 or paired_ids != expected_pairs:
            failures.append("E4 paired_by_seed_day does not contain the exact 3024 paired units")
        if len(cell) != 1008 or cell_ids != expected_cells:
            failures.append("E4 cell_summary does not contain the exact 1008 seed-averaged cells")
        if len(network) != 36 or len(day) != 112 or len(aggregate) != 4:
            failures.append("E4 network/day/aggregate summary dimensions differ from 36/112/4")
        if len(actions) != 132300:
            failures.append("E4 charging-action ledger does not contain exactly 132300 rows")
        if not (
            raw["route_unchanged"].eq(True).all()  # noqa: E712
            and raw["service_unchanged"].eq(True).all()  # noqa: E712
            and raw["energy_unchanged"].eq(True).all()  # noqa: E712
            and raw["hard_violation_count"].eq(0).all()
            and raw["clock_violation_count"].eq(0).all()
        ):
            failures.append("E4 fixed-route/service/energy or feasibility contract fails")

        grouped = raw.groupby(base_keys, sort=False)
        for field in (
            "route_fingerprint",
            "service_fingerprint",
            "energy_fingerprint",
            "charging_kwh",
            "direct_fuel_emissions_kg",
        ):
            if int(grouped[field].nunique().max()) != 1:
                failures.append(f"E4 timing rules change frozen paired field {field}")

        action_sums = actions.groupby(action_keys, as_index=False).agg(
            action_kwh=("energy_kwh", "sum"),
            action_actual=("actual_emissions_kg", "sum"),
            action_forecast=("forecast_emissions_kg", "sum"),
        )
        joined_actions = raw.merge(
            action_sums, on=action_keys, how="outer", validate="one_to_one", indicator=True
        )
        if len(joined_actions) != 9072 or not joined_actions["_merge"].eq("both").all():
            failures.append("E4 action ledger does not map one-to-one onto raw timing rows")
        for action_field, raw_field in (
            ("action_kwh", "charging_kwh"),
            ("action_actual", "actual_charging_emissions_kg"),
            ("action_forecast", "forecast_charging_emissions_kg"),
        ):
            if float((joined_actions[action_field] - joined_actions[raw_field]).abs().max()) > 1e-9:
                failures.append(f"E4 action ledger does not sum to raw field {raw_field}")

        indexed = {
            rule: raw.loc[raw["timing_rule"].eq(rule)].set_index(base_keys).sort_index()
            for rule in rules
        }
        paired_indexed = paired.set_index(base_keys).sort_index()
        immediate = indexed["immediate"]
        forecast = indexed["forecast_timed"]
        oracle = indexed["actual_oracle"]
        formulas = {
            "realized_saving_kg": immediate["actual_charging_emissions_kg"]
            - forecast["actual_charging_emissions_kg"],
            "realized_saving_pct": 100.0
            * (
                immediate["actual_charging_emissions_kg"]
                - forecast["actual_charging_emissions_kg"]
            )
            / immediate["actual_charging_emissions_kg"],
            "total_operational_reduction_pct": 100.0
            * (
                immediate["actual_charging_emissions_kg"]
                - forecast["actual_charging_emissions_kg"]
            )
            / (
                immediate["actual_charging_emissions_kg"]
                + immediate["direct_fuel_emissions_kg"]
            ),
            "oracle_potential_kg": immediate["actual_charging_emissions_kg"]
            - oracle["actual_charging_emissions_kg"],
            "oracle_potential_pct": 100.0
            * (
                immediate["actual_charging_emissions_kg"]
                - oracle["actual_charging_emissions_kg"]
            )
            / immediate["actual_charging_emissions_kg"],
            "predicted_saving_kg": immediate["forecast_charging_emissions_kg"]
            - forecast["forecast_charging_emissions_kg"],
        }
        for field, recomputed in formulas.items():
            if float((paired_indexed[field] - recomputed).abs().max()) > 1e-9:
                failures.append(f"E4 paired formula does not recompute for {field}")
        if bool(
            (
                forecast["forecast_charging_emissions_kg"]
                > immediate["forecast_charging_emissions_kg"] + 1e-9
            ).any()
        ):
            failures.append("E4 forecast-timed rule increases its forecast objective")
        if bool(
            (
                oracle["actual_charging_emissions_kg"]
                > forecast["actual_charging_emissions_kg"] + 1e-9
            ).any()
        ):
            failures.append("E4 actual-oracle row is not an actual-emissions lower bound")

        recomputed_cell = (
            paired.groupby(["instance", "condition", "arm", "operating_day"], as_index=False)
            .agg(
                mean_immediate_actual_charging_kg=("immediate_actual_charging_kg", "mean"),
                mean_realized_saving_kg=("realized_saving_kg", "mean"),
                mean_direct_fuel_emissions_kg=("direct_fuel_emissions_kg", "mean"),
                mean_pre_day_realized_saving_kg=("pre_day_realized_saving_kg", "mean"),
            )
        )
        saved_cell = cell.set_index(["instance", "condition", "arm", "operating_day"]).sort_index()
        recomputed_cell = recomputed_cell.set_index(
            ["instance", "condition", "arm", "operating_day"]
        ).sort_index()
        for field in (
            "mean_immediate_actual_charging_kg",
            "mean_realized_saving_kg",
            "mean_direct_fuel_emissions_kg",
            "mean_pre_day_realized_saving_kg",
        ):
            if float((saved_cell[field] - recomputed_cell[field]).abs().max()) > 1e-9:
                failures.append(f"E4 seed-averaged cell does not recompute for {field}")

        aggregate_indexed = aggregate.set_index(["condition", "arm"])
        for condition in conditions:
            for arm in arms:
                block = recomputed_cell.xs((condition, arm), level=("condition", "arm"))
                immediate_sum = float(block["mean_immediate_actual_charging_kg"].sum())
                saving_sum = float(block["mean_realized_saving_kg"].sum())
                direct_sum = float(block["mean_direct_fuel_emissions_kg"].sum())
                pre_day_sum = float(block["mean_pre_day_realized_saving_kg"].sum())
                network_savings = block.groupby(level="instance")["mean_realized_saving_kg"].sum()
                day_savings = block.groupby(level="operating_day")["mean_realized_saving_kg"].sum()
                expected_summary = {
                    "pooled_charging_reduction_pct": 100.0 * saving_sum / immediate_sum,
                    "pooled_total_operational_reduction_pct": 100.0
                    * saving_sum
                    / (immediate_sum + direct_sum),
                    "networks_improved": int((network_savings > 1e-6).sum()),
                    "days_improved": int((day_savings > 1e-6).sum()),
                    "days_worsened": int((day_savings < -1e-6).sum()),
                    "pre_day_share_of_positive_total_saving_pct": 100.0
                    * pre_day_sum
                    / saving_sum,
                }
                saved = aggregate_indexed.loc[(condition, arm)]
                for field, value in expected_summary.items():
                    if abs(float(saved[field]) - value) > 1e-9:
                        failures.append(
                            f"E4 aggregate summary does not recompute for {condition}/{arm}/{field}"
                        )

        reductions = aggregate["pooled_charging_reduction_pct"]
        total_reductions = aggregate["pooled_total_operational_reduction_pct"]
        if not (
            abs(float(reductions.min()) - 3.887798459404608) <= 1e-9
            and abs(float(reductions.max()) - 4.87666867834168) <= 1e-9
            and abs(float(total_reductions.min()) - 0.35153335338471176) <= 1e-9
            and abs(float(total_reductions.max()) - 0.5232816116456492) <= 1e-9
            and aggregate["networks_improved"].eq(9).all()
            and int(aggregate["days_improved"].min()) == 18
            and int(aggregate["days_improved"].max()) == 20
            and aggregate["days_worsened"].gt(0).all()
        ):
            failures.append("E4 headline range or network/day direction boundary differs")

        if len(interaction) != 2:
            failures.append("E4 interaction_overall does not contain two responsibility conditions")
        else:
            expected_interaction = {
                "geographic": (0.2505030076388159, 6, 3, 17, 11),
                "mixed": (0.5144170602516939, 9, 0, 16, 12),
            }
            for row in interaction.itertuples(index=False):
                mean_delta, network_positive, network_negative, day_positive, day_negative = (
                    expected_interaction[str(row.condition)]
                )
                if not (
                    abs(float(row.network_mean_difference_percentage_points) - mean_delta) <= 1e-9
                    and int(row.network_positive) == network_positive
                    and int(row.network_negative) == network_negative
                    and int(row.day_positive) == day_positive
                    and int(row.day_negative) == day_negative
                ):
                    failures.append(f"E4 collaboration interaction differs for {row.condition}")

        if decision.get("verdict") != "PASS_E4_FORECAST_TIMING_FORMAL" or not decision.get(
            "all_mechanical_checks_pass"
        ):
            failures.append("E4 formal decision is not mechanically complete")
        if verification.get("status") != "PASS_INDEPENDENT_RECALC_AND_HASH_AUDIT":
            failures.append("E4 independent verification status differs")
    except (AttributeError, KeyError, TypeError, ValueError, pd.errors.MergeError) as exc:
        failures.append(f"E4 identity audit schema failure: {exc}")
    return failures


def e6_identity_failures(root: Path) -> list[str]:
    """Recompute the exact 54-spec x 5-level E6 frontier design."""
    failures: list[str] = []
    try:
        decision = read_json(root / "decision.json")
        raw = pd.read_csv(root / "raw_runs.csv")
        selected = pd.read_csv(root / "selected_frontier.csv")
        manifest = pd.read_csv(root / "task_manifest.csv")
    except (FileNotFoundError, KeyError, ValueError, pd.errors.ParserError) as exc:
        return [f"E6 identity audit could not read formal evidence: {exc}"]

    expected = {
        (instance, condition, seed, alpha)
        for instance in EXPECTED_STATIC_INSTANCES
        for condition in ("geographic", "mixed")
        for seed in EXPECTED_STATIC_SEEDS
        for alpha in EXPECTED_E6_ALPHAS
    }
    try:
        def identities(frame: pd.DataFrame) -> set[tuple[str, str, int, float]]:
            return {
                (str(row.instance), str(row.condition), int(row.seed), float(row.alpha))
                for row in frame.itertuples(index=False)
            }

        for name, frame in (
            ("raw_runs", raw),
            ("selected_frontier", selected),
            ("task_manifest", manifest),
        ):
            if len(frame) != 270 or identities(frame) != expected:
                failures.append(f"E6 {name} does not contain the exact 9 x 2 x 3 x 5 design")
        if not (raw["status"].eq("PASS").all() and raw["planned_budget"].eq(4000).all()):
            failures.append("E6 formal rows are not all PASS under the frozen budget contract")
        if not (raw["violation_count"].eq(0).all() and raw["fairness_satisfied"].eq(True).all()):  # noqa: E712
            failures.append("E6 formal rows contain a feasibility or participation failure")
        search = raw["executed_search"].eq(True)  # noqa: E712
        reused = raw["reused_from_alpha0"].eq(True)  # noqa: E712
        if int(search.sum()) != 174 or int(reused.sum()) != 96 or bool((search == reused).any()):
            failures.append("E6 search/reuse partition differs from 174 executed and 96 reused rows")
        if not (raw.loc[search, "evaluations"].eq(4000).all() and raw.loc[reused, "evaluations"].eq(0).all()):
            failures.append("E6 evaluation counts do not match the search/reuse partition")
        contract = str(decision.get("contract_sha256", ""))
        if set(raw["contract_sha256"].astype(str)) != {contract} or set(
            manifest["contract_sha256"].astype(str)
        ) != {contract}:
            failures.append("E6 raw runs or task manifest drift from the frozen contract")
        if bool(
            (
                selected["selected_minimum_profit_ratio"]
                + 1e-10
                < selected["displayed_theta"]
            ).any()
        ):
            failures.append("E6 selected frontier contains a row below its participation threshold")
        for _spec_id, group in selected.groupby("spec_id", sort=False):
            alpha0 = group.loc[group["alpha"].eq(0.0), "selected_total_cost"]
            if len(alpha0) != 1:
                failures.append("E6 frontier spec does not contain exactly one alpha=0 baseline")
                continue
            recomputed = 100.0 * (group["selected_total_cost"] / float(alpha0.iloc[0]) - 1.0)
            if float((recomputed - group["cost_increment_pct"]).abs().max()) > 1e-9:
                failures.append("E6 cost increments do not recompute from the alpha=0 baseline")
                break
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        failures.append(f"E6 identity audit schema failure: {exc}")
    return failures


def final_record_failures() -> list[str]:
    failures: list[str] = []
    for path in (HANDOFF, PROJECT_MEMORY, DYNAMIC_MEMORY, PRD_MEMORY):
        if not path.is_file():
            failures.append(f"final record surface missing: {display_path(path)}")
            continue
        if FINAL_RECORD_MARKER not in path.read_text(encoding="utf-8"):
            failures.append(
                f"final record marker missing from {display_path(path)}: {FINAL_RECORD_MARKER}"
            )
    return failures


def verify_legacy_manifest(
    root: Path, *, allowed_unlisted: set[str] | None = None
) -> list[str]:
    """Verify the old ``file_count/files`` manifest without rewriting it."""

    allowed = allowed_unlisted or set()
    label = display_path(root)
    manifest_path = root / "artifact_hashes.json"
    if not manifest_path.is_file():
        return [f"{label}: legacy artifact_hashes.json missing"]
    manifest = read_json(manifest_path)
    rows = manifest.get("files")
    if not isinstance(rows, list):
        return [f"{label}: legacy manifest files list missing"]
    failures: list[str] = []
    if int(manifest.get("file_count", -1)) != len(rows):
        failures.append(f"{label}: legacy manifest file_count differs")
    listed: set[str] = set()
    root_prefix = f"{label}/"
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            failures.append(f"{label}: legacy manifest row {index} is not an object")
            continue
        relative = str(row.get("path", ""))
        expected = str(row.get("sha256", ""))
        if not relative.startswith(root_prefix):
            failures.append(f"{label}: legacy path escapes evidence root: {relative}")
            continue
        if relative in listed:
            failures.append(f"{label}: duplicate legacy path {relative}")
            continue
        listed.add(relative)
        path = ROOT / relative
        if not path.is_file():
            failures.append(f"{label}: legacy missing {relative}")
        elif sha256(path) != expected:
            failures.append(f"{label}: legacy hash drift {relative}")
    observed = {
        str(path.relative_to(ROOT))
        for path in root.rglob("*")
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and path.name != ".DS_Store"
    }
    unexpected = observed - listed
    if unexpected != allowed:
        failures.extend(
            f"{label}: legacy unlisted {relative}"
            for relative in sorted(unexpected - allowed)
        )
        failures.extend(
            f"{label}: declared legacy exception absent {relative}"
            for relative in sorted(allowed - unexpected)
        )
    return failures


def _git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def verify_sealed_git_tree(
    root: Path, commit: str, *, annotated_tag: str | None = None
) -> list[str]:
    """Prove that the current evidence tree is byte-identical to its seal commit."""

    label = display_path(root)
    failures: list[str] = []
    commit_check = _git(["cat-file", "-e", f"{commit}^{{commit}}"])
    if commit_check.returncode != 0:
        return [f"{label}: seal commit unavailable: {commit}"]
    if annotated_tag:
        resolved = _git(["rev-parse", f"{annotated_tag}^{{}}"])
        if resolved.returncode != 0 or resolved.stdout.strip() != commit:
            failures.append(
                f"{label}: annotated tag does not resolve to seal commit: {annotated_tag}"
            )
    tree = _git(["ls-tree", "-r", "--name-only", commit, "--", label])
    if tree.returncode != 0:
        return failures + [f"{label}: cannot read sealed git tree"]
    expected_paths = {row for row in tree.stdout.splitlines() if row}
    current_paths = {
        str(path.relative_to(ROOT))
        for path in root.rglob("*")
        if path.is_file() and not path.name.startswith("._") and path.name != ".DS_Store"
    }
    for relative in sorted(current_paths - expected_paths):
        failures.append(f"{label}: file added after seal {relative}")
    for relative in sorted(expected_paths - current_paths):
        failures.append(f"{label}: sealed file missing {relative}")
    diff = _git(["diff", "--quiet", commit, "--", label])
    if diff.returncode == 1:
        failures.append(f"{label}: tracked bytes or modes drifted after seal")
    elif diff.returncode != 0:
        failures.append(f"{label}: git diff against seal commit failed")
    return failures


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=PAPER_DIR,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def verify_paper_build() -> tuple[list[str], dict[str, Any], list[str]]:
    """Verify that the current PDF is a successful, current build of the TeX tree."""

    failures: list[str] = []
    warnings: list[str] = []
    info: dict[str, Any] = {}
    for required in (TEX, PAPER_PDF, PAPER_LOG, PAPER_FLS):
        if not required.is_file():
            failures.append(f"paper build artifact missing: {display_path(required)}")
    if failures:
        return failures, info, warnings

    log_text = PAPER_LOG.read_text(encoding="utf-8", errors="replace")
    fatal_patterns = {
        "undefined control sequence": r"Undefined control sequence",
        "undefined citation or reference": (
            r"LaTeX Warning:.*undefined|Citation .* undefined|Reference .* undefined|"
            r"There were undefined references"
        ),
        "multiply defined labels": r"multiply defined",
        "fatal TeX stop": r"Emergency stop|Fatal error|^!",
    }
    for label, pattern in fatal_patterns.items():
        if re.search(pattern, log_text, flags=re.IGNORECASE | re.MULTILINE):
            failures.append(f"paper compile log contains {label}")
    if not any(
        marker in log_text
        for marker in (
            "Output written on paper_main.xdv",
            "Output written on paper_main.pdf",
        )
    ):
        failures.append("paper compile log lacks successful XeLaTeX output marker")

    pdf_mtime = PAPER_PDF.stat().st_mtime_ns
    input_paths: set[Path] = set()
    for line in PAPER_FLS.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("INPUT "):
            continue
        raw = Path(line[6:])
        path = raw if raw.is_absolute() else PAPER_DIR / raw
        path = path.resolve()
        try:
            path.relative_to(PAPER_DIR.resolve())
        except ValueError:
            continue
        if path == PAPER_PDF.resolve():
            continue
        if path.suffix.lower() in {
            ".tex",
            ".cls",
            ".sty",
            ".pdf",
            ".png",
            ".jpg",
            ".jpeg",
            ".eps",
        }:
            input_paths.add(path)
    missing_inputs = sorted(str(path) for path in input_paths if not path.is_file())
    stale_inputs = sorted(
        str(path.relative_to(ROOT))
        for path in input_paths
        if path.is_file() and path.stat().st_mtime_ns > pdf_mtime
    )
    if missing_inputs:
        failures.append(f"paper build inputs missing: {missing_inputs}")
    if stale_inputs:
        failures.append(f"paper PDF is older than inputs: {stale_inputs}")

    pdfinfo = _run_command(["pdfinfo", str(PAPER_PDF)])
    if pdfinfo.returncode != 0:
        failures.append("pdfinfo could not read paper_main.pdf")
    else:
        page_match = re.search(r"(?m)^Pages:\s+(\d+)", pdfinfo.stdout)
        page_count = int(page_match.group(1)) if page_match else 0
        info["page_count"] = page_count
        # Closest SETP mother papers in the local evidence set span 16--24 A4
        # pages, so page count is a gross truncation guard, not a target length.
        if page_count < 15:
            failures.append(f"paper PDF unexpectedly short: {page_count} pages")
        if "Page size:       595.28 x 841.89 pts (A4)" not in pdfinfo.stdout:
            failures.append("paper PDF is not the expected A4 page size")

    extraction = _run_command(["pdftotext", "-layout", str(PAPER_PDF), "-"])
    if extraction.returncode != 0:
        failures.append("pdftotext could not extract the compiled manuscript")
    else:
        extracted_compact = re.sub(r"\s+", "", extraction.stdout)
        for forbidden in FORBIDDEN_PATH_GLYPHS:
            if forbidden in extracted_compact:
                failures.append(
                    f"compiled PDF uses forbidden path glyph or homophone: {forbidden}"
                )
        required_fragments = [
            CURRENT_TITLE_ZH,
            "TVCI-ALNS",
            "对区域—城际配送企业而言，使用电动车并不必然实现低碳配送",
            "组件累加并未带来单调的成本改善",
            "五档实验覆盖9个网络、2类责任和3个种子",
            "依据预测电网碳强度安排充电",
            "本文核算运营直接排放和购入电力间接排放",
        ]
        if all((TABLES / filename).is_file() for filename in E7_REQUIRED_PAPER_FILES):
            required_fragments.append(
                "本文同时记录每个重规划阶段的实际计算时间（wall-clock time）"
            )
        for fragment in required_fragments:
            if re.sub(r"\s+", "", fragment) not in extracted_compact:
                failures.append(f"compiled PDF text missing: {fragment}")

    fonts = _run_command(["pdffonts", str(PAPER_PDF)])
    if fonts.returncode == 0:
        font_names = {
            line.split()[0].split("+", 1)[-1]
            for line in fonts.stdout.splitlines()[2:]
            if line.split()
        }
        non_unicode_fonts = [
            line.split()[0].split("+", 1)[-1]
            for line in fonts.stdout.splitlines()[2:]
            if len(line.split()) >= 7 and line.split()[6] == "no"
        ]
        if non_unicode_fonts:
            warnings.append(
                "embedded fonts without ToUnicode mapping: "
                + ", ".join(sorted(set(non_unicode_fonts)))
            )
        forbidden_cjk_fallbacks = {
            name
            for name in font_names
            if "ArialUnicode" in name or "HiraginoSansGB" in name
        }
        if forbidden_cjk_fallbacks:
            failures.append(
                "forbidden Chinese fallback font is embedded: "
                + ", ".join(sorted(forbidden_cjk_fallbacks))
            )
        if not any("NotoSansCJKsc" in name or "SimHei" in name for name in font_names):
            failures.append("approved Chinese heading font is not embedded")
        info["non_unicode_font_count"] = len(set(non_unicode_fonts))
    else:
        warnings.append("pdffonts unavailable; font mapping was not inspected")

    info.update(
        {
            "input_file_count": len(input_paths),
            "tex_sha256": sha256(TEX),
            "pdf_sha256": sha256(PAPER_PDF),
            "log_sha256": sha256(PAPER_LOG),
        }
    )
    return failures, info, warnings


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def require(text: str, fragment: str, failures: list[str], label: str) -> None:
    if fragment not in text:
        failures.append(f"manuscript missing {label}: {fragment}")


def e7_generated_exhibit_failures(
    table_root: Path,
    expected_exhibits: dict[str, str],
    provenance: dict[str, Any],
) -> list[str]:
    """Require byte-for-byte reproduction and manifest hashes for all seven files."""

    failures: list[str] = []
    generated_hashes = provenance.get("generated_hashes", {})
    if not isinstance(generated_hashes, dict) or set(generated_hashes) != set(
        E7_EXHIBITS
    ):
        failures.append("E7 paper-evidence generated inventory differs")
    for filename, expected in expected_exhibits.items():
        path = table_root / filename
        if not path.is_file():
            failures.append(f"sealed E7 manuscript exhibit missing: {filename}")
            continue
        if path.read_text(encoding="utf-8") != expected:
            failures.append(f"sealed E7 exhibit does not reproduce: {filename}")
        if generated_hashes.get(filename) != sha256(path):
            failures.append(f"E7 paper-evidence exhibit hash differs: {filename}")
    return failures


def replay_invariant_decision_failures(decision: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if decision.get("status") != "PASS_E7_REPLAY_INVARIANTS_AUDIT":
        failures.append("E7 replay-invariants audit decision does not pass")
    for field, expected in E7_REPLAY_INVARIANT_COUNTS.items():
        try:
            observed = int(decision.get(field, -1))
        except (TypeError, ValueError):
            observed = -1
        if observed != expected:
            failures.append(f"E7 replay-invariants field differs: {field} != {expected}")
    return failures


def e6_endpoint_summary() -> dict[tuple[str, float], tuple[float, float]]:
    with (E6 / "selected_frontier.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    seed_groups: dict[tuple[str, str, float], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        alpha = float(row["alpha"])
        if alpha in {0.0, 1.0}:
            seed_groups[(row["instance"], row["condition"], alpha)].append(row)
    network_rows: dict[tuple[str, float], list[tuple[float, float]]] = defaultdict(list)
    for (_instance, condition, alpha), group in seed_groups.items():
        network_rows[(condition, alpha)].append(
            (
                statistics.fmean(float(row["cost_increment_pct"]) for row in group),
                statistics.fmean(
                    float(row["selected_minimum_profit_ratio"]) for row in group
                ),
            )
        )
    return {
        key: (
            statistics.fmean(row[0] for row in values),
            statistics.fmean(row[1] for row in values),
        )
        for key, values in network_rows.items()
    }


def audit(*, allow_pending_e7: bool) -> dict[str, Any]:
    failures: list[str] = []
    text = TEX.read_text(encoding="utf-8")
    if text.count("动态需求; 参与约束; 自适应大邻域搜索") < 1:
        failures.append("Chinese keywords omit dynamic demand")
    if "dynamic demand; participation constraints;" not in text:
        failures.append("English keywords omit dynamic demand")
    for forbidden in FORBIDDEN_PATH_GLYPHS:
        if forbidden in text:
            failures.append(
                f"manuscript uses forbidden path glyph or homophone: {forbidden}"
            )
    introduction_start = text.find(r"\section{引言}")
    introduction_end = text.find(r"\section{模型建立}", introduction_start)
    if introduction_start < 0 or introduction_end < 0:
        failures.append("manuscript introduction boundary is missing")
    else:
        introduction = text[introduction_start:introduction_end]
        introduction_citations = re.findall(r"\\cite\{([^}]*)\}", introduction)
        if any("," in keys for keys in introduction_citations):
            failures.append("introduction contains a multi-key citation command")
        for sentence in re.split(r"[。！？；\n]+", introduction):
            if sentence.count(r"\cite{") > 1:
                failures.append(
                    "introduction contains more than one citation in a sentence or semicolon unit"
                )
                break
        first_citations = list(dict.fromkeys(introduction_citations))
        bibliography_keys = re.findall(r"\\bibitem\{([^}]*)\}", text)
        if bibliography_keys[: len(first_citations)] != first_citations:
            failures.append(
                "introduction first-citation order differs from bibliography numbering"
            )
    v13_heading = r"\subsubsection{V13大型多车场带时间窗算例实验}"
    v13_following_heading = r"\subsubsection{本文模型实验}"
    v13_start = text.find(v13_heading)
    v13_end = text.find(v13_following_heading, v13_start)
    if v13_start < 0 or v13_end < 0:
        failures.append("manuscript V13 benchmark section boundary is missing")
    else:
        v13_section = text[v13_start:v13_end]
        for forbidden in E2_V13_MAIN_TABLE_FORBIDDEN_TERMS:
            if forbidden in v13_section:
                failures.append(
                    f"manuscript V13 main table uses forbidden term: {forbidden}"
                )
        for required in E2_V13_MAIN_TABLE_REQUIRED_TERMS:
            if required not in v13_section:
                failures.append(
                    f"manuscript V13 main table misses required term: {required}"
                )
    quality_text = QUALITY_GATES.read_text(encoding="utf-8")
    completion_text = COMPLETION_MATRIX.read_text(encoding="utf-8")
    paper_build_failures, paper_build_info, paper_build_warnings = verify_paper_build()
    failures.extend(paper_build_failures)

    sealed_e1_e2_failures: list[str] = []
    sealed_e1_e2_failures.extend(verify_legacy_manifest(E1))
    sealed_e1_e2_failures.extend(
        verify_sealed_git_tree(E1, E1_SEAL_COMMIT)
    )
    sealed_e1_e2_failures.extend(
        verify_legacy_manifest(E2, allowed_unlisted=E2_LEGACY_UNLISTED)
    )
    sealed_e1_e2_failures.extend(
        verify_sealed_git_tree(E2, E2_SEAL_COMMIT, annotated_tag=E2_SEAL_TAG)
    )
    failures.extend(sealed_e1_e2_failures)

    forbidden_appendix = re.search(
        r"\\appendix\b|\\begin\{appendix(?:es)?\}|\\section\{附录\}", text
    )
    if forbidden_appendix:
        failures.append("manuscript contains an appendix despite the no-appendix contract")
    # The two closest SETP mother papers use the concise reader-facing labels
    # “问题与模型/模型建立” and “算法设计”.  The invariant is the five-part
    # sequence, not the older draft's verbose wording.
    expected_sections = ["引言", "模型建立", "算法设计", "数值试验", "结论"]
    observed_sections = re.findall(r"(?m)^\\section\{([^}]+)\}", text)
    if observed_sections != expected_sections:
        failures.append(
            f"manuscript section sequence differs: {observed_sections}"
        )

    require(
        text,
        "对区域—城际配送企业而言，使用电动车并不必然实现低碳配送",
        failures,
        "problem-first introduction",
    )
    require(
        text,
        rf"\Title{{{CURRENT_TITLE_ZH}}}",
        failures,
        "unified Chinese title",
    )
    require(
        text,
        rf"\ETitle{{{CURRENT_TITLE_EN}}}",
        failures,
        "unified English title",
    )
    require(
        text,
        "跨场降本、成员参与和低碳充电三者相互牵制",
        failures,
        "single operating problem",
    )
    require(
        text,
        "结果表明，充电择时是路径与车型减排的补充",
        failures,
        "abstract claim stays within sealed evidence",
    )
    if re.search(r"张[^，。；\n]{0,6}网络", text):
        failures.append("manuscript still uses 张 as the network quantifier")
    if "Cheng A J, Tarroja B, Shaffer B, Samuelsen S" in text or "ref:24" in text:
        failures.append("manuscript restored the invalid EPSR 208:107847 carbon-aware charging citation")
    for fragment in (
        "A branch-and-price algorithm for electric vehicle routing problem with time windows and mixed fleet",
        "Multi-depot mixed fleet routing and speed optimization under a carbon trading mechanism",
        "Electric truck route planning considering multiple charging pile queues and time windows",
        "A periodic optimization model and solution for capacitated vehicle routing problem with dynamic requests",
        "Multi-vehicle dynamic vehicle routing optimization in green logistics distribution",
        "Improved ant colony optimization algorithm for solving vehicle routing problem with soft time windows",
        "Research on vehicle routing problem considering truck-UAV cooperative distribution mode",
        "Multi-constraint vehicle routing problem with variable fleets",
    ):
        require(
            text,
            fragment,
            failures,
            "official English form for a Chinese journal reference",
        )
    require(
        text,
        "DOI: 10.1016/j.trd.2024.104383",
        failures,
        "verified orderly-charging reference metadata",
    )
    contribution_match = re.search(r"针对上述不足，本文.*?主要工作如下：(.*?)\n", text)
    contribution = contribution_match.group(1) if contribution_match else ""
    if not contribution or not all(marker in contribution for marker in ("1)", "2)", "3)")):
        failures.append("manuscript contribution paragraph could not be parsed as three items")
    if "；4)" in contribution or "4)" in contribution:
        failures.append("manuscript contribution paragraph still contains four competing items")
    for fragment in (
        "重要运营问题 → 可被结果否定的主张 → 必要模型与算法 → 有解释力的对照证据 → 适用边界",
        "结果方向不得作为扩跑、删流、换实例或放宽预算的门槛",
        "现象—数量—机制—边界",
        "不把“算法必须显著最好”设为论文成立条件",
    ):
        require(quality_text, fragment, failures, "ReSETP research-writing quality gate")
    for fragment in (
        "要求—证据矩阵",
        "E7小中大三网络×两责任×五流×四臂",
        "hooks事件后的唯一收口顺序",
        "不得把预检结果替代正式结果",
        "只有全部命令各自成功且矩阵所有项均已证明",
    ):
        require(completion_text, fragment, failures, "ReSETP goal-completion matrix")

    for evidence in (E2B, E3, E4, E6, PUBLIC_ADAPTER):
        failures.extend(required_surface_failures(evidence))
    for evidence in (E2B, E3, E6, PUBLIC_ADAPTER):
        failures.extend(verify_manifest(evidence))
    failures.extend(e2b_identity_failures(E2B))
    failures.extend(e3_identity_failures(E3))
    failures.extend(global_hash_manifest_failures(E4 / "artifact_hashes.json", expected_count=262))
    failures.extend(e4_identity_failures(E4))
    failures.extend(e6_identity_failures(E6))

    for fragment in (
        "充电环节排放下降3.888\\%--4.877\\%",
        "运营总排放下降0.352\\%--0.523\\%",
        "按电网日仅有18--20日改善",
        "各情境95.46\\%--99.71\\%的净减排来自前一日首趟充电窗口",
        "现有证据不支持“协同稳定放大充电择时收益”的一般结论",
    ):
        require(text, fragment, failures, "E4 time-varying carbon evidence boundary")

    e1 = read_json(E1 / "decision.json")
    if (
        e1.get("verdict") != "E1_280_STRUCTURE_SUPPORTED"
        or int(e1.get("mixed_rows", -1)) != 20
        or int(e1.get("cv_only_ok", -1)) != 5
        or int(e1.get("ev_only_not_found", -1)) != 5
    ):
        failures.append("E1 sealed decision differs from the accepted structure gate")

    e2 = read_json(E2 / "decision.json")
    if (
        e2.get("verdict") != "E2_10SEED_PRIMARY_LEAD_SUPPORTED"
        or int(e2.get("matrix_rows", -1)) != 810
        or int(e2.get("algorithms", -1)) != 9
        or int(e2.get("instances", -1)) != 9
        or int(e2.get("eval_budget", -1)) != 4000
        or int(e2.get("zero_violation_rows", -1)) != 810
        or int(e2.get("recalculation_ok_rows", -1)) != 810
    ):
        failures.append("E2 sealed decision differs from the accepted 810-row benchmark")
    require(
        text,
        f"TVCI-ALNS平均名次为{float(e2['primary_mean_rank']):.2f}",
        failures,
        "E2 primary mean rank",
    )
    require(
        text,
        "现有证据支持其总体竞争力和相对5种对照的优势，尚不足以说明其全面优于所有算法",
        failures,
        "E2 restrained comparison claim",
    )
    require(
        text,
        "自适应大邻域搜索（adaptive large neighborhood search，ALNS）",
        failures,
        "ALNS definition at first manuscript use",
    )
    require(
        text,
        "时变碳强度（time-varying carbon intensity，TVCI）",
        failures,
        "TVCI definition at first manuscript use",
    )
    require(
        text,
        "下述参数均在算法比较前确定",
        failures,
        "adapted-comparator parameter provenance boundary",
    )
    require(
        text,
        "GA取Narayanan等文中的遗传算法对照",
        failures,
        "GA comparator source role",
    )
    require(
        text,
        "GA-VNS在该解码框架下组合GA的全局搜索与VNS局部改进",
        failures,
        "adapted-comparator provenance boundary",
    )
    require(
        text,
        "统一评价函数核算成本，并检查实体车排班、时间窗、载重、电量和充电约束",
        failures,
        "shared comparator evaluation contract",
    )
    require(
        text,
        "种群规模不同会使实际完成的代数不同，比较预算仍按完整方案评价次数控制",
        failures,
        "population-method budget comparability boundary",
    )
    public_adapter = read_json(PUBLIC_ADAPTER / "decision.json")
    if (
        public_adapter.get("decision") != "PASS_THREE_INSTANCE_SEMANTIC_ADAPTER_GATE"
        or not public_adapter.get("semantic_adapter_ready")
        or public_adapter.get("formal_180x10_authorized") is not False
    ):
        failures.append("public Goeke three-instance semantic adapter gate differs from the accepted boundary")
    for fragment in (
        "E-UK10\\_01和E-UK15\\_01的复算距离分别为408.130 km和709.005 km",
        "E-UK20\\_01得到847.900 km的可行方案，高于原文10次ALNS最好值785.47 km",
        "原文比较值仅作复算参照，不作为最优值",
    ):
        require(text, fragment, failures, "public benchmark semantic-adapter boundary")
    require(
        text,
        "每条路径对应一个配送趟，固定费按配送趟数计取",
        failures,
        "trip-dispatch fixed-cost implementation semantics",
    )
    require(
        text,
        "表 \\ref{tab:e2-summary} 给出8种通过实现核查的算法总体性能",
        failures,
        "E2 manuscript valid-comparator boundary",
    )
    if "IWD" in text:
        failures.append(
            "E2 manuscript must exclude IWD after its implementation-validity gate failed; "
            "the sealed nine-algorithm evidence remains unchanged"
        )

    e2b = read_json(E2B / "decision.json")
    if e2b.get("verdict") != "E2B_FORMAL_EVIDENCE_READY" or not e2b.get(
        "formal_inference_allowed"
    ):
        failures.append("E2b formal decision is not inference-ready")
    ba = e2b["paired_summary"]["B_minus_A_total_cost"]
    cb = e2b["paired_summary"]["C_minus_B_total_cost"]
    dc = e2b["paired_summary"]["D_minus_C_ev_indirect"]
    require(
        text,
        f"B相对A平均成本增加£{float(ba['mean_delta']):.2f}",
        failures,
        "negative staged-search result",
    )
    require(
        text,
        f"{ba['right_better']}个改善、{ba['right_worse']}个变差、{ba['ties']}个持平",
        failures,
        "staged-search sign counts",
    )
    require(
        text,
        f"C相对B平均成本降低£{abs(float(cb['mean_delta'])):.2f}",
        failures,
        "cross-depot operator result",
    )
    require(
        text,
        f"{cb['right_better']}个单元改善、{cb['right_worse']}个变差、{cb['ties']}个持平",
        failures,
        "cross-depot operator sign counts",
    )
    require(
        text,
        f"平均下降{abs(float(dc['mean_delta'])):.3f} kg",
        failures,
        "charging-timing emissions result",
    )
    require(
        text,
        "分阶段搜索本身未形成稳定增益",
        failures,
        "E2b claim boundary",
    )

    e3 = read_json(E3 / "decision.json")
    if e3.get("status") != "FORMAL_COMPLETE" or not e3.get(
        "trend_inference_allowed"
    ):
        failures.append("E3 medium formal decision does not allow trend inference")
    require(
        text,
        (
            f"平均协同节省分别为{float(e3['old_geographic_observed_mean_saving_pct']):.2f}\\%、"
            f"{float(e3['medium_selected_network_mean_saving_pct']):.2f}\\%和"
            f"{float(e3['old_mixed_observed_mean_saving_pct']):.2f}\\%"
        ),
        failures,
        "E3 three-level means",
    )
    require(
        text,
        f"只有{e3['raw_strictly_monotone_networks']}/9个网络严格逐档增加",
        failures,
        "E3 non-monotonic boundary",
    )
    require(
        text,
        "不支持把它写成每个网络都严格单调",
        failures,
        "E3 interpretation boundary",
    )

    e6 = read_json(E6 / "decision.json")
    if e6.get("status") != "PASS_E6_PROFIT_GUARANTEE_FRONTIER" or not e6.get(
        "formal_complete"
    ):
        failures.append("E6 frontier decision is incomplete")
    endpoints = e6_endpoint_summary()
    geo0 = endpoints[("geographic", 0.0)]
    geo1 = endpoints[("geographic", 1.0)]
    mixed0 = endpoints[("mixed", 0.0)]
    mixed1 = endpoints[("mixed", 1.0)]
    require(
        text,
        f"地理聚集情形的最低收益比从{geo0[1]:.3f}提高到{geo1[1]:.3f}",
        failures,
        "E6 geographic profit ratios",
    )
    require(
        text,
        f"平均系统成本增幅从0增加到{geo1[0]:.2f}\\%",
        failures,
        "E6 geographic endpoint cost",
    )
    require(
        text,
        f"空间交错情形的无约束方案平均最低收益比已经为{mixed0[1]:.3f}",
        failures,
        "E6 mixed unrestricted ratio",
    )
    require(
        text,
        f"保障推进到1时平均成本增幅仅为{mixed1[0]:.2f}\\%",
        failures,
        "E6 mixed endpoint cost",
    )
    require(
        text,
        "曲线无需逐档严格上升",
        failures,
        "E6 non-strict frontier boundary",
    )

    e2_preamble = text.split(r"\begin{document}", maxsplit=1)[0]
    for filename in E2_PUBLIC_EXHIBITS:
        require(
            e2_preamble,
            rf"\IfFileExists{{generated_tables/{filename}}}",
            failures,
            f"atomic E2 public benchmark input {filename}",
        )
    if e2_preamble.count(r"\IfFileExists{generated_tables/e2_v13_mdvrptw_") != len(
        E2_PUBLIC_EXHIBITS
    ):
        failures.append("atomic E2 public benchmark gate is not exact")
    for filename in E2_PUBLIC_GENERATED_EXHIBITS:
        require(
            text,
            f"generated_tables/{filename}",
            failures,
            f"E2 public benchmark hook {filename}",
        )
    require(
        text,
        r"\newif\ifETwoPublicReady",
        failures,
        "atomic E2 public benchmark gate",
    )
    e2_public_ready = all(
        (E2_PUBLIC / filename).is_file()
        for filename in E2_PUBLIC_REQUIRED_SOURCE_FILES
    )
    if not e2_public_ready:
        if not allow_pending_e7:
            failures.append("E2 public BKS formal evidence is not sealed")
        if any((TABLES / filename).is_file() for filename in E2_PUBLIC_EXHIBITS):
            failures.append(
                "E2 public benchmark manuscript exhibit exists before formal evidence is sealed"
            )
    else:
        missing_exhibits = [
            filename for filename in E2_PUBLIC_EXHIBITS if not (TABLES / filename).is_file()
        ]
        if missing_exhibits:
            failures.append(
                "sealed E2 V13 benchmark exhibits missing: " + ", ".join(missing_exhibits)
            )
        else:
            failures.append(
                "E2 V13 formal evidence exists but its dedicated paper builder "
                "and reproduction audit are not yet implemented"
            )

    for filename in E7_REQUIRED_PAPER_FILES:
        require(
            text,
            f"generated_tables/{filename}",
            failures,
            f"E7 table hook {filename}",
        )
    require(
        text,
        "阶段计算时间不超过下一触发间隔时，记为满足实时响应条件",
        failures,
        "dynamic response-time criterion",
    )
    require(
        text,
        "批量滚动决策支持",
        failures,
        "non-realtime terminology boundary",
    )
    require(
        text,
        "选取N114、N221和N322三个网络，分别由50、100和150客户的基础算例按三班时域展开",
        failures,
        "dynamic network label and expanded customer-count boundary",
    )

    e7_ready = all(
        (root / "decision.json").is_file()
        for root in (E7_FORMAL, E7_REPLAY, E7_REPLAY_INVARIANTS, E7_AUDIT)
    )
    if not e7_ready:
        if not allow_pending_e7:
            failures.append(
                "E7 formal/replay/replay-invariants/independent-audit decisions are not all sealed"
            )
        if any((TABLES / filename).is_file() for filename in E7_REQUIRED_PAPER_FILES):
            failures.append("E7 manuscript exhibit exists before all E7 decisions are sealed")
    else:
        for evidence in (E7_FORMAL, E7_REPLAY, E7_REPLAY_INVARIANTS, E7_AUDIT):
            failures.extend(required_surface_failures(evidence))
            failures.extend(verify_manifest(evidence))
        failures.extend(final_record_failures())
        formal = read_json(E7_FORMAL / "decision.json")
        replay = read_json(E7_REPLAY / "decision.json")
        replay_invariants = read_json(E7_REPLAY_INVARIANTS / "decision.json")
        independent = read_json(E7_AUDIT / "decision.json")
        if formal.get("verdict") not in {
            "E7_FORMAL_EVIDENCE_COMPLETE",
            "E7_FORMAL_EVIDENCE_COMPLETE_WITH_ARM_FAILURES",
        } or formal.get("failures"):
            failures.append("E7 formal decision is not complete")
        if replay.get("status") != "PASS_E7_28DAY_ZERO_SEARCH_CHARGING_REPLAY":
            failures.append("E7 28-day replay decision does not pass")
        failures.extend(replay_invariant_decision_failures(replay_invariants))
        if (
            independent.get("verdict")
            != "PASS_E7_MULTINETWORK_FORMAL_AND_REPLAY_INDEPENDENT_AUDIT"
        ):
            failures.append("E7 independent audit decision does not pass")
        independent_checks = independent.get("checks", {})
        for field in E7_REQUIRED_INDEPENDENT_CHECKS:
            if independent_checks.get(field) is not True:
                failures.append(f"E7 independent audit did not enforce {field}")
        for filename in E7_REQUIRED_PAPER_FILES:
            if not (TABLES / filename).is_file():
                failures.append(f"sealed E7 manuscript exhibit missing: {filename}")
        dynamic_text = ""
        try:
            pair_frame, task_frame, paired_frame, replay_frame, source_decision = (
                evidence_builder.load_e7_evidence(E7_AUDIT, E7_REPLAY)
            )
            expected_exhibits = evidence_builder.render_e7_bundle(
                pair_frame,
                task_frame,
                paired_frame,
                replay_frame,
                source_decision,
            )
            provenance = read_json(TABLES / E7_PROVENANCE)
            expected_source_roots = {
                "independent_audit": evidence_builder.source_root_label(E7_AUDIT),
                "28day_replay": evidence_builder.source_root_label(E7_REPLAY),
            }
            if provenance.get("schema_version") != "resetp.e7.paper-evidence.v1":
                failures.append("E7 paper-evidence manifest schema differs")
            if provenance.get("source_roots") != expected_source_roots:
                failures.append("E7 paper-evidence source roots differ")
            if provenance.get("source_hashes") != evidence_builder.e7_source_hashes(
                E7_AUDIT, E7_REPLAY
            ):
                failures.append("E7 paper-evidence source hashes differ")
            if provenance.get("builder_sha256") != sha256(
                Path(evidence_builder.__file__).resolve()
            ):
                failures.append("E7 paper-evidence builder hash differs")
            if provenance.get("coverage") != {
                "formal_tasks": 120,
                "stream_pairs": 30,
                "network_condition_cells": 6,
                "replay_pairs": 840,
                "reader_facing_exhibits": 7,
            }:
                failures.append("E7 paper-evidence coverage declaration differs")
            if "cross-site stream counts" not in str(
                provenance.get("reconstruction_boundary", "")
            ):
                failures.append("E7 paper-evidence reconstruction boundary is missing")
            failures.extend(
                e7_generated_exhibit_failures(TABLES, expected_exhibits, provenance)
            )
            dynamic_text = (
                expected_exhibits[evidence_builder.E7_INTERPRETATION_NAME]
                + expected_exhibits[evidence_builder.E7_CONCLUSION_NAME]
            )
        except Exception as exc:
            failures.append(f"E7 paper-evidence reproduction failed: {exc}")
        controlled = formal.get("controlled_arm_failures", [])
        if int(independent.get("controlled_arm_failure_count", -1)) != len(controlled):
            failures.append("E7 formal and independent controlled-failure counts disagree")
        if controlled:
            require(
                dynamic_text,
                f"{len(controlled)}个受控不可执行单元",
                failures,
                "controlled E7 arm failures",
            )
        with (E7_AUDIT / "paired_summary.csv").open(
            newline="", encoding="utf-8"
        ) as handle:
            paired = list(csv.DictReader(handle))
        deadline_misses = sum(
            int(row["full_stage_deadline_miss_count"]) for row in paired
        )
        if deadline_misses:
            require(
                dynamic_text,
                f"{deadline_misses}个阶段超过下一触发间隔",
                failures,
                "E7 deadline misses",
            )
        else:
            require(
                dynamic_text,
                "全部可比较阶段均满足实时响应条件",
                failures,
                "E7 realtime result",
            )

    checks = {
        "e1_e2_sealed_and_undrifted": not sealed_e1_e2_failures,
        "no_appendix_and_setp_section_sequence": not forbidden_appendix
        and observed_sections == expected_sections,
        "paper_build_current_and_content_extractable": not paper_build_failures,
        "paper_build_info": paper_build_info,
        "paper_build_warnings": paper_build_warnings,
        "e2_public_bks_ready": e2_public_ready,
        "e2b_manifest_and_claims": not any("E2b" in row or "e2_alns" in row for row in failures),
        "e3_manifest_and_claims": not any("E3" in row or "e3_ablation" in row for row in failures),
        "e4_manifest_and_claims": not any("E4" in row or "e4_e5" in row for row in failures),
        "e6_manifest_and_claims": not any("E6" in row or "e6_fairness" in row for row in failures),
        "e7_ready": e7_ready,
        "required_experiment_surfaces": not any(
            "required experiment surface missing" in row for row in failures
        ),
        "final_records_updated": e7_ready and not any(
            "final record" in row for row in failures
        ),
        "pending_e7_allowed": allow_pending_e7,
        "manuscript_path": str(TEX.relative_to(ROOT)),
    }
    return {
        "status": "PASS" if not failures else "FAIL",
        "mode": "pending_e7" if allow_pending_e7 else "final",
        "checks": checks,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-pending-e7", action="store_true")
    args = parser.parse_args()
    result = audit(allow_pending_e7=args.allow_pending_e7)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
