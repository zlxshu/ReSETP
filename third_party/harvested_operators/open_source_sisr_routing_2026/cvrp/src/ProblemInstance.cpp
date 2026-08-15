#include "ProblemInstance.hpp"

Matrix::Matrix() : dimension(0) {}

Matrix::Matrix(size_t dim)
    : dimension(dim), data(dim * dim, DistanceType()) {}

void ProblemInstance::print() const
{
    std::cout << "ProblemInstance:" << std::endl;
    std::cout << "Name: " << name << std::endl;
    std::cout << "Dimension: " << dimension << std::endl;
    std::cout << "Vehicles: " << vehicles << std::endl;
    std::cout << "Customer Count: " << customer_count << std::endl;
    std::cout << "Depot Indices: ";
    std::cout << depot_index << " ";
    std::cout << std::endl;
    std::cout << "Capacity: " << capacity << std::endl;

    std::cout << "Nodes:" << std::endl;
    for (const Node &node : nodes)
    {
        std::cout << node.id << ": x: " << node.x << " y: " << node.y << " demand: "
                  << node.demand;
    }
}

// Calculates Euclidean distance between 2 nodes
DistanceType ProblemInstance::computeNodesDistance(int node_a, int node_b)
{
    float dx = nodes[node_a].x - nodes[node_b].x;
    float dy = nodes[node_a].y - nodes[node_b].y;

    double distance = std::sqrt(dx * dx + dy * dy);

    if constexpr (std::is_integral<DistanceType>::value)
    {
        return static_cast<DistanceType>(std::round(distance));
    }
    else
    {
        return static_cast<DistanceType>(distance);
    }
}

// Calculates distances of all nodes between each other
void computeDistanceMatrix(ProblemInstance &p)
{
    p.distance_matrix = Matrix(p.dimension);

    for (int i = 0; i < p.dimension; ++i)
    {
        for (int j = i + 1; j < p.dimension; ++j)
        {
            DistanceType distance = p.computeNodesDistance(i, j);
            p.distance_matrix[i][j] = distance;
            p.distance_matrix[j][i] = distance;
        }
    }
}

// For each node sort all other nodes based on their distance
void computeAdjacencyMatrix(ProblemInstance &instance)
{
    instance.adjacency_matrix.resize(instance.dimension);

    for (int i = 0; i < instance.dimension; ++i)
    {
        std::vector<std::pair<DistanceType, int>> distances;

        for (int j = 0; j < instance.dimension; ++j)
        {
            distances.push_back(std::make_pair(instance.distance_matrix[i][j], j));
        }

        std::sort(distances.begin(), distances.end());

        instance.adjacency_matrix[i].resize(distances.size());
        for (int k = 0; k < distances.size(); ++k)
        {
            instance.adjacency_matrix[i][k] = distances[k].second;
        }
    }
}

void preprocessProblem(ProblemInstance &instance)
{
    computeDistanceMatrix(instance);
    computeAdjacencyMatrix(instance);
}

// Reads problem instance from a file
bool readProblemFileVRP(const std::string &path, ProblemInstance &instance)
{
    // Get the value after the first colon in a string
    auto getValue = [](const std::string &line) -> std::string
    {
        auto pos = line.find(':');
        return (pos != std::string::npos) ? line.substr(pos + 1) : "";
    };

    std::ifstream file(path);

    if (!file.is_open())
    {
        std::cerr << "Error: Could not open file " << path << std::endl;
        return false;
    }

    std::string line;

    // Section with general parameters, some might be missing depending on the dataset
    while (std::getline(file, line))
    {
        std::istringstream iss(line);
        std::string key;
        if (line.find("NODE_COORD_SECTION") != std::string::npos)
        {
            break;
        }
        else if (std::getline(iss, key, ' '))
        {
            if (key == "NAME")
            {
                instance.name = getValue(line);
            }
            else if (key == "DIMENSION")
            {
                instance.dimension = std::stoi(getValue(line));
            }
            else if (key == "CAPACITY")
            {
                instance.capacity = std::stoi(getValue(line));
            }
        }
    }

    // Section with customers coordinates
    instance.nodes.reserve(instance.dimension);
    while (std::getline(file, line))
    {
        if (std::find_if_not(line.begin(), line.end(), ::isspace) == line.end())
            continue;

        if (line.find("DEMAND_SECTION") != std::string::npos)
            break;

        Node node;
        std::istringstream iss(line);
        iss >> node.id >> node.x >> node.y;
        instance.nodes.push_back(node);
    }

    // Section with demands of the customers
    while (std::getline(file, line))
    {
        if (std::find_if_not(line.begin(), line.end(), ::isspace) == line.end())
            continue;

        if (line.find("DEPOT_SECTION") != std::string::npos)
            break;

        std::istringstream iss(line);

        int id;
        int demand;
        iss >> id;
        iss >> demand;

        instance.nodes[id - 1].demand = demand;
    }

    // Section with depot position
    instance.customer_count = instance.dimension - 1;
    while (std::getline(file, line))
    {
        if (std::find_if_not(line.begin(), line.end(), ::isspace) == line.end())
            continue;

        if (line.find("-1") != std::string::npos)
            break;

        std::istringstream iss(line);

        int id;
        iss >> id;

        // Indexing from 0
        instance.depot_index = id - 1;
    }

    file.close();

    return true;
}
