#!/usr/bin/env python3
"""Build the four atomic manuscript exhibits from sealed SINTEF evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

from baselines.e2_alns import run_solomon_sintef_formal_20260717 as runner


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / "baselines/e2_alns/e2_solomon_sintef_formal_20260717"
DEFAULT_OUTPUT = ROOT / "docs/paper_submission_final/generated_tables"
TABLE_NAME = "e2_solomon_benchmark.tex"
CLASS_TABLE_NAME = "e2_solomon_class_summary.tex"
INTERPRETATION_NAME = "e2_solomon_interpretation.tex"
PROVENANCE_NAME = "e2_solomon_paper_evidence_manifest.json"
REQUIRED_SOURCE_FILES = (
    "metadata.json",
    "contract.json",
    "raw_runs.csv",
    "decision.json",
    "artifact_hashes.json",
    "report.md",
    "instance_summary.csv",
    "class_summary.csv",
    "solutions.jsonl",
    "cpu_contract_snapshot.json",
    "run_state.json",
    "task_artifact_hashes.json",
)
DISPLAY_INSTANCES = (
    "C101", "C109", "C201", "C208", "R101", "R112",
    "R201", "R211", "RC101", "RC108", "RC201", "RC208",
)


class E2SolomonEvidenceError(RuntimeError):
    """Raised when sealed formal evidence cannot support a paper exhibit."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def truthy(value: object) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def verify_source_manifest(source: Path) -> None:
    sidecars = list(source.rglob("._*"))
    if sidecars:
        raise E2SolomonEvidenceError("formal Solomon evidence contains AppleDouble files")
    manifest = json.loads((source / "artifact_hashes.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise E2SolomonEvidenceError("formal artifact manifest is not a mapping")
    observed = {
        str(path.relative_to(source))
        for path in source.rglob("*")
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and ".tasks" not in path.parts
        and not path.name.startswith("._")
    }
    if observed != set(manifest):
        raise E2SolomonEvidenceError(
            f"formal artifact inventory differs: unlisted={sorted(observed-set(manifest))}, "
            f"missing={sorted(set(manifest)-observed)}"
        )
    drift = [relative for relative, expected in manifest.items() if sha256(source / relative) != expected]
    if drift:
        raise E2SolomonEvidenceError(f"formal artifact hash drift: {drift}")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def normalized_raw_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    integer_fields = {
        "seed", "route_count", "bks_vehicle_count", "eval_budget", "evaluations",
        "candidate_scores", "repair_delta_count", "violation_count",
    }
    float_fields = {
        "distance_double", "distance_rounded_2", "bks_distance", "distance_gap_pct",
        "process_cpu_seconds", "elapsed_seconds", "task_elapsed_seconds",
        "time_to_best_seconds",
    }
    boolean_fields = {
        "reached_bks_vehicle_count", "full_bks_hit", "bks_conflict_candidate",
        "algorithm_reported_feasible", "feasible", "independent_recompute_pass", "timeout",
    }
    output: list[dict[str, Any]] = []
    for row in rows:
        normalized: dict[str, Any] = dict(row)
        for field in integer_fields:
            normalized[field] = int(row[field])
        for field in float_fields:
            normalized[field] = "" if row[field] == "" else float(row[field])
        for field in boolean_fields:
            normalized[field] = truthy(row[field])
        output.append(normalized)
    return output


def assert_summary_rows_match_raw(
    rows: list[dict[str, str]],
    instances: list[dict[str, str]],
    classes: list[dict[str, str]],
) -> None:
    """Reject sealed summaries that do not reproduce from the 560 raw rows."""

    expected_instances = runner.build_instance_summary(normalized_raw_rows(rows))
    expected_classes = runner.build_class_summary(expected_instances)
    for label, actual_rows, expected_rows, key in (
        ("instance", instances, expected_instances, "instance"),
        ("class", classes, expected_classes, "class"),
    ):
        actual = {row[key]: row for row in actual_rows}
        expected = {str(row[key]): row for row in expected_rows}
        if set(actual) != set(expected):
            raise E2SolomonEvidenceError(f"{label} summary identities differ from raw rows")
        for identity, expected_row in expected.items():
            actual_row = actual[identity]
            for field, expected_value in expected_row.items():
                if field not in actual_row:
                    raise E2SolomonEvidenceError(f"{label} summary field missing: {identity}/{field}")
                actual_value = actual_row[field]
                if expected_value == "":
                    matches = actual_value == ""
                elif isinstance(expected_value, str):
                    matches = actual_value == expected_value
                else:
                    try:
                        matches = math.isclose(
                            float(actual_value),
                            float(expected_value),
                            rel_tol=1e-10,
                            abs_tol=1e-8,
                        )
                    except (TypeError, ValueError):
                        matches = False
                if not matches:
                    raise E2SolomonEvidenceError(
                        f"{label} summary differs from raw rows: {identity}/{field}"
                    )


def validate_solution_records(
    source: Path,
    rows: list[dict[str, str]],
    expected_keys: set[str],
) -> None:
    try:
        records = [
            json.loads(line)
            for line in (source / "solutions.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError) as exc:
        raise E2SolomonEvidenceError(f"formal solution records cannot be read: {exc}") from exc
    keys = [str(record.get("task_key", "")) for record in records]
    if len(records) != len(expected_keys) or set(keys) != expected_keys or len(set(keys)) != len(expected_keys):
        raise E2SolomonEvidenceError("formal solution-record identities differ")
    raw_by_key = {row["task_key"]: row for row in rows}
    for record in records:
        key = str(record["task_key"])
        raw = raw_by_key[key]
        if (
            str(record.get("instance")) != raw["instance"]
            or int(record.get("seed", -1)) != int(raw["seed"])
            or str(record.get("status")) != raw["status"]
        ):
            raise E2SolomonEvidenceError(f"formal solution-record identity differs: {key}")
        solution = record.get("solution")
        if not isinstance(solution, dict):
            raise E2SolomonEvidenceError(f"formal solution payload is invalid: {key}")
        solution_hash = runner.canonical_sha256(solution)
        if solution_hash != record.get("solution_sha256") or solution_hash != raw["solution_sha256"]:
            raise E2SolomonEvidenceError(f"formal solution hash differs: {key}")
        recomputed = runner.pure_vrptw_recompute(
            solution,
            runner.BUNDLES / str(record["instance"]),
        )
        if truthy(raw["independent_recompute_pass"]) != bool(recomputed["passed"]):
            raise E2SolomonEvidenceError(f"formal solution feasibility differs: {key}")
        if int(raw["route_count"]) != int(recomputed["route_count"]):
            raise E2SolomonEvidenceError(f"formal solution route count differs: {key}")
        if not math.isclose(
            float(raw["distance_double"]),
            float(recomputed["distance_double"]),
            rel_tol=1e-10,
            abs_tol=1e-8,
        ):
            raise E2SolomonEvidenceError(f"formal solution distance differs: {key}")
        if not math.isclose(
            float(raw["distance_rounded_2"]),
            float(recomputed["distance_rounded_2"]),
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise E2SolomonEvidenceError(f"formal rounded solution distance differs: {key}")
        if int(raw["violation_count"]) != len(recomputed["failures"]):
            raise E2SolomonEvidenceError(f"formal solution violation count differs: {key}")
        expected_feasible = truthy(raw["algorithm_reported_feasible"]) and bool(recomputed["passed"])
        if truthy(raw["feasible"]) != expected_feasible:
            raise E2SolomonEvidenceError(f"formal solution feasible flag differs: {key}")
        sealed_recompute = record.get("independent_recomputation")
        if not isinstance(sealed_recompute, dict) or runner.canonical_sha256(sealed_recompute) != runner.canonical_sha256(recomputed):
            raise E2SolomonEvidenceError(f"sealed independent recomputation differs: {key}")


def assert_decision_matches_raw(decision: dict[str, Any], rows: list[dict[str, str]]) -> None:
    raw_failures = sorted(row["task_key"] for row in rows if row.get("status") != "OK")
    expected_verdict = "FORMAL_COMPLETE" if not raw_failures else "FORMAL_COMPLETE_WITH_ALGORITHM_FAILURES"
    if (
        decision.get("verdict") != expected_verdict
        or sorted(decision.get("failures", [])) != raw_failures
        or int(decision.get("failure_count", -1)) != len(raw_failures)
        or decision.get("all_unfavorable_results_retained") is not True
    ):
        raise E2SolomonEvidenceError("formal decision failures differ from raw rows")
    conflict_count = sum(truthy(row.get("bks_conflict_candidate")) for row in rows)
    if int(decision.get("bks_conflict_candidate_count", -1)) != conflict_count:
        raise E2SolomonEvidenceError("formal BKS conflict count differs from raw rows")


def verify_task_artifact_manifest(source: Path) -> None:
    manifest = json.loads((source / "task_artifact_hashes.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise E2SolomonEvidenceError("formal task-artifact manifest is not a mapping")
    observed = {
        str(path.relative_to(source))
        for path in (source / ".tasks").rglob("*")
        if path.is_file() and not path.name.startswith("._")
    }
    if set(manifest) != observed:
        raise E2SolomonEvidenceError("formal task-artifact inventory differs")
    drift = [relative for relative, expected in manifest.items() if sha256(source / relative) != expected]
    if drift:
        raise E2SolomonEvidenceError(f"formal task-artifact hash drift: {drift[:5]}")


def load_and_validate(source: Path) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    missing = [name for name in REQUIRED_SOURCE_FILES if not (source / name).is_file()]
    if missing:
        raise E2SolomonEvidenceError(f"formal evidence files are missing: {missing}")
    verify_source_manifest(source)
    verify_task_artifact_manifest(source)
    metadata = json.loads((source / "metadata.json").read_text(encoding="utf-8"))
    contract = json.loads((source / "contract.json").read_text(encoding="utf-8"))
    decision = json.loads((source / "decision.json").read_text(encoding="utf-8"))
    run_state = json.loads((source / "run_state.json").read_text(encoding="utf-8"))
    cpu_snapshot = json.loads((source / "cpu_contract_snapshot.json").read_text(encoding="utf-8"))
    if metadata.get("schema_version") != runner.CONTRACT_SCHEMA:
        raise E2SolomonEvidenceError("formal metadata schema differs")
    if int(metadata.get("task_count", -1)) != 560 or int(metadata.get("instance_count", -1)) != 56:
        raise E2SolomonEvidenceError("formal task or instance count differs")
    if decision.get("verdict") not in {"FORMAL_COMPLETE", "FORMAL_COMPLETE_WITH_ALGORITHM_FAILURES"}:
        raise E2SolomonEvidenceError("formal decision is incomplete")
    if int(decision.get("task_count", -1)) != 560 or int(decision.get("expected_task_count", -1)) != 560:
        raise E2SolomonEvidenceError("formal decision matrix differs")
    if int(decision.get("bks_conflict_candidate_count", -1)) != 0:
        raise E2SolomonEvidenceError("BKS conflict candidates require independent audit before publication")
    contract_sha = str(contract.get("contract_sha256", ""))
    if not contract_sha or metadata.get("contract_sha256") != contract_sha:
        raise E2SolomonEvidenceError("formal contract hash differs across evidence surfaces")
    contract_body = {
        key: value
        for key, value in contract.items()
        if key not in {"contract_sha256", "created_at_utc", "git_head_at_start"}
    }
    if runner.canonical_sha256(contract_body) != contract_sha:
        raise E2SolomonEvidenceError("formal contract body hash differs")
    if metadata.get("algorithm_version") != contract.get("algorithm_version"):
        raise E2SolomonEvidenceError("formal algorithm version differs across evidence surfaces")
    if int(contract.get("eval_budget", -1)) != runner.FORMAL_EVAL_BUDGET:
        raise E2SolomonEvidenceError("formal contract evaluation budget differs")
    if runner.canonical_sha256(cpu_snapshot) != runner.canonical_sha256(contract.get("cpu_contract")):
        raise E2SolomonEvidenceError("formal CPU contract snapshot differs")
    if run_state.get("verdict") != decision.get("verdict") or int(run_state.get("completed_task_count", -1)) != 560 or int(run_state.get("expected_task_count", -1)) != 560:
        raise E2SolomonEvidenceError("formal final run state differs from decision")

    rows = read_csv(source / "raw_runs.csv")
    expected_keys = {
        runner.task_key(name, seed)
        for name in runner.FORMAL_INSTANCES
        for seed in runner.FORMAL_SEEDS
    }
    observed_keys = [row.get("task_key", "") for row in rows]
    if len(rows) != 560 or set(observed_keys) != expected_keys or len(set(observed_keys)) != 560:
        raise E2SolomonEvidenceError("formal raw task identities differ")
    assert_decision_matches_raw(decision, rows)
    validate_solution_records(source, rows, expected_keys)
    references = runner.read_references()
    for row in rows:
        reference = references[row["instance"]]
        expected_key = runner.task_key(row["instance"], int(row["seed"]))
        if row["task_key"] != expected_key or row["class"] != reference["class"]:
            raise E2SolomonEvidenceError(f"formal raw task mapping differs: {row['task_key']}")
        if int(row["eval_budget"]) != runner.FORMAL_EVAL_BUDGET:
            raise E2SolomonEvidenceError(f"evaluation budget differs: {row['task_key']}")
        if row.get("algorithm_version") != metadata.get("algorithm_version"):
            raise E2SolomonEvidenceError(f"algorithm version differs: {row['task_key']}")
        if int(row["bks_vehicle_count"]) != reference["bks_vehicle_count"]:
            raise E2SolomonEvidenceError(f"BKS vehicle count differs: {row['task_key']}")
        if float(row["bks_distance"]) != reference["bks_distance_published_2dp"]:
            raise E2SolomonEvidenceError(f"BKS distance differs: {row['task_key']}")
        assessment = runner.reference_assessment(
            int(row["route_count"]),
            float(row["distance_rounded_2"]),
            reference["bks_vehicle_count"],
            reference["bks_distance_published_2dp"],
        )
        for field in ("reached_bks_vehicle_count", "full_bks_hit", "bks_conflict_candidate"):
            if truthy(row[field]) != bool(assessment[field]):
                raise E2SolomonEvidenceError(f"reference assessment differs: {row['task_key']}/{field}")
        expected_gap = assessment["distance_gap_pct"]
        if expected_gap == "":
            if row["distance_gap_pct"] != "":
                raise E2SolomonEvidenceError(f"distance Gap is defined for excess vehicles: {row['task_key']}")
        elif abs(float(row["distance_gap_pct"]) - float(expected_gap)) > 1e-10:
            raise E2SolomonEvidenceError(f"distance Gap differs: {row['task_key']}")
        if row["status"] == "OK":
            if not truthy(row["feasible"]) or not truthy(row["independent_recompute_pass"]):
                raise E2SolomonEvidenceError(f"OK row is not independently feasible: {row['task_key']}")
            if int(row["evaluations"]) != runner.FORMAL_EVAL_BUDGET or int(row["candidate_scores"]) != runner.FORMAL_EVAL_BUDGET:
                raise E2SolomonEvidenceError(f"OK row does not close evaluation budget: {row['task_key']}")
        try:
            failure_codes = json.loads(row["failure_codes"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise E2SolomonEvidenceError(f"failure codes are invalid: {row['task_key']}") from exc
        if not isinstance(failure_codes, list) or (row["status"] == "OK") != (not failure_codes):
            raise E2SolomonEvidenceError(f"status and failure codes differ: {row['task_key']}")
        expected_infeasible = (
            not truthy(row["algorithm_reported_feasible"])
            or not truthy(row["independent_recompute_pass"])
        )
        if ("INFEASIBLE" in failure_codes) != expected_infeasible:
            raise E2SolomonEvidenceError(f"infeasible failure code differs: {row['task_key']}")
        if ("TIMEOUT" in failure_codes) != truthy(row["timeout"]):
            raise E2SolomonEvidenceError(f"timeout failure code differs: {row['task_key']}")
    instances = read_csv(source / "instance_summary.csv")
    classes = read_csv(source / "class_summary.csv")
    if len(instances) != 56 or {row["instance"] for row in instances} != set(runner.FORMAL_INSTANCES):
        raise E2SolomonEvidenceError("instance summary does not cover all 56 instances")
    if [row["class"] for row in classes] != ["C1", "C2", "R1", "R2", "RC1", "RC2"]:
        raise E2SolomonEvidenceError("class summary order or coverage differs")
    assert_summary_rows_match_raw(rows, instances, classes)
    return rows, instances, classes, {
        "metadata": metadata,
        "contract": contract,
        "decision": decision,
        "run_state": run_state,
    }


def number(row: dict[str, str], field: str, digits: int) -> str:
    value = row.get(field, "")
    return "--" if value == "" else f"{float(value):.{digits}f}"


def pair(row: dict[str, str], left: str, right: str, digits: int = 2) -> str:
    if row.get(left, "") == "" or row.get(right, "") == "":
        return "--"
    return f"({int(float(row[left]))},{float(row[right]):.{digits}f})"


def render_instance_table(instances: list[dict[str, str]]) -> str:
    by_name = {row["instance"]: row for row in instances}
    lines = [
        r"\begin{tabular*}{0.98\linewidth}{@{\extracolsep{\fill}}lrrrrrrr@{}}",
        r"\toprule",
        r"算例 & BKS$(K,D)$ & Best$(K,D)$ & Avg$(K,D)$ & Avg Gap/\% & CPU/s & BKS命中 & 有效/Runs \\",
        r"\midrule",
    ]
    for name in DISPLAY_INSTANCES:
        row = by_name[name]
        lines.append(
            f"{name} & {pair(row, 'bks_vehicle_count', 'bks_distance')} & "
            f"{pair(row, 'best_route_count', 'best_distance')} & "
            f"{pair(row, 'avg_route_count', 'avg_distance')} & "
            f"{number(row, 'avg_gap_pct', 2)}({row['gap_valid_runs']}) & "
            f"{number(row, 'avg_process_cpu_seconds', 1)} & "
            f"{row['bks_hits']}/{row['runs']} & {row['valid_runs']}/{row['runs']} " + r"\\"
        )
    lines.extend([r"\bottomrule", r"\end{tabular*}"])
    return "\n".join(lines) + "\n"


def render_class_table(classes: list[dict[str, str]]) -> str:
    lines = [
        r"\begin{tabular*}{0.98\linewidth}{@{\extracolsep{\fill}}lrrrrrrrrr@{}}",
        r"\toprule",
        r"类别 & 算例数 & 平均$K$ & 平均$D$ & CNV & CTD & CPU/s & RT/s & $T_{best}$/s & 有效例;运行 \\",
        r"\midrule",
    ]
    for row in classes:
        lines.append(
            f"{row['class']} & {row['instance_count']} & {number(row, 'avg_best_route_count', 2)} & "
            f"{number(row, 'avg_best_distance', 2)} & {row['CNV']} & {number(row, 'CTD', 2)} & "
            f"{number(row, 'avg_process_cpu_seconds', 1)} & {number(row, 'avg_elapsed_seconds', 1)} & "
            f"{number(row, 'avg_time_to_best_seconds', 1)} & "
            f"{row['complete_instance_count']}/{row['instance_count']};{row['valid_runs']}/{row['Runs']} " + r"\\"
        )
    total_runs = sum(int(row["Runs"]) for row in classes)
    total_valid = sum(int(row["valid_runs"]) for row in classes)
    total_complete = sum(int(row["complete_instance_count"]) for row in classes)
    all_classes_complete = total_complete == 56
    total_cnv = str(sum(int(row["CNV"]) for row in classes)) if all_classes_complete else "--"
    total_ctd = f"{sum(float(row['CTD']) for row in classes):.2f}" if all_classes_complete else "--"
    lines.extend(
        [
            r"\midrule",
            f"合计 & 56 & -- & -- & {total_cnv} & {total_ctd} & -- & -- & -- & "
            f"{total_complete}/56;{total_valid}/{total_runs} "
            + r"\\",
            r"\bottomrule",
            r"\end{tabular*}",
        ]
    )
    return "\n".join(lines) + "\n"


def render_interpretation(rows: list[dict[str, str]], instances: list[dict[str, str]]) -> str:
    valid = [row for row in rows if row["status"] == "OK"]
    at_bks_k = [row for row in valid if truthy(row["reached_bks_vehicle_count"])]
    hits = sum(truthy(row["full_bks_hit"]) for row in valid)
    failures = len(rows) - len(valid)
    gap_instances = [row for row in instances if row["avg_gap_pct"] != ""]
    if gap_instances:
        best = min(gap_instances, key=lambda row: float(row["avg_gap_pct"]))
        worst = max(gap_instances, key=lambda row: float(row["avg_gap_pct"]))
        boundary = (
            f"在达到BKS车辆数且可计算距离Gap的算例中，逐例平均Gap最低为{best['instance']}的"
            f"{float(best['avg_gap_pct']):.2f}\\%，最高为{worst['instance']}的"
            f"{float(worst['avg_gap_pct']):.2f}\\%。"
        )
    else:
        boundary = "现有运行均未同时达到BKS车辆数，因而不计算距离Gap。"
    failure_text = (
        "560次运行均通过独立可行性与预算复核。"
        if failures == 0
        else f"560次运行中有{failures}次失败或无效，其任务身份和失败代码均保留在正式记录中。"
    )
    return (
        f"全部56个算例共560次独立运行中，{len(valid)}次形成有效解，{len(at_bks_k)}次达到BKS车辆数，"
        f"{hits}次命中完整BKS。{boundary}{failure_text}上述结果只评价基础VRPTW路径搜索能力，"
        "不替代后续自有算例对时变碳强度、混合车队和协同机制的检验。\n"
    )


def build(source: Path, output: Path) -> dict[str, Any]:
    rows, instances, classes, contracts = load_and_validate(source)
    exhibits = {
        TABLE_NAME: render_instance_table(instances),
        CLASS_TABLE_NAME: render_class_table(classes),
        INTERPRETATION_NAME: render_interpretation(rows, instances),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".e2-solomon-stage-", dir=output.parent) as directory:
        stage = Path(directory)
        for name, text in exhibits.items():
            atomic_text(stage / name, text)
        provenance = {
            "schema_version": "resetp.e2.solomon-sintef-paper-evidence.v1",
            "source_root": str(source.relative_to(ROOT)),
            "source_contract_sha256": contracts["metadata"]["contract_sha256"],
            "source_hashes": {name: sha256(source / name) for name in REQUIRED_SOURCE_FILES},
            "generated_hashes": {name: sha256(stage / name) for name in exhibits},
            "display_instances": list(DISPLAY_INSTANCES),
            "display_rule": "lexicographic first and last instance of each Solomon class; frozen before results",
            "full_test_coverage": {"instances": 56, "runs": 560},
            "builder_sha256": sha256(Path(__file__).resolve()),
        }
        atomic_text(
            stage / PROVENANCE_NAME,
            json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        output.mkdir(parents=True, exist_ok=True)
        # The manifest is the visibility gate.  Remove the old one before any
        # exhibit replacement and publish the new manifest last.
        (output / PROVENANCE_NAME).unlink(missing_ok=True)
        for name in exhibits:
            os.replace(stage / name, output / name)
        os.replace(stage / PROVENANCE_NAME, output / PROVENANCE_NAME)
    return provenance


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    provenance = build(args.source, args.output)
    print(json.dumps(provenance, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
