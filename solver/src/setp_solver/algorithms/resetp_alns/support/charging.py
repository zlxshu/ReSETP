"""Shared EV charging repair for search states.

v2026-06-11: Provides the algorithm-side repair hook for paper_main.tex
lines 428-457. Given a route and carbon profile, it inserts station visits
when needed and constructs ``ChargingAction`` values using the existing
Solution/ChargingAction schema. Use ``repair_route_charging`` when route
nodes may need stations; use ``solve_charging`` when only actions are needed.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
import os
from collections.abc import Mapping
from time import perf_counter
from typing import Any

from setp_solver.charge_timing import (
    ChargeTimingContexts,
    DEFAULT_CHARGE_TIMING_POLICY,
    select_charge_timing_start,
    validate_charge_timing_policy,
)
from setp_solver.cost import (
    CARBON_SLOT_SECONDS,
    best_charging_action_start,
    charging_action_electricity_cost,
    charging_action_emissions_kg,
    ev_instance_arc_energy_kwh,
    route_next_day_departure_second,
    route_return_arrival_without_charging,
    time_profile_rows_for_node,
)
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import DEFAULT_PRICES, PriceParameters
from setp_solver.charging_action import _curve_aware_action
from setp_solver.charging_curve import (
    curve_for_charging_node,
    spec_from_parameters,
)
from setp_solver.solution import ChargingAction, Route, Solution
from setp_solver.station_copies import physical_station_id
from setp_solver.algorithms.resetp_alns.support.carbon_charging import (
    ChargeOption,
    select_charge_option,
)
from setp_solver.search.multitrip_schedule import (
    certified_depot_charge_window,
    route_timing,
    select_certified_depot_charge_start,
    validate_depot_charge_window_mode,
)
from setp_solver.search.evaluation import EvaluationContext, record_repair_delta
from setp_solver.algorithms.resetp_alns.operators.repair_scoring import (
    route_model_cost_delta,
)


CHARGE_AMOUNT_STRATEGIES = (
    "just_enough",
    "max_coverage",
    "soc_85",
    "soc_95",
    "full",
)
CURVE_KNEE_STRATEGY_PREFIX = "curve_knee_"
PUBLIC_STATION_CANDIDATE_MODES = frozenset({"fallback", "parallel", "split"})
FALLBACK_PUBLIC_STATION_CANDIDATE_MODE = "fallback"
DEFAULT_PUBLIC_STATION_CANDIDATE_MODE = FALLBACK_PUBLIC_STATION_CANDIDATE_MODE
SPLIT_PUBLIC_STATION_CANDIDATE_MODE = "split"
# Two depot launch levels closer than this are the same physical decision:
# 1e-3 kWh is 1 Wh, below the resolution of any charging meter or tariff record
# this model uses, so two levels that close cannot price, emit or schedule
# differently.  The former 1e-6 kWh was float-exact deduplication (1.3e-8 of a
# 77.28 kWh pack) with no physical meaning
# (docs/handoff/station_split_review_20260908.md, H-1).  Measured effect of the
# widening on its own is small -- on the two replayed run packages the level
# count fell 19->18 and 27->24 -- because most of the wasted rebuilds come from
# levels that rebuild into a plan ``add_public`` already holds, not from levels
# less than 1 Wh apart.
SPLIT_DEPOT_LEVEL_TOLERANCE_KWH = 1e-3
# Smallest station top-up that counts as a charging process.  The model gives
# every visited public-station node one charging process h, with its own
# arrival/departure energies and its own start and end clock
# (docs/paper_v2/paper_main.tex:420), so a station visit that buys ~0 kWh is
# not a charging arrangement and must not enter the candidate set.  No
# instance, calendar or price parameter in this repository fixes a metering or
# billing minimum, so the value is set from observed magnitudes instead: the
# one real split session in the replay bought 4.937 kWh, while the zero-energy
# drive-by points bought 0.0045 kWh and 1e-6 kWh
# (docs/handoff/station_split_review_20260908.md, section B).  0.5 kWh sits an
# order below the real session and two or more orders above the drive-bys, so
# it separates the two populations without touching either.  It is a screening
# floor, not a curve or tariff property -- recalibrate it if a real instance
# ever exposes a genuine sub-0.5 kWh top-up.
SPLIT_MIN_STATION_ENERGY_KWH = 0.5


@dataclass(frozen=True)
class _ForcedStationScreen:
    """One exact first-insertion result and its Pareto resources."""

    station: Node
    insertion: tuple[str, ChargingAction, float, float, float]
    insertion_from_id: str
    insertion_to_id: str
    capacity_group: str
    detour_m: float
    arrival_second: float
    target_arrival_second: float
    departure_energy_kwh: float
    target_residual_energy_kwh: float
    latest_start_second: float
    occupancy_seconds: float
    charge_energy_kwh: float
    chargeable_energy_kwh: float
    electricity_cost: float
    electricity_price_per_kwh: float
    carbon_kg: float
    carbon_kg_per_kwh: float
    energy_to_station_kwh: float
    energy_to_target_kwh: float


class ChargingRepairRuntime:
    """Solve-local static timing data and deterministic route repair results."""

    def __init__(
        self,
        instance: Instance,
        gamma_profile: list[dict[str, Any]],
        prices: PriceParameters | dict[str, float] | Any,
        carbon_profiles_by_day_offset: Mapping[
            int, list[dict[str, Any]]
        ] | None,
    ) -> None:
        self.instance = instance
        self.gamma_profile = gamma_profile
        self.prices = prices
        self.carbon_profiles_by_day_offset = carbon_profiles_by_day_offset
        self.timing_contexts = ChargeTimingContexts(instance, prices)
        self.stations = [node for node in instance.node_lookup.values() if node.node_type.lower() == "f"]
        self._candidate_cache: dict[
            tuple[Any, ...],
            tuple[tuple[str, Route, tuple[ChargingAction, ...]], ...],
        ] = {}
        self._repaired_cache: dict[
            tuple[Any, ...], tuple[Route, tuple[ChargingAction, ...]]
        ] = {}
        self._route_score_cache: dict[tuple[Any, ...], float] = {}
        self.hits = 0
        self.misses = 0
        self.repaired_hits = 0
        self.repaired_misses = 0
        self.route_score_hits = 0
        self.route_score_misses = 0
        self.repair_seconds = 0.0
        self.candidate_seconds = 0.0
        self.route_score_seconds = 0.0
        self.station_candidates_enumerated = 0
        self.station_candidates_reachable = 0
        self.station_candidates_after_equivalence = 0
        self.station_candidates_after_dominance = 0
        self.station_candidate_rebuilds = 0
        self.station_candidate_evaluations = 0
        self.station_split_levels = 0

    def assert_matches(
        self,
        instance: Instance,
        gamma_profile: list[dict[str, Any]],
        prices: PriceParameters | dict[str, float] | Any,
        carbon_profiles_by_day_offset: Mapping[
            int, list[dict[str, Any]]
        ] | None,
    ) -> None:
        if (
            instance is not self.instance
            or gamma_profile is not self.gamma_profile
            or prices is not self.prices
            or carbon_profiles_by_day_offset
            is not self.carbon_profiles_by_day_offset
        ):
            raise ValueError("charging repair runtime was reused with other inputs")

    @staticmethod
    def candidate_key(
        route: Route,
        *,
        strategy: str,
        carbon_weight: float,
        depot_charge_window_mode: str,
        charge_timing_policy: str,
        charge_amount_strategy: str,
        public_station_candidate_mode: str,
    ) -> tuple[Any, ...]:
        return (
            route.vehicle_id,
            route.vehicle_type,
            route.home_depot_id,
            tuple(route.node_sequence),
            strategy,
            float(carbon_weight),
            depot_charge_window_mode,
            charge_timing_policy,
            charge_amount_strategy,
            public_station_candidate_mode,
        )

    def get_candidates(
        self,
        key: tuple[Any, ...],
    ) -> list[tuple[str, Route, list[ChargingAction]]] | None:
        cached = self._candidate_cache.get(key)
        if cached is None:
            self.misses += 1
            return None
        self.hits += 1
        return [
            (
                label,
                replace(repaired, node_sequence=list(repaired.node_sequence)),
                list(actions),
            )
            for label, repaired, actions in cached
        ]

    def put_candidates(
        self,
        key: tuple[Any, ...],
        candidates: list[tuple[str, Route, list[ChargingAction]]],
    ) -> list[tuple[str, Route, list[ChargingAction]]]:
        self._candidate_cache[key] = tuple(
            (
                label,
                replace(repaired, node_sequence=list(repaired.node_sequence)),
                tuple(actions),
            )
            for label, repaired, actions in candidates
        )
        return candidates

    @staticmethod
    def repaired_key(
        route: Route,
        *,
        strategy: str,
        carbon_weight: float,
        depot_charge_window_mode: str,
        charge_timing_policy: str,
        charge_amount_strategy: str,
        public_station_candidate_mode: str,
    ) -> tuple[Any, ...]:
        """Bind a selected repair to every exact selector input."""

        return (
            *ChargingRepairRuntime.candidate_key(
                route,
                strategy=strategy,
                carbon_weight=carbon_weight,
                depot_charge_window_mode=depot_charge_window_mode,
                charge_timing_policy=charge_timing_policy,
                charge_amount_strategy=charge_amount_strategy,
                public_station_candidate_mode=public_station_candidate_mode,
            ),
            os.environ.get("SETP_ALNS_CRUSH_TRUE_REPAIR", "1"),
        )

    def get_repaired(
        self,
        key: tuple[Any, ...],
    ) -> tuple[Route, list[ChargingAction]] | None:
        cached = self._repaired_cache.get(key)
        if cached is None:
            self.repaired_misses += 1
            return None
        self.repaired_hits += 1
        route, actions = cached
        return replace(route, node_sequence=list(route.node_sequence)), list(actions)

    def put_repaired(
        self,
        key: tuple[Any, ...],
        route: Route,
        actions: list[ChargingAction],
    ) -> tuple[Route, list[ChargingAction]]:
        self._repaired_cache[key] = (
            replace(route, node_sequence=list(route.node_sequence)),
            tuple(actions),
        )
        return route, actions

    @staticmethod
    def route_score_key(
        route: Route,
        actions: list[ChargingAction],
        *,
        carbon_weight: float,
    ) -> tuple[Any, ...]:
        """Use complete route/action values without rounding or reordering."""

        return (
            str(route.vehicle_id),
            str(route.vehicle_type),
            str(route.home_depot_id),
            tuple(route.node_sequence),
            tuple(actions),
            float(carbon_weight),
            os.environ.get("SETP_ALNS_CRUSH_TRUE_REPAIR", "1"),
        )

    def score_route(
        self,
        route: Route,
        actions: list[ChargingAction],
        context: EvaluationContext,
    ) -> float:
        key = self.route_score_key(
            route,
            actions,
            carbon_weight=float(context.carbon_weight),
        )
        cached = self._route_score_cache.get(key)
        if cached is not None:
            self.route_score_hits += 1
            return float(cached)
        self.route_score_misses += 1
        started = perf_counter()
        score = route_model_cost_delta(route, actions, context)
        self.route_score_seconds += perf_counter() - started
        self._route_score_cache[key] = float(score)
        return float(score)

    def diagnostics(self) -> dict[str, Any]:
        return {
            "candidate_cache_hits": int(self.hits),
            "candidate_cache_misses": int(self.misses),
            "repaired_cache_hits": int(self.repaired_hits),
            "repaired_cache_misses": int(self.repaired_misses),
            "route_score_cache_hits": int(self.route_score_hits),
            "route_score_cache_misses": int(self.route_score_misses),
            "repair_seconds": float(self.repair_seconds),
            "candidate_seconds": float(self.candidate_seconds),
            "route_score_seconds": float(self.route_score_seconds),
            "station_pruning": {
                "enumerated": int(self.station_candidates_enumerated),
                "reachable": int(self.station_candidates_reachable),
                "after_equivalence": int(
                    self.station_candidates_after_equivalence
                ),
                "after_dominance": int(
                    self.station_candidates_after_dominance
                ),
                "candidate_rebuilds": int(self.station_candidate_rebuilds),
                "candidate_evaluations": int(
                    self.station_candidate_evaluations
                ),
                "split_levels": int(self.station_split_levels),
            },
            "timing_context_count": len(self.timing_contexts._contexts),
        }


_CHARGING_REPAIR_RUNTIMES: dict[
    tuple[int, int, int, int],
    tuple[
        Instance,
        list[dict[str, Any]],
        PriceParameters | dict[str, float] | Any,
        Mapping[int, list[dict[str, Any]]] | None,
        ChargingRepairRuntime,
    ],
] = {}


def charging_repair_runtime_diagnostics() -> dict[str, Any]:
    """Aggregate exact solve-local repair and station-screen counters."""

    totals = {
        "enumerated": 0,
        "reachable": 0,
        "after_equivalence": 0,
        "after_dominance": 0,
        "candidate_rebuilds": 0,
        "candidate_evaluations": 0,
        "split_levels": 0,
    }
    # 每个运行时都已在记缓存命中与三段耗时，此前只有站点筛选被汇总上来，
    # 于是"一圈的时间花在哪"无从查证（2026-09-02 查表8 时发现）。这里一并汇总。
    counters = {
        "candidate_cache_hits": 0,
        "candidate_cache_misses": 0,
        "repaired_cache_hits": 0,
        "repaired_cache_misses": 0,
        "route_score_cache_hits": 0,
        "route_score_cache_misses": 0,
    }
    seconds = {
        "repair_seconds": 0.0,
        "candidate_seconds": 0.0,
        "route_score_seconds": 0.0,
    }
    runtimes = [entry[4] for entry in _CHARGING_REPAIR_RUNTIMES.values()]
    for runtime in runtimes:
        diagnostics = runtime.diagnostics()
        station = diagnostics["station_pruning"]
        for name in totals:
            totals[name] += int(station[name])
        for name in counters:
            counters[name] += int(diagnostics[name])
        for name in seconds:
            seconds[name] += float(diagnostics[name])
    return {
        "runtime_count": len(runtimes),
        "station_pruning": totals,
        **counters,
        **seconds,
    }


def _get_charging_repair_runtime(
    instance: Instance,
    gamma_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any,
    carbon_profiles_by_day_offset: Mapping[
        int, list[dict[str, Any]]
    ] | None,
) -> ChargingRepairRuntime:
    key = (
        id(instance),
        id(gamma_profile),
        id(prices),
        id(carbon_profiles_by_day_offset),
    )
    cached = _CHARGING_REPAIR_RUNTIMES.get(key)
    if cached is not None and (
        cached[0] is instance
        and cached[1] is gamma_profile
        and cached[2] is prices
        and cached[3] is carbon_profiles_by_day_offset
    ):
        return cached[4]
    runtime = ChargingRepairRuntime(
        instance,
        gamma_profile,
        prices,
        carbon_profiles_by_day_offset,
    )
    _CHARGING_REPAIR_RUNTIMES[key] = (
        instance,
        gamma_profile,
        prices,
        carbon_profiles_by_day_offset,
        runtime,
    )
    return runtime


def validate_public_station_candidate_mode(mode: str) -> str:
    """Validate the public-station candidate-generation policy."""

    if mode not in PUBLIC_STATION_CANDIDATE_MODES:
        raise ValueError(
            "unknown public station candidate mode: "
            f"{mode!r}; expected one of "
            f"{sorted(PUBLIC_STATION_CANDIDATE_MODES)}"
        )
    return mode


def normalize_charge_amount_strategies(
    strategies: tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    """Return a unique ordered tuple of supported charge targets."""

    normalized = tuple(str(value).strip().lower() for value in strategies)
    if not normalized or len(set(normalized)) != len(normalized):
        raise ValueError("charge amount strategies must be non-empty and unique")
    unknown = {
        value
        for value in normalized
        if value not in CHARGE_AMOUNT_STRATEGIES
        and _curve_knee_index(value) is None
    }
    if unknown:
        raise ValueError(f"unknown charge amount strategies: {sorted(unknown)}")
    return normalized


def curve_knee_strategies(parameters: object) -> tuple[str, ...]:
    """Name every internal breakpoint carried by the input charging curve."""

    internal_count = max(
        0,
        len(spec_from_parameters(parameters).soc_breakpoints) - 2,
    )
    return tuple(
        f"{CURVE_KNEE_STRATEGY_PREFIX}{index}"
        for index in range(1, internal_count + 1)
    )


def _curve_knee_index(strategy: str) -> int | None:
    if not strategy.startswith(CURVE_KNEE_STRATEGY_PREFIX):
        return None
    suffix = strategy.removeprefix(CURVE_KNEE_STRATEGY_PREFIX)
    if not suffix.isdigit() or int(suffix) < 1:
        return None
    return int(suffix)


def _curve_breakpoints_for_strategy(
    parameters: object,
    strategy: str,
) -> tuple[float, ...]:
    if _curve_knee_index(strategy) is None:
        return ()
    return spec_from_parameters(parameters).soc_breakpoints


def charge_amount_target_kwh(
    strategy: str,
    *,
    just_enough_kwh: float,
    max_coverage_kwh: float,
    capacity_kwh: float,
    curve_soc_breakpoints: tuple[float, ...] = (),
) -> float:
    """Map one shared physical charge target to an end-of-charge energy."""

    name = strategy
    capacity = float(capacity_kwh)
    just_enough = min(capacity, float(just_enough_kwh))
    if name == "just_enough":
        return just_enough
    if name == "max_coverage":
        return min(capacity, float(max_coverage_kwh))
    knee_index = _curve_knee_index(name)
    if knee_index is not None:
        internal_breakpoints = tuple(float(value) for value in curve_soc_breakpoints[1:-1])
        if knee_index > len(internal_breakpoints):
            raise ValueError(
                f"charging curve has no internal breakpoint {knee_index}"
            )
        return max(just_enough, internal_breakpoints[knee_index - 1] * capacity)
    if name == "soc_85":
        return max(just_enough, 0.85 * capacity)
    if name == "soc_95":
        return max(just_enough, 0.95 * capacity)
    return capacity


def solve_charging(
    route: Route,
    instance: Instance,
    gamma_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    depot_charge_window_mode: str = "full_gap",
    charge_timing_policy: str = DEFAULT_CHARGE_TIMING_POLICY,
    carbon_profiles_by_day_offset: Mapping[int, list[dict[str, Any]]] | None = None,
) -> list[ChargingAction]:
    """Return charging actions for a repaired version of ``route``."""

    _, actions = repair_route_charging(
        route,
        instance,
        gamma_profile,
        prices,
        depot_charge_window_mode=depot_charge_window_mode,
        charge_timing_policy=charge_timing_policy,
        carbon_profiles_by_day_offset=carbon_profiles_by_day_offset,
    )
    return actions


def repair_route_charging(
    route: Route,
    instance: Instance,
    gamma_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    strategy: str = "legacy",
    carbon_weight: float = 1.0,
    depot_charge_window_mode: str = "full_gap",
    charge_timing_policy: str = DEFAULT_CHARGE_TIMING_POLICY,
    charge_amount_strategy: str = "just_enough",
    carbon_profiles_by_day_offset: Mapping[int, list[dict[str, Any]]] | None = None,
    public_station_candidate_mode: str = DEFAULT_PUBLIC_STATION_CANDIDATE_MODE,
) -> tuple[Route, list[ChargingAction]]:
    """Insert station visits and actions sufficient for battery feasibility.

    ``legacy`` preserves the frozen E2 behavior.  ``integrated`` is isolated
    for the item-4 mechanism gate and compares complete charging intervals and
    station detours in common monetary units.
    """

    candidates = repair_route_charging_candidates(
        route,
        instance,
        gamma_profile,
        prices,
        strategy=strategy,
        carbon_weight=carbon_weight,
        depot_charge_window_mode=depot_charge_window_mode,
        charge_timing_policy=charge_timing_policy,
        charge_amount_strategy=charge_amount_strategy,
        carbon_profiles_by_day_offset=carbon_profiles_by_day_offset,
        public_station_candidate_mode=public_station_candidate_mode,
    )
    if len(candidates) == 1:
        _, repaired, actions = candidates[0]
        return repaired, actions
    context = EvaluationContext(
        instance=instance,
        carbon_profile=gamma_profile,
        prices=prices,
        carbon_weight=carbon_weight,
    )
    runtime = _get_charging_repair_runtime(
        instance,
        gamma_profile,
        prices,
        carbon_profiles_by_day_offset,
    )
    scored_candidates = []
    for index, (_, candidate_route, candidate_actions) in enumerate(candidates):
        runtime.station_candidate_evaluations += 1
        record_repair_delta(context)
        scored_candidates.append(
            (
                route_model_cost_delta(candidate_route, candidate_actions, context),
                index,
                candidate_route,
                candidate_actions,
            )
        )
    _, _, repaired, actions = min(scored_candidates)
    return repaired, actions


def repair_route_charging_candidates(
    route: Route,
    instance: Instance,
    gamma_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    strategy: str = "legacy",
    carbon_weight: float = 1.0,
    depot_charge_window_mode: str = "full_gap",
    charge_timing_policy: str = DEFAULT_CHARGE_TIMING_POLICY,
    charge_amount_strategy: str = "just_enough",
    carbon_profiles_by_day_offset: Mapping[int, list[dict[str, Any]]] | None = None,
    public_station_candidate_mode: str = DEFAULT_PUBLIC_STATION_CANDIDATE_MODE,
) -> list[tuple[str, Route, list[ChargingAction]]]:
    """Build the legacy depot path and, when enabled, a public-only path."""

    validate_public_station_candidate_mode(public_station_candidate_mode)
    if strategy not in {"legacy", "integrated"}:
        raise ValueError(f"unknown charging-repair strategy: {strategy}")
    validate_depot_charge_window_mode(depot_charge_window_mode)
    validate_charge_timing_policy(charge_timing_policy)
    charge_amount_strategy = normalize_charge_amount_strategies((charge_amount_strategy,))[0]
    if route.vehicle_type.lower() != "ev" or not route.node_sequence:
        return [("depot_fallback", route, [])]
    runtime = _get_charging_repair_runtime(
        instance,
        gamma_profile,
        prices,
        carbon_profiles_by_day_offset,
    )
    node_lookup = instance.node_lookup
    stations = runtime.stations if runtime is not None else [node for node in node_lookup.values() if node.node_type.lower() == "f"]
    cache_key: tuple[Any, ...] | None = None
    timing_contexts: ChargeTimingContexts | None = None
    if runtime is not None:
        runtime.assert_matches(
            instance,
            gamma_profile,
            prices,
            carbon_profiles_by_day_offset,
        )
        cache_key = runtime.candidate_key(
            route,
            strategy=strategy,
            carbon_weight=carbon_weight,
            depot_charge_window_mode=depot_charge_window_mode,
            charge_timing_policy=charge_timing_policy,
            charge_amount_strategy=charge_amount_strategy,
            public_station_candidate_mode=public_station_candidate_mode,
        )
        cached_candidates = runtime.get_candidates(cache_key)
        if cached_candidates is not None:
            return cached_candidates
        timing_contexts = runtime.timing_contexts

    def finish(
        result: list[tuple[str, Route, list[ChargingAction]]],
    ) -> list[tuple[str, Route, list[ChargingAction]]]:
        if runtime is None or cache_key is None:
            return result
        return runtime.put_candidates(cache_key, result)
    candidates: list[tuple[str, Route, list[ChargingAction]]] = []
    fallback_error: ValueError | None = None
    if runtime is not None:
        runtime.station_candidate_rebuilds += 1
    initial_departure_second = route_timing(
        route,
        instance,
        prices,
        charging_actions=[],
        validate_battery=False,
    ).earliest_departure_second
    try:
        fallback_route, fallback_actions = _repair_route_charging_candidate(
            route,
            instance,
            gamma_profile,
            prices,
            strategy=strategy,
            carbon_weight=carbon_weight,
            depot_charge_window_mode=depot_charge_window_mode,
            charge_timing_policy=charge_timing_policy,
            charge_amount_strategy=charge_amount_strategy,
            carbon_profiles_by_day_offset=carbon_profiles_by_day_offset,
            depot_precharge_target_kwh=None,
            stations=stations,
            timing_contexts=timing_contexts,
            initial_departure_second=initial_departure_second,
        )
    except ValueError as exc:
        fallback_error = exc
    else:
        candidates.append(("depot_fallback", fallback_route, fallback_actions))
    if public_station_candidate_mode == FALLBACK_PUBLIC_STATION_CANDIDATE_MODE:
        if fallback_error is not None:
            raise fallback_error
        return finish(candidates)
    remaining_customers = [
        node_id
        for node_id in route.node_sequence[1:]
        if node_lookup[node_id].node_type.lower() == "c"
    ]
    load_kg = sum(float(node_lookup[node_id].demand) for node_id in remaining_customers)
    initial_battery = _price(prices, "initial_ev_battery_kwh")
    battery_cap = instance.battery_capacity_kwh(
        fallback=_price(prices, "B_battery_kwh"),
    )
    start_node = route.node_sequence[0]
    if runtime is not None:
        runtime.station_candidates_enumerated += len(stations)
    # A forced parallel path launches with exactly enough depot energy to
    # reach its first station.  At that station ``coverage_targets`` is every
    # remaining target and ``charge_amount_target_kwh`` is never below that
    # complete remaining-route energy.  A second public insertion therefore
    # cannot occur; longer forced paths always reach the fail-closed
    # ``station_insertions < len(forced_station_path)`` check below.  Do not
    # enumerate those guaranteed rejections: with a metropolitan station pool
    # the former all-length permutation loop was factorial while producing the
    # exact same accepted candidate list.
    reachable: list[_ForcedStationScreen] = []
    walk_profile = _RouteWalkProfile(route, instance, prices)
    traces: dict[float, _ForcedScreenTrace | None] = {}
    for station in stations:
        launch_target = max(
            initial_battery,
            _ev_energy(
                instance,
                start_node,
                station.node_id,
                load_kg,
                prices,
            ),
        )
        if launch_target > battery_cap + 1e-9:
            continue
        if launch_target in traces:
            trace = traces[launch_target]
        else:
            trace = traces[launch_target] = _build_forced_screen_trace(
                route,
                instance,
                gamma_profile,
                prices,
                walk=walk_profile,
                strategy=strategy,
                carbon_weight=carbon_weight,
                depot_charge_window_mode=depot_charge_window_mode,
                charge_timing_policy=charge_timing_policy,
                charge_amount_strategy=charge_amount_strategy,
                carbon_profiles_by_day_offset=carbon_profiles_by_day_offset,
                depot_precharge_target_kwh=launch_target,
                timing_contexts=timing_contexts,
            )
        if trace is None or not trace.positions:
            continue
        screen = _screen_forced_public_station(
            route,
            station,
            instance,
            gamma_profile,
            prices,
            strategy=strategy,
            carbon_weight=carbon_weight,
            charge_timing_policy=charge_timing_policy,
            charge_amount_strategy=charge_amount_strategy,
            timing_contexts=timing_contexts,
            trace=trace,
        )
        if screen is not None:
            reachable.append(screen)
    if runtime is not None:
        runtime.station_candidates_reachable += len(reachable)

    equivalent_representatives: dict[str, _ForcedStationScreen] = {}
    for screen in reachable:
        equivalent_representatives.setdefault(
            physical_station_id(screen.station),
            screen,
        )
    distinct = list(equivalent_representatives.values())
    if runtime is not None:
        runtime.station_candidates_after_equivalence += len(distinct)
    nondominated = _remove_dominated_station_screens(distinct)
    if runtime is not None:
        runtime.station_candidates_after_dominance += len(nondominated)

    def build_forced(
        depot_target_kwh: float,
        station_path: tuple[str, ...],
        screen: _ForcedStationScreen | None,
    ) -> tuple[Route, list[ChargingAction]] | None:
        """Build one forced-station path for a given depot launch level."""

        if runtime is not None:
            runtime.station_candidate_rebuilds += 1
        try:
            return _repair_route_charging_candidate(
                route,
                instance,
                gamma_profile,
                prices,
                strategy=strategy,
                carbon_weight=carbon_weight,
                depot_charge_window_mode=depot_charge_window_mode,
                charge_timing_policy=charge_timing_policy,
                charge_amount_strategy=charge_amount_strategy,
                carbon_profiles_by_day_offset=carbon_profiles_by_day_offset,
                depot_precharge_target_kwh=depot_target_kwh,
                forced_station_path=station_path,
                stations=stations,
                timing_contexts=timing_contexts,
                precomputed_first_station=screen,
                initial_departure_second=initial_departure_second,
            )
        except ValueError:
            return None

    def add_public(
        built: tuple[Route, list[ChargingAction]],
        label_suffix: str,
    ) -> bool:
        """Record one public-station candidate unless it is already present."""

        public_route, public_actions = built
        public_station_ids = [
            action.station_id
            for action in public_actions
            if node_lookup[action.station_id].node_type.lower() == "f"
        ]
        if not public_station_ids:
            return False
        if any(
            candidate_route == public_route
            and candidate_actions == public_actions
            for _, candidate_route, candidate_actions in candidates
        ):
            return False
        candidates.append(
            (
                "public_path_" + "__".join(public_station_ids) + label_suffix,
                public_route,
                public_actions,
            )
        )
        return True

    for screen in nondominated:
        station_path = (screen.station.node_id,)
        launch_target = max(
            initial_battery,
            _ev_energy(
                instance,
                start_node,
                screen.station.node_id,
                load_kg,
                prices,
            ),
        )
        built = build_forced(launch_target, station_path, screen)
        if built is None:
            continue
        add_public(built, "")
        if public_station_candidate_mode != SPLIT_PUBLIC_STATION_CANDIDATE_MODE:
            continue
        # Split mode keeps the launch-target endpoint above (the depot carries
        # only enough to reach the station) and adds the interior levels where
        # the depot/station division of the same trip energy can be optimal.
        levels = _split_depot_launch_levels(
            built[1],
            launch_target_kwh=launch_target,
            initial_battery_kwh=initial_battery,
            battery_capacity_kwh=battery_cap,
            instance=instance,
            prices=prices,
        )
        if runtime is not None:
            runtime.station_split_levels += len(levels)
        for order, level in enumerate(levels):
            split_built = build_forced(level, station_path, None)
            if split_built is not None:
                add_public(split_built, f"__split{order:02d}")
    if not candidates and fallback_error is not None:
        raise fallback_error
    return finish(candidates)


def _slot_boundaries_within(start_second: float, span_seconds: float) -> list[float]:
    """Return the tariff/carbon slot boundaries a session of ``span`` crosses."""

    if span_seconds <= 0.0:
        return []
    first = math.floor(float(start_second) / CARBON_SLOT_SECONDS) + 1
    last = math.floor((float(start_second) + float(span_seconds)) / CARBON_SLOT_SECONDS)
    return [
        float(index) * CARBON_SLOT_SECONDS for index in range(first, last + 1)
    ]


def _split_depot_launch_levels(
    actions: list[ChargingAction],
    *,
    launch_target_kwh: float,
    initial_battery_kwh: float,
    battery_capacity_kwh: float,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
) -> list[float]:
    """Return the interior depot launch levels a split trip can be optimal at.

    ``actions`` is the launch-target build for one forced station: the depot
    carries exactly enough to reach the station and the station covers the
    rest.  Raising the depot level ``x`` moves energy from the station to the
    depot one-for-one, because the station target is a fixed end-of-charge
    level and its charged amount is that level minus the arrival energy.
    Electricity price and carbon intensity are half-hour step functions and
    the charging curve is piecewise linear in energy, so with both start times
    held fixed the trip cost is piecewise linear in ``x``: it can only bend
    where one session's end crosses a slot boundary or a curve breakpoint.
    Those levels, plus the two endpoints, are therefore the whole candidate
    set, and the curve's exact time/energy inverses give them in closed form
    rather than on a percentage grid.

    ``x`` is bounded above by the largest level that still leaves the station a
    real charging process.  The model gives every visited public-station node
    one charging process ``h`` with its own arrival and departure energies and
    its own start and end clock (``docs/paper_v2/paper_main.tex:420``), so a
    station visit buying ~0 kWh is not a charging arrangement and is not a
    charging candidate.  The bound is therefore "station top-up at least
    ``SPLIT_MIN_STATION_ENERGY_KWH``", not "the station charges nothing".

    Do not restate that bound as "the top endpoint is the depot-only plan plus
    a pointless detour, so it is dominated": that reasoning is false on this
    instance.  The distance matrix stores fastest-path distances and 1.57% of
    its triples violate the triangle inequality (worst case -7588 m), so going
    via a station can be shorter than going direct.  On one replayed trip the
    depot->station->customer detour was -1305 m and a level just under the top
    endpoint beat the depot-only plan by 2.26 CNY while the station bought
    1e-6 kWh (``docs/handoff/station_split_review_20260908.md``, section B).
    That shortcut is a property of the road-network matrix, not of a charging
    decision, and this function does not admit it as one.

    A trip whose entire station share is below ``SPLIT_MIN_STATION_ENERGY_KWH``
    leaves no room between the two bounds and yields no interior level.

    Start times are read from this launch-target build.  The depot and station
    timing selectors may move a start when ``x`` changes, in which case these
    levels are a candidate set rather than a certificate of optimality.
    """

    node_lookup = instance.node_lookup
    depot_action = next(
        (
            action
            for action in actions
            if node_lookup[action.station_id].node_type.lower() == "d"
        ),
        None,
    )
    station_action = next(
        (
            action
            for action in actions
            if node_lookup[action.station_id].node_type.lower() == "f"
        ),
        None,
    )
    if depot_action is None or station_action is None:
        return []
    # Energy spent reaching the station: the launch level minus what is left
    # on arrival.  It is fixed for this insertion, so it converts a station
    # arrival energy into the depot launch level that produces it.
    energy_to_station = launch_target_kwh - float(station_action.start_energy_kwh)
    station_target_kwh = float(station_action.end_energy_kwh)
    upper = min(
        battery_capacity_kwh,
        station_target_kwh + energy_to_station - SPLIT_MIN_STATION_ENERGY_KWH,
    )
    if upper <= launch_target_kwh + SPLIT_DEPOT_LEVEL_TOLERANCE_KWH:
        return []
    station_node = node_lookup[station_action.station_id]
    depot_curve = curve_for_charging_node(
        prices,
        node_type="d",
        capacity_kwh=battery_capacity_kwh,
        reference_power_kw=_price(prices, "depot_charge_power_kw"),
    )
    station_curve = curve_for_charging_node(
        prices,
        node_type=station_node.node_type,
        capacity_kwh=battery_capacity_kwh,
        reference_power_kw=_charge_power_kw(station_node, prices),
    )

    levels: list[float] = []
    depot_start = float(depot_action.charge_start_second)
    for boundary in _slot_boundaries_within(
        depot_start,
        depot_curve.duration_seconds(initial_battery_kwh, upper),
    ):
        levels.append(
            depot_curve.reachable_energy_kwh(
                initial_battery_kwh,
                boundary - depot_start,
            )
        )
    station_start = float(station_action.charge_start_second)
    for boundary in _slot_boundaries_within(
        station_start,
        float(station_action.occupancy_minutes) * 60.0,
    ):
        levels.append(
            station_curve.minimum_energy_before_gap_kwh(
                station_target_kwh,
                boundary - station_start,
            )
            + energy_to_station
        )
    levels.extend(
        float(energy) for energy in depot_curve.energy_breakpoints_kwh
    )
    levels.extend(
        float(energy) + energy_to_station
        for energy in station_curve.energy_breakpoints_kwh
    )

    interior: list[float] = []
    for level in sorted(levels):
        if (
            level <= launch_target_kwh + SPLIT_DEPOT_LEVEL_TOLERANCE_KWH
            or level >= upper - SPLIT_DEPOT_LEVEL_TOLERANCE_KWH
        ):
            continue
        if interior and level - interior[-1] <= SPLIT_DEPOT_LEVEL_TOLERANCE_KWH:
            continue
        interior.append(level)
    return interior


def _repair_route_charging_candidate(
    route: Route,
    instance: Instance,
    gamma_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    strategy: str,
    carbon_weight: float,
    depot_charge_window_mode: str,
    charge_timing_policy: str,
    charge_amount_strategy: str,
    carbon_profiles_by_day_offset: Mapping[int, list[dict[str, Any]]] | None,
    depot_precharge_target_kwh: float | None,
    stations: list[Node],
    forced_station_path: tuple[str, ...] = (),
    timing_contexts: ChargeTimingContexts | None = None,
    precomputed_first_station: _ForcedStationScreen | None = None,
    initial_departure_second: float | None = None,
) -> tuple[Route, list[ChargingAction]]:
    """Build one charging path without changing any feasibility rule."""

    node_lookup = instance.node_lookup
    original_targets = [node_id for node_id in route.node_sequence[1:] if node_lookup[node_id].node_type.lower() != "f"]
    repaired = [route.node_sequence[0]]
    actions: list[ChargingAction] = []
    # v2026-06-12: Q2 starts EV routes from bbar and makes depot precharge a
    # first-class decision before preserving the existing en-route station logic.
    battery = _price(prices, "initial_ev_battery_kwh")
    time_s = (
        route_timing(
            route,
            instance,
            prices,
            charging_actions=[],
            validate_battery=False,
        ).earliest_departure_second
        if initial_departure_second is None
        else initial_departure_second
    )
    remaining_customers = [node_id for node_id in original_targets if node_lookup[node_id].node_type.lower() == "c"]
    depot_action = _depot_precharge_action(
        route,
        original_targets,
        node_lookup,
        instance,
        gamma_profile,
        prices,
        strategy=strategy,
        carbon_weight=carbon_weight,
        depot_charge_window_mode=depot_charge_window_mode,
        charge_timing_policy=charge_timing_policy,
        charge_amount_strategy=charge_amount_strategy,
        carbon_profiles_by_day_offset=carbon_profiles_by_day_offset,
        target_charge_level_kwh=depot_precharge_target_kwh,
        timing_contexts=timing_contexts,
    )
    if depot_action is not None:
        actions.append(depot_action)
        battery += float(depot_action.energy_kwh)
        # v2026-06-12: S0 depot action is the previous-return/next-departure
        # overnight charge that supplies departure battery; it must not delay
        # the current-day route clock used for station repair.

    current = route.node_sequence[0]
    station_insertions = 0
    for target_idx, target in enumerate(original_targets):
        load_kg = sum(float(node_lookup[node_id].demand) for node_id in remaining_customers)
        needed_direct = _ev_energy(
            instance,
            current,
            target,
            load_kg,
            prices,
        )
        future_targets = original_targets[target_idx:]
        failure_offset = _first_direct_infeasible_offset(
            current,
            future_targets,
            battery,
            node_lookup,
            instance,
            prices,
            remaining_customers,
        )
        should_insert = failure_offset is not None
        if should_insert:
            coverage_targets = (
                future_targets
                if depot_precharge_target_kwh is not None
                else future_targets[: int(failure_offset) + 1]
            )
            available_stations = _available_station_visits(stations, repaired)
            if not available_stations and battery + 1e-9 < needed_direct:
                raise ValueError("No charging stations available for EV charging repair")
            if station_insertions == 0 and precomputed_first_station is not None:
                candidate = (
                    precomputed_first_station.insertion
                    if current == precomputed_first_station.insertion_from_id
                    and target == precomputed_first_station.insertion_to_id
                    else None
                )
            else:
                candidate = _best_station_insert(
                    current,
                    target,
                    coverage_targets,
                    future_targets,
                    remaining_customers,
                    load_kg,
                    battery,
                    time_s,
                    available_stations,
                    node_lookup,
                    instance,
                    gamma_profile,
                    prices,
                    route.vehicle_id,
                    strategy=strategy,
                    carbon_weight=carbon_weight,
                    charge_timing_policy=charge_timing_policy,
                    charge_amount_strategy=charge_amount_strategy,
                    forced_station_id=(
                        forced_station_path[station_insertions]
                        if station_insertions < len(forced_station_path)
                        else None
                    ),
                    timing_contexts=timing_contexts,
                )
            if (
                precomputed_first_station is not None
                and station_insertions == 0
                and forced_station_path
                and candidate is not None
                and candidate[0] != forced_station_path[0]
            ):
                raise AssertionError("precomputed station identity changed")
            if candidate is None:
                if battery + 1e-9 < needed_direct:
                    raise ValueError(f"No feasible charging insert between {current} and {target}")
            else:
                station_id, action, arrive_station, depart_station, battery_after_charge = candidate
                station_insertions += 1
                repaired.append(station_id)
                actions.append(action)
                battery = battery_after_charge
                time_s = depart_station
                current = station_id

        travel = _ev_travel_time(
            instance,
            current,
            target,
            prices,
        )
        battery -= _ev_energy(
            instance,
            current,
            target,
            load_kg,
            prices,
        )
        time_s = max(time_s + travel, float(node_lookup[target].ready_time)) + float(node_lookup[target].service_time)
        repaired.append(target)
        if node_lookup[target].node_type.lower() == "c":
            remaining_customers.remove(target)
        current = target

    if station_insertions < len(forced_station_path):
        raise ValueError("forced public-station path was not fully used")

    repaired_route = replace(route, node_sequence=repaired)
    actions = _reanchor_depot_actions(
        repaired_route,
        actions,
        instance,
        gamma_profile,
        prices,
        depot_charge_window_mode=depot_charge_window_mode,
        carbon_profiles_by_day_offset=carbon_profiles_by_day_offset,
        strategy=strategy,
        carbon_weight=carbon_weight,
        charge_timing_policy=charge_timing_policy,
        timing_contexts=timing_contexts,
    )
    return repaired_route, actions


def _available_station_visits(
    stations: list[Node], repaired: list[str]
) -> list[Node]:
    """Expose one unused visit identity per physical station."""

    used = set(repaired)
    physical_seen: set[str] = set()
    available: list[Node] = []
    for station in stations:
        physical = physical_station_id(station)
        if station.node_id in used or physical in physical_seen:
            continue
        physical_seen.add(physical)
        available.append(station)
    return available


def _first_direct_infeasible_offset(
    current: str,
    future_targets: list[str],
    battery: float,
    node_lookup: dict[str, Node],
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
    remaining_customers: list[str],
) -> int | None:
    """Return the target offset where direct travel first depletes EV battery."""

    local_current = current
    local_battery = float(battery)
    local_remaining = list(remaining_customers)
    for offset, target in enumerate(future_targets):
        load_kg = sum(float(node_lookup[node_id].demand) for node_id in local_remaining)
        local_battery -= _ev_energy(
            instance,
            local_current,
            target,
            load_kg,
            prices,
        )
        if local_battery < -1e-9:
            return offset
        if node_lookup[target].node_type.lower() == "c" and target in local_remaining:
            local_remaining.remove(target)
        if node_lookup[target].node_type.lower() in {"d", "f"}:
            return None
        local_current = target
    return None


def _charge_power_kw(node: Node, prices: PriceParameters | dict[str, float] | Any) -> float:
    node_type = node.node_type.lower()
    if node_type == "d":
        power = _price(prices, "depot_charge_power_kw")
    else:
        power = float(node.charge_power_kw) if node.charge_power_kw is not None else 0.0
    if power <= 1e-9:
        raise ValueError(f"Charging power is missing or nonpositive at {node.node_id}")
    return power


def _fixed_charge_earliest(node: Node, node_type: str, arrival_second: float) -> float:
    if node_type == "d":
        return float(node.ready_time)
    return max(float(arrival_second), float(node.ready_time))


def _fixed_charge_window(
    idx: int,
    route: Route,
    node_lookup: dict[str, Node],
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
    occupancy_sec: float,
    arrival_second: float,
    n_slots: int,
    *,
    depot_charge_window_mode: str,
    charging_actions: list[ChargingAction],
) -> tuple[float, float]:
    node_id = route.node_sequence[idx]
    node = node_lookup[node_id]
    if node.node_type.lower() == "d":
        if depot_charge_window_mode == "full_gap":
            period = float(n_slots) * CARBON_SLOT_SECONDS
            earliest = route_return_arrival_without_charging(route, instance, prices)
            latest = (
                route_next_day_departure_second(
                    route,
                    instance,
                    prices,
                    period_seconds=period,
                )
                - occupancy_sec
            )
            return earliest, latest
        earliest, latest, _ = certified_depot_charge_window(
            route,
            instance,
            prices,
            occupancy_seconds=occupancy_sec,
            mode=depot_charge_window_mode,
            charging_actions=charging_actions,
        )
        return earliest, latest
    return _fixed_charge_earliest(node, node.node_type.lower(), arrival_second), _fixed_charge_latest(
        idx,
        route.node_sequence,
        node_lookup,
        instance,
        prices,
        occupancy_sec,
    )


def _fixed_charge_latest(
    idx: int,
    node_sequence: list[str],
    node_lookup: dict[str, Node],
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
    occupancy_sec: float,
) -> float:
    node_id = node_sequence[idx]
    node = node_lookup[node_id]
    latest = float(node.due_time)
    if node.node_type.lower() == "d":
        latest -= occupancy_sec
    if idx + 1 < len(node_sequence):
        successor_id = node_sequence[idx + 1]
        successor = node_lookup[successor_id]
        latest = min(
            latest,
            float(successor.due_time)
            - occupancy_sec
            - _ev_travel_time(
                instance,
                node_id,
                successor_id,
                prices,
            ),
        )
    return latest


def _depot_precharge_action(
    route: Route,
    original_targets: list[str],
    node_lookup: dict[str, Node],
    instance: Instance,
    gamma_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any,
    *,
    strategy: str = "legacy",
    carbon_weight: float = 1.0,
    depot_charge_window_mode: str = "same_day_predeparture",
    charge_timing_policy: str = DEFAULT_CHARGE_TIMING_POLICY,
    charge_amount_strategy: str = "just_enough",
    carbon_profiles_by_day_offset: Mapping[int, list[dict[str, Any]]] | None = None,
    target_charge_level_kwh: float | None = None,
    timing_contexts: ChargeTimingContexts | None = None,
    feasibility_only: bool = False,
) -> ChargingAction | None:
    """Build the depot launch charge.

    ``feasibility_only`` keeps the window and calendar rejections but skips
    choosing the cheapest start; callers that only read ``energy_kwh`` pass it.
    """

    depot_id = route.node_sequence[0]
    depot = node_lookup[depot_id]
    if depot.node_type.lower() != "d":
        return None
    battery_cap = instance.battery_capacity_kwh(
        fallback=_price(prices, "B_battery_kwh"),
    )
    initial_battery = _price(prices, "initial_ev_battery_kwh")
    if target_charge_level_kwh is None:
        route_need = _direct_route_energy_need(depot_id, original_targets, node_lookup, instance, prices)
        target_charge_level = charge_amount_target_kwh(
            charge_amount_strategy,
            just_enough_kwh=route_need,
            max_coverage_kwh=route_need,
            capacity_kwh=battery_cap,
            curve_soc_breakpoints=_curve_breakpoints_for_strategy(
                prices,
                charge_amount_strategy,
            ),
        )
    else:
        target_charge_level = float(target_charge_level_kwh)
        if (
            not math.isfinite(target_charge_level)
            or target_charge_level < initial_battery - 1e-9
            or target_charge_level > battery_cap + 1e-9
        ):
            raise ValueError(
                "depot launch charge target must lie within battery bounds"
            )
    energy_needed = max(0.0, target_charge_level - initial_battery)
    if energy_needed <= 1e-9:
        return None
    power_kw = _price(prices, "depot_charge_power_kw")
    if power_kw <= 1e-9:
        raise ValueError("Depot charge power pi_d must be positive")
    action = _curve_aware_action(
        vehicle_id=route.vehicle_id,
        station_id=depot_id,
        start_energy_kwh=initial_battery,
        energy_kwh=energy_needed,
        reference_power_kw=power_kw,
        prices=prices,
        instance=instance,
    )
    occupancy_sec = float(action.occupancy_minutes) * 60.0
    synthetic_route = Route(route.vehicle_id, route.vehicle_type, route.home_depot_id, [route.node_sequence[0], *original_targets])
    earliest, latest, _ = certified_depot_charge_window(
        synthetic_route,
        instance,
        prices,
        occupancy_seconds=occupancy_sec,
        mode=depot_charge_window_mode,
        charging_actions=[],
    )
    charge_start, charge_day_offset = select_certified_depot_charge_start(
        action,
        earliest,
        latest,
        instance,
        prices,
        gamma_profile,
        mode=depot_charge_window_mode,
        strategy=strategy,
        carbon_weight=carbon_weight,
        charge_timing_policy=charge_timing_policy,
        carbon_profiles_by_day_offset=carbon_profiles_by_day_offset,
        timing_contexts=timing_contexts,
        feasibility_only=feasibility_only,
    )
    return replace(
        action,
        charge_start_second=charge_start,
        charge_day_offset=charge_day_offset,
    )


def _reanchor_depot_actions(
    route: Route,
    actions: list[ChargingAction],
    instance: Instance,
    gamma_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any,
    *,
    depot_charge_window_mode: str,
    carbon_profiles_by_day_offset: Mapping[int, list[dict[str, Any]]] | None,
    strategy: str,
    carbon_weight: float = 1.0,
    charge_timing_policy: str = DEFAULT_CHARGE_TIMING_POLICY,
    timing_contexts: ChargeTimingContexts | None = None,
) -> list[ChargingAction]:
    """Recompute depot charging against the final certificate route clock."""

    depot_indices = [
        index
        for index, action in enumerate(actions)
        if action.vehicle_id == route.vehicle_id
        and action.station_id == route.home_depot_id
    ]
    if not depot_indices:
        return actions
    if len(depot_indices) != 1:
        raise ValueError(
            f"expected one depot charging action for {route.vehicle_id}, "
            f"found {len(depot_indices)}"
        )
    index = depot_indices[0]
    action = actions[index]
    earliest, latest, _ = certified_depot_charge_window(
        route,
        instance,
        prices,
        occupancy_seconds=float(action.occupancy_minutes) * 60.0,
        mode=depot_charge_window_mode,
        charging_actions=actions,
    )
    start, offset = select_certified_depot_charge_start(
        action,
        earliest,
        latest,
        instance,
        prices,
        gamma_profile,
        mode=depot_charge_window_mode,
        strategy=strategy,
        carbon_weight=carbon_weight,
        charge_timing_policy=charge_timing_policy,
        carbon_profiles_by_day_offset=carbon_profiles_by_day_offset,
        timing_contexts=timing_contexts,
    )
    updated = list(actions)
    updated[index] = replace(
        action,
        charge_start_second=start,
        charge_day_offset=offset,
    )
    return updated


def _direct_route_energy_need(
    depot_id: str,
    original_targets: list[str],
    node_lookup: dict[str, Node],
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
    *,
    remaining_customers: list[str] | None = None,
) -> float:
    total = 0.0
    current = depot_id
    local_remaining = (
        [node_id for node_id in original_targets if node_lookup[node_id].node_type.lower() == "c"]
        if remaining_customers is None
        else list(remaining_customers)
    )
    for target in original_targets:
        load_kg = sum(float(node_lookup[node_id].demand) for node_id in local_remaining)
        total += _ev_energy(
            instance,
            current,
            target,
            load_kg,
            prices,
        )
        if node_lookup[target].node_type.lower() == "c" and target in local_remaining:
            local_remaining.remove(target)
        current = target
    return total


def _route_travel_lower_bound(
    depot_id: str,
    original_targets: list[str],
    node_lookup: dict[str, Node],
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
) -> float:
    stations = [node for node in node_lookup.values() if node.node_type.lower() == "f"]
    battery_cap = instance.battery_capacity_kwh(
        fallback=_price(prices, "B_battery_kwh"),
    )
    battery = min(battery_cap, _price(prices, "initial_ev_battery_kwh") + battery_cap)
    total = 0.0
    current = depot_id
    remaining_customers = [node_id for node_id in original_targets if node_lookup[node_id].node_type.lower() == "c"]
    for target in original_targets:
        load_kg = sum(float(node_lookup[node_id].demand) for node_id in remaining_customers)
        direct_time = _ev_travel_time(instance, current, target, prices)
        direct_energy = _ev_energy(
            instance,
            current,
            target,
            load_kg,
            prices,
        )
        if direct_energy <= battery + 1e-9:
            best_time = direct_time
            battery -= direct_energy
        else:
            best_candidate: tuple[float, float] | None = None
            for station in stations:
                time_to_station = _ev_travel_time(
                    instance,
                    current,
                    station.node_id,
                    prices,
                )
                energy_to_station = _ev_energy(
                    instance,
                    current,
                    station.node_id,
                    load_kg,
                    prices,
                )
                if energy_to_station > battery + 1e-9:
                    continue
                time_station_to_target = _ev_travel_time(
                    instance,
                    station.node_id,
                    target,
                    prices,
                )
                energy_station_to_target = _ev_energy(
                    instance,
                    station.node_id,
                    target,
                    load_kg,
                    prices,
                )
                if energy_station_to_target > battery_cap + 1e-9:
                    continue
                travel_time = time_to_station + time_station_to_target
                battery_after_target = battery_cap - energy_station_to_target
                candidate = (travel_time, battery_after_target)
                if best_candidate is None or candidate[0] < best_candidate[0]:
                    best_candidate = candidate
            if best_candidate is None:
                best_time = direct_time
                battery = max(0.0, battery - direct_energy)
            else:
                best_time, battery = best_candidate
        total += best_time
        total += float(node_lookup[target].service_time)
        if node_lookup[target].node_type.lower() == "c":
            remaining_customers.remove(target)
        current = target
    return total


class _RouteWalkProfile:
    """Battery-independent walk data for one route, built once per repair.

    Leg energies, travel times, load evolution, clock chain, and per-position
    future/remaining snapshots do not depend on the launch battery or on the
    screened station, so every forced-station trace replays these arrays with
    the same floating-point values in the same order as the original walks.
    """

    __slots__ = (
        "targets",
        "currents",
        "loads",
        "leg_energy",
        "leg_travel",
        "futures",
        "remaining_snapshots",
        "time_chain",
        "kinds",
        "depart_second",
        "initial_battery",
    )

    def __init__(
        self,
        route: Route,
        instance: Instance,
        prices: PriceParameters | dict[str, float] | Any,
    ) -> None:
        node_lookup = instance.node_lookup
        targets = [
            node_id
            for node_id in route.node_sequence[1:]
            if node_lookup[node_id].node_type.lower() != "f"
        ]
        remaining = [
            node_id
            for node_id in targets
            if node_lookup[node_id].node_type.lower() == "c"
        ]
        self.targets = targets
        self.initial_battery = _price(prices, "initial_ev_battery_kwh")
        self.depart_second = route_timing(
            route,
            instance,
            prices,
            charging_actions=[],
            validate_battery=False,
        ).earliest_departure_second
        currents: list[str] = []
        loads: list[float] = []
        leg_energy: list[float] = []
        leg_travel: list[float] = []
        futures: list[list[str]] = []
        remaining_snapshots: list[list[str]] = []
        time_chain: list[float] = []
        kinds: list[str] = []
        current = route.node_sequence[0]
        time_s = self.depart_second
        for target_idx, target in enumerate(targets):
            load_kg = sum(
                float(node_lookup[node_id].demand)
                for node_id in remaining
            )
            currents.append(current)
            loads.append(load_kg)
            futures.append(targets[target_idx:])
            remaining_snapshots.append(list(remaining))
            time_chain.append(time_s)
            kind = node_lookup[target].node_type.lower()
            kinds.append(kind)
            leg_energy.append(
                _ev_energy(instance, current, target, load_kg, prices)
            )
            travel = _ev_travel_time(instance, current, target, prices)
            leg_travel.append(travel)
            time_s = max(
                time_s + travel,
                float(node_lookup[target].ready_time),
            ) + float(node_lookup[target].service_time)
            if kind == "c" and target in remaining:
                remaining.remove(target)
            current = target
        self.currents = currents
        self.loads = loads
        self.leg_energy = leg_energy
        self.leg_travel = leg_travel
        self.futures = futures
        self.remaining_snapshots = remaining_snapshots
        self.time_chain = time_chain
        self.kinds = kinds

    def direct_infeasible_from(self, position: int, battery: float) -> bool:
        """Sequentially replay ``_first_direct_infeasible_offset``.

        Identical float values are subtracted in the identical order, so the
        -1e-9 gate decides exactly as the original per-station walk did.
        """

        local_battery = float(battery)
        leg_energy = self.leg_energy
        kinds = self.kinds
        for index in range(position, len(leg_energy)):
            local_battery -= leg_energy[index]
            if local_battery < -1e-9:
                return True
            if kinds[index] in ("d", "f"):
                return False
        return False


class _ForcedScreenTrace:
    """Fired positions of one launch-battery walk over a route profile."""

    __slots__ = ("walk", "positions")

    def __init__(
        self,
        walk: _RouteWalkProfile,
        positions: tuple[tuple[int, float], ...],
    ) -> None:
        self.walk = walk
        self.positions = positions


def _build_forced_screen_trace(
    route: Route,
    instance: Instance,
    gamma_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any,
    *,
    walk: _RouteWalkProfile,
    strategy: str,
    carbon_weight: float,
    depot_charge_window_mode: str,
    charge_timing_policy: str,
    charge_amount_strategy: str,
    carbon_profiles_by_day_offset: Mapping[
        int, list[dict[str, Any]]
    ] | None,
    depot_precharge_target_kwh: float,
    timing_contexts: ChargeTimingContexts | None,
) -> _ForcedScreenTrace | None:
    """Walk the route once per depot-precharge target on the shared profile."""

    battery = walk.initial_battery
    try:
        depot_action = _depot_precharge_action(
            route,
            walk.targets,
            instance.node_lookup,
            instance,
            gamma_profile,
            prices,
            strategy=strategy,
            carbon_weight=carbon_weight,
            depot_charge_window_mode=depot_charge_window_mode,
            charge_timing_policy=charge_timing_policy,
            charge_amount_strategy=charge_amount_strategy,
            carbon_profiles_by_day_offset=carbon_profiles_by_day_offset,
            target_charge_level_kwh=depot_precharge_target_kwh,
            timing_contexts=timing_contexts,
            # The screen below reads only ``energy_kwh``; the chosen start was
            # optimised once per launch target and thrown away.
            feasibility_only=True,
        )
    except ValueError:
        return None
    if depot_action is not None:
        battery += float(depot_action.energy_kwh)

    positions: list[tuple[int, float]] = []
    leg_energy = walk.leg_energy
    for index in range(len(leg_energy)):
        if walk.direct_infeasible_from(index, battery):
            positions.append((index, battery))
            if battery + 1e-9 < leg_energy[index]:
                break
        battery -= leg_energy[index]
    return _ForcedScreenTrace(walk, tuple(positions))


def _screen_forced_public_station(
    route: Route,
    station: Node,
    instance: Instance,
    gamma_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any,
    *,
    strategy: str,
    carbon_weight: float,
    charge_timing_policy: str,
    charge_amount_strategy: str,
    timing_contexts: ChargeTimingContexts | None,
    trace: _ForcedScreenTrace,
) -> _ForcedStationScreen | None:
    """Apply the existing exact first-insertion rules on the shared trace."""

    node_lookup = instance.node_lookup
    walk = trace.walk
    for index, battery in trace.positions:
        current = walk.currents[index]
        target = walk.targets[index]
        future_targets = walk.futures[index]
        remaining_customers = walk.remaining_snapshots[index]
        load_kg = walk.loads[index]
        time_s = walk.time_chain[index]
        try:
            insertion = _best_station_insert(
                current,
                target,
                future_targets,
                future_targets,
                remaining_customers,
                load_kg,
                battery,
                time_s,
                [station],
                node_lookup,
                instance,
                gamma_profile,
                prices,
                route.vehicle_id,
                strategy=strategy,
                carbon_weight=carbon_weight,
                charge_timing_policy=charge_timing_policy,
                charge_amount_strategy=charge_amount_strategy,
                forced_station_id=station.node_id,
                timing_contexts=timing_contexts,
            )
        except ValueError:
            return None
        if insertion is not None:
            return _station_screen_profile(
                current,
                target,
                future_targets,
                station,
                insertion,
                load_kg,
                instance,
                gamma_profile,
                prices,
                strategy=strategy,
            )
        if battery + 1e-9 < walk.leg_energy[index]:
            return None
    return None


def _station_screen_profile(
    current: str,
    target: str,
    future_targets: list[str],
    station: Node,
    insertion: tuple[str, ChargingAction, float, float, float],
    load_kg: float,
    instance: Instance,
    gamma_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any,
    *,
    strategy: str,
) -> _ForcedStationScreen:
    station_id, action, arrive, depart, battery_after = insertion
    energy_to_station = _ev_energy(
        instance, current, station_id, load_kg, prices
    )
    energy_to_target = _ev_energy(
        instance, station_id, target, load_kg, prices
    )
    occupancy = float(action.occupancy_minutes) * 60.0
    latest = min(
        float(station.due_time),
        float(instance.nodes[instance.node_index[target]].due_time)
        - occupancy
        - _ev_travel_time(instance, station_id, target, prices),
    )
    if strategy == "integrated":
        latest = min(
            latest,
            _latest_charge_start_for_downstream(
                station_id,
                future_targets,
                instance.node_lookup,
                instance,
                prices,
                occupancy,
            ),
        )
    charge_energy = float(action.energy_kwh)
    arrival_energy = float(battery_after) - charge_energy
    chargeable_energy = instance.battery_capacity_kwh(
        fallback=_price(prices, "B_battery_kwh"),
    ) - arrival_energy
    electricity = charging_action_electricity_cost(
        action,
        instance,
        gamma_profile,
        prices,
    )
    carbon = charging_action_emissions_kg(
        action,
        instance,
        gamma_profile,
        prices,
    )
    unconstrained = (
        station.station_chargers is not None
        and int(station.station_chargers) >= int(instance.num_ev)
    )
    return _ForcedStationScreen(
        station=station,
        insertion=insertion,
        insertion_from_id=current,
        insertion_to_id=target,
        capacity_group=(
            "__all_public_capacity_unconstrained__"
            if unconstrained
            else physical_station_id(station)
        ),
        detour_m=(
            _ev_distance(instance, current, station_id, prices)
            + _ev_distance(instance, station_id, target, prices)
            - _ev_distance(instance, current, target, prices)
        ),
        arrival_second=float(arrive),
        target_arrival_second=float(depart)
        + _ev_travel_time(instance, station_id, target, prices),
        departure_energy_kwh=float(battery_after),
        target_residual_energy_kwh=float(battery_after) - energy_to_target,
        latest_start_second=float(latest),
        occupancy_seconds=occupancy,
        charge_energy_kwh=charge_energy,
        chargeable_energy_kwh=float(chargeable_energy),
        electricity_cost=float(electricity),
        electricity_price_per_kwh=float(electricity) / charge_energy,
        carbon_kg=float(carbon),
        carbon_kg_per_kwh=float(carbon) / charge_energy,
        energy_to_station_kwh=energy_to_station,
        energy_to_target_kwh=energy_to_target,
    )


def _strictly_dominates_station(
    better: _ForcedStationScreen,
    worse: _ForcedStationScreen,
) -> bool:
    """Return strict Pareto dominance; no tolerance or score is used."""

    if better.capacity_group != worse.capacity_group:
        return False
    lower_better = (
        "detour_m",
        "arrival_second",
        "target_arrival_second",
        "occupancy_seconds",
        "charge_energy_kwh",
        "electricity_cost",
        "electricity_price_per_kwh",
        "carbon_kg",
        "carbon_kg_per_kwh",
        "energy_to_station_kwh",
        "energy_to_target_kwh",
    )
    higher_better = (
        "departure_energy_kwh",
        "target_residual_energy_kwh",
        "latest_start_second",
        "chargeable_energy_kwh",
    )
    weak = all(
        getattr(better, name) <= getattr(worse, name)
        for name in lower_better
    ) and all(
        getattr(better, name) >= getattr(worse, name)
        for name in higher_better
    )
    strict = any(
        getattr(better, name) < getattr(worse, name)
        for name in lower_better
    ) or any(
        getattr(better, name) > getattr(worse, name)
        for name in higher_better
    )
    return weak and strict


def _remove_dominated_station_screens(
    screens: list[_ForcedStationScreen],
) -> list[_ForcedStationScreen]:
    return [
        candidate
        for candidate in screens
        if not any(
            other is not candidate
            and _strictly_dominates_station(other, candidate)
            for other in screens
        )
    ]


def _best_station_insert(
    current: str,
    target: str,
    coverage_targets: list[str],
    future_targets: list[str],
    remaining_customers: list[str],
    load_kg: float,
    battery: float,
    depart_current: float,
    stations: list[Node],
    node_lookup: dict[str, Node],
    instance: Instance,
    gamma_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any,
    vehicle_id: str,
    *,
    strategy: str = "legacy",
    carbon_weight: float = 1.0,
    charge_timing_policy: str = DEFAULT_CHARGE_TIMING_POLICY,
    charge_amount_strategy: str = "just_enough",
    forced_station_id: str | None = None,
    timing_contexts: ChargeTimingContexts | None = None,
) -> tuple[str, ChargingAction, float, float, float] | None:
    best: tuple[float, float, str, ChargingAction, float, float, float] | None = None
    refined: list[tuple[ChargeOption, float, float]] = []
    battery_cap = instance.battery_capacity_kwh(fallback=_price(prices, "B_battery_kwh"))
    curve_breakpoints = _curve_breakpoints_for_strategy(prices, charge_amount_strategy)
    target_node = node_lookup[target]
    direct_distance = _ev_distance(instance, current, target, prices)
    direct_travel_time = _ev_travel_time(instance, current, target, prices)
    for station in stations:
        if (
            forced_station_id is not None
            and station.node_id != forced_station_id
        ):
            continue
        to_station = _ev_distance(
            instance,
            current,
            station.node_id,
            prices,
        )
        time_to_station = _ev_travel_time(
            instance,
            current,
            station.node_id,
            prices,
        )
        energy_to_station = _ev_energy(
            instance,
            current,
            station.node_id,
            load_kg,
            prices,
        )
        if battery + 1e-9 < energy_to_station:
            continue
        battery_at_station = battery - energy_to_station
        station_to_target = _ev_distance(
            instance,
            station.node_id,
            target,
            prices,
        )
        time_station_to_target = _ev_travel_time(
            instance,
            station.node_id,
            target,
            prices,
        )
        energy_to_target = _ev_energy(
            instance,
            station.node_id,
            target,
            load_kg,
            prices,
        )
        if energy_to_target > battery_cap + 1e-9:
            continue
        segment_need_from_station = _direct_route_energy_need(
            station.node_id,
            coverage_targets,
            node_lookup,
            instance,
            prices,
            remaining_customers=remaining_customers,
        )
        if segment_need_from_station > battery_cap + 1e-9:
            continue
        max_coverage_need = segment_need_from_station
        if coverage_targets != future_targets:
            max_coverage_need = _direct_route_energy_need(
                station.node_id, future_targets, node_lookup, instance, prices,
                remaining_customers=remaining_customers,
            )
        target_charge_level = charge_amount_target_kwh(
            charge_amount_strategy,
            just_enough_kwh=segment_need_from_station,
            max_coverage_kwh=max_coverage_need,
            capacity_kwh=battery_cap,
            curve_soc_breakpoints=curve_breakpoints,
        )
        energy_needed = max(0.0, target_charge_level - battery_at_station)
        if energy_needed <= 1e-9:
            continue
        if station.charge_power_kw is None:
            continue
        action = _curve_aware_action(
            vehicle_id=vehicle_id,
            station_id=station.node_id,
            start_energy_kwh=battery_at_station,
            energy_kwh=energy_needed,
            reference_power_kw=float(station.charge_power_kw),
            prices=prices,
            instance=instance,
        )
        occupancy_sec = float(action.occupancy_minutes) * 60.0
        arrive = depart_current + time_to_station
        earliest = max(arrive, float(station.ready_time))
        latest = min(
            float(station.due_time),
            float(target_node.due_time)
            - occupancy_sec
            - time_station_to_target,
        )
        if strategy == "integrated":
            latest = min(
                latest,
                _latest_charge_start_for_downstream(
                    station.node_id,
                    future_targets,
                    node_lookup,
                    instance,
                    prices,
                    occupancy_sec,
                ),
            )
        if latest + 1e-9 < earliest:
            continue
        detour = (
            to_station
            + station_to_target
            - direct_distance
        )
        detour_seconds = (
            time_to_station
            + time_station_to_target
            - direct_travel_time
        )
        if strategy == "integrated":
            refined.append(
                (
                    ChargeOption(
                        station_id=station.node_id,
                        node_type=station.node_type,
                        earliest_start_second=earliest,
                        latest_start_second=latest,
                        energy_kwh=energy_needed,
                        power_kw=float(station.charge_power_kw),
                        detour_m=detour,
                        detour_seconds=detour_seconds,
                        occupancy_seconds_override=occupancy_sec,
                        start_energy_kwh=action.start_energy_kwh,
                        end_energy_kwh=action.end_energy_kwh,
                        charging_curve_id=action.charging_curve_id,
                    ),
                    arrive,
                    battery_at_station + energy_needed,
                )
            )
            continue
        station_profile = time_profile_rows_for_node(
            instance,
            station.node_id,
            gamma_profile,
        )
        charge_start, gamma = _lowest_gamma_slot_start(
            earliest,
            latest,
            station_profile,
        )
        if charge_timing_policy != "carbon_min":
            charge_start = select_charge_timing_start(
                action,
                earliest_start_second=earliest,
                latest_start_second=latest,
                instance=instance,
                carbon_profile=gamma_profile,
                prices=prices,
                charge_timing_policy=charge_timing_policy,
                timing_contexts=timing_contexts,
            )
        depart = charge_start + occupancy_sec
        action = replace(action, charge_start_second=charge_start)
        key = (gamma, detour, station.node_id, action, arrive, depart, battery_at_station + energy_needed)
        if best is None or (key[0], key[1], key[2]) < (best[0], best[1], best[2]):
            best = key
    if strategy == "integrated":
        if not refined:
            return None
        if not isinstance(prices, PriceParameters):
            raise TypeError("integrated charging repair currently requires PriceParameters")
        scored = select_charge_option(
            [item[0] for item in refined],
            instance,
            gamma_profile,
            prices,
            carbon_weight=carbon_weight,
            charge_timing_policy=charge_timing_policy,
            timing_contexts=timing_contexts,
        )
        option = scored.option
        _, arrive, battery_after = next(item for item in refined if item[0] == option)
        depart = scored.timing.start_second + option.occupancy_seconds
        action = replace(
            option.action_at(scored.timing.start_second),
            vehicle_id=vehicle_id,
        )
        return option.station_id, action, arrive, depart, battery_after
    if best is None:
        return None
    _, _, station_id, action, arrive, depart, battery_after = best
    return station_id, action, arrive, depart, battery_after


def _latest_charge_start_for_downstream(
    station_id: str,
    future_targets: list[str],
    node_lookup: dict[str, Node],
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
    occupancy_sec: float,
) -> float:
    """Protect every downstream due time after an inserted station."""

    if not future_targets:
        return float(node_lookup[station_id].due_time) - float(occupancy_sec)
    successor_id = future_targets[-1]
    latest_successor_start = float(node_lookup[successor_id].due_time)
    for current_id in reversed(future_targets[:-1]):
        current = node_lookup[current_id]
        travel = _ev_travel_time(
            instance,
            current_id,
            successor_id,
            prices,
        )
        latest_successor_start = min(
            float(current.due_time),
            latest_successor_start - float(current.service_time) - travel,
        )
        successor_id = current_id
    return latest_successor_start - float(occupancy_sec) - _ev_travel_time(
        instance,
        station_id,
        successor_id,
        prices,
    )


def _lowest_gamma_slot_start(earliest: float, latest: float, gamma_profile: list[dict[str, Any]]) -> tuple[float, float]:
    candidates: list[tuple[float, float]] = []
    period = float(len(gamma_profile)) * CARBON_SLOT_SECONDS
    if period <= 0.0:
        raise ValueError("gamma_profile must be non-empty")
    first_cycle = math.floor(float(earliest) / period) - 1
    last_cycle = math.ceil(float(latest) / period) + 1
    for row in gamma_profile:
        base_start = float(row["horizon_second_start"])
        for cycle in range(first_cycle, last_cycle + 1):
            slot_start = base_start + cycle * period
            if earliest - 1e-9 <= slot_start <= latest + 1e-9:
                candidates.append((float(row["actual_gco2_per_kwh"]), slot_start))
    if not candidates:
        slot = math.ceil(earliest / CARBON_SLOT_SECONDS) * CARBON_SLOT_SECONDS
        start = slot if slot <= latest + 1e-9 else earliest
        wrapped = start % period
        gamma = min(gamma_profile, key=lambda row: (wrapped - float(row["horizon_second_start"])) % period)["actual_gco2_per_kwh"]
        return float(start), float(gamma)
    gamma, start = min(candidates, key=lambda item: (item[0], item[1]))
    return start, gamma


def _ev_distance(
    instance: Instance,
    from_node_id: str,
    to_node_id: str,
    prices: PriceParameters | dict[str, float] | Any,
) -> float:
    distance, _, _ = instance.arc_metrics(
        from_node_id,
        to_node_id,
        "ev",
        fallback_speed_mps=_price(prices, "v_speed_ms"),
    )
    return distance


def _ev_travel_time(
    instance: Instance,
    from_node_id: str,
    to_node_id: str,
    prices: PriceParameters | dict[str, float] | Any,
) -> float:
    _, travel, _ = instance.arc_metrics(
        from_node_id,
        to_node_id,
        "ev",
        fallback_speed_mps=_price(prices, "v_speed_ms"),
    )
    return travel


def _ev_energy(
    instance: Instance,
    from_node_id: str,
    to_node_id: str,
    load_kg: float,
    prices: PriceParameters | dict[str, float] | Any,
) -> float:
    return ev_instance_arc_energy_kwh(
        instance,
        from_node_id,
        to_node_id,
        load_kg,
        prices,
    )


def _price(prices: PriceParameters | dict[str, float] | Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))
