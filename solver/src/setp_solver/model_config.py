"""Explicit model-semantics configuration."""

from __future__ import annotations

from dataclasses import dataclass


MODEL_CONFIG_SCHEMA = "setp-model-config.v2"
DEPOT_CHARGER_CAPACITY_UNBOUNDED = "unbounded"
DEPOT_CHARGER_CAPACITY_FINITE_INSTANCE = "finite_instance"
_DEPOT_CHARGER_CAPACITY_MODES = {
    DEPOT_CHARGER_CAPACITY_UNBOUNDED,
    DEPOT_CHARGER_CAPACITY_FINITE_INSTANCE,
}


@dataclass(frozen=True)
class ModelConfig:
    """Model choices that must not be inferred from ambient process state."""

    strict_multitrip: bool = True
    depot_charger_capacity_mode: str = DEPOT_CHARGER_CAPACITY_UNBOUNDED

    def __post_init__(self) -> None:
        if type(self.strict_multitrip) is not bool:
            raise TypeError("strict_multitrip must be a bool")
        if self.depot_charger_capacity_mode not in _DEPOT_CHARGER_CAPACITY_MODES:
            raise ValueError(
                "depot_charger_capacity_mode must be one of "
                f"{sorted(_DEPOT_CHARGER_CAPACITY_MODES)!r}"
            )

    def as_metadata(self) -> dict[str, object]:
        return {
            "schema_version": MODEL_CONFIG_SCHEMA,
            "strict_multitrip": self.strict_multitrip,
            "depot_charger_capacity_mode": self.depot_charger_capacity_mode,
        }
