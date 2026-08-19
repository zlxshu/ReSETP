#include "LocalSearch.h"
#include "Measure.h"
#include "Trip.h"
#include "primitives.h"

#include <algorithm>
#include <cassert>
#include <numeric>
#include <utility>

using setp_hgs_kernel::Solution;
using setp_hgs_kernel::search::LocalSearch;
using setp_hgs_kernel::search::NodeOperator;
using setp_hgs_kernel::search::RouteOperator;

namespace
{
bool candidateLess(LocalSearch::Candidate const &first,
                   LocalSearch::Candidate const &second)
{
    return first.proxyDelta < second.proxyDelta
           || (first.proxyDelta == second.proxyDelta
               && first.scanOrdinal < second.scanOrdinal);
}
}  // namespace

void LocalSearch::retainCandidate(std::vector<Candidate> &candidates,
                                  Solution candidate,
                                  Cost proxyDelta,
                                  size_t scanOrdinal,
                                  size_t limit)
{
    candidateStatistics_.numMaterialised++;
    auto const duplicate = std::find_if(
        candidates.begin(),
        candidates.end(),
        [&](Candidate const &other) { return other.solution() == candidate; });
    Candidate materialised(std::move(candidate), proxyDelta, scanOrdinal);
    if (duplicate != candidates.end())
    {
        if (candidateLess(materialised, *duplicate))
            *duplicate = std::move(materialised);
        return;
    }

    if (candidates.size() < limit)
        candidates.push_back(std::move(materialised));
    else
    {
        auto const worst = std::max_element(
            candidates.begin(), candidates.end(), candidateLess);
        if (candidateLess(materialised, *worst))
            *worst = std::move(materialised);
    }
}

