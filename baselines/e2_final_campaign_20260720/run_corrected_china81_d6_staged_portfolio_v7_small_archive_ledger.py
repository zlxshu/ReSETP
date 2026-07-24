#!/usr/bin/env python3
"""V7 launcher for the registered small-archive ledger repair."""

from __future__ import annotations

import os
from pathlib import Path


CAMPAIGN_NAME = (
    "corrected_china81_rerun_v7_small_archive_ledger_20260724"
)
os.environ["RESET_D6_CAMPAIGN_NAME"] = CAMPAIGN_NAME
os.environ["RESET_D6_LAUNCHER_SOURCE"] = str(Path(__file__).resolve())

from run_corrected_china81_d6_staged_portfolio_v6_budget_recheck import (  # noqa: E402
    main,
)


if __name__ == "__main__":
    raise SystemExit(main())
