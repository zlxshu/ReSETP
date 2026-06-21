from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path
from typing import Iterable

import numpy as np

from .config import ScenarioConfig
from .evrptwmf import BaseDistribution, load_base_distribution, pairwise_distances, parse_evrptwmf
from .models import CandidateScore, DynamicEvent, Node, Scenario
from .validation import validate_scenario


def generate_scenario(config: ScenarioConfig) -> Scenario:
    if config.n_depots < 1 or config.n_stations < 0 or config.n_customers < 1:
        raise ValueError("n_depots >= 1, n_stations >= 0, and n_customers >= 1 are required")

    rng = np.random.default_rng(config.seed)
    base = load_base_distribution(config.base_instance_path)

    customer_xy = _generate_customer_xy(config, rng, base)
    demand = _generate_demand(config, rng, base)
    ready, due, service = _generate_time_windows(config, rng, base)

    base_depot_xy = _exact_base_facility_xy(config, base, "depot")
    depot_xy, depot_scores = _select_depots(customer_xy, demand, ready, due, service, config, rng, initial_xy=base_depot_xy)
    base_station_xy = _exact_base_facility_xy(config, base, "station")
    station_xy, station_scores = _select_stations(customer_xy, depot_xy, config, rng, initial_xy=base_station_xy)

    nodes = _build_nodes(customer_xy, demand, ready, due, service, depot_xy, station_xy, config)
    distance_matrix = pairwise_distances(np.asarray([(node.x, node.y) for node in nodes], dtype=float))
    dynamic_events = _generate_dynamic_events(nodes, config, rng)

    scenario = Scenario(
        scenario_id=config.scenario_id,
        seed=config.seed,
        nodes=nodes,
        distance_matrix=distance_matrix,
        depot_scores=depot_scores,
        station_scores=station_scores,
        dynamic_events=dynamic_events,
        metadata={
            "coord_mode": config.coord_mode,
            "demand_mode": config.demand_mode,
            "time_window_mode": config.time_window_mode,
            "base_instance_path": config.base_instance_path or "",
            # v2026-06-12: record fleet composition so solver search gates do not fall back to paper defaults.
            "num_cv": config.num_cv,
            "num_ev": config.num_ev,
            "time_window_shift_seconds": config.time_window_shift_seconds,
            "empirical_exact_base": config.empirical_exact_base,
            "depot_due_time": config.depot_due_time,
            "design_note": "Autonomous Python generator inspired by candidate scoring and manifest provenance, not a MATLAB port.",
        },
    )
    scenario.validation = validate_scenario(nodes, distance_matrix, config)
    return scenario


def _generate_customer_xy(config: ScenarioConfig, rng: np.random.Generator, base: BaseDistribution | None) -> np.ndarray:
    if config.coord_mode == "empirical" and base and base.has_data:
        src = base.customer_xy
        if config.empirical_exact_base and config.n_customers <= len(src):
            # v2026-06-12: Q1 shifted bundle preserves the Goeke customer layout exactly.
            return src[: config.n_customers].copy()
        idx = rng.integers(0, len(src), size=config.n_customers)
        scale = max(np.ptp(src[:, 0]), np.ptp(src[:, 1]), 1.0)
        jitter = rng.normal(0.0, scale * 0.015, size=(config.n_customers, 2))
        return _enforce_min_distance(src[idx] + jitter, config.min_customer_distance, rng, config.coord_bounds)

    xmin, xmax, ymin, ymax = config.coord_bounds
    centers = np.column_stack(
        [
            rng.uniform(xmin + 0.15 * (xmax - xmin), xmax - 0.15 * (xmax - xmin), config.n_customer_clusters),
            rng.uniform(ymin + 0.15 * (ymax - ymin), ymax - 0.15 * (ymax - ymin), config.n_customer_clusters),
        ]
    )
    labels = rng.integers(0, config.n_customer_clusters, size=config.n_customers)
    span = max(xmax - xmin, ymax - ymin)
    xy = centers[labels] + rng.normal(0.0, span * config.cluster_std_ratio, size=(config.n_customers, 2))
    xy[:, 0] = np.clip(xy[:, 0], xmin, xmax)
    xy[:, 1] = np.clip(xy[:, 1], ymin, ymax)
    return _enforce_min_distance(xy, config.min_customer_distance, rng, config.coord_bounds)