std::vector<LocalSearch::Candidate> LocalSearch::promisingCandidates(
    Solution const &solution,
    CostEvaluator const &costEvaluator,
    size_t limit)
{
    if (limit == 0)
        throw std::invalid_argument("Candidate limit must be positive.");
    if (!solution.isComplete())
        throw std::invalid_argument(
            "Candidate scan requires a complete base solution.");
    if (data.numGroups() != 0)
        throw std::invalid_argument(
            "Candidate scan does not support client groups.");
    for (size_t client = data.numDepots(); client != data.numLocations(); ++client)
    {
        ProblemData::Client const &clientData = data.location(client);
        if (!clientData.required)
            throw std::invalid_argument(
                "Candidate scan does not support optional clients.");
    }

    candidateStatistics_ = {};
    std::vector<Candidate> candidates;
    candidates.reserve(limit);
    size_t scanOrdinal = 0;
    loadSolution(solution);

    auto const competitive = [&](Cost proxyDelta, size_t ordinal)
    {
        if (candidates.size() < limit)
            return true;
        auto const worst = std::max_element(
            candidates.begin(), candidates.end(), candidateLess);
        return proxyDelta < worst->proxyDelta
               || (proxyDelta == worst->proxyDelta
                   && ordinal < worst->scanOrdinal);
    };

    auto const scanNodePair = [&](size_t uClient,
                                  bool vIsRouteStart,
                                  size_t vIndex)
    {
        for (auto *nodeOp : nodeOps)
        {
            auto *U = &nodes[uClient];
            auto *V = vIsRouteStart ? routes[vIndex][0] : &nodes[vIndex];
            if (!U->route() || !V->route())
                continue;

            auto const ordinal = scanOrdinal++;
            auto const deltaCost = nodeOp->evaluate(U, V, costEvaluator);
            candidateStatistics_.numEvaluated++;
            if (deltaCost >= 0)
                continue;
            candidateStatistics_.numPromising++;
            if (!competitive(deltaCost, ordinal))
                continue;

            auto *rU = U->route();
            auto *rV = V->route();
            nodeOp->apply(U, V);
            update(rU, rV);
            retainCandidate(candidates,
                            exportSolution(),
                            deltaCost,
                            ordinal,
                            limit);
            loadSolution(solution);
        }
    };

    auto const scanDepotRemoval = [&](size_t routeIndex, size_t nodeIndex)
    {
        auto *U = routes[routeIndex][nodeIndex];
        if (!U->isReloadDepot())
            return;

        auto const ordinal = scanOrdinal++;
        auto const deltaCost = removeCost(U, data, costEvaluator);
        candidateStatistics_.numEvaluated++;
        if (deltaCost > 0)
            return;
        candidateStatistics_.numPromising++;
        if (!competitive(deltaCost, ordinal))
            return;

        auto *route = U->route();
        route->remove(U->idx());
        update(route, route);
        retainCandidate(candidates,
                        exportSolution(),
                        deltaCost,
                        ordinal,
                        limit);
        loadSolution(solution);
    };

    // Enumerate one-step node moves from the shared base.  Empty routes are
    // opened to all operators here: the external exact-truth loop replaces the
    // proxy-only intermediate step that historically unlocked those moves.
    for (auto const uClient : orderNodes)
    {
        auto *U = &nodes[uClient];
        if (!U->route())
            continue;

        auto const routeIndex = U->route()->idx();
        auto const prevIndex = p(U)->idx();
        auto const nextIndex = n(U)->idx();
        if (p(U)->isReloadDepot())
            scanDepotRemoval(routeIndex, prevIndex);
        if (n(U)->isReloadDepot())
            scanDepotRemoval(routeIndex, nextIndex);

        for (auto const vClient : neighbours_[uClient])
        {
            auto *V = &nodes[vClient];
            if (!V->route())
                continue;
            scanNodePair(uClient, false, vClient);

            V = &nodes[vClient];
            if (V->route() && p(V)->isStartDepot())
                scanNodePair(uClient, true, V->route()->idx());
        }

        for (auto const &[vehType, offset] : orderVehTypes)
        {
            auto const begin = routes.begin() + offset;
            auto const end = begin + data.vehicleType(vehType).numAvailable;
            auto const empty = std::find_if(
                begin, end, [](auto const &route) { return route.empty(); });
            if (empty != end)
                scanNodePair(uClient, true, empty->idx());
        }
    }

    // Route operators already represent one compound move, so each negative
    // evaluation can be materialised directly from the same base solution.
    for (auto const rU : orderRoutes)
    {
        if (routes[rU].empty())
            continue;
        for (size_t rV = rU + 1; rV != routes.size(); ++rV)
        {
            if (routes[rV].empty())
                continue;
            for (auto *routeOp : routeOps)
            {
                auto *U = &routes[rU];
                auto *V = &routes[rV];
                auto const ordinal = scanOrdinal++;
                auto const deltaCost = routeOp->evaluate(U, V, costEvaluator);
                candidateStatistics_.numEvaluated++;
                if (deltaCost >= 0)
                    continue;
                candidateStatistics_.numPromising++;
                if (!competitive(deltaCost, ordinal))
                    continue;

                routeOp->apply(U, V);
                update(U, V);
                retainCandidate(candidates,
                                exportSolution(),
                                deltaCost,
                                ordinal,
                                limit);
                loadSolution(solution);
            }
        }
    }

    std::sort(candidates.begin(), candidates.end(), candidateLess);
    candidateStatistics_.numReturned = candidates.size();
    loadSolution(solution);
    return candidates;
}

Solution LocalSearch::operator()(Solution const &solution,
                                 CostEvaluator const &costEvaluator)
{
    loadSolution(solution);

    while (true)
    {
        search(costEvaluator);
        auto const numUpdates = numUpdates_;  // after node search

        intensify(costEvaluator);
        if (numUpdates_ == numUpdates)
            // Then intensify (route search) did not do any additional
            // updates, so the solution is locally optimal.
            break;
    }

    return exportSolution();
}

Solution LocalSearch::search(Solution const &solution,
                             CostEvaluator const &costEvaluator)
{
    loadSolution(solution);
    search(costEvaluator);
    return exportSolution();
}

Solution LocalSearch::intensify(Solution const &solution,
                                CostEvaluator const &costEvaluator)
{
    loadSolution(solution);
    intensify(costEvaluator);
    return exportSolution();
}

Solution LocalSearch::repairRequired(Solution const &solution,
                                     CostEvaluator const &costEvaluator)
{
    loadSolution(solution);

    for (auto const uClient : orderNodes)
    {
        auto *U = &nodes[uClient];
        ProblemData::Client const &client = data.location(U->client());
        if (!U->route() && client.required)
            insertRequiredFeasible(U, costEvaluator);
    }

    return exportSolution();
}

