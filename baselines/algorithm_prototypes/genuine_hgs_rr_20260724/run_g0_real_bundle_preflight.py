#!/usr/bin/env python3
"""Zero-search real-China81 wiring gate for the genuine hybrid.

The gate is deliberately separated from G1. It loads three preregistered
development bundles, replays the frozen witnesses, exercises the tailored
finite-fleet decoder, and round-trips a feasible solution through the PyVRP
warm-start adapter. It never runs HGS or RR iterations.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable


REPO = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
PREREGISTRATION = PACKAGE / "g0_real_bundle_preregistration_v1.json"
OUT = PACKAGE / "g0_real_bundle_gate_v1"
FORMAL_ROOT = (
    REPO / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v7_small_archive_ledger_20260724"
)
FORMAL_PROGRESS = FORMAL_ROOT / "full_gate/progress.json"
FORMAL_PROCESS_TOKENS = (
    "run_corrected_china81_d6_staged_portfolio_v7_small_archive_ledger.py",
    "run_e2_staged_release_chain.py",
)
CONTRACT = REPO / "docs/handoff/e2_genuine_hybrid_hgs_rr_contract_20260724.md"


class DecoderShortlistInfeasibleError(RuntimeError):
    """Carry candidate-level evidence when the real-bundle decoder fails."""

    def __init__(self, diagnostics: list[dict[str, Any]]) -> None:
        super().__init__("decoder shortlist has no globally feasible candidate")
        self.diagnostics = diagnostics


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("cannot write an empty real-bundle gate CSV")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def load_preregistration() -> dict[str, Any]:
    payload = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    if payload.get("schema") != (
        "resetp.coop-hgs-rr-g0-real-bundle-preregistration.v1"
    ):
        raise RuntimeError("unexpected real-bundle preregistration schema")
    if payload.get("status") != "REGISTERED_NOT_EXECUTED":
        raise RuntimeError("real-bundle preregistration status drift")
    return payload


def _manifest_entries(payload: dict[str, Any]) -> dict[str, str]:
    entries = payload.get("sha256")
    if entries is None:
        entries = payload.get("artifacts")
    if not isinstance(entries, dict) or not entries:
        raise RuntimeError("authority hash manifest has no artifact entries")
    return {str(path): str(value) for path, value in entries.items()}


def _selected_manifest_paths(
    authority_name: str,
    instance_ids: tuple[str, ...],
    entries: dict[str, str],
) -> tuple[str, ...]:
    if authority_name == "static_inputs":
        shared = {
            "instance_catalog.csv",
            "facilities.csv",
            "metadata.json",
            "node_city_membership.csv",
        }
        selected = {
            path
            for path in entries
            if path in shared
            or any(
                path == f"instances/{instance_id}/nodes.csv"
                for instance_id in instance_ids
            )
        }
    elif authority_name == "road_matrices":
        selected = {
            path
            for path in entries
            if any(
                path.startswith(f"instances/{instance_id}/")
                for instance_id in instance_ids
            )
        }
    elif authority_name == "runtime_parameters":
        selected = set(entries)
    elif authority_name == "finite_fleet":
        selected = {
            path
            for path in entries
            if path
            in {
                "fleet_caps.csv",
                "metadata.json",
                "decision.json",
                "witness_hashes.json",
            }
            or any(
                path == f"witnesses/{instance_id}.json" for instance_id in instance_ids
            )
        }
    else:
        raise RuntimeError(f"unknown authority {authority_name!r}")
    if not selected:
        raise RuntimeError(
            f"no selected manifest entries for authority {authority_name}"
        )
    return tuple(sorted(selected))


def verify_preregistration_inputs(
    preregistration: dict[str, Any],
) -> dict[str, Any]:
    registration = preregistration["development_registration"]
    registration_path = REPO / registration["path"]
    if sha256(registration_path) != registration["sha256"]:
        raise RuntimeError("development registration hash mismatch")
    development = json.loads(registration_path.read_text(encoding="utf-8"))
    registered_rows = {row["instance_id"]: row for row in development["strata"]}
    instance_rows = tuple(preregistration["instances"])
    instance_ids = tuple(row["instance_id"] for row in instance_rows)
    if set(instance_ids) != set(registered_rows):
        raise RuntimeError("real-bundle panel differs from development registration")
    for row in instance_rows:
        registered = registered_rows[row["instance_id"]]
        for key in ("region", "customer_count", "nodes_sha256"):
            if row[key] != registered[key]:
                raise RuntimeError(
                    f"development registration mismatch: {row['instance_id']}:{key}"
                )

    verified_files = 1
    authority_counts: dict[str, int] = {}
    for authority_name, authority in preregistration["authorities"].items():
        authority_root = REPO / authority["path"]
        manifest_path = authority_root / "artifact_hashes.json"
        if sha256(manifest_path) != authority["artifact_hashes_sha256"]:
            raise RuntimeError(f"authority manifest hash mismatch: {authority_name}")
        entries = _manifest_entries(
            json.loads(manifest_path.read_text(encoding="utf-8"))
        )
        selected = _selected_manifest_paths(
            authority_name,
            instance_ids,
            entries,
        )
        for relative in selected:
            path = authority_root / relative
            if not path.is_file():
                raise RuntimeError(f"authority artifact is missing: {path}")
            if sha256(path) != entries[relative]:
                raise RuntimeError(f"authority artifact hash mismatch: {path}")
        authority_counts[authority_name] = len(selected)
        verified_files += 1 + len(selected)

    fleet_root = REPO / preregistration["authorities"]["finite_fleet"]["path"]
    for row in instance_rows:
        witness = fleet_root / "witnesses" / f"{row['instance_id']}.json"
        if sha256(witness) != row["witness_sha256"]:
            raise RuntimeError(f"frozen witness hash mismatch: {row['instance_id']}")
    return {
        "instance_ids": instance_ids,
        "verified_file_count": verified_files,
        "authority_selected_file_counts": authority_counts,
    }


def formal_resource_state() -> dict[str, Any]:
    progress: dict[str, Any] = {}
    if FORMAL_PROGRESS.is_file():
        progress = json.loads(FORMAL_PROGRESS.read_text(encoding="utf-8"))
    process_text = subprocess.check_output(
        ["ps", "-axo", "pid=,command="],
        text=True,
    )
    processes = [
        {
            "pid": line.strip().split(maxsplit=1)[0],
            "token": next(token for token in FORMAL_PROCESS_TOKENS if token in line),
        }
        for line in process_text.splitlines()
        if any(token in line for token in FORMAL_PROCESS_TOKENS)
        and "run_g0_real_bundle_preflight.py" not in line
    ]
    return {
        "progress_status": progress.get("status"),
        "completed_tasks": progress.get("completed_tasks"),
        "updated_at_utc": progress.get("updated_at_utc"),
        "blocking_processes": processes,
        "formal_running": bool(
            str(progress.get("status", "")).upper() == "RUNNING" or processes
        ),
    }


def require_resource_isolation() -> dict[str, Any]:
    state = formal_resource_state()
    if state["formal_running"]:
        raise RuntimeError(
            "HALT_G0_RESOURCE_ISOLATION_FORMAL_E2_RUNNING:"
            f"progress={state['progress_status']}:"
            f"processes={state['blocking_processes']}"
        )
    return state


def _install_import_paths() -> None:
    for path in (
        REPO / "solver/src",
        REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720",
        PACKAGE,
    ):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))


def _load_witness(
    instance_id: str,
    preregistration: dict[str, Any],
) -> Any:
    from setp_solver.solution import Route, Solution

    fleet_root = REPO / preregistration["authorities"]["finite_fleet"]["path"]
    path = fleet_root / "witnesses" / f"{instance_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return Solution(
        routes=[
            Route(
                vehicle_id=str(route["vehicle_id"]),
                vehicle_type=str(route["vehicle_type"]),
                home_depot_id=str(route["home_depot_id"]),
                node_sequence=[str(node) for node in route["node_sequence"]],
            )
            for route in payload["routes"]
        ]
    )


def _customer_multiset(solution: Any, bundle: Any) -> Counter[str]:
    customer_ids = {
        node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "c"
    }
    return Counter(
        node_id
        for route in solution.routes
        for node_id in route.node_sequence
        if node_id in customer_ids
    )


def _route_identity(solution: Any, bundle: Any) -> Counter[tuple[Any, ...]]:
    customer_ids = {
        node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "c"
    }
    return Counter(
        (
            route.home_depot_id,
            route.vehicle_type.strip().lower(),
            tuple(
                node_id for node_id in route.node_sequence if node_id in customer_ids
            ),
        )
        for route in solution.routes
    )


def _require_customer_coverage(solution: Any, bundle: Any) -> None:
    expected = {
        node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "c"
    }
    observed = _customer_multiset(solution, bundle)
    if set(observed) != expected or any(count != 1 for count in observed.values()):
        missing = sorted(expected - set(observed))
        duplicate = sorted(node_id for node_id, count in observed.items() if count != 1)
        raise RuntimeError(
            "customer coverage mismatch:"
            f"missing={missing[:5]}:duplicate={duplicate[:5]}"
        )


def _require_finite_fleet(solution: Any, bundle: Any) -> None:
    use = Counter(
        (route.home_depot_id, route.vehicle_type.strip().lower())
        for route in solution.routes
    )
    for (depot_id, vehicle_type), count in use.items():
        cap = int(bundle.fleet_caps_by_depot[depot_id][f"num_{vehicle_type}"])
        if count > cap:
            raise RuntimeError(
                f"finite fleet exceeded: {depot_id}:{vehicle_type}:{count}>{cap}"
            )


def _verify_city_date_bindings(
    bundle: Any,
    preregistration: dict[str, Any],
) -> dict[str, Any]:
    expected_bindings = preregistration["approved_city_bindings"]
    cities = {
        str(node.city).strip().lower()
        for node in bundle.instance.nodes
        if node.city is not None
    }
    rows_by_city: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in bundle.time_profile:
        rows_by_city[str(row["city"]).strip().lower()].append(row)
    if set(rows_by_city) != cities:
        raise RuntimeError("time-profile cities differ from instance cities")
    for city in sorted(cities):
        expected = expected_bindings[city]
        if expected["region"] != bundle.region:
            raise RuntimeError(f"city-region binding mismatch: {city}")
        rows = rows_by_city[city]
        if len(rows) != 48:
            raise RuntimeError(f"city does not have 48 half-hour rows: {city}")
        slots = {int(row["half_hour_slot"]) for row in rows}
        if slots != set(range(1, 49)):
            raise RuntimeError(f"half-hour slots are incomplete: {city}")
        for row in rows:
            if row["date"] != bundle.date:
                raise RuntimeError(f"scenario date mismatch: {city}")
            if row["joint_key_status"] != "PASS_CITY_DATE_SLOT_PARAMETER_IDENTITY":
                raise RuntimeError(f"parameter identity is not PASS: {city}")
            for key in (
                "price_area_id",
                "carbon_source_column",
                "diesel_zone",
            ):
                if str(row[key]) != str(expected[key]):
                    raise RuntimeError(f"approved city binding mismatch: {city}:{key}")
            if not math.isclose(
                float(row["diesel_price_cny_per_l"]),
                float(expected["diesel_price_cny_per_l"]),
                rel_tol=0.0,
                abs_tol=1.0e-12,
            ):
                raise RuntimeError(f"approved diesel price mismatch: {city}")
        if bundle.price_area_by_city[city] != expected["price_area_id"]:
            raise RuntimeError(f"bundle price-area mismatch: {city}")
        if (
            bundle.carbon_source_column_by_city[city]
            != expected["carbon_source_column"]
        ):
            raise RuntimeError(f"bundle carbon-source mismatch: {city}")
        if bundle.diesel_zone_by_city[city] != expected["diesel_zone"]:
            raise RuntimeError(f"bundle diesel-zone mismatch: {city}")
        if not math.isclose(
            float(bundle.diesel_price_by_city[city]),
            float(expected["diesel_price_cny_per_l"]),
            rel_tol=0.0,
            abs_tol=1.0e-12,
        ):
            raise RuntimeError(f"bundle diesel-price mismatch: {city}")
    if "shenzhen" in cities and (bundle.price_area_by_city["shenzhen"] != "shenzhen"):
        raise RuntimeError("Shenzhen independent price area was not preserved")
    return {
        "cities": sorted(cities),
        "time_profile_row_count": sum(len(rows) for rows in rows_by_city.values()),
        "shenzhen_independent_price_area": (
            "shenzhen" not in cities
            or bundle.price_area_by_city["shenzhen"] == "shenzhen"
        ),
    }


def _projection_roundtrip(solution: Any, bundle: Any) -> tuple[Any, dict[str, Any]]:
    from pyvrp_adapter import (
        _project_initial_solution,
        _translate_solution,
        build_pyvrp_problem,
    )

    problem = build_pyvrp_problem(
        bundle,
        route_proxy_mode="mechanism_ev",
    )
    data = problem.model.data()
    native = _project_initial_solution(solution, data, problem)
    translated = _translate_solution(native, problem)
    _require_customer_coverage(translated, bundle)
    if _route_identity(solution, bundle) != _route_identity(translated, bundle):
        raise RuntimeError(
            "PyVRP projection roundtrip changed route depot, type or customers"
        )
    return translated, {
        "native_route_count": len(native.routes()),
        "translated_route_count": len(translated.routes),
        "route_identity_preserved": True,
    }


def _decoder_diagnostics(shortlist: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rank, result in enumerate(shortlist.evaluated, start=1):
        candidate = shortlist.candidates[rank - 1]
        rows.append(
            {
                "rank": rank,
                "feasible": bool(result.scored.feasible),
                "objective": float(result.scored.objective),
                "assignments": [
                    {
                        "route_index": route_index,
                        "home_depot_id": assignment.home_depot_id,
                        "vehicle_type": assignment.vehicle_type,
                        "charge_strategy": assignment.charge_strategy,
                        "carbon_weight": assignment.carbon_weight,
                    }
                    for route_index, assignment in candidate.assignments
                ],
                "violations": [
                    {
                        "type": violation.type,
                        "vehicle_id": violation.vehicle_id,
                        "location": violation.location,
                        "detail": violation.detail,
                    }
                    for violation in result.scored.violations
                ],
            }
        )
    return rows


def _verify_bundle_source_paths(
    bundle: Any,
    preregistration: dict[str, Any],
) -> None:
    expected_roots = {
        key: str(value["path"]) for key, value in preregistration["authorities"].items()
    }
    if bundle.static_input_authority != expected_roots["static_inputs"]:
        raise RuntimeError("static input authority drift")
    if bundle.road_matrix_authority != expected_roots["road_matrices"]:
        raise RuntimeError("road matrix authority drift")
    if bundle.runtime_parameter_authority != expected_roots["runtime_parameters"]:
        raise RuntimeError("runtime parameter authority drift")
    if bundle.fleet_authority != expected_roots["finite_fleet"]:
        raise RuntimeError("finite fleet authority drift")
    for relative in bundle.source_paths.values():
        path = REPO / relative
        if not path.exists():
            raise RuntimeError(f"bundle source path is missing: {relative}")


def run_instance(
    registered: dict[str, Any],
    preregistration: dict[str, Any],
) -> dict[str, Any]:
    from contracts import (
        AlgorithmArm,
        CandidateSource,
        CompleteEvaluationLedger,
    )
    from decoder_cache import RouteLocalDecoderCache
    from evaluation import BudgetedCompleteEvaluator
    from fleet_assignment_dp import (
        build_route_assignment_options,
        decode_assignment_shortlist,
    )
    from setp_solver.check import check_solution
    from setp_solver.china81 import load_china81_bundle
    from setp_solver.china81_completion import (
        complete_china81_route_skeleton,
        exact_china81_score,
    )
    from setp_solver.cost import evaluate

    instance_id = registered["instance_id"]
    bundle = load_china81_bundle(
        REPO,
        instance_id,
        date=preregistration["scenario_date"],
        static_input_authority=preregistration["authorities"]["static_inputs"]["path"],
        road_matrix_authority=preregistration["authorities"]["road_matrices"]["path"],
        runtime_parameter_authority=preregistration["authorities"][
            "runtime_parameters"
        ]["path"],
        fleet_authority=preregistration["authorities"]["finite_fleet"]["path"],
    )
    if bundle.instance_id != instance_id or bundle.region != registered["region"]:
        raise RuntimeError("loaded bundle identity differs from preregistration")
    customer_count = sum(
        node.node_type.lower() == "c" for node in bundle.instance.nodes
    )
    if customer_count != int(registered["customer_count"]):
        raise RuntimeError("loaded customer count differs from preregistration")
    _verify_bundle_source_paths(bundle, preregistration)
    binding = _verify_city_date_bindings(bundle, preregistration)

    witness = _load_witness(instance_id, preregistration)
    completion = complete_china81_route_skeleton(witness, bundle)
    _require_customer_coverage(completion.solution, bundle)
    _require_finite_fleet(completion.solution, bundle)
    direct_violations = check_solution(
        completion.solution,
        bundle.instance,
        bundle.prices,
    )
    direct = evaluate(
        completion.solution,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    )
    objective, breakdown, exact_violations = exact_china81_score(
        completion.solution,
        bundle,
    )
    if direct_violations or exact_violations:
        raise RuntimeError(
            "frozen witness completion is infeasible:"
            f"direct={len(direct_violations)}:exact={len(exact_violations)}"
        )
    if not math.isclose(
        float(completion.objective),
        float(objective),
        rel_tol=0.0,
        abs_tol=1.0e-9,
    ) or not math.isclose(
        float(direct["total_cost"]),
        float(objective),
        rel_tol=0.0,
        abs_tol=1.0e-9,
    ):
        raise RuntimeError("completion, direct and exact costs disagree")

    shortlist_limit = int(preregistration["decoder_shortlist_limit"])
    ledger = CompleteEvaluationLedger(
        arm=AlgorithmArm.RUIN_RECREATE,
        limit=shortlist_limit,
    )
    evaluator = BudgetedCompleteEvaluator(bundle=bundle, ledger=ledger)
    cache = RouteLocalDecoderCache()
    options_by_route = build_route_assignment_options(
        witness,
        bundle,
        route_local_cache=cache,
    )
    shortlist = decode_assignment_shortlist(
        witness,
        bundle,
        evaluator=evaluator,
        source=CandidateSource.RUIN_RECREATE,
        max_candidates=shortlist_limit,
        source_metadata={
            "gate": "G0_REAL_BUNDLE",
            "instance_id": instance_id,
            "search_iterations": 0,
        },
        route_local_cache=cache,
    )
    option_depots = {
        option.assignment.home_depot_id
        for options in options_by_route.values()
        for option in options
    }
    option_types = {
        option.assignment.vehicle_type
        for options in options_by_route.values()
        for option in options
    }
    expected_depots = set(bundle.fleet_caps_by_depot)
    if option_depots != expected_depots:
        raise RuntimeError(
            "finite-fleet decoder did not retain every present depot:"
            f"expected={sorted(expected_depots)}:observed={sorted(option_depots)}"
        )
    if option_types != {"cv", "ev"}:
        raise RuntimeError(
            "finite-fleet decoder did not retain both CV and EV assignments"
        )
    if shortlist.selected is None or not shortlist.selected.scored.feasible:
        raise DecoderShortlistInfeasibleError(
            _decoder_diagnostics(shortlist)
        )
    if ledger.consumed != shortlist.decoded_count:
        raise RuntimeError("complete decoder evaluations escaped the visible ledger")
    if ledger.consumed < 1 or ledger.consumed > shortlist_limit:
        raise RuntimeError("decoder complete-evaluation count is invalid")
    _require_customer_coverage(shortlist.selected.scored.solution, bundle)
    _require_finite_fleet(shortlist.selected.scored.solution, bundle)

    translated, projection = _projection_roundtrip(
        shortlist.selected.scored.solution,
        bundle,
    )
    roundtrip = complete_china81_route_skeleton(translated, bundle)
    roundtrip_objective, _, roundtrip_violations = exact_china81_score(
        roundtrip.solution,
        bundle,
    )
    if roundtrip_violations:
        raise RuntimeError("translated PyVRP skeleton is not fully completable")
    _require_customer_coverage(roundtrip.solution, bundle)
    _require_finite_fleet(roundtrip.solution, bundle)

    return {
        "instance_id": instance_id,
        "stratum": registered["stratum"],
        "region": bundle.region,
        "status": "PASS",
        "detail": "",
        "customer_count": customer_count,
        "city_count": len(binding["cities"]),
        "cities": "|".join(binding["cities"]),
        "scenario_date": bundle.date,
        "time_profile_row_count": binding["time_profile_row_count"],
        "shenzhen_independent_price_area": binding["shenzhen_independent_price_area"],
        "witness_completion_cost": float(objective),
        "witness_emissions_kg": float(breakdown["E_total"]),
        "direct_violation_count": len(direct_violations),
        "exact_violation_count": len(exact_violations),
        "decoder_candidate_count": len(shortlist.candidates),
        "decoder_complete_evaluations": ledger.consumed,
        "decoder_feasible_evaluations": sum(
            record.feasible for record in ledger.records
        ),
        "decoder_selected_cost": float(shortlist.selected.scored.objective),
        "decoder_diagnostics_json": json.dumps(
            _decoder_diagnostics(shortlist),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "decoder_depot_count": len(option_depots),
        "decoder_vehicle_types": "|".join(sorted(option_types)),
        "decoder_cache_entries": cache.as_dict()["entries"],
        "decoder_cache_hits": cache.as_dict()["hits"],
        "decoder_cache_misses": cache.as_dict()["misses"],
        "projection_native_route_count": projection["native_route_count"],
        "projection_route_identity_preserved": projection["route_identity_preserved"],
        "roundtrip_completion_cost": float(roundtrip_objective),
        "search_iterations": 0,
    }


def _failure_row(
    registered: dict[str, Any],
    exc: Exception,
) -> dict[str, Any]:
    return {
        "instance_id": registered["instance_id"],
        "stratum": registered["stratum"],
        "region": registered["region"],
        "status": "FAIL",
        "detail": f"{type(exc).__name__}:{exc}",
        "customer_count": registered["customer_count"],
        "city_count": "",
        "cities": "",
        "scenario_date": "",
        "time_profile_row_count": "",
        "shenzhen_independent_price_area": "",
        "witness_completion_cost": "",
        "witness_emissions_kg": "",
        "direct_violation_count": "",
        "exact_violation_count": "",
        "decoder_candidate_count": "",
        "decoder_complete_evaluations": "",
        "decoder_feasible_evaluations": "",
        "decoder_selected_cost": "",
        "decoder_diagnostics_json": json.dumps(
            getattr(exc, "diagnostics", []),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "decoder_depot_count": "",
        "decoder_vehicle_types": "",
        "decoder_cache_entries": "",
        "decoder_cache_hits": "",
        "decoder_cache_misses": "",
        "projection_native_route_count": "",
        "projection_route_identity_preserved": "",
        "roundtrip_completion_cost": "",
        "search_iterations": 0,
    }


def _source_hashes() -> dict[str, str]:
    sources: Iterable[Path] = (
        PREREGISTRATION,
        CONTRACT,
        *sorted(
            path for path in PACKAGE.glob("*.py") if not path.name.startswith("._")
        ),
    )
    return {str(path.relative_to(REPO)): sha256(path) for path in sources}


def execute_gate() -> int:
    preregistration = load_preregistration()
    verified = verify_preregistration_inputs(preregistration)
    resource_state = require_resource_isolation()
    if OUT.exists():
        raise RuntimeError(f"refusing to overwrite existing gate: {OUT}")
    OUT.mkdir(parents=True)
    _install_import_paths()
    rows: list[dict[str, Any]] = []
    for registered in preregistration["instances"]:
        try:
            rows.append(run_instance(registered, preregistration))
        except Exception as exc:
            rows.append(_failure_row(registered, exc))
    passed = all(row["status"] == "PASS" for row in rows)
    write_csv(OUT / "raw_runs.csv", rows)
    metadata = {
        "schema": "resetp.coop-hgs-rr-g0-real-bundle-metadata.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO,
            text=True,
        ).strip(),
        "preregistration_sha256": sha256(PREREGISTRATION),
        "verified_inputs": verified,
        "resource_state_at_start": resource_state,
        "search_iterations": 0,
        "source_hashes": _source_hashes(),
    }
    write_json(OUT / "metadata.json", metadata)
    decision = {
        "schema": "resetp.coop-hgs-rr-g0-real-bundle-decision.v1",
        "decision": (
            "PASS_G0_REAL_BUNDLE_WIRING__G1_NOT_AUTHORIZED"
            if passed
            else "HALT_G0_REAL_BUNDLE_WIRING"
        ),
        "passed_instances": sum(row["status"] == "PASS" for row in rows),
        "total_instances": len(rows),
        "search_iterations": 0,
        "claim_boundary": preregistration["claim_boundary"],
    }
    write_json(OUT / "decision.json", decision)
    report_lines = [
        "# G0 real China81 bundle wiring gate",
        "",
        f"Decision: `{decision['decision']}`.",
        "",
        (
            f"{decision['passed_instances']}/{decision['total_instances']} "
            "preregistered bundles passed."
        ),
        "",
        (
            "This gate loads real frozen inputs and exercises completion, exact "
            "scoring, tailored finite-fleet decoding, and PyVRP warm-start "
            "roundtrip without running any search iteration."
        ),
        "",
        (
            "It cannot support performance, 1+1>2, BKS, or SOTA claims. G1 "
            "remains separately gated."
        ),
        "",
    ]
    for row in rows:
        report_lines.append(
            f"- `{row['instance_id']}`: {row['status']}"
            + (f" — {row['detail']}" if row["detail"] else "")
        )
    report_lines.append("")
    (OUT / "report.md").write_text(
        "\n".join(report_lines),
        encoding="utf-8",
    )
    targets = (
        OUT / "metadata.json",
        OUT / "raw_runs.csv",
        OUT / "decision.json",
        OUT / "report.md",
    )
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "files": {path.name: sha256(path) for path in targets},
        },
    )
    write_json(
        OUT / "done.json",
        {
            "schema": "resetp.coop-hgs-rr-g0-real-bundle-done.v1",
            "decision": decision["decision"],
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "search_iterations": 0,
        },
    )
    print(decision["decision"])
    return 0 if passed else 2


def check_contract() -> int:
    preregistration = load_preregistration()
    verified = verify_preregistration_inputs(preregistration)
    state = formal_resource_state()
    print(
        json.dumps(
            {
                "contract": "PASS",
                "verified_inputs": verified,
                "resource_state": state,
                "execute_allowed_now": not state["formal_running"],
                "expected_output": str(OUT.relative_to(REPO)),
                "claim_boundary": preregistration["claim_boundary"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-contract", action="store_true")
    mode.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.check_contract:
        return check_contract()
    return execute_gate()


if __name__ == "__main__":
    raise SystemExit(main())
