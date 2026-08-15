"""
This file implements depot route (i.e. between two or more routes)
local search improvement heuristics such as swap_depots, reassign_depot move etc. All
operators assume we start from a feasible solution. Also, all functions
implementing the operations have the following signature:

do_Y_move(route_datas, ... , dm,cm,d,node_cap,v_cap strategy, best_delta), where

* route_datas is a list of RouteData objects, the data members are
        1. route as a list of node indices. Must begin and end to depot (0).
        2. current route cost
        3. current route demand, can be None is v_cap = None
* dm is the numpy-compatible distance matrix as with intra route heuristics.
* cm is the numpy-compatible cost matrix as with intra route heuristics.
* v_cap is the optional capacity constraint (can be None). If set, also give d.
* d is the demand of each facility and depot (d[0] is 0)
    The parameter must be set if v_cap is given.
* node_cap is the maximum capacity of a facility and depot
* strategy is either FIRST_ACCEPT (default) or BEST_ACCEPT.
    First accept returns a modified route as soon as the first improvement is
    encountered. Best accept tries all possible combinations and returns the
    best one.
* best_delta is the required level of change in the in route cost. It can be
   used to  set the upper bound (requirement) for the improvement. Usually it
   is None, which sets the level to 0.0. In that case only improving deltas are
   accepted. If set to (large) positive value, best worsening move can also be
   returned.

All depot route improvement operators return
1. the new improved routes as a list of route data objects
    IMPORTANT: Only changed routes are returned
2. A list of tuples (depot_index, depot_demand_delta) for all depot demand changes
3. a list of depots that have their demands reduced
4. the improvement (delta)
as (1+1+1)-tuple to the operator or (None,None,None) if no improvements were found."""

import gurobipy as grb

from avns.data_structures.ls_route_classes import RouteData
from avns.local_search.decorators import receivesroutedatasinput, buildstartmodel
from avns.eps_config import C_EPS, OPT_EPS
from avns.utils.route_util import route_objf_only_routing


