"""Explicit artificial fixtures for the isolated nonlinear-charging prototype."""

from __future__ import annotations

from prototype import (
    ChargeAction,
    ChargeOpportunity,
    FixedRouteCase,
    ObjectiveCoefficients,
    PiecewiseLinearCurve,
    RouteLeg,
    TimeSignals,
)


def conflict_micro_route() -> FixedRouteCase:
    """Return a hand-auditable route with two charging opportunities.

    Every number is an artificial test fixture.  It is not a China parameter,
    a formal discretization choice, or a proposed carbon-price weight.
    """

    return FixedRouteCase(
        case_id="ARTIFICIAL_CONFLICT_TWO_CHARGERS",
        initial_time_seconds=0.0,
        initial_soc_kwh=6.0,
        terminal_min_soc_kwh=1.0,
        curve=PiecewiseLinearCurve(
            energy_kwh=(0.0, 6.0, 10.0),
            cumulative_seconds=(0.0, 720.0, 1440.0),
        ),
        signals=TimeSignals(
            boundaries_seconds=tuple(float(value) for value in range(0, 12_601, 900)),
            price_per_kwh=(
                1.0,
                1.0,
                0.4,
                0.4,
                1.2,
                1.2,
                0.5,
                0.5,
                1.1,
                1.1,
                0.6,
                0.6,
                0.9,
                0.9,
            ),
            carbon_per_kwh=(
                0.2,
                0.2,
                1.0,
                1.0,
                0.3,
                0.3,
                1.1,
                1.1,
                0.4,
                0.4,
                0.9,
                0.9,
                0.5,
                0.5,
            ),
        ),
        objective=ObjectiveCoefficients(price=1.0, carbon=0.25),
        legs=(
            RouteLeg(
                name="customer_1",
                travel_seconds=600.0,
                drive_energy_kwh=3.0,
                service_window=(600.0, 1_200.0),
                service_seconds=300.0,
                charge_after_service=ChargeOpportunity(
                    latest_finish_seconds=3_600.0,
                    actions=(
                        ChargeAction(target_soc_kwh=6.0, wait_seconds=0.0),
                        ChargeAction(target_soc_kwh=6.0, wait_seconds=900.0),
                        ChargeAction(target_soc_kwh=8.0, wait_seconds=0.0),
                        ChargeAction(target_soc_kwh=8.0, wait_seconds=900.0),
                    ),
                ),
            ),
            RouteLeg(
                name="customer_2",
                travel_seconds=900.0,
                drive_energy_kwh=4.0,
                service_window=(2_100.0, 5_400.0),
                service_seconds=300.0,
                charge_after_service=ChargeOpportunity(
                    latest_finish_seconds=7_200.0,
                    actions=(
                        ChargeAction(target_soc_kwh=7.0, wait_seconds=0.0),
                        ChargeAction(target_soc_kwh=7.0, wait_seconds=900.0),
                        ChargeAction(target_soc_kwh=9.0, wait_seconds=0.0),
                        ChargeAction(target_soc_kwh=9.0, wait_seconds=900.0),
                    ),
                ),
            ),
            RouteLeg(
                name="terminal",
                travel_seconds=1_200.0,
                drive_energy_kwh=6.0,
                service_window=(0.0, 12_600.0),
                service_seconds=0.0,
                charge_after_service=None,
            ),
        ),
        comparison_tolerance=1e-9,
    )

