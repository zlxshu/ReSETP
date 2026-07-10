"""Deprecated shim — winner kernel lives in algorithms.resetp_alns.kernel.winner."""
from __future__ import annotations

from setp_solver.algorithms.resetp_alns.kernel.winner import (  # noqa: F401
    WinnerKernelConfig,
    e2_alns_throughput_flags,
    operator_base_id,
    run_e2_alns_throughput,
    run_staged_alns_lns_hybrid,
    run_staged_carbon_aware_hybrid,
    run_staged_carbon_schedule_pair,
    run_winner_kernel,
    winner_operator_module,
)
from setp_solver.algorithms.resetp_alns.kernel import winner as _winner

def __getattr__(name: str):
    return getattr(_winner, name)
