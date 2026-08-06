"""Explicit model-semantics configuration with a legacy compatibility edge."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import os
from typing import Iterator


LEGACY_STRICT_MULTITRIP_ENV = "SETP_E3_STRICT_MULTITRIP"
MODEL_CONFIG_SCHEMA = "setp-model-config.v2"
DEPOT_CHARGER_CAPACITY_UNBOUNDED = "unbounded"
DEPOT_CHARGER_CAPACITY_FINITE_INSTANCE = "finite_instance"
_DEPOT_CHARGER_CAPACITY_MODES = {
    DEPOT_CHARGER_CAPACITY_UNBOUNDED,
    DEPOT_CHARGER_CAPACITY_FINITE_INSTANCE,
}


class MissingModelConfigError(ValueError):
    """Raised when a mainline entry omits explicit model semantics."""


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


_ACTIVE_MODEL_CONFIG: ContextVar[ModelConfig | None] = ContextVar(
    "setp_active_model_config",
    default=None,
)


@contextmanager
def model_config_scope(config: ModelConfig) -> Iterator[ModelConfig]:
    """Bind one explicit configuration for all nested scoring operations."""

    if not isinstance(config, ModelConfig):
        raise TypeError("config must be a ModelConfig")
    token = _ACTIVE_MODEL_CONFIG.set(config)
    try:
        yield config
    finally:
        _ACTIVE_MODEL_CONFIG.reset(token)


def active_model_config() -> ModelConfig | None:
    return _ACTIVE_MODEL_CONFIG.get()


def legacy_model_config_from_environment() -> ModelConfig:
    """Translate the historical 0/1 environment contract without changing it."""

    raw = os.environ.get(LEGACY_STRICT_MULTITRIP_ENV, "0")
    return ModelConfig(strict_multitrip=raw.lower() not in {"0", "false", "no"})


def strict_multitrip_enabled() -> bool:
    """Resolve the active explicit value, or the isolated legacy boundary."""

    config = active_model_config()
    if config is not None:
        return config.strict_multitrip
    return legacy_model_config_from_environment().strict_multitrip
