"""Frozen configurations for the MDA-ILS-VNS bounded parameter race."""

from __future__ import annotations

from selective_route_vns import SearchConfig


FOUNDATION = SearchConfig(
    "foundation",
    route_operators=("SwapStar",),
)

_ROWS = (
    ("race_01", 20, 0.2, 4.0, False, 600, 5, 25),
    ("race_02", 80, 0.0, 1.0, True, 600, 3, 35),
    ("race_03", 65, 1.0, 4.0, True, 300, 1, 25),
    ("race_04", 80, 0.0, 1.0, True, 300, 3, 15),
    ("race_05", 35, 0.2, 2.0, True, 100, 5, 35),
    ("race_06", 20, 0.2, 0.5, False, 300, 1, 40),
    ("race_07", 50, 1.0, 1.0, False, 1200, 5, 15),
    ("race_08", 65, 0.5, 0.5, False, 100, 5, 25),
    ("race_09", 35, 0.0, 2.0, True, 1200, 3, 25),
    ("race_10", 50, 0.2, 0.5, True, 600, 1, 15),
    ("race_11", 50, 1.0, 0.5, False, 600, 3, 40),
    ("race_12", 50, 0.0, 4.0, False, 100, 3, 35),
    ("race_13", 20, 1.0, 4.0, False, 300, 3, 15),
    ("race_14", 35, 0.5, 1.0, True, 100, 1, 40),
    ("race_15", 80, 0.5, 2.0, False, 1200, 1, 35),
    ("race_16", 65, 0.5, 2.0, True, 1200, 5, 40),
)

RACE_CONFIGS: dict[str, SearchConfig] = {"foundation": FOUNDATION}
for (
    name,
    neighbours,
    wait_weight,
    warp_weight,
    symmetric,
    history,
    min_perturbations,
    max_perturbations,
) in _ROWS:
    RACE_CONFIGS[name] = SearchConfig(
        name=name,
        route_operators=("SwapStar",),
        weight_wait_time=wait_weight,
        weight_time_warp=warp_weight,
        num_neighbours=neighbours,
        symmetric_neighbours=symmetric,
        history_length=history,
        min_perturbations=min_perturbations,
        max_perturbations=max_perturbations,
    )
