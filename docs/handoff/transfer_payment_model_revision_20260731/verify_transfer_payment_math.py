#!/usr/bin/env python3
"""Independent two-depot transfer-payment verification for ReSETP.

The script reconstructs the 20 I/U pairs from the sealed E6 v3 source table.
It does not use the prose report as a numerical input and does not modify any
source or evidence file.
"""

from __future__ import annotations

import csv
import json
from decimal import Decimal, getcontext
from fractions import Fraction
from itertools import permutations
from pathlib import Path
from typing import Any


getcontext().prec = 50

MEMBERS = ("D_guangzhou", "D_shenzhen")
TOL = Decimal("1e-9")

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[3]
SOURCE_RAW = (
    REPO_ROOT
    / "baselines/china_e3_e7/e6_fairness_v3_20260731/raw_runs.csv"
)
ALLOCATION_RAW = (
    REPO_ROOT
    / "baselines/china_e3_e7/e6_allocation_20260731/raw_runs.csv"
)


def dec(value: str) -> Decimal:
    return Decimal(value)


def dstr(value: Decimal) -> str:
    return format(value, "f")


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_source_pairs() -> list[dict[str, Any]]:
    rows = load_csv(SOURCE_RAW)
    by_key: dict[tuple[str, int], dict[str, dict[str, str]]] = {}
    for row in rows:
        if row["state"] not in {"I", "U"}:
            continue
        key = (row["instance_id"], int(row["seed"]))
        by_key.setdefault(key, {})[row["state"]] = row

    pairs: list[dict[str, Any]] = []
    for key in sorted(by_key):
        states = by_key[key]
        if set(states) != {"I", "U"}:
            raise AssertionError(f"incomplete I/U pair: {key}: {sorted(states)}")
        state_i = states["I"]
        state_u = states["U"]
        costs = {
            "I": dec(state_i["total_cost_cny"]),
            "U": dec(state_u["total_cost_cny"]),
        }
        profits = {
            "I": {
                member: dec(state_i[f"profit_{member}_cny"]) for member in MEMBERS
            },
            "U": {
                member: dec(state_u[f"profit_{member}_cny"]) for member in MEMBERS
            },
        }
        pairs.append(
            {
                "instance_id": key[0],
                "seed": key[1],
                "cost": costs,
                "profit": profits,
                "delta": costs["I"] - costs["U"],
            }
        )
    if len(pairs) != 20:
        raise AssertionError(f"expected 20 I/U pairs, found {len(pairs)}")
    return pairs


