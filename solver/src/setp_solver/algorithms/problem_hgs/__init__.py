"""Isolated Problem-HGS construction package.

v1 2026-08-07: initial decision objects.
v2 2026-08-07: runnable whole-duty HGS, full evaluation, and safe charging.
v3 2026-08-07: expose frozen input identities used by the formal runner.
v4 2026-08-08: formal complete DCREX replaces the prototype crossover.
"""

from .charging import ChargingRepairPolicy
from .dcrex import DCREXController, InsertionOperator
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
    ProblemHGSRunProvenance,
    ProblemHGSRunResult,
    ProblemHGSSearchParameters,
    ProblemHGSSearchState,
    FrozenPopulationIdentity,
    population_sha256,
    run_integrated_problem_hgs,
    search_configuration_sha256,
)
from .stopping import MaxIterations

__all__ = [
    "ChargingRepairPolicy",
    "DCREXController",
    "DutyChargingSession",
    "DutyDynamicState",
    "ProblemHGSRunProvenance",
    "ProblemHGSRunResult",
    "ProblemHGSSearchParameters",
    "ProblemHGSSearchState",
    "DutyIndividual",
    "DutyTrip",
    "FrozenMappingIdentity",
    "FrozenPopulationIdentity",
    "InsertionOperator",
    "MaxIterations",
    "PhysicalVehicleDuty",
    "PreparedDynamicCandidate",
    "future_individual_from_cut",
    "mapping_sha256",
    "population_sha256",
    "prepare_dynamic_candidate",
    "run_integrated_problem_hgs",
    "search_configuration_sha256",
]
