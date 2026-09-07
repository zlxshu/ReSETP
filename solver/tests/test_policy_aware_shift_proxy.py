"""Truth table for the policy-aware shift-aware EV route proxy (A1/A2/A4).

Every expected number here was recomputed on 2026-09-05 against the three
tariff/carbon calendars actually used by the private technical line; none is
copied from a design note.  The proxy price of a window is
``depot_energy_cny_per_kwh + actual_gco2_per_kwh / 1000 * carbon_price``
evaluated at the slot the arm's charge-timing policy would choose.

The point of the change under test: before it, both arms of the charge-timing
experiment priced EV arcs from one fixed key (lowest carbon, ties to the
LATEST slot), so the timing mechanism could not reach the route search.  Now
the key is the arm's own policy.  ``charge_timing_policy=None`` must keep the
historical key verbatim, which is what protects every other caller.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from setp_solver.algorithms.problem_hgs.kernel_proposals import (
    _rebuilt_shift_aware_ev_unit_costs,
)
from setp_solver.cost import time_profile_rows_for_node

REPO = Path(__file__).resolve().parents[2]
INSTANCE_ID = "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd"
DATA = REPO / "data/ChinaInstances"

CALENDARS = {
    "beijing_v4": None,  # the registered default authority
    "midday_valley": DATA / "china81_cf_calendar_midday_valley_v1_20260904",
    "uniform": DATA / "china81_cf_calendar_uniform_v1_20260904",
}

AM = "AM"
PM = "PM"
TOL = 1e-6

# --- D.1a: the historical key, which `charge_timing_policy=None` must keep ---
HISTORICAL_PROXY = {
    ("beijing_v4", AM): 0.68026575,
    ("beijing_v4", PM): 1.18154175,
    ("midday_valley", AM): 0.95342275,
    ("midday_valley", PM): 0.59620575,
    ("uniform", AM): 0.96643008,
    ("uniform", PM): 0.88237008,
}
# the historical tie-break takes the LATEST slot: 390 min / 750 min
HISTORICAL_SLOT_SECOND = {AM: 23400.0, PM: 45000.0}

# --- D.1b/c/d: the policy-aware keys ---
POLICY_PROXY = {
    ("beijing_v4", "asap", AM): 0.69194575,
    ("beijing_v4", "asap", PM): 1.18460175,
    ("beijing_v4", "cost_plus_carbon", AM): 0.68026575,
    ("beijing_v4", "cost_plus_carbon", PM): 1.18154175,
    ("midday_valley", "asap", AM): 0.96510275,
    ("midday_valley", "asap", PM): 1.18460175,
    ("midday_valley", "cost_plus_carbon", AM): 0.68202575,
    ("midday_valley", "cost_plus_carbon", PM): 0.59620575,
    ("uniform", "asap", AM): 0.97811008,
    ("uniform", "asap", PM): 0.88543008,
    ("uniform", "cost_plus_carbon", AM): 0.96643008,
    ("uniform", "cost_plus_carbon", PM): 0.88237008,
}


def _runtime():
    import importlib.util
    import sys

    name = "resetp_private_runtime_for_proxy_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, REPO / "solver/scripts/run_problem_hgs_private_technical.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _context(calendar_key: str, carbon_price: float = 0.2):
    runtime = _runtime()
    bundle, _initial, _np, context = runtime._build_context(
        REPO,
        INSTANCE_ID,
        fleet_parameters=runtime.FLEET_PARAMETER_CLASSES["endogenous"],
        tariff_calendar_authority=CALENDARS[calendar_key],
    )
    bundle = replace(
        bundle,
        prices=replace(bundle.prices, carbon_price=carbon_price),
        carbon_price_cny_per_kg=carbon_price,
    )
    return replace(context, bundle=bundle)


DEPOT_NODE_TYPE = "d"


def _depot_ids(context) -> list[str]:
    """The instance's depot nodes (node_type 'd'); expected to be exactly 2."""
    ids = sorted(
        node.node_id
        for node in context.bundle.instance.nodes
        if str(node.node_type) == DEPOT_NODE_TYPE
    )
    assert len(ids) == 2, f"expected 2 depots, found {ids}"
    return ids


def _rates(context, depot_id: str, policy):
    rows = time_profile_rows_for_node(
        context.bundle.instance, depot_id, context.bundle.time_profile
    )
    assert rows, f"no depot time-profile rows for {depot_id}"
    return _rebuilt_shift_aware_ev_unit_costs(
        context, rows, charge_timing_policy=policy
    )


