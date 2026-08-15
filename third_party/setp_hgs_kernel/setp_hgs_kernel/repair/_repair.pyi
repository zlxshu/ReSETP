from setp_hgs_kernel import (
    CostEvaluator,
    ProblemData,
    RandomNumberGenerator,
    Route,
)

class SISRInsertion:
    client: int
    route_index: int
    position: int
    delta_cost: int

class SISRRepairResult:
    routes: list[Route]
    selected_insertions: list[SISRInsertion]
    positions_evaluated: int
    positions_blinked: int
    new_routes_created: int
    reconstructed: bool

def greedy_repair(
    routes: list[Route],
    unplanned: list[int],
    data: ProblemData,
    cost_evaluator: CostEvaluator,
) -> list[Route]: ...
def nearest_route_insert(
    routes: list[Route],
    unplanned: list[int],
    data: ProblemData,
    cost_evaluator: CostEvaluator,
) -> list[Route]: ...
def sisr_repair(
    routes: list[Route],
    unplanned: list[int],
    data: ProblemData,
    cost_evaluator: CostEvaluator,
    rng: RandomNumberGenerator,
    blink_probability: float,
) -> SISRRepairResult: ...
