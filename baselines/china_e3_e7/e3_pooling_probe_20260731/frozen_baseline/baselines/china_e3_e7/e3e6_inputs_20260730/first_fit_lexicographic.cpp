#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <random>
#include <stdexcept>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

namespace {

constexpr double kTolerance = 1.0e-9;

struct Depot {
    int cap{};
    double ready{};
    double due{};
    double service{};
};

struct Option {
    int absolute_rank{};
    int depot{};
};

struct Customer {
    std::string id;
    double demand{};
    double ready{};
    double due{};
    double service{};
    int original_depot{};
    int selected_position{-1};
    std::vector<Option> options;
};

struct RouteState {
    std::vector<int> customers;
    double load{};
    double depart{};
    int last_node{};
};

struct SearchState {
    std::vector<std::vector<RouteState>> routes;
    std::vector<double> assigned_demand;
};

struct Stats {
    std::uint64_t prefix_oracle_calls{};
    std::uint64_t infeasible_prefix_attempts{};
    std::uint64_t nodes_visited{};
    std::uint64_t route_feasibility_checker_calls{};
    std::uint64_t d2a_cap_prunes{};
    std::uint64_t conflict_backjumps{};
    std::uint64_t heuristic_checker_calls{};
    std::uint64_t demand_hall_prunes{};
    std::uint64_t pairwise_clique_prunes{};
};

using Conflict = std::vector<std::uint64_t>;

struct Problem {
    int depot_count{};
    int customer_count{};
    int selected_count{};
    double payload_capacity{};
    std::uint64_t random_seed{};
    std::vector<Depot> depots;
    std::vector<Customer> customers;
    std::vector<int> selected_customer;
    std::vector<double> travel;

    [[nodiscard]] double travel_time(int from_node, int to_node) const {
        const int total = depot_count + customer_count;
        return travel[static_cast<std::size_t>(from_node) * total + to_node];
    }
};

Conflict empty_conflict(int selected_count) {
    return Conflict(static_cast<std::size_t>((selected_count + 63) / 64), 0);
}

Conflict all_conflict(int selected_count) {
    Conflict result = empty_conflict(selected_count);
    for (int index = 0; index < selected_count; ++index) {
        result[static_cast<std::size_t>(index / 64)] |=
            std::uint64_t{1} << (index % 64);
    }
    return result;
}

void set_conflict(Conflict& conflict, int index) {
    conflict[static_cast<std::size_t>(index / 64)] |=
        std::uint64_t{1} << (index % 64);
}

void clear_conflict(Conflict& conflict, int index) {
    conflict[static_cast<std::size_t>(index / 64)] &=
        ~(std::uint64_t{1} << (index % 64));
}

bool contains_conflict(const Conflict& conflict, int index) {
    return (
        conflict[static_cast<std::size_t>(index / 64)]
        & (std::uint64_t{1} << (index % 64))
    ) != 0;
}

void merge_conflict(Conflict& target, const Conflict& source) {
    for (std::size_t index = 0; index < target.size(); ++index) {
        target[index] |= source[index];
    }
}

class Solver {
public:
    explicit Solver(Problem problem)
        : problem_(std::move(problem)),
          selected_customer_position_(
              static_cast<std::size_t>(problem_.selected_count), -1
          ) {
        for (int customer_index = 0;
             customer_index < problem_.customer_count;
             ++customer_index) {
            const int selected =
                problem_.customers[customer_index].selected_position;
            if (selected >= 0) {
                selected_customer_position_[selected] = customer_index;
            }
        }
        build_pairwise_incompatibility();
    }

    bool solve(
        std::vector<int>& chosen_options,
        std::vector<std::vector<std::vector<int>>>& route_groups
    ) {
        std::vector<int> prefix;
        std::vector<int> incumbent;
        if (!solve_prefix(prefix, nullptr, incumbent, route_groups)) {
            return false;
        }

        for (int selected = 0; selected < problem_.selected_count; ++selected) {
            const Customer& customer =
                problem_.customers[selected_customer_position_[selected]];
            bool accepted = false;
            for (int option_index = 0;
                 option_index < static_cast<int>(customer.options.size());
                 ++option_index) {
                std::vector<int> candidate_prefix = prefix;
                candidate_prefix.push_back(option_index);
                if (
                    static_cast<int>(incumbent.size())
                        >= static_cast<int>(candidate_prefix.size())
                    && std::equal(
                        candidate_prefix.begin(),
                        candidate_prefix.end(),
                        incumbent.begin()
                    )
                ) {
                    prefix.push_back(option_index);
                    accepted = true;
                    break;
                }
                std::vector<int> witness;
                std::vector<std::vector<std::vector<int>>> witness_routes;
                if (solve_prefix(
                        candidate_prefix,
                        &incumbent,
                        witness,
                        witness_routes
                    )) {
                    prefix.push_back(option_index);
                    incumbent = std::move(witness);
                    route_groups = std::move(witness_routes);
                    accepted = true;
                    break;
                }
            }
            if (!accepted) {
                throw std::runtime_error(
                    "lexicographic prefix fixing failed"
                );
            }
        }
        chosen_options = std::move(prefix);
        return true;
    }

