#include "Sisrs.hpp"

Sisrs::Sisrs(ProblemInstance &p, const std::string &config, bool is_verbose) : problem(p), gen(std::random_device{}()), is_verbose(is_verbose)
{
    config_path = config;
    setupParametersFleet();
}

std::unique_ptr<Solution> Sisrs::createInitialSolution()
{
    auto initial_solution = std::make_unique<Solution>(problem);
    std::vector<int> route;

    for (int i = 0; i < problem.dimension; ++i)
    {
        // skip depot
        if (i == problem.depot_index)
        {
            continue;
        }
        initial_solution->createRoute(i);
    }
    return initial_solution;
}

void Sisrs::localSearch()
{
    // Create an initial solution
    sol_current = createInitialSolution();

    // Other solution objects to store results
    // Currently best known solution
    sol_best = std::make_unique<Solution>(*sol_current);
    // Neighbor - ruin&repair of the current solution
    sol_neighbor = std::make_unique<Solution>(*sol_current);

    improvements.push_back({{"Iteration", 0}, {"Vehicles", sol_current->routes_count}, {"Distance", sol_current->total_cost}, {"Sort", "none"}});

    int fleet_minimisation_steps = std::round(fleet_minimise_ratio * n_iter);

    if (fleet_minimisation_steps > 0)
    {
        minimiseFleet(fleet_minimisation_steps);
    }

    setupParametersDistance();

    minimiseDistance(n_iter - fleet_minimisation_steps);
}

int Sisrs::randomSubstringStart(int full_length, int output_length)
{
    int minStartIndex = 0;
    int maxStartIndex = full_length - output_length;

    std::uniform_int_distribution<> dist(minStartIndex, maxStartIndex);
    return dist(gen);
}

int Sisrs::randomSubstringStartIncluding(int full_length, int output_length, int must_include_index)
{
    int minStartIndex = std::max(0, must_include_index - output_length + 1);
    int maxStartIndex = std::min(full_length - output_length, must_include_index);

    std::uniform_int_distribution<> dist(minStartIndex, maxStartIndex);
    return dist(gen);
}

std::vector<int> Sisrs::randomSubstringIncluding(const std::vector<int> &input_string, int output_length, int must_include_index)
{
    int n = input_string.size();

    if (output_length > n || output_length <= 0)
    {
        std::cout << n << " " << output_length << " " << must_include_index << "\n";
        throw std::invalid_argument("Invalid output_length: ");
    }

    if (must_include_index < 0 || must_include_index >= n)
    {
        std::cout << n << " " << output_length << " " << must_include_index << "\n";
        throw std::invalid_argument("Invalid must_include_index");
    }

    int start_index = randomSubstringStartIncluding(n, output_length, must_include_index);

    std::vector<int> result(input_string.begin() + start_index, input_string.begin() + start_index + output_length);
    return result;
}

