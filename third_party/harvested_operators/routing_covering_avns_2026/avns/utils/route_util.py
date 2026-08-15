"""Functions to compute the objective function value (including/excluding covering costs), as well as to
compute the routing cost (or distance) of a single route.
Because said values often need to be computed for CoveringRoute, CoveringRoutePool, or RouteData objects, we implement
them once in this script instead of implementing a corresponding function for each of the aforementioned classes.

# Portions of this file are adapted from VeRyPy
# (https://github.com/yorak/VeRyPy), by Jussi Rasku, under the MIT License.
# Original copyright (c) 2021 Jussi Rasku. All rights reserved.
Adjustments and extensions have been made to account for the peculiarities of the underlying problem, which include:
rejection of nonchanging moves, acceptance of non-improving moves, inclusion of covering cost, and inclusion of
additional capacity and route length restrictions.
"""


def route_objf(route, cm, ca, ccc):
    """ Compute the objective function of a solution, given by sol and ca.
    Parameters

    ----------
    route: list
       Route for which cost should be computed
    cm: np.ndarray
       Cost Matrix
    ca: dict
       Maps facilities to a list of customers that are covered by the facility. Keys must exactly match the entries
       in route[1:-1]
    ccc: np.ndarray
       Customer covering cost matrix

    Returns
    -------
    cost: float
       Total routing and covering cost incurred by route and its coverings

    """
    cost = sum((cm[route[i - 1], route[i]] for i in range(1, len(route)))) + sum([ccc[c][f] for f in route[1:-1] for c in ca[f]])
    return cost

def route_objf_only_routing(route, m):
    """ Compute the cost of a route with respect to a matrix m.
    m can either be a cost matrix or a distance matrix.
    Parameters
    ----------
    route: list
       Route for which cost should be computed
    m: np.ndarray
       Cost or distance matrix

    Returns
    -------
    val: float
       Total routing cost (or distance, depending on the input matrix) of route

    """
    val = sum((m[route[i - 1], route[i]] for i in range(1, len(route))))
    return val
