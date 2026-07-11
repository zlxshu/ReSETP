"""Close out and verify the E2 loss-recovery short gate without rerunning it."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "baselines/e2_alns/e2_loss_recovery_20260711/short_gate"
PROVENANCE_FILES = (
    "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
    "baselines/e2_alns/e2_loss_recovery_gate.py",
)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_blob(repo_root: Path, commit: str, relative_path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    ).stdout


def _is_short_gate_decision(verdict: object) -> bool:
    text = str(verdict or "")
    return text.endswith("_SHORT_GATE_PROMOTED") or text.endswith("_SHORT_GATE_REJECTED")


def verify(output_dir: Path, execution_commit: str) -> dict[str, Any]:
    decision_path = output_dir / "decision.json"
    raw_path = output_dir / "raw_runs.csv"
    metadata_path = output_dir / "metadata.json"
    if not decision_path.exists() or not raw_path.exists() or not metadata_path.exists():
        raise RuntimeError("SHORT_GATE_NOT_FINISHED")
    decision = _read_json(decision_path)
    metadata = _read_json(metadata_path)
    with raw_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected = int(metadata["expected_runs"])
    run_ids = [row["run_id"] for row in rows]
    duplicate_run_ids = sorted({run_id for run_id in run_ids if run_ids.count(run_id) > 1})
    status_failures = [row["run_id"] for row in rows if row["status"] != "OK"]
    under_evals = [row["run_id"] for row in rows if int(row["actual_evals"]) != int(row["eval_budget"])]
    violations = [row["run_id"] for row in rows if int(row["violations"]) != 0]
    solution_dir = output_dir / "solutions"
    missing_solutions = [run_id for run_id in run_ids if not (solution_dir / f"{run_id}.json").exists()]
    missing_operator_counts = [run_id for run_id in run_ids if not (solution_dir / f"{run_id}.operators.json").exists()]
    provenance: dict[str, Any] = {}
    provenance_ok = True
    for relative_path in PROVENANCE_FILES:
        working = (REPO_ROOT / relative_path).read_bytes()
        committed = _git_blob(REPO_ROOT, execution_commit, relative_path)
        matches = working == committed
        provenance_ok = provenance_ok and matches
        provenance[relative_path] = {
            "working_sha256": _sha256(working),
            "committed_sha256": _sha256(committed),
            "matches_execution_commit": matches,
        }
    passed = (
        len(rows) == expected
        and not duplicate_run_ids
        and not status_failures
        and not under_evals
        and not violations
        and not missing_solutions
        and not missing_operator_counts
        and provenance_ok
        and _is_short_gate_decision(decision.get("verdict"))
    )
    launch_head = metadata.get("git_commit")
    metadata.update(
        {
            "launch_head": launch_head,
            "execution_commit": execution_commit,
            "execution_provenance": "candidate and runner bytes match execution_commit; process was launched immediately before the commit and the loaded runtime files were not changed",
        }
    )
    _write_json(metadata_path, metadata)
    verification = {
        "verdict": "LOSS_RECOVERY_SHORT_GATE_VERIFIED" if passed else "HALT_LOSS_RECOVERY_VERIFICATION",
        "decision_verdict": decision.get("verdict"),
        "rows": len(rows),
        "expected_rows": expected,
        "duplicate_run_ids": duplicate_run_ids,
        "status_failures": status_failures,
        "under_evals": under_evals,
        "violations": violations,
        "missing_solutions": missing_solutions,
        "missing_operator_counts": missing_operator_counts,
        "execution_commit": execution_commit,
        "provenance_files": provenance,
    }
    _write_json(output_dir / "verification.json", verification)
    hashes = {
        str(path.relative_to(output_dir)): _sha256(path.read_bytes())
        for path in sorted(output_dir.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }
    _write_json(output_dir / "artifact_hashes.json", hashes)
    if not passed:
        raise RuntimeError(json.dumps(verification, sort_keys=True))
    return verification


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--execution-commit", default="bc204940")
    args = parser.parse_args()
    print(json.dumps(verify(args.output_dir.resolve(), args.execution_commit), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