@pytest.fixture(scope="module")
def contexts():
    return {key: _context(key) for key in CALENDARS}


@pytest.mark.parametrize("calendar_key", sorted(CALENDARS))
def test_default_policy_keeps_the_historical_window_prices(
    contexts, calendar_key
):
    """D.1a: no declared policy => the pre-change key, value AND slot."""
    context = contexts[calendar_key]
    depots = _depot_ids(context)
    assert depots, "the DEPOTSEARCH instance must expose depots"
    for depot_id in depots:
        rates = _rates(context, depot_id, None)
        assert set(rates) == {AM, PM}
        for shift_id in (AM, PM):
            assert rates[shift_id]["proxy_cny_per_kwh"] == pytest.approx(
                HISTORICAL_PROXY[(calendar_key, shift_id)], abs=TOL
            )
            assert rates[shift_id][
                "selected_slot_start_second"
            ] == pytest.approx(HISTORICAL_SLOT_SECOND[shift_id], abs=TOL)


@pytest.mark.parametrize("calendar_key", sorted(CALENDARS))
@pytest.mark.parametrize("policy", ["asap", "cost_plus_carbon"])
def test_each_policy_prices_its_own_window(contexts, calendar_key, policy):
    """D.1b/c/d: the two live arm policies, on all three calendars."""
    context = contexts[calendar_key]
    for depot_id in _depot_ids(context):
        rates = _rates(context, depot_id, policy)
        for shift_id in (AM, PM):
            assert rates[shift_id]["proxy_cny_per_kwh"] == pytest.approx(
                POLICY_PROXY[(calendar_key, policy, shift_id)], abs=TOL
            )


def test_beijing_cost_plus_carbon_keeps_its_price_but_moves_its_slot(contexts):
    """D.1c: the tie-break flip is visible in the slot, not in the price.

    Beijing's 360 and 390 min slots carry the same tariff and the same carbon
    intensity, so switching the tie from latest to earliest (aligning with the
    exact timer) is bit-neutral on the price and only renames the slot.
    """
    context = contexts["beijing_v4"]
    for depot_id in _depot_ids(context):
        rates = _rates(context, depot_id, "cost_plus_carbon")
        assert rates[AM]["proxy_cny_per_kwh"] == pytest.approx(
            HISTORICAL_PROXY[("beijing_v4", AM)], abs=TOL
        )
        assert rates[PM]["proxy_cny_per_kwh"] == pytest.approx(
            HISTORICAL_PROXY[("beijing_v4", PM)], abs=TOL
        )
        # ... while the recorded slot moves 390 -> 360 min and 750 -> 720 min
        assert rates[AM]["selected_slot_start_second"] == pytest.approx(
            21600.0, abs=TOL
        )
        assert rates[PM]["selected_slot_start_second"] == pytest.approx(
            43200.0, abs=TOL
        )


def test_uniform_calendar_still_separates_the_two_arms(contexts):
    """D.1d: the uniform calendar levels the TARIFF, not the carbon intensity.

    So it is the smallest-gap control, not a zero-gap one: the two arms must
    still price the windows differently.
    """
    context = contexts["uniform"]
    for depot_id in _depot_ids(context):
        asap = _rates(context, depot_id, "asap")
        cpc = _rates(context, depot_id, "cost_plus_carbon")
        am_gap = (
            asap[AM]["proxy_cny_per_kwh"] - cpc[AM]["proxy_cny_per_kwh"]
        )
        pm_gap = (
            asap[PM]["proxy_cny_per_kwh"] - cpc[PM]["proxy_cny_per_kwh"]
        )
        assert am_gap == pytest.approx(0.01168, abs=TOL)
        assert pm_gap == pytest.approx(0.00306, abs=TOL)
        assert (
            asap[AM]["proxy_cny_per_kwh"] != cpc[AM]["proxy_cny_per_kwh"]
        )


def test_midday_valley_opens_the_largest_gap(contexts):
    """D.1b: the calendar this batch is solved on -- the arms diverge most."""
    context = contexts["midday_valley"]
    for depot_id in _depot_ids(context):
        asap = _rates(context, depot_id, "asap")
        cpc = _rates(context, depot_id, "cost_plus_carbon")
        assert (
            asap[AM]["proxy_cny_per_kwh"] - cpc[AM]["proxy_cny_per_kwh"]
        ) == pytest.approx(0.283077, abs=1e-5)
        assert (
            asap[PM]["proxy_cny_per_kwh"] - cpc[PM]["proxy_cny_per_kwh"]
        ) == pytest.approx(0.588396, abs=1e-5)


