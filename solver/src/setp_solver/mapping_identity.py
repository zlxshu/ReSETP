"""Canonical content identity for numeric mappings.

declared_identity=PROJECT_DOMAIN
code_role=PURE_FUNCTION
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping


def mapping_sha256(values: Mapping[str, float]) -> str:
    """Hash mapping keys and exact IEEE-754 values in canonical order."""

    payload = [
        [str(key), float(value).hex()]
        for key, value in sorted(values.items())
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
