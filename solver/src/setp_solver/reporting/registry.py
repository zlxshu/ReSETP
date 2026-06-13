from __future__ import annotations

from collections.abc import Callable
from typing import Any


Runner = Callable[[Any], Any]
RUNNERS: dict[str, Runner] = {}


def register_runner(name: str) -> Callable[[Runner], Runner]:
    def decorator(func: Runner) -> Runner:
        if name in RUNNERS:
            raise ValueError(f"Duplicate reporting runner: {name}")
        RUNNERS[name] = func
        return func

    return decorator


def get_runner(name: str) -> Runner:
    try:
        return RUNNERS[name]
    except KeyError as exc:
        names = ", ".join(sorted(RUNNERS))
        raise KeyError(f"Unknown reporting runner {name!r}. Available: {names}") from exc
