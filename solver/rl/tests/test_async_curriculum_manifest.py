from __future__ import annotations

import json
from pathlib import Path

import pytest

from dr_alns_ppo.train_async_block_ppo import _load_manifest_for_args, parse_args


REPO_ROOT = Path(__file__).resolve().parents[3]
PILOT08_MANIFEST = (
    REPO_ROOT
    / "solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot08/training_bundle_manifest_curriculum.json"
)
ASYNC_REPORT_DIR = "solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/test_curriculum_manifest"


def _pilot08_bundles_available() -> bool:
    if not PILOT08_MANIFEST.is_file():
        return False
    manifest = json.loads(PILOT08_MANIFEST.read_text(encoding="utf-8"))
    return all((REPO_ROOT / bundle / "scenario_manifest.json").is_file() for bundle in manifest.get("train", []))


@pytest.mark.skipif(not _pilot08_bundles_available(), reason="Pilot08 generated curriculum bundles are local ignored data")
def test_load_manifest_for_args_accepts_curriculum_manifest_with_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO_ROOT)
    args = parse_args(
        [
            "train",
            "--manifest",
            str(PILOT08_MANIFEST),
            "--curriculum",
            "--output-dir",
            ASYNC_REPORT_DIR,
        ]
    )

    manifest = _load_manifest_for_args(args)

    assert len(manifest["train"]) == 12
    assert not any("E-UK100_01" in bundle for bundle in manifest["train"])
    assert any("E-UK100_01" in bundle for bundle in manifest["formal_eval"])


def test_load_manifest_for_args_rejects_curriculum_manifest_without_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO_ROOT)
    args = parse_args(["train", "--manifest", str(PILOT08_MANIFEST), "--output-dir", ASYNC_REPORT_DIR])

    with pytest.raises(ValueError, match="Forbidden training bundle"):
        _load_manifest_for_args(args)


def test_curriculum_flag_is_available_on_manifest_consuming_commands() -> None:
    audit = parse_args(["audit", "--manifest", str(PILOT08_MANIFEST), "--curriculum"])
    self_check = parse_args(
        [
            "self-check",
            "--manifest",
            str(PILOT08_MANIFEST),
            "--curriculum",
            "--output-dir",
            ASYNC_REPORT_DIR,
        ]
    )
    train = parse_args(
        [
            "train",
            "--manifest",
            str(PILOT08_MANIFEST),
            "--curriculum",
            "--output-dir",
            ASYNC_REPORT_DIR,
        ]
    )

    assert audit.curriculum is True
    assert self_check.curriculum is True
    assert train.curriculum is True
