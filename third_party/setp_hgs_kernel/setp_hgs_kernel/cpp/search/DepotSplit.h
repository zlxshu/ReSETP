#ifndef SETP_HGS_KERNEL_SEARCH_DEPOTSPLIT_H
#define SETP_HGS_KERNEL_SEARCH_DEPOTSPLIT_H

#include "LocalSearchOperator.h"

#include <cstddef>
#include <vector>

namespace setp_hgs_kernel::search
{
/**
 * DepotSplit(data, compatible_vehicle_groups)
 *
 * Moves a trip prefix or suffix to an empty vehicle based at another depot.
 * This is the closed-route counterpart of HGAMP's Splitf/Splitb depot-insert
 * action: physical vehicle homes remain fixed, while the moved customers are
 * reassigned to a duty owned by another depot. For multi-trip routes, only a
 * segment contained in one trip is moved; existing reload boundaries outside
 * that segment stay untouched.
 *
 * Candidate costs are computed from cached route segments through
 * CostEvaluator::deltaCost(). The target remains a single closed trip owned by
 * its physical vehicle; complete duty scheduling is handled above this kernel.
 */
class DepotSplit : public NodeOperator
{
    enum class Direction
    {
        NONE,
        PREFIX,
        SUFFIX,
    };

    std::vector<size_t> compatibleVehicleGroups;
    Direction direction = Direction::NONE;

    Cost evaluateSegment(Route *source,
                         Route *target,
                         size_t first,
                         size_t last,
                         CostEvaluator const &costEvaluator) const;

public:
    Cost evaluate(Route::Node *U,
                  Route::Node *V,
                  CostEvaluator const &costEvaluator) override;

    void apply(Route::Node *U, Route::Node *V) const override;

    bool supportsInitialEmptyRouteMoves() const override { return true; }

    DepotSplit(ProblemData const &data,
               std::vector<size_t> compatibleVehicleGroups);
};

template <> bool supports<DepotSplit>(ProblemData const &data);
}  // namespace setp_hgs_kernel::search

#endif  // SETP_HGS_KERNEL_SEARCH_DEPOTSPLIT_H
