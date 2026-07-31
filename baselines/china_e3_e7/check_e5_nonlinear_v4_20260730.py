#!/usr/bin/env python3
"""Versioned entry point for the unchanged E5 independent checker."""

from __future__ import annotations

import check_e5_nonlinear_v2_20260730 as checker

checker.TASK_ID = "E5-NONLINEAR-CHARGING-V4-20260730"


if __name__ == "__main__":
    raise SystemExit(checker.main())
