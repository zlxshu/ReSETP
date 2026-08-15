#pragma once

#include <stdexcept>

#include "ProblemInstance.hpp"

// Class representing a single route (tour) of a solution
// Contains sequence of customers and additional statistics (cost, demand)
class Route
{
public:
    Route();

    // Served customers in order
    std::vector<int> customers;

    // Total cost of the route
    DistanceType cost;

    // Total demand of the route
    float demand;

    // Flag whether route was changed during an iteration step
    bool ruined;

    // Recalculate cost of the whole route
    void updateRouteCost(ProblemInstance &p);
};

// Class containing a solution to a CVRP Problem, i.e. routes and unserved customers are stored
class Solution
{
public:
    // Basic constructor, requires a valid problem instance
    Solution(ProblemInstance &p);

    // Deep copy
    Solution(const Solution &other);

    // Copy assignment
    Solution &operator=(const Solution &other);

    // Solution cost - sum of costs of all routes
    DistanceType total_cost;

    // Problem instance which is solved by this solution
    ProblemInstance &problem;

    // Set of vehicle routes in the solution
    std::vector<Route> routes;

    // Mapping from a customer to their route
    std::vector<int> customer_to_route;

    // Some of the customers might not be served, solution is feasible if this is empty
    std::vector<int> absent_customers;
    // Adds a new route into the solution
    void createRoute(int customer);

    // Inserts a customer into an existing route
    void insertIntoRoute(int route_index, int customer, int position, DistanceType insertion_cost);

    // Removes a customer from an existing route
    void removeFromRoute(int route_index, const std::vector<int> &removed_customers);

    // Remove empty routes from solution and reset "ruined" flag
    void resetRoutes();

    // Basic command line print
    void printSolution(std::ostream &out = std::cout);
};