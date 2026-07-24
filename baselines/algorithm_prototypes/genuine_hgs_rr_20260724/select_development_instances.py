"""Verify the result-blind China81 development-instance registration."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
REGISTRATION = HERE / "development_instance_registration.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    registration = json.loads(
        REGISTRATION.read_text(encoding="utf-8")
    )
    catalog = ROOT / registration["catalog"]["path"]
    if _sha256(catalog) != registration["catalog"]["sha256"]:
        raise SystemExit("HALT_DEVELOPMENT_CATALOG_HASH_DRIFT")
    with catalog.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    salt = registration["salt"]
    verified: list[str] = []
    for stratum in registration["strata"]:
        candidates = [
            row
            for row in rows
            if row["region"] == stratum["region"]
            and int(stratum["customer_count_min"])
            <= int(row["customer_count"])
            <= int(stratum["customer_count_max"])
        ]
        ranked = sorted(
            (
                hashlib.sha256(
                    (
                        f"{salt}|{row['instance_id']}|"
                        f"{row['nodes_sha256']}"
                    ).encode("utf-8")
                ).hexdigest(),
                row,
            )
            for row in candidates
        )
        ranking_hash, selected = ranked[0]
        expected = {
            "instance_id": selected["instance_id"],
            "customer_count": int(selected["customer_count"]),
            "nodes_sha256": selected["nodes_sha256"],
            "ranking_sha256": ranking_hash,
        }
        observed = {
            key: stratum[key]
            for key in expected
        }
        if observed != expected:
            raise SystemExit(
                "HALT_DEVELOPMENT_INSTANCE_REGISTRATION_DRIFT: "
                f"{stratum['label']}: {observed!r} != {expected!r}"
            )
        verified.append(selected["instance_id"])
    print(
        "PASS_RESULT_BLIND_DEVELOPMENT_INSTANCE_REGISTRATION "
        + ",".join(verified)
    )


if __name__ == "__main__":
    main()
