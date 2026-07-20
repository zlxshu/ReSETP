from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import math
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class Node:
    node_id: str
    node_type: str
    x: float
    y: float
    demand: float = 0.0
    ready_time: float = 0.0
    due_time: float = 0.0
    service_time: float = 0.0
    # v2026-06-11: optional per-station rated charging power pi_s from generated instance metadata.
    charge_power_kw: float | None = None
    # v2026-06-12: Z0b station/depot charger count C_s for eq:station_capacity.
    # ``station_capacity`` in older generated bundles is accepted by loaders
    # and normalized into this field.
    station_chargers: int | None = None
    # China81 uses city-specific road, tariff, and carbon rows. Historical
    # instances leave this unset and retain their single-profile semantics.
    city: str | None = None


@dataclass(frozen=True)
class RoadProfileMatrices:
    """One vehicle profile's same-path directed road metrics."""

    distance_m: tuple[tuple[float, ...], ...]
    duration_s: tuple[tuple[float, ...], ...]
    sum_v2d_m3_s2: tuple[tuple[float, ...], ...]


@dataclass(frozen=True)
class VehicleTypeParameters:
    """One complete, source-bound vehicle configuration."""

    vehicle_type_id: str
    fuel_type: str
    payload_capacity_kg: float
    curb_mass_kg: float
    gross_mass_kg: float
    frontal_area_m2: float
    battery_kwh: float | None
    drag_coefficient: float
    rolling_resistance_coefficient: float
    non_energy_distance_cost_per_km: float
    engine_friction_kj_per_rev_l: float | None
    engine_speed_rev_per_s: float | None
    engine_displacement_l: float | None
    traction_energy_multiplier: float | None
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class Instance:
    nodes: list[Node]
    distance_matrix: list[list[float]]
    diesel_l_per_meter: float | None = None
    ev_kwh_per_meter: float | None = None
    unit_distance_cost_per_meter: float | None = None
    # v2026-06-26: structural fleet availability. When present, these are hard
    # upper bounds on physical CV/EV vehicles; a physical vehicle may serve
    # multiple route/trip rows via the ``CV1#Tn`` route-id convention.
    num_cv: int | None = None
    num_ev: int | None = None
    road_profiles: Mapping[str, RoadProfileMatrices] | None = None
    vehicle_parameters: Mapping[str, VehicleTypeParameters] | None = None
    demand_mass_per_unit_kg: float | None = None
    _node_index: dict[str, int] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_node_index",
            {
                node.node_id: idx
                for idx, node in enumerate(self.nodes)
            },
        )
        if self.road_profiles is None and self.vehicle_parameters is None:
            return
        if self.road_profiles is None or self.vehicle_parameters is None:
            raise ValueError(
                "profiled instances require both road and vehicle profiles"
            )
        demand_mass = self.demand_mass_per_unit_kg
        if (
            demand_mass is None
            or not math.isfinite(float(demand_mass))
            or float(demand_mass) <= 0.0
        ):
            raise ValueError(
                "profiled instances require a positive demand-mass unit"
            )
        if len(self._node_index) != len(self.nodes):
            raise ValueError("profiled instances require unique node ids")
        normalized = {
            str(profile).lower(): RoadProfileMatrices(
                distance_m=_freeze_profile_matrix(matrices.distance_m),
                duration_s=_freeze_profile_matrix(matrices.duration_s),
                sum_v2d_m3_s2=_freeze_profile_matrix(
                    matrices.sum_v2d_m3_s2
                ),
            )
            for profile, matrices in self.road_profiles.items()
        }
        if set(normalized) != {"cv", "ev"}:
            raise ValueError(
                "profiled instances require exactly CV and EV road profiles"
            )
        for profile, matrices in normalized.items():
            for name, matrix in (
                ("distance", matrices.distance_m),
                ("duration", matrices.duration_s),
                ("sum_v2d", matrices.sum_v2d_m3_s2),
            ):
                _validate_profile_matrix(
                    matrix,
                    len(self.nodes),
                    profile=profile,
                    name=name,
                )
        object.__setattr__(
            self,
            "road_profiles",
            MappingProxyType(normalized),
        )
        vehicle_parameters = {
            str(profile).lower(): parameters
            for profile, parameters in self.vehicle_parameters.items()
        }
        if set(vehicle_parameters) != {"cv", "ev"}:
            raise ValueError(
                "profiled instances require exactly CV and EV vehicle profiles"
            )
        _validate_vehicle_parameters(
            vehicle_parameters["cv"],
            profile="cv",
        )
        _validate_vehicle_parameters(
            vehicle_parameters["ev"],
            profile="ev",
        )
        object.__setattr__(
            self,
            "vehicle_parameters",
            MappingProxyType(vehicle_parameters),
        )

    @property
    def node_index(self) -> dict[str, int]:
        return self._node_index

    def distance(self, from_node_id: str, to_node_id: str) -> float:
        left, right = self._indices(from_node_id, to_node_id)
        return float(self.distance_matrix[left][right])

    def arc_metrics(
        self,
        from_node_id: str,
        to_node_id: str,
        vehicle_type: str,
        *,
        fallback_speed_mps: float,
    ) -> tuple[float, float, float]:
        """Return distance, travel time, and sum(v^2 d) for one arc.

        Historical instances use their single distance matrix and frozen
        constant speed. Profiled China81 instances fail closed unless the
        requested CV/EV profile exists with all three same-path matrices.
        """

        left, right = self._indices(from_node_id, to_node_id)
        if self.road_profiles is None:
            speed = float(fallback_speed_mps)
            if not math.isfinite(speed) or speed <= 0.0:
                raise ValueError(
                    "fallback vehicle speed must be finite and positive"
                )
            distance = float(self.distance_matrix[left][right])
            return (
                distance,
                distance / speed,
                speed * speed * distance,
            )
        profile = str(vehicle_type).lower()
        try:
            matrices = self.road_profiles[profile]
        except KeyError as exc:
            raise ValueError(
                f"road profile {profile!r} is unavailable"
            ) from exc
        return (
            float(matrices.distance_m[left][right]),
            float(matrices.duration_s[left][right]),
            float(matrices.sum_v2d_m3_s2[left][right]),
        )

    def vehicle_profile(
        self,
        vehicle_type: str,
    ) -> VehicleTypeParameters | None:
        if self.vehicle_parameters is None:
            return None
        profile = str(vehicle_type).lower()
        try:
            return self.vehicle_parameters[profile]
        except KeyError as exc:
            raise ValueError(
                f"vehicle profile {profile!r} is unavailable"
            ) from exc

    def payload_capacity_kg(
        self,
        vehicle_type: str,
        *,
        fallback: float,
    ) -> float:
        profile = self.vehicle_profile(vehicle_type)
        return (
            float(fallback)
            if profile is None
            else float(profile.payload_capacity_kg)
        )

    def battery_capacity_kwh(
        self,
        *,
        fallback: float,
    ) -> float:
        profile = self.vehicle_profile("ev")
        if profile is None:
            return float(fallback)
        if profile.battery_kwh is None:
            raise ValueError("EV vehicle profile has no battery capacity")
        return float(profile.battery_kwh)

    def non_energy_distance_cost_per_km(
        self,
        vehicle_type: str,
        *,
        fallback: float,
    ) -> float:
        profile = self.vehicle_profile(vehicle_type)
        return (
            float(fallback)
            if profile is None
            else float(profile.non_energy_distance_cost_per_km)
        )

    def load_mass_kg(
        self,
        load_units: float,
        *,
        fallback_mass_per_unit_kg: float,
    ) -> float:
        multiplier = (
            float(fallback_mass_per_unit_kg)
            if self.vehicle_parameters is None
            else float(self.demand_mass_per_unit_kg)
        )
        return multiplier * float(load_units)

    def _indices(
        self,
        from_node_id: str,
        to_node_id: str,
    ) -> tuple[int, int]:
        index = self.node_index
        if from_node_id not in index:
            raise KeyError(f"Unknown node id: {from_node_id}")
        if to_node_id not in index:
            raise KeyError(f"Unknown node id: {to_node_id}")
        return index[from_node_id], index[to_node_id]


