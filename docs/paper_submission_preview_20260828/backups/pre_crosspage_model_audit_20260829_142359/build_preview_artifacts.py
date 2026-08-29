#!/usr/bin/env python3
"""Export existing and newly run evidence into the fixed paper exhibit shapes."""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
FIGURES = HERE / "generated_figures"
TABLES = HERE / "generated_tables"
REPRESENTATIVE = REPO / "solver/reports/paper_submission_preview_20260828/representative_full/seed_11/best_solution.json"
PUBLIC_CONVERGENCE = REPO / "solver/reports/submission_fallback_20260824/01_public_seed11_full/PR17B_independent_seed11/raw_runs.csv"
APPROVED = REPO / "docs/paper_gci_dmm_vrp_20260804/tex_draft_v2_20260819"
DEPOT_LABELS = {
    "D_OSM_WAY_1003511503": "D1",
    "D_OSM_WAY_1071205721": "D2",
}

for source in (REPO / "solver/src", REPO / "solver/scripts", REPO / "models/src", REPO / "third_party/setp_hgs_kernel"):
    sys.path.insert(0, str(source))

from run_problem_hgs_private_technical import (  # noqa: E402
    DEPOT_SEARCH_INSTANCE_ID,
    ENDOGENOUS_FLEET_PARAMETERS,
    _build_context,
    _with_registered_idle_duties,
)
from setp_solver.algorithms.problem_hgs.evaluation import DutyFullEvaluator  # noqa: E402
from setp_solver.algorithms.problem_hgs.model import DutyIndividual  # noqa: E402
from setp_solver.cost import (  # noqa: E402
    _evaluate_route,
    charging_action_electricity_cost,
    charging_action_emissions_kg,
    diesel_price_for_route,
)
from setp_solver.search.metaheuristic_baselines import solution_from_dict  # noqa: E402
from setp_solver.solution import physical_vehicle_id  # noqa: E402


def _clock(second: float) -> str:
    minute = int(round(float(second) / 60.0))
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _trip_rows() -> list[dict[str, object]]:
    payload = json.loads(REPRESENTATIVE.read_text(encoding="utf-8"))
    bundle, _initial, _pi0, context = _build_context(
        REPO,
        DEPOT_SEARCH_INSTANCE_ID,
        fleet_parameters=ENDOGENOUS_FLEET_PARAMETERS,
    )
    solution = solution_from_dict(payload["evaluation"]["prepared_solution"])
    individual = _with_registered_idle_duties(DutyIndividual.from_solution(solution), bundle)
    evaluation = DutyFullEvaluator(context).evaluate(individual)
    schedules = {item.route_id: item for item in evaluation.certificate.trips}
    actions = defaultdict(list)
    for action in evaluation.prepared_solution.charging_actions:
        actions[action.vehicle_id].append(action)
    seen_vehicles: set[str] = set()
    rows = []
    for route in evaluation.prepared_solution.routes:
        schedule = schedules[route.vehicle_id]
        energy = _evaluate_route(route, bundle.instance, bundle.instance.node_lookup, bundle.prices)
        vehicle = physical_vehicle_id(route.vehicle_id)
        fixed = 0.0
        if vehicle not in seen_vehicles:
            seen_vehicles.add(vehicle)
            fixed = bundle.instance.vehicle_fixed_cost_per_day(
                route.vehicle_type,
                fallback=bundle.prices.vehicle_fixed_cost,
            )
        distance_cost = energy.distance_m / 1000.0 * bundle.instance.non_energy_distance_cost_per_km(
            route.vehicle_type,
            fallback=bundle.prices.c_km,
        )
        fuel_cost = 0.0
        direct_emissions = 0.0
        if route.vehicle_type.lower() == "cv":
            fuel_cost = energy.fuel_liters * diesel_price_for_route(route, bundle.instance, bundle.prices)
            direct_emissions = energy.fuel_liters * bundle.prices.diesel_ef
        route_actions = actions[route.vehicle_id]
        electricity_cost = sum(
            charging_action_electricity_cost(action, bundle.instance, bundle.time_profile, bundle.prices)
            for action in route_actions
        )
        indirect_emissions = sum(
            charging_action_emissions_kg(action, bundle.instance, bundle.time_profile, bundle.prices)
            for action in route_actions
        )
        emissions = direct_emissions + indirect_emissions
        carbon_cost = emissions * bundle.prices.carbon_price
        customers = route.node_sequence[1:-1]
        path = [
            DEPOT_LABELS[node_id] if node_id in DEPOT_LABELS else str(int(node_id.removeprefix("C")))
            for node_id in route.node_sequence
        ]
        load_kg = sum(float(bundle.instance.node_lookup[node_id].demand) for node_id in customers)
        capacity_kg = bundle.instance.payload_capacity_kg(
            route.vehicle_type,
            fallback=bundle.prices.Q_capacity,
        )
        rows.append({
            "path": f"[{','.join(path)}]",
            "distance_km": energy.distance_m / 1000.0,
            "cost_cny": fixed + distance_cost + fuel_cost + electricity_cost + carbon_cost,
            "duration_h": (schedule.return_second - schedule.departure_second) / 3600.0,
            "fuel_l": energy.fuel_liters if route.vehicle_type.lower() == "cv" else 0.0,
            "electricity_kwh": energy.ev_drive_kwh if route.vehicle_type.lower() == "ev" else 0.0,
            "emissions_kg": emissions,
            "num": len(customers),
            "load_rate_pct": 100.0 * load_kg / capacity_kg,
        })
    return rows


