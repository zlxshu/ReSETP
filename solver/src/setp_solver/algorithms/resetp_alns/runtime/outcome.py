"""Minimal ALNS outcome enum used by the ReSETP search backend.

Adapted from N-Wouda/alns 7.0.0 (MIT License). This project-local copy keeps
only the runtime surface used by the ReSETP ALNS path.  The upstream copyright
notice and complete MIT text are retained in
``runtime/LICENSE-N-WOUDA-ALNS.md``.
"""

from __future__ import annotations

from enum import IntEnum


class Outcome(IntEnum):
    BEST = 0
    BETTER = 1
    ACCEPT = 2
    REJECT = 3