// Ruin method (Algorithm 2)
void Sisrs::ruin()
{
    // Equations 5,6,7
    float cardinality = std::min(static_cast<float>(max_cardinality),
                                 (problem.customer_count - sol_neighbor->absent_customers.size()) / static_cast<float>(sol_neighbor->routes.size()));

    float max_strings = (4.0f * average_removed) / (1.0f + cardinality);
    std::uniform_real_distribution<float> dist(1.0f, max_strings);

    // Added bound on the problem size to make sure the number is sane
    int strings_to_remove = std::min(static_cast<size_t>(std::floor(dist(gen))), sol_neighbor->routes.size());

    // Pick a random customer
    std::uniform_int_distribution<> dist_customer(0, problem.dimension - 1);
    int customer_seed = dist_customer(gen);
    while (sol_neighbor->customer_to_route[customer_seed] == -1)
    {
        customer_seed = dist_customer(gen);
    }

    // Routes that will be ruined
    int ruined_routes_count = 0;

    // Index of the next customer based on the adjacency matrix
    int adj_index = 0;

    // Line 5
    while (ruined_routes_count < strings_to_remove)
    {
        const int next_customer = problem.adjacency_matrix[customer_seed][adj_index];
        const int next_customers_route_index = sol_neighbor->customer_to_route[next_customer];
        ++adj_index;

        Route &route = sol_neighbor->routes[next_customers_route_index];

        // Line 6 conditions, skip absent customer, depot, or ruined path
        if (next_customers_route_index == -1 || route.ruined)
        {
            continue;
        }

        // Line 8 - Equations 8 and 9
        int route_total_length = route.customers.size();
        float remove_max_cardinality = std::min(static_cast<float>(route_total_length), cardinality);
        std::uniform_real_distribution<float> dist(0.0f, remove_max_cardinality);

        int to_remove_cardinality = std::floor(dist(gen)) + 1;

        // Line 9 - string/split string removal procedures
        const std::vector<int> customer_vector = route.customers;
        int customer_index = 0;
        while (next_customer != customer_vector[customer_index])
        {
            ++customer_index;
        }

        std::uniform_real_distribution dist_alpha(0.0f, 1.0f);

        std::vector<int> to_remove_customers;

        if (dist_alpha(gen) > alpha || to_remove_cardinality == 1 || route_total_length == to_remove_cardinality)
        {
            // 'string'

            to_remove_customers = randomSubstringIncluding(customer_vector, to_remove_cardinality, customer_index);
        }
        else
        {
            // 'split string'

            // Find m
            int m = 1;
            std::uniform_real_distribution<float> dist_beta(0.0f, 1.0f);
            while (m < route_total_length - to_remove_cardinality && dist_beta(gen) > beta)
            {
                ++m;
            }

            // Whole string (l + m) size
            int whole_size = to_remove_cardinality + m;
            std::vector<int> to_remove_whole = randomSubstringIncluding(customer_vector, whole_size, customer_index);

            // Which part (of size m) will be preserved
            int kept_start_index = randomSubstringStart(whole_size, m);

            // Fill the to-be-removed vector, skip m customers in the middle
            to_remove_customers.reserve(to_remove_cardinality);
            to_remove_customers.insert(to_remove_customers.end(), to_remove_whole.begin(), to_remove_whole.begin() + kept_start_index);
            to_remove_customers.insert(to_remove_customers.end(), to_remove_whole.begin() + kept_start_index + m, to_remove_whole.end());
        }

        // Remove the customers
        sol_neighbor->removeFromRoute(next_customers_route_index, to_remove_customers);
        // Line 10
        route.ruined = true;
        ++ruined_routes_count;
    }
}

