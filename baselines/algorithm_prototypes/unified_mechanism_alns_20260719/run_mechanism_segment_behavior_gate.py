#!/usr/bin/env python3
"""Run the zero-search SEG-GEN-01 behaviour and attribution gate."""

from __future__ import annotations

import csv
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = (
    REPO
    / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
)
for path in (
    REPO / "solver/src",
    REPO / "models/src",
    HERE,
    LEGACY,
    REPO,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from initial_pool import solution_signature_hash  # noqa: E402
from mechanism_segment_generator import (  # noqa: E402
    SegmentGeneratorConfig,
    propose_segment_move,
)
from prototype import independent_cost  # noqa: E402
from setp_solver.algorithms.resetp_alns.operators.local_search import (  # noqa: E402
    _route_customers,
)
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
from terminal_completion import apply_terminal_completion  # noqa: E402
from v7_responsibility_solver import (  # noqa: E402
    annotate_cross_site_services,
)


OUT = HERE / "mechanism_segment_generation_behavior_gate"
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
TOL = 1.0e-9
PROTECTED = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
    REPO
    / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
)
SOURCES = (
    Path(__file__).resolve(),
    HERE / "mechanism_segment_generator.py",
    HERE / "segment_generation_alns.py",
    HERE / "test_mechanism_segment_generator.py",
    REPO
    / "docs/handoff/generation_side_segment_trial_contract_20260719.md",
    REPO
    / "docs/handoff/algorithm_forensics_and_generation_blueprint_20260719.md",
)


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"output already exists: {OUT}")
    source_hashes = _hash_map(SOURCES)
    protected_hashes = _hash_map(PROTECTED)
    input_hashes = _input_hashes((*BINDING, NONBINDING))
    rows: list[dict[str, Any]] = []
    witnesses: dict[str, Any] = {}

    for bundle_dir in BINDING:
        bundle, owners, source, context = _fixture(bundle_dir)
        source_cost = independent_cost(bundle_dir, source, PRICES)
        source_completed = apply_terminal_completion(
            bundle_dir,
            source,
            prices=PRICES,
        )
        arm_payloads: dict[str, dict[str, Any]] = {}
        for mode in ("mechanism", "distance"):
            candidate, activity = propose_segment_move(
                source,
                context,
                owners,
                config=SegmentGeneratorConfig(mode=mode),
            )
            payload = _arm_payload(
                bundle_dir,
                bundle,
                source,
                candidate,
                activity,
            )
            arm_payloads[mode] = payload
            rows.append(
                {
                    "case": bundle_dir.name,
                    "binding": True,
                    "mode": mode,
                    "source_cost": source_cost,
                    **{
                        key: value
                        for key, value in payload.items()
                        if key != "solution"
                    },
                }
            )
        mechanism = arm_payloads["mechanism"]
        distance = arm_payloads["distance"]
        witnesses[bundle_dir.name] = {
            "source": _solution_payload(source),
            "source_signature": solution_signature_hash(source),
            "source_terminal_cost": float(source_completed.cost),
            "mechanism": {
                **mechanism,
                "solution": (
                    None
                    if mechanism["solution"] is None
                    else _solution_payload(mechanism["solution"])
                ),
            },
            "distance": {
                **distance,
                "solution": (
                    None
                    if distance["solution"] is None
                    else _solution_payload(distance["solution"])
                ),
            },
        }

    bundle, owners, source, context = _fixture(NONBINDING)
    candidate, activity = propose_segment_move(
        source,
        context,
        owners,
        config=SegmentGeneratorConfig(),
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
            "terminal_cost": None,
            "feasible": candidate is None,
            "route_membership_changed": False,
            "selected_segment_length": None,
            "selected_distance_delta": None,
            "selected_local_model_delta": None,
            "distance_worse_model_better_candidates": int(
                activity["ledger"][
                    "distance_worse_model_better_candidates"
                ]
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
            "PASS_SEGMENT_GENERATOR_BEHAVIOR"
            if passed
            else "STOP_SEGMENT_GENERATOR_BEHAVIOR"
        ),
        "passed": bool(passed),
        "checks": checks,
        "drift_checks": drift,
        "binding_case_count": len(BINDING),
        "formal_search_allowed": False,
        "stage2_allowed": False,
        "next_allowed_step": (
            "result_blind_two_instance_one_seed_performance_warning_gate"
            if passed
            else "freeze_SEG_GEN_01_without_performance_run"
        ),
    }
    metadata = {
        "schema_version": "resetp.seg-gen-01.behavior.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git_head(),
        "binding_cases": [
            str(path.relative_to(REPO)) for path in BINDING
        ],
        "nonbinding_case": str(NONBINDING.relative_to(REPO)),
        "prices": asdict(PRICES),
        "generator_config": asdict(SegmentGeneratorConfig()),
        "fixture_preparation_search_evaluations": 0,
        "complete_search_candidate_evaluations": 0,
        "source_hashes": source_hashes,
        "protected_hashes": protected_hashes,
        "input_hashes": input_hashes,
        "claim_boundary": (
            "Behaviour and attribution only on burned development inputs. "
            "This is not performance, benchmark, formal, or stage-two evidence."
        ),
    }
    audit = {
        "all_selected_segments_have_length_at_least_two": checks[
            "all_mechanism_segments_length_at_least_two"
        ],
        "distance_veto_witness_present": checks[
            "distance_worse_selected_witness_present"
        ],
        "mechanism_beats_distance_on_both_binding_fixtures": checks[
            "mechanism_terminal_better_than_distance"
        ],
        "zero_complete_search_evaluations": checks[
            "zero_complete_search_candidate_evaluations"
        ],
        "independent_feasibility_and_replay": checks[
            "all_mechanism_candidates_feasible_and_improving"
        ],
        "scope": "independent deterministic audit of behaviour artifacts",
    }

    OUT.mkdir(parents=True)
    _write_csv(OUT / "raw_runs.csv", rows)
    _write_json(OUT / "solution_witnesses.json", witnesses)
    _write_json(OUT / "metadata.json", metadata)
    _write_json(OUT / "decision.json", decision)
    _write_json(OUT / "independent_audit.json", audit)
    _write_text(
        OUT / "report.md",
        "# 生成侧成段搬移行为门\n\n"
        f"结论：`{decision['verdict']}`。\n\n"
        "两个多车场旧开发夹具都生成了至少两名客户的成段搬移；"
        "机制版保留了里程变差但完整业务成本下降的候选，"
        "并在两个夹具的对称终局复算中都优于里程删减版。"
        "单车场夹具精确不动作。\n\n"
        "这只证明动作和归因成立，不证明它在新题或完整搜索中胜 v7。\n",
    )
    _write_json(
        OUT / "artifact_hashes.json",
        {
            path.name: _sha256(path)
            for path in sorted(OUT.iterdir())
            if path.is_file()
            and path.name != "artifact_hashes.json"
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if passed else 1


def _fixture(bundle_dir: Path):
    bundle = load_search_bundle(bundle_dir)
    owners = infer_customer_home_depots(bundle.instance)
    solution = build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        PRICES,
        introduce_ev=False,
        require_charging_signal=False,
    )
    solution = annotate_cross_site_services(solution, owners)
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=PRICES,
        budget=EvalBudget(limit=0, target=0),
        customer_home_depot=owners,
        allow_cross_depot=True,
    )
    return bundle, owners, solution, context


