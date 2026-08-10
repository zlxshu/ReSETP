from setp_hgs_kernel import CostEvaluator, ProblemData, Route

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
