from __future__ import annotations

import json
from pathlib import Path

import pytest

from setp_solver.mapping_identity import mapping_sha256
from setp_solver.pi0_manifest import load_pi0_manifest


def _write(path: Path, record: dict[str, object]) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema": "resetp.formal_pi0.v1",
                "instances": {"instance": record},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_probe_identity_is_fixed_but_not_formally_reusable(tmp_path: Path) -> None:
    values = {"D0": 10.0, "D1": 20.0}
    path = _write(
        tmp_path / "pi0.json",
        {
            "values": values,
            "source_id": "one-seed-probe",
            "value_sha256": mapping_sha256(values),
            "run_kind": "probe",
            "externally_frozen": True,
            "formal_reuse_allowed": False,
            "selected_package_sha256_by_enterprise": {
                "ENT_A": "a" * 64,
                "ENT_B": "b" * 64,
            },
        },
    )

    record = load_pi0_manifest(path)["instance"]

    assert record["values"] == values
    assert record["run_kind"] == "probe"
    assert record["externally_frozen"] is True
    assert record["formal_reuse_allowed"] is False


@pytest.mark.parametrize("bad_value", [0.0, -1.0, float("inf")])
def test_nonpositive_or_nonfinite_pi0_is_rejected(
    tmp_path: Path,
    bad_value: float,
) -> None:
    path = _write(
        tmp_path / "pi0.json",
        {"values": {"D0": bad_value}, "source_id": "bad"},
    )

    with pytest.raises(ValueError, match="positive"):
        load_pi0_manifest(path)


def test_declared_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "pi0.json",
        {
            "values": {"D0": 10.0},
            "source_id": "bad-hash",
            "value_sha256": "0" * 64,
        },
    )

    with pytest.raises(ValueError, match="hash mismatch"):
        load_pi0_manifest(path)


def test_old_formal_v1_defaults_remain_compatible(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "pi0.json",
        {"values": {"D0": 10.0}, "source_id": "legacy-formal"},
    )

    record = load_pi0_manifest(path)["instance"]

    assert record["run_kind"] == "formal"
    assert record["externally_frozen"] is True
    assert record["formal_reuse_allowed"] is True
