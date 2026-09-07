"""Standalone SETP solver scoring utilities."""

from .cost import evaluate
# v2026-06-11: export optional default-frozen profit fairness context.
from .check import FairnessContext, Violation, check_solution
from .instance_loader import Instance, Node, load_carbon_profile
from .profit import DepotProfitBreakdown, calculate_depot_profits
from .solution import ChargingAction, CrossSiteService, Route, Solution

__all__ = [
    "ChargingAction",
    "CrossSiteService",
    "Instance",
    "FairnessContext",
    "Node",
    "DepotProfitBreakdown",
    "Route",
    "Solution",
    "Violation",
    "calculate_depot_profits",
    "check_solution",
    "evaluate",
    "load_carbon_profile",
]
