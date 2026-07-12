"""Independent ReSETP ALNS algorithm package.

Lazy exports to avoid circular imports with search.candidates shims.
"""
from __future__ import annotations

from typing import Any

__all__ = [
    "SearchPolicy",
    "WinnerKernelConfig",
    "e2_alns_throughput_flags",
    "run_alns_wouda",
    "run_e2_alns_throughput",
    "run_resetp_alns",
    "run_winner_kernel",
    "run_tvci_alns",
    "run_tvci_carbon_schedule_pair",
    "TVCI_ALNS_ID",
    "TVCI_ALNS_NAME_EN",
    "TVCI_ALNS_NAME_ZH",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from setp_solver.algorithms.resetp_alns import api as _api
        return getattr(_api, name)
    raise AttributeError(name)
