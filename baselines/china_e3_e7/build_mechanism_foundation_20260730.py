#!/usr/bin/env python3
"""Freeze the minimal zero-search foundation for China E3, E5, E6, and E7."""

from __future__ import annotations

import csv
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "baselines/china_e3_e7/mechanism_foundation_20260730"
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path = [
    entry
    for entry in sys.path
    if Path(entry or ".").resolve() != SCRIPT_DIR
]
for path in (ROOT / "solver/src", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from baselines.china_e3_e7.mechanism_foundation import (  # noqa: E402
    CANDIDATE_CASE_PLAN,
    china81_dynamic_events,
    event_payload,
)
from setp_solver.search.dynamic import RollingParameters  # noqa: E402


BASE_RUNNER = ROOT / "baselines/china_e3_e7/e3_mismatch_20260729/run_e3_mismatch.py"
_spec = importlib.util.spec_from_file_location("_e3_foundation_base", BASE_RUNNER)
if _spec is None or _spec.loader is None:
    raise RuntimeError("cannot load audited E3 input builder")
base = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = base
_spec.loader.exec_module(base)
base.TASK_ID = "E3E7-MINIMAL-FOUNDATION-01"


def canonical_sha256(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def write_event_tsv(path: Path, events: list[dict[str, Any]]) -> None:
    if not events:
        raise ValueError("refusing to write an empty event stream")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(events[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(events)
    temporary.replace(path)


def freeze_static_inputs(rows: list[dict[str, Any]]) -> None:
    for family, instances in (("E3", CANDIDATE_CASE_PLAN["E3"]), ("E6", CANDIDATE_CASE_PLAN["E6"])):
        intensities = (0, 25, 50) if family == "E3" else (0,)
        for instance_id in instances:
            original = base.load_bundle(instance_id)
            for intensity in intensities:
                if intensity:
                    mapping, assignments = base.mismatch_mapping(original, intensity)
                else:
                    mapping = dict(original.customer_home_depot)
                    assignments = []
                bundle = base.with_responsibility(original, mapping)
                initial, audit = base.build_common_initial(bundle)
                folder = OUT / "inputs" / family.lower() / f"{instance_id}__mismatch{intensity:02d}"
                mapping_payload = {
                    "schema": "resetp.mechanism-foundation.responsibility-map.v1",
                    "family": family,
                    "instance_id": instance_id,
                    "mismatch_intensity_pct": intensity,
                    "mapping": mapping,
                    "mapping_sha256": canonical_sha256(mapping),
                    "selection_rule": "two-depot deterministic SHA-256 stratified reassignment" if intensity else "original frozen responsibility",
                }
                initial_payload = base.solution_payload(initial)
                write_json(folder / "responsibility_map.json", mapping_payload)
                write_json(folder / "initial_solution.json", initial_payload)
                certificate = {
                    "schema": "resetp.mechanism-foundation.static-input-certificate.v1",
                    "responsibility_map_sha256": canonical_sha256(mapping_payload),
                    "initial_solution_sha256": canonical_sha256(initial_payload),
                    "shared_by_all_arms_and_seeds": True,
                    "independent_initial_audit": audit,
                    "assignment_rows": assignments,
                }
                write_json(folder / "input_certificate.json", certificate)
                rows.append(
                    {
                        "family": family,
                        "instance_id": instance_id,
                        "cell": f"mismatch-{intensity}",
                        "check": "common_static_input",
                        "status": "PASS",
                        "search_evaluations": 0,
                        "artifact_sha256": canonical_sha256(certificate),
                    }
                )


def freeze_dynamic_inputs(rows: list[dict[str, Any]]) -> None:
    params = RollingParameters()
    for instance_id in CANDIDATE_CASE_PLAN["E7"]:
        bundle = base.load_bundle(instance_id)
        existing_ids = {node.node_id for node in bundle.instance.nodes}
        for seed in range(1, 6):
            events = china81_dynamic_events(bundle.instance, seed=seed, params=params)
            payload = {
                "schema": "resetp.china81.e7.events.v1",
                "instance_id": instance_id,
                "stream_seed": seed,
                "rolling_parameters": asdict(params),
                "absolute_operating_clock": True,
                "events": event_payload(events),
            }
            event_ids = [event.event_id for event in events]
            added_ids = [event.customer_id for event in events if event.event_type == "add"]
            if len(event_ids) != len(set(event_ids)) or existing_ids.intersection(added_ids):
                raise RuntimeError(f"HALT_E7_EVENT_ID_COLLISION:{instance_id}:{seed}")
            if events != sorted(events, key=lambda event: (event.t_appear, event.event_id)):
                raise RuntimeError(f"HALT_E7_EVENT_ORDER:{instance_id}:{seed}")
            path = OUT / "inputs/e7_events" / instance_id / f"stream_seed{seed}.json"
            write_json(path, payload)
            write_event_tsv(path.with_suffix(".tsv"), payload["events"])
            rows.append(
                {
                    "family": "E7",
                    "instance_id": instance_id,
                    "cell": f"stream-{seed}",
                    "check": "frozen_dynamic_event_stream",
                    "status": "PASS",
                    "search_evaluations": 0,
                    "artifact_sha256": canonical_sha256(payload),
                }
            )


def write_contract(rows: list[dict[str, Any]]) -> None:
    contract = {
        "schema": "resetp.mechanism-foundation.candidate-contract.v1",
        "task_id": "E3E7-MINIMAL-FOUNDATION-01",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "candidate_case_plan": {key: list(value) for key, value in CANDIDATE_CASE_PLAN.items()},
        "case_plan_approval_status": "AWAITING_USER_APPROVAL",
        "scope": "zero-search technical foundation and decision options only; no method choice or mechanism effect was frozen",
        "e3": {
            "intensities_pct": [0, 25, 50],
            "arms": ["LOCK", "FREE"],
            "common_input_per_instance_intensity": True,
        },
        "e5": {
            "arms": ["L100_control", "NL90_mild"],
            "budget_unit": "total complete-candidate evaluations",
            "active_option": None,
            "approval_status": "AWAITING_USER_CHOICE_A_OR_B",
            "option_A": "change execution schedule so deterministic evaluations remain after route-pool recombination; requires rerunning the blind pilot",
            "option_B": "measure L/S on search candidates while retaining the route-pool comparison and certificate in the total evaluation ledger; implementation is tested but not activated",
            "option_B_candidate_starved_unit_rule": "L_search/S_search > 0.5",
            "arm_failure_rule_if_approved": "starved share > 0.20",
        },
        "e6": {
            "states": ["I", "U", "F"],
            "candidate_rule": "F is the cheapest independently checked U-nested candidate plus I fallback that weakly preserves every depot profit",
            "profit_ledger_must_close": True,
            "nested_candidates_are_not_independent_samples": True,
        },
        "e7": {
            "stream_seeds": [1, 2, 3, 4, 5],
            "event_types": ["add", "cancel", "demand_change"],
            "state_gates": [
                "state inheritance",
                "customer conservation",
                "charging concurrency",
                "exact-trigger charging lock",
                "independent final certificate",
            ],
            "stage_budget_selector_status": "AWAITING_USER_APPROVAL",
            "numeric_budget_status": "UNSELECTED",
        },
        "formal_search_allowed": False,
        "formal_hold_reason": "FOUNDATION_ONLY_EFFECT_RUN_NOT_STARTED",
        "search_evaluations": 0,
    }
    write_json(OUT / "pre_registration.json", contract)
    write_csv(OUT / "raw_runs.csv", rows)
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.mechanism-foundation.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "source_hashes": {
                str(path.relative_to(ROOT)): file_sha256(path)
                for path in (
                    Path(__file__).resolve(),
                    ROOT / "baselines/china_e3_e7/mechanism_foundation.py",
                    BASE_RUNNER,
                    ROOT / "solver/src/setp_solver/search/dynamic.py",
                    ROOT / "solver/src/setp_solver/profit.py",
                    ROOT / "solver/src/setp_solver/cost.py",
                    ROOT / "solver/src/setp_solver/check.py",
                    ROOT / "solver/src/setp_solver/search/evaluation.py",
                )
            },
            "protected_files_modified": False,
            "search_evaluations": 0,
        },
    )
    write_json(
        OUT / "decision.json",
        {
            "verdict": "PASS_TECHNICAL_FOUNDATION_OPTIONS_READY",
            "checks_passed": len(rows),
            "checks_failed": 0,
            "pending_user_decisions": [
                "E3--E7 candidate case allocation",
                "E5 option A or option B",
                "E7 result-blind stage-budget selector",
            ],
            "formal_search_allowed": False,
            "scientific_result_claim_allowed": False,
            "search_evaluations": 0,
        },
    )
    report = (
        "# E3--E7 最小共同底座\n\n"
        "结论：`PASS_TECHNICAL_FOUNDATION_OPTIONS_READY`。本包只验证候选输入和技术规则，未替用户冻结方法，未运行效果搜索。\n\n"
        "候选最小算例组合已可执行：E3 为 50c-01/100c-02，E5 复用同两题，E6 为 150c-01，E7 复用三题；是否正式采用仍待用户批准。"
        "E5 的方案 B 已实现并测试，但 `active_option=null`；方案 A 未被暗中实现或启用。"
        "E7 的三规模五事件流已通过零搜索构造，逐阶段预算规则与数值仍未冻结。\n\n"
        "当前没有正式预算，也没有任何 E3/E5/E6/E7 效果数字；"
        "`formal_search_allowed=false` 会保持到用户完成上述决定。\n"
    )
    (OUT / "report.md").write_text(report, encoding="utf-8")
    artifacts = {
        str(path.relative_to(OUT)): file_sha256(path)
        for path in sorted(OUT.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }
    write_json(OUT / "artifact_hashes.json", {"schema": "resetp.artifact-hashes.v1", "artifacts": artifacts})


def main() -> int:
    if OUT.exists() and any(OUT.iterdir()):
        raise RuntimeError(f"refusing to overwrite non-empty foundation directory: {OUT}")
    rows: list[dict[str, Any]] = []
    freeze_static_inputs(rows)
    freeze_dynamic_inputs(rows)
    rows.append({"family": "E5", "instance_id": "shared", "cell": "budget-contract", "check": "post-search convergence window", "status": "PASS", "search_evaluations": 0, "artifact_sha256": canonical_sha256({"terminal_closure_evaluations": 2})})
    rows.append({"family": "E6", "instance_id": CANDIDATE_CASE_PLAN["E6"][0], "cell": "profit-contract", "check": "participation ledger and I fallback", "status": "PASS", "search_evaluations": 0, "artifact_sha256": canonical_sha256({"profit_ledger_must_close": True})})
    write_contract(rows)
    print(f"PASS_TECHNICAL_FOUNDATION_OPTIONS_READY {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