def crosscheck_allocation_input(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    allocation_rows = load_csv(ALLOCATION_RAW)
    indexed = {
        (row["instance_id"], int(row["seed"])): row for row in allocation_rows
    }
    if len(indexed) != 20:
        raise AssertionError(
            f"expected 20 allocation rows, found {len(indexed)}"
        )

    maximum_error = Decimal(0)
    fields_checked = 0
    for pair in pairs:
        key = (pair["instance_id"], pair["seed"])
        row = indexed[key]
        comparisons = [
            (pair["cost"]["I"], dec(row["system_cost_I_cny"])),
            (pair["cost"]["U"], dec(row["system_cost_U_cny"])),
            (pair["delta"], dec(row["system_saving_delta_cny"])),
        ]
        for member in MEMBERS:
            comparisons.extend(
                [
                    (
                        pair["profit"]["I"][member],
                        dec(row[f"profit_I_{member}_cny"]),
                    ),
                    (
                        pair["profit"]["U"][member],
                        dec(row[f"profit_U_{member}_cny"]),
                    ),
                ]
            )
        for source_value, allocation_value in comparisons:
            error = abs(source_value - allocation_value)
            maximum_error = max(maximum_error, error)
            fields_checked += 1

    if maximum_error > TOL:
        raise AssertionError(
            "allocation/source crosscheck failed: "
            f"max error {dstr(maximum_error)} > {dstr(TOL)}"
        )
    return {
        "pairs_checked": len(pairs),
        "fields_checked": fields_checked,
        "max_abs_error_cny": dstr(maximum_error),
        "tolerance_cny": dstr(TOL),
    }


def shapley_by_permutations(delta: Decimal) -> dict[str, Decimal]:
    def value(coalition: frozenset[str]) -> Decimal:
        return delta if coalition == frozenset(MEMBERS) else Decimal(0)

    marginal_sum = {member: Decimal(0) for member in MEMBERS}
    orderings = list(permutations(MEMBERS))
    for ordering in orderings:
        coalition: frozenset[str] = frozenset()
        for member in ordering:
            enlarged = coalition | {member}
            marginal_sum[member] += value(enlarged) - value(coalition)
            coalition = enlarged
    divisor = Decimal(len(orderings))
    return {member: marginal_sum[member] / divisor for member in MEMBERS}


def symbolic_shapley_coefficients() -> dict[str, Fraction]:
    """Return exact coefficients multiplying the symbol Delta."""

    def coeff(coalition: frozenset[str]) -> Fraction:
        return Fraction(1) if coalition == frozenset(MEMBERS) else Fraction(0)

    marginal_sum = {member: Fraction(0) for member in MEMBERS}
    orderings = list(permutations(MEMBERS))
    for ordering in orderings:
        coalition: frozenset[str] = frozenset()
        for member in ordering:
            enlarged = coalition | {member}
            marginal_sum[member] += coeff(enlarged) - coeff(coalition)
            coalition = enlarged
    return {
        member: marginal_sum[member] / len(orderings) for member in MEMBERS
    }


def verify(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    symbolic_coefficients = symbolic_shapley_coefficients()

    shapley_max_error = Decimal(0)
    core_width_max_error = Decimal(0)
    budget_balance_max_error = Decimal(0)
    direct_transfer_max_error = Decimal(0)
    direct_settlement_target_max_error = Decimal(0)
    member_profit_closure_max_error = Decimal(0)

    core_equivalence_mismatches = 0
    feasible_ir_member_violations = 0
    feasible_ir_unit_violations = 0
    negative_reference_ir_member_violations = 0
    negative_reference_ir_unit_violations = 0
    positive_delta_units = 0
    negative_delta_units = 0
    feasible_transfers: list[Decimal] = []
    feasible_member_gains: list[Decimal] = []
    negative_details: list[dict[str, str | int]] = []

    for pair in pairs:
        delta: Decimal = pair["delta"]
        profit_i: dict[str, Decimal] = pair["profit"]["I"]
        profit_u: dict[str, Decimal] = pair["profit"]["U"]
        phi = shapley_by_permutations(delta)
        for member in MEMBERS:
            shapley_max_error = max(
                shapley_max_error, abs(phi[member] - delta / Decimal(2))
            )

        changes = {
            member: profit_u[member] - profit_i[member] for member in MEMBERS
        }
        member_surplus = sum(changes.values(), Decimal(0))
        member_profit_closure_max_error = max(
            member_profit_closure_max_error, abs(member_surplus - delta)
        )

        damaged = min(MEMBERS, key=lambda member: (changes[member], member))
        payer = next(member for member in MEMBERS if member != damaged)
        lower = profit_i[damaged] - profit_u[damaged]
        upper = profit_u[payer] - profit_i[payer]
        interval_nonempty = lower <= upper
        delta_nonnegative = delta >= 0
        if interval_nonempty != delta_nonnegative:
            core_equivalence_mismatches += 1
        core_width_max_error = max(
            core_width_max_error, abs((upper - lower) - delta)
        )

        formula_transfer = lower + delta / Decimal(2)
        direct_transfer = profit_i[damaged] + phi[damaged] - profit_u[damaged]
        direct_transfer_max_error = max(
            direct_transfer_max_error, abs(formula_transfer - direct_transfer)
        )

        settled = {
            damaged: profit_u[damaged] + formula_transfer,
            payer: profit_u[payer] - formula_transfer,
        }
        pre_transfer_sum = sum(profit_u.values(), Decimal(0))
        post_transfer_sum = sum(settled.values(), Decimal(0))
        budget_balance_max_error = max(
            budget_balance_max_error, abs(post_transfer_sum - pre_transfer_sum)
        )
        for member in MEMBERS:
            direct_target = profit_i[member] + phi[member]
            direct_settlement_target_max_error = max(
                direct_settlement_target_max_error,
                abs(settled[member] - direct_target),
            )

        ir_violating_members = [
            member
            for member in MEMBERS
            if settled[member] < profit_i[member] - TOL
        ]
        if delta_nonnegative:
            positive_delta_units += 1
            feasible_transfers.append(formula_transfer)
            feasible_member_gains.extend(
                settled[member] - profit_i[member] for member in MEMBERS
            )
            feasible_ir_member_violations += len(ir_violating_members)
            feasible_ir_unit_violations += bool(ir_violating_members)
        else:
            negative_delta_units += 1
            negative_reference_ir_member_violations += len(ir_violating_members)
            negative_reference_ir_unit_violations += bool(ir_violating_members)
            negative_details.append(
                {
                    "instance_id": pair["instance_id"],
                    "seed": pair["seed"],
                    "cost_I_cny": dstr(pair["cost"]["I"]),
                    "cost_U_cny": dstr(pair["cost"]["U"]),
                    "delta_cny": dstr(delta),
                    "profit_I_D_guangzhou_cny": dstr(
                        profit_i["D_guangzhou"]
                    ),
                    "profit_U_D_guangzhou_cny": dstr(
                        profit_u["D_guangzhou"]
                    ),
                    "profit_I_D_shenzhen_cny": dstr(profit_i["D_shenzhen"]),
                    "profit_U_D_shenzhen_cny": dstr(profit_u["D_shenzhen"]),
                    "core_lower_cny": dstr(lower),
                    "core_upper_cny": dstr(upper),
                    "shapley_reference_transfer_cny": dstr(formula_transfer),
                }
            )

    checks = [
        {
            "id": "shapley_equal_split",
            "passed": (
                symbolic_coefficients["D_guangzhou"] == Fraction(1, 2)
                and symbolic_coefficients["D_shenzhen"] == Fraction(1, 2)
                and shapley_max_error <= TOL
            ),
            "symbolic_coefficients_of_delta": {
                member: str(symbolic_coefficients[member]) for member in MEMBERS
            },
            "units_enumerated": len(pairs),
            "max_abs_error_cny": dstr(shapley_max_error),
        },
        {
            "id": "core_nonempty_iff_delta_nonnegative",
            "passed": (
                core_equivalence_mismatches == 0
                and core_width_max_error <= TOL
            ),
            "units_checked": len(pairs),
            "equivalence_mismatches": core_equivalence_mismatches,
            "positive_delta_units": positive_delta_units,
            "negative_delta_units": negative_delta_units,
            "max_abs_interval_width_minus_delta_cny": dstr(
                core_width_max_error
            ),
        },
        {
            "id": "budget_balance",
            "passed": budget_balance_max_error <= TOL,
            "units_checked": len(pairs),
            "max_abs_error_cny": dstr(budget_balance_max_error),
        },
        {
            "id": "individual_rationality",
            "passed": (
                feasible_ir_member_violations == 0
                and feasible_ir_unit_violations == 0
                and negative_reference_ir_member_violations == 2
                and negative_reference_ir_unit_violations == 1
            ),
            "feasible_units_checked": positive_delta_units,
            "feasible_member_violations": feasible_ir_member_violations,
            "feasible_unit_violations": feasible_ir_unit_violations,
            "negative_delta_reference_member_violations_expected": (
                negative_reference_ir_member_violations
            ),
            "negative_delta_reference_unit_violations_expected": (
                negative_reference_ir_unit_violations
            ),
        },
        {
            "id": "transfer_formula_matches_direct_shapley",
            "passed": (
                direct_transfer_max_error <= TOL
                and direct_settlement_target_max_error <= TOL
            ),
            "units_checked": len(pairs),
            "max_abs_transfer_error_cny": dstr(direct_transfer_max_error),
            "max_abs_settled_profit_vs_direct_target_error_cny": dstr(
                direct_settlement_target_max_error
            ),
        },
        {
            "id": "negative_delta_no_budget_balanced_ir_transfer",
            "passed": (
                negative_delta_units == 1
                and len(negative_details) == 1
                and dec(negative_details[0]["core_lower_cny"])
                > dec(negative_details[0]["core_upper_cny"])
            ),
            "negative_units": negative_details,
            "proof": (
                "Let signed receipts be s_G and s_S. Budget balance gives "
                "s_G+s_S=0. Individual rationality requires "
                "s_G>=(Pi_G^I-Pi_G^U) and "
                "s_S>=(Pi_S^I-Pi_S^U). In the only negative unit these "
                "lower bounds sum to 1.135377416540>0, contradicting "
                "s_G+s_S=0."
            ),
        },
    ]

    passed_count = sum(bool(check["passed"]) for check in checks)
    mean_transfer = sum(feasible_transfers, Decimal(0)) / Decimal(
        len(feasible_transfers)
    )
    mean_member_gain = sum(feasible_member_gains, Decimal(0)) / Decimal(
        len(feasible_member_gains)
    )
    return {
        "status": "PASS" if passed_count == len(checks) else "FAIL",
        "math_checks_total": len(checks),
        "math_checks_passed": passed_count,
        "tolerance_cny": dstr(TOL),
        "source_files": {
            "e6_v3_raw_runs": str(SOURCE_RAW.relative_to(REPO_ROOT)),
            "allocation_raw_runs_crosscheck": str(
                ALLOCATION_RAW.relative_to(REPO_ROOT)
            ),
        },
        "source_crosscheck": crosscheck_allocation_input(pairs),
        "checks": checks,
        "summary": {
            "units": len(pairs),
            "feasible_units": positive_delta_units,
            "infeasible_units": negative_delta_units,
            "budget_balance_max_abs_error_cny": dstr(
                budget_balance_max_error
            ),
            "individual_rationality_violations_feasible_members": (
                feasible_ir_member_violations
            ),
            "individual_rationality_violations_feasible_units": (
                feasible_ir_unit_violations
            ),
            "member_profit_vs_system_delta_max_abs_closure_error_cny": dstr(
                member_profit_closure_max_error
            ),
            "mean_shapley_transfer_feasible_units_cny": dstr(mean_transfer),
            "mean_member_gain_feasible_units_cny": dstr(mean_member_gain),
        },
    }


def main() -> int:
    result = verify(load_source_pairs())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