    [[nodiscard]] const Stats& stats() const {
        return stats_;
    }

private:
    struct Branch {
        double route_utilization{};
        double demand_utilization{};
        int absolute_rank{};
        int destination{};
        int option_index{};
        bool feasible{};
        SearchState state;
    };

    struct SearchBranch {
        double route_utilization{};
        double demand_utilization{};
        int absolute_rank{};
        int destination{};
        int option_index{};
        bool feasible{};
        std::vector<RouteState> routes;
        double assigned_demand{};
    };

    Problem problem_;
    Stats stats_;
    std::vector<int> selected_customer_position_;
    std::vector<int> active_prefix_;
    std::vector<std::vector<double>> suffix_mandatory_;
    std::vector<double> subset_capacity_;
    std::vector<int> found_options_;
    std::vector<std::vector<std::vector<int>>> found_routes_;
    bool triangle_inequality_verified_{true};
    std::vector<std::vector<std::vector<unsigned char>>>
        pairwise_incompatible_;
    std::vector<std::vector<int>> pairwise_degree_;

    void build_pairwise_incompatibility() {
        const int total = problem_.depot_count + problem_.customer_count;
        for (int left = 0; left < total; ++left) {
            for (int middle = 0; middle < total; ++middle) {
                for (int right = 0; right < total; ++right) {
                    if (
                        problem_.travel_time(left, right)
                        > problem_.travel_time(left, middle)
                            + problem_.travel_time(middle, right)
                            + 1.0e-7
                    ) {
                        triangle_inequality_verified_ = false;
                    }
                }
            }
        }
        pairwise_incompatible_.assign(
            static_cast<std::size_t>(problem_.depot_count),
            std::vector<std::vector<unsigned char>>(
                static_cast<std::size_t>(problem_.customer_count),
                std::vector<unsigned char>(
                    static_cast<std::size_t>(problem_.customer_count),
                    0
                )
            )
        );
        for (int depot = 0; depot < problem_.depot_count; ++depot) {
            const Depot& depot_node = problem_.depots[depot];
            for (int left = 0;
                 left < problem_.customer_count;
                 ++left) {
                for (int right = left + 1;
                     right < problem_.customer_count;
                     ++right) {
                    bool incompatible =
                        problem_.customers[left].demand
                            + problem_.customers[right].demand
                        > problem_.payload_capacity + kTolerance;
                    if (!incompatible && triangle_inequality_verified_) {
                        RouteState empty;
                        empty.load = 0.0;
                        empty.depart =
                            depot_node.ready + depot_node.service;
                        empty.last_node = depot;
                        RouteState first;
                        RouteState second;
                        incompatible =
                            !route_append_feasible(
                                depot,
                                empty,
                                left,
                                first,
                                false,
                                false
                            )
                            || !route_append_feasible(
                                depot,
                                first,
                                right,
                                second,
                                false,
                                false
                            );
                    }
                    pairwise_incompatible_[depot][left][right] =
                        incompatible ? 1 : 0;
                    pairwise_incompatible_[depot][right][left] =
                        incompatible ? 1 : 0;
                }
            }
        }
        pairwise_degree_.assign(
            static_cast<std::size_t>(problem_.depot_count),
            std::vector<int>(
                static_cast<std::size_t>(problem_.customer_count),
                0
            )
        );
        for (int depot = 0; depot < problem_.depot_count; ++depot) {
            for (int customer = 0;
                 customer < problem_.customer_count;
                 ++customer) {
                pairwise_degree_[depot][customer] = std::count(
                    pairwise_incompatible_[depot][customer].begin(),
                    pairwise_incompatible_[depot][customer].end(),
                    static_cast<unsigned char>(1)
                );
            }
        }
    }

