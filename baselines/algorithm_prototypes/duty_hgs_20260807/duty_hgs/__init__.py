"""Isolated Duty-HGS construction package.

v1 2026-08-07: initial decision objects.
v2 2026-08-07: runnable whole-duty HGS, full evaluation, and safe charging.
v3 2026-08-07: expose frozen input identities used by the formal runner.
"""

from .charging import ChargingRepairPolicy
from .dynamic import (
    DutyDynamicState,
    PreparedDynamicCandidate,
    future_individual_from_cut,
    prepare_dynamic_candidate,
)
from .evaluation import FrozenMappingIdentity, mapping_sha256
from .model import (
    DutyChargingSession,
    DutyIndividual,
    DutyTrip,
    PhysicalVehicleDuty,
)
from .runner import (
    DutyHGSRunProvenance,
    DutyHGSRunResult,
    DutyHGSSearchParameters,
    DutyHGSSearchState,
    FrozenPopulationIdentity,
    population_sha256,
    run_duty_hgs,
    search_configuration_sha256,
)

__all__ = [
    "ChargingRepairPolicy",
    "DutyChargingSession",
    "DutyDynamicState",
    "DutyHGSRunProvenance",
    "DutyHGSRunResult",
    "DutyHGSSearchParameters",
    "DutyHGSSearchState",
    "DutyIndividual",
    "DutyTrip",
    "FrozenMappingIdentity",
    "FrozenPopulationIdentity",
    "PhysicalVehicleDuty",
    "PreparedDynamicCandidate",
    "future_individual_from_cut",
    "mapping_sha256",
    "population_sha256",
    "prepare_dynamic_candidate",
    "run_duty_hgs",
    "search_configuration_sha256",
]
