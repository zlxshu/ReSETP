"""Absolute, validated path registry for the reusable launch harness."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PACKAGE = Path(__file__).resolve().parent
DEFAULT_PROJECT_ROOT = PACKAGE.parents[2].resolve()
REGISTRATION = PACKAGE / "registration_v1.json"
MONITOR_CONFIG = PACKAGE / "monitor_integration_v1.json"
OUTPUT = PACKAGE / "integration_gate_v1"
MONITOR_RUN_DIR = PACKAGE / ".absolute-execution-harness-v1.monitor"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_absolute_file(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_absolute() or not resolved.is_file():
        raise RuntimeError(f"{label} is not an absolute existing file: {path}")
    return resolved


def require_absolute_dir(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_absolute() or not resolved.is_dir():
        raise RuntimeError(
            f"{label} is not an absolute existing directory: {path}"
        )
    return resolved


def validate_project_root(path: Path) -> Path:
    root = require_absolute_dir(path, "project root")
    required = (
        root / "HANDOFF.md",
        root / "docs/handoff/READ_ME_FIRST_FOR_AGENTS.md",
        root / "solver/src/setp_solver",
    )
    if not required[0].is_file() or not required[1].is_file():
        raise RuntimeError("project root is missing mandatory handoff markers")
    if not required[2].is_dir():
        raise RuntimeError("project root is missing solver/src/setp_solver")
    if PACKAGE.parents[2].resolve() != root:
        raise RuntimeError(
            f"harness package root mismatch: {PACKAGE.parents[2]} != {root}"
        )
    return root


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
