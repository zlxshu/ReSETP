from types import MappingProxyType

from setp_solver.algorithms.problem_hgs.dynamic import (
    DutyDynamicState,
    _merge_execution_history,
)
from setp_solver.search.dynamic_multitrip_schedule import (
    CertificateCut,
    DynamicAssetState,
)
from setp_solver.solution import Route, Solution


def _route(route_id: str, customer: str) -> Route:
    return Route(route_id, "cv", "D0", ["D0", customer, "D0"])


def test_multistage_merge_keeps_earlier_and_current_committed_routes() -> None:
    asset = DynamicAssetState("CV_D0_1", "cv", "D0", 10.0, 0.0, 2)
    state = DutyDynamicState(
        source_solution=Solution(
            routes=[_route("CV_D0_1#T2", "C2"), _route("CV_D0_1#T3", "C3")]
        ),
        cut=CertificateCut(
            trigger_second=10.0,
            completed_route_ids=("CV_D0_1#T2",),
            in_progress_route_ids=(),
            editable_route_ids=("CV_D0_1#T3",),
            locked_charging_actions=(),
            asset_states=MappingProxyType({"CV_D0_1": asset}),
        ),
        asset_states=MappingProxyType({"CV_D0_1": asset}),
        future_customer_ids=frozenset({"C3"}),
        customer_appearance_second={"C1": 0.0, "C2": 0.0, "C3": 0.0},
        charging_strategy="aware",
        charging_intensity_field="forecast_gco2_per_kwh",
        prior_committed_solution=Solution(
            routes=[_route("CV_D0_1#T1", "C1")]
        ),
    )

    merged = _merge_execution_history(
        state,
        Solution(routes=[_route("CV_D0_1#T3", "C3")]),
    )

    assert [route.vehicle_id for route in merged.routes] == [
        "CV_D0_1#T1",
        "CV_D0_1#T2",
        "CV_D0_1#T3",
    ]


def test_multistage_state_rejects_route_identity_overlap() -> None:
    asset = DynamicAssetState("CV_D0_1", "cv", "D0", 10.0, 0.0, 2)
    try:
        DutyDynamicState(
            source_solution=Solution(routes=[_route("CV_D0_1#T2", "C2")]),
            cut=CertificateCut(
                trigger_second=10.0,
                completed_route_ids=(),
                in_progress_route_ids=(),
                editable_route_ids=("CV_D0_1#T2",),
                locked_charging_actions=(),
                asset_states=MappingProxyType({"CV_D0_1": asset}),
            ),
            asset_states=MappingProxyType({"CV_D0_1": asset}),
            future_customer_ids=frozenset({"C2"}),
            customer_appearance_second={"C2": 0.0},
            charging_strategy="aware",
            charging_intensity_field="forecast_gco2_per_kwh",
            prior_committed_solution=Solution(
                routes=[_route("CV_D0_1#T2", "C1")]
            ),
        )
    except ValueError as error:
        assert "overlap earlier committed history" in str(error)
    else:
        raise AssertionError("overlapping dynamic history was accepted")