    bool greedy_clique_exists(
        int depot,
        std::vector<int> candidates,
        int needed
    ) const {
        if (needed <= 0) {
            return true;
        }
        if (static_cast<int>(candidates.size()) < needed) {
            return false;
        }
        std::stable_sort(
            candidates.begin(),
            candidates.end(),
            [this, depot](int left, int right) {
                return pairwise_degree_[depot][left]
                    > pairwise_degree_[depot][right];
            }
        );
        for (int start = 0;
             start < static_cast<int>(candidates.size());
             ++start) {
            std::vector<int> clique{candidates[start]};
            for (int offset = 1;
                 offset < static_cast<int>(candidates.size());
                 ++offset) {
                const int index =
                    (start + offset)
                    % static_cast<int>(candidates.size());
                const int candidate = candidates[index];
                const bool fits_clique = std::all_of(
                    clique.begin(),
                    clique.end(),
                    [this, depot, candidate](int member) {
                        return pairwise_incompatible_[
                            depot
                        ][member][candidate] != 0;
                    }
                );
                if (fits_clique) {
                    clique.push_back(candidate);
                    if (static_cast<int>(clique.size()) >= needed) {
                        return true;
                    }
                }
            }
        }
        return false;
    }

    bool mandatory_clique_feasible(
        int customer_index,
        const SearchState& state,
        const std::vector<int>& chosen
    ) {
        for (int depot = 0; depot < problem_.depot_count; ++depot) {
            if (
                *std::max_element(
                    pairwise_degree_[depot].begin(),
                    pairwise_degree_[depot].end()
                ) == 0
            ) {
                continue;
            }
            std::vector<int> mandatory;
            std::vector<int> future_needing_new_route;
            for (int index = 0;
                 index < problem_.customer_count;
                 ++index) {
                const Customer& customer = problem_.customers[index];
                int destination = -1;
                if (index < customer_index) {
                    destination =
                        customer.selected_position < 0
                        ? customer.original_depot
                        : customer.options[
                            chosen[customer.selected_position]
                        ].depot;
                } else if (customer.selected_position < 0) {
                    destination = customer.original_depot;
                } else if (
                    customer.selected_position
                    < static_cast<int>(active_prefix_.size())
                ) {
                    destination = customer.options[
                        active_prefix_[customer.selected_position]
                    ].depot;
                }
                if (destination == depot) {
                    mandatory.push_back(index);
                    if (
                        triangle_inequality_verified_
                        && index >= customer_index
                    ) {
                        const bool can_use_current_route = std::any_of(
                            state.routes[depot].begin(),
                            state.routes[depot].end(),
                            [this, depot, index](const RouteState& route) {
                                RouteState updated;
                                return route_append_feasible(
                                    depot,
                                    route,
                                    index,
                                    updated,
                                    false,
                                    false
                                );
                            }
                        );
                        if (!can_use_current_route) {
                            future_needing_new_route.push_back(index);
                        }
                    }
                }
            }
            if (
                greedy_clique_exists(
                    depot,
                    mandatory,
                    problem_.depots[depot].cap + 1
                )
                || greedy_clique_exists(
                    depot,
                    future_needing_new_route,
                    problem_.depots[depot].cap
                        - static_cast<int>(state.routes[depot].size())
                        + 1
                )
            ) {
                ++stats_.pairwise_clique_prunes;
                return false;
            }
        }
        return true;
    }

    [[nodiscard]] SearchState empty_state() const {
        SearchState state;
        state.routes.resize(static_cast<std::size_t>(problem_.depot_count));
        state.assigned_demand.assign(
            static_cast<std::size_t>(problem_.depot_count), 0.0
        );
        return state;
    }

    bool route_append_feasible(
        int depot_index,
        const RouteState& route,
        int customer_index,
        RouteState& updated,
        bool count_check,
        bool record_customer
    ) {
        if (count_check) {
            ++stats_.route_feasibility_checker_calls;
        }
        const Depot& depot = problem_.depots[depot_index];
        const Customer& customer = problem_.customers[customer_index];
        const double load = route.load + customer.demand;
        if (load > problem_.payload_capacity) {
            return false;
        }
        const int customer_node = problem_.depot_count + customer_index;
        const double arrive =
            route.depart
            + problem_.travel_time(route.last_node, customer_node);
        const double start = std::max(arrive, customer.ready);
        if (start > customer.due + kTolerance) {
            return false;
        }
        const double depart = start + customer.service;
        const double return_arrive =
            depart + problem_.travel_time(customer_node, depot_index);
        const double return_start = std::max(return_arrive, depot.ready);
        if (return_start > depot.due + kTolerance) {
            return false;
        }
        updated = route;
        if (record_customer) {
            updated.customers.push_back(customer_index);
        }
        updated.load = load;
        updated.depart = depart;
        updated.last_node = customer_node;
        return true;
    }

