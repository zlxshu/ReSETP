from __future__ import annotations

import importlib
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
    """Load the pure proxy helper without requiring the compiled PyVRP wheel."""

    importlib.import_module("setp_solver.algorithms")
    duty_hgs_package = _module("setp_solver.algorithms.duty_hgs")
    duty_hgs_package.__path__ = [
        str(SOLVER_SRC / "setp_solver/algorithms/duty_hgs")
    ]
    stub_names = {
        "setp_solver.algorithms.duty_hgs": duty_hgs_package,
        "pyvrp": _module(
            "pyvrp",
            Model=object,
            Route=object,
            Solution=object,
            Trip=object,
        ),
        "pyvrp._pyvrp": _module(
            "pyvrp._pyvrp",
            RandomNumberGenerator=object,
        ),
        "pyvrp.PenaltyManager": _module(
            "pyvrp.PenaltyManager",
            PenaltyManager=object,
        ),
        "pyvrp.search": _module(
            "pyvrp.search",
            LocalSearch=object,
            compute_neighbours=lambda *_args, **_kwargs: (),
        ),
        "pyvrp.solve": _module(
            "pyvrp.solve",
            SolveParams=object,
        ),
    }
    previous = {name: sys.modules.get(name) for name in stub_names}
    sys.modules.update(stub_names)
    module_name = (
        "setp_solver.algorithms.duty_hgs._pyvrp_proposals_fixed_cost_test"
    )
    path = SOLVER_SRC / "setp_solver/algorithms/duty_hgs/pyvrp_proposals.py"
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


def test_duty_hgs_proxy_reads_cv_170_ev_220_from_vehicle_authority() -> None:
    from setp_solver.china81 import load_china81_bundle

    class RecordingModel:
        latest = None

        def __init__(self):
            self.vehicle_types = []
            RecordingModel.latest = self

        def add_depot(self, *_args, **kwargs):
            return len(kwargs.get("name", "")), kwargs.get("name")

        def add_client(self, *_args, **kwargs):
            return len(kwargs.get("name", "")), kwargs.get("name")

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
    context = SimpleNamespace(bundle=bundle, dynamic_state=None)

    proxy_module._build_unique_asset_problem(context, fleet)

    fixed_costs = {
        row["name"]: row["fixed_cost"]
        for row in RecordingModel.latest.vehicle_types
    }
    assert fixed_costs == {
        "CV1": proxy_module._money_units(170.0),
        "EV1": proxy_module._money_units(220.0),
    }
