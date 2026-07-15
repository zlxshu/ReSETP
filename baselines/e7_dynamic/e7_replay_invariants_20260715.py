#!/usr/bin/env python3
"""Hard invariants for the E7 zero-search charging replay."""

from __future__ import annotations

from math import isfinite
from typing import Any, Mapping, Sequence

from setp_solver.check import _check_station_capacity


DAY_SECONDS = 86_400.0
TOL = 1e-9


def charging_window_boundary_violations(
    witnesses: Sequence[Mapping[str, Any]],
    trigger_seconds: Sequence[float],
) -> list[str]:
    """Return violations of the frozen rolling-state charging boundaries."""

    violations: list[str] = []
    for index, witness in enumerate(witnesses):
        prefix = f"witness[{index}]"
        try:
            capture_stage = int(witness["capture_stage"])
            lock_state = str(witness["lock_state"])
            day_offset = int(witness["charge_day_offset"])
            observed = float(witness["observed_start_second"])
            earliest = float(witness["earliest_start_second"])
            latest = float(witness["latest_start_second"])
            duration = float(witness["occupancy_minutes"]) * 60.0
            energy = float(witness["energy_kwh"])
        except (KeyError, TypeError, ValueError) as exc:
            violations.append(f"{prefix}: incomplete witness ({exc})")
            continue
        numeric = (observed, earliest, latest, duration, energy)
        if not all(isfinite(value) for value in numeric):
            violations.append(f"{prefix}: non-finite witness value")
            continue
        if duration <= 0.0 or energy <= 0.0:
            violations.append(f"{prefix}: non-positive charging quantity")
        if earliest > latest + TOL:
            violations.append(f"{prefix}: empty charging window")
        if observed < earliest - TOL or observed > latest + TOL:
            violations.append(f"{prefix}: observed action outside charging window")

        if lock_state == "completed_before_trigger":
            if capture_stage < 1 or capture_stage > len(trigger_seconds):
                violations.append(f"{prefix}: capture stage has no trigger")
                continue
            absolute_earliest = earliest + day_offset * DAY_SECONDS
            absolute_latest_end = latest + duration + day_offset * DAY_SECONDS
            current_trigger = float(trigger_seconds[capture_stage - 1])
            if absolute_latest_end > current_trigger + TOL:
                violations.append(f"{prefix}: charging window ends after current trigger")
            if capture_stage > 1:
                previous_trigger = float(trigger_seconds[capture_stage - 2])
                if absolute_earliest < previous_trigger - TOL:
                    violations.append(
                        f"{prefix}: charging window crosses previous trigger"
                    )
        elif lock_state == "in_progress_at_trigger_fixed":
            if abs(earliest - observed) > TOL or abs(latest - observed) > TOL:
                violations.append(f"{prefix}: in-progress action is not fixed")
        elif lock_state != "future_after_final_stage":
            violations.append(f"{prefix}: unknown lock state {lock_state}")
    return violations


def station_capacity_violation_count(solution: Any, instance: Any) -> int:
    """Count shared station/depot charger-capacity violations."""

    node_lookup = {node.node_id: node for node in instance.nodes}
    return len(_check_station_capacity(solution, node_lookup, instance))
