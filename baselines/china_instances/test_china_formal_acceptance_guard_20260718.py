from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("china_formal_acceptance_guard_20260718.py")
SPEC = importlib.util.spec_from_file_location("formal_guard", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_current_repository_fails_closed() -> None:
    result = MODULE.evaluate()
    assert result["allowed"] is False
    assert "G1_FORMAL_FREEZE_MISSING" in result["blockers"]


def test_all_four_gates_are_required(tmp_path: Path) -> None:
    readiness = write(tmp_path / "readiness.json", {"open_blocker_count": 0})
    pending = write(tmp_path / "pending.json", {"decisions": []})
    g1 = write(tmp_path / "g1.json", {"decision": "PASS_G1_FORMALLY_FROZEN"})
    china81 = write(
        tmp_path / "china81.json",
        {
            "decision": "PASS_CHINA81_FINAL_FROZEN",
            "formal_search_allowed": True,
        },
    )
    result = MODULE.evaluate(readiness, pending, g1, china81)
    assert result["allowed"] is True
    assert result["blockers"] == []