def load_profiled_road_matrices(
    matrix_root: str | Path,
    nodes: list[Node],
) -> Mapping[str, RoadProfileMatrices]:
    """Load the frozen CV/EV distance-duration-sum(v^2 d) CSV contract."""

    root = Path(matrix_root)
    node_ids = [node.node_id for node in nodes]
    profiles: dict[str, RoadProfileMatrices] = {}
    for profile in ("cv", "ev"):
        profile_root = root / profile
        profiles[profile] = RoadProfileMatrices(
            distance_m=_freeze_profile_matrix(
                _load_labeled_matrix(
                    profile_root / "road_distance_m.csv",
                    node_ids,
                )
            ),
            duration_s=_freeze_profile_matrix(
                _load_labeled_matrix(
                    profile_root / "road_duration_s.csv",
                    node_ids,
                )
            ),
            sum_v2d_m3_s2=_freeze_profile_matrix(
                _load_labeled_matrix(
                    profile_root / "road_sum_v2d_m3_s2.csv",
                    node_ids,
                )
            ),
        )
    return MappingProxyType(profiles)


def load_instance(path: str | Path) -> Instance:
    instance_path = Path(path)
    nodes: list[Node] = []
    matrix_rows: list[list[float]] = []
    num_cv: int | None = None
    num_ev: int | None = None
    in_matrix = False

    with instance_path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("DistanceMatrix"):
                in_matrix = True
                continue
            if line.startswith("m "):
                if "numPetrolVeh" in line:
                    num_cv = _slash_int(line)
                elif "numElectroVeh" in line:
                    num_ev = _slash_int(line)
                continue
            if in_matrix:
                matrix_rows.append([float(value) for value in line.split()])
                continue
            if line.startswith("StringID"):
                continue
            parts = line.split()
            if len(parts) < 8:
                continue
            try:
                nodes.append(
                    Node(
                        node_id=parts[0],
                        node_type=parts[1],
                        x=float(parts[2]),
                        y=float(parts[3]),
                        demand=float(parts[4]),
                        ready_time=float(parts[5]),
                        due_time=float(parts[6]),
                        service_time=float(parts[7]),
                    )
                )
            except ValueError:
                continue

    if not nodes:
        raise ValueError(f"No nodes found in instance file: {instance_path}")
    if len(matrix_rows) != len(nodes) or any(len(row) != len(nodes) for row in matrix_rows):
        raise ValueError("Distance matrix shape does not match node count")
    return Instance(nodes=nodes, distance_matrix=matrix_rows, num_cv=num_cv, num_ev=num_ev)