    bool add_customer_to_depot(
        std::vector<RouteState>& routes,
        double& assigned_demand,
        int depot_index,
        int customer_index,
        bool count_check,
        bool record_customer
    ) {
        for (std::size_t route_index = 0;
             route_index < routes.size();
             ++route_index) {
            RouteState updated;
            if (route_append_feasible(
                    depot_index,
                    routes[route_index],
                    customer_index,
                    updated,
                    count_check,
                    record_customer
                )) {
                routes[route_index] = std::move(updated);
                assigned_demand +=
                    problem_.customers[customer_index].demand;
                return true;
            }
        }

        const Depot& depot = problem_.depots[depot_index];
        RouteState empty;
        empty.load = 0.0;
        empty.depart = depot.ready + depot.service;
        empty.last_node = depot_index;
        RouteState opened;
        if (!route_append_feasible(
                depot_index,
                empty,
            customer_index,
            opened,
            count_check,
            record_customer
        )) {
            return false;
        }
        if (
            static_cast<int>(routes.size())
            >= problem_.depots[depot_index].cap
        ) {
            if (count_check) {
                ++stats_.d2a_cap_prunes;
            }
            return false;
        }
        routes.push_back(std::move(opened));
        assigned_demand +=
            problem_.customers[customer_index].demand;
        return true;
    }

    bool add_customer(
        SearchState& state,
        int depot_index,
        int customer_index,
        bool count_check,
        bool record_customer
    ) {
        return add_customer_to_depot(
            state.routes[depot_index],
            state.assigned_demand[depot_index],
            depot_index,
            customer_index,
            count_check,
            record_customer
        );
    }

    [[nodiscard]] int destination_for(
        const Customer& customer,
        const std::vector<int>& chosen
    ) const {
        if (customer.selected_position < 0) {
            return customer.original_depot;
        }
        const int option_index = chosen[customer.selected_position];
        return customer.options[option_index].depot;
    }

    bool pack_mapping(
        const std::vector<int>& chosen,
        std::vector<std::vector<std::vector<int>>>& groups
    ) {
        ++stats_.heuristic_checker_calls;
        SearchState state = empty_state();
        for (int customer_index = 0;
             customer_index < problem_.customer_count;
             ++customer_index) {
            const int destination =
                destination_for(problem_.customers[customer_index], chosen);
            if (!add_customer(
                    state,
                    destination,
                    customer_index,
                    false,
                    true
                )) {
                return false;
            }
        }
        groups = extract_groups(state);
        return true;
    }

