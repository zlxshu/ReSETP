from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class DynamicEventConfig:
    enabled: bool = False
    n_events: int = 0
    event_rate: float | None = None
    event_ratio: tuple[float, float, float, float] = (5.0, 2.0, 1.0, 1.0)
    time_window_change_ratio: tuple[float, float, float] = (1.0, 3.0, 1.0)
    random_mode: str = "random"
    q_kg: float = 500.0
    t_min: float = 1800.0
    q_accum_policy: str = "positive_only"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScenarioConfig:
    n_depots: int = 2
    n_stations: int = 3
    n_customers: int = 25
    seed: int = 1
    scenario_id: str = "synthetic_setp"

    coord_mode: str = "synthetic"
    demand_mode: str = "truncnorm"
    time_window_mode: str = "synthetic"
    depot_strategy: str = "scored_candidates"
    station_strategy: str = "hybrid_support"

    coord_bounds: tuple[float, float, float, float] = (-60000.0, 60000.0, -45000.0, 45000.0)
    n_customer_clusters: int = 4
    cluster_std_ratio: float = 0.12
    min_customer_distance: float = 300.0
    min_depot_distance: float = 5000.0
    min_station_distance: float = 1500.0
    station_avoid_node_overlap: bool = True
    station_min_node_distance: float = 1.0
    max_isolated_customer_share: float = 0.08

    vehicle_capacity: float = 1600.0
    # v2026-06-12: fleet composition is an instance-level structural parameter
    # for solver search gates; defaults preserve the paper baseline m^g=m^e=10.
    num_cv: int = 10
    num_ev: int = 10
    max_customer_demand_ratio: float = 0.65
    demand_mean: float = 520.0
    demand_std: float = 240.0
    demand_min: float = 50.0

    horizon_start: float = 0.0
    horizon_end: float = 32400.0
    # v2026-06-12: Q1 24h shifted variants keep customer windows shifted while
    # the carbon profile covers the full day; defaults preserve legacy output.
    time_window_shift_seconds: float = 0.0
    empirical_exact_base: bool = False
    depot_due_time: float | None = None
    time_window_min_width: float = 3600.0
    time_window_max_width: float = 21600.0
    service_time_min: float = 180.0
    service_time_max: float = 1800.0

    # v2026-06-12: Z0b public charging stations are the scarce shared resource;
    # depots get a large static route-count upper bound in generated nodes.
    station_capacity: int = 1
    # v2026-06-11: align station rated power with paper parameter pi_s; 60 kW is a medium-power DC fast-charge setting, proxied by GRIDSERVE Electric Hub medium-power chargers (up to 60 kW), accessed 2026-06-11.
    station_charge_power_kw: float = 60.0
    carbon_regions: tuple[str, ...] = ("R1", "R2", "R3")
    carbon_alignment_mode: str = "none"
    carbon_time_anchor_utc: str | None = None
    carbon_profile_path: str | None = None
    base_instance_path: str | None = None
    add_event_source_paths: tuple[str, ...] = ()
    dynamic_event_config: DynamicEventConfig = field(default_factory=DynamicEventConfig)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["dynamic_event_config"] = self.dynamic_event_config.to_dict()
        if self.carbon_alignment_mode == "none":
            data.pop("carbon_alignment_mode", None)
            data.pop("carbon_time_anchor_utc", None)
            data.pop("carbon_profile_path", None)
        return data
