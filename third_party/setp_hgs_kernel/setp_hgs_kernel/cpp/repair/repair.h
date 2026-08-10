#ifndef PYVRP_REPAIR_H
#define PYVRP_REPAIR_H

#include "CostEvaluator.h"
#include "ProblemData.h"
#include "Solution.h"
#include "search/Route.h"

#include <vector>

namespace setp_hgs_kernel::repair
{
// Populate the given locs and routes vectors with routes from the solution.
void setupRoutes(std::vector<search::Route::Node> &locs,
                 std::vector<search::Route> &routes,
                 std::vector<setp_hgs_kernel::Route> const &solRoutes,
                 ProblemData const &data);

// Turns the given search routes into solution routes.
std::vector<setp_hgs_kernel::Route>
exportRoutes(ProblemData const &data, std::vector<search::Route> const &routes);
}  // namespace setp_hgs_kernel::repair

#endif  // PYVRP_REPAIR_H
