"""Stable public names for the current carbon-aware search method.

The short name is a presentation/API label for the existing staged
ALNS--LNS search kernel followed by fixed-route charging rescheduling.  The
legacy machine identifier is intentionally retained so frozen E2 evidence and
old result files remain readable.
"""

from __future__ import annotations

TVCI_ALNS_ID = "TVCI-ALNS"
TVCI_ALNS_NAME_EN = "Time-Varying Carbon-Intensity-Guided ALNS"
TVCI_ALNS_NAME_ZH = "时变碳强度引导的自适应大邻域搜索"
TVCI_ALNS_DISPLAY_NAME = f"{TVCI_ALNS_ID}: {TVCI_ALNS_NAME_EN}"

# Historical identifiers are part of the evidence contract and must not be
# rewritten in sealed E2 CSV/JSON artifacts.
TVCI_ALNS_LEGACY_ID = "staged_hybrid_carbon_aware"
TVCI_ALNS_LEGACY_LABEL = "staged ALNS-LNS hybrid + carbon-aware charging schedule"
TVCI_ALNS_KERNEL_LABEL = "staged ALNS-LNS hybrid"

__all__ = [
    "TVCI_ALNS_DISPLAY_NAME",
    "TVCI_ALNS_ID",
    "TVCI_ALNS_KERNEL_LABEL",
    "TVCI_ALNS_LEGACY_ID",
    "TVCI_ALNS_LEGACY_LABEL",
    "TVCI_ALNS_NAME_EN",
    "TVCI_ALNS_NAME_ZH",
]