def _generate_demand(config: ScenarioConfig, rng: np.random.Generator, base: BaseDistribution | None) -> np.ndarray:
    cap = config.vehicle_capacity * config.max_customer_demand_ratio
    mode = config.demand_mode.lower()
    if mode == "empirical" and base and len(base.customer_demand):
        if config.empirical_exact_base and config.n_customers <= len(base.customer_demand):
            # v2026-06-12: Q1 shifted bundle preserves Goeke demands exactly.
            values = base.customer_demand[: config.n_customers].copy()
        else:
            values = rng.choice(base.customer_demand, size=config.n_customers, replace=True)
            values = values * rng.uniform(0.9, 1.1, size=config.n_customers)
    elif mode == "uniform":
        values = rng.uniform(config.demand_min, cap, size=config.n_customers)
    elif mode == "gamma":
        shape = max((config.demand_mean / max(config.demand_std, 1.0)) ** 2, 0.5)
        scale = config.demand_mean / shape
        values = rng.gamma(shape, scale, size=config.n_customers)
    elif mode == "lognormal":
        sigma2 = math.log(1 + (config.demand_std / max(config.demand_mean, 1.0)) ** 2)
        mu = math.log(max(config.demand_mean, 1.0)) - sigma2 / 2
        values = rng.lognormal(mu, math.sqrt(sigma2), size=config.n_customers)
    else:
        values = _truncated_normal(rng, config.demand_mean, config.demand_std, config.demand_min, cap, config.n_customers)
    return np.round(np.clip(values, config.demand_min, cap), 1)