// Recreate method (Algorithm 3)
bool Sisrs::recreate(DistanceType max_cost, int routes_cap, bool allow_absence)
{
    // --- Sort the absent customers

    // Pick the sorting algorithm
    std::discrete_distribution<> dist_sort(weights.begin(), weights.end());
    SortAlgorithm sort_algo = static_cast<SortAlgorithm>(dist_sort(gen));

    // Sort
    switch (sort_algo)
    {
    case RANDOM:
        last_sorting = "RANDOM";
        std::shuffle(sol_neighbor->absent_customers.begin(), sol_neighbor->absent_customers.end(), gen);
        break;

    case DEMAND:
        last_sorting = "DEMAND";
        std::sort(sol_neighbor->absent_customers.begin(), sol_neighbor->absent_customers.end(), [this](int a, int b)
                  { return problem.nodes[a].demand > problem.nodes[b].demand; });
        break;

    case FAR:
        last_sorting = "FAR";
        std::sort(sol_neighbor->absent_customers.begin(), sol_neighbor->absent_customers.end(), [this](int a, int b)
                  { return problem.distance_matrix[problem.depot_index][a] > problem.distance_matrix[problem.depot_index][b]; });
        break;

    case CLOSE:
        last_sorting = "CLOSE";
        std::sort(sol_neighbor->absent_customers.begin(), sol_neighbor->absent_customers.end(), [this](int a, int b)
                  { return problem.distance_matrix[problem.depot_index][a] < problem.distance_matrix[problem.depot_index][b]; });
        break;

    case TW_WIDTH:
        last_sorting = "TW_WIDTH";
        std::sort(sol_neighbor->absent_customers.begin(), sol_neighbor->absent_customers.end(), [this](int a, int b)
                  { return problem.nodes[a].service_end - problem.nodes[a].service_start < problem.nodes[b].service_end - problem.nodes[b].service_start; });
        break;

    case TW_START:
        last_sorting = "TW_START";
        std::sort(sol_neighbor->absent_customers.begin(), sol_neighbor->absent_customers.end(), [this](int a, int b)
                  { return problem.nodes[a].service_start < problem.nodes[b].service_start; });
        break;

    case TW_END:
        last_sorting = "TW_END";
        std::sort(sol_neighbor->absent_customers.begin(), sol_neighbor->absent_customers.end(), [this](int a, int b)
                  { return problem.nodes[a].service_end > problem.nodes[b].service_end; });
        break;
    }

    std::uniform_int_distribution<int> dist_blink(1, 100);

    std::vector<int> new_absent_customers;

    // Line 3 - iterate over all userved customers
    for (int customer : sol_neighbor->absent_customers)
    {
        // Route in which the best position was found
        int insert_best_route_index = -1;
        // Position inside route with lowest cost
        int insert_best_position;
        // Lowest cost increase
        // Bounding it by the solution improvement helps to skip some computations
        DistanceType insert_best_cost = max_cost - sol_neighbor->total_cost;
        if (routes_cap > sol_neighbor->routes_count)
        {
            insert_best_cost = 1e10;
        }
        Node customer_node = problem.nodes[customer];

        for (int i = 0; i < sol_neighbor->routes.size(); ++i)
        {
            const auto &route = sol_neighbor->routes[i];

            // Routes that customer fits into (Line 5)
            if (problem.capacity < route.demand + customer_node.demand ||
                route.customers.empty())
            {
                continue;
            }

            int route_size = route.customers.size();

            // Line 6
            // j stands for a place (index in the route), where the customer is being inserted
            // j = 0            means after the depot, before the first customer
            // j = route_size   means at the end of the route, behind the last customer
            // This means that customers on indices j - 1 an j are the customers' new neighbors
            for (int j = 0; j < route_size + 1; ++j)
            {
                int next_customer = (j < route_size) ? route.customers[j] : problem.depot_index;
                int prev_customer = (j > 0) ? route.customers[j - 1] : problem.depot_index;

                DistanceType distance_to_prev = problem.distance_matrix[prev_customer][customer];
                DistanceType distance_to_next = problem.distance_matrix[customer][next_customer];

                // Check TW feasibilities
                TimeType previous_service_start = 0;
                if (j != 0)
                {
                    previous_service_start = route.earliest_departures[j - 1];

                    // Get in time here, if it fails, inserting feasibly in later positions is impossible
                    if (route.earliest_departures[j - 1] + distance_to_prev > customer_node.service_end)
                    {
                        break;
                    }
                }
                
                // Get in time to the next customer or depot
                if (route.latest_arrivals[j] < std::max(customer_node.service_start, previous_service_start + distance_to_prev) + customer_node.service_length + distance_to_next)
                {
                    continue;
                }

                // Calculate the insertion cost increase
                DistanceType insert_here_cost = distance_to_prev + distance_to_next - problem.distance_matrix[prev_customer][next_customer];

                // Update the best found spot
                // Line 7 -- random blink moved here, for smaller gamma, this is faster
                if (insert_here_cost < insert_best_cost && (dist_blink(gen) > gamma * 100))
                {
                    insert_best_cost = insert_here_cost;
                    insert_best_position = j;
                    insert_best_route_index = i;
                }
            }
        }

        // No position was found in existing routes
        if (insert_best_route_index == -1)
        {
            if (routes_cap == sol_neighbor->routes_count)
            {
                if (allow_absence)
                {
                    new_absent_customers.push_back(customer);
                }
                else
                {
                    return false;
                }
            }
            // Create new route
            else
            {
                sol_neighbor->createRoute(customer);
            }
        }
        // Line 13
        else
        {
            sol_neighbor->insertIntoRoute(insert_best_route_index, customer, insert_best_position, insert_best_cost);
        }

        // Callback when the solution can't be beneficial anymore
        if (max_cost <= sol_neighbor->total_cost && routes_cap == sol_neighbor->routes_count)
        {
            return false;
        }
    }
    sol_neighbor->absent_customers = new_absent_customers;
    return true;
}