void LocalSearch::search(CostEvaluator const &costEvaluator)
{
    if (nodeOps.empty())
        return;

    searchCompleted_ = false;
    for (int step = 0; !searchCompleted_; ++step)
    {
        searchCompleted_ = true;

        // Node operators are evaluated for neighbouring (U, V) pairs.
        for (auto const uClient : orderNodes)
        {
            auto *U = &nodes[uClient];

            auto const lastTested = lastTestedNodes[uClient];
            lastTestedNodes[uClient] = numUpdates_;

            // First test removing or inserting U. Particularly relevant if not
            // all clients are required (e.g., when prize collecting).
            applyOptionalClientMoves(U, costEvaluator);

            // Evaluate moves involving the client's group, if it is in any.
            applyGroupMoves(U, costEvaluator);

            if (!U->route())  // we already evaluated inserting U, so there is
                continue;     // nothing left to be done for this client.

            // If U borders a reload depot, try removing it.
            applyDepotRemovalMove(p(U), costEvaluator);
            applyDepotRemovalMove(n(U), costEvaluator);

            // We next apply the regular node operators. These work on pairs
            // of nodes (U, V), where both U and V are in the solution.
            for (auto const vClient : neighbours_[uClient])
            {
                auto *V = &nodes[vClient];

                if (!V->route())
                    continue;

                if (lastUpdated[U->route()->idx()] > lastTested
                    || lastUpdated[V->route()->idx()] > lastTested)
                {
                    if (applyNodeOps(U, V, costEvaluator))
                        continue;

                    if (p(V)->isStartDepot()
                        && applyNodeOps(U, p(V), costEvaluator))
                        continue;
                }
            }

            // Moves involving empty routes are not tested in the first
            // iteration to avoid using too many routes.
            if (step > 0 || hasInitialEmptyRouteOperator)
                applyEmptyRouteMoves(U, costEvaluator, step == 0);
        }
    }
}

void LocalSearch::intensify(CostEvaluator const &costEvaluator)
{
    if (routeOps.empty())
        return;

    searchCompleted_ = false;
    while (!searchCompleted_)
    {
        searchCompleted_ = true;

        for (auto const rU : orderRoutes)
        {
            auto &U = routes[rU];
            assert(U.idx() == rU);

            if (U.empty())
                continue;

            auto const lastTested = lastTestedRoutes[U.idx()];
            lastTestedRoutes[U.idx()] = numUpdates_;

            for (size_t rV = U.idx() + 1; rV != routes.size(); ++rV)
            {
                auto &V = routes[rV];
                assert(V.idx() == rV);

                if (V.empty())
                    continue;

                if (lastUpdated[U.idx()] > lastTested
                    || lastUpdated[V.idx()] > lastTested)
                    applyRouteOps(&U, &V, costEvaluator);
            }
        }
    }
}

void LocalSearch::shuffle(RandomNumberGenerator &rng)
{
    rng.shuffle(orderNodes.begin(), orderNodes.end());
    rng.shuffle(nodeOps.begin(), nodeOps.end());

    rng.shuffle(orderRoutes.begin(), orderRoutes.end());
    rng.shuffle(routeOps.begin(), routeOps.end());

    rng.shuffle(orderVehTypes.begin(), orderVehTypes.end());
}

bool LocalSearch::applyNodeOps(Route::Node *U,
                               Route::Node *V,
                               CostEvaluator const &costEvaluator,
                               bool initialEmptyOnly)
{
    for (auto *nodeOp : nodeOps)
    {
        if (initialEmptyOnly && !nodeOp->supportsInitialEmptyRouteMoves())
            continue;

        auto const deltaCost = nodeOp->evaluate(U, V, costEvaluator);
        if (deltaCost < 0)
        {
            auto *rU = U->route();  // copy these because the operator can
            auto *rV = V->route();  // modify the nodes' route membership

            [[maybe_unused]] auto const costBefore
                = costEvaluator.penalisedCost(*rU)
                  + Cost(rU != rV) * costEvaluator.penalisedCost(*rV);

            nodeOp->apply(U, V);
            update(rU, rV);

            [[maybe_unused]] auto const costAfter
                = costEvaluator.penalisedCost(*rU)
                  + Cost(rU != rV) * costEvaluator.penalisedCost(*rV);

            // When there is an improving move, the delta cost evaluation must
            // be exact. The resulting cost is then the sum of the cost before
            // the move, plus the delta cost.
            assert(costAfter == costBefore + deltaCost);

            return true;
        }
    }

    return false;
}

