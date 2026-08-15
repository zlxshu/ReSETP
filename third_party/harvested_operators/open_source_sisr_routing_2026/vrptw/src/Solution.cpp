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

void Route::updateRouteVariables(ProblemInstance &p, int pos_index)
{
    if (customers.empty())
    {
        return;
    }

    int customers_count = customers.size();

    int begin = 1;
    if (pos_index == 0 || pos_index == -1)
    {
        earliest_departures[0] = std::max(p.nodes[customers[0]].service_start, p.distance_matrix[p.depot_index][customers[0]]) + p.nodes[customers[0]].service_length;
        begin = 1;
    }
    else
    {
        begin = pos_index;
    }

    for (int j = begin; j < customers_count; ++j)
    {
        earliest_departures[j] = std::max(earliest_departures[j - 1] + p.distance_matrix[customers[j - 1]][customers[j]],
                                          p.nodes[customers[j]].service_start) +
                                 p.nodes[customers[j]].service_length;
    }

    begin = customers_count - 2;
    if (pos_index == customers_count - 1 || pos_index == -1)
    {   
        latest_arrivals[customers_count] = p.nodes[p.depot_index].service_end;
        latest_arrivals[customers_count - 1] = std::min(latest_arrivals[customers_count] - p.distance_matrix[customers[customers_count - 1]][p.depot_index] - p.nodes[customers[customers_count - 1]].service_length,
            p.nodes[customers[customers_count - 1]].service_end);

        begin = customers_count - 2;
    }
    else
    {
        begin = pos_index;
    }

    for (int j = begin; j >= 0; --j)
    {
        latest_arrivals[j] = std::min(latest_arrivals[j + 1] - p.distance_matrix[customers[j]][customers[j + 1]] - p.nodes[customers[j]].service_length,
                                      p.nodes[customers[j]].service_end);
    }
}

void Route::print(ProblemInstance &p, std::ostream &out)
{
    out << "cost: " << cost << " ruined: " << ruined << " demand: " << demand << std::endl;

    out << "customs: ";
    for (int customer : customers)
    {
        out << customer << ", ";
    }
    out << std::endl
        << "starts: ";
    for (int customer : customers)
    {
        out << p.nodes[customer].service_start << ", ";
    }
    out << std::endl
        << "ends: ";
    for (int customer : customers)
    {
        out << p.nodes[customer].service_end << ", ";
    }
    out << std::endl
        << "durations: ";
    for (int customer : customers)
    {
        out << p.nodes[customer].service_length << ", ";
    }
    out << std::endl
        << "distances: ";
    for (int i = 0; i < customers.size() - 1; ++i)
    {
        out << p.distance_matrix[customers[i]][customers[i + 1]] << " " << customers[i] << " " << customers[i + 1] << ", ";
    }
    out << std::endl
        << "earliest dep: ";
    for (int i = 0; i < customers.size(); ++i)
    {
        out << earliest_departures[i] << ", ";
    }
    out << std::endl
        << "latest arr: ";
    for (int i = 0; i < customers.size() + 1; ++i)
    {
        out << latest_arrivals[i] << ", ";
    }
    out << std::endl;
}

Solution::Solution(ProblemInstance &p)
    : total_cost(0.0f), routes_count(0), problem(p), customer_to_route(p.dimension, -1)
{
}

Solution::Solution(const Solution &other)
    : total_cost(other.total_cost),
      problem(other.problem),
      absent_customers(other.absent_customers),
      customer_to_route(other.customer_to_route),
      routes(other.routes),
      routes_count(other.routes_count)
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
    routes_count = other.routes_count;
    customer_to_route = other.customer_to_route;

    return *this;
}

void Solution::createRoute(int customer)
{
    routes.emplace_back();
    Route &new_route = routes.back();
    int new_route_index = routes.size() - 1;

    new_route.customers.push_back(customer);
    new_route.demand = problem.nodes[customer].demand;
    new_route.latest_arrivals.push_back(0);
    new_route.latest_arrivals.push_back(0);
    new_route.earliest_departures.push_back(0);
    new_route.cost = problem.distance_matrix[problem.depot_index][customer] + problem.distance_matrix[customer][problem.depot_index];
    new_route.updateRouteVariables(problem, -1);

    customer_to_route[customer] = new_route_index;
    routes_count += 1;

    total_cost += new_route.cost;
}

void Solution::insertIntoRoute(int route_index, int customer, int position, DistanceType insertion_cost)
{
    auto &route = routes[route_index];

    route.customers.insert(route.customers.begin() + position, customer);
    route.earliest_departures.insert(route.earliest_departures.begin() + position, 0);
    route.latest_arrivals.insert(route.latest_arrivals.begin() + position, 0);
    route.cost += insertion_cost;
    total_cost += insertion_cost;
    route.demand += problem.nodes[customer].demand;
    customer_to_route[customer] = route_index;
    route.updateRouteVariables(problem, position);
}

void Solution::removeFromRouteAll(int route_index)
{
    auto &route = routes[route_index];

    total_cost -= route.cost;
    --routes_count;

    for (int customer : route.customers)
    {
        absent_customers.push_back(customer);
        customer_to_route[customer] = -1;
    }
    route.customers.clear();
}

void Solution::removeFromRoute(int route_index, const std::vector<int> &removed_customers)
{
    if (removed_customers.empty())
    {
        return;
    }

    auto &route = routes[route_index];

    if (route.customers.size() == removed_customers.size())
    {
        removeFromRouteAll(route_index);
        return;
    }

    total_cost -= route.cost;

    for (int customer : removed_customers)
    {
        route.customers.erase(std::remove(route.customers.begin(), route.customers.end(), customer), route.customers.end());
        absent_customers.push_back(customer);
        customer_to_route[customer] = -1;
        route.demand -= problem.nodes[customer].demand;
    }
    route.earliest_departures.resize(route.customers.size());
    route.latest_arrivals.resize(route.customers.size() + 1);

    route.updateRouteCost(problem);

    route.updateRouteVariables(problem, -1);
    total_cost += route.cost;
}

void Solution::resetRoutes()
{
    // Reset ruined flag
    for (int i = 0; i < routes.size(); ++i)
    {
        routes[i].ruined = false;
    }

    if (routes.size() == routes_count)
    {
        // nothing clear
        return;
    }

    // Remove empty routes
    std::vector<Route> cleared_routes;

    for (const Route &route : routes)
    {
        // Skip empty routes
        if (route.customers.empty())
        {
            continue;
        }

        cleared_routes.push_back(route);

        // Update the mapping
        for (int customer : route.customers)
        {
            customer_to_route[customer] = cleared_routes.size() - 1;
        }
    }
    routes = cleared_routes;

    // Sanity check whether the number is correct
    if (routes.size() != routes_count)
    {
        throw std::runtime_error("Routes count corrupted");
    }

    // Recalculate all costs to avoid acumulation of distance floating point inaccuracy 
    // possibly caused by removing and inserting customers all over again
    total_cost = 0;
    for (Route &route : routes)
    {
        route.updateRouteCost(problem);
        total_cost += route.cost;
    }
}

void Solution::printSolution(std::ostream &out)
{
    out << "Solution uses " << routes.size() << " but actually non empty is " << routes_count
        << " routes, with total cost " << total_cost << std::endl;

    for (int j = 0; j < routes.size(); ++j)
    {
        out << "[" << j << "] ";
        Route &route = routes[j];
        if (route.customers.empty())
        {
            out << "This route is currently empty" << std::endl;
        }
        else
        {
            route.print(problem, out);
        }
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