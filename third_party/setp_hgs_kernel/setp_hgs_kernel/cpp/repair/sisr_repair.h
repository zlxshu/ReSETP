#ifndef SETP_HGS_KERNEL_REPAIR_SISR_REPAIR_H
#define SETP_HGS_KERNEL_REPAIR_SISR_REPAIR_H

#include "CostEvaluator.h"
#include "ProblemData.h"
#include "RandomNumberGenerator.h"
#include "Route.h"

#include <vector>

namespace setp_hgs_kernel::repair
{
struct SISRInsertion
{
    size_t client;
    size_t routeIndex;
    size_t position;
    Cost deltaCost;
};

struct SISRRepairResult
{
    std::vector<Route> routes;
    std::vector<SISRInsertion> selectedInsertions;
    size_t positionsEvaluated;
    size_t positionsBlinked;
    size_t newRoutesCreated;
    bool reconstructed;
};

/**
 * Faithful all-route, all-position SISR recreate using cached incremental
 * insertion evaluation. Blink draws occur only when a candidate improves the
 * current best value, following Pajersky, Sobotka and Rudova (2026).
 */
SISRRepairResult sisrRepair(std::vector<Route> const &solRoutes,
                            std::vector<size_t> const &unplanned,
                            ProblemData const &data,
                            CostEvaluator const &costEvaluator,
                            RandomNumberGenerator &rng,
                            double blinkProbability);
}  // namespace setp_hgs_kernel::repair

#endif  // SETP_HGS_KERNEL_REPAIR_SISR_REPAIR_H
