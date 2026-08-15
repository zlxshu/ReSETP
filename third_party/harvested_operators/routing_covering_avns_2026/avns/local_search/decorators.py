"""Decorators and their corresponding sets, used to identify the call signature required by each implemented operator.

# The decorators proposed in this file are adapted from VeRyPy
# (https://github.com/yorak/VeRyPy), by Jussi Rasku, under the MIT License.
# Original copyright (c) 2021 Jussi Rasku. All rights reserved.

"""
# All operators that are sensitive to route order must be added here.
#  See inter_route_operations.py decorator for details.
ROUTE_ORDER_SENSITIVE_OPERATORS = set()

#  All operators that receive the entire route_datas list of RouteData objects as input (can operate on all routes at once)
ALL_ROUTES_INPUT_OPERATORS = set()

#  All operators that have to be applied at the start to build a model (Depot IP move)
KEEP_START_MODEL_OPERATORS = set()


# All operators that change customer assignments
CHANGE_CUSTOMER_ASSIGNMENTS = set()

# All intra route operators (only operators that can ONLY be called with a single route as argument)
INTRA_ROUTE_OPERATORS = set()


def setAsIntraRoute(f):
    """Intra-route operators only."""
    INTRA_ROUTE_OPERATORS.add(f)
    return f

def routeordersensitive(f):
    """Order-sensitive operator only."""
    ROUTE_ORDER_SENSITIVE_OPERATORS.add(f)
    return f

# Create a decorator to mark operators that receive the total route list
def receivesroutedatasinput(f):
    """Operators that receive all routes as input."""
    ALL_ROUTES_INPUT_OPERATORS.add(f)
    return f



def buildstartmodel(f):
    """Operators that set up a gurobi model, which can be stored and re-used in subsequent operator calls."""
    KEEP_START_MODEL_OPERATORS.add(f)
    return f


def changescustomerassignments(f):
    """Operators that adjust customer assignments, i.e., that adjust covering decisions."""

    CHANGE_CUSTOMER_ASSIGNMENTS.add(f)
    return f


# Strategy for the local search operators: Accept the first or best improvement?
class LSOPT:
    FIRST_ACCEPT = 1  # Accept the first improving move
    BEST_ACCEPT = 2  # Accept the best improving move


# Strategy for the applying moves: Apply first move right away or apply best move after trying all?
class APPLYOPT:
    FIRST_APPLY = 5  # Apply first move as soon as it is found
    BEST_APPLY = 6  # Try all moves first, apply best move
