"""Isolated Problem-HGS construction package.

v1 2026-08-07: initial decision objects.
v2 2026-08-07: runnable whole-duty HGS, full evaluation, and safe charging.
v3 2026-08-07: expose frozen input identities used by the formal runner.
v4 2026-08-08: formal complete DCREX replaces the prototype crossover.
"""

from .charging import ChargingRepairPolicy
from .bi_objective_population import BI_OBJECTIVE, SINGLE_OBJECTIVE
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
    ScheduleAccountingVector,
    ScheduledChargingSession,
    ScheduledDuty,
    ScheduledSOCPoint,
    ScheduledTripWitness,
)
from .schedule_oracle import (
    OracleStatus,
    ScheduleCoordinator,
    ScheduleOracleContext,
    SingleDutyScheduleOracle,
)
from .runner import (
    BiObjectiveSolutionRecord,
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
    "BI_OBJECTIVE",
    "SINGLE_OBJECTIVE",
    "BiObjectiveSolutionRecord",
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
    "ScheduleAccountingVector",
    "ScheduleCoordinator",
    "ScheduleOracleContext",
    "ScheduledChargingSession",
    "ScheduledDuty",
    "ScheduledSOCPoint",
    "ScheduledTripWitness",
    "SingleDutyScheduleOracle",
    "OracleStatus",
    "PreparedDynamicCandidate",
    "future_individual_from_cut",
    "mapping_sha256",
    "population_sha256",
    "prepare_dynamic_candidate",
    "run_integrated_problem_hgs",
    "search_configuration_sha256",
]
