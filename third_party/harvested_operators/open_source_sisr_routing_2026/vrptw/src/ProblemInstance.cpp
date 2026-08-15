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
    std::cout << "Depot Indiex: " << depot_index << " ";
    std::cout << std::endl;
    std::cout << "Capacity: " << capacity << std::endl;

    std::cout << "Nodes:" << std::endl;
    for (const Node &node : nodes)
    {
        std::cout << node.id << ": x: " << node.x << " y: " << node.y << " demand: " << node.demand
                  << " tw start: " << node.service_start << " tw end: " << node.service_end
                  << " tw duration: " << node.service_length << std::endl;
    }
}

// Calculates Euclidean distance between 2 nodes
DistanceType ProblemInstance::computeNodesDistance(int node_a, int node_b)
{
    double dx = nodes[node_a].x - nodes[node_b].x;
    double dy = nodes[node_a].y - nodes[node_b].y;

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

// Homberger and Gehring (1999)
// Customer data are indexed from 0 in this problem file type
bool readProblemFileVRPTW(const std::string &file_path, ProblemInstance &instance)
{
    std::ifstream file(file_path);

    if (!file.is_open())
    {
        std::cerr << "Error: Could not open file " << file_path << std::endl;
        return false;
    }

    instance.customer_count = 0;
    std::string line;

    // Skips over lines in the file that contain only whitespaces and skips over declared number of non-empty lines
    // Returns the first non-empty line after all desired skips were made
    auto skip_lines = [&file](int non_empty_kept) 
    {
        std::string line;
        int non_empty_count = -1;

        while (getline(file, line))
        {
            if (std::find_if_not(line.begin(), line.end(), ::isspace) == line.end())
                continue;
            
            non_empty_count ++;
            if (non_empty_count >= non_empty_kept)
                break;
        }
        return line;
    };

    // Read the instance name
    line = skip_lines(0);
    instance.name = line;

    // Skip lines without information and read the vehicle stats
    line = skip_lines(2);
    std::istringstream ss(line);
    ss >> instance.vehicles >> instance.capacity;

    // Skip more lines
    skip_lines(1);

    // Read nodes
    while (std::getline(file, line))
    {
        if (std::find_if_not(line.begin(), line.end(), ::isspace) == line.end())
            continue;

        std::istringstream iss(line);

        Node node;

        iss >> node.id >> node.x >> node.y >> node.demand >> node.service_start >> node.service_end >> node.service_length;

        if (node.demand == 0)
        {
            instance.depot_index = node.id;
        }
        else
        {
            ++instance.customer_count;
        }

        instance.nodes.push_back(node);
        ++instance.dimension;
    }

    file.close();

    return true;
}
