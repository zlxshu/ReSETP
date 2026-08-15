#pragma once

#include <random>
#include <optional>
#include <memory>

#include "Solution.hpp"
#include "ProblemInstance.hpp"

// Class representing a CVRP problem solver based on the algorithms from SISRs article
class Sisrs
{
private:
    // --- SA metaheuristic parameters

    // Number of iterations
    int n_iter = 300000;

    // Starting temperature
    double t_0 = 100.0;

    // Final temperature
    double t_f = 1.0;

    // Cooling constant
    double cooling = pow(t_f / t_0, 1.0 / n_iter);

    //Sorting algorithms of recreate
    enum SortAlgorithm
    {
        RANDOM,
        DEMAND,
        FAR,
        CLOSE
    };

    std::vector<int> weights = {4, 4, 2, 1};

    // --- Other constants

    // Maximal number of removed customers from a single path
    int max_cardinality = 10;

    // Average number of removed customers
    int average_removed = 10;

    // Split procedure choice probability
    float alpha = 0.5f;

    // split string removal parameter
    float beta = 0.01f;

    // recreate blink rate - only two decimal places are taken to account
    float gamma = 0.01f;

    // RNG
    std::minstd_rand gen;

    // Instance that is being solved
    ProblemInstance &problem;

    // Verbose/silent mode
    bool is_verbose = false;

    // Setup parameters
    void setupParameters(const std::string &config);

    // Returns a substring from a string that contains element on the desired position
    std::vector<int> randomSubstringIncluding(const std::vector<int> &input_string, int output_length, int must_include_index);

    // Returns a starting index of a random substring of desired length
    int randomSubstringStart(int full_length, int substring_length);

    // Returns a starting index of a random substring of desired length, including element on defined index
    int randomSubstringStartIncluding(int full_length, int substring_length, int must_include_index);

    // Builds an naive solution with routes containing single customer
    // Ignores vehicle capacity constraint
    std::unique_ptr<Solution> createInitialSolution();

    // Ruin algorithm (2)
    void ruin();

    // Recreate algorithm (3)
    bool recreate(DistanceType max_cost);

    // --- Logs

    // WHich sorting recreate used in the current iteration
    std::string last_sorting;

    // Improvements list
    nlohmann::json improvements = nlohmann::json::array();

    // Store the parameters
    nlohmann::json logParameters();

public:
    // Best discovered solution
    std::unique_ptr<Solution> sol_best;

    // Current solution
    std::unique_ptr<Solution> sol_current;

    // Neigbhbour solution of current
    std::unique_ptr<Solution> sol_neighbor;

    // Problem instance which is being solved
    Sisrs(ProblemInstance &p, const std::string &config, bool is_verbose);

    // Simulated annealing metaheuristic (Algorithm 1)
    void localSearch();

    bool saveJson(const std::string& path, float duration);

};