void Sisrs::minimiseDistance(int n_iterations)
{
    cooling = pow(t_f / t_0, 1.0 / n_iterations);

    std::uniform_real_distribution<float> dis(0.0f, 1.0f);

    // Small epsilon to avoid accepting rounding errors as improvements
    const double epsilon = 1e-5;

    int fleet_size_limit = sol_best->routes.size();

    double t_current = t_0;

    for (int i = 0; i < n_iterations; ++i)
    {
        if (is_verbose && i % 100000 == 0)
        {
            std::cout << "Distance minimization phase: Iteration " << i << "/" << n_iterations << "   Best solution no. vehicles & distance: " << sol_best->routes_count << " " << sol_best->total_cost << std::endl;
        }
        // Copy current solution to neighbor
        *sol_neighbor = *sol_current;

        // Apply ruin operator
        ruin();

        double t_coeffictinet = log(dis(gen));

        if (recreate(sol_current->total_cost - t_current * t_coeffictinet, fleet_size_limit, false))
        {
            // Assuming, that the fleet minimisation is the main objective,
            // a feasible solution with fewer routes should be picked
            if (fleet_minimise_ratio > 0 && sol_neighbor->routes_count < fleet_size_limit)
            {
                sol_neighbor->resetRoutes();
                *sol_current = *sol_neighbor;
                *sol_best = *sol_neighbor;
                fleet_size_limit = sol_best->routes_count;
                improvements.push_back({{"Iteration", n_iter - n_iterations + i + 1}, {"Vehicles", sol_best->routes_count}, {"Distance", sol_best->total_cost}, {"Sort", last_sorting}});
            }
            else if (sol_neighbor->total_cost < sol_current->total_cost - t_current * t_coeffictinet)
            // Accept if the neighbor's cost is within the range
            {
                sol_neighbor->resetRoutes();
                // Update the solution
                *sol_current = *sol_neighbor;

                // Update best solution
                if (sol_neighbor->total_cost + epsilon < sol_best->total_cost)
                {
                    *sol_best = *sol_neighbor;
                    improvements.push_back({{"Iteration", n_iter - n_iterations + i + 1}, {"Vehicles", sol_best->routes_count}, {"Distance", sol_best->total_cost}, {"Sort", last_sorting}});
                }
            }
        }

        // Cool down temperature for next iteration
        t_current *= cooling;
    }
}

void Sisrs::minimiseFleet(int n_iterations)
{
    std::vector<int> absence_counters(problem.dimension, 0);

    auto sumAbs = [&absence_counters](const std::vector<int> &customers)
    {
        int sum = 0;
        for (int customer : customers)
        {
            sum += absence_counters[customer];
        }
        return sum;
    };

    int fleet_size_limit = sol_best->routes.size();
    int current_absence_score = 0;

    for (int i = 0; i < n_iterations; ++i)
    {
        if (is_verbose && i % 100000 == 0)
        {
            std::cout << "Fleet minimization phase: Iteration " << i << "/" << n_iterations << "   Best solution no. vehicles & distance: " << sol_best->routes_count << " " << sol_best->total_cost << std::endl;
        }
        *sol_neighbor = *sol_current;

        ruin();
        recreate(1000000000, fleet_size_limit, true);

        // New best solution is found
        if (sol_neighbor->absent_customers.size() == 0)
        {
            sol_neighbor->resetRoutes();
            *sol_best = *sol_neighbor;

            // Line 11 - Find and remove tour with the lowest sumAbs
            int lowest_absence_route_index = 0;
            int lowest_absence_route_score = sumAbs(sol_neighbor->routes[0].customers);
            for (int j = 1; j < sol_neighbor->routes.size(); ++j)
            {
                int score = sumAbs(sol_neighbor->routes[j].customers);
                if (score < lowest_absence_route_score)
                {
                    lowest_absence_route_score = score;
                    lowest_absence_route_index = j;
                }
            }
            sol_neighbor->removeFromRouteAll(lowest_absence_route_index);
            sol_neighbor->resetRoutes();
            *sol_current = *sol_neighbor;
            fleet_size_limit = sol_current->routes_count;

            improvements.push_back({{"Iteration", i + 1}, {"Vehicles", sol_best->routes_count}, {"Distance", sol_best->total_cost}, {"Sort", last_sorting}});
        }
        else
        {
            int neighbor_absence_score = sumAbs(sol_neighbor->absent_customers);
            // New improving solution is found
            if (sol_neighbor->absent_customers.size() < sol_current->absent_customers.size() || neighbor_absence_score < current_absence_score)
            {
                sol_neighbor->resetRoutes();
                *sol_current = *sol_neighbor;
            }
        }

        // Increase the absence table
        for (int j : sol_neighbor->absent_customers)
        {
            ++absence_counters[j];
        }
        current_absence_score = sumAbs(sol_current->absent_customers);
    }
    *sol_current = *sol_best;
}