def _slash_int(line: str) -> int | None:
    match = re.search(r"/\s*([0-9]+)\s*/", line)
    return int(match.group(1)) if match else None


def _load_labeled_matrix(
    path: Path,
    expected_node_ids: list[str],
) -> list[list[float]]:
    if not path.is_file():
        raise ValueError(f"required road matrix is missing: {path}")
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError(f"road matrix is empty: {path}") from exc
        if (
            not header
            or header[0] != "node_id"
            or header[1:] != expected_node_ids
        ):
            raise ValueError(
                f"road matrix header disagrees with instance nodes: {path}"
            )
        rows: list[list[float]] = []
        observed_ids: list[str] = []
        for row in reader:
            if len(row) != len(expected_node_ids) + 1:
                raise ValueError(f"road matrix row width is invalid: {path}")
            observed_ids.append(row[0])
            try:
                rows.append([float(value) for value in row[1:]])
            except ValueError as exc:
                raise ValueError(
                    f"road matrix contains a non-numeric value: {path}"
                ) from exc
    if observed_ids != expected_node_ids:
        raise ValueError(
            f"road matrix row labels disagree with instance nodes: {path}"
        )
    return rows


def _validate_profile_matrix(
    matrix: Sequence[Sequence[float]],
    node_count: int,
    *,
    profile: str,
    name: str,
) -> None:
    if len(matrix) != node_count or any(
        len(row) != node_count for row in matrix
    ):
        raise ValueError(
            f"{profile} {name} matrix shape does not match node count"
        )
    for left, row in enumerate(matrix):
        for right, raw in enumerate(row):
            value = float(raw)
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(
                    f"{profile} {name} matrix contains an invalid value"
                )
            if left == right and abs(value) > 1e-9:
                raise ValueError(
                    f"{profile} {name} matrix diagonal must be zero"
                )


