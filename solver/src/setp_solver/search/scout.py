"""Best-effort candidate algorithm scout.

v2026-06-11: G6 records import/interface status for local reference
algorithms without adapting or running them against SETP. Use
``scout_reference_algorithms`` for the non-blocking candidate board.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from pathlib import Path
import sys

from .alns_wouda import _ensure_matplotlib_stub


@dataclass(frozen=True)
class CandidateStatus:
    name: str
    can_import: bool
    interface_summary: str
    adapter_needed: str
    status: str


def scout_reference_algorithms(repo_root: str | Path) -> list[CandidateStatus]:
    root = Path(repo_root) / "Reference Algorithm"
    candidates = [
        ("ALNS-Wouda", root / "ALNS-7.0.0@N-Wouda", "alns", "State.objective() wrapper already implemented", "primary adapter"),
        ("DR-ALNS@RobbertReijnen", root / "DR-ALNS@RobbertReijnen" / "code" / "src", "ALNS_custom", "routing-problem facade plus evaluate callback", "scout only"),
        ("ALNS@wangqianlongucas", root / "ALNS@wangqianlongucas" / "code", "main", "script-to-Solution bridge", "scout only"),
        ("GeneticAlgorithmPython", root / "GeneticAlgorithmPython-3.6.0@ahmedfgad", "pygad", "chromosome<->Solution codec plus evaluate callback", "scout only"),
        ("NSGA-II@haris989", root / "NSGA-II@haris989", None, "script extraction and multiobjective wrapper", "scout only"),
        ("scikit-opt", root / "scikit-opt-0.6.5@guofei9987", "sko", "permutation codec plus evaluate callback", "scout only"),
        ("VNS@Valdecy", root / "VNS@Valdecy", None, "single-file function wrapper", "scout only"),
    ]
    return [_probe(name, path, module, adapter, status) for name, path, module, adapter, status in candidates]


def _probe(name: str, path: Path, module: str | None, adapter: str, status: str) -> CandidateStatus:
    if module is None:
        return CandidateStatus(name, path.exists(), "single-file/script candidate, no package import attempted", adapter, status)
    if not path.exists():
        return CandidateStatus(name, False, f"path missing: {path}", adapter, status)
    old_path = list(sys.path)
    try:
        sys.path.insert(0, str(path))
        if module == "alns":
            _ensure_matplotlib_stub()
        imported = importlib.import_module(module)
        summary = f"module={module}, file={getattr(imported, '__file__', '<namespace>')}"
        return CandidateStatus(name, True, summary, adapter, status)
    except Exception as exc:  # pragma: no cover - diagnostic board records failures.
        return CandidateStatus(name, False, f"{type(exc).__name__}: {exc}", adapter, status)
    finally:
        sys.path[:] = old_path
