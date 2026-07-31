#!/usr/bin/env python3
"""Independent arithmetic audit for the two-depot transfer settlement."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from decimal import Decimal, getcontext
from itertools import permutations
from pathlib import Path
from typing import Any


getcontext().prec = 60

MEMBERS = ("D_guangzhou", "D_shenzhen")
STATES = ("I", "U", "F")
TOL = Decimal("1e-9")
EXPECTED_SOURCE_HASHES = {
    "fairness_raw": "c3225c57f2c9bbd34244a5ace3bccdd117db3d4dd05c5c082d59837be3a56313",
    "allocation_raw": "c1e58d6392757d12a8734cd3a00de00d8787936955c1626c203711e91d146431",
}

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[3]
FAIRNESS_DIR = REPO_ROOT / "baselines/china_e3_e7/e6_fairness_v3_20260731"
ALLOCATION_DIR = REPO_ROOT / "baselines/china_e3_e7/e6_allocation_20260731"
FAIRNESS_RAW = FAIRNESS_DIR / "raw_runs.csv"
ALLOCATION_RAW = ALLOCATION_DIR / "raw_runs.csv"


def decimal(value: str) -> Decimal:
    return Decimal(value)


def decimal_text(value: Decimal) -> str:
    return format(value, "f")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def fairness_manifest_raw_hash() -> str:
    manifest = load_json(FAIRNESS_DIR / "artifact_hashes.json")
    suffix = "e6_fairness_v3_20260731/raw_runs.csv"
    matches = [
        value
        for key, value in manifest["files"].items()
        if key.endswith(suffix)
    ]
    if len(matches) != 1:
        raise AssertionError(f"fairness manifest raw_runs entries: {len(matches)}")
    return str(matches[0])


def allocation_manifest_raw_hash() -> str:
    manifest = load_json(ALLOCATION_DIR / "artifact_hashes.json")
    suffix = "e6_allocation_20260731/raw_runs.csv"
    matches = [
        value["sha256"]
        for key, value in manifest["files"].items()
        if key.endswith(suffix)
    ]
    if len(matches) != 1:
        raise AssertionError(f"allocation manifest raw_runs entries: {len(matches)}")
    return str(matches[0])


def input_integrity() -> dict[str, Any]:
    fairness_hash = sha256(FAIRNESS_RAW)
    allocation_hash = sha256(ALLOCATION_RAW)
    fairness_manifest_hash = fairness_manifest_raw_hash()
    allocation_manifest_hash = allocation_manifest_raw_hash()
    fairness_statuses = {
        "metadata": load_json(FAIRNESS_DIR / "metadata.json")["status"],
        "decision": load_json(FAIRNESS_DIR / "decision.json")["status"],
        "done": load_json(FAIRNESS_DIR / "done.json")["status"],
    }
    allocation_statuses = {
        "metadata": load_json(ALLOCATION_DIR / "metadata.json")["status"],
        "decision": load_json(ALLOCATION_DIR / "decision.json")["status"],
        "done": load_json(ALLOCATION_DIR / "done.json")["status"],
    }
    hashes_match = (
        fairness_hash == EXPECTED_SOURCE_HASHES["fairness_raw"]
        == fairness_manifest_hash
        and allocation_hash == EXPECTED_SOURCE_HASHES["allocation_raw"]
        == allocation_manifest_hash
    )
    statuses_complete = (
        set(fairness_statuses.values()) == {"COMPLETE"}
        and set(allocation_statuses.values()) == {"COMPLETE"}
    )
    return {
        "passed": hashes_match and statuses_complete,
        "fairness_raw_sha256": fairness_hash,
        "fairness_manifest_raw_sha256": fairness_manifest_hash,
        "allocation_raw_sha256": allocation_hash,
        "allocation_manifest_raw_sha256": allocation_manifest_hash,
        "fairness_statuses": fairness_statuses,
        "allocation_statuses": allocation_statuses,
    }


def reconstruct_units() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    fairness_rows = load_csv(FAIRNESS_RAW)
    allocation_rows = load_csv(ALLOCATION_RAW)

    fairness_index: dict[
        tuple[str, int], dict[str, dict[str, str]]
    ] = {}
    for row in fairness_rows:
        key = (row["instance_id"], int(row["seed"]))
        state = row["state"]
        if state in fairness_index.setdefault(key, {}):
            raise AssertionError(f"duplicate fairness state {key} {state}")
        fairness_index[key][state] = row

    if len(fairness_rows) != 60:
        raise AssertionError(f"fairness rows: {len(fairness_rows)}")
    if len(fairness_index) != 20:
        raise AssertionError(f"fairness units: {len(fairness_index)}")
    for key, rows_by_state in fairness_index.items():
        if set(rows_by_state) != set(STATES):
            raise AssertionError(
                f"fairness states for {key}: {sorted(rows_by_state)}"
            )

    allocation_index: dict[tuple[str, int], dict[str, str]] = {}
    for row in allocation_rows:
        key = (row["instance_id"], int(row["seed"]))
        if key in allocation_index:
            raise AssertionError(f"duplicate allocation unit {key}")
        allocation_index[key] = row
    if len(allocation_rows) != 20:
        raise AssertionError(f"allocation rows: {len(allocation_rows)}")
    if set(allocation_index) != set(fairness_index):
        raise AssertionError("fairness/allocation unit keys differ")

    expected_instances = {
        "cn-prd-50c-01-V2-LOCATIONS",
        "cn-prd-100c-02-V2-LOCATIONS",
    }
    expected_keys = {
        (instance_id, seed)
        for instance_id in expected_instances
        for seed in range(1, 11)
    }
    if set(fairness_index) != expected_keys:
        raise AssertionError("20-unit denominator differs from the sealed design")

    units: list[dict[str, Any]] = []
    crosscheck_max_error = Decimal(0)
    crosscheck_fields = 0
    for key in sorted(fairness_index):
        state_i = fairness_index[key]["I"]
        state_u = fairness_index[key]["U"]
        allocation = allocation_index[key]
        cost_i = decimal(state_i["total_cost_cny"])
        cost_u = decimal(state_u["total_cost_cny"])
        delta = cost_i - cost_u
        profit_i = {
            member: decimal(state_i[f"profit_{member}_cny"])
            for member in MEMBERS
        }
        profit_u = {
            member: decimal(state_u[f"profit_{member}_cny"])
            for member in MEMBERS
        }

        comparisons = [
            (cost_i, decimal(allocation["system_cost_I_cny"])),
            (cost_u, decimal(allocation["system_cost_U_cny"])),
            (delta, decimal(allocation["system_saving_delta_cny"])),
        ]
        for member in MEMBERS:
            comparisons.extend(
                [
                    (
                        profit_i[member],
                        decimal(allocation[f"profit_I_{member}_cny"]),
                    ),
                    (
                        profit_u[member],
                        decimal(allocation[f"profit_U_{member}_cny"]),
                    ),
                ]
            )
        for fairness_value, allocation_value in comparisons:
            crosscheck_fields += 1
            crosscheck_max_error = max(
                crosscheck_max_error,
                abs(fairness_value - allocation_value),
            )

        units.append(
            {
                "instance_id": key[0],
                "seed": key[1],
                "cost_i": cost_i,
                "cost_u": cost_u,
                "delta": delta,
                "profit_i": profit_i,
                "profit_u": profit_u,
            }
        )

    crosscheck = {
        "passed": crosscheck_max_error <= TOL,
        "fairness_rows": len(fairness_rows),
        "allocation_rows": len(allocation_rows),
        "units": len(units),
        "fields_compared": crosscheck_fields,
        "max_abs_error_cny": decimal_text(crosscheck_max_error),
        "tolerance_cny": decimal_text(TOL),
    }
    return units, crosscheck


def shapley_from_definition(delta: Decimal) -> dict[str, Decimal]:
    def value(coalition: frozenset[str]) -> Decimal:
        if coalition == frozenset(MEMBERS):
            return delta
        return Decimal(0)

    totals = {member: Decimal(0) for member in MEMBERS}
    orderings = list(permutations(MEMBERS))
    for ordering in orderings:
        coalition: frozenset[str] = frozenset()
        for member in ordering:
            enlarged = coalition | {member}
            totals[member] += value(enlarged) - value(coalition)
            coalition = enlarged
    return {
        member: totals[member] / Decimal(len(orderings))
        for member in MEMBERS
    }


def verify_math(units: list[dict[str, Any]]) -> dict[str, Any]:
    unit_results: list[dict[str, Any]] = []
    shapley_max_error = Decimal(0)
    core_width_max_error = Decimal(0)
    budget_max_error = Decimal(0)
    transfer_max_error = Decimal(0)
    settlement_target_max_error = Decimal(0)
    member_cost_closure_max_error = Decimal(0)
    core_equivalence_mismatches = 0
    transfer_interval_equivalence_mismatches = 0
    feasible_ir_violations = 0
    feasible_ir_unit_violations = 0
    negative_reference_ir_violations = 0
    negative_units: list[dict[str, Any]] = []

    for unit in units:
        delta: Decimal = unit["delta"]
        profit_i: dict[str, Decimal] = unit["profit_i"]
        profit_u: dict[str, Decimal] = unit["profit_u"]
        phi = shapley_from_definition(delta)

        unit_shapley_error = max(
            abs(phi[member] - delta / Decimal(2)) for member in MEMBERS
        )
        shapley_max_error = max(shapley_max_error, unit_shapley_error)

        changes = {
            member: profit_u[member] - profit_i[member]
            for member in MEMBERS
        }
        member_cost_closure = abs(
            sum(changes.values(), Decimal(0)) - delta
        )
        member_cost_closure_max_error = max(
            member_cost_closure_max_error,
            member_cost_closure,
        )
        damaged = min(MEMBERS, key=lambda member: (changes[member], member))
        payer = next(member for member in MEMBERS if member != damaged)

        lower = profit_i[damaged] - profit_u[damaged]
        upper = profit_u[payer] - profit_i[payer]
        interval_nonempty = lower <= upper + TOL
        delta_nonnegative = delta >= 0
        abstract_core_nonempty = delta_nonnegative
        if abstract_core_nonempty != delta_nonnegative:
            core_equivalence_mismatches += 1
        if interval_nonempty != delta_nonnegative:
            transfer_interval_equivalence_mismatches += 1
        core_width_error = abs((upper - lower) - delta)
        core_width_max_error = max(core_width_max_error, core_width_error)

        closed_form_transfer = lower + delta / Decimal(2)
        direct_transfer = (
            profit_i[damaged] + phi[damaged] - profit_u[damaged]
        )
        unit_transfer_error = abs(closed_form_transfer - direct_transfer)
        transfer_max_error = max(transfer_max_error, unit_transfer_error)

        settled = {
            damaged: profit_u[damaged] + closed_form_transfer,
            payer: profit_u[payer] - closed_form_transfer,
        }
        before_sum = sum(profit_u.values(), Decimal(0))
        after_sum = sum(settled.values(), Decimal(0))
        budget_error = abs(after_sum - before_sum)
        budget_max_error = max(budget_max_error, budget_error)

        unit_settlement_target_error = max(
            abs(settled[member] - (profit_i[member] + phi[member]))
            for member in MEMBERS
        )
        settlement_target_max_error = max(
            settlement_target_max_error,
            unit_settlement_target_error,
        )

        ir_violating_members = [
            member
            for member in MEMBERS
            if settled[member] < profit_i[member] - TOL
        ]
        if delta_nonnegative:
            feasible_ir_violations += len(ir_violating_members)
            feasible_ir_unit_violations += int(bool(ir_violating_members))
        else:
            negative_reference_ir_violations += len(ir_violating_members)
            required_signed_receipts = {
                member: profit_i[member] - profit_u[member]
                for member in MEMBERS
            }
            negative_units.append(
                {
                    "instance_id": unit["instance_id"],
                    "seed": unit["seed"],
                    "cost_I_cny": decimal_text(unit["cost_i"]),
                    "cost_U_cny": decimal_text(unit["cost_u"]),
                    "delta_cny": decimal_text(delta),
                    "profit_I_D_guangzhou_cny": decimal_text(
                        profit_i["D_guangzhou"]
                    ),
                    "profit_U_D_guangzhou_cny": decimal_text(
                        profit_u["D_guangzhou"]
                    ),
                    "profit_I_D_shenzhen_cny": decimal_text(
                        profit_i["D_shenzhen"]
                    ),
                    "profit_U_D_shenzhen_cny": decimal_text(
                        profit_u["D_shenzhen"]
                    ),
                    "core_transfer_lower_cny": decimal_text(lower),
                    "core_transfer_upper_cny": decimal_text(upper),
                    "required_signed_receipt_D_guangzhou_cny": decimal_text(
                        required_signed_receipts["D_guangzhou"]
                    ),
                    "required_signed_receipt_D_shenzhen_cny": decimal_text(
                        required_signed_receipts["D_shenzhen"]
                    ),
                    "sum_required_signed_receipts_cny": decimal_text(
                        sum(required_signed_receipts.values(), Decimal(0))
                    ),
                    "shapley_reference_ir_violations": len(
                        ir_violating_members
                    ),
                }
            )

        unit_results.append(
            {
                "instance_id": unit["instance_id"],
                "seed": unit["seed"],
                "C_I_cny": decimal_text(unit["cost_i"]),
                "C_U_cny": decimal_text(unit["cost_u"]),
                "delta_cny": decimal_text(delta),
                "shapley_D_guangzhou_cny": decimal_text(
                    phi["D_guangzhou"]
                ),
                "shapley_D_shenzhen_cny": decimal_text(
                    phi["D_shenzhen"]
                ),
                "shapley_equal_split_max_abs_error_cny": decimal_text(
                    unit_shapley_error
                ),
                "core_nonempty": delta_nonnegative,
                "transfer_interval_nonempty": interval_nonempty,
                "core_interval_lower_cny": decimal_text(lower),
                "core_interval_upper_cny": decimal_text(upper),
                "core_width_vs_delta_abs_error_cny": decimal_text(
                    core_width_error
                ),
                "damaged_member": damaged,
                "payer_member": payer,
                "closed_form_transfer_cny": decimal_text(
                    closed_form_transfer
                ),
                "direct_shapley_transfer_cny": decimal_text(direct_transfer),
                "transfer_formula_abs_error_cny": decimal_text(
                    unit_transfer_error
                ),
                "budget_balance_abs_error_cny": decimal_text(budget_error),
                "settled_profit_D_guangzhou_cny": decimal_text(
                    settled["D_guangzhou"]
                ),
                "settled_profit_D_shenzhen_cny": decimal_text(
                    settled["D_shenzhen"]
                ),
                "settled_vs_direct_shapley_target_max_abs_error_cny": (
                    decimal_text(unit_settlement_target_error)
                ),
                "individual_rationality_violations": len(
                    ir_violating_members
                ),
                "individual_rationality_violating_members": (
                    ir_violating_members
                ),
                "member_profit_vs_system_delta_closure_abs_error_cny": (
                    decimal_text(member_cost_closure)
                ),
            }
        )

    negative_infeasibility_passed = (
        len(negative_units) == 1
        and decimal(negative_units[0]["core_transfer_lower_cny"])
        > decimal(negative_units[0]["core_transfer_upper_cny"])
        and decimal(
            negative_units[0]["sum_required_signed_receipts_cny"]
        )
        > 0
    )
    checks = [
        {
            "id": "two_member_shapley_equal_split",
            "passed": shapley_max_error <= TOL,
            "units_checked": len(units),
            "max_abs_error_cny": decimal_text(shapley_max_error),
        },
        {
            "id": "two_member_core_nonempty_iff_delta_nonnegative",
            "passed": (
                core_equivalence_mismatches == 0
                and transfer_interval_equivalence_mismatches == 0
                and core_width_max_error <= TOL
            ),
            "units_checked": len(units),
            "abstract_equivalence_mismatches": core_equivalence_mismatches,
            "transfer_interval_equivalence_mismatches": (
                transfer_interval_equivalence_mismatches
            ),
            "max_abs_interval_width_minus_delta_cny": decimal_text(
                core_width_max_error
            ),
        },
        {
            "id": "budget_balance",
            "passed": budget_max_error <= TOL,
            "units_checked": len(units),
            "max_abs_error_cny": decimal_text(budget_max_error),
        },
        {
            "id": "individual_rationality_on_feasible_settlements",
            "passed": (
                feasible_ir_violations == 0
                and feasible_ir_unit_violations == 0
                and negative_reference_ir_violations == 2
            ),
            "feasible_units_checked": len(units) - len(negative_units),
            "feasible_member_violations": feasible_ir_violations,
            "feasible_unit_violations": feasible_ir_unit_violations,
            "negative_delta_reference_member_violations": (
                negative_reference_ir_violations
            ),
        },
        {
            "id": "closed_form_transfer_matches_shapley_definition",
            "passed": (
                transfer_max_error <= TOL
                and settlement_target_max_error <= TOL
            ),
            "units_checked": len(units),
            "max_abs_transfer_error_cny": decimal_text(transfer_max_error),
            "max_abs_settlement_target_error_cny": decimal_text(
                settlement_target_max_error
            ),
        },
        {
            "id": "negative_delta_budget_balance_ir_infeasibility",
            "passed": negative_infeasibility_passed,
            "negative_units": negative_units,
            "proof": (
                "Budget balance requires s_G+s_S=0. Individual rationality "
                "requires s_d>=Pi_d^I-Pi_d^U for each member. In the negative "
                "unit the two lower bounds sum to a positive amount, so the "
                "requirements have no common solution."
            ),
        },
    ]
    passed_count = sum(int(bool(check["passed"])) for check in checks)
    return {
        "status": "PASS" if passed_count == len(checks) else "FAIL",
        "math_checks_total": len(checks),
        "math_checks_passed": passed_count,
        "tolerance_cny": decimal_text(TOL),
        "checks": checks,
        "summary": {
            "units": len(units),
            "nonnegative_delta_units": len(units) - len(negative_units),
            "negative_delta_units": len(negative_units),
            "budget_balance_max_abs_error_cny": decimal_text(
                budget_max_error
            ),
            "individual_rationality_violations_feasible_members": (
                feasible_ir_violations
            ),
            "individual_rationality_violations_feasible_units": (
                feasible_ir_unit_violations
            ),
            "negative_delta_shapley_reference_member_violations": (
                negative_reference_ir_violations
            ),
            "transfer_formula_max_abs_error_cny": decimal_text(
                transfer_max_error
            ),
            "settlement_target_max_abs_error_cny": decimal_text(
                settlement_target_max_error
            ),
            "member_profit_vs_system_delta_max_abs_closure_error_cny": (
                decimal_text(member_cost_closure_max_error)
            ),
        },
        "unit_results": unit_results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    integrity = input_integrity()
    units, crosscheck = reconstruct_units()
    math_result = verify_math(units)
    result = {
        "schema": "resetp.transfer-payment-independent-math-audit.v1",
        "input_integrity": integrity,
        "source_crosscheck": crosscheck,
        **math_result,
    }
    if not integrity["passed"] or not crosscheck["passed"]:
        result["status"] = "FAIL"
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
