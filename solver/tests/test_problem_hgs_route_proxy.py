from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


SOLVER_SRC = Path(__file__).resolve().parents[1] / "src"
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOLVER_SRC))


def _module(name: str, **attributes) -> ModuleType:
    module = ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


def _load_route_proxy_module():
    """Load the pure proxy helper without requiring the compiled test kernel."""

    importlib.import_module("setp_solver.algorithms")
    problem_hgs_package = _module("setp_solver.algorithms.problem_hgs")
    problem_hgs_package.__path__ = [
        str(SOLVER_SRC / "setp_solver/algorithms/problem_hgs")
    ]
    stub_names = {
        "setp_solver.algorithms.problem_hgs": problem_hgs_package,
        "setp_hgs_kernel": _module(
            "setp_hgs_kernel",
            Model=object,
            Route=object,
            Solution=object,
            Trip=object,
            __version__="0.12.2",
        ),
        "setp_hgs_kernel._setp_hgs_kernel": _module(
            "setp_hgs_kernel._setp_hgs_kernel",
            RandomNumberGenerator=object,
        ),
        "setp_hgs_kernel.PenaltyManager": _module(
            "setp_hgs_kernel.PenaltyManager",
            PenaltyManager=object,
        ),
        "setp_hgs_kernel.search": _module(
            "setp_hgs_kernel.search",
            DepotSplit=object,
            LocalSearch=object,
            compute_neighbours=lambda *_args, **_kwargs: (),
        ),
        "setp_hgs_kernel.solve": _module(
            "setp_hgs_kernel.solve",
            SolveParams=object,
        ),
    }
    previous = {name: sys.modules.get(name) for name in stub_names}
    sys.modules.update(stub_names)
    module_name = (
        "setp_solver.algorithms.problem_hgs._kernel_proposals_route_proxy_test"
    )
    path = SOLVER_SRC / "setp_solver/algorithms/problem_hgs/kernel_proposals.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = loaded
    try:
        spec.loader.exec_module(loaded)
    finally:
        sys.modules.pop(module_name, None)
        for name, original in previous.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    return loaded


class _RouteOnlyInstance:
    def vehicle_profile(self, _vehicle_type: str):
        return SimpleNamespace(payload_capacity_kg=1000.0)

    def arc_metrics(self, *_args, **_kwargs):
        return (2000.0, 120.0, 0.0)

    def non_energy_distance_cost_per_km(self, *_args, **_kwargs):
        return 2.5


def test_route_only_proxy_excludes_propulsion_and_carbon() -> None:
    proxy_module = _load_route_proxy_module()
    context = SimpleNamespace(
        bundle=SimpleNamespace(
            instance=_RouteOnlyInstance(),
            prices=SimpleNamespace(v_speed_ms=10.0, c_km=9.0),
        )
    )

    units = proxy_module._route_proxy_cost_units(
        context,
        "D1",
        "C1",
        vehicle_type="ev",
        depot_id="D1",
        ev_unit_cost=None,
        include_propulsion_proxy=False,
    )

    assert units == proxy_module._money_units(5.0)


def test_route_proxy_reads_cv_170_ev_220_from_vehicle_authority() -> None:
    from setp_solver.china81 import load_china81_bundle

    class RecordingModel:
        latest = None

        def __init__(self):
            self.vehicle_types = []
            RecordingModel.latest = self

        def add_depot(self, *_args, **_kwargs):
            return len(_kwargs.get("name", "")), _kwargs.get("name")

        def add_client(self, *_args, **_kwargs):
            return len(_kwargs.get("name", "")), _kwargs.get("name")

        def add_profile(self, **kwargs):
            return kwargs["name"]

        def add_edge(self, *_args, **_kwargs):
            return None

        def add_vehicle_type(self, **kwargs):
            self.vehicle_types.append(kwargs)

        def data(self):
            return self

    proxy_module = _load_route_proxy_module()
    proxy_module.Model = RecordingModel
    bundle = load_china81_bundle(
        REPO_ROOT,
        "cn-prd-10c-01-V2-LOCATIONS",
    )
    depot = next(
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "d"
    )
    fleet = SimpleNamespace(
        duties=(
            SimpleNamespace(
                physical_vehicle_id="CV1",
                vehicle_type="cv",
                home_depot_id=depot,
                trips=(),
            ),
            SimpleNamespace(
                physical_vehicle_id="EV1",
                vehicle_type="ev",
                home_depot_id=depot,
                trips=(),
            ),
        )
    )
    context = SimpleNamespace(
        bundle=bundle,
        dynamic_state=None,
        rebuilt_route_constraints=None,
    )

    proxy_module._build_unique_asset_problem(
        context,
        fleet,
        include_propulsion_proxy=False,
    )

    fixed_costs = {
        row["name"]: row["fixed_cost"]
        for row in RecordingModel.latest.vehicle_types
    }
    assert fixed_costs == {
        "CV1": proxy_module._money_units(170.0),
        "EV1": proxy_module._money_units(220.0),
    }


def test_problem_hgs_context_reports_premium_without_adding_it_twice() -> None:
    from setp_solver.china81 import load_china81_bundle
    from setp_solver.cost import evaluate
    from setp_solver.solution import Route, Solution

    _load_route_proxy_module()
    evaluation_module = sys.modules[
        "setp_solver.algorithms.problem_hgs.evaluation"
    ]
    bundle = load_china81_bundle(
        REPO_ROOT,
        "cn-prd-10c-01-V2-LOCATIONS",
    )
    depot = next(
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "d"
    )
    customer = next(
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    )
    solution = Solution(
        routes=[Route("EV1", "ev", depot, [depot, customer, depot])]
    )
    context = SimpleNamespace(
        bundle=bundle,
        ev_daily_fixed_premium_cny=50.0,
    )

    direct = evaluate(
        solution,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    )
    wrapped = evaluation_module._evaluate_with_context_cost(
        solution,
        context,
        carbon_quota_kg=0.0,
    )

    assert direct["cost_fix"] == 220.0
    assert wrapped["cost_fix_ev_premium"] == 50.0
    assert wrapped["cost_fix"] == direct["cost_fix"]
    assert wrapped["total_cost"] == direct["total_cost"]