def test_zero_carbon_price_degenerates_cost_plus_carbon_to_cost_min():
    """D.1e: same degeneration the exact timer applies at carbon_price == 0."""
    context = _context("midday_valley", carbon_price=0.0)
    for depot_id in _depot_ids(context):
        cpc = _rates(context, depot_id, "cost_plus_carbon")
        cost_min = _rates(context, depot_id, "cost_min")
        for shift_id in (AM, PM):
            assert (
                cpc[shift_id]["selected_slot_start_second"]
                == cost_min[shift_id]["selected_slot_start_second"]
            )
            assert cpc[shift_id]["proxy_cny_per_kwh"] == pytest.approx(
                cost_min[shift_id]["proxy_cny_per_kwh"], abs=TOL
            )


def test_unknown_policy_is_rejected(contexts):
    """D.1f: the policy name goes through the one shared whitelist."""
    context = contexts["midday_valley"]
    depot_id = _depot_ids(context)[0]
    with pytest.raises(ValueError):
        _rates(context, depot_id, "cheapest_ever")


# ---------------------------------------------------------------------------
# 2026-09-06: the first-trip window rule
#
# The AM window is the first-trip one: with ``prev_return`` it opens at the
# contract's last shift end (19:00) on the PRECEDING day instead of the
# simulation day's 00:00, so it also covers the evening calendar rows.  The PM
# window is an inter-shift window and must not move at all.  Every number
# below was read off the three registered calendars on 2026-09-06.
# ---------------------------------------------------------------------------
PREV_RETURN_SLOT_SECOND = 68_400.0  # the contract's PM shift end, 19:00

PREV_RETURN_AM_PROXY = {
    # asap now plugs in at 19:00 of the preceding evening
    ("beijing_v4", "asap", 0.2): 1.24308175,
    ("beijing_v4", "asap", 1.0): 1.62092175,
    ("midday_valley", "asap", 0.2): 1.24308175,
    ("midday_valley", "asap", 1.0): 1.62092175,
    ("uniform", "asap", 0.2): 0.94391008,
    ("uniform", "asap", 1.0): 1.32175008,
}


def _rates_with_window(context, depot_id: str, policy, first_trip_window):
    rows = time_profile_rows_for_node(
        context.bundle.instance, depot_id, context.bundle.time_profile
    )
    assert rows, f"no depot time-profile rows for {depot_id}"
    return _rebuilt_shift_aware_ev_unit_costs(
        context,
        rows,
        charge_timing_policy=policy,
        first_trip_window=first_trip_window,
    )


@pytest.mark.parametrize("calendar_key", sorted(CALENDARS))
@pytest.mark.parametrize("policy", [None, "asap", "cost_plus_carbon"])
def test_same_day_window_is_the_unchanged_default(
    contexts, calendar_key, policy
):
    """The default window keeps every historical proxy price bit-for-bit."""
    context = contexts[calendar_key]
    for depot_id in _depot_ids(context):
        assert _rates_with_window(
            context, depot_id, policy, "same_day"
        ) == _rates(context, depot_id, policy)


@pytest.mark.parametrize("calendar_key", sorted(CALENDARS))
@pytest.mark.parametrize("carbon_price", [0.2, 1.0])
def test_prev_return_moves_asap_to_the_preceding_evening(
    calendar_key, carbon_price
):
    """``asap`` prices the evening return, not the day's midnight valley."""
    context = _context(calendar_key, carbon_price=carbon_price)
    for depot_id in _depot_ids(context):
        rates = _rates_with_window(context, depot_id, "asap", "prev_return")
        assert rates[AM]["selected_slot_start_second"] == pytest.approx(
            PREV_RETURN_SLOT_SECOND, abs=TOL
        )
        assert rates[AM]["proxy_cny_per_kwh"] == pytest.approx(
            PREV_RETURN_AM_PROXY[(calendar_key, "asap", carbon_price)], abs=TOL
        )
        # ...and the AM slot it left behind was the day's own 00:00
        same_day = _rates_with_window(context, depot_id, "asap", "same_day")
        assert same_day[AM]["selected_slot_start_second"] == pytest.approx(
            0.0, abs=TOL
        )