bool LocalSearch::applyRouteOps(Route *U,
                                Route *V,
                                CostEvaluator const &costEvaluator)
{
    for (auto *routeOp : routeOps)
    {
        auto const deltaCost = routeOp->evaluate(U, V, costEvaluator);
        if (deltaCost < 0)
        {
            [[maybe_unused]] auto const costBefore
                = costEvaluator.penalisedCost(*U)
                  + Cost(U != V) * costEvaluator.penalisedCost(*V);

            routeOp->apply(U, V);
            update(U, V);

            [[maybe_unused]] auto const costAfter
                = costEvaluator.penalisedCost(*U)
                  + Cost(U != V) * costEvaluator.penalisedCost(*V);

            // When there is an improving move, the delta cost evaluation must
            // be exact. The resulting cost is then the sum of the cost before
            // the move, plus the delta cost.
            assert(costAfter == costBefore + deltaCost);

            return true;
        }
    }

    return false;
}

void LocalSearch::applyDepotRemovalMove(Route::Node *U,
                                        CostEvaluator const &costEvaluator)
{
    if (!U->isReloadDepot())
        return;

    // We remove the depot when that's either better, or neutral. It can be
    // neutral if for example it's the same depot visited consecutively, but
    // that's then unnecessary.
    if (removeCost(U, data, costEvaluator) <= 0)
    {
        auto *route = U->route();
        route->remove(U->idx());
        update(route, route);
    }
}

void LocalSearch::applyEmptyRouteMoves(Route::Node *U,
                                       CostEvaluator const &costEvaluator,
                                       bool initialEmptyOnly)
{
    assert(U->route());

    // We apply moves involving empty routes in the (randomised) order of
    // orderVehTypes. This helps because empty vehicle moves incur fixed cost,
    // and a purely greedy approach over-prioritises vehicles with low fixed
    // costs but possibly high variable costs.
    for (auto const &[vehType, offset] : orderVehTypes)
    {
        auto const begin = routes.begin() + offset;
        auto const end = begin + data.vehicleType(vehType).numAvailable;
        auto const pred = [](auto const &route) { return route.empty(); };
        auto empty = std::find_if(begin, end, pred);

        if (empty != end
            && applyNodeOps(U, (*empty)[0], costEvaluator, initialEmptyOnly))
            break;
    }
}

void LocalSearch::applyOptionalClientMoves(Route::Node *U,
                                           CostEvaluator const &costEvaluator)
{
    ProblemData::Client const &uData = data.location(U->client());

    if (uData.group)  // groups have their own operator - applyGroupMoves()
        return;

    if (!uData.required && removeCost(U, data, costEvaluator) < 0)
    {
        auto *route = U->route();
        route->remove(U->idx());
        update(route, route);
    }

    if (!U->route())
        insert(U, costEvaluator, uData.required);
}

void LocalSearch::applyGroupMoves(Route::Node *U,
                                  CostEvaluator const &costEvaluator)
{
    ProblemData::Client const &uData = data.location(U->client());

    if (!uData.group)
        return;

    auto const &group = data.group(*uData.group);
    assert(group.mutuallyExclusive);

    std::vector<size_t> inSol;
    auto const pred = [&](auto client) { return nodes[client].route(); };
    std::copy_if(group.begin(), group.end(), std::back_inserter(inSol), pred);

    if (inSol.empty())
    {
        insert(U, costEvaluator, group.required);
        return;
    }

    // We remove clients in order of increasing cost delta (biggest improvement
    // first), and evaluate swapping the last client with U.
    std::vector<Cost> costs;
    for (auto const client : inSol)
        costs.push_back(removeCost(&nodes[client], data, costEvaluator));

    // Sort clients in order of increasing removal costs.
    std::vector<size_t> range(inSol.size());
    std::iota(range.begin(), range.end(), 0);
    std::sort(range.begin(),
              range.end(),
              [&costs](auto idx1, auto idx2)
              { return costs[idx1] < costs[idx2]; });

    // Remove all but the last client, whose removal is the least valuable.
    for (auto idx = range.begin(); idx != range.end() - 1; ++idx)
    {
        auto const client = inSol[*idx];
        auto const &node = nodes[client];
        auto *route = node.route();

        route->remove(node.idx());
        update(route, route);
    }

    // Test swapping U and V, and do so if U is better to have than V.
    auto *V = &nodes[inSol[range.back()]];
    if (U != V && inplaceCost(U, V, data, costEvaluator) < 0)
    {
        auto *route = V->route();
        auto const idx = V->idx();
        route->remove(idx);
        route->insert(idx, U);
        update(route, route);
    }
}

