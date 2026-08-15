#pragma once

#include <iostream>
#include <fstream>
#include <string>
#include <vector>
#include <sstream>
#include <stdio.h>
#include <cmath>
#include <list>
#include <algorithm>

#include "../lib/json.hpp"

using DistanceType = int;

struct Matrix
{
public:
    Matrix();
    Matrix(size_t dimension);

    DistanceType *operator[](int r)
    {
        return &data[r * dimension];
    }

private:
    size_t dimension;
    std::vector<DistanceType> data;
};

// Struct representing a node (customer or depot) in the problem instance
struct Node
{
    // id is indexed from 1
    int id;
    float x;
    float y;
    int demand;
};

// Class representing a problem instance for a vehicle routing problem
class ProblemInstance
{
public:
    // Miscellaneous information from the input files
    std::string name;

    // Total number of nodes
    int dimension;

    // Number of vehicles
    int vehicles;

    // Number of customers
    int customer_count;

    // Node indicex of depot
    int depot_index;

    // Vehicle capacity
    int capacity;

    // Vector of all nodes (customers and depot)
    std::vector<Node> nodes;

    // Distance matrix between nodes
    Matrix distance_matrix;

    // Adjacency matrix between nodes (used by the SISRs algorithm)
    std::vector<std::vector<int>> adjacency_matrix;

    // Reads the problem instance from a file
    friend bool readProblemFileVRP(const std::string &path, ProblemInstance &instance);

    friend bool readProblemFileJson(const std::string &path, ProblemInstance &instance);

    // Computes additional data
    friend void preprocessProblem(ProblemInstance &instance);

    // Aux. funtion to get distance of 2 nodes
    DistanceType computeNodesDistance(int node_a, int node_b);

    void print() const;
};