def _write_trip_rows(rows: list[dict[str, object]]) -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    with (TABLES / "final_solution_trip_rows.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    latex = []
    for row in rows:
        latex.append(
            f"{{{row['path']}}} & {row['distance_km']:.2f} & {row['cost_cny']:.2f} & "
            f"{row['duration_h']:.2f} & {row['fuel_l']:.2f} & {row['electricity_kwh']:.2f} & "
            f"{row['emissions_kg']:.2f} & {row['num']} & {row['load_rate_pct']:.2f} \\\\"
        )
    numeric = ("distance_km", "cost_cny", "duration_h", "fuel_l", "electricity_kwh", "emissions_kg")
    means = {key: sum(float(row[key]) for row in rows) / len(rows) for key in numeric}
    totals = {key: sum(float(row[key]) for row in rows) for key in numeric}
    mean_load = sum(float(row["load_rate_pct"]) for row in rows) / len(rows)
    total_num = sum(int(row["num"]) for row in rows)
    latex.extend([
        "\\midrule",
        f"均值 & {means['distance_km']:.2f} & {means['cost_cny']:.2f} & {means['duration_h']:.2f} & "
        f"{means['fuel_l']:.2f} & {means['electricity_kwh']:.2f} & {means['emissions_kg']:.2f} & -- & {mean_load:.2f} \\\\",
        f"合计 & {totals['distance_km']:.2f} & {totals['cost_cny']:.2f} & {totals['duration_h']:.2f} & "
        f"{totals['fuel_l']:.2f} & {totals['electricity_kwh']:.2f} & {totals['emissions_kg']:.2f} & {total_num} & -- \\\\",
        "\\bottomrule",
    ])
    (TABLES / "final_solution_trip_rows.tex").write_text("\n".join(latex) + "\n", encoding="utf-8")


def _approved_figure_module():
    spec = importlib.util.spec_from_file_location("approved_figures", APPROVED / "build_approved_figures.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module.OUT_DIR = FIGURES
    module.add_figure_title = lambda _fig, _title: None
    return module


def _build_time_varying_carbon_figure() -> None:
    """Draw the experiment input using the registered 24-hour carbon series."""
    module = _approved_figure_module()
    hourly = module.read_csv(APPROVED / "data/figure3_hourly_source.csv")
    carbon = module.np.array([float(row["碳强度_kgCO2e每kWh"]) for row in hourly])
    hours = module.np.arange(25, dtype=float)

    fig, ax = module.plt.subplots(figsize=(6.15, 1.45))
    fig.subplots_adjust(left=0.10, right=0.99, top=0.95, bottom=0.28)
    ax.step(
        hours,
        module.np.r_[carbon, carbon[-1]],
        where="post",
        color="black",
        linewidth=module.CURVE_WIDTH_PT,
    )
    ax.set_xlim(0, 24)
    ax.set_ylim(0.10, 0.70)
    ax.set_xticks([0, 4, 8, 12, 16, 20, 24])
    ax.set_xlabel("时刻", fontproperties=module.CN)
    ax.set_ylabel("电网碳强度（kgCO$_2$e/kWh）", fontproperties=module.CN)
    module.style_axes(ax)
    module.save_pdf(fig, "figure_experiment_carbon_intensity", "北京50客户代表算例的逐时电网碳强度")


def _build_carbon_charging_figure() -> None:
    """Fill the paper's fixed two-panel carbon/price charging framework."""
    FIGURES.mkdir(parents=True, exist_ok=True)
    module = _approved_figure_module()
    hourly = module.read_csv(APPROVED / "data/figure3_hourly_source.csv")
    if len(hourly) != 24:
        raise RuntimeError("Figure 3 requires exactly 24 hourly rows")

    hours = module.np.arange(24, dtype=float)
    carbon = module.np.array([float(row["碳强度_kgCO2e每kWh"]) for row in hourly])
    price = module.np.array([float(row["场内电价_元每kWh"]) for row in hourly])
    asap = module.np.array([float(row["ASAP充电量_kWh"]) for row in hourly])
    aware = module.np.array([float(row["碳感知充电量_kWh"]) for row in hourly])

    fig, axes = module.plt.subplots(1, 2, figsize=(6.48, 2.05), sharex=True)
    fig.subplots_adjust(left=0.08, right=0.93, top=0.95, bottom=0.24, wspace=0.43)
    signal_specs = (
        (axes[0], carbon, "电网碳强度（kgCO$_2$e/kWh）", "(a)"),
        (axes[1], price, "分时电价（元/kWh）", "(b)"),
    )
    for ax, signal, ylabel, panel in signal_specs:
        load_ax = ax.twinx()
        width = 0.36
        load_ax.bar(hours - width / 2, asap, width=width, color="0.78", edgecolor="black", linewidth=0.35, hatch="...")
        load_ax.bar(hours + width / 2, aware, width=width, color="0.40", edgecolor="black", linewidth=0.35, hatch="///")
        ax.step(
            module.np.arange(25),
            module.np.r_[signal, signal[-1]],
            where="post",
            color="black",
            linewidth=module.CURVE_WIDTH_PT,
            zorder=3,
        )
        ax.set_xlim(-0.5, 24)
        ax.set_ylabel(ylabel, fontproperties=module.CN)
        load_ax.set_ylabel("充电量（kWh）", fontproperties=module.CN)
        module.style_axes(ax)
        module.style_axes(load_ax)
        ax.text(0.01, 0.98, panel, transform=ax.transAxes, ha="left", va="top", fontproperties=module.EN)
        handles = [
            module.Patch(facecolor="0.78", edgecolor="black", hatch="..."),
            module.Patch(facecolor="0.40", edgecolor="black", hatch="///"),
        ]
        labels = ["有空即充", "碳感知充电"]
        legend = load_ax.legend(handles, labels, loc="upper right", borderpad=0.25, handlelength=1.3, labelspacing=0.20)
        module.tune_legend(legend, labels)
    for ax in axes:
        ax.set_xticks([0, 4, 8, 12, 16, 20, 24])
        ax.set_xlabel("时刻", fontproperties=module.CN)
    module.save_pdf(fig, "figure_3_carbon_tariff_charging", "图3  分时电价、电网碳强度与车辆充电时刻")


def _build_fleet_carbon_figure() -> None:
    root = REPO / "solver/reports/paper_submission_preview_20260828/missing_static/carbon_fleet"
    price_dirs = sorted((path for path in root.glob("*") if path.is_dir()), key=lambda path: float(path.name))
    series: list[tuple[float, float, float]] = []
    for price_dir in price_dirs:
        counts = []
        for seed_dir in sorted(price_dir.glob("seed_*")):
            result = seed_dir / "best_solution.json"
            if not result.is_file():
                continue
            routes = json.loads(result.read_text(encoding="utf-8"))["evaluation"]["prepared_solution"]["routes"]
            vehicles = {(route["vehicle_id"].split("#", 1)[0], route["vehicle_type"].lower()) for route in routes}
            counts.append((sum(kind == "cv" for _, kind in vehicles), sum(kind == "ev" for _, kind in vehicles)))
        if len(counts) == 3:
            series.append((float(price_dir.name), sum(item[0] for item in counts) / 3, sum(item[1] for item in counts) / 3))
    if len(series) != 6:
        return

    module = _approved_figure_module()
    fig, ax = module.plt.subplots(figsize=(6.15, 1.65))
    fig.subplots_adjust(left=0.10, right=0.99, top=0.95, bottom=0.27)
    prices = [item[0] for item in series]
    cv_counts = [item[1] for item in series]
    ev_counts = [item[2] for item in series]
    ax.plot(prices, cv_counts, color="black", marker="o", markersize=3.0, markerfacecolor="white", linewidth=module.CURVE_WIDTH_PT)
    ax.plot(prices, ev_counts, color="0.40", linestyle="--", marker="^", markersize=3.2, markerfacecolor="white", linewidth=module.CURVE_WIDTH_PT)
    ax.set_xlim(0, 2.2)
    ax.set_xticks(prices)
    ax.set_ylim(bottom=0)
    ax.set_xlabel("单位碳价（元/千克二氧化碳当量）", fontproperties=module.CN)
    ax.set_ylabel("车辆数（辆）", fontproperties=module.CN)
    module.style_axes(ax)
    labels = ["燃油车", "电动车"]
    legend = ax.legend(labels, loc="upper right", borderpad=0.35, handlelength=2.4, labelspacing=0.25)
    module.tune_legend(legend, labels)
    module.save_pdf(fig, "figure_4_mixed_fleet", "图4  不同碳价下的车辆派遣数量")


def _build_public_convergence_figure() -> None:
    module = _approved_figure_module()
    rows = list(csv.DictReader(PUBLIC_CONVERGENCE.open(encoding="utf-8")))
    iterations = [int(row["iteration"]) for row in rows]
    costs = [float(row["best_cost"]) / 1000.0 for row in rows]
    fig, ax = module.plt.subplots(figsize=(2.95, 2.20))
    fig.subplots_adjust(left=0.23, right=0.96, top=0.95, bottom=0.22)
    ax.step(iterations, costs, where="post", color="black", linewidth=module.CURVE_WIDTH_PT)
    ax.set_xlim(iterations[0], iterations[-1])
    ax.set_xlabel("迭代次数", fontproperties=module.CN)
    ax.set_ylabel("当前最优距离", fontproperties=module.CN)
    module.style_axes(ax)
    module.save_pdf(fig, "figure_2_public_pr17b_convergence", "图2  本文算法在PR17B上的收敛过程")


def main() -> None:
    rows = _trip_rows()
    _write_trip_rows(rows)
    _build_time_varying_carbon_figure()
    _build_public_convergence_figure()
    _build_carbon_charging_figure()
    _build_fleet_carbon_figure()
    print(json.dumps({"trip_rows": len(rows), "figures": sorted(path.name for path in FIGURES.glob("*.pdf"))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
