#include "Solution.hpp"
#include "ProblemInstance.hpp"

Route::Route()
    : cost(0), demand(0), ruined(false)
{
}

void Route::updateRouteCost(ProblemInstance &p)
{
    cost = 0;
    if (customers.empty())
    {
        return;
    }

    // Distances from the depot to the first and last served customers
    cost += p.distance_matrix[p.depot_index][customers.front()];
    cost += p.distance_matrix[customers.back()][p.depot_index];

    // Distances between the running customers
    for (int j = 0; j < customers.size() - 1; ++j)
    {
        cost += p.distance_matrix[customers[j]][customers[j + 1]];
    }
}

Solution::Solution(ProblemInstance &p)
    : total_cost(0.0f), problem(p), customer_to_route(p.dimension, -1)
{
}

Solution::Solution(const Solution &other)
    : total_cost(other.total_cost),
      problem(other.problem),
      absent_customers(other.absent_customers),
      customer_to_route(other.customer_to_route),
      routes(other.routes)
{
}

Solution &Solution::operator=(const Solution &other)
{
    if (this == &other)
        return *this;

    total_cost = other.total_cost;
    problem = other.problem;
    absent_customers = other.absent_customers;
    routes = other.routes;
    customer_to_route = other.customer_to_route;

    return *this;
}

void Solution::createRoute(int customer)
{
    routes.emplace_back();
    Route &new_route = routes.back();
    int new_route_index = routes.size() - 1;

    new_route.customers.push_back(customer);
    customer_to_route[customer] = new_route_index;
    new_route.demand = problem.nodes[customer].demand;
    new_route.cost = problem.distance_matrix[problem.depot_index][customer] + problem.distance_matrix[customer][problem.depot_index];

    total_cost += new_route.cost;
}

void Solution::insertIntoRoute(int route_index, int customer, int position, DistanceType insertion_cost)
{
    auto &route = routes[route_index];

    route.customers.insert(route.customers.begin() + position, customer);
    route.cost += insertion_cost;
    total_cost += insertion_cost;
    route.demand += problem.nodes[customer].demand;
    customer_to_route[customer] = route_index;
}

void Solution::removeFromRoute(int route_index, const std::vector<int> &removed_customers)
{
    if (removed_customers.empty())
    {
        return;
    }

    auto &route = routes[route_index];
    total_cost -= route.cost;

    for (int customer : removed_customers)
    {
        route.customers.erase(std::remove(route.customers.begin(), route.customers.end(), customer), route.customers.end());
        absent_customers.push_back(customer);
        customer_to_route[customer] = -1;
        route.demand -= problem.nodes[customer].demand;
    }

    route.updateRouteCost(problem);

    total_cost += route.cost;
}

void Solution::resetRoutes()
{
    std::vector<Route> cleared_routes;

    for (const Route &route : routes)
    {
        // Skip empty routes
        if (route.customers.empty())
        {
            continue;
        }

        cleared_routes.push_back(route);

        // Reset ruined flag
        cleared_routes[cleared_routes.size() - 1].ruined = false;

        // Update the mapping
        for (int customer : route.customers)
        {
            customer_to_route[customer] = cleared_routes.size() - 1;
        }
    }
    routes = cleared_routes;
}

void Solution::printSolution(std::ostream &out)
{
    out << "Solution uses " << routes.size()
        << " routes, with total cost " << total_cost << std::endl;

    int i = 0;
    for (int j = 0; j < routes.size(); ++j)
    {
        out << "[" << i << "] ";
        out << "cost: " << routes[j].cost << " ruined: " << routes[j].ruined << " demand: " << routes[j].demand << " customers: ";

        for (int customer : routes[j].customers)
        {
            out << customer << ", ";
        }
        out << std::endl;
        i++;
    }
    out << "Absent customers: ";
    if (absent_customers.size() == 0)
    {
        out << "none";
    }
    for (int i = 0; i < absent_customers.size(); ++i)
    {
        out << absent_customers[i] << ", ";
    }
    out << " customer_to_route mapping: \n";
    for (int i = 0; i < customer_to_route.size(); ++i)
    {
        out << i << " - " << customer_to_route[i] << ", ";
    }
    out << std::endl
        << std::endl;
}