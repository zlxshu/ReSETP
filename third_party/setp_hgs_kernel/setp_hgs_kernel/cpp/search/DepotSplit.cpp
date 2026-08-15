#include "DepotSplit.h"

#include <algorithm>
#include <stdexcept>
#include <utility>
#include <vector>

using setp_hgs_kernel::Cost;
using setp_hgs_kernel::search::DepotSplit;
using setp_hgs_kernel::search::Route;

namespace
{
size_t firstClientInTrip(Route::Node const *node)
{
    auto const *route = node->route();
    auto first = node->idx();
    while (first > 1 && !(*route)[first - 1]->isDepot())
        --first;
    return first;
}

size_t lastClientInTrip(Route::Node const *node)
{
    auto const *route = node->route();
    auto last = node->idx();
    while (last + 1 < route->size() && !(*route)[last + 1]->isDepot())
        ++last;
    return last;
}
}  // namespace

DepotSplit::DepotSplit(ProblemData const &data,
                       std::vector<size_t> compatibleVehicleGroups)
    : NodeOperator(data),
      compatibleVehicleGroups(std::move(compatibleVehicleGroups))
{
    if (this->compatibleVehicleGroups.size() != data.numVehicleTypes())
        throw std::invalid_argument(
            "DepotSplit needs one compatibility group per vehicle type.");
}

Cost DepotSplit::evaluateSegment(Route *source,
                                 Route *target,
                                 size_t first,
                                 size_t last,
                                 CostEvaluator const &costEvaluator) const
{
    auto const movedClients = last - first + 1;
    Cost deltaCost = target->fixedVehicleCost();
    if (movedClients == source->numClients())
        deltaCost -= source->fixedVehicleCost();

    auto const sourceProposal
        = Route::Proposal(source->before(first - 1), source->after(last + 1));
    auto const targetProposal
        = Route::Proposal(target->before(0),
                          source->between(first, last),
                          target->after(1));
    costEvaluator.deltaCost(deltaCost, sourceProposal, targetProposal);
    return deltaCost;
}

Cost DepotSplit::evaluate(Route::Node *U,
                          Route::Node *V,
                          CostEvaluator const &costEvaluator)
{
    stats_.numEvaluations++;
    direction = Direction::NONE;

    if (!U->route() || !V->route() || U->isDepot()
        || !V->isStartDepot())
        return 0;

    auto *source = U->route();
    auto *target = V->route();
    if (source == target || !target->empty()
        || source->startDepot() != source->endDepot()
        || target->startDepot() != target->endDepot()
        || source->startDepot() == target->startDepot())
        return 0;

    auto const sourceType = source->vehicleType();
    auto const targetType = target->vehicleType();
    if (compatibleVehicleGroups[sourceType]
        != compatibleVehicleGroups[targetType])
        return 0;

    auto const firstClient = firstClientInTrip(U);
    auto const lastClient = lastClientInTrip(U);
    auto const prefixCost = evaluateSegment(
        source, target, firstClient, U->idx(), costEvaluator);
    auto bestCost = prefixCost;
    direction = Direction::PREFIX;

    if (U->idx() != firstClient || U->idx() != lastClient)
    {
        auto const suffixCost = evaluateSegment(
            source, target, U->idx(), lastClient, costEvaluator);
        if (suffixCost < bestCost)
        {
            bestCost = suffixCost;
            direction = Direction::SUFFIX;
        }
    }

    if (bestCost >= 0)
        direction = Direction::NONE;
    return std::min<Cost>(bestCost, 0);
}

void DepotSplit::apply(Route::Node *U, Route::Node *V) const
{
    if (direction == Direction::NONE)
        throw std::logic_error("DepotSplit apply() has no improving move.");

    stats_.numApplications++;
    auto *source = U->route();
    auto *target = V->route();
    auto const first
        = direction == Direction::PREFIX ? firstClientInTrip(U) : U->idx();
    auto const last
        = direction == Direction::PREFIX ? U->idx() : lastClientInTrip(U);

    std::vector<Route::Node *> moved;
    moved.reserve(last - first + 1);
    for (size_t idx = first; idx <= last; ++idx)
        moved.push_back((*source)[idx]);

    for (auto *node : moved)
        source->remove(node->idx());
    for (auto *node : moved)
        target->insert(target->size() - 1, node);
}

template <>
bool setp_hgs_kernel::search::supports<DepotSplit>(ProblemData const &data)
{
    return data.numDepots() > 1 && data.numVehicleTypes() > 1;
}