def _freeze_profile_matrix(
    matrix: Sequence[Sequence[float]],
) -> tuple[tuple[float, ...], ...]:
    return tuple(
        tuple(float(value) for value in row)
        for row in matrix
    )


def _validate_vehicle_parameters(
    parameters: VehicleTypeParameters,
    *,
    profile: str,
) -> None:
    expected_fuel = "diesel" if profile == "cv" else "electric"
    if parameters.fuel_type.lower() != expected_fuel:
        raise ValueError(
            f"{profile} vehicle fuel type must be {expected_fuel}"
        )
    positive_fields = {
        "payload_capacity_kg": parameters.payload_capacity_kg,
        "curb_mass_kg": parameters.curb_mass_kg,
        "gross_mass_kg": parameters.gross_mass_kg,
        "frontal_area_m2": parameters.frontal_area_m2,
        "drag_coefficient": parameters.drag_coefficient,
        "rolling_resistance_coefficient": (
            parameters.rolling_resistance_coefficient
        ),
        "non_energy_distance_cost_per_km": (
            parameters.non_energy_distance_cost_per_km
        ),
    }
    for name, raw in positive_fields.items():
        value = float(raw)
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(
                f"{profile} vehicle {name} must be finite and positive"
            )
    if (
        float(parameters.curb_mass_kg)
        + float(parameters.payload_capacity_kg)
        > float(parameters.gross_mass_kg) + 1e-9
    ):
        raise ValueError(
            f"{profile} curb mass plus payload exceeds gross mass"
        )
    if not parameters.vehicle_type_id.strip():
        raise ValueError(f"{profile} vehicle type id is empty")
    if not parameters.source_ids:
        raise ValueError(f"{profile} vehicle sources are empty")
    engine_fields = (
        parameters.engine_friction_kj_per_rev_l,
        parameters.engine_speed_rev_per_s,
        parameters.engine_displacement_l,
    )
    traction = parameters.traction_energy_multiplier
    if profile == "cv":
        if any(
            value is None
            or not math.isfinite(float(value))
            or float(value) <= 0.0
            for value in engine_fields
        ):
            raise ValueError(
                "CV vehicle engine parameters must be finite and positive"
            )
        if traction is not None:
            raise ValueError(
                "CV vehicle profile must not define an EV traction multiplier"
            )
    else:
        if any(value is not None for value in engine_fields):
            raise ValueError(
                "EV vehicle profile must not define diesel engine parameters"
            )
        if (
            traction is None
            or not math.isfinite(float(traction))
            or float(traction) <= 0.0
        ):
            raise ValueError(
                "EV traction multiplier must be finite and positive"
            )
    battery = parameters.battery_kwh
    if profile == "ev":
        if battery is None or not math.isfinite(float(battery)) or float(battery) <= 0.0:
            raise ValueError(
                "EV vehicle battery capacity must be finite and positive"
            )
    elif battery is not None:
        raise ValueError("CV vehicle profile must not define a battery")


def load_carbon_profile(path: str | Path) -> list[dict[str, Any]]:
    profile_path = Path(path)
    rows: list[dict[str, Any]] = []
    with profile_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(
                {
                    "time_index": int(row["time_index"]),
                    "datetime_utc": row["datetime_utc"],
                    "actual_gco2_per_kwh": float(row["actual_gco2_per_kwh"]),
                    "forecast_gco2_per_kwh": float(row["forecast_gco2_per_kwh"]),
                    "index_label": row["index_label"],
                    "index_code": int(row["index_code"]),
                    "horizon_second_start": float(row["horizon_second_start"]),
                }
            )
    rows.sort(key=lambda item: item["horizon_second_start"])
    return rows
