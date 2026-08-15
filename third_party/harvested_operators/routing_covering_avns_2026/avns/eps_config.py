"""
Configuration files for epsilon values used in different stages of the algorithm.
"""

# epsilons that are used for improvement checking in local search operators
S_EPS = 1e-10  # baseline epsilon used for all types of comparisons
OPT_EPS = 1e-3  # used to verify if the result of an optimization model has an objective < best_delta
C_EPS = 0  # epsilon used when verifying capacity restrictions; epsilon is added to capacity for additional buffer
ZRO_OP_EPS = 1e-5  # cost delta epsilon - used by LS operators to pre-filter potentially nonchanging moves
LARGE_NUM = 10 ** 10 # large number, used during feasibility checks in operator computation