    bool quick_witness(
        const std::vector<int>& prefix,
        const std::vector<int>* preferred,
        std::vector<int>& chosen,
        std::vector<std::vector<std::vector<int>>>& groups
    ) {
        std::vector<std::vector<int>> candidates;
        if (
            preferred != nullptr
            && preferred->size() == static_cast<std::size_t>(
                problem_.selected_count
            )
            && std::equal(
                prefix.begin(),
                prefix.end(),
                preferred->begin()
            )
        ) {
            candidates.push_back(*preferred);
        }
        std::vector<int> nearest(
            static_cast<std::size_t>(problem_.selected_count), 0
        );
        std::copy(prefix.begin(), prefix.end(), nearest.begin());
        candidates.push_back(nearest);

        std::uint64_t seed = problem_.random_seed;
        for (int value : prefix) {
            seed ^= static_cast<std::uint64_t>(value + 0x9e3779b9)
                + (seed << 6) + (seed >> 2);
        }
        std::mt19937_64 generator(seed);

        // A full random destination vector almost never lands inside the
        // narrow D2-A feasible region on the hard 150/200-customer cells.
        // Build additional result-blind witnesses online in the exact frozen
        // customer order.  Every choice is still checked through the same
        // First-Fit transition; this changes only witness discovery, not the
        // exhaustive proof used when no witness is found.
        const int online_attempts = prefix.empty() ? 8192 : 64;
        for (int attempt = 0; attempt < online_attempts; ++attempt) {
            ++stats_.heuristic_checker_calls;
            SearchState state = empty_state();
            std::vector<int> candidate(
                static_cast<std::size_t>(problem_.selected_count), -1
            );
            std::copy(prefix.begin(), prefix.end(), candidate.begin());
            bool failed = false;
            for (int customer_index = 0;
                 customer_index < problem_.customer_count;
                 ++customer_index) {
                const Customer& customer =
                    problem_.customers[customer_index];
                if (customer.selected_position < 0) {
                    if (!add_customer(
                            state,
                            customer.original_depot,
                            customer_index,
                            false,
                            false
                        )) {
                        failed = true;
                        break;
                    }
                    continue;
                }
                const int selected = customer.selected_position;
                if (selected < static_cast<int>(prefix.size())) {
                    const int option_index = prefix[selected];
                    candidate[selected] = option_index;
                    if (!add_customer(
                            state,
                            customer.options[option_index].depot,
                            customer_index,
                            false,
                            false
                        )) {
                        failed = true;
                        break;
                    }
                    continue;
                }
                std::vector<Branch> branches;
                branches.reserve(customer.options.size());
                for (int option_index = 0;
                     option_index
                         < static_cast<int>(customer.options.size());
                     ++option_index) {
                    const Option& option = customer.options[option_index];
                    Branch branch;
                    branch.absolute_rank = option.absolute_rank;
                    branch.destination = option.depot;
                    branch.option_index = option_index;
                    branch.state = state;
                    branch.feasible = add_customer(
                            branch.state,
                            option.depot,
                            customer_index,
                            false,
                            false
                        );
                    branch.route_utilization = branch.feasible
                        ? static_cast<double>(
                            branch.state.routes[option.depot].size()
                        ) / problem_.depots[option.depot].cap
                        : std::numeric_limits<double>::infinity();
                    branch.demand_utilization = branch.feasible
                        ? branch.state.assigned_demand[option.depot]
                            / (
                                problem_.depots[option.depot].cap
                                * problem_.payload_capacity
                            )
                        : std::numeric_limits<double>::infinity();
                    branches.push_back(std::move(branch));
                }
                std::shuffle(
                    branches.begin(),
                    branches.end(),
                    generator
                );
                const double jitter_scale =
                    attempt == 0
                    ? 0.0
                    : std::min(2.0, 0.05 + attempt / 4096.0);
                std::uniform_real_distribution<double> jitter(
                    0.0,
                    jitter_scale
                );
                for (Branch& branch : branches) {
                    if (branch.feasible) {
                        branch.demand_utilization += jitter(generator);
                    }
                }
                std::stable_sort(
                    branches.begin(),
                    branches.end(),
                    [](const Branch& left, const Branch& right) {
                        if (left.feasible != right.feasible) {
                            return left.feasible > right.feasible;
                        }
                        const double left_score =
                            4.0 * left.route_utilization
                            + left.demand_utilization;
                        const double right_score =
                            4.0 * right.route_utilization
                            + right.demand_utilization;
                        return left_score < right_score;
                    }
                );
                if (branches.empty() || !branches.front().feasible) {
                    failed = true;
                    break;
                }
                candidate[selected] = branches.front().option_index;
                state = std::move(branches.front().state);
            }
            if (!failed) {
                chosen = std::move(candidate);
                if (!pack_mapping(chosen, groups)) {
                    throw std::runtime_error(
                        "online witness replay failed"
                    );
                }
                return true;
            }
        }

        const int complete_random_attempts = prefix.empty() ? 512 : 32;
        for (int attempt = 0;
             attempt < complete_random_attempts;
             ++attempt) {
            std::vector<int> candidate = nearest;
            for (int selected = static_cast<int>(prefix.size());
                 selected < problem_.selected_count;
                 ++selected) {
                const Customer& customer =
                    problem_.customers[selected_customer_position_[selected]];
                std::uniform_int_distribution<int> distribution(
                    0, static_cast<int>(customer.options.size()) - 1
                );
                candidate[selected] = distribution(generator);
            }
            candidates.push_back(std::move(candidate));
        }

        std::vector<std::vector<int>> seen;
        for (const std::vector<int>& candidate : candidates) {
            if (
                std::find(seen.begin(), seen.end(), candidate)
                != seen.end()
            ) {
                continue;
            }
            seen.push_back(candidate);
            std::vector<std::vector<std::vector<int>>> candidate_groups;
            if (pack_mapping(candidate, candidate_groups)) {
                chosen = candidate;
                groups = std::move(candidate_groups);
                return true;
            }
        }
        return false;
    }

    void prepare_prefix_bounds(const std::vector<int>& prefix) {
        active_prefix_ = prefix;
        const int subset_count = (1 << problem_.depot_count) - 1;
        subset_capacity_.assign(
            static_cast<std::size_t>(subset_count + 1), 0.0
        );
        for (int mask = 1; mask <= subset_count; ++mask) {
            for (int depot = 0; depot < problem_.depot_count; ++depot) {
                if ((mask & (1 << depot)) != 0) {
                    subset_capacity_[mask] +=
                        problem_.depots[depot].cap
                        * problem_.payload_capacity;
                }
            }
        }
        suffix_mandatory_.assign(
            static_cast<std::size_t>(subset_count + 1),
            std::vector<double>(
                static_cast<std::size_t>(problem_.customer_count + 1), 0.0
            )
        );
        for (int customer_index = problem_.customer_count - 1;
             customer_index >= 0;
             --customer_index) {
            const Customer& customer = problem_.customers[customer_index];
            int allowed_mask = 0;
            if (customer.selected_position < 0) {
                allowed_mask = 1 << customer.original_depot;
            } else if (
                customer.selected_position
                < static_cast<int>(prefix.size())
            ) {
                allowed_mask = 1 << customer.options[
                    prefix[customer.selected_position]
                ].depot;
            } else {
                for (const Option& option : customer.options) {
                    allowed_mask |= 1 << option.depot;
                }
            }
            for (int mask = 1; mask <= subset_count; ++mask) {
                suffix_mandatory_[mask][customer_index] =
                    suffix_mandatory_[mask][customer_index + 1]
                    + (
                        (allowed_mask & ~mask) == 0
                        ? customer.demand
                        : 0.0
                    );
            }
        }
    }