@pytest.mark.parametrize("calendar_key", sorted(CALENDARS))
@pytest.mark.parametrize("carbon_price", [0.2, 1.0])
def test_prev_return_never_makes_a_cost_key_worse(calendar_key, carbon_price):
    """The merged window is a superset, so a priced key can only improve."""
    context = _context(calendar_key, carbon_price=carbon_price)
    for depot_id in _depot_ids(context):
        widened = _rates_with_window(
            context, depot_id, "cost_plus_carbon", "prev_return"
        )
        narrow = _rates_with_window(
            context, depot_id, "cost_plus_carbon", "same_day"
        )
        assert (
            widened[AM]["proxy_cny_per_kwh"]
            <= narrow[AM]["proxy_cny_per_kwh"] + TOL
        )
        # The PM window is an inter-shift window; the rule does not touch it.
        assert widened[PM] == narrow[PM]


def test_the_flat_tariff_calendar_is_where_the_wider_window_bites(contexts):
    """Under the uniform tariff the evening is cleaner, so the argmin moves.

    On the two real tariff calendars the preceding evening is both dearer and
    dirtier than the night valley, so ``cost_plus_carbon`` does not move; the
    uniform-tariff control is the case that proves the wider window is
    actually searched rather than ignored.
    """
    for depot_id in _depot_ids(contexts["uniform"]):
        widened = _rates_with_window(
            contexts["uniform"], depot_id, "cost_plus_carbon", "prev_return"
        )
        assert widened[AM]["selected_slot_start_second"] == pytest.approx(
            PREV_RETURN_SLOT_SECOND, abs=TOL
        )
        assert widened[AM]["proxy_cny_per_kwh"] == pytest.approx(
            0.94391008, abs=TOL
        )
    for calendar_key in ("beijing_v4", "midday_valley"):
        for depot_id in _depot_ids(contexts[calendar_key]):
            widened = _rates_with_window(
                contexts[calendar_key],
                depot_id,
                "cost_plus_carbon",
                "prev_return",
            )
            narrow = _rates_with_window(
                contexts[calendar_key],
                depot_id,
                "cost_plus_carbon",
                "same_day",
            )
            # Only the reported window bound moves (it now opens at -18000 s,
            # i.e. 19:00 the day before); the priced slot does not.
            for key in (
                "selected_slot",
                "selected_slot_start_second",
                "electricity_cny_per_kwh",
                "actual_gco2_per_kwh",
                "proxy_cny_per_kwh",
            ):
                assert widened[AM][key] == narrow[AM][key]
            assert widened[AM]["window_start_second"] == pytest.approx(
                -18_000.0, abs=TOL
            )


def test_unknown_first_trip_window_is_refused(contexts):
    context = contexts["beijing_v4"]
    depot_id = _depot_ids(context)[0]
    with pytest.raises(ValueError, match="unknown first-trip charging window"):
        _rates_with_window(context, depot_id, "asap", "tomorrow")


# ---------------------------------------------------------------------------
# 2026-09-06 (second pass): the first shift's window opening
#
# The window opens at the vehicle's OWN return the preceding evening, which
# the route proxy cannot know before any route exists.  The caller measures
# the median last return of the initial population and passes it in as
# ``first_trip_window_open_second``; ``None`` keeps the 19:00 fallback.  An
# opening rarely lands on a 30-minute calendar boundary, so the first priced
# row must be the row that CONTAINS it.
# ---------------------------------------------------------------------------


def _rates_with_opening(context, depot_id: str, policy, opening):
    rows = time_profile_rows_for_node(
        context.bundle.instance, depot_id, context.bundle.time_profile
    )
    assert rows, f"no depot time-profile rows for {depot_id}"
    return _rebuilt_shift_aware_ev_unit_costs(
        context,
        rows,
        charge_timing_policy=policy,
        first_trip_window="prev_return",
        first_trip_window_open_second=opening,
    )


def test_the_window_opening_defaults_to_the_last_shift_end(contexts):
    """``None`` is the registered fallback and changes nothing."""
    context = contexts["beijing_v4"]
    for depot_id in _depot_ids(context):
        for policy in (None, "asap", "cost_plus_carbon"):
            assert _rates_with_opening(
                context, depot_id, policy, None
            ) == _rates_with_window(context, depot_id, policy, "prev_return")