void LocalSearch::insert(Route::Node *U,
                         CostEvaluator const &costEvaluator,
                         bool required)
{
    Route::Node *UAfter = routes[0][0];
    Cost bestCost = insertCost(U, UAfter, data, costEvaluator);

    for (auto const vClient : neighbours_[U->client()])
    {
        auto *V = &nodes[vClient];

        if (!V->route())
            continue;

        auto const cost = insertCost(U, V, data, costEvaluator);
        if (cost < bestCost)
        {
            bestCost = cost;
            UAfter = V;
        }
    }

    if (required || bestCost < 0)
    {
        UAfter->route()->insert(UAfter->idx() + 1, U);
        update(UAfter->route(), UAfter->route());
    }
}

bool LocalSearch::insertRequiredFeasible(
    Route::Node *U, CostEvaluator const &costEvaluator)
{
    Route::Node *bestAfter = nullptr;
    Cost bestCost = 0;

    // Required dynamic clients cannot be left at a penalised infeasible
    // position.  Screen every insertion position with the same cached route
    // prefix/suffix proposal used by regular local search, and materialise
    // only the cheapest hard-feasible one.
    for (auto &route : routes)
    {
        for (size_t idx = 0; idx + 1 < route.size(); ++idx)
        {
            auto *V = route[idx];
            if (!insertFeasible(U, V, data))
                continue;

            auto const cost = insertCost(U, V, data, costEvaluator);
            if (!bestAfter || cost < bestCost)
            {
                bestAfter = V;
                bestCost = cost;
            }
        }
    }

    if (!bestAfter)
        return false;

    bestAfter->route()->insert(bestAfter->idx() + 1, U);
    update(bestAfter->route(), bestAfter->route());
    return true;
}

void LocalSearch::update(Route *U, Route *V)
{
    numUpdates_++;
    searchCompleted_ = false;

    U->update();
    lastUpdated[U->idx()] = numUpdates_;

    for (auto *op : routeOps)  // this is used by some route operators
        op->update(U);         // to keep caches in sync.

    if (U != V)
    {
        V->update();
        lastUpdated[V->idx()] = numUpdates_;

        for (auto *op : routeOps)  // this is used by some route operators
            op->update(V);         // to keep caches in sync.
    }
}

void LocalSearch::loadSolution(Solution const &solution)
{
    std::fill(lastTestedNodes.begin(), lastTestedNodes.end(), -1);
    std::fill(lastTestedRoutes.begin(), lastTestedRoutes.end(), -1);
    std::fill(lastUpdated.begin(), lastUpdated.end(), 0);
    numUpdates_ = 0;

    // First empty all routes.
    for (auto &route : routes)
        route.clear();

    // Determine offsets for vehicle types.
    std::vector<size_t> vehicleOffset(data.numVehicleTypes(), 0);
    for (size_t vehType = 1; vehType < data.numVehicleTypes(); vehType++)
    {
        auto const prevAvail = data.vehicleType(vehType - 1).numAvailable;
        vehicleOffset[vehType] = vehicleOffset[vehType - 1] + prevAvail;
    }

    // Load routes from solution.
    for (auto const &solRoute : solution.routes())
    {
        // Determine index of next route of this type to load, where we rely
        // on solution to be valid to not exceed the number of vehicles per
        // vehicle type.
        auto const idx = vehicleOffset[solRoute.vehicleType()]++;
        auto &route = routes[idx];

        // Routes use a representation with nodes for each client, reload depot
        // (one per trip), and start/end depots. The start depot doubles as the
        // reload depot for the first trip.
        route.reserve(solRoute.size() + solRoute.numTrips() + 1);

        for (size_t tripIdx = 0; tripIdx != solRoute.numTrips(); ++tripIdx)
        {
            auto const &trip = solRoute.trip(tripIdx);

            if (tripIdx != 0)  // then we first insert a trip delimiter.
            {
                Route::Node depot = {trip.startDepot()};
                route.push_back(&depot);
            }

            for (auto const client : trip)
                route.push_back(&nodes[client]);
        }

        route.update();
    }

    for (auto *nodeOp : nodeOps)
        nodeOp->init(solution);

    for (auto *routeOp : routeOps)
        routeOp->init(solution);
}

