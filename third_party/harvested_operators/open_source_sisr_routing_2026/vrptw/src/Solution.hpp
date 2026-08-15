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

    // Value of latest possible arrival, while still mantaining feasibility
    // Calculated in advance as a push-forward global variable for each customer
    std::vector<TimeType> latest_arrivals;

    // Value of earliest possible departure, while still mantaining feasibility
    // Calculated in advance as a push-forward global variable for each customer
    std::vector<TimeType> earliest_departures;

    // Total cost of the route
    DistanceType cost;

    // Total demand of the route
    int demand;

    // Flag whether route was changed during an iteration step
    bool ruined;

    // Recalculate cost of the whole route
    void updateRouteCost(ProblemInstance &p);

    // Recalculate the push-forward variables of TW constraint
    void updateRouteVariables(ProblemInstance &p, int pos_index);

    // Basic command line print
    void print(ProblemInstance &p, std::ostream &out = std::cout);
};

// Class containing a solution to a VRPTW Problem, i.e. routes and unserved customers are stored
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

    // How many vehicles (non-empty routes) are actually used by the solution.
    // Usually should be used instead of routes.Size()
    int routes_count;

    // Mapping from a customer to their route
    std::vector<int> customer_to_route;

    // Some of the customers might not be served, solution is feasible if this is empty
    std::vector<int> absent_customers;
    // Adds a new route into the solution
    void createRoute(int customer);

    // Inserts a customer into an existing route
    void insertIntoRoute(int route_index, int customer, int position, DistanceType insertion_cost);

    // Removes whole route
    void removeFromRouteAll(int route_index);

    // Removes a customer from an existing route
    void removeFromRoute(int route_index, const std::vector<int> &removed_customers);

    // Remove empty routes from solution and reset "ruined" flag
    void resetRoutes();

    // Basic command line print
    void printSolution(std::ostream &out = std::cout);
};