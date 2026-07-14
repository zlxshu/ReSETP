"""Independent evidence replay for the E7 shared-start dynamic experiment."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from baselines.e7_dynamic import e7_formal_dynamic_value_20260714 as formal
from setp_solver.search.dynamic_multitrip_schedule import (
    cut_certificate_at_trigger,
    cut_dynamic_certificate_at_trigger,
    validate_dynamic_multitrip_certificate,
)
from setp_solver.search.metaheuristic_baselines import solution_from_dict
from setp_solver.search.multitrip_schedule import (
    MultiTripCertificate,
    ScheduledTrip,
)


ROOT = formal.ROOT.resolve()
CRITICAL_SOURCE_PATHS = (
    "baselines/e7_dynamic/e7_formal_dynamic_value_20260714.py",
    "solver/src/setp_solver/search/dynamic_multitrip_schedule.py",
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
)


class AuditFailure(RuntimeError):
    """Raised with the name of the first failed evidence check."""


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AuditFailure(label)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def truth(value: Any) -> bool:
    return str(value).lower() == "true"


def close(left: Any, right: Any, tolerance: float = 1e-6) -> bool:
    a = float(left)
    b = float(right)
    return abs(a - b) <= tolerance * max(1.0, abs(a), abs(b))


def certificate_from_dict(payload: dict[str, Any]) -> MultiTripCertificate:
    return MultiTripCertificate(
        contract_id=str(payload["contract_id"]),
        status=str(payload["status"]),
        vehicle_counts={str(key): int(value) for key, value in payload["vehicle_counts"].items()},
        trips=tuple(ScheduledTrip(**row) for row in payload["trips"]),
        recharge_mode=str(payload["recharge_mode"]),
        depot_charge_power_kw=float(payload["depot_charge_power_kw"]),
        first_trip_charge_day_offset=int(payload.get("first_trip_charge_day_offset", -1)),
    )


def verify_recorded_file(row: dict[str, str], path_key: str, hash_key: str) -> None:
    path = (ROOT / row[path_key]).resolve()
    require(path.is_file(), f"missing recorded file: {row[path_key]}")
    require(formal.sha256(path) == row[hash_key], f"recorded hash mismatch: {row[path_key]}")


def replay_session(
    stream_seed: int,
    arm: str,
    expected_stages: int,
    summary: dict[str, str],
    raw_by_key: dict[tuple[int, str, int], dict[str, str]],
) -> dict[str, Any]:
    evidence = load_json(ROOT / summary["stage_evidence_path"])
    require(len(evidence) == expected_stages, f"stream {stream_seed} {arm}: evidence stage count")

    sources = formal.load_arm(arm)
    events, owners, _, _ = formal.load_stream(stream_seed)
    batches = formal._validated_trigger_batches(stream_seed, events)
    require(len(batches) == expected_stages, f"stream {stream_seed} {arm}: full frozen stage count")

    current_solution = sources["solution"]
    current_certificate = sources["certificate"]
    current_instance = sources["bundle"].instance
    inherited_states = None
    inherited_locked_actions: tuple[Any, ...] = ()
    previous_start = None
    committed_customers: set[str] = set()
    booked_routes: set[str] = set()
    booked_actions: set[tuple[Any, ...]] = set()
    committed: dict[str, float] = {}
    fixed_asset_ids: set[str] | None = None
    rejection_counts: Counter[str] = Counter()
    executable_total = 0
    accepted_total = 0

    for stage_index, (batch, stage_payload) in enumerate(zip(batches, evidence), start=1):
        trigger = float(batch["trigger_time"])
        if stage_index == 1:
            cut = cut_certificate_at_trigger(
                current_solution,
                current_certificate,
                current_instance,
                sources["prices"],
                trigger_second=trigger,
            )
        else:
            cut = cut_dynamic_certificate_at_trigger(
                current_solution,
                current_certificate,
                current_instance,
                sources["prices"],
                inherited_asset_states=inherited_states,
                previous_stage_start_second=float(previous_start),
                trigger_second=trigger,
                inherited_locked_charging_actions=inherited_locked_actions,
            )

        locked_ids = [*cut.completed_route_ids, *cut.in_progress_route_ids]
        locked_routes = formal.gate._cut_routes(current_solution, locked_ids)
        new_routes = [route for route in locked_routes if route.vehicle_id not in booked_routes]
        formal.add_breakdown(
            committed,
            formal.evaluate_parts(new_routes, [], current_instance, sources),
        )
        booked_routes.update(route.vehicle_id for route in new_routes)
        for route in new_routes:
            committed_customers.update(formal.p2.route_customers(route, current_instance))

        new_actions = [
            action
            for action in cut.locked_charging_actions
            if formal.action_key(action) not in booked_actions
        ]
        formal.add_breakdown(
            committed,
            formal.evaluate_parts([], new_actions, current_instance, sources),
        )
        booked_actions.update(formal.action_key(action) for action in new_actions)

        construction = formal.gate.build_open_stage(
            formal.gate._cut_routes(current_solution, cut.editable_route_ids),
            current_instance,
            batch["events"],
            trigger,
            committed_customers,
            owners,
            sources["prices"],
            stage_index=stage_index,
            isolate_changed_customers=True,
        )
        event_ids, event_types, applied_ids, ignored_ids = formal._validate_stage_application(
            construction,
            batch["events"],
        )
        solution = solution_from_dict(stage_payload["solution"])
        certificate = certificate_from_dict(stage_payload["certificate"])
        validate_dynamic_multitrip_certificate(
            solution,
            certificate,
            construction.effective_instance,
            sources["prices"],
            asset_states=cut.asset_states,
            stage_start_second=trigger,
            locked_charging_actions=cut.locked_charging_actions,
        )

        expected_assets = {key: asdict(value) for key, value in sorted(cut.asset_states.items())}
        require(stage_payload["asset_states"] == expected_assets, f"stream {stream_seed} {arm} stage {stage_index}: asset states")
        require(
            stage_payload["asset_states_sha256"] == formal.canonical_sha256(expected_assets),
            f"stream {stream_seed} {arm} stage {stage_index}: asset state hash",
        )
        asset_ids = set(expected_assets)
        if fixed_asset_ids is None:
            fixed_asset_ids = asset_ids
        require(asset_ids == fixed_asset_ids and len(asset_ids) == 20, f"stream {stream_seed} {arm} stage {stage_index}: fixed assets")
        require(
            Counter(
                (value["vehicle_type"], value["home_depot_id"])
                for value in expected_assets.values()
            )
            == Counter({("cv", "D0"): 5, ("cv", "D1"): 5, ("ev", "D0"): 5, ("ev", "D1"): 5}),
            f"stream {stream_seed} {arm} stage {stage_index}: fleet composition",
        )

        locked_payload = [asdict(route) for route in locked_routes]
        action_payload = [asdict(action) for action in cut.locked_charging_actions]
        require(stage_payload["locked_routes"] == locked_payload, f"stream {stream_seed} {arm} stage {stage_index}: locked routes")
        require(stage_payload["locked_routes_sha256"] == formal.canonical_sha256(locked_payload), f"stream {stream_seed} {arm} stage {stage_index}: locked route hash")
        require(stage_payload["locked_charging_actions"] == action_payload, f"stream {stream_seed} {arm} stage {stage_index}: locked charging")
        require(stage_payload["locked_charging_actions_sha256"] == formal.canonical_sha256(action_payload), f"stream {stream_seed} {arm} stage {stage_index}: locked charging hash")

        active_customers = {
            node.node_id
            for node in construction.effective_instance.nodes
            if node.node_type.lower() == "c"
        }
        flat_future = [
            customer
            for route in solution.routes
            for customer in formal.p2.route_customers(route, construction.effective_instance)
        ]
        require(len(flat_future) == len(set(flat_future)), f"stream {stream_seed} {arm} stage {stage_index}: duplicate customer")
        future_customers = set(flat_future)
        require(committed_customers.isdisjoint(future_customers), f"stream {stream_seed} {arm} stage {stage_index}: committed/future overlap")
        require(committed_customers | future_customers == active_customers, f"stream {stream_seed} {arm} stage {stage_index}: customer coverage")
        expected_customer_sets = {
            "active_customer_ids": sorted(active_customers),
            "committed_customer_ids": sorted(committed_customers),
            "future_customer_ids": sorted(future_customers),
        }
        for key, expected in expected_customer_sets.items():
            require(stage_payload[key] == expected, f"stream {stream_seed} {arm} stage {stage_index}: {key}")
            require(stage_payload[f"{key}_sha256"] == formal.canonical_sha256(expected), f"stream {stream_seed} {arm} stage {stage_index}: {key} hash")

        if arm == "independent":
            require(solution.cross_site_services == [], f"stream {stream_seed} independent stage {stage_index}: cross-site list")
            for route in solution.routes:
                require(
                    all(
                        owners[customer] == route.home_depot_id
                        for customer in formal.p2.route_customers(route, construction.effective_instance)
                    ),
                    f"stream {stream_seed} independent stage {stage_index}: cross-site customer",
                )

        require(stage_payload["solution_sha256"] == formal.canonical_sha256(stage_payload["solution"]), f"stream {stream_seed} {arm} stage {stage_index}: solution hash")
        require(stage_payload["certificate_sha256"] == formal.canonical_sha256(stage_payload["certificate"]), f"stream {stream_seed} {arm} stage {stage_index}: certificate hash")

        raw = raw_by_key[(stream_seed, arm, stage_index)]
        require(raw["event_ids"] == ";".join(event_ids), f"stream {stream_seed} {arm} stage {stage_index}: event ids")
        require(raw["event_types"] == ";".join(event_types), f"stream {stream_seed} {arm} stage {stage_index}: event types")
        require(raw["applied_event_ids"] == ";".join(applied_ids), f"stream {stream_seed} {arm} stage {stage_index}: applied events")
        require(raw["ignored_locked_event_ids"] == ";".join(ignored_ids), f"stream {stream_seed} {arm} stage {stage_index}: ignored events")
        require(int(raw["asset_state_count"]) == 20, f"stream {stream_seed} {arm} stage {stage_index}: asset count")
        require(raw["stage_certificate_status"] == "PASS", f"stream {stream_seed} {arm} stage {stage_index}: certificate status")
        require(truth(raw["customer_accounting_pass"]), f"stream {stream_seed} {arm} stage {stage_index}: customer accounting flag")
        require(int(raw["active_customer_count"]) == len(active_customers), f"stream {stream_seed} {arm} stage {stage_index}: active count")
        require(int(raw["committed_customer_count"]) == len(committed_customers), f"stream {stream_seed} {arm} stage {stage_index}: committed count")
        require(int(raw["future_customer_count"]) == len(future_customers), f"stream {stream_seed} {arm} stage {stage_index}: future count")
        for key in (
            "asset_states_sha256",
            "locked_routes_sha256",
            "locked_charging_actions_sha256",
            "active_customer_ids_sha256",
            "committed_customer_ids_sha256",
            "future_customer_ids_sha256",
        ):
            require(raw[key] == stage_payload[key], f"stream {stream_seed} {arm} stage {stage_index}: raw/evidence {key}")
        require(raw["stage_solution_sha256"] == stage_payload["solution_sha256"], f"stream {stream_seed} {arm} stage {stage_index}: raw solution hash")
        require(raw["stage_certificate_sha256"] == stage_payload["certificate_sha256"], f"stream {stream_seed} {arm} stage {stage_index}: raw certificate hash")

        rejection = {key: int(value) for key, value in json.loads(raw["search_rejection_counts_json"]).items()}
        rejection_counts.update(rejection)
        duplicate_route_rejections = sum(
            value
            for key, value in rejection.items()
            if "route" in key.lower() and ("duplicate" in key.lower() or "not unique" in key.lower())
        )
        require(duplicate_route_rejections == 0, f"stream {stream_seed} {arm} stage {stage_index}: duplicate route rejection")
        evaluations = int(raw["evaluations"])
        changed = int(raw["changed_candidate_count"])
        exact = int(raw["search_exact_check_count"])
        executable = int(raw["executable_candidate_count"])
        accepted = int(raw["accepted_candidate_count"])
        require(0 <= accepted <= executable <= exact <= changed <= evaluations, f"stream {stream_seed} {arm} stage {stage_index}: search counters")
        executable_total += executable
        accepted_total += accepted

        future_parts = formal.evaluate_parts(
            solution.routes,
            solution.charging_actions,
            construction.effective_instance,
            sources,
        )
        running_parts = dict(committed)
        formal.add_breakdown(running_parts, future_parts)
        for key, value in stage_payload["cost_breakdown"].items():
            require(key in running_parts and close(value, running_parts[key]), f"stream {stream_seed} {arm} stage {stage_index}: cost {key}")
        require(close(raw["future_cost"], future_parts["total_cost"]), f"stream {stream_seed} {arm} stage {stage_index}: future cost")
        require(close(raw["running_total_cost"], running_parts["total_cost"]), f"stream {stream_seed} {arm} stage {stage_index}: running cost")

        inherited_states = cut.asset_states
        inherited_locked_actions = cut.locked_charging_actions
        previous_start = trigger
        current_solution = solution
        current_certificate = certificate
        current_instance = construction.effective_instance

    final_solution = load_json(ROOT / summary["final_solution_path"])
    final_certificate = load_json(ROOT / summary["final_certificate_path"])
    require(final_solution == evidence[-1]["solution"], f"stream {stream_seed} {arm}: final solution object")
    require(final_certificate == evidence[-1]["certificate"], f"stream {stream_seed} {arm}: final certificate object")

    remaining_actions = [
        action
        for action in current_solution.charging_actions
        if formal.action_key(action) not in booked_actions
    ]
    final_parts = dict(committed)
    formal.add_breakdown(
        final_parts,
        formal.evaluate_parts(
            current_solution.routes,
            remaining_actions,
            current_instance,
            sources,
        ),
    )
    require(close(summary["final_total_cost"], final_parts["total_cost"]), f"stream {stream_seed} {arm}: final cost")
    require(close(summary["final_total_emissions"], final_parts["E_total"]), f"stream {stream_seed} {arm}: final emissions")
    return {
        "stages": expected_stages,
        "evaluations": expected_stages * int(summary["evaluations_per_stage"]),
        "executable_candidates": executable_total,
        "accepted_candidates": accepted_total,
        "rejection_counts": dict(rejection_counts),
    }


def validate_run(
    run_dir: Path,
    expected_streams: list[int],
    expected_evaluations: int,
    require_formal: bool,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    require(run_dir.is_dir(), "run directory exists")
    metadata = load_json(run_dir / "metadata.json")
    decision = load_json(run_dir / "decision.json")
    raw_rows = read_rows(run_dir / "raw_runs.csv")
    session_rows = read_rows(run_dir / "session_summary.csv")
    paired_rows = read_rows(run_dir / "paired_summary.csv")

    require(metadata["contract_id"] == formal.CONTRACT_ID, "contract id")
    require(metadata["streams"] == expected_streams, "stream list")
    require(metadata["evaluations_per_stage"] == expected_evaluations, "evaluation budget")
    require(metadata["trigger_mode"] == "batched", "trigger mode")
    require(metadata["shared_initial_plan"] is True, "shared start flag")
    require(metadata["treatment_difference"] == "cross-depot service permission only", "single treatment difference")
    require(metadata["result_direction_used_to_continue"] is False, "result direction guard")
    require(metadata["run_start_commit"] == metadata["source_commit"] == metadata["artifact_write_commit"], "run/write/source commit equality")
    require(decision["passed"] is True and decision["failure_count"] == 0, "internal decision pass")
    require(decision["session_count"] == 2 * len(expected_streams), "session count")
    require(decision["paired_stream_count"] == len(expected_streams), "paired stream count")
    require(decision["zero_customer_loss"] is True, "zero customer loss")
    require(decision["all_stages_completed_before_next_trigger"] is True, "stage timing")
    require(not (run_dir / "failures.csv").exists(), "no failure file")
    if require_formal:
        require(metadata["scope"] == "formal", "formal scope")
        require(decision["verdict"] == "E7_PAIRED_FORMAL_PASS", "formal verdict")

    session_by_key = {
        (int(row["stream_seed"]), row["arm"]): row for row in session_rows
    }
    paired_by_seed = {int(row["stream_seed"]): row for row in paired_rows}
    require(len(session_by_key) == 2 * len(expected_streams), "unique sessions")
    require(set(paired_by_seed) == set(expected_streams), "paired seeds")

    expected_stage_counts: dict[int, int] = {}
    for stream_seed in expected_streams:
        events, _, _, _ = formal.load_stream(stream_seed)
        expected_stage_counts[stream_seed] = len(
            formal._validated_trigger_batches(stream_seed, events)
        )
    expected_raw_count = 2 * sum(expected_stage_counts.values())
    require(len(raw_rows) == expected_raw_count, "raw stage count")
    raw_by_key = {
        (int(row["stream_seed"]), row["arm"], int(row["stage"])): row
        for row in raw_rows
    }
    require(len(raw_by_key) == len(raw_rows), "unique raw stages")

    session_results: dict[str, Any] = {}
    for stream_seed in expected_streams:
        cooperative = session_by_key[(stream_seed, "cooperative")]
        independent = session_by_key[(stream_seed, "independent")]
        for key in (
            "initial_solution_sha256",
            "initial_certificate_sha256",
            "event_sha256",
            "owner_sha256",
            "initial_total_cost",
            "initial_total_emissions",
            "initial_route_count",
            "initial_charging_action_count",
            "initial_cross_site_customer_count",
        ):
            require(cooperative[key] == independent[key], f"stream {stream_seed}: same-start {key}")

        for arm, summary in (("cooperative", cooperative), ("independent", independent)):
            stages = expected_stage_counts[stream_seed]
            require(int(summary["stages"]) == stages, f"stream {stream_seed} {arm}: summary stages")
            require(int(summary["evaluations_per_stage"]) == expected_evaluations, f"stream {stream_seed} {arm}: summary budget")
            require(int(summary["total_evaluations"]) == stages * expected_evaluations, f"stream {stream_seed} {arm}: total evaluations")
            require(truth(summary["customer_accounting_pass"]), f"stream {stream_seed} {arm}: summary customer accounting")
            for path_key, hash_key in (
                ("event_path", "event_sha256"),
                ("owner_path", "owner_sha256"),
                ("initial_solution_path", "initial_solution_sha256"),
                ("initial_certificate_path", "initial_certificate_sha256"),
                ("final_solution_path", "final_solution_sha256"),
                ("final_certificate_path", "final_certificate_sha256"),
                ("stage_evidence_path", "stage_evidence_sha256"),
            ):
                verify_recorded_file(summary, path_key, hash_key)

        for stage_index in range(1, expected_stage_counts[stream_seed] + 1):
            cooperative_stage = raw_by_key[(stream_seed, "cooperative", stage_index)]
            independent_stage = raw_by_key[(stream_seed, "independent", stage_index)]
            for key in (
                "trigger_second",
                "event_ids",
                "event_types",
                "evaluations",
                "stage_search_seed",
                "operator_pairs",
            ):
                require(cooperative_stage[key] == independent_stage[key], f"stream {stream_seed} stage {stage_index}: paired {key}")
            require(int(cooperative_stage["evaluations"]) == expected_evaluations, f"stream {stream_seed} stage {stage_index}: cooperative budget")
            require(int(independent_stage["evaluations"]) == expected_evaluations, f"stream {stream_seed} stage {stage_index}: independent budget")

        session_results[f"stream{stream_seed}_cooperative"] = replay_session(
            stream_seed,
            "cooperative",
            expected_stage_counts[stream_seed],
            cooperative,
            raw_by_key,
        )
        session_results[f"stream{stream_seed}_independent"] = replay_session(
            stream_seed,
            "independent",
            expected_stage_counts[stream_seed],
            independent,
            raw_by_key,
        )

        pair = paired_by_seed[stream_seed]
        cooperative_cost = float(pair["cooperative_total_cost"])
        independent_cost = float(pair["independent_total_cost"])
        saving = float(pair["cooperative_saving_percent"])
        require(
            close(saving, 100.0 * (independent_cost - cooperative_cost) / independent_cost),
            f"stream {stream_seed}: paired saving arithmetic",
        )

    manifest = load_json(run_dir / "artifact_hashes.json")
    require(manifest["algorithm"] == "sha256", "artifact hash algorithm")
    listed = {row["path"]: row for row in manifest["artifacts"]}
    actual = {
        str(path.relative_to(ROOT)): path
        for path in run_dir.rglob("*")
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    require(set(listed) == set(actual), "artifact inventory")
    for relative_path, path in actual.items():
        require(listed[relative_path]["sha256"] == formal.sha256(path), f"artifact hash: {relative_path}")
        require(int(listed[relative_path]["bytes"]) == path.stat().st_size, f"artifact bytes: {relative_path}")

    source_commit = metadata["source_commit"]
    for relative_path in CRITICAL_SOURCE_PATHS:
        committed = subprocess.check_output(
            ["git", "show", f"{source_commit}:{relative_path}"],
            cwd=ROOT,
        )
        current = (ROOT / relative_path).read_bytes()
        require(
            hashlib.sha256(committed).hexdigest() == hashlib.sha256(current).hexdigest(),
            f"source commit anchor: {relative_path}",
        )

    paired_results = [
        {
            "stream_seed": stream_seed,
            "cooperative_total_cost": float(paired_by_seed[stream_seed]["cooperative_total_cost"]),
            "independent_total_cost": float(paired_by_seed[stream_seed]["independent_total_cost"]),
            "cooperative_saving_percent": float(paired_by_seed[stream_seed]["cooperative_saving_percent"]),
        }
        for stream_seed in expected_streams
    ]
    duplicate_route_rejections = sum(
        value
        for result in session_results.values()
        for key, value in result["rejection_counts"].items()
        if "route" in key.lower() and ("duplicate" in key.lower() or "not unique" in key.lower())
    )
    require(duplicate_route_rejections == 0, "all-session duplicate route rejections")
    return {
        "verdict": "PASS",
        "run_dir": str(run_dir.relative_to(ROOT)),
        "source_commit": source_commit,
        "stream_count": len(expected_streams),
        "stage_counts": expected_stage_counts,
        "session_count": len(session_rows),
        "raw_stage_count": len(raw_rows),
        "total_evaluations": sum(int(row["evaluations"]) for row in raw_rows),
        "duplicate_route_rejections": duplicate_route_rejections,
        "paired_results": paired_results,
        "session_results": session_results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--streams", type=int, nargs="+", required=True)
    parser.add_argument("--evaluations", type=int, required=True)
    parser.add_argument("--require-formal", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = validate_run(
            args.run_dir,
            expected_streams=args.streams,
            expected_evaluations=args.evaluations,
            require_formal=args.require_formal,
        )
    except (AuditFailure, AssertionError, KeyError, ValueError, TypeError) as error:
        print(json.dumps({"verdict": "FAIL", "error": str(error)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
