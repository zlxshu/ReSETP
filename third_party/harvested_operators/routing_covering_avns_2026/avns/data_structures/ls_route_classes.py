"""Classes for routes used in local search algorithms.

These classes store routing information and auxiliary data needed for efficient
constraint checking and move computation. All classes are designed for local
search operations only and do not contain customer covering information.

# The RouteData class proposed in this file are adapted from VeRyPy
# (https://github.com/yorak/VeRyPy), by Jussi Rasku, under the MIT License.
# Original copyright (c) 2021 Jussi Rasku. All rights reserved.
Adjustments and extensions have been made to account for the peculiarities of the underlying problem, which include:
rejection of nonchanging moves, acceptance of non-improving moves, inclusion of covering cost, and inclusion of
additional capacity and route length restrictions."""

from avns.utils.route_util import route_objf, route_objf_only_routing


class RouteData:
    """Route data structure with auxiliary information for local search.

    Stores a single route (sequence of nodes) along with its cost, distance,
    and demand. Provides lazy-computed auxiliary data such as forward/backward
    demand and distance prefixes to enable O(1) constraint checks during
    neighborhood evaluation.

    Parameters
    ----------
    route : list of int or None
        Node sequence [depot, facility_1, ..., facility_k, depot].
        When None, an empty route [depot, depot] is created.
    cost : float, optional
        Current total route cost (default: 0.0).
    distance : float, optional
        Current total route distance (default: 0.0).
    demand : float, optional
        Total demand served by the route (default: 0.0).
    node_set : set or None, optional
        Set of all non-depot nodes in the route (default: None).
    generate_node_set : bool, optional
        When True, compute node_set from the input route (default: False).
    depot_dist_swaps : dict or None, optional
        Pre-computed depot swap costs; maps depot ID to (cost_delta,
        distance_delta, best_position) triples (default: None).
    """

    def __init__(self, route=None, cost=0.0, distance=0.0, demand=0.0, node_set=None,
                 generate_node_set=False, depot_dist_swaps=None):
        # 1. Extract depot from route and validate cycle structure
        depot = route[0] if (route is not None) else None
        assert route[-1] == depot, f"Route {route} is not a cycle"
        self.depot = depot

        # 2. Store route (or empty route if none provided)
        self.route = [depot, depot] if (route is None) else route

        # 3. Store route metrics
        self.cost = cost
        self.distance = distance
        self.demand = demand
        self.node_set = node_set
        self.aux_data_updated = False

        # 4. Initialize prefix arrays for forward/backward demand and distance
        self.fwd_d = None
        self.rwd_d = None
        self.fwd_dist = None
        self.rwd_dist = None

        # 5. Initialize depot swap information (lazy-computed per depot)
        self.depot_dist_swaps = depot_dist_swaps if depot_dist_swaps is not None else {}
        self.depot_dist_swaps[depot] = (0, 0, 0)

        # 6. Generate node set if requested
        if generate_node_set:
            assert route is not None, "No route to generate it from"
            self.node_set = RouteData._route_to_nodeset(route, depot)

    def __str__(self):
        """Return a human-readable string representation of the route."""
        return "%s (demand=%.2f, cost=%.2f)" % (self.route, self.demand, self.cost)

    def __iter__(self):
        """Enable unpacking of RouteData into (route, cost, distance, demand, node_set)."""
        for e in (self.route, self.cost, self.distance, self.demand, self.node_set):
            yield e

    def __getitem__(self, i):
        """Enable indexed access to route components.

        Parameters
        ----------
        i : int
            Index: 0=route, 1=cost, 2=distance, 3=demand, 4=node_set.

        Returns
        -------
        Value at index i, or raises IndexError if i > 4.
        """
        if i == 0:
            return self.route
        elif i == 1:
            return self.cost
        elif i == 2:
            return self.distance
        elif i == 3:
            return self.demand
        elif i == 4:
            return self.node_set
        else:
            raise IndexError("0=route, 1=cost, 2=distance, 3=demand, 4=node_set (can be None)")

    def _canonical_route(self):
        """Return route in canonical form for consistent comparison.

        Routes are normalized by reversing when the first visited facility has
        a higher index than the last visited facility. This enables checking
        whether two routes are identical regardless of traversal direction.

        Returns
        -------
        list
            The route or its reverse, whichever is lexicographically smaller.
        """
        # 1. Compute reverse route
        rev = self.route[::-1]

        # 2. Return canonical ordering (smaller lexicographically)
        return self.route if self.route <= rev else rev

    def unique_identifier(self):
        """Compute a unique hash identifier for the route.

        Returns
        -------
        int
            Hash of the route's canonical form (tuple of node sequence).
        """
        # 1. Compute canonical route if not cached
        if not hasattr(self, "canonical_route"):
            self.canonical_route = self._canonical_route()

        # 2. Return hash of canonical tuple
        return hash(tuple(self.canonical_route))

    def update_auxiliary_data(self, dm, cm, d, direction=None):
        """Compute prefix demand and distance arrays for constraint checks.

        Populates forward (fwd_d, fwd_dist) and/or backward (rwd_d, rwd_dist)
        prefix arrays. These enable O(1) lookups of cumulative demand and
        distance along route segments, avoiding O(k) recomputation during
        move evaluations.

        Parameters
        ----------
        dm : 2D array-like or None
            Distance matrix. When None, cm is used for both distances.
        cm : 2D array-like
            Cost matrix.
        d : array-like or None
            Demand at each node. When None, no demand prefix is computed.
        direction : int or None, optional
            Direction to compute: 1 for forward, -1 for backward, None for both.
        """
        # 1. Recursively compute both directions if direction is None
        if not direction:
            self.update_auxiliary_data(dm, cm, d, direction=1)
            self.update_auxiliary_data(dm, cm, d, direction=-1)
            return

        # 2. Initialize cumulative arrays
        route_d = [0.0] * len(self.route)
        route_dist = [0.0] * len(self.route)
        cum_d = 0.0
        cum_dist = 0.0

        # 3. Start from first (forward) or second-to-last (backward) facility
        start_i = 1 if direction == 1 else -2
        i = start_i

        # 4. Accumulate distances and demands along route direction
        for n in self.route[start_i::direction]:
            if d:
                # 5. Accumulate distance between consecutive nodes
                if dm is None:
                    cum_dist += cm[self.route[i - direction], self.route[i]]
                else:
                    cum_dist += dm[self.route[i - direction], self.route[i]]
                route_dist[i] = cum_dist

                # 6. Accumulate demand only for non-depot nodes
                if not n == self.depot:
                    cum_d += d[n]
                    route_d[i] = cum_d
                else:
                    # 7. Depot does not contribute to demand
                    route_d[i] = cum_d
            i += direction

        # 8. Store in appropriate direction-specific attribute
        if direction > 0:
            self.fwd_d = route_d
            self.fwd_dist = route_dist
        elif direction < 0:
            self.rwd_d = route_d
            self.rwd_dist = route_dist

    def update_depot_dist_swaps(self, new_depot: int, dm, cm):
        """Pre-compute cost delta for swapping to a different depot.

        Computes the cheapest way to change the route's depot to new_depot and
        caches the result. Results are reused on subsequent calls (lazy evaluation).

        Parameters
        ----------
        new_depot : int
            Depot index to evaluate as a replacement.
        dm : 2D array-like or None
            Distance matrix. When None, cm is used instead.
        cm : 2D array-like
            Cost matrix.
        """
        # 1. Compute and cache depot swap cost if not already computed
        if new_depot not in self.depot_dist_swaps.keys():
            self.depot_dist_swaps[new_depot] = RouteData.compute_new_depot_cost(
                self, new_depot=new_depot, dm=dm, cm=cm)

    @staticmethod
    def _route_to_nodeset(route, depot):
        """Extract the set of visiting (non-depot) nodes from a route.

        Parameters
        ----------
        route : list
            Route node sequence [depot, ..., facilities, ..., depot].
        depot : int
            Depot node ID.

        Returns
        -------
        set
            Set of all facility (non-depot) nodes in the route.
            Empty set if route is empty or contains only depots.
        """
        # 1. Return empty set for empty routes
        if not route or route == [depot, depot]:
            return set()

        # 2. Skip leading depot repetitions
        start_from = 0
        while route[start_from] == depot and start_from < len(route) - 1:
            start_from += 1

        # 3. Skip trailing depot repetitions
        if route[-1] == depot:
            end_to = -2
            while route[end_to] == depot and abs(end_to) < len(route):
                end_to -= 1
            r_nodes = set(route[start_from:end_to + 1])
        else:
            r_nodes = set(route[start_from:])

        return r_nodes

    @staticmethod
    def from_routes_with_hashes(routes, hashes, dm, cm, d, cas, ccc):
        """Construct RouteData objects from routes and pre-computed hashes.

        Parameters
        ----------
        routes : list of list
            List of route node sequences.
        hashes : list of int
            Pre-computed hash for each route (unique identifier).
        dm : 2D array-like or None
            Distance matrix.
        cm : 2D array-like
            Cost matrix.
        d : array-like
            Demand at each node.
        cas : list of dict
            Customer assignment dict for each route.
        ccc : float
            Cost coefficient for customer covering.

        Returns
        -------
        list of RouteData
            RouteData objects corresponding to input routes.
        """
        route_datas = []

        # 1. Convert each route to a RouteData object
        for i in range(len(routes)):
            r = routes[i]
            h = hashes[i]
            ca = cas[i]

            # 2. Compute route cost
            r_cost = route_objf(r, cm, ca, ccc)

            # 3. Compute route distance
            if dm is not None:
                r_distance = route_objf_only_routing(r, dm)
            else:
                r_distance = route_objf_only_routing(r, cm)

            # 4. Compute route demand (sum of node demands on route)
            r_demand = sum(d[node] for node in r[1:-1]) if d else 0

            # 5. Extract node set (non-depot nodes)
            r_nodes = RouteData._route_to_nodeset(r, r[0])

            # 6. Create and store RouteData object
            route_datas.append(RouteData(r, r_cost, r_distance, r_demand, r_nodes))
            route_datas[-1].hash = h

        return route_datas

    @staticmethod
    def compute_new_depot_cost(route_data, new_depot, dm, cm):
        """Compute cost delta for changing a route's depot.

        Evaluates all possible positions where new_depot can be inserted into
        the current route and returns the best (least-cost) option.

        Parameters
        ----------
        route_data : RouteData
            Current route to evaluate.
        new_depot : int
            Depot to evaluate as a replacement.
        dm : 2D array-like or None
            Distance matrix. When None, cm is used instead.
        cm : 2D array-like
            Cost matrix.

        Returns
        -------
        tuple
            (cost_delta, distance_delta, best_position) where:
            - cost_delta: objective change from depot swap.
            - distance_delta: distance change from depot swap.
            - best_position: index where new_depot achieves lowest cost.
        """
        # 1. Unpack route data
        route, r_l, r_dist, r_d, _ = route_data

        # 2. Extract current depot and boundary nodes
        old_depot = route[0]
        pre_old_depot = route[-2]
        after_old_depot = route[1]

        # 3. Compute cost of replacing depot at position 0
        # Current: [..., pre_old_depot, old_depot, after_old_depot, ...]
        # New:     [..., pre_old_depot, new_depot, after_old_depot, ...]
        best_delta = (cm[new_depot, after_old_depot] + cm[pre_old_depot, new_depot]
                      - cm[old_depot, after_old_depot] - cm[pre_old_depot, old_depot])

        # 4. Compute corresponding distance delta
        if dm is None:
            best_delta_dist = best_delta
        else:
            best_delta_dist = (dm[new_depot, after_old_depot] + dm[pre_old_depot, new_depot]
                              - dm[old_depot, after_old_depot] - dm[pre_old_depot, old_depot])

        best_position = 0

        # 5. For routes with >= 3 facility nodes, also try relocating depot to other positions
        if len(route) >= 5:
            # 6. Compute cost of removing old_depot from position 0
            # Current: [..., pre_old_depot, old_depot, after_old_depot, ...]
            # No depot: [..., pre_old_depot, after_old_depot, ...]
            delta_removal = (cm[pre_old_depot, after_old_depot]
                           - cm[old_depot, after_old_depot] - cm[pre_old_depot, old_depot])

            if dm is None:
                delta_dist_removal = delta_removal
            else:
                delta_dist_removal = (dm[pre_old_depot, after_old_depot]
                                    - dm[old_depot, after_old_depot] - dm[pre_old_depot, old_depot])

            # 7. Try inserting new_depot at each position in the route
            for i in range(1, len(route) - 2):
                a = route[i]
                b = route[i + 1]

                # 8. Compute cost of insertion at position i
                # Current: [..., a, b, ...]
                # New:     [..., a, new_depot, b, ...]
                delta = (cm[a, new_depot] + cm[new_depot, b] - cm[a, b] + delta_removal)

                if dm is None:
                    delta_dist = delta
                else:
                    delta_dist = (dm[a, new_depot] + dm[new_depot, b] - dm[a, b] + delta_dist_removal)

                # 9. Update best option if this position is cheaper
                if delta < best_delta:
                    best_delta = delta
                    best_delta_dist = delta_dist
                    best_position = i

        return best_delta, best_delta_dist, best_position