@pytest.mark.parametrize("calendar_key", sorted(CALENDARS))
def test_an_opening_inside_a_slot_is_priced_by_that_slot(
    contexts, calendar_key
):
    """A 16:20 opening pays the 16:00-16:30 row, not the 16:30 one.

    This is the off-by-one that would otherwise leave the proxy disagreeing
    with the exact settlement: filtering the merged window on
    ``slot_start >= opening`` drops the row the charge actually starts in.
    """
    context = contexts[calendar_key]
    opening = 16 * 3600.0 + 20 * 60.0  # 58800 s, inside the 16:00 row
    containing_row_start = 16 * 3600.0
    for depot_id in _depot_ids(context):
        rates = _rates_with_opening(context, depot_id, "asap", opening)
        assert rates[AM]["selected_slot_start_second"] == pytest.approx(
            containing_row_start, abs=TOL
        )
        # The window is reported as opening at the measured instant itself,
        # one day back, not at the slot boundary.
        assert rates[AM]["window_start_second"] == pytest.approx(
            opening - 86_400.0, abs=TOL
        )
        # And the price is that row's price, read straight off the calendar.
        rows = time_profile_rows_for_node(
            context.bundle.instance, depot_id, context.bundle.time_profile
        )
        row = next(
            item
            for item in rows
            if float(item["horizon_second_start"]) == containing_row_start
        )
        assert rates[AM]["electricity_cny_per_kwh"] == pytest.approx(
            float(row["depot_energy_cny_per_kwh"]), abs=TOL
        )
        assert rates[AM]["actual_gco2_per_kwh"] == pytest.approx(
            float(row["actual_gco2_per_kwh"]), abs=TOL
        )
        # The PM window is an inter-shift window; the opening cannot touch it.
        assert rates[PM] == _rates_with_window(
            context, depot_id, "asap", "prev_return"
        )[PM]


def test_an_earlier_opening_reaches_the_clean_afternoon(contexts):
    """A mid-afternoon opening lets a carbon key see the grid's clean hours.

    On the beijing calendar 15:00-16:30 is by far the cleanest part of the
    day (182.5 gCO2/kWh against 584.9-643.3 overnight), so at a high carbon
    price the merged window's argmin moves there -- and only an opening early
    enough to include it can find it.  This is exactly the disagreement the
    2026-09-06 projection measured between the 19:00 fallback and the exact
    settlement.
    """
    context = _context("beijing_v4", carbon_price=1.0)
    afternoon_opening = 15 * 3600.0
    for depot_id in _depot_ids(context):
        early = _rates_with_opening(
            context, depot_id, "cost_plus_carbon", afternoon_opening
        )
        fallback = _rates_with_opening(
            context, depot_id, "cost_plus_carbon", None
        )
        assert early[AM]["selected_slot_start_second"] == pytest.approx(
            afternoon_opening, abs=TOL
        )
        assert early[AM]["actual_gco2_per_kwh"] < fallback[AM][
            "actual_gco2_per_kwh"
        ]
        assert (
            early[AM]["proxy_cny_per_kwh"]
            < fallback[AM]["proxy_cny_per_kwh"] - TOL
        )


def test_the_opening_is_inert_under_the_same_day_window(contexts):
    """Under ``same_day`` the wrapping branch is dead, opening or not."""
    context = contexts["beijing_v4"]
    rows_by_depot = {
        depot_id: time_profile_rows_for_node(
            context.bundle.instance, depot_id, context.bundle.time_profile
        )
        for depot_id in _depot_ids(context)
    }
    for depot_id, rows in rows_by_depot.items():
        for policy in (None, "asap", "cost_plus_carbon"):
            with_opening = _rebuilt_shift_aware_ev_unit_costs(
                context,
                rows,
                charge_timing_policy=policy,
                first_trip_window="same_day",
                first_trip_window_open_second=15 * 3600.0,
            )
            assert with_opening == _rates(context, depot_id, policy)


@pytest.mark.parametrize("opening", [-1.0, 86_400.0, 90_000.0])
def test_an_opening_outside_one_day_is_refused(contexts, opening):
    context = contexts["beijing_v4"]
    depot_id = _depot_ids(context)[0]
    with pytest.raises(ValueError, match="local second of one representative"):
        _rates_with_opening(context, depot_id, "asap", opening)