def _generate_time_windows(
    config: ScenarioConfig,
    rng: np.random.Generator,
    base: BaseDistribution | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = config.n_customers
    mode = config.time_window_mode.lower()
    if mode == "empirical" and base and len(base.ready_time):
        if config.empirical_exact_base and n <= len(base.ready_time):
            # v2026-06-12: Q1 exact base mode shifts all customer windows by +28800s.
            idx = np.arange(n)
            widths = base.due_time[idx] - base.ready_time[idx]
            starts = base.ready_time[idx] + float(config.time_window_shift_seconds)
            service = base.service_time[idx]
        else:
            idx = rng.integers(0, len(base.ready_time), size=n)
            widths = np.maximum(base.due_time[idx] - base.ready_time[idx], config.time_window_min_width)
            starts = base.ready_time[idx] + float(config.time_window_shift_seconds) + rng.normal(0, 0.03 * max(config.horizon_end - config.horizon_start, 1), size=n)
            service = np.maximum(base.service_time[idx], config.service_time_min)
    elif mode == "tight":
        widths = rng.uniform(config.time_window_min_width, min(config.time_window_max_width, config.time_window_min_width * 2.0), size=n)
        latest_start = np.maximum(config.horizon_start, config.horizon_end - widths)
        starts = rng.uniform(config.horizon_start, latest_start)
        service = rng.uniform(config.service_time_min, min(config.service_time_max, config.service_time_min * 2.0), size=n)
    elif mode == "clustered":
        centers = np.asarray([0.25, 0.50, 0.75]) * (config.horizon_end - config.horizon_start) + config.horizon_start
        chosen = rng.choice(centers, size=n, replace=True)
        widths = rng.uniform(config.time_window_min_width, config.time_window_max_width * 0.65, size=n)
        starts = chosen - widths / 2.0 + rng.normal(0.0, config.time_window_min_width * 0.35, size=n)
        service = rng.uniform(config.service_time_min, config.service_time_max, size=n)
    elif mode == "mixed":
        sub_modes = rng.choice(["uniform", "tight", "clustered"], size=n, p=[0.45, 0.25, 0.30])
        starts = np.zeros(n)
        widths = np.zeros(n)
        service = np.zeros(n)
        for i, sub_mode in enumerate(sub_modes):
            sub_cfg = replace(config, n_customers=1, time_window_mode=str(sub_mode))
            r, d, s = _generate_time_windows(sub_cfg, rng, None)
            starts[i] = r[0]
            widths[i] = d[0] - r[0]
            service[i] = s[0]
    else:
        widths = rng.uniform(config.time_window_min_width, config.time_window_max_width, size=n)
        latest_start = np.maximum(config.horizon_start, config.horizon_end - widths)
        starts = rng.uniform(config.horizon_start, latest_start)
        service = rng.uniform(config.service_time_min, config.service_time_max, size=n)
    ready = np.clip(starts, config.horizon_start, config.horizon_end - config.time_window_min_width)
    due = np.minimum(ready + widths, config.horizon_end)
    if config.empirical_exact_base and mode == "empirical" and base and len(base.ready_time):
        service = np.minimum(service, np.maximum(due - ready, 0.0))
    else:
        service = np.minimum(service, np.maximum(due - ready, config.service_time_min))
    return np.round(ready, 1), np.round(due, 1), np.round(service, 1)


def _exact_base_facility_xy(config: ScenarioConfig, base: BaseDistribution | None, role: str) -> np.ndarray | None:
    if not (config.empirical_exact_base and config.coord_mode == "empirical" and base and base.has_data):
        return None
    if role == "depot" and len(base.depot_xy):
        return base.depot_xy[: config.n_depots].copy()
    if role == "station" and len(base.station_xy):
        return base.station_xy[: config.n_stations].copy()
    return None


def _select_depots(
    customer_xy: np.ndarray,
    demand: np.ndarray,
    ready: np.ndarray,
    due: np.ndarray,
    service: np.ndarray,
    config: ScenarioConfig,
    rng: np.random.Generator,
    initial_xy: np.ndarray | None = None,
) -> tuple[np.ndarray, list[CandidateScore]]:
    candidates = _depot_candidates(customer_xy, config, rng)
    selected: list[np.ndarray] = []
    all_scores: list[CandidateScore] = []
    current_distance = np.full(len(customer_xy), np.inf)
    if initial_xy is not None and len(initial_xy):
        for i, xy in enumerate(np.asarray(initial_xy, dtype=float)[: config.n_depots]):
            selected.append(np.asarray(xy, dtype=float))
            current_distance = np.minimum(current_distance, np.linalg.norm(customer_xy - selected[-1], axis=1))
            all_scores.append(
                CandidateScore(
                    candidate_id=f"D_BASE_{i:02d}",
                    role="depot",
                    x=float(selected[-1][0]),
                    y=float(selected[-1][1]),
                    score=1.0,
                    coverage_score=1.0,
                    balance_score=1.0,
                    distance_score=1.0,
                    separation_score=1.0,
                    feasibility_score=1.0,
                    selected=True,
                )
            )

    for _ in range(max(config.n_depots - len(selected), 0)):
        scored = [
            _score_depot_candidate(cand, customer_xy, demand, ready, due, service, selected, current_distance, config, i)
            for i, cand in enumerate(candidates)
            if not _too_close_to_selected(cand, selected, config.min_depot_distance)
        ]
        if not scored:
            raise ValueError("No feasible depot candidates; relax min_depot_distance or coordinate bounds")
        scored.sort(key=lambda row: row.score, reverse=True)
        chosen = scored[0]
        chosen.selected = True
        selected.append(np.asarray([chosen.x, chosen.y], dtype=float))
        current_distance = np.minimum(current_distance, np.linalg.norm(customer_xy - selected[-1], axis=1))
        all_scores.extend(scored[: min(50, len(scored))])

    selected_xy = np.asarray(selected, dtype=float)
    return selected_xy, _dedupe_scores(all_scores)


def _depot_candidates(customer_xy: np.ndarray, config: ScenarioConfig, rng: np.random.Generator) -> np.ndarray:
    centers = _kmeans_like(customer_xy, max(config.n_depots, min(config.n_customer_clusters, len(customer_xy))), rng, iterations=12)
    xmin, xmax, ymin, ymax = config.coord_bounds
    random = np.column_stack([rng.uniform(xmin, xmax, 120), rng.uniform(ymin, ymax, 120)])
    quantile_points = np.asarray(
        [
            [np.quantile(customer_xy[:, 0], qx), np.quantile(customer_xy[:, 1], qy)]
            for qx in (0.2, 0.5, 0.8)
            for qy in (0.2, 0.5, 0.8)
        ],
        dtype=float,
    )
    return np.vstack([centers, quantile_points, random])


def _score_depot_candidate(
    cand: np.ndarray,
    customer_xy: np.ndarray,
    demand: np.ndarray,
    ready: np.ndarray,
    due: np.ndarray,
    service: np.ndarray,
    selected: list[np.ndarray],
    current_distance: np.ndarray,
    config: ScenarioConfig,
    idx: int,
) -> CandidateScore:
    dist = np.linalg.norm(customer_xy - cand, axis=1)
    if selected:
        improvement = np.maximum(current_distance - dist, 0.0)
        assigned = dist < current_distance
    else:
        center = np.mean(customer_xy, axis=0)
        baseline = np.linalg.norm(customer_xy - center, axis=1)
        improvement = np.maximum(baseline - dist, 0.0)
        assigned = dist <= np.quantile(dist, 0.55)
    total_demand = max(float(np.sum(demand)), 1.0)
    demand_share = float(np.sum(demand[assigned]) / total_demand)
    target_share = 1.0 / max(config.n_depots, 1)
    balance = 1.0 - min(abs(demand_share - target_share) / max(target_share, 1e-9), 1.0)
    distance_score = float(np.sum(improvement) / max(np.sum(np.maximum(current_distance[np.isfinite(current_distance)], 1.0)), np.sum(dist), 1.0))
    coverage_score = float(np.mean(dist <= np.quantile(dist, 0.5)))
    if selected:
        separation = min(float(np.linalg.norm(cand - s)) for s in selected)
        separation_score = min(separation / max(config.min_depot_distance, 1.0), 1.5) / 1.5
    else:
        separation_score = 1.0
    round_trip = 2.0 * dist
    feasible = ready + round_trip + service <= due
    feasibility_score = float(np.mean(feasible))
    score = 0.30 * coverage_score + 0.25 * balance + 0.25 * distance_score + 0.10 * separation_score + 0.10 * feasibility_score
    return CandidateScore(
        candidate_id=f"D_CAND_{idx:04d}",
        role="depot",
        x=float(cand[0]),
        y=float(cand[1]),
        score=float(score),
        coverage_score=coverage_score,
        balance_score=balance,
        distance_score=distance_score,
        separation_score=separation_score,
        feasibility_score=feasibility_score,
    )


def _select_stations(
    customer_xy: np.ndarray,
    depot_xy: np.ndarray,
    config: ScenarioConfig,
    rng: np.random.Generator,
    initial_xy: np.ndarray | None = None,
) -> tuple[np.ndarray, list[CandidateScore]]:
    if config.n_stations == 0:
        return np.zeros((0, 2)), []
    candidates = _station_candidates(customer_xy, depot_xy, config, rng)
    all_nodes = np.vstack([depot_xy, customer_xy])
    selected: list[np.ndarray] = []
    scores: list[CandidateScore] = []
    if initial_xy is not None and len(initial_xy):
        for i, xy in enumerate(np.asarray(initial_xy, dtype=float)[: config.n_stations]):
            selected.append(np.asarray(xy, dtype=float))
            scores.append(
                CandidateScore(
                    candidate_id=f"F_BASE_{i:02d}",
                    role="station",
                    x=float(selected[-1][0]),
                    y=float(selected[-1][1]),
                    score=1.0,
                    coverage_score=1.0,
                    balance_score=1.0,
                    distance_score=1.0,
                    separation_score=1.0,
                    feasibility_score=1.0,
                    selected=True,
                )
            )
    for _ in range(max(config.n_stations - len(selected), 0)):
        rows = []
        for i, cand in enumerate(candidates):
            if _too_close_to_selected(cand, selected, config.min_station_distance):
                continue
            if config.station_avoid_node_overlap and _too_close_to_any_node(cand, all_nodes, config.station_min_node_distance):
                continue
            rows.append(_score_station_candidate(cand, customer_xy, depot_xy, selected, config, i))
        if not rows:
            raise ValueError(
                "No feasible station candidates after applying min_station_distance and node-overlap filters; "
                "relax min_station_distance or station_min_node_distance, or increase candidate diversity."
            )
        rows.sort(key=lambda row: row.score, reverse=True)
        chosen = rows[0]
        chosen.selected = True
        selected.append(np.asarray([chosen.x, chosen.y], dtype=float))
        scores.extend(rows[: min(50, len(rows))])
    return np.asarray(selected, dtype=float), _dedupe_scores(scores)


def _station_candidates(customer_xy: np.ndarray, depot_xy: np.ndarray, config: ScenarioConfig, rng: np.random.Generator) -> np.ndarray:
    centroid = np.mean(customer_xy, axis=0)
    far_customers = customer_xy[np.argsort(np.min(_dist(customer_xy, depot_xy), axis=1))[-max(config.n_stations * 3, 3) :]]
    corridor = []
    for depot in depot_xy:
        for point in far_customers:
            corridor.append(0.55 * depot + 0.45 * point)
        corridor.append(0.5 * depot + 0.5 * centroid)
    xmin, xmax, ymin, ymax = config.coord_bounds
    random = np.column_stack([rng.uniform(xmin, xmax, 80), rng.uniform(ymin, ymax, 80)])
    return np.vstack([np.asarray(corridor), random])


def _score_station_candidate(
    cand: np.ndarray,
    customer_xy: np.ndarray,
    depot_xy: np.ndarray,
    selected: list[np.ndarray],
    config: ScenarioConfig,
    idx: int,
) -> CandidateScore:
    d_customer = np.min(_dist(customer_xy, cand[None, :]), axis=1)
    d_depot = float(np.min(_dist(depot_xy, cand[None, :])))
    customer_support = 1.0 - min(float(np.median(d_customer)) / max(np.ptp(customer_xy[:, 0]), np.ptp(customer_xy[:, 1]), 1.0), 1.0)
    depot_access = 1.0 - min(d_depot / max(np.ptp(customer_xy[:, 0]), np.ptp(customer_xy[:, 1]), 1.0), 1.0)
    if selected:
        spacing = min(float(np.linalg.norm(cand - s)) for s in selected)
        separation_score = min(spacing / max(config.min_station_distance, 1.0), 1.5) / 1.5
    else:
        separation_score = 1.0
    coverage = float(np.mean(d_customer <= np.quantile(d_customer, 0.35)))
    score = 0.35 * customer_support + 0.25 * depot_access + 0.25 * separation_score + 0.15 * coverage
    return CandidateScore(
        candidate_id=f"F_CAND_{idx:04d}",
        role="station",
        x=float(cand[0]),
        y=float(cand[1]),
        score=float(score),
        coverage_score=coverage,
        balance_score=customer_support,
        distance_score=depot_access,
        separation_score=separation_score,
        feasibility_score=1.0,
    )


def _build_nodes(
    customer_xy: np.ndarray,
    demand: np.ndarray,
    ready: np.ndarray,
    due: np.ndarray,
    service: np.ndarray,
    depot_xy: np.ndarray,
    station_xy: np.ndarray,
    config: ScenarioConfig,
) -> list[Node]:
    nodes: list[Node] = []
    # v2026-06-12: Z0b uses C_s for both depots and public stations. Depot
    # chargers are set to a static customer-count route upper bound so depot
    # overnight charging is capacity-checked without becoming the scarce
    # resource in formal experiments.
    depot_chargers = max(1, int(config.n_customers))
    for i, xy in enumerate(depot_xy):
        # v2026-06-12: Q1 shifted 24h carbon grid uses a 17:00 depot return deadline.
        depot_due = config.horizon_end if config.depot_due_time is None else config.depot_due_time
        nodes.append(
            Node(
                f"D{i}",
                "d",
                float(xy[0]),
                float(xy[1]),
                0.0,
                config.horizon_start,
                depot_due,
                0.0,
                station_capacity=depot_chargers,
                station_chargers=depot_chargers,
            )
        )
    for i, xy in enumerate(customer_xy, start=1):
        nodes.append(Node(f"C{i}", "c", float(xy[0]), float(xy[1]), float(demand[i - 1]), float(ready[i - 1]), float(due[i - 1]), float(service[i - 1])))
    for i, xy in enumerate(station_xy, start=1):
        nodes.append(
            Node(
                f"F{i}",
                "f",
                float(xy[0]),
                float(xy[1]),
                0.0,
                config.horizon_start,
                config.horizon_end,
                0.0,
                station_capacity=config.station_capacity,
                station_chargers=config.station_capacity,
                charge_power_kw=config.station_charge_power_kw,
                carbon_region=config.carbon_regions[(i - 1) % len(config.carbon_regions)],
            )
        )
    return nodes


def _generate_dynamic_events(nodes: list[Node], config: ScenarioConfig, rng: np.random.Generator) -> list[DynamicEvent]:
    dyn = config.dynamic_event_config
    if not dyn.enabled:
        return []
    customers = [node for node in nodes if node.node_type == "c"]
    n_events = _dynamic_event_count(dyn, len(customers))
    counts = _proportional_counts(n_events, dyn.event_ratio)
    types = ["add"] * counts[0] + ["cancel"] * counts[1] + ["demand_change"] * counts[2] + ["time_window_change"] * counts[3]
    if counts[0] > 0 and not config.add_event_source_paths:
        raise ValueError("Dynamic add events require add_event_source_paths from migrated Goeke instances; run with --base-id or provide donor paths.")
    add_donors = _load_add_event_donors(config, nodes, rng) if counts[0] > 0 else []
    rng.shuffle(types)
    times = _sample_event_times(rng, n_events, config.horizon_start, config.horizon_end, dyn.random_mode)
    events: list[DynamicEvent] = []
    customer_indices = rng.choice(len(customers), size=min(n_events, len(customers)), replace=False)
    if len(customer_indices) < n_events:
        customer_indices = np.resize(customer_indices, n_events)

    for event_id, (event_type, t_appear, customer_index) in enumerate(zip(types, times, customer_indices, strict=True), start=1):
        base = customers[int(customer_index)]
        old_demand = base.demand
        new_demand = old_demand
        old_ready = base.ready_time
        old_due = base.due_time
        new_ready = old_ready
        new_due = old_due
        x, y = base.x, base.y
        customer_id = base.node_id
        time_window_action = "none"
        demand_source = "existing_customer"
        time_window_source = "existing_customer"
        donor_instance_id = ""
        donor_customer_id = ""
        if event_type == "add":
            donor = add_donors[int(rng.integers(0, len(add_donors)))]
            customer_id = f"N{event_id}"
            x = donor["x"]
            y = donor["y"]
            old_demand = 0.0
            new_demand, demand_source = _resolve_add_demand(donor, customers, config, rng)
            new_ready, new_due, time_window_source = _resolve_add_time_window(donor, customers, config, rng)
            old_ready = new_ready
            old_due = new_due
            donor_instance_id = donor["instance_id"]
            donor_customer_id = donor["customer_id"]
        elif event_type == "cancel":
            new_demand = 0.0
        elif event_type == "demand_change":
            factor = float(np.clip(rng.normal(1.0, 0.18), 0.5, 1.5))
            new_demand = float(np.clip(round(old_demand * factor, 1), config.demand_min, config.vehicle_capacity * config.max_customer_demand_ratio))
        elif event_type == "time_window_change":
            width = max(old_due - old_ready, config.time_window_min_width)
            action = _sample_time_window_action(dyn.time_window_change_ratio, rng)
            time_window_action = action
            if action == "shrink":
                new_width = max(config.time_window_min_width, width * rng.uniform(0.55, 0.85))
            elif action == "extend":
                new_width = min(config.time_window_max_width, width * rng.uniform(1.15, 1.60))
            else:
                new_width = width
            center = (old_ready + old_due) / 2.0 + rng.uniform(-900.0, 900.0)
            new_ready = float(np.clip(center - new_width / 2.0, config.horizon_start, config.horizon_end - new_width))
            new_due = float(min(new_ready + new_width, config.horizon_end))
        events.append(
            DynamicEvent(
                event_id=event_id,
                event_type=event_type,
                t_appear=float(t_appear),
                customer_id=customer_id,
                x=float(x),
                y=float(y),
                old_demand=float(old_demand),
                new_demand=float(new_demand),
                delta_demand=float(new_demand - old_demand),
                old_ready_time=float(old_ready),
                old_due_time=float(old_due),
                new_ready_time=float(new_ready),
                new_due_time=float(new_due),
                time_window_action=time_window_action,
                demand_source=demand_source,
                time_window_source=time_window_source,
                donor_instance_id=donor_instance_id,
                donor_customer_id=donor_customer_id,
                source="goeke_donor_overlay" if event_type == "add" else "synthetic_overlay",
                seed=config.seed,
            )
        )
    events.sort(key=lambda event: event.t_appear)
    for i, event in enumerate(events, start=1):
        event.event_id = i
    return events


def _dynamic_event_count(config: DynamicEventConfig, n_customers: int) -> int:
    if config.event_rate is not None and config.event_rate > 0:
        return max(1, round(n_customers * min(config.event_rate, 1.0)))
    return max(0, config.n_events)


def _sample_event_times(rng: np.random.Generator, n: int, t0: float, t1: float, mode: str) -> np.ndarray:
    span = max(t1 - t0, 1.0)
    key = mode.lower()
    if key == "normal":
        values = rng.normal(t0 + 0.5 * span, span / 6.0, n)
        return np.sort(np.clip(values, t0, t1))
    if key == "truncnorm":
        values = _truncated_normal(rng, t0 + 0.5 * span, span / 6.0, t0, t1, n)
        return np.sort(values)
    if key == "triangular":
        values = t0 + span * 0.5 * (rng.random(n) + rng.random(n))
        return np.sort(values)
    return np.sort(t0 + rng.random(n) * span)


def _proportional_counts(total: int, ratio: Iterable[float]) -> list[int]:
    values = np.asarray(list(ratio), dtype=float)
    if np.any(values < 0) or np.sum(values) <= 0:
        values = np.ones_like(values)
    raw = total * values / np.sum(values)
    counts = np.floor(raw).astype(int)
    for idx in np.argsort(raw - counts)[::-1][: total - int(np.sum(counts))]:
        counts[idx] += 1
    return counts.tolist()


def _sample_time_window_action(ratio: Iterable[float], rng: np.random.Generator) -> str:
    values = np.asarray(list(ratio), dtype=float)
    if len(values) != 3 or np.any(values < 0) or np.sum(values) <= 0:
        values = np.asarray([1.0, 3.0, 1.0])
    probs = values / np.sum(values)
    return str(rng.choice(["shrink", "keep", "extend"], p=probs))


def _resolve_add_demand(
    donor: dict[str, float | str],
    current_customers: list[Node],
    config: ScenarioConfig,
    rng: np.random.Generator,
) -> tuple[float, str]:
    donor_demand = float(donor["demand"])
    cap = config.vehicle_capacity * config.max_customer_demand_ratio
    if config.demand_min <= donor_demand <= cap:
        return donor_demand, "donor_inherited"
    pool = np.asarray([node.demand for node in current_customers if config.demand_min <= node.demand <= cap], dtype=float)
    if len(pool):
        value = float(rng.choice(pool) * rng.uniform(0.9, 1.1))
        return float(np.round(np.clip(value, config.demand_min, cap), 1)), "generated_from_current_instance"
    value = float(_generate_demand(replace(config, n_customers=1), rng, None)[0])
    return value, "generated_from_config"


def _resolve_add_time_window(
    donor: dict[str, float | str],
    current_customers: list[Node],
    config: ScenarioConfig,
    rng: np.random.Generator,
) -> tuple[float, float, str]:
    donor_ready = float(donor["ready_time"])
    donor_due = float(donor["due_time"])
    if _time_window_reasonable(donor_ready, donor_due, config):
        return donor_ready, donor_due, "donor_inherited"
    candidates = [
        node for node in current_customers
        if _time_window_reasonable(node.ready_time, node.due_time, config)
    ]
    if candidates:
        node = candidates[int(rng.integers(0, len(candidates)))]
        width = node.due_time - node.ready_time
        shift = float(rng.uniform(-900.0, 900.0))
        ready = float(np.clip(node.ready_time + shift, config.horizon_start, config.horizon_end - width))
        return ready, float(ready + width), "generated_from_current_instance"
    ready, due, _ = _generate_time_windows(replace(config, n_customers=1), rng, None)
    return float(ready[0]), float(due[0]), "generated_from_config"


def _time_window_reasonable(ready: float, due: float, config: ScenarioConfig) -> bool:
    width = due - ready
    return (
        np.isfinite(ready)
        and np.isfinite(due)
        and config.horizon_start <= ready < due <= config.horizon_end
        and config.time_window_min_width <= width <= config.time_window_max_width
    )


def _load_add_event_donors(config: ScenarioConfig, current_nodes: list[Node], rng: np.random.Generator) -> list[dict[str, float | str]]:
    current_xy = {
        (round(node.x, 3), round(node.y, 3))
        for node in current_nodes
        if node.node_type == "c"
    }
    donors: list[dict[str, float | str]] = []
    source_paths = list(config.add_event_source_paths)
    rng.shuffle(source_paths)
    for source_path in source_paths:
        try:
            nodes, _ = parse_evrptwmf(source_path)
        except Exception:
            continue
        instance_id = Path(source_path).stem
        for node in nodes:
            if node.node_type != "c":
                continue
            key = (round(node.x, 3), round(node.y, 3))
            if key in current_xy:
                continue
            donors.append(
                {
                    "instance_id": instance_id,
                    "customer_id": node.node_id,
                    "x": float(node.x),
                    "y": float(node.y),
                    "demand": float(node.demand),
                    "ready_time": float(node.ready_time),
                    "due_time": float(node.due_time),
                }
            )
    if not donors:
        raise ValueError("No reasonable donor customers found for dynamic add events in add_event_source_paths")
    return donors


def _kmeans_like(xy: np.ndarray, k: int, rng: np.random.Generator, iterations: int) -> np.ndarray:
    k = min(max(k, 1), len(xy))
    centers = xy[rng.choice(len(xy), size=k, replace=False)].copy()
    for _ in range(iterations):
        dist = _dist(xy, centers)
        labels = np.argmin(dist, axis=1)
        for i in range(k):
            mask = labels == i
            if np.any(mask):
                centers[i] = np.mean(xy[mask], axis=0)
    return centers


def _dist(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    delta = a[:, None, :] - b[None, :, :]
    return np.sqrt(np.sum(delta * delta, axis=2))


def _truncated_normal(rng: np.random.Generator, mean: float, std: float, lo: float, hi: float, n: int) -> np.ndarray:
    values = rng.normal(mean, max(std, 1e-9), size=n)
    for _ in range(20):
        mask = (values < lo) | (values > hi)
        if not np.any(mask):
            break
        values[mask] = rng.normal(mean, max(std, 1e-9), size=int(np.sum(mask)))
    return np.clip(values, lo, hi)


def _enforce_min_distance(xy: np.ndarray, min_distance: float, rng: np.random.Generator, bounds: tuple[float, float, float, float]) -> np.ndarray:
    xmin, xmax, ymin, ymax = bounds
    out = xy.copy()
    for i in range(len(out)):
        guard = 0
        while i > 0 and np.min(np.linalg.norm(out[:i] - out[i], axis=1)) < min_distance and guard < 100:
            out[i] += rng.normal(0.0, min_distance, size=2)
            out[i, 0] = np.clip(out[i, 0], xmin, xmax)
            out[i, 1] = np.clip(out[i, 1], ymin, ymax)
            guard += 1
    return out


def _too_close_to_selected(cand: np.ndarray, selected: list[np.ndarray], min_distance: float) -> bool:
    return bool(selected and min(np.linalg.norm(cand - point) for point in selected) < min_distance)


def _too_close_to_any_node(cand: np.ndarray, nodes: np.ndarray, min_distance: float) -> bool:
    return bool(len(nodes) and min(np.linalg.norm(cand - point) for point in nodes) < min_distance)


def _dedupe_scores(scores: list[CandidateScore]) -> list[CandidateScore]:
    seen: set[str] = set()
    out: list[CandidateScore] = []
    for score in sorted(scores, key=lambda row: (not row.selected, -row.score)):
        key = f"{score.role}:{score.candidate_id}:{round(score.x, 3)}:{round(score.y, 3)}"
        if key in seen:
            continue
        seen.add(key)
        out.append(score)
    return out
