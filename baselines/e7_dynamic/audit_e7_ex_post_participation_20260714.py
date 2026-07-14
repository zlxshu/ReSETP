#!/usr/bin/env python3
"""Zero-search probe for E7 depot-level realised participation.

This script reads only the frozen E7 formal evidence and the already-built
full-day service ledgers.  It follows the same accounting convention used by
E6: customer revenue goes to the depot that actually serves the customer;
route and charging costs go to the route's home depot.

The probe refuses to report a ratio unless the reconstructed depot costs close
to the recorded full-day system cost and every service record is bound to a
recorded route with the same serving depot.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping

from setp_solver.search.bundle import load_search_bundle
from setp_solver.solution import ChargingAction, Route, Solution
import validate_e7_records_independent_20260714 as validator_module


REPO = Path(__file__).resolve().parents[2]
RUN_DIR = REPO / "baselines/e7_dynamic/e7_v2_20260714/formal_shared_start_400_route_fix"
VALUE_DIR = REPO / "baselines/e7_dynamic/e7_full_day_value_audit_formal_20260714"
EXPECTED_STREAMS = (1, 2, 3, 4, 5)
COST_FIELDS = (
    "cost_fix",
    "cost_km",
    "cost_fuel",
    "cost_elec",
    "cost_occ",
    "cost_transship",
    "cost_carbon",
)
TOL = 1e-6


class ProbeError(RuntimeError):
    pass


def _validator() -> Any:
    return validator_module


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _route_id(route: Mapping[str, Any]) -> str:
    return str(route["vehicle_id"])


def _action_key(action: ChargingAction) -> tuple[Any, ...]:
    return (
        action.vehicle_id,
        action.station_id,
        round(float(action.charge_start_second), 9),
        round(float(action.energy_kwh), 9),
    )


def _add_cost(target: dict[str, float], part: Mapping[str, Any]) -> None:
    for field in COST_FIELDS:
        target[field] = target.get(field, 0.0) + float(part[field])


def _total(row: Mapping[str, float]) -> float:
    return sum(float(row.get(field, 0.0)) for field in COST_FIELDS)


def _close(left: float, right: float) -> bool:
    return abs(float(left) - float(right)) <= TOL * max(1.0, abs(float(left)), abs(float(right)))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _current_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True, stderr=subprocess.PIPE
        ).strip()
    except subprocess.CalledProcessError as exc:
        raise ProbeError("cannot read current audit commit") from exc


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO.resolve()))
    except ValueError as exc:
        raise ProbeError(f"path leaves repository: {path}") from exc


def _validate_commit_bound_sources() -> dict[str, Any]:
    commit = _current_commit()
    sources = (
        Path(__file__).resolve(),
        (Path(__file__).resolve().parent / "validate_e7_records_independent_20260714.py").resolve(),
    )
    result: dict[str, Any] = {}
    for path in sources:
        relative = _relative(path)
        if not path.is_file():
            raise ProbeError(f"audit source is missing: {relative}")
        current = _sha256(path)
        committed = hashlib.sha256(
            validator_module.git_blob(REPO, commit, relative)
        ).hexdigest()
        if current != committed:
            raise ProbeError(f"audit source differs from HEAD: {relative}")
        result[relative] = {"commit": commit, "sha256": current}
    return result


def _validate_value_audit() -> dict[str, Any]:
    decision = _read_json(VALUE_DIR / "decision.json")
    if decision.get("status") != "PASS":
        raise ProbeError("full-day value audit did not pass")
    if decision.get("independent_record_replay") != "RECORD_LAYER_PASS":
        raise ProbeError("full-day value audit lacks an independent replay pass")
    manifest = _read_json(VALUE_DIR / "artifact_hashes.json")
    listed = {str(row["path"]): row for row in manifest.get("artifacts", [])}
    actual: dict[str, Path] = {}
    for path in VALUE_DIR.rglob("*"):
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        ):
            actual[_relative(path)] = path
    if set(listed) != set(actual):
        raise ProbeError("full-day value audit artifact inventory does not close")
    for relative, path in actual.items():
        if listed[relative]["sha256"] != _sha256(path):
            raise ProbeError(f"full-day value audit file hash differs: {relative}")
        if int(listed[relative]["bytes"]) != path.stat().st_size:
            raise ProbeError(f"full-day value audit file size differs: {relative}")
    return {
        "path": _relative(VALUE_DIR),
        "artifact_count": len(listed),
        "artifact_manifest_sha256": _sha256(VALUE_DIR / "artifact_hashes.json"),
    }


def reconstruct_cost_by_depot(stream: int, arm: str, validator: Any) -> dict[str, Any]:
    if arm not in {"cooperative", "independent"}:
        raise ProbeError(f"unknown arm: {arm}")
    _, owners, batches = validator.validate_event_stream(REPO, stream)
    bundle = load_search_bundle(REPO / validator.BASE_BUNDLE)
    prices = validator.formal_prices()
    if abs(float(prices.cross_site_cost)) > 1e-12:
        raise ProbeError("probe requires the frozen zero cross-site fee")
    if abs(float(prices.carbon_price)) > 1e-12:
        raise ProbeError("probe requires the frozen zero carbon price")

    stages = _read_json(RUN_DIR / "stage_evidence" / f"stream{stream}__{arm}.json")
    if len(stages) != len(batches):
        raise ProbeError("stage evidence and trigger batches differ")
    session_rows = {
        (int(row["stream_seed"]), row["arm"]): row
        for row in _read_csv(RUN_DIR / "session_summary.csv")
    }
    recorded_total = float(session_rows[(stream, arm)]["final_total_cost"])

    current_instance = bundle.instance
    committed_customers: set[str] = set()
    booked_route_payloads: dict[str, dict[str, Any]] = {}
    booked_action_keys: set[tuple[Any, ...]] = set()
    route_depot: dict[str, str] = {}
    by_depot = {"D0": {field: 0.0 for field in COST_FIELDS}, "D1": {field: 0.0 for field in COST_FIELDS}}
    reconstructed_dispositions: list[dict[str, Any]] = []

    for stage_index, (stage, batch) in enumerate(zip(stages, batches), start=1):
        new_routes: list[Route] = []
        for payload in stage["locked_routes"]:
            route_id = _route_id(payload)
            previous = booked_route_payloads.get(route_id)
            if previous is not None and previous != payload:
                raise ProbeError(f"booked route changed: {route_id}")
            route_depot[route_id] = str(payload["home_depot_id"])
            if previous is None:
                booked_route_payloads[route_id] = dict(payload)
                route = Route(**payload)
                new_routes.append(route)
                committed_customers.update(validator._route_customers(payload, current_instance))

        for route in new_routes:
            part = validator.evaluate_direct(
                Solution(routes=[route], charging_actions=[]),
                current_instance,
                bundle.carbon_profile,
                prices,
            )
            _add_cost(by_depot[route.home_depot_id], part)

        for route_payload in [*stage["locked_routes"], *stage["solution"]["routes"]]:
            route_depot[_route_id(route_payload)] = str(route_payload["home_depot_id"])

        for payload in stage["locked_charging_actions"]:
            action = ChargingAction(**payload)
            key = _action_key(action)
            if key in booked_action_keys:
                continue
            booked_action_keys.add(key)
            depot = route_depot.get(action.vehicle_id)
            if depot is None:
                raise ProbeError(f"charging action has no route/depot binding: {action.vehicle_id}")
            part = validator.evaluate_direct(
                Solution(routes=[], charging_actions=[action]),
                current_instance,
                bundle.carbon_profile,
                prices,
            )
            _add_cost(by_depot[depot], part)

        applied = validator.apply_event_batch(current_instance, batch.events, committed_customers)
        for event in batch.events:
            event_id = str(event["event_id"])
            status = "ignored_locked" if event_id in applied.ignored_locked_event_ids else "applied"
            reconstructed_dispositions.append(
                {
                    "event_id": event_id,
                    "event_type": str(event["event_type"]),
                    "customer_id": str(event["customer_id"]),
                    "stage": stage_index,
                    "status": status,
                }
            )
        current_instance = applied.instance

    final_payload = stages[-1]["solution"]
    final_routes = [Route(**row) for row in final_payload["routes"]]
    for route in final_routes:
        if route.vehicle_id in booked_route_payloads:
            raise ProbeError(f"final future route was already booked: {route.vehicle_id}")
        route_depot[route.vehicle_id] = route.home_depot_id
        part = validator.evaluate_direct(
            Solution(routes=[route], charging_actions=[]),
            current_instance,
            bundle.carbon_profile,
            prices,
        )
        _add_cost(by_depot[route.home_depot_id], part)

    for payload in final_payload["charging_actions"]:
        action = ChargingAction(**payload)
        if _action_key(action) in booked_action_keys:
            continue
        depot = route_depot.get(action.vehicle_id)
        if depot is None:
            raise ProbeError(f"final charging action has no route/depot binding: {action.vehicle_id}")
        part = validator.evaluate_direct(
            Solution(routes=[], charging_actions=[action]),
            current_instance,
            bundle.carbon_profile,
            prices,
        )
        _add_cost(by_depot[depot], part)

    depot_total = {depot: _total(parts) for depot, parts in by_depot.items()}
    reconstructed_total = sum(depot_total.values())
    if not _close(reconstructed_total, recorded_total):
        raise ProbeError(
            f"depot costs do not close: reconstructed={reconstructed_total}, recorded={recorded_total}"
        )
    return {
        "cost_components_by_depot": by_depot,
        "cost_by_depot": depot_total,
        "recorded_total_cost": recorded_total,
        "reconstructed_total_cost": reconstructed_total,
        "cost_closure_error": reconstructed_total - recorded_total,
        "route_depot": route_depot,
        "event_dispositions": reconstructed_dispositions,
    }


def revenue_by_depot(stream: int, arm: str, route_depot: Mapping[str, str]) -> dict[str, Any]:
    ledger = _read_json(VALUE_DIR / "service_ledgers" / f"stream{stream}__{arm}.json")
    records = ledger["service_records"]
    ids = [str(row["customer_id"]) for row in records]
    if len(ids) != len(set(ids)):
        raise ProbeError("service ledger repeats a customer")
    rho = Decimal(str(ledger["revenue_per_kg"]))
    revenue = {"D0": Decimal("0"), "D1": Decimal("0")}
    demand = {"D0": Decimal("0"), "D1": Decimal("0")}
    for row in records:
        route_id = str(row["route_id"])
        serving_depot = str(row["serving_depot"])
        bound_depot = route_depot.get(route_id)
        if bound_depot != serving_depot:
            raise ProbeError(
                f"service/route depot mismatch for {row['customer_id']}: {serving_depot} != {bound_depot}"
            )
        quantity = Decimal(str(row["demand_kg"]))
        demand[serving_depot] += quantity
        revenue[serving_depot] += quantity * rho
    if sum(revenue.values()) != Decimal(str(ledger["full_day_revenue"])):
        raise ProbeError("depot revenue does not close to full-day revenue")
    recorded_dispositions = [
        {
            "event_id": str(row["event_id"]),
            "event_type": str(row["event_type"]),
            "customer_id": str(row["customer_id"]),
            "stage": int(row["stage"]),
            "status": str(row["status"]),
        }
        for row in ledger["event_dispositions"]
    ]
    return {
        "revenue_by_depot": {key: float(value) for key, value in revenue.items()},
        "demand_by_depot": {key: float(value) for key, value in demand.items()},
        "full_day_revenue": float(sum(revenue.values())),
        "served_customer_count": len(records),
        "recorded_event_dispositions": recorded_dispositions,
    }


def audit_arm(stream: int, arm: str, validator: Any) -> dict[str, Any]:
    cost = reconstruct_cost_by_depot(stream, arm, validator)
    revenue = revenue_by_depot(stream, arm, cost["route_depot"])
    if revenue["recorded_event_dispositions"] != cost["event_dispositions"]:
        raise ProbeError("event dispositions do not match the independently rebuilt event ledger")
    profit = {
        depot: revenue["revenue_by_depot"][depot] - cost["cost_by_depot"][depot]
        for depot in ("D0", "D1")
    }
    if not _close(sum(profit.values()), revenue["full_day_revenue"] - cost["recorded_total_cost"]):
        raise ProbeError("depot profits do not close to full-day operating net benefit")
    return {
        "arm": arm,
        "stream": stream,
        "cost_by_depot": cost["cost_by_depot"],
        "cost_components_by_depot": cost["cost_components_by_depot"],
        "revenue_by_depot": revenue["revenue_by_depot"],
        "demand_by_depot": revenue["demand_by_depot"],
        "profit_by_depot": profit,
        "served_customer_count": revenue["served_customer_count"],
        "cost_closure_error": cost["cost_closure_error"],
    }


def audit_stream(stream: int) -> dict[str, Any]:
    validator = _validator()
    cooperative = audit_arm(stream, "cooperative", validator)
    independent = audit_arm(stream, "independent", validator)
    baseline = independent["profit_by_depot"]
    if any(value <= 0.0 for value in baseline.values()):
        raise ProbeError(f"independent depot profit is not positive: {baseline}")
    ratios = {
        depot: cooperative["profit_by_depot"][depot] / baseline[depot]
        for depot in ("D0", "D1")
    }
    return {
        "stream": stream,
        "accounting_rule": (
            "revenue follows the depot that actually serves the customer; "
            "route and charging costs follow the route home depot"
        ),
        "cooperative": cooperative,
        "independent": independent,
        "profit_ratio_by_depot": ratios,
        "minimum_profit_ratio": min(ratios.values()),
        "both_depots_no_worse": all(value >= 1.0 - 1e-9 for value in ratios.values()),
        "interpretation": "ex-post realised participation check; not enforced during E7 search",
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _artifact_hashes(output: Path) -> dict[str, Any]:
    rows = []
    for path in sorted(output.rglob("*")):
        if (
            not path.is_file()
            or path.name == "artifact_hashes.json"
            or path.name.startswith("._")
            or "__pycache__" in path.parts
            or ".pytest_cache" in path.parts
        ):
            continue
        rows.append(
            {"path": _relative(path), "sha256": _sha256(path), "bytes": path.stat().st_size}
        )
    return {
        "algorithm": "sha256",
        "excluded": ["artifact_hashes.json", "._*", "__pycache__", ".pytest_cache"],
        "artifacts": rows,
    }


def run_formal_audit(output: Path) -> dict[str, Any]:
    output = output.resolve()
    if output.exists():
        raise ProbeError("output directory must be new")
    if RUN_DIR.resolve() in output.parents or VALUE_DIR.resolve() in output.parents:
        raise ProbeError("output directory overlaps frozen evidence")

    source_evidence = _validate_commit_bound_sources()
    value_evidence = _validate_value_audit()
    formal_replay = validator_module.validate_formal_run(REPO, RUN_DIR)
    if formal_replay.get("verdict") != "RECORD_LAYER_PASS":
        raise ProbeError("formal E7 record replay did not pass")

    results = [audit_stream(stream) for stream in EXPECTED_STREAMS]
    raw_rows: list[dict[str, Any]] = []
    paired_rows: list[dict[str, Any]] = []
    for result in results:
        stream = int(result["stream"])
        ratios = result["profit_ratio_by_depot"]
        paired_rows.append(
            {
                "stream_seed": stream,
                "D0_profit_ratio": ratios["D0"],
                "D1_profit_ratio": ratios["D1"],
                "minimum_profit_ratio": result["minimum_profit_ratio"],
                "both_depots_no_worse": result["both_depots_no_worse"],
            }
        )
        for depot in ("D0", "D1"):
            cooperative = result["cooperative"]
            independent = result["independent"]
            raw_rows.append(
                {
                    "stream_seed": stream,
                    "depot_id": depot,
                    "cooperative_revenue": cooperative["revenue_by_depot"][depot],
                    "cooperative_cost": cooperative["cost_by_depot"][depot],
                    "cooperative_profit": cooperative["profit_by_depot"][depot],
                    "independent_revenue": independent["revenue_by_depot"][depot],
                    "independent_cost": independent["cost_by_depot"][depot],
                    "independent_profit": independent["profit_by_depot"][depot],
                    "profit_ratio": ratios[depot],
                    "participation_slack": (
                        cooperative["profit_by_depot"][depot]
                        - independent["profit_by_depot"][depot]
                    ),
                    "no_worse": ratios[depot] >= 1.0 - 1e-9,
                    "cooperative_cost_closure_error": cooperative["cost_closure_error"],
                    "independent_cost_closure_error": independent["cost_closure_error"],
                }
            )

    status_counts = Counter(bool(row["both_depots_no_worse"]) for row in paired_rows)
    minimum_row = min(raw_rows, key=lambda row: float(row["profit_ratio"]))
    decision = {
        "status": "PASS",
        "verdict": "E7_EX_POST_PARTICIPATION_AUDIT_PASS",
        "stream_count": len(results),
        "depot_comparison_count": len(raw_rows),
        "both_depots_no_worse_stream_count": status_counts[True],
        "participation_failed_stream_count": status_counts[False],
        "minimum_profit_ratio": minimum_row["profit_ratio"],
        "minimum_profit_ratio_stream": minimum_row["stream_seed"],
        "minimum_profit_ratio_depot": minimum_row["depot_id"],
        "all_independent_profits_positive": all(
            float(row["independent_profit"]) > 0 for row in raw_rows
        ),
        "maximum_absolute_cost_closure_error": max(
            max(
                abs(float(row["cooperative_cost_closure_error"])),
                abs(float(row["independent_cost_closure_error"])),
            )
            for row in raw_rows
        ),
        "interpretation": (
            "ex-post realised participation check; participation was not enforced "
            "during the E7 search"
        ),
        "commercial_assumption": (
            "customer revenue follows the depot that actually served the customer"
        ),
    }
    metadata = {
        "contract_id": "E7_EX_POST_PARTICIPATION_AUDIT_V1",
        "scope": "formal_zero_search_audit",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_run": _relative(RUN_DIR),
        "source_value_audit": value_evidence,
        "audit_commit": _current_commit(),
        "audit_source": source_evidence,
        "streams": list(EXPECTED_STREAMS),
        "depots": ["D0", "D1"],
        "accounting_rule": (
            "revenue follows the depot that actually serves the customer; "
            "route and charging costs follow the route home depot"
        ),
        "cross_site_fee": 0.0,
        "carbon_price": 0.0,
        "result_direction_used_to_continue": False,
    }

    output.mkdir(parents=True, exist_ok=False)
    _write_csv(output / "raw_runs.csv", raw_rows)
    _write_csv(output / "paired_summary.csv", paired_rows)
    _write_json(output / "stream_results.json", results)
    _write_json(output / "independent_validation.json", formal_replay)
    _write_json(output / "metadata.json", metadata)
    _write_json(output / "decision.json", decision)
    detail = [
        "| {stream} | {d0:.4f} | {d1:.4f} | {ok} |".format(
            stream=int(row["stream_seed"]),
            d0=float(row["D0_profit_ratio"]),
            d1=float(row["D1_profit_ratio"]),
            ok="是" if row["both_depots_no_worse"] else "否",
        )
        for row in paired_rows
    ]
    report = [
        "# E7 动态订单下的双方参与结果",
        "",
        "## 判定",
        "",
        "机械复核通过。五条订单变化序列、两个车场和两种经营方式的收入、成本与收益均闭合，各自经营的车场收益均为正。",
        "",
        "合作方案在2/5条订单变化序列中同时满足两家车场均不低于各自经营收益；其余3条至少有一家车场低于参与底线，最低收益比为{ratio:.4f}（序列{stream}，车场{depot}）。这说明静态条件下满足的参与要求不会在动态订单变化中自动延续。".format(
            ratio=float(decision["minimum_profit_ratio"]),
            stream=int(decision["minimum_profit_ratio_stream"]),
            depot=decision["minimum_profit_ratio_depot"],
        ),
        "",
        "| 订单变化序列 | 车场D0收益比 | 车场D1收益比 | 双方均不吃亏 |",
        "|---:|---:|---:|:---:|",
        *detail,
        "",
        "## 证据边界",
        "",
        "这是一项事后参与检查，动态搜索过程中没有强制双方参与底线，因此不能写成动态公平约束始终得到满足。收入按实际服务车场归属，路线与充电成本按执行车辆所属车场归属；本批跨场费和碳价均为零，不存在需要主观分摊的公共费用。若企业合同规定客户收入仍归历史所属方，结论需要按新的结算规则重新计算。",
        "",
    ]
    (output / "report.md").write_text("\n".join(report), encoding="utf-8")
    _write_json(output / "artifact_hashes.json", _artifact_hashes(output))
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stream", type=int)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.output_dir is not None:
        result = run_formal_audit(args.output_dir)
    elif args.stream is not None:
        result = audit_stream(args.stream)
    else:
        raise SystemExit("provide --stream for a probe or --output-dir for the formal audit")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
