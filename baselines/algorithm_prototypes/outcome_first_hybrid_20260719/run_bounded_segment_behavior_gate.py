#!/usr/bin/env python3
"""Zero-search behavior, attribution, and accounting gate for SEG-GEN-02."""

from __future__ import annotations

import csv
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
UNIFIED = (
    REPO
    / "baselines/algorithm_prototypes/unified_mechanism_alns_20260719"
)
LEGACY = (
    REPO
    / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
)
for path in (
    REPO / "solver/src",
    REPO / "models/src",
    HERE,
    UNIFIED,
    LEGACY,
    REPO,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from bounded_segment_generator import (  # noqa: E402
    BoundedSegmentGeneratorConfig,
    propose_bounded_segment_move,
)
from initial_pool import solution_signature_hash  # noqa: E402
from prototype import independent_cost  # noqa: E402
from setp_solver.algorithms.resetp_alns.support.construction import (  # noqa: E402
    build_initial_solution,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.profit import infer_customer_home_depots  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.search.evaluation import (  # noqa: E402
    EvalBudget,
    EvaluationContext,
)
from v7_responsibility_solver import (  # noqa: E402
    annotate_cross_site_services,
)


OUT = HERE / "bounded_segment_behavior_gate_v3_china81_scope"
DONOR_ROOT = (
    REPO
    / "baselines/algorithm_prototypes/algo_reset_20260719/"
    "fresh_donor02_mechanism_bundles"
)
BINDING = (
    DONOR_ROOT / "DEV-fullsource-donor02-25c",
    DONOR_ROOT / "DEV-fullsource-donor02-50c",
)
NONBINDING = (
    REPO
    / "models/data_bundle/generated_instances/"
    "L-main_mixed23_archive_20260709/"
    "L-main-vanilla-100c-01"
)
PRICES = replace(DEFAULT_PRICES, B_battery_kwh=280.0)
PROTECTED = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
    REPO
    / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
    UNIFIED / "mechanism_segment_generator.py",
)
SOURCES = (
    Path(__file__).resolve(),
    HERE / "bounded_segment_generator.py",
    HERE / "bounded_segment_generation_alns.py",
    HERE / "test_bounded_segment_generator.py",
    REPO
    / "docs/handoff/outcome_first_multiengine_hybrid_contract_20260719.md",
)


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite: {OUT}")
    source_hashes = _hash_map(SOURCES)
    protected_hashes = _hash_map(PROTECTED)
    input_hashes = _input_hashes((*BINDING, NONBINDING))
    rows: list[dict[str, Any]] = []
    witnesses: dict[str, Any] = {}

    for bundle_dir in BINDING:
        bundle, owners, source, context = _fixture(bundle_dir)
        source_cost = independent_cost(bundle_dir, source, PRICES)
        witnesses[bundle_dir.name] = {
            "source_signature": solution_signature_hash(source),
            "source_cost": float(source_cost),
            "arms": {},
        }
        for mode in ("mechanism", "distance"):
            candidate, activity = propose_bounded_segment_move(
                source,
                context,
                owners,
                config=BoundedSegmentGeneratorConfig(mode=mode),
            )
            candidate_cost = (
                None
                if candidate is None
                else independent_cost(bundle_dir, candidate, PRICES)
            )
            violations = (
                []
                if candidate is None
                else check_solution(candidate, bundle.instance, PRICES)
            )
            ledger = dict(activity["ledger"])
            selected = activity.get("selected")
            row = {
                "case": bundle_dir.name,
                "binding": True,
                "mode": mode,
                "source_cost": float(source_cost),
                "candidate_present": candidate is not None,
                "candidate_cost": candidate_cost,
                "feasible": not violations,
                "selected_distance_delta": (
                    None
                    if selected is None
                    else selected["distance_delta"]
                ),
                "selected_local_model_delta": (
                    None
                    if selected is None
                    else selected["local_model_delta"]
                ),
                "source_shortlist": int(
                    ledger["source_segments_shortlisted"]
                ),
                "max_positions_per_source": int(
                    ledger["maximum_positions_for_one_source"]
                ),
                "candidate_build_attempts": int(
                    ledger["candidate_build_attempts"]
                ),
                "exact_shortlist": int(
                    ledger["exact_candidates_shortlisted"]
                ),
                "completion_shortlist": int(
                    ledger["completion_candidates_screened"]
                ),
                "complete_candidate_evaluations": int(
                    ledger[
                        "complete_candidate_evaluations_before_submission"
                    ]
                ),
                "activity_json": json.dumps(
                    activity,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
            rows.append(row)
            witnesses[bundle_dir.name]["arms"][mode] = {
                "candidate_signature": (
                    None
                    if candidate is None
                    else solution_signature_hash(candidate)
                ),
                "candidate_cost": candidate_cost,
                "activity": activity,
            }

    bundle, owners, source, context = _fixture(NONBINDING)
    candidate, activity = propose_bounded_segment_move(
        source,
        context,
        owners,
        config=BoundedSegmentGeneratorConfig(),
    )
    rows.append(
        {
            "case": NONBINDING.name,
            "binding": False,
            "mode": "mechanism",
            "source_cost": independent_cost(
                NONBINDING,
                source,
                PRICES,
            ),
            "candidate_present": candidate is not None,
            "candidate_cost": None,
            "feasible": candidate is None,
            "selected_distance_delta": None,
            "selected_local_model_delta": None,
            "source_shortlist": int(
                activity["ledger"]["source_segments_shortlisted"]
            ),
            "max_positions_per_source": int(
                activity["ledger"]["maximum_positions_for_one_source"]
            ),
            "candidate_build_attempts": int(
                activity["ledger"]["candidate_build_attempts"]
            ),
            "exact_shortlist": int(
                activity["ledger"]["exact_candidates_shortlisted"]
            ),
            "completion_shortlist": int(
                activity["ledger"]["completion_candidates_screened"]
            ),
            "complete_candidate_evaluations": int(
                activity["ledger"][
                    "complete_candidate_evaluations_before_submission"
                ]
            ),
            "activity_json": json.dumps(
                activity,
                ensure_ascii=False,
                sort_keys=True,
            ),
        }
    )
    witnesses[NONBINDING.name] = {
        "source_signature": solution_signature_hash(source),
        "candidate_present": candidate is not None,
        "activity": activity,
    }

    checks = _checks(rows)
    drift = {
        "sources_unchanged": source_hashes == _hash_map(SOURCES),
        "protected_unchanged": (
            protected_hashes == _hash_map(PROTECTED)
        ),
        "inputs_unchanged": (
            input_hashes
            == _input_hashes((*BINDING, NONBINDING))
        ),
    }
    passed = all(checks.values()) and all(drift.values())
    decision = {
        "verdict": (
            "PASS_SEG_GEN_02_BEHAVIOR"
            if passed
            else "STOP_SEG_GEN_02_BEHAVIOR"
        ),
        "passed": bool(passed),
        "checks": checks,
        "drift_checks": drift,
        "formal_search_allowed": False,
        "stage2_allowed": False,
        "next_allowed_step": (
            "await_china81_physical_and_search_gate"
            if passed
            else "freeze_SEG_GEN_02"
        ),
    }
    metadata = {
        "schema_version": "resetp.seg-gen-02.behavior.v3",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git("rev-parse", "HEAD"),
        "git_status_short": _git("status", "--short"),
        "binding_cases": [
            str(path.relative_to(REPO)) for path in BINDING
        ],
        "nonbinding_case": str(NONBINDING.relative_to(REPO)),
        "prices": asdict(PRICES),
        "config": asdict(BoundedSegmentGeneratorConfig()),
        "complete_search_candidate_evaluations": 0,
        "source_hashes": source_hashes,
        "protected_hashes": protected_hashes,
        "input_hashes": input_hashes,
        "claim_boundary": (
            "Zero-search behavior and accounting evidence only; "
            "not performance or manuscript evidence. Private performance "
            "is restricted to China81 after its physical/search gate."
        ),
    }

    OUT.mkdir(parents=True)
    _write_csv(OUT / "raw_runs.csv", rows)
    _write_json(OUT / "solution_witnesses.json", witnesses)
    _write_json(OUT / "metadata.json", metadata)
    _write_json(OUT / "decision.json", decision)
    _write_text(OUT / "report.md", _report(rows, decision))
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
    return 0 if passed else 1


def _fixture(bundle_dir: Path):
    bundle = load_search_bundle(bundle_dir)
    owners = infer_customer_home_depots(bundle.instance)
    source = build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        PRICES,
        introduce_ev=False,
        require_charging_signal=False,
    )
    source = annotate_cross_site_services(source, owners)
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=PRICES,
        budget=EvalBudget(limit=0, target=0),
        customer_home_depot=owners,
        allow_cross_depot=True,
    )
    return bundle, owners, source, context


def _checks(rows: list[dict[str, Any]]) -> dict[str, bool]:
    binding_mechanism = [
        row
        for row in rows
        if row["binding"] and row["mode"] == "mechanism"
    ]
    nonbinding = [row for row in rows if not row["binding"]]
    return {
        "mechanism_candidate_on_all_binding_cases": all(
            bool(row["candidate_present"])
            for row in binding_mechanism
        ),
        "all_candidates_feasible": all(
            bool(row["feasible"]) for row in rows
        ),
        "at_least_one_distance_worse_model_better_selection": any(
            row["selected_distance_delta"] is not None
            and float(row["selected_distance_delta"]) > 0.0
            and row["selected_local_model_delta"] is not None
            and float(row["selected_local_model_delta"]) < 0.0
            for row in binding_mechanism
        ),
        "source_bound_respected": all(
            int(row["source_shortlist"]) <= 64 for row in rows
        ),
        "position_bound_respected": all(
            int(row["max_positions_per_source"]) <= 6
            for row in rows
        ),
        "candidate_build_bound_respected": all(
            int(row["candidate_build_attempts"]) <= 64 * 6
            for row in rows
        ),
        "local_exact_bound_respected": all(
            int(row["exact_shortlist"]) <= 48 for row in rows
        ),
        "completion_bound_respected": all(
            int(row["completion_shortlist"]) <= 12 for row in rows
        ),
        "zero_hidden_complete_evaluations": all(
            int(row["complete_candidate_evaluations"]) == 0
            for row in rows
        ),
        "single_depot_exact_noop": all(
            not bool(row["candidate_present"])
            and int(row["candidate_build_attempts"]) == 0
            for row in nonbinding
        ),
    }


def _report(
    rows: list[dict[str, Any]],
    decision: dict[str, Any],
) -> str:
    lines = [
        "# SEG-GEN-02 零搜索行为门",
        "",
        f"- 判决：`{decision['verdict']}`",
        "- 边界：只证明候选活性、上限和记账，不证明搜索性能。",
        "",
        "|题|臂|候选|源段上限|每段位置|建候选|局部精算|联合完成|",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"|{row['case']}|{row['mode']}|"
            f"{int(bool(row['candidate_present']))}|"
            f"{row['source_shortlist']}|"
            f"{row['max_positions_per_source']}|"
            f"{row['candidate_build_attempts']}|"
            f"{row['exact_shortlist']}|"
            f"{row['completion_shortlist']}|"
        )
    lines.extend(
        [
            "",
            "所有完整候选偷算为0；旧 SEG-GEN-01、共同成本、检查器、"
            "评价边界和 winner 内核哈希在运行前后保持不变。",
            "",
        ]
    )
    return "\n".join(lines)


def _input_hashes(paths: tuple[Path, ...]) -> dict[str, str]:
    return {
        str(path.relative_to(REPO)): _sha(path)
        for root in paths
        for path in sorted(root.iterdir())
        if path.is_file() and not path.name.startswith("._")
    }


def _hash_map(paths: tuple[Path, ...]) -> dict[str, str]:
    return {
        str(path.relative_to(REPO)): _sha(path)
        for path in paths
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buffer.getvalue(), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=REPO,
        text=True,
    ).strip()


if __name__ == "__main__":
    raise SystemExit(main())
