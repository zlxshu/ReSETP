# RoutingCovering_AVNS

This repository contains a Python implementation of the **Adaptive Variable Neighborhood Search (AVNS)** proposed in:

> Hagn, A., Krause, J., Stargalla, M., Moreno, L. (2026). *An Adaptive Variable Neighborhood Search for a Family of Set Covering Routing Problems with an Application in Disaster Relief Operations.* arXiv Preprint: https://arxiv.org/abs/2411.17510

The algorithm solves a family of **Set Covering Routing Problems (SCRPs)**, including the Multi-Vehicle Covering Tour Problem (m-CTP and m-CTP-p), the Vehicle Routing Problem with Demand Allocation (VRDAP), and a real-world case study on helicopter-based food aid distribution in Afghanistan. The repository also includes the generator used to construct the Afghanistan case study instances.

The test instances and computed solutions used in the paper are hosted in a separate repository: https://github.com/andreashagntum/RoutingCovering_Instances.

**If you use this code in your own work, please cite the paper above.**

---

## Algorithm Overview

The AVNS solves SCRPs, a class of vehicle routing problems in which not every customer has to be visited directly. Instead, customers are *covered* by nearby facilities (distribution points), which are visited by vehicles on circular routes originating at depots. The objective is to jointly minimize routing costs and customer-to-facility assignment costs, subject to vehicle capacity, facility capacity, and route-length constraints.

The algorithm operates in three phases:

**1. Constructive heuristic.** A feasible initial solution is built in two steps: customers are first greedily assigned to facilities (prioritizing the most constrained customers), and facilities are then routed using a cheapest-insertion procedure.

**2. Local search.** A set of operators is applied iteratively to improve the current solution. Operators fall into four categories:
- *Intra-route operators* (2-opt, swap, relocate) improve the ordering of facilities within a single route.
- *Inter-route operators* (1-point move, 2-point move, 2-opt\*, cross-string) move or exchange facilities between routes.
- *Depot assignment* reassigns routes to depots using a greedy cost-delta criterion.
- *Facility string replacement* removes strings of consecutive facilities from a route and reassigns their customers to open or closed facilities, simultaneously modifying route structure and customer assignments.

An **adaptive operator selection** mechanism tracks each operator's historical performance using a smoothed scoring system and biases future selections toward operators that have recently yielded improvements. A **tabu simulated annealing** criterion controls solution acceptance, allowing non-improving moves to be accepted with a temperature-dependent probability while a tabu list prevents cycling.

**3. Shaking.** When the local search stagnates, a destroy-and-repair shaking step perturbs the current solution by removing fractions of customers, facilities, and depots, then rebuilding feasibility using the constructive heuristic. The intensity of the perturbation is gradually increased across consecutive shaking steps, and reset whenever a new best solution is found.

For a detailed description of all algorithm components, refer to Section 4 of the paper and the docstrings of the individual source files.

---

## Repository Structure

```
RoutingCovering_AVNS/
├── afg_instance_generation/         # Generator for the Afghanistan case study instances
├── avns/                            # AVNS implementation
│   ├── data_structures/             # Input data and route/solution data structures
│   │   ├── data_classes.py          # Instance data classes
│   │   ├── ls_route_classes.py      # Route data structures used during local search
│   │   └── solution_classes.py      # Route and solution data structures
│   ├── local_search/                # Local search operators
│   │   ├── compute_operator.py      # Operator dispatch and evaluation logic
│   │   ├── customer_operators.py    # Operators also modifying customer-to-facility assignments
│   │   ├── decorators.py            # Decorators categorizing operators by type and call signature
│   │   ├── depot_route_operators.py # Depot assignment operator
│   │   ├── inter_route_operators.py # Inter-route operators
│   │   ├── intra_route_operators.py # Intra-route operators
│   │   └── operator_auxiliary.py    # Auxiliary functions shared across operators
│   ├── utils/                       # Utility modules
│   │   ├── auxiliary.py             # General-purpose auxiliary functions
│   │   ├── plot_solutions.py        # Progress plots and Folium map visualizations
│   │   └── route_util.py            # Solution cost computation functions
│   ├── adaptive_vns.py              # Main AVNS loop
│   ├── constructive_heuristic.py    # Greedy constructive heuristic
│   ├── eps_config.py                # Epsilon tolerances used throughout the algorithm
│   ├── scoring.py                   # Operator scoring and adaptive selection logic
│   ├── shaking.py                   # Shaking decision and destroy-and-repair logic
│   └── simulated_annealing.py       # Simulated annealing acceptance criterion
├── config/                          # Environment configuration files
│   ├── requirements.txt             # Minimal dependencies
│   └── scrp_avns.yaml               # Conda environment file (full)
├── experiments/                     # Experiment entry point and configuration
│   ├── parameter_configs/           # Per-instance-set hyperparameter configurations
│   │   ├── AFG_config_avns.py
│   │   ├── m_CTP_config_avns.py
│   │   ├── m_CTP_p_config_avns.py
│   │   ├── mandatory_m_CTP_p_config_avns.py
│   │   ├── non_mandatory_m_CTP_p_config_avns.py
│   │   └── VRDAP_config_avns.py
│   └── run.py                       # Main entry point for running the AVNS
└── mip/
    └── mip.py                       # Gurobi MIP formulation (benchmark / lower bound computation)
```

---

## Getting Started

### Requirements

- Python 3.12
- Dependencies listed in `config/requirements.txt`

To recreate the environment used in the paper:

```bash
conda create --name scrp_avns python=3.12
conda activate scrp_avns
pip install -r config/requirements.txt
```

or simply clone the conda environment:
```bash
conda env create --file config/scrp_avns.yaml
```

### Running the AVNS

The main entry point is `experiments/run.py`. Input arguments — including the instance set, instance directory, output directory, runtime limit, and number of runs — are configured directly in the `__main__` block of that file. The hyperparameter configurations for each instance set are defined in the corresponding file under `experiments/parameter_configs/`.

### MIP Formulation

`mip/mip.py` provides a standalone Gurobi implementation of the MILP formulation from Section 3.1 of the paper, which can be used to compute lower bounds or solve small instances to optimality. Similar to `run.py`, all required 
parameters are defined in its `__main__` block.


Note that `mip.py` requires a valid **Gurobi license**.

### Generating Afghanistan Case Study Instances

The `afg_instance_generation/` directory contains the instance generator for the Afghanistan case study. For a detailed description of the generation procedure and the required input data, refer to the README inside that directory.

---

## Related Repositories

| Repository                                                                               | Contents                                                                                                                                                                                                    |
|------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [RoutingCovering_Instances](https://github.com/andreashagntum/RoutingCovering_Instances) | Test instances and computed solutions for all instance sets considered in the paper                                                                                                                         |
| [VeRyPy](https://github.com/yorak/VeRyPy)                    | Ready-to-use implementation of various Vehicle Routing heuristics; implementations of several inter- and intra-route operators as well as other datastructures were re-used and extended in this repository |

---
