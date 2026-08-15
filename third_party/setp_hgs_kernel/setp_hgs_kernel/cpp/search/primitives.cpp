#include "primitives.h"

#include <algorithm>
#include <cassert>

namespace
{
/**
 * Simple wrapper class that implements the required evaluation interface for
 * a single client that might not currently be in the solution.
 */
class ClientSegment
{
    setp_hgs_kernel::ProblemData const &data;
    size_t client;

public:
    ClientSegment(setp_hgs_kernel::ProblemData const &data, size_t client)
        : data(data), client(client)
    {
        assert(client >= data.numDepots());  // must be an actual client
    }

    setp_hgs_kernel::search::Route const *route() const { return nullptr; }

    size_t first() const { return client; }
    size_t last() const { return client; }
    size_t size() const { return 1; }

    bool startsAtReloadDepot() const { return false; }
    bool endsAtReloadDepot() const { return false; }

    setp_hgs_kernel::Distance distance([[maybe_unused]] size_t profile) const
    {
        return 0;
    }

    setp_hgs_kernel::DurationSegment duration([[maybe_unused]] size_t profile) const
    {
        setp_hgs_kernel::ProblemData::Client const &clientData = data.location(client);
        return {clientData};
    }

    setp_hgs_kernel::LoadSegment load(size_t dimension) const
    {
        return {data.location(client), dimension};
    }
};

/**
 * One reload marker, adapted from PyVRP 0.12.2 RelocateWithDepot.cpp.
 * It resets every load dimension and contributes the depot time window.
 */
class ReloadDepotSegment
{
    setp_hgs_kernel::ProblemData const &data;
    size_t depot;

public:
    ReloadDepotSegment(setp_hgs_kernel::ProblemData const &data, size_t depot)
        : data(data), depot(depot)
    {
        assert(depot < data.numDepots());
    }

    setp_hgs_kernel::search::Route const *route() const { return nullptr; }

    size_t first() const { return depot; }
    size_t last() const { return depot; }
    size_t size() const { return 1; }

    bool startsAtReloadDepot() const { return true; }
    bool endsAtReloadDepot() const { return true; }

    setp_hgs_kernel::Distance distance([[maybe_unused]] size_t profile) const
    {
        return 0;
    }

    setp_hgs_kernel::DurationSegment duration([[maybe_unused]] size_t profile) const
    {
        setp_hgs_kernel::ProblemData::Depot const &depotData = data.location(depot);
        return {depotData};
    }

    setp_hgs_kernel::LoadSegment load([[maybe_unused]] size_t dimension) const
    {
        return {};
    }
};
}  // namespace

setp_hgs_kernel::Cost setp_hgs_kernel::search::insertCost(Route::Node *U,
                                      Route::Node *V,
                                      ProblemData const &data,
                                      CostEvaluator const &costEvaluator)
{
    if (!V->route() || U->isDepot())
        return 0;

    auto *route = V->route();
    ProblemData::Client const &client = data.location(U->client());

    Cost deltaCost
        = Cost(route->empty()) * route->fixedVehicleCost() - client.prize;

    costEvaluator.deltaCost<true>(
        deltaCost,
        Route::Proposal(route->before(V->idx()),
                        ClientSegment(data, U->client()),
                        route->after(V->idx() + 1)));

    return deltaCost;
}

bool setp_hgs_kernel::search::insertFeasible(Route::Node *U,
                                             Route::Node *V,
                                             ProblemData const &data)
{
    if (!V->route() || U->isDepot())
        return false;

    auto *route = V->route();
    Route::Proposal proposal(route->before(V->idx()),
                             ClientSegment(data, U->client()),
                             route->after(V->idx() + 1));

    if (proposal.distance().second > 0)
        return false;

    for (size_t dim = 0; dim != route->capacity().size(); ++dim)
        if (proposal.excessLoad(dim) > 0)
            return false;

    return proposal.duration().second == 0;
}

setp_hgs_kernel::Cost setp_hgs_kernel::search::insertReloadCost(
    Route::Node *V,
    size_t depot,
    ProblemData const &data,
    CostEvaluator const &costEvaluator)
{
    if (!V->route() || V->isEndDepot() || depot >= data.numDepots())
        return 0;

    auto *route = V->route();
    auto const &reloadDepots
        = data.vehicleType(route->vehicleType()).reloadDepots;
    if (std::find(reloadDepots.begin(), reloadDepots.end(), depot)
        == reloadDepots.end())
        return 0;

    Cost deltaCost = 0;
    costEvaluator.deltaCost<true>(
        deltaCost,
        Route::Proposal(route->before(V->idx()),
                        ReloadDepotSegment(data, depot),
                        route->after(V->idx() + 1)));

    return deltaCost;
}

bool setp_hgs_kernel::search::insertReloadFeasible(Route::Node *V,
                                                   size_t depot,
                                                   ProblemData const &data)
{
    if (!V->route() || V->isEndDepot() || depot >= data.numDepots())
        return false;

    auto *route = V->route();
    auto const &reloadDepots
        = data.vehicleType(route->vehicleType()).reloadDepots;
    if (std::find(reloadDepots.begin(), reloadDepots.end(), depot)
        == reloadDepots.end())
        return false;

    Route::Proposal proposal(route->before(V->idx()),
                             ReloadDepotSegment(data, depot),
                             route->after(V->idx() + 1));
    if (proposal.distance().second > 0)
        return false;

    for (size_t dim = 0; dim != route->capacity().size(); ++dim)
        if (proposal.excessLoad(dim) > 0)
            return false;

    return proposal.duration().second == 0;
}

setp_hgs_kernel::Cost setp_hgs_kernel::search::removeCost(Route::Node *U,
                                      ProblemData const &data,
                                      CostEvaluator const &costEvaluator)
{
    if (!U->route() || U->isStartDepot() || U->isEndDepot())
        return 0;

    auto *route = U->route();
    Cost deltaCost = 0;

    if (!U->isDepot())
    {
        ProblemData::Client const &client = data.location(U->client());
        deltaCost
            = client.prize
              - Cost(route->numClients() == 1) * route->fixedVehicleCost();
    }

    costEvaluator.deltaCost<true>(deltaCost,
                                  Route::Proposal(route->before(U->idx() - 1),
                                                  route->after(U->idx() + 1)));

    return deltaCost;
}

setp_hgs_kernel::Cost setp_hgs_kernel::search::inplaceCost(Route::Node *U,
                                       Route::Node *V,
                                       ProblemData const &data,
                                       CostEvaluator const &costEvaluator)
{
    if (U->route() || !V->route())
        return 0;

    auto const *route = V->route();
    ProblemData::Client const &uClient = data.location(U->client());
    ProblemData::Client const &vClient = data.location(V->client());

    Cost deltaCost = vClient.prize - uClient.prize;

    costEvaluator.deltaCost<true>(
        deltaCost,
        Route::Proposal(route->before(V->idx() - 1),
                        ClientSegment(data, U->client()),
                        route->after(V->idx() + 1)));

    return deltaCost;
}
