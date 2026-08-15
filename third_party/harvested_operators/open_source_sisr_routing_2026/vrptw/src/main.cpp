#include "ProblemInstance.hpp"
#include "Solution.hpp"
#include "Sisrs.hpp"

#include <chrono>

#include "../lib/cxxopts.hpp"

int main(int argc, char *argv[])
{

    cxxopts::Options options("solver", "Open-source C++ implementation of Slack Induction by String Removals for vehicle routing problem with time windows");
    options.add_options()
        ("instance", "Path to the instance file", cxxopts::value<std::string>())
        ("configuration", "Path to the JSON configuration file", cxxopts::value<std::string>())
        ("output-json", "Path to the output file to save the JSON-style result", cxxopts::value<std::string>())
        ("output-agg", "Path to the output file to save (append) the aggregated run result", cxxopts::value<std::string>())
        ("v,verbose", "Enable detailed logging output", cxxopts::value<bool>()->default_value("false"))
        ("h,help", "Print usage")
    ;
    auto cli_args = options.parse(argc, argv);

    if (cli_args.count("help")) {
        std::cout << options.help() << std::endl;
        return 0;
    }
    if (cli_args.count("instance") == 0) {
        std::cerr << "Error: The required argument --instance must be provided.\n" << options.help() << std::endl;
        return 1;
    }
    if (cli_args.count("configuration") == 0) {
        std::cerr << "Error: The required argument --configuration must be provided.\n" << options.help() << std::endl;
        return 1;
    }

    std::string instance_path = cli_args["instance"].as<std::string>();
    std::string configuration_path = cli_args["configuration"].as<std::string>();
    bool is_verbose = cli_args["verbose"].as<bool>();

    std::chrono::steady_clock::time_point begin = std::chrono::steady_clock::now();

    std::string base_filename = instance_path.substr(instance_path.find_last_of("/\\") + 1);
    int dot_pos = base_filename.find_last_of('.');
    std::string file_extension = base_filename.substr(dot_pos + 1);

    ProblemInstance problem;

    if (file_extension == "vrp" || file_extension == "txt")
    {
        if (!readProblemFileVRPTW(instance_path, problem))
        {
            std::cerr << "Problem loading the input file." << std::endl;
            return 1;
        }

        // Finish data preparation
        preprocessProblem(problem);
    }
    else
    {
        std::cerr << "Unknown input file format." << std::endl;
        return 1;
    }

    // Initialize the solver class
    Sisrs solver(problem, configuration_path, is_verbose);

    // Solve the problem
    solver.localSearch();

    std::chrono::steady_clock::time_point end = std::chrono::steady_clock::now();
    float duration = std::chrono::duration_cast<std::chrono::seconds>(end - begin).count();

    std::string filename_without_extension = base_filename.substr(0, dot_pos);

    // Write solution into JSON-style file
    if (cli_args.count("output-json") != 0)
    {
        std::string output_path_json = cli_args["output-json"].as<std::string>();

        if (solver.saveJson(output_path_json, duration))
        {
            std::cout << "Solution writen to JSON file successfully!" << std::endl;
        }
        else
        {
            std::cout << "Failed to file write solution to JSON file!" << std::endl;
        }
    }

    // Write into aggregated experiment document
    if (cli_args.count("output-agg") != 0)
    {
        std::string output_path_agg = cli_args["output-agg"].as<std::string>();

        std::ofstream outFile(output_path_agg, std::ios::app);
        if (outFile.is_open())
        {
            outFile << filename_without_extension << " " << solver.sol_best->routes_count << " " << solver.sol_best->total_cost << " " << duration << std::endl;
            outFile.close();
            std::cout << "Aggregated file written successfully!" << std::endl;
        }
        else
        {
            std::cout << "Failed to open the aggregated file " << output_path_agg << std::endl;
        }
    }
    std::cout << "Best solution no. vehicles & distance: " << solver.sol_best->routes_count << " " << solver.sol_best->total_cost << " " << " Computation time (s): " << duration << std::endl;

    return 0;
}