"""Versioned absolute-path execution helpers for JRC v2."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any


PACKAGE = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE.parents[2].resolve()
REGISTRATION_V2 = PACKAGE / "g0_registration_v2.json"
ENGINEERING_OUT_V2 = PACKAGE / "engineering_gate_v2"
G0_OUT_V2 = PACKAGE / "g0_gate_v2"
ENGINEERING_CONFIG_V2 = PACKAGE / "monitor_engineering_v2.json"
G0_CONFIG_V2 = PACKAGE / "monitor_g0_v2.json"
ENGINEERING_MONITOR_V2 = (
    PACKAGE / ".jrc-exact-neighborhood-engineering-v2.monitor"
)
G0_MONITOR_V2 = PACKAGE / ".jrc-exact-neighborhood-g0-v2.monitor"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("cannot write empty CSV")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def artifact_manifest(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and "__pycache__" not in path.parts
        and ".monitor" not in path.parts
    }


def verify_v2_registration() -> dict[str, Any]:
    registration = read_json(REGISTRATION_V2)
    if registration.get("schema") != "resetp.jrc-exact-nh-g0.v2":
        raise RuntimeError("unexpected JRC v2 registration schema")
    if Path(registration["project_root"]).resolve() != PROJECT_ROOT:
        raise RuntimeError("JRC v2 project-root identity mismatch")
    for raw, expected in registration["protected_sha256"].items():
        path = Path(raw)
        if not path.is_absolute() or not path.is_file():
            raise RuntimeError(f"JRC v2 protected path invalid: {raw}")
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(
                f"JRC v2 protected hash drift: {raw}: {actual} != {expected}"
            )
    return registration