Solution LocalSearch::exportSolution() const
{
    std::vector<setp_hgs_kernel::Route> solRoutes;
    solRoutes.reserve(data.numVehicles());

    std::vector<Trip> trips;
    std::vector<size_t> visits;

    for (auto const &route : routes)
    {
        if (route.empty())
            continue;

        trips.clear();
        trips.reserve(route.numTrips());

        visits.clear();
        visits.reserve(route.numClients());

        auto const *prevDepot = route[0];
        for (size_t idx = 1; idx != route.size(); ++idx)
        {
            auto const *node = route[idx];

            if (!node->isDepot())
            {
                visits.push_back(node->client());
                continue;
            }

            trips.emplace_back(data,
                               visits,
                               route.vehicleType(),
                               prevDepot->client(),
                               node->client());

            visits.clear();
            prevDepot = node;
        }

        assert(trips.size() == route.numTrips());
        solRoutes.emplace_back(data, trips, route.vehicleType());
    }

    return {data, solRoutes};
}

void LocalSearch::addNodeOperator(NodeOperator &op)
{
    nodeOps.emplace_back(&op);
    hasInitialEmptyRouteOperator
        = hasInitialEmptyRouteOperator || op.supportsInitialEmptyRouteMoves();
}

void LocalSearch::addRouteOperator(RouteOperator &op)
{
    routeOps.emplace_back(&op);
}

std::vector<NodeOperator *> const &LocalSearch::nodeOperators() const
{
    return nodeOps;
}

std::vector<RouteOperator *> const &LocalSearch::routeOperators() const
{
    return routeOps;
}

void LocalSearch::setNeighbours(Neighbours neighbours)
{
    if (neighbours.size() != data.numLocations())
        throw std::runtime_error("Neighbourhood dimensions do not match.");

    for (size_t client = data.numDepots(); client != data.numLocations();
         ++client)
    {
        auto const beginPos = neighbours[client].begin();
        auto const endPos = neighbours[client].end();

        auto const pred = [&](auto item)
        { return item == client || item < data.numDepots(); };

        if (std::any_of(beginPos, endPos, pred))
        {
            throw std::runtime_error("Neighbourhood of client "
                                     + std::to_string(client)
                                     + " contains itself or a depot.");
        }
    }

    neighbours_ = neighbours;
}

LocalSearch::Neighbours const &LocalSearch::neighbours() const
{
    return neighbours_;
}

LocalSearch::Statistics LocalSearch::statistics() const
{
    size_t numMoves = 0;
    size_t numImproving = 0;

    auto const count = [&](auto const *op)
    {
        auto const &stats = op->statistics();
        numMoves += stats.numEvaluations;
        numImproving += stats.numApplications;
    };

    std::for_each(nodeOps.begin(), nodeOps.end(), count);
    std::for_each(routeOps.begin(), routeOps.end(), count);

    assert(numImproving <= numUpdates_);
    return {numMoves, numImproving, numUpdates_};
}

LocalSearch::CandidateStatistics LocalSearch::candidateStatistics() const
{
    return candidateStatistics_;
}

LocalSearch::LocalSearch(ProblemData const &data, Neighbours neighbours)
    : data(data),
      neighbours_(data.numLocations()),
      orderNodes(data.numClients()),
      orderRoutes(data.numVehicles()),
      lastTestedNodes(data.numLocations()),
      lastTestedRoutes(data.numVehicles()),
      lastUpdated(data.numVehicles())
{
    setNeighbours(neighbours);

    std::iota(orderNodes.begin(), orderNodes.end(), data.numDepots());
    std::iota(orderRoutes.begin(), orderRoutes.end(), 0);

    size_t offset = 0;
    for (size_t vehType = 0; vehType != data.numVehicleTypes(); vehType++)
    {
        orderVehTypes.emplace_back(vehType, offset);
        offset += data.vehicleType(vehType).numAvailable;
    }

    nodes.reserve(data.numLocations());
    for (size_t loc = 0; loc != data.numLocations(); ++loc)
        nodes.emplace_back(loc);

    routes.reserve(data.numVehicles());
    size_t rIdx = 0;
    for (size_t vehType = 0; vehType != data.numVehicleTypes(); ++vehType)
    {
        auto const numAvailable = data.vehicleType(vehType).numAvailable;
        for (size_t vehicle = 0; vehicle != numAvailable; ++vehicle)
            routes.emplace_back(data, rIdx++, vehType);
    }
}