    [[nodiscard]] Conflict failure_conflict(
        int depot,
        int through_customer_index
    ) const {
        Conflict result = empty_conflict(problem_.selected_count);
        for (int selected = 0;
             selected < problem_.selected_count;
             ++selected) {
            if (
                selected_customer_position_[selected]
                    > through_customer_index
            ) {
                continue;
            }
            const Customer& customer =
                problem_.customers[selected_customer_position_[selected]];
            int occurrences = 0;
            for (const Option& option : customer.options) {
                occurrences += option.depot == depot ? 1 : 0;
            }
            if (
                occurrences > 0
                && occurrences
                    < static_cast<int>(customer.options.size())
            ) {
                set_conflict(result, selected);
            }
        }
        return result;
    }

    bool hall_feasible(
        int customer_index,
        const SearchState& state,
        const std::vector<int>& chosen,
        Conflict& conflict
    ) {
        const int subset_count = (1 << problem_.depot_count) - 1;
        for (int mask = 1; mask <= subset_count; ++mask) {
            double current = 0.0;
            for (int depot = 0; depot < problem_.depot_count; ++depot) {
                if ((mask & (1 << depot)) != 0) {
                    current += state.assigned_demand[depot];
                }
            }
            if (
                current + suffix_mandatory_[mask][customer_index]
                > subset_capacity_[mask] + kTolerance
            ) {
                ++stats_.demand_hall_prunes;
                conflict = empty_conflict(problem_.selected_count);
                for (int selected = 0;
                     selected < problem_.selected_count;
                     ++selected) {
                    const int selected_customer =
                        selected_customer_position_[selected];
                    const bool processed =
                        selected_customer < customer_index;
                    const bool fixed_future =
                        !processed
                        && selected
                            < static_cast<int>(active_prefix_.size());
                    if (
                        (!processed && !fixed_future)
                        || chosen[selected] < 0
                    ) {
                        continue;
                    }
                    const Customer& selected_node =
                        problem_.customers[selected_customer];
                    const int destination =
                        selected_node.options[chosen[selected]].depot;
                    if ((mask & (1 << destination)) == 0) {
                        continue;
                    }
                    const bool can_leave_subset = std::any_of(
                        selected_node.options.begin(),
                        selected_node.options.end(),
                        [mask](const Option& option) {
                            return (
                                mask & (1 << option.depot)
                            ) == 0;
                        }
                    );
                    if (can_leave_subset) {
                        set_conflict(conflict, selected);
                    }
                }
                return false;
            }
        }
        return true;
    }

