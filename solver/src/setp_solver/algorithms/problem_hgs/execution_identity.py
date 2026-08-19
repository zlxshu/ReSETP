"""Canonical identity of the Problem-HGS objects that actually execute.

declared_identity=PROJECT_ADAPTER
code_role=THIN_ADAPTER
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from .charging import ChargingRepairPolicy
from .kernel_proposals import IndependentKernelDutyRouteProposalEngine
from .population import PenaltyParameters
from .proposals import MechanismProposalEngine, SequentialProposalEngine


SCHEMA_VERSION = "resetp.problem_hgs.effective_execution.v1"
POLICY_FIELDS = tuple(
    "strategy carbon_weight depot_charge_window_mode charge_timing_policy charge_amount_strategy public_station_candidate_mode first_trip_prev_night_enabled frvcpy_enabled charging_gap_enabled".split()
)
MECHANISM_FIELDS = tuple(
    "include_charging_candidates include_non_charging_candidates include_structural_channels cross_depot_enabled multi_trip_enabled type_exchange_enabled".split()
)
POPULATION_FIELDS = tuple(
    "min_pop_size generation_size num_elite num_close lb_diversity ub_diversity".split()
)
LIVE_SWITCH_FIELDS = tuple(
    "include_mechanism_refinement include_whole_duty_type_exchange include_charging_candidates incremental_full_truth_sentinel_enabled shift_aware_departure_enabled schedule_cross_repair_fallback schedule_all_changed_move_evaluation fleet_activation_enabled objective_mode charging_prescreen_enabled charging_prescreen_audit_limit cross_depot_enabled multi_trip_enabled type_exchange_enabled route_layer_crossover_enabled education_depth_limit".split()
)


def _primitive(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _primitive(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_primitive(item) for item in value]
    raise TypeError(f"non-JSON execution identity value: {type(value).__name__}")


def _sha256(value: Any) -> str:
    encoded = json.dumps(
        _primitive(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def charging_policy_configuration(
    policy: ChargingRepairPolicy,
) -> dict[str, object]:
    return {name: _primitive(getattr(policy, name)) for name in POLICY_FIELDS}


def proposal_stage_configuration(engine: object) -> dict[str, object]:
    """Snapshot a known proposal stage without invoking it."""

    if isinstance(engine, IndependentKernelDutyRouteProposalEngine):
        return {
            "type": "IndependentKernelDutyRouteProposalEngine",
            "source_id": str(engine.source_id),
        }
    if isinstance(engine, MechanismProposalEngine):
        return {
            "type": "MechanismProposalEngine",
            "source_id": str(engine.source_id),
            **{name: bool(getattr(engine, name)) for name in MECHANISM_FIELDS},
            "charging_policy": charging_policy_configuration(engine.charging_policy),
        }
    if isinstance(engine, SequentialProposalEngine):
        return {
            "type": "SequentialProposalEngine",
            "source_id": str(engine.source_id),
            "providers": [proposal_stage_configuration(provider) for provider in engine.providers],
        }
    raise TypeError(
        f"proposal stage has no approved stable configuration adapter: {type(engine).__name__}"
    )


def _stage_configuration(engine: object | None) -> dict[str, object] | None:
    if engine is None:
        return None
    try:
        return proposal_stage_configuration(engine)
    except TypeError:
        return None


def _penalty_configuration(parameters: PenaltyParameters) -> dict[str, object]:
    payload = asdict(parameters)
    payload["initial_penalty_by_type"] = [
        [str(name), float(value)] for name, value in sorted(parameters.initial_penalty_by_type)
    ]
    return _primitive(payload)


def _engine_value(engine: object | None, name: str) -> str | None:
    return None if engine is None else str(getattr(engine, name))


@dataclass(frozen=True)
class EffectiveExecutionBundle:
    schema_version: str
    effective_charging_policy: ChargingRepairPolicy
    route_engine: object
    route_stage_engine: object
    mechanism_stage_engine: object | None
    formal_identity_eligible: bool
    route_engine_source_id: str
    route_stage_source_id: str
    mechanism_stage_source_id: str | None
    route_stage_configuration: dict[str, object] | None
    mechanism_stage_configuration: dict[str, object] | None
    strategy: str
    carbon_weight: float
    depot_charge_window_mode: str
    charge_timing_policy: str
    charge_amount_strategy: str
    public_station_candidate_mode: str
    first_trip_prev_night_enabled: bool
    frvcpy_enabled: bool
    charging_gap_enabled: bool
    carbon_price_cny_per_kg: float
    fairness_enabled: bool
    fairness_theta: float | None
    route_engine_runtime_sha256: str
    route_stage_runtime_sha256: str
    mechanism_stage_runtime_sha256: str | None
    charging_profile_input_sha256: str | None
    min_pop_size: int
    generation_size: int
    num_elite: int
    num_close: int
    lb_diversity: float
    ub_diversity: float
    project_penalty_parameters: dict[str, object]
    repair_probability: float
    repair_booster: int
    num_iters_no_improvement: int
    include_mechanism_refinement: bool
    include_whole_duty_type_exchange: bool
    include_charging_candidates: bool
    incremental_full_truth_sentinel_enabled: bool
    shift_aware_departure_enabled: bool
    schedule_cross_repair_fallback: bool
    schedule_all_changed_move_evaluation: bool
    fleet_activation_enabled: bool
    objective_mode: str
    charging_prescreen_enabled: bool
    charging_prescreen_audit_limit: int
    cross_depot_enabled: bool
    multi_trip_enabled: bool
    type_exchange_enabled: bool
    route_layer_crossover_enabled: bool
    education_depth_limit: int | None

    def algorithm_configuration_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "route_engine_source_id": self.route_engine_source_id,
            "route_stage_configuration": _primitive(self.route_stage_configuration),
            "mechanism_stage_configuration": _primitive(self.mechanism_stage_configuration),
            "charging_policy": {key: getattr(self, key) for key in POLICY_FIELDS},
            "carbon_price_cny_per_kg": self.carbon_price_cny_per_kg,
            "fairness": {
                "enabled": self.fairness_enabled,
                "theta": self.fairness_theta,
            },
            "population": {key: getattr(self, key) for key in POPULATION_FIELDS},
            "project_penalty_parameters": _primitive(self.project_penalty_parameters),
            "copied_kernel": {
                "repair_probability": self.repair_probability,
                "repair_booster": self.repair_booster,
                "num_iters_no_improvement": self.num_iters_no_improvement,
            },
            "live_switches": {key: getattr(self, key) for key in LIVE_SWITCH_FIELDS},
        }

    def runtime_identity_payload(self) -> dict[str, object]:
        return {
            "route_engine_runtime_sha256": self.route_engine_runtime_sha256,
            "route_stage_runtime_sha256": self.route_stage_runtime_sha256,
            "mechanism_stage_runtime_sha256": self.mechanism_stage_runtime_sha256,
            "charging_profile_input_sha256": self.charging_profile_input_sha256,
        }


def build_effective_execution_bundle(
    *,
    policy: ChargingRepairPolicy,
    route_engine: object,
    route_stage_engine: object,
    mechanism_stage_engine: object | None,
    context: object,
    population_parameters: object,
    penalty_parameters: PenaltyParameters,
    repair_probability: float,
    repair_booster: int,
    num_iters_no_improvement: int,
    live_switches: Mapping[str, object],
) -> EffectiveExecutionBundle:
    route_configuration = _stage_configuration(route_stage_engine)
    mechanism_configuration = _stage_configuration(mechanism_stage_engine)
    eligible = route_configuration is not None and (
        mechanism_stage_engine is None or mechanism_configuration is not None
    )
    policy_configuration = charging_policy_configuration(policy)
    profiles = policy.carbon_profiles_by_day_offset
    return EffectiveExecutionBundle(
        schema_version=SCHEMA_VERSION,
        effective_charging_policy=policy,
        route_engine=route_engine,
        route_stage_engine=route_stage_engine,
        mechanism_stage_engine=mechanism_stage_engine,
        formal_identity_eligible=eligible,
        route_engine_source_id=str(route_engine.source_id),
        route_stage_source_id=str(route_stage_engine.source_id),
        mechanism_stage_source_id=_engine_value(mechanism_stage_engine, "source_id"),
        route_stage_configuration=route_configuration,
        mechanism_stage_configuration=mechanism_configuration,
        carbon_price_cny_per_kg=float(context.bundle.prices.carbon_price),
        fairness_enabled=bool(getattr(context, "fairness_enabled", True)),
        fairness_theta=(
            float(getattr(context, "theta", 0.0))
            if bool(getattr(context, "fairness_enabled", True))
            else None
        ),
        route_engine_runtime_sha256=str(route_engine.identity_sha256),
        route_stage_runtime_sha256=str(route_stage_engine.identity_sha256),
        mechanism_stage_runtime_sha256=_engine_value(mechanism_stage_engine, "identity_sha256"),
        charging_profile_input_sha256=(None if profiles is None else _sha256(profiles)),
        min_pop_size=int(population_parameters.min_pop_size),
        generation_size=int(population_parameters.generation_size),
        num_elite=int(population_parameters.num_elite),
        num_close=int(population_parameters.num_close),
        lb_diversity=float(population_parameters.lb_diversity),
        ub_diversity=float(population_parameters.ub_diversity),
        project_penalty_parameters=_penalty_configuration(penalty_parameters),
        repair_probability=float(repair_probability),
        repair_booster=int(repair_booster),
        num_iters_no_improvement=int(num_iters_no_improvement),
        incremental_full_truth_sentinel_enabled=bool(
            getattr(context, "incremental_full_truth_sentinel_enabled", True)
        ),
        shift_aware_departure_enabled=bool(
            getattr(context, "shift_aware_departure_enabled", False)
        ),
        **policy_configuration,
        **live_switches,
    )
