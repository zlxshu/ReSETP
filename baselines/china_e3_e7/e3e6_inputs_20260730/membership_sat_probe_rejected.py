#!/usr/bin/env python3
"""Exact destination-membership SAT probe with frozen First-Fit lazy cuts."""

from __future__ import annotations

import argparse
import sys
from time import perf_counter
from typing import Any

import build_inputs as builder


def load_z3() -> Any:
    try:
        import z3  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        system_site = (
            "/Library/Frameworks/Python.framework/Versions/3.14/"
            "lib/python3.14/site-packages"
        )
        if system_site not in sys.path:
            sys.path.append(system_site)
        import z3  # type: ignore[import-not-found]
    return z3


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", required=True)
    parser.add_argument("--intensity", type=int, required=True)
    parser.add_argument("--progress-every", type=int, default=1000)
    args = parser.parse_args()

    z3 = load_z3()
    runner = builder.load_runner()
    bundle = runner.e3.load_bundle(args.instance)
    original, target, selected, _ineligible, failure = (
        builder.prepare_selection(runner, bundle, args.intensity)
    )
    if failure is not None:
        print(f"INFEASIBLE_SELECTION {failure}", flush=True)
        return
    options = [
        [
            destination
            for absolute_rank, destination in enumerate(
                item["ranking"], start=1
            )
            if absolute_rank != 1 and destination != item["owner"]
        ]
        for item in selected
    ]
    variables = [
        [
            z3.Bool(f"choice_{selected_index}_{option_index}")
            for option_index in range(len(item_options))
        ]
        for selected_index, item_options in enumerate(options)
    ]
    solver = z3.Solver()
    for item_variables in variables:
        solver.add(
            z3.PbEq(
                [(variable, 1) for variable in item_variables],
                1,
            )
        )

    nodes = {
        node.node_id: node
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    payload = int(
        round(
            bundle.instance.payload_capacity_kg(
                "cv", fallback=float(bundle.prices.Q_capacity)
            )
        )
    )
    depots = runner._depot_ids(bundle)
    for depot_id in depots:
        fixed_demand = sum(
            int(round(nodes[customer_id].demand))
            for customer_id, owner in original.items()
            if owner == depot_id
            and customer_id not in {
                item["customer_id"] for item in selected
            }
        )
        terms = []
        for selected_index, item in enumerate(selected):
            demand = int(round(nodes[item["customer_id"]].demand))
            for option_index, destination in enumerate(
                options[selected_index]
            ):
                if destination == depot_id:
                    terms.append(
                        (variables[selected_index][option_index], demand)
                    )
        cap = bundle.fleet_caps_by_depot[depot_id]
        total_cap = int(cap["num_cv"]) + int(cap["num_ev"])
        solver.add(
            z3.PbLe(
                terms,
                total_cap * payload - fixed_demand,
            )
        )

    cuts: set[tuple[str, tuple[bool, ...]]] = set()
    started = perf_counter()
    models = 0
    while True:
        status = solver.check()
        if status == z3.unsat:
            print(
                f"UNSAT models={models} cuts={len(cuts)} "
                f"elapsed={perf_counter() - started:.6f}s",
                flush=True,
            )
            return
        if status != z3.sat:
            raise RuntimeError(
                f"membership SAT unknown: {solver.reason_unknown()}"
            )
        models += 1
        model = solver.model()
        chosen = [
            next(
                option_index
                for option_index, variable in enumerate(item_variables)
                if z3.is_true(model.eval(variable))
            )
            for item_variables in variables
        ]
        mapping = dict(original)
        for selected_index, item in enumerate(selected):
            mapping[item["customer_id"]] = options[selected_index][
                chosen[selected_index]
            ]
        remapped = runner.e3.with_responsibility(bundle, mapping)
        failing: list[str] = []
        route_groups: dict[str, list[list[str]]] = {}
        for depot_id in depots:
            try:
                groups = runner.e3._pack_depot(remapped, depot_id)
            except Exception:
                failing.append(depot_id)
                continue
            route_groups[depot_id] = groups
            caps = bundle.fleet_caps_by_depot[depot_id]
            total_cap = int(caps["num_cv"]) + int(caps["num_ev"])
            if len(groups) > total_cap:
                failing.append(depot_id)
        if not failing:
            actual = sum(
                mapping[customer_id] != original[customer_id]
                for customer_id in original
            )
            if actual != target:
                raise RuntimeError("mismatch target drift")
            print(
                f"SAT models={models} cuts={len(cuts)} "
                f"elapsed={perf_counter() - started:.6f}s",
                flush=True,
            )
            return
        for depot_id in failing:
            pattern = tuple(
                mapping[item["customer_id"]] == depot_id
                for item in selected
                if depot_id in options[
                    selected.index(item)
                ]
            )
            key = (depot_id, pattern)
            if key in cuts:
                raise RuntimeError("duplicate membership cut")
            cuts.add(key)
            literals = []
            pattern_index = 0
            for selected_index, item_options in enumerate(options):
                matching = [
                    variables[selected_index][option_index]
                    for option_index, destination in enumerate(item_options)
                    if destination == depot_id
                ]
                if not matching:
                    continue
                membership = z3.Or(*matching)
                literals.append(
                    z3.Not(membership)
                    if pattern[pattern_index]
                    else membership
                )
                pattern_index += 1
            solver.add(z3.Or(*literals))
        if models % args.progress_every == 0:
            print(
                f"PROGRESS models={models} cuts={len(cuts)} "
                f"elapsed={perf_counter() - started:.6f}s",
                flush=True,
            )


if __name__ == "__main__":
    main()