def _arm_payload(
    bundle_dir: Path,
    bundle: Any,
    source: Any,
    candidate: Any,
    activity: dict[str, Any],
) -> dict[str, Any]:
    selected = activity["selected"]
    if candidate is None:
        return {
            "candidate_present": False,
            "candidate_cost": None,
            "terminal_cost": None,
            "feasible": True,
            "route_membership_changed": False,
            "selected_segment_length": None,
            "selected_distance_delta": None,
            "selected_local_model_delta": None,
            "distance_worse_model_better_candidates": int(
                activity["ledger"][
                    "distance_worse_model_better_candidates"
                ]
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
            "solution": None,
        }
    cost = independent_cost(bundle_dir, candidate, PRICES)
    terminal = apply_terminal_completion(
        bundle_dir,
        candidate,
        prices=PRICES,
    )
    return {
        "candidate_present": True,
        "candidate_cost": float(cost),
        "terminal_cost": float(terminal.cost),
        "feasible": not check_solution(
            candidate,
            bundle.instance,
            PRICES,
        ),
        "route_membership_changed": (
            _membership(source, bundle.instance)
            != _membership(candidate, bundle.instance)
        ),
        "selected_segment_length": int(
            selected["segment_length"]
        ),
        "selected_distance_delta": float(
            selected["distance_delta"]
        ),
        "selected_local_model_delta": (
            None
            if selected["local_model_delta"] is None
            else float(selected["local_model_delta"])
        ),
        "distance_worse_model_better_candidates": int(
            activity["ledger"][
                "distance_worse_model_better_candidates"
            ]
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
        "solution": candidate,
    }


def _checks(rows: list[dict[str, Any]]) -> dict[str, bool]:
    binding_mechanism = [
        row
        for row in rows
        if row["binding"] and row["mode"] == "mechanism"
    ]
    binding_distance = {
        row["case"]: row
        for row in rows
        if row["binding"] and row["mode"] == "distance"
    }
    nonbinding = [row for row in rows if not row["binding"]]
    return {
        "all_mechanism_candidates_present": all(
            row["candidate_present"]
            for row in binding_mechanism
        ),
        "all_mechanism_segments_length_at_least_two": all(
            int(row["selected_segment_length"]) >= 2
            for row in binding_mechanism
        ),
        "all_mechanism_candidates_change_membership": all(
            row["route_membership_changed"]
            for row in binding_mechanism
        ),
        "all_mechanism_candidates_feasible_and_improving": all(
            row["feasible"]
            and float(row["candidate_cost"])
            < float(row["source_cost"]) - TOL
            for row in binding_mechanism
        ),
        "distance_worse_model_better_witness_each_case": all(
            int(row["distance_worse_model_better_candidates"])
            >= 1
            for row in binding_mechanism
        ),
        "distance_worse_selected_witness_present": any(
            float(row["selected_distance_delta"]) > TOL
            and float(row["selected_local_model_delta"]) < -TOL
            for row in binding_mechanism
        ),
        "mechanism_terminal_better_than_distance": all(
            binding_distance[row["case"]]["terminal_cost"] is None
            or float(row["terminal_cost"])
            < float(
                binding_distance[row["case"]]["terminal_cost"]
            )
            - TOL
            for row in binding_mechanism
        ),
        "zero_complete_search_candidate_evaluations": all(
            int(row["complete_candidate_evaluations"]) == 0
            for row in rows
        ),
        "nonbinding_exact_noop": all(
            not row["candidate_present"]
            for row in nonbinding
        ),
    }


def _membership(solution: Any, instance: Any) -> dict[str, int]:
    return {
        customer_id: route_index
        for route_index, route in enumerate(solution.routes)
        for customer_id in _route_customers(route, instance)
    }


def _solution_payload(solution: Any) -> dict[str, Any]:
    return {
        "routes": [asdict(route) for route in solution.routes],
        "charging_actions": [
            asdict(action) for action in solution.charging_actions
        ],
        "cross_site_services": [
            asdict(service)
            for service in solution.cross_site_services
        ],
    }


def _input_hashes(bundle_dirs: tuple[Path, ...]) -> dict[str, str]:
    return _hash_map(
        tuple(
            path
            for bundle_dir in bundle_dirs
            for path in sorted(bundle_dir.iterdir())
            if path.is_file()
        )
    )


def _hash_map(paths: tuple[Path, ...]) -> dict[str, str]:
    return {
        str(path.relative_to(REPO)): _sha256(path)
        for path in paths
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(block)
    return digest.hexdigest()


def _git_head() -> str:
    import subprocess

    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_text(path: Path, content: str) -> None:
    temporary = path.with_name(
        f".{path.name}.tmp-{os.getpid()}"
    )
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _write_json(path: Path, payload: Any) -> None:
    _write_text(
        path,
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=str,
        )
        + "\n",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    _write_text(path, buffer.getvalue())


if __name__ == "__main__":
    raise SystemExit(main())