    bool visit(
        int customer_index,
        SearchState& state,
        std::vector<int>& chosen,
        Conflict& conflict
    ) {
        ++stats_.nodes_visited;
        if (
            std::getenv("RESETPE3E6_TRACE_PREFIX") != nullptr
            && stats_.nodes_visited % 1000000 == 0
        ) {
            std::cerr
                << "DFS_PROGRESS nodes=" << stats_.nodes_visited
                << " customer_index=" << customer_index
                << " hall_prunes=" << stats_.demand_hall_prunes
                << " cap_prunes=" << stats_.d2a_cap_prunes
                << '\n';
        }
        if (!hall_feasible(customer_index, state, chosen, conflict)) {
            return false;
        }
        if (
            customer_index % 8 == 0
            && !mandatory_clique_feasible(
                customer_index,
                state,
                chosen
            )
        ) {
            conflict = all_conflict(problem_.selected_count);
            return false;
        }
        if (customer_index == problem_.customer_count) {
            found_options_ = chosen;
            if (!pack_mapping(found_options_, found_routes_)) {
                throw std::runtime_error(
                    "exact witness replay failed"
                );
            }
            conflict = empty_conflict(problem_.selected_count);
            return true;
        }

        const Customer& customer = problem_.customers[customer_index];
        if (customer.selected_position < 0) {
            const int depot = customer.original_depot;
            std::vector<RouteState> old_routes = state.routes[depot];
            const double old_demand = state.assigned_demand[depot];
            if (!add_customer(
                    state,
                    depot,
                    customer_index,
                    true,
                    false
                )) {
                conflict = failure_conflict(
                    depot,
                    customer_index
                );
                return false;
            }
            if (visit(customer_index + 1, state, chosen, conflict)) {
                return true;
            }
            state.routes[depot] = std::move(old_routes);
            state.assigned_demand[depot] = old_demand;
            return false;
        }

        std::vector<int> option_indices;
        if (
            customer.selected_position
            < static_cast<int>(active_prefix_.size())
        ) {
            option_indices.push_back(
                active_prefix_[customer.selected_position]
            );
        } else {
            option_indices.resize(customer.options.size());
            std::iota(option_indices.begin(), option_indices.end(), 0);
        }

        std::vector<SearchBranch> branches;
        branches.reserve(option_indices.size());
        for (int option_index : option_indices) {
            const Option& option = customer.options[option_index];
            SearchBranch branch;
            branch.absolute_rank = option.absolute_rank;
            branch.destination = option.depot;
            branch.option_index = option_index;
            branch.routes = state.routes[option.depot];
            branch.assigned_demand =
                state.assigned_demand[option.depot];
            branch.feasible = add_customer_to_depot(
                branch.routes,
                branch.assigned_demand,
                option.depot,
                customer_index,
                true,
                false
            );
            branch.route_utilization = branch.feasible
                ? static_cast<double>(
                    branch.routes.size()
                ) / problem_.depots[option.depot].cap
                : std::numeric_limits<double>::infinity();
            branch.demand_utilization =
                (
                    state.assigned_demand[option.depot]
                    + customer.demand
                )
                / (
                    problem_.depots[option.depot].cap
                    * problem_.payload_capacity
                );
            branches.push_back(std::move(branch));
        }

        if (
            customer.selected_position
            < static_cast<int>(active_prefix_.size())
        ) {
            std::sort(
                branches.begin(),
                branches.end(),
                [](const SearchBranch& left, const SearchBranch& right) {
                    return left.option_index < right.option_index;
                }
            );
        } else {
            std::sort(
                branches.begin(),
                branches.end(),
                [](const SearchBranch& left, const SearchBranch& right) {
                    return std::tie(
                        left.route_utilization,
                        left.demand_utilization,
                        left.absolute_rank,
                        left.destination
                    ) < std::tie(
                        right.route_utilization,
                        right.demand_utilization,
                        right.absolute_rank,
                        right.destination
                    );
                }
            );
        }

        Conflict branch_conflicts = empty_conflict(problem_.selected_count);
        for (SearchBranch& branch : branches) {
            Conflict child_conflict =
                empty_conflict(problem_.selected_count);
            const int old_choice = chosen[customer.selected_position];
            chosen[customer.selected_position] = branch.option_index;
            if (!branch.feasible) {
                child_conflict = failure_conflict(
                    branch.destination,
                    customer_index
                );
            } else {
                std::vector<RouteState> old_routes =
                    std::move(state.routes[branch.destination]);
                const double old_demand =
                    state.assigned_demand[branch.destination];
                state.routes[branch.destination] =
                    std::move(branch.routes);
                state.assigned_demand[branch.destination] =
                    branch.assigned_demand;
                if (visit(
                        customer_index + 1,
                        state,
                        chosen,
                        child_conflict
                )) {
                    return true;
                }
                state.routes[branch.destination] =
                    std::move(old_routes);
                state.assigned_demand[branch.destination] =
                    old_demand;
            }
            chosen[customer.selected_position] = old_choice;
            if (!contains_conflict(
                    child_conflict,
                    customer.selected_position
                )) {
                ++stats_.conflict_backjumps;
                conflict = std::move(child_conflict);
                return false;
            }
            merge_conflict(branch_conflicts, child_conflict);
        }
        clear_conflict(branch_conflicts, customer.selected_position);
        conflict = std::move(branch_conflicts);
        return false;
    }

    bool solve_prefix(
        const std::vector<int>& prefix,
        const std::vector<int>* preferred,
        std::vector<int>& chosen,
        std::vector<std::vector<std::vector<int>>>& groups
    ) {
        ++stats_.prefix_oracle_calls;
        const bool trace = std::getenv(
            "RESETPE3E6_TRACE_PREFIX"
        ) != nullptr;
        const std::uint64_t nodes_before = stats_.nodes_visited;
        if (trace) {
            std::cerr
                << "PREFIX_START length=" << prefix.size()
                << " nodes_total=" << nodes_before << '\n';
        }
        if (quick_witness(prefix, preferred, chosen, groups)) {
            if (trace) {
                std::cerr
                    << "PREFIX_PASS_HEURISTIC length=" << prefix.size()
                    << " nodes_delta=0\n";
            }
            return true;
        }
        prepare_prefix_bounds(prefix);
        std::vector<int> working(
            static_cast<std::size_t>(problem_.selected_count), -1
        );
        for (std::size_t index = 0; index < prefix.size(); ++index) {
            working[index] = prefix[index];
        }
        Conflict conflict = empty_conflict(problem_.selected_count);
        SearchState state = empty_state();
        if (!visit(0, state, working, conflict)) {
            ++stats_.infeasible_prefix_attempts;
            if (trace) {
                std::cerr
                    << "PREFIX_INFEASIBLE_EXACT length="
                    << prefix.size()
                    << " nodes_delta="
                    << (stats_.nodes_visited - nodes_before)
                    << '\n';
            }
            return false;
        }
        chosen = found_options_;
        groups = found_routes_;
        if (trace) {
            std::cerr
                << "PREFIX_PASS_EXACT length=" << prefix.size()
                << " nodes_delta="
                << (stats_.nodes_visited - nodes_before)
                << '\n';
        }
        return true;
    }