@buildstartmodel
@receivesroutedatasinput
def do_depot_ip_move(route_datas, dm, cm, q, d, dc,
                     node_cap,  # constraints
                     best_delta,
                     model,
                     first_iteration):
    """ For a current solution with routes, compute the depot insertion cost
        for all depots, use information as IP-input and solve an IP.

    If an improving move was found and made, operation returns a list of the
    same length as route_datas with None entries if route at that index was
    not changed and else the changed RouteData object.
    If there is no improving move found, returns None.

    This operator has to receive an optimization model as parameter
        and an indicator for the first operation.
    """
    # 1. Initialize
    depots = list(range(1, len(dc)))
    route_ids = list(range(len(route_datas)))
    current_depot_cost = 0
    no_good_cut_is_active = False   # True iff. no good cut is active at current iteration

    # 2. If depotIP is called for the first time: set up IP from scratch
    if first_iteration:
        # 2.1 Create the model completely - use addLConstr to speed up constraint creation
        model = grb.Model("SSCFLP")

        # 2.2 Create variables
        x: dict[tuple[int, int], grb.Var] = {}
        y: dict[int, grb.Var] = {}

        # 2.3 Build model
        for depot in depots:
            # 2.3.1 Depot selection variables
            y[depot] = model.addVar(obj=dc[depot], lb=0, ub=1, vtype=grb.GRB.BINARY, name=f"y[{depot}]")

            # 2.3.2 If depot is currently open, add costs
            if d[depot] > 0:
                current_depot_cost += dc[depot]

            # 2.3.3 Depot-route assignment variables
            for i in route_ids:
                # a) Make sure swap information from route is available, compute it if is not available
                route_datas[i].update_depot_dist_swaps(new_depot=depot, dm=dm, cm=cm)

                # b) Define variables
                x[depot, i] = model.addVar(obj=route_datas[i].depot_dist_swaps[depot][0], lb=0, ub=1,
                                           vtype=grb.GRB.BINARY,
                                           name=f"x[{depot},{i}]")


                # 2.3.4 Routes can only be assigned to opened depots
                model.addLConstr(lhs=x[depot, i], sense=grb.GRB.LESS_EQUAL, rhs=y[depot], name=f"only_select_open_depots_dep{depot}_route{i}]")

            # 2.3.5 Depot capacity constraint
            model.addLConstr(lhs=grb.quicksum(route_datas[i].demand * x[depot, i] for i in route_ids),
                             sense=grb.GRB.LESS_EQUAL,
                             rhs=(node_cap[depot] + C_EPS) * y[depot],
                             name=f"depot_capacity_{depot}")

            # 2.3.6 Dummy constraints that force variables to 0 iff. they violate q constraint
            for i in route_ids:
                if dm is None:
                    route_distance = route_objf_only_routing(route_datas[i].route, cm)
                else:
                    route_distance = route_objf_only_routing(route_datas[i].route, dm)
                if route_distance + route_datas[i].depot_dist_swaps[depot][1] <= q:
                    model.addLConstr(lhs=x[depot, i], sense=grb.GRB.LESS_EQUAL, rhs=1,
                                     name=f"q_constr_dep{depot}_route{i}]")
                else:   # q constraint violate -> add constr of type x <= 0
                    model.addLConstr(lhs=x[depot, i], sense=grb.GRB.LESS_EQUAL, rhs=0,
                                     name=f"q_constr_dep{depot}_route{i}]")


        # 2.3.7 Route selection constraint
        for i in route_ids:
            model.addLConstr(lhs=grb.quicksum(x[depot, i] for depot in depots),
                             sense=grb.GRB.EQUAL,
                             rhs=1,
                             name=f"route_selection_{i}")

        # 2.3.8 No-good cut to prevent obtaining the input solution as output
        # such solutions can be obtained by selecting depot assignments for all non-empty routes that
        # are equal to their initial depot selection
        skip_routes = []
        for index in route_ids:
            # a) Skip routes where selecting the same depot would lead to a repositioning (-> route would change)
            _, _, pos = route_datas[index].depot_dist_swaps[route_datas[index].route[0]]
            if pos != 0:
                skip_routes.append(index)
                break
        # b) Only add the cut if no routes were skipped; only then could the input solution be optimal
        if skip_routes == []:
            nonempty_route_cnt = len([i for i in route_ids if len(route_datas[i].route) >= 3])
            # cut to prevent obtaining the input solution
            model.addLConstr(lhs=grb.quicksum(grb.quicksum(x[depot, i] for i in route_ids if
                                                           (route_datas[i].route[0] == depot and len(route_datas[i].route) >= 3))
                                              for depot in depots), sense=grb.GRB.LESS_EQUAL, rhs=nonempty_route_cnt - 1,
                             name="no_good_cut")

            no_good_cut_is_active = True
        else:   # also add cut (even if trivial) for later iterations
            model.addLConstr(lhs = 0, sense = grb.GRB.LESS_EQUAL, rhs = len(route_ids) - 1, name = "no_good_cut")

        # 2.4. Set variable starts (if no good cut is inactive) or VarHints (if no good cut is active)
        # 2.4.1 Depot variables
        for depot in depots:
            if d[depot] > 0:
                if no_good_cut_is_active:
                    y[depot].VarHintVal = 1
                else:
                    y[depot].Start = 1
        # 2.4.2 Route selection variables
        for i in route_ids:
            if no_good_cut_is_active:
                x[route_datas[i].route[0], i].VarHintVal = 1
            else:
                x[route_datas[i].route[0], i].Start = 1


    # 3. Else: Model was already built, change only parameters (objectives, loads, start solution)
    else:
        # 3.1 Get variables based on original nomenclature
        x_reconstructed = {}
        y_reconstructed = {}
        for var in model.getVars():
            name = var.varName
            if name.startswith("y"):
                index = int(name.split("[")[1].rstrip("]"))
                y_reconstructed[index] = var
            elif name.startswith("x"):
                i = int(name.split(",")[0].lstrip("x["))
                j = int(name.split(",")[1].rstrip("]"))
                x_reconstructed[i, j] = var

        # 3.2 Adjust coefficients
        for depot in depots:
            # 3.2.1 f depot is currently open, add costs and set start value
            if d[depot] > 0:
                current_depot_cost += dc[depot]

            no_nonzero_coeffs = 0   # no. of nonzero coefficients of no good cut
            for i in route_ids:
                # 3.2.2 Make sure swap information from route is available, compute it if is not available
                route_datas[i].update_depot_dist_swaps(new_depot=depot, dm=dm, cm=cm)

                # 3.2.3 Adjust x[depot, i] variable objective value
                x_reconstructed[depot, i].obj = route_datas[i].depot_dist_swaps[depot][0]

                # 3.2.4 Adjust load value for depot capacity constraint
                model.chgCoeff(model.getConstrByName(f"depot_capacity_{depot}"),
                               x_reconstructed[depot, i], route_datas[i].demand)

                # 3.2.5 Adjust dummy constraints for q constraint
                if dm is None:
                    route_distance = route_objf_only_routing(route_datas[i].route, cm)
                else:
                    route_distance = route_objf_only_routing(route_datas[i].route, dm)
                if route_distance + route_datas[i].depot_dist_swaps[depot][1] <= q:
                    model.getConstrByName(f"q_constr_dep{depot}_route{i}]").rhs = 1
                else:  # q constraint violate -> add constr of type x <= 0
                    model.getConstrByName(f"q_constr_dep{depot}_route{i}]").rhs = 0

                # 3.2.6 If route is empty: does not matter for no good cut anyway => set coefficient to 0
                if len(route_datas[i].route) == 2:
                    model.chgCoeff(model.getConstrByName("no_good_cut"), x_reconstructed[depot, i], 0)
                # else: set coefficient to 1 iff. depot position would not change if x[depot, i] was selected
                else:
                    if route_datas[i].route[0] == depot:
                        _, _, pos = route_datas[i].depot_dist_swaps[depot]
                        if pos == 0:
                            model.chgCoeff(model.getConstrByName("no_good_cut"), x_reconstructed[depot, i], 1)
                            no_nonzero_coeffs += 1
                        else:
                            model.chgCoeff(model.getConstrByName("no_good_cut"), x_reconstructed[depot, i], 0)
                    else:
                        model.chgCoeff(model.getConstrByName("no_good_cut"), x_reconstructed[depot, i], 0)

            # 3.3 Get no. of nonempty routes and update RHS
            nonempty_route_cnt = len([i for i in route_ids if len(route_datas[i].route) >= 3])
            model.getConstrByName("no_good_cut").rhs = nonempty_route_cnt - 1

            # 3.4 No good cut only active iff. one nonzero coefficient per route
            if no_nonzero_coeffs == nonempty_route_cnt:
                no_good_cut_is_active = True


        # 3.5 Set variable starts (if no good cut is inactive) or VarHints (if no good cut is active)
        # 3.5.1 depot vars
        for depot in depots:
            if d[depot] > 0:
                if no_good_cut_is_active:
                    y_reconstructed[depot].VarHintVal = 1
                else:
                    y_reconstructed[depot].Start = 1
        # 3.5.2 route selection variables
        for i in route_ids:
            if no_good_cut_is_active:
                x_reconstructed[route_datas[i].route[0], i].VarHintVal = 1
            else:
                x_reconstructed[route_datas[i].route[0], i].Start = 1

    # 4. Set model parameters and solve
    model.setParam("OutputFlag", False)
    model.update()
    model.optimize()

    # 5. Check if an improving solution was found
    try:
        delta_reassign = - current_depot_cost + model.ObjVal
    except: # catch case that no feasible route reassignment was found
        return None, (None, None, None, None)

    # 6. If move was found: unpack and return
    if delta_reassign + OPT_EPS < best_delta:
        # 6.1 Get depot reassignments
        new_swaps = []
        for depot in depots:
            if model.getVarByName(f"y[{depot}]").X > 0.5:
                for i in route_ids:
                    if model.getVarByName(f"x[{depot},{i}]").X > 0.5:
                        new_swaps.append((depot, i))
        # 6.2 Construct return list with None entries except for changed routes at index i
        return_list: list[None or RouteData] = [None for _ in range(len(route_datas))]
        depot_demand_deltas = []
        for new_depot, index in new_swaps:
            # Unpack swaps, route, current cost, and current demand
            delta, delta_dist, pos = route_datas[index].depot_dist_swaps[new_depot]
            route, r_l, r_dist, r_d, _ = route_datas[index]
            # Easier handling for empty routes
            if len(route) <= 2:
                return_list[index] = RouteData([new_depot, new_depot],
                                               r_l + delta,
                                               r_dist + delta_dist,
                                               r_d,
                                               # Transform delta and position for swaps to avoid costly computation
                                               depot_dist_swaps=route_datas[index].depot_dist_swaps.copy())

            else:
                return_list[index] = RouteData([new_depot] + route[pos + 1:-1] + route[1:pos + 1] + [new_depot],
                                               r_l + delta,
                                               r_dist + delta_dist,
                                               r_d,
                                               # Transform delta and position for swaps to avoid costly computation
                                               depot_dist_swaps={d: (diff - delta, diff_dist - delta_dist, (position - pos) % (len(route) - 2))
                                                            for d, (diff, diff_dist, position) in
                                                            route_datas[index].depot_dist_swaps.items()})
            # Adjust depot demand
            depot_demand_deltas += [(route[0], - r_d), (new_depot, + r_d)]

        # 6.3 Check if routes were reassigned -> If not, then a numerical error happened and we will return None
        if not return_list == [None for _ in range(len(route_datas))]:
            return model, (return_list,
                           depot_demand_deltas,
                           None,
                           delta_reassign)
    return None, (None, None, None, None)
