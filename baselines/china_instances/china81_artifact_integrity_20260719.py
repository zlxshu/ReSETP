#!/usr/bin/env python3
"""Shared fail-closed integrity checks for frozen China81 artifact packages."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any


class ArtifactIntegrityError(RuntimeError):
    """A frozen artifact package is missing, malformed, or hash-drifted."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ArtifactIntegrityError(f"missing JSON evidence: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ArtifactIntegrityError(f"invalid JSON evidence: {path}") from exc
    if not isinstance(payload, dict):
        raise ArtifactIntegrityError(f"JSON evidence must be an object: {path}")
    return payload


def _hash_entries(payload: dict[str, Any], manifest: Path) -> dict[str, str]:
    entries: Any = payload.get("sha256", payload.get("files", payload))
    if not isinstance(entries, dict) or not entries:
        raise ArtifactIntegrityError(f"empty artifact hash manifest: {manifest}")
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in entries.items()):
        raise ArtifactIntegrityError(f"artifact hash entries must be string pairs: {manifest}")
    return entries


def verify_artifact_package(
    package: Path,
    required_entries: tuple[str, ...] = (),
) -> int:
    """Verify every authority hash and require critical files to be covered."""

    package = package.resolve()
    manifest = package / "artifact_hashes.json"
    entries = _hash_entries(load_json(manifest), manifest)
    missing_entries = sorted(set(required_entries) - set(entries))
    if missing_entries:
        raise ArtifactIntegrityError(
            f"critical files absent from artifact hash manifest: {missing_entries}"
        )
    for relative, expected in entries.items():
        path_part = PurePosixPath(relative)
        if (
            path_part.is_absolute()
            or ".." in path_part.parts
            or path_part.name.startswith("._")
        ):
            raise ArtifactIntegrityError(f"unsafe artifact hash path: {relative}")
        if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
            raise ArtifactIntegrityError(f"invalid SHA-256 value for {relative}")
        target = package.joinpath(*path_part.parts)
        if not target.is_file():
            raise ArtifactIntegrityError(f"missing hashed artifact: {target}")
        if sha256(target) != expected:
            raise ArtifactIntegrityError(f"artifact hash drift: {target}")
    return len(entries)


def require_decision(
    path: Path,
    verdict_prefix: str,
    required_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Require an accepted decision and exact safety-critical field values."""

    payload = load_json(path)
    verdict = payload.get("verdict", payload.get("decision", ""))
    if not isinstance(verdict, str) or not verdict.startswith(verdict_prefix):
        raise ArtifactIntegrityError(f"unaccepted decision in {path}: {verdict!r}")
    for field, expected in (required_fields or {}).items():
        if payload.get(field) != expected:
            raise ArtifactIntegrityError(
                f"decision field mismatch in {path}: {field}={payload.get(field)!r}"
            )
    return payload
