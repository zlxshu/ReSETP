from __future__ import annotations

from pathlib import Path
import unittest

from setp_solver.search.winner_nondeterminism import (
    RESTORATION_DIR,
    classify_context_matrix,
    collect_env_fingerprint,
    self_check_gate_for_summary,
)


class WinnerNondeterminismTests(unittest.TestCase):
    def test_env_fingerprint_records_python_numpy_blas_and_alns_path(self) -> None:
        result = collect_env_fingerprint(
            Path.cwd(),
            Path("solver/reports/dr_alns_ppo_v2/restoration/test_tmp_nondeterminism"),
        )

        system = result["fingerprints"]["system"]

        self.assertIn("executable", system)
        self.assertIn("python_version", system)
        self.assertIn("numpy_version", system)
        self.assertIn("numpy_show_config", system)
        self.assertIn("alns_module_file", system)

    def test_context_matrix_classifies_internal_nondeterminism(self) -> None:
        rows = [
            _matrix_row("system_direct", "system", 1, 100.0),
            _matrix_row("system_direct", "system", 2, 101.0),
            _matrix_row("venv_direct", "venv", 1, 100.0),
            _matrix_row("venv_direct", "venv", 2, 100.0),
        ]

        result = classify_context_matrix(rows)

        self.assertEqual(result["classification"], "code_nondeterminism")
        self.assertEqual(result["unstable_contexts"], ["system_direct"])

    def test_context_matrix_classifies_environment_numeric_drift(self) -> None:
        rows = [
            _matrix_row("system_direct", "system", 1, 4779.0),
            _matrix_row("system_direct", "system", 2, 4779.0),
            _matrix_row("system_processpool", "system", 1, 4779.0),
            _matrix_row("system_processpool", "system", 2, 4779.0),
            _matrix_row("venv_direct", "venv", 1, 4909.0),
            _matrix_row("venv_direct", "venv", 2, 4909.0),
            _matrix_row("venv_official_wrapper", "venv", 1, 4909.0),
            _matrix_row("venv_official_wrapper", "venv", 2, 4909.0),
        ]

        result = classify_context_matrix(rows)

        self.assertEqual(result["classification"], "environment_numeric_drift")
        self.assertEqual(result["system_anchor"], 4779.0)
        self.assertEqual(result["venv_anchor"], 4909.0)

    def test_self_check_gate_accepts_env_internal_anchor_only_with_repeated_zero_violation_runs(self) -> None:
        classification = {"classification": "environment_numeric_drift"}

        self.assertEqual(
            self_check_gate_for_summary(classification, {"gate": "PASS_VENV_SELF_CHECK"}),
            "PASS_VENV_SELF_CHECK",
        )
        self.assertEqual(
            self_check_gate_for_summary(classification, {"gate": "HALT_VENV_SELF_CHECK"}),
            "HALT_VENV_SELF_CHECK",
        )

    def test_nondeterminism_reports_stay_under_restoration_dir(self) -> None:
        self.assertEqual(str(RESTORATION_DIR), "solver/reports/dr_alns_ppo_v2/restoration")

    def test_no_formal_runner_strings_in_nondeterminism_runner(self) -> None:
        source = Path("solver/src/setp_solver/search/winner_nondeterminism.py").read_text(encoding="utf-8")

        self.assertNotIn("formal_runner", source)
        self.assertNotIn("run_e1", source.lower())
        self.assertNotIn("run_e7", source.lower())


def _matrix_row(context_id: str, python_env: str, repeat: int, best_obj: float) -> dict[str, object]:
    return {
        "context_id": context_id,
        "python_env": python_env,
        "repeat": repeat,
        "success": True,
        "best_obj": best_obj,
        "violation_count": 0,
    }


if __name__ == "__main__":
    unittest.main()
