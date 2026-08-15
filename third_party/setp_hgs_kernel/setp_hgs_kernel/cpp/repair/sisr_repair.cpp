#include "sisr_repair.h"

#include "repair.h"
#include "search/primitives.h"
#include "Solution.h"

#include <algorithm>
#include <cassert>
#include <limits>
#include <stdexcept>
#include <tuple>

using SearchRoute = setp_hgs_kernel::search::Route;
using SolRoute = setp_hgs_kernel::Route;

using setp_hgs_kernel::search::insertCost;
using setp_hgs_kernel::search::insertFeasible;

setp_hgs_kernel::repair::SISRRepairResult
setp_hgs_kernel::repair::sisrRepair(
    std::vector<SolRoute> const &solRoutes,
    std::vector<size_t> const &unplanned,
    ProblemData const &data,
    CostEvaluator const &costEvaluator,
    RandomNumberGenerator &rng,
    double blinkProbability)
{
    if (blinkProbability < 0 || blinkProbability >= 1)
        throw std::invalid_argument("Blink probability must be in [0, 1).");

    std::vector<SearchRoute::Node> locs;
    std::vector<SearchRoute> routes;
    routes.reserve(data.numVehicles());
    setupRoutes(locs, routes, solRoutes, data);

    std::vector<size_t> used(data.numVehicleTypes(), 0);
    for (auto const &route : routes)
        used[route.vehicleType()]++;

    SISRRepairResult result = {{}, {}, 0, 0, 0, true};
    result.selectedInsertions.reserve(unplanned.size());

    for (auto const client : unplanned)
    {
        auto *U = &locs[client];
        assert(!U->route());

        SearchRoute *bestRoute = nullptr;
        size_t bestPosition = 0;
        auto bestCost = std::numeric_limits<Cost>::max();

        for (auto &route : routes)
        {
            for (size_t position = 0; position <= route.numClients(); ++position)
            {
                result.positionsEvaluated++;
                auto *V = route[position];
                if (!insertFeasible(U, V, data))
                    continue;

                auto const deltaCost = insertCost(U, V, data, costEvaluator);
                if (deltaCost >= bestCost)
                    continue;

                if (rng.rand() < blinkProbability)
                {
                    result.positionsBlinked++;
                    continue;
                }

                bestRoute = &route;
                bestPosition = position;
                bestCost = deltaCost;
            }
        }

        if (bestRoute)
        {
            auto const routeIndex = bestRoute->idx();
            bestRoute->insert(bestPosition + 1, U);
            bestRoute->update();
            result.selectedInsertions.push_back(
                {client, routeIndex, bestPosition, bestCost});
            continue;
        }

        auto singletonCost = std::numeric_limits<Cost>::max();
        size_t singletonVehicleType = data.numVehicleTypes();
        for (size_t vehicleType = 0; vehicleType != data.numVehicleTypes();
             ++vehicleType)
        {
            auto const &specification = data.vehicleType(vehicleType);
            if (used[vehicleType] >= specification.numAvailable)
                continue;

            SolRoute singleton(data, {client}, vehicleType);
            if (!singleton.isFeasible())
                continue;

            Solution singletonSolution(data, {singleton});
            auto const cost = costEvaluator.penalisedCost(singletonSolution);
            if (std::tie(cost, vehicleType)
                < std::tie(singletonCost, singletonVehicleType))
            {
                singletonCost = cost;
                singletonVehicleType = vehicleType;
            }
        }

        if (singletonVehicleType == data.numVehicleTypes())
        {
            result.reconstructed = false;
            return result;
        }

        auto &route = routes.emplace_back(
            data, routes.size(), singletonVehicleType);
        route.insert(1, U);
        route.update();
        used[singletonVehicleType]++;
        result.newRoutesCreated++;
        result.selectedInsertions.push_back(
            {client, route.idx(), 0, singletonCost});
    }

    result.routes = exportRoutes(data, routes);
    return result;
}
