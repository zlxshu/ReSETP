from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO / "solver/scripts/experiment_acceptance.py"
SPEC = importlib.util.spec_from_file_location("experiment_acceptance", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
acceptance = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = acceptance
SPEC.loader.exec_module(acceptance)


def test_acceptance_keeps_service_and_feasibility_facts() -> None:
    common = {
        "termination_ok": True,
        "feasible_ok": True,
        "customers_complete": True,
        "demand_complete": True,
    }
    assert acceptance.assess_run(**common).accepted is True
    for field in common:
        rejected = acceptance.assess_run(**{**common, field: False})
        assert rejected.accepted is False
        assert rejected.failure_reasons


def test_result_writer_preserves_failure(tmp_path: Path) -> None:
    output = tmp_path / "failed-run"
    rejected = acceptance.assess_run(
        termination_ok=False,
        feasible_ok=True,
        customers_complete=True,
        demand_complete=True,
        success_verdict="RUN_COMPLETE",
        failure_verdict="RUN_FAILED",
    )
    acceptance.finalize_run_output(
        output,
        acceptance=rejected,
        metadata={"purpose": "unit test"},
        decision={"detail": "preserve failure"},
        report_text="# Failed run\n",
    )
    assert acceptance.result_exit_code(rejected) == 2
    metadata = json.loads((output / "metadata.json").read_text("utf-8"))
    decision = json.loads((output / "decision.json").read_text("utf-8"))
    assert metadata["status"] == "FAILED"
    assert decision["accepted"] is False
    assert decision["verdict"] == "RUN_FAILED"
    assert (output / "report.md").read_text("utf-8") == "# Failed run\n"
