"""Load and validate CONTROL_CONSOLE.yaml + PARAMETERS_CONSOLE.yaml."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTROL = REPO_ROOT / "CONTROL_CONSOLE.yaml"
DEFAULT_PARAMS = REPO_ROOT / "PARAMETERS_CONSOLE.yaml"


def _require_yaml() -> Any:
    if yaml is None:
        raise RuntimeError(
            "PyYAML is required for the control console. "
            "Install with: python -m pip install pyyaml"
        )
    return yaml


def load_yaml(path: Path) -> dict[str, Any]:
    y = _require_yaml()
    if not path.is_file():
        raise FileNotFoundError(f"Missing console file: {path}")
    data = y.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return data


def resolve_repo_root(params: dict[str, Any]) -> Path:
    raw = (params.get("paths") or {}).get("repo_root", ".")
    p = Path(str(raw))
    if not p.is_absolute():
        p = (REPO_ROOT / p).resolve()
    return p


def abs_under(repo: Path, rel: str | Path) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else (repo / p).resolve()


def apply_env_overrides(control: dict[str, Any]) -> dict[str, Any]:
    """Optional environment overrides for CI / one-click variants."""
    out = dict(control)
    mode = os.environ.get("RESETP_CONSOLE_MODE")
    if mode:
        out["mode"] = mode.strip().lower()
    dry = os.environ.get("RESETP_CONSOLE_DRY_RUN")
    if dry is not None:
        out["dry_run"] = dry.strip().lower() in {"1", "true", "yes", "on"}
    return out
