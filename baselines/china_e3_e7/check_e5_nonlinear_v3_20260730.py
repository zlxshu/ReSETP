#!/usr/bin/env python3
"""Versioned entry point for the unchanged E5 independent checker.

The verified v2 checker already performs the required reconstruction, fixed-
decision NL90 replay, common check/evaluate scoring, and exact China81 ledger
closure.  V3 changes only the runner-side budget semantics, so this entry point
reuses that checker without changing any physical or scoring semantics while
giving newly issued certificates the v3 task identity.
"""

from __future__ import annotations

import check_e5_nonlinear_v2_20260730 as checker

checker.TASK_ID = "E5-NONLINEAR-CHARGING-V3-20260730"


if __name__ == "__main__":
    raise SystemExit(checker.main())
