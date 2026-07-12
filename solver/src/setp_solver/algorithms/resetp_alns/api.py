"""Public API for the independent ReSETP ALNS algorithm package."""
from __future__ import annotations

from setp_solver.algorithms.resetp_alns.kernel.alns_core import SearchPolicy, run_alns_wouda
from setp_solver.algorithms.resetp_alns.kernel.winner import (
    WinnerKernelConfig,
    run_winner_kernel,
    run_e2_alns_throughput,
    e2_alns_throughput_flags,
    run_tvci_alns,
    run_tvci_carbon_schedule_pair,
)
from setp_solver.algorithms.resetp_alns.naming import (
    TVCI_ALNS_ID,
    TVCI_ALNS_NAME_EN,
    TVCI_ALNS_NAME_ZH,
)

# Canonical name
run_resetp_alns = run_winner_kernel

__all__ = [
    "SearchPolicy",
    "WinnerKernelConfig",
    "e2_alns_throughput_flags",
    "run_alns_wouda",
    "run_e2_alns_throughput",
    "run_tvci_alns",
    "run_tvci_carbon_schedule_pair",
    "TVCI_ALNS_ID",
    "TVCI_ALNS_NAME_EN",
    "TVCI_ALNS_NAME_ZH",
    "run_resetp_alns",
    "run_winner_kernel",
]