    [[nodiscard]] std::vector<std::vector<std::vector<int>>>
    extract_groups(const SearchState& state) const {
        std::vector<std::vector<std::vector<int>>> result(
            static_cast<std::size_t>(problem_.depot_count)
        );
        for (int depot = 0; depot < problem_.depot_count; ++depot) {
            for (const RouteState& route : state.routes[depot]) {
                result[depot].push_back(route.customers);
            }
        }
        return result;
    }
};

Problem read_problem() {
    std::string magic;
    if (!(std::cin >> magic) || magic != "RESETPE3E6FF1") {
        throw std::runtime_error("invalid problem header");
    }
    Problem problem;
    std::cin
        >> problem.depot_count
        >> problem.customer_count
        >> problem.selected_count
        >> problem.payload_capacity
        >> problem.random_seed;
    problem.depots.resize(
        static_cast<std::size_t>(problem.depot_count)
    );
    for (Depot& depot : problem.depots) {
        std::cin >> depot.cap >> depot.ready >> depot.due >> depot.service;
    }
    problem.customers.resize(
        static_cast<std::size_t>(problem.customer_count)
    );
    problem.selected_customer.assign(
        static_cast<std::size_t>(problem.selected_count), -1
    );
    for (int index = 0; index < problem.customer_count; ++index) {
        Customer& customer = problem.customers[index];
        int option_count = 0;
        std::cin
            >> customer.id
            >> customer.demand
            >> customer.ready
            >> customer.due
            >> customer.service
            >> customer.original_depot
            >> customer.selected_position
            >> option_count;
        customer.options.resize(static_cast<std::size_t>(option_count));
        for (Option& option : customer.options) {
            std::cin >> option.absolute_rank >> option.depot;
        }
        if (customer.selected_position >= 0) {
            problem.selected_customer[customer.selected_position] = index;
        }
    }
    const int total = problem.depot_count + problem.customer_count;
    problem.travel.resize(
        static_cast<std::size_t>(total) * total
    );
    for (double& value : problem.travel) {
        std::cin >> value;
    }
    if (!std::cin) {
        throw std::runtime_error("truncated problem input");
    }
    return problem;
}

void write_stats(const Stats& stats) {
    std::cout
        << "STATS "
        << stats.prefix_oracle_calls << ' '
        << stats.infeasible_prefix_attempts << ' '
        << stats.nodes_visited << ' '
        << stats.route_feasibility_checker_calls << ' '
        << stats.d2a_cap_prunes << ' '
        << stats.conflict_backjumps << ' '
        << stats.heuristic_checker_calls << ' '
        << stats.demand_hall_prunes << ' '
        << stats.pairwise_clique_prunes << '\n';
}

}  // namespace

int main() {
    try {
        std::ios::sync_with_stdio(false);
        std::cin.tie(nullptr);
        std::cout << std::setprecision(17);

        Problem problem = read_problem();
        const int depot_count = problem.depot_count;
        const int selected_count = problem.selected_count;
        Solver solver(std::move(problem));
        std::vector<int> chosen;
        std::vector<std::vector<std::vector<int>>> route_groups;
        const bool feasible = solver.solve(chosen, route_groups);
        if (!feasible) {
            std::cout << "INFEASIBLE\n";
            write_stats(solver.stats());
            return 0;
        }
        std::cout << "PASS\n";
        std::cout << "CHOSEN " << selected_count;
        for (int option_index : chosen) {
            std::cout << ' ' << option_index;
        }
        std::cout << '\n';
        std::cout << "DEPOTS " << depot_count << '\n';
        for (int depot = 0; depot < depot_count; ++depot) {
            std::cout
                << "DEPOT " << depot << ' '
                << route_groups[depot].size() << '\n';
            for (const std::vector<int>& route : route_groups[depot]) {
                std::cout << "ROUTE " << route.size();
                for (int customer_index : route) {
                    std::cout << ' ' << customer_index;
                }
                std::cout << '\n';
            }
        }
        write_stats(solver.stats());
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "ERROR " << error.what() << '\n';
        return 2;
    }
}