void Sisrs::setupParametersFleet()
{
    std::ifstream config_file(config_path);

    if (!config_file.is_open())
    {
        std::cout << "Could not open config file, using default parameters." << config_path << std::endl;
        return;
    }

    nlohmann::json config;
    config_file >> config;

    int iterations = config.value("iterations", 125000);
    bool scaled_iters = config.value("iterations_scaled", false);
    if (scaled_iters)
    {
        iterations *= problem.customer_count;
    }

    n_iter = iterations;
    fleet_minimise_ratio = config.value("fleet_minimise_ratio", fleet_minimise_ratio);
    t_0 = config.value("initial_temperature", t_0);
    t_f = config.value("final_temperature", t_f);
    weights = config.value("weights", weights);
    max_cardinality = config.value("max_cardinality", max_cardinality);
    average_removed = config.value("average_removed", average_removed);
    alpha = config.value("split_procedure_choice_probability", alpha);
    beta = config.value("split_string_removal_parameter", beta);
    gamma = config.value("recreate_blink_rate", gamma);

    // Ensure compability if config json contains different names
    max_cardinality = config.value("max_cardinality_fleet", max_cardinality);
    average_removed = config.value("average_removed_fleet", average_removed);
    gamma = config.value("recreate_blink_rate_fleet", gamma);
}

void Sisrs::setupParametersDistance()
{
    std::ifstream config_file(config_path);

    if (!config_file.is_open())
    {
        std::cout << "Could not open config file, using default parameters." << config_path << std::endl;
        return;
    }

    nlohmann::json config;
    config_file >> config;

    max_cardinality = config.value("max_cardinality_distance", max_cardinality);
    average_removed = config.value("average_removed_distance", average_removed);
    gamma = config.value("recreate_blink_rate_distance", gamma);
}

bool Sisrs::saveJson(const std::string &path, float duration)
{
    nlohmann::json output_json;
    output_json["Routes"] = nlohmann::json::array();

    for (int i = 0; i < sol_best->routes.size(); ++i)
    {
        const Route &route = sol_best->routes[i];
        // {}Vehicle
        nlohmann::json vehicle = {
            {"Id", i},
            {"StartLocation", problem.depot_index},
            {"EndLocation", problem.depot_index}
        };

        // Route
        nlohmann::json route_out = {
            {"Vehicle", vehicle},
            {"Stops", nlohmann::json::array()},
            {"Distance", route.cost}
        };
        // []Stops
        int route_length = route.customers.size();
        for (int j = -1; j <= route_length; ++j)
        {
            nlohmann::json stop = {
                {"Location", nullptr},
            };

            // Dummy - initial depot visit
            if (j == -1)
            {
                stop["Location"] = problem.depot_index;
            }
            else if (j == route_length)
            {
                stop["Location"] = problem.depot_index;
            }
            else
            {
                stop["Location"] = problem.nodes[route.customers[j]].id;
            }
            route_out["Stops"].push_back(stop);
        }
        output_json["Routes"].push_back(route_out);
    }

    output_json["SolutionStats"] = {
        {"NumberOfVehicles", sol_best->routes.size()},
        {"TotalCoveredDistance", sol_best->total_cost},
        {"ComputationTime", duration},
        {"Improvements", nlohmann::json::array()},
    };

    output_json["SolutionStats"]["Improvements"] = improvements;
    output_json["AlgorithmStats"] = logParameters();

    std::ofstream file(path);

    if (file.is_open())
    {
        file << output_json.dump(4);
        file.close();
        return true;
    }
    return false;
}


nlohmann::json Sisrs::logParameters()
{
    nlohmann::json algorithm_stats;
    // SA
    algorithm_stats["StartingTemperature"] = t_0;
    algorithm_stats["FinalTemperature"] = t_f;
    algorithm_stats["TotalIterations"] = n_iter;
    algorithm_stats["FleetMinimisationShare"] = fleet_minimise_ratio;

    // SISRs
    algorithm_stats["MaxCardinality"] = max_cardinality;
    algorithm_stats["AverageRemoved"] = average_removed;
    algorithm_stats["Alpha"] = alpha;
    algorithm_stats["Beta"] = beta;
    algorithm_stats["Gamma"] = gamma;

    algorithm_stats["Sortings"] = nlohmann::json::array();

    // Recreate orderings
    algorithm_stats["Sortings"].push_back({"RANDOM", weights[0]});
    algorithm_stats["Sortings"].push_back({"DEMAND", weights[1]});
    algorithm_stats["Sortings"].push_back({"FAR", weights[2]});
    algorithm_stats["Sortings"].push_back({"CLOSE", weights[3]});
    algorithm_stats["Sortings"].push_back({"TW_WIDTH", weights[4]});
    algorithm_stats["Sortings"].push_back({"TW_START", weights[5]});
    algorithm_stats["Sortings"].push_back({"TW_END", weights[6]});

    return algorithm_stats;
}
