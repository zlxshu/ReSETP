"""Runtime objects and switches used by the integrated Problem-HGS loop."""

from __future__ import annotations

from dataclasses import dataclass

from .charging import ChargingRepairPolicy


@dataclass(frozen=True)
class ExecutionSettings:
    charging_policy: ChargingRepairPolicy
    route_engine: object
    route_stage_engine: object
    mechanism_stage_engine: object | None
    repair_probability: float
    repair_booster: int
    num_iters_no_improvement: int
    include_whole_duty_type_exchange: bool
    include_charging_candidates: bool
    schedule_all_changed_move_evaluation: bool
    fleet_activation_enabled: bool
    charging_prescreen_enabled: bool
    education_depth_limit: int | None

    @property
    def effective_charging_policy(self) -> ChargingRepairPolicy:
        return self.charging_policy

    @property
    def frvcpy_enabled(self) -> bool:
        return bool(self.charging_policy.frvcpy_enabled)

    @property
    def charge_timing_policy(self) -> str:
        return str(self.charging_policy.charge_timing_policy)


def build_execution_settings(
    *,
    policy: ChargingRepairPolicy,
    route_engine: object,
    route_stage_engine: object,
    mechanism_stage_engine: object | None,
    repair_probability: float,
    repair_booster: int,
    num_iters_no_improvement: int,
    include_whole_duty_type_exchange: bool,
    include_charging_candidates: bool,
    schedule_all_changed_move_evaluation: bool,
    fleet_activation_enabled: bool,
    charging_prescreen_enabled: bool,
    education_depth_limit: int | None,
) -> ExecutionSettings:
    return ExecutionSettings(
        charging_policy=policy,
        route_engine=route_engine,
        route_stage_engine=route_stage_engine,
        mechanism_stage_engine=mechanism_stage_engine,
        repair_probability=float(repair_probability),
        repair_booster=int(repair_booster),
        num_iters_no_improvement=int(num_iters_no_improvement),
        include_whole_duty_type_exchange=bool(
            include_whole_duty_type_exchange
        ),
        include_charging_candidates=bool(include_charging_candidates),
        schedule_all_changed_move_evaluation=bool(
            schedule_all_changed_move_evaluation
        ),
        fleet_activation_enabled=bool(fleet_activation_enabled),
        charging_prescreen_enabled=bool(charging_prescreen_enabled),
        education_depth_limit=education_depth_limit,
    )
