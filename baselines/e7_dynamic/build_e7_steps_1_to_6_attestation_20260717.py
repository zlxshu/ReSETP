#!/usr/bin/env python3
"""Build the post-closeout E7 steps 1--6 attestation without any search.

The builder reads only five sealed evidence surfaces explicitly supplied to it:
formal E7, 28-day replay, replay invariants, independent total audit, and the
paper-evidence manifest.  It never scans checkpoints, monitor directories, or
intermediate E7 state.  A failed gate returns HALT and never publishes the
formal attestation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping


REPO = Path(__file__).resolve().parents[2]
DEFAULT_SOURCES = {
    "formal": REPO / "baselines/e7_dynamic/e7_multinetwork_formal_20260715",
    "replay": REPO / "baselines/e7_dynamic/e7_multiday_zero_search_replay_20260715",
    "replay_invariants": REPO / "baselines/e7_dynamic/e7_replay_invariants_audit_20260715",
    "independent_audit": REPO / "baselines/e7_dynamic/e7_multinetwork_independent_audit_20260715",
    "paper": REPO / "docs/paper_submission_final/generated_tables",
}
DEFAULT_OUTPUT = REPO / "baselines/e7_dynamic/e7_steps_1_to_6_attestation_20260717.json"
PAPER_BUILDER = REPO / "baselines/paper_story/build_20260715_formal_evidence.py"
PAPER_MANIFEST_NAME = "e7_dynamic_paper_evidence_manifest.json"
RECORD_SURFACES = ("metadata.json", "raw_runs.csv", "decision.json", "artifact_hashes.json", "report.md")
SCHEMA = "resetp.e7.steps-1-to-6-attestation.v1"
PAPER_EXHIBITS = (
    "e7_dynamic_policy_comparison.tex",
    "e7_dynamic_mechanism_diagnostics.tex",
    "e7_dynamic_charging_replay.tex",
    "e7_dynamic_interpretation.tex",
    "e7_dynamic_conclusion.tex",
    "e7_dynamic_abstract_zh.tex",
    "e7_dynamic_abstract_en.tex",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(payload: Any) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def evidence_key(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO.resolve()))
    except ValueError:
        return str(path.resolve())


def verify_record_package(name: str, root: Path) -> tuple[dict[str, Any], dict[str, str]]:
    missing = [surface for surface in RECORD_SURFACES if not (root / surface).is_file()]
    if missing:
        raise ValueError(f"{name}: missing record surfaces: {missing}")
    manifest_path = root / "artifact_hashes.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError(f"{name}: artifact manifest is empty")
    failures: list[str] = []
    for relative, expected in manifest.items():
        path = root / relative
        if not path.is_file() or sha256(path) != expected:
            failures.append(relative)
    for surface in ("metadata.json", "raw_runs.csv", "decision.json", "report.md"):
        if manifest.get(surface) != sha256(root / surface):
            failures.append(surface)
    if failures:
        raise ValueError(f"{name}: manifest mismatch: {sorted(set(failures))}")
    if list(root.rglob("._*")):
        raise ValueError(f"{name}: AppleDouble contamination")
    evidence = {evidence_key(root / relative): expected for relative, expected in manifest.items()}
    evidence[evidence_key(manifest_path)] = sha256(manifest_path)
    return json.loads((root / "decision.json").read_text(encoding="utf-8")), evidence


def _validate_decisions(decisions: Mapping[str, Mapping[str, Any]], formal_metadata: Mapping[str, Any]) -> None:
    formal = decisions["formal"]
    if formal.get("verdict") not in {
        "E7_FORMAL_EVIDENCE_COMPLETE",
        "E7_FORMAL_EVIDENCE_COMPLETE_WITH_ARM_FAILURES",
    } or formal.get("failures"):
        raise ValueError("formal E7 decision does not pass")
    if int(formal_metadata.get("task_count", -1)) != 120:
        raise ValueError("formal E7 metadata does not contain exactly 120 tasks")
    replay = decisions["replay"]
    replay_expected = {
        "formal_task_count": 120,
        "replayed_full_day_task_count": 30,
        "operating_day_count": 28,
        "paired_day_row_count": 840,
        "route_hash_failures": 0,
        "energy_hash_failures": 0,
        "route_search_evaluations": 0,
    }
    if replay.get("status") != "PASS_E7_28DAY_ZERO_SEARCH_CHARGING_REPLAY" or any(
        int(replay.get(key, -1)) != value for key, value in replay_expected.items()
    ):
        raise ValueError("28-day E7 replay does not pass exact zero-search counts")
    invariants = decisions["replay_invariants"]
    invariant_expected = {
        "full_task_count": 30,
        "task_day_row_count": 840,
        "window_violation_count": 0,
        "station_capacity_violation_count": 0,
        "route_hash_failure_count": 0,
        "energy_hash_failure_count": 0,
        "emissions_recalculation_failure_count": 0,
        "route_search_evaluations": 0,
    }
    if invariants.get("status") != "PASS_E7_REPLAY_INVARIANTS_AUDIT" or any(
        int(invariants.get(key, -1)) != value for key, value in invariant_expected.items()
    ) or not invariants.get("checks") or not all(invariants["checks"].values()):
        raise ValueError("E7 replay-invariants decision does not pass exact counts")
    independent = decisions["independent_audit"]
    empty_fields = (
        "formal_hash_failures",
        "replay_hash_failures",
        "replay_invariant_hash_failures",
        "replay_row_failures",
        "economic_closure_failures",
        "external_pause_timing_contamination",
    )
    if (
        independent.get("verdict") != "PASS_E7_MULTINETWORK_FORMAL_AND_REPLAY_INDEPENDENT_AUDIT"
        or not independent.get("checks")
        or not all(independent["checks"].values())
        or any(independent.get(field) for field in empty_fields)
    ):
        raise ValueError("E7 independent total audit does not pass")


def verify_paper_manifest(
    paper_root: Path,
    replay_root: Path,
    audit_root: Path,
) -> tuple[dict[str, Any], dict[str, str]]:
    path = paper_root / PAPER_MANIFEST_NAME
    if not path.is_file():
        raise ValueError("paper: E7 paper-evidence manifest is missing")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "resetp.e7.paper-evidence.v1":
        raise ValueError("paper: manifest schema differs")
    if not PAPER_BUILDER.is_file() or manifest.get("builder_sha256") != sha256(PAPER_BUILDER):
        raise ValueError("paper: evidence builder hash differs")
    coverage = manifest.get("coverage", {})
    expected_coverage = {
        "formal_tasks": 120,
        "stream_pairs": 30,
        "network_condition_cells": 6,
        "replay_pairs": 840,
        "reader_facing_exhibits": 7,
    }
    if any(int(coverage.get(key, -1)) != value for key, value in expected_coverage.items()):
        raise ValueError("paper: coverage differs")
    generated = manifest.get("generated_hashes", {})
    if set(generated) != set(PAPER_EXHIBITS):
        raise ValueError("paper: seven-exhibit inventory differs")
    evidence = {
        evidence_key(path): sha256(path),
        evidence_key(PAPER_BUILDER): sha256(PAPER_BUILDER),
    }
    for name, expected in generated.items():
        exhibit = paper_root / name
        if not exhibit.is_file() or sha256(exhibit) != expected:
            raise ValueError(f"paper: generated exhibit differs: {name}")
        evidence[evidence_key(exhibit)] = expected
    roots = {"independent_audit": audit_root, "28day_replay": replay_root}
    source_hashes = manifest.get("source_hashes", {})
    if not source_hashes:
        raise ValueError("paper: source hash map is empty")
    for label, expected in source_hashes.items():
        prefix, separator, relative = label.partition("/")
        if not separator or prefix not in roots:
            raise ValueError(f"paper: unsupported source label: {label}")
        source = roots[prefix] / relative
        if not source.is_file() or sha256(source) != expected:
            raise ValueError(f"paper: source differs: {label}")
        evidence[evidence_key(source)] = expected
    return manifest, evidence


def build_attestation(
    sources: Mapping[str, Path],
    output: Path,
    publish: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    failures: list[str] = []
    evidence_hashes: dict[str, str] = {}
    decisions: dict[str, Any] = {}
    formal_metadata: dict[str, Any] = {}
    for name in ("formal", "replay", "replay_invariants", "independent_audit"):
        root = Path(sources[name])
        try:
            decision, evidence = verify_record_package(name, root)
            decisions[name] = decision
            evidence_hashes.update(evidence)
            if name == "formal":
                formal_metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            failures.append(str(exc))
    paper_manifest: dict[str, Any] = {}
    try:
        paper_manifest, paper_evidence = verify_paper_manifest(
            Path(sources["paper"]),
            Path(sources["replay"]),
            Path(sources["independent_audit"]),
        )
        evidence_hashes.update(paper_evidence)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        failures.append(str(exc))
    if not failures:
        try:
            _validate_decisions(decisions, formal_metadata)
        except (ValueError, KeyError, TypeError) as exc:
            failures.append(str(exc))
    contract_hashes = {
        key: value
        for key, value in formal_metadata.items()
        if key.endswith("contract_sha256") and isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
    }
    if not failures and not contract_hashes:
        failures.append("formal E7 metadata lacks a sealed search-contract hash")
    decision = {
        "verdict": "PASS_E7_STEPS_1_TO_6_ATTESTATION_READY" if not failures else "HALT_E7_STEPS_1_TO_6_ATTESTATION",
        "failures": failures,
        "search_performed": False,
        "route_search_evaluations": 0,
        "formal_attestation_published": bool(publish and not failures),
    }
    if failures:
        return decision, None
    evidence_hashes[evidence_key(Path(__file__).resolve())] = sha256(Path(__file__).resolve())
    search_version = canonical_sha256(
        {
            "formal_search_contract_hashes": contract_hashes,
            "formal_decision_sha256": evidence_hashes[evidence_key(Path(sources["formal"]) / "decision.json")],
        }
    )
    payload = {
        "schema_version": SCHEMA,
        "steps_1_to_6_complete": True,
        "search_version_closed": True,
        "search_version": search_version,
        "formal_search_contract_hashes": contract_hashes,
        "evidence_hashes": dict(sorted(evidence_hashes.items())),
        "paper_evidence_manifest_sha256": sha256(Path(sources["paper"]) / PAPER_MANIFEST_NAME),
        "paper_coverage": paper_manifest["coverage"],
        "route_search_evaluations_during_attestation": 0,
        "builder_sha256": sha256(Path(__file__).resolve()),
    }
    if publish:
        atomic_json(output, payload)
    return decision, payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--formal-root", type=Path, default=DEFAULT_SOURCES["formal"])
    parser.add_argument("--replay-root", type=Path, default=DEFAULT_SOURCES["replay"])
    parser.add_argument("--replay-invariants-root", type=Path, default=DEFAULT_SOURCES["replay_invariants"])
    parser.add_argument("--independent-audit-root", type=Path, default=DEFAULT_SOURCES["independent_audit"])
    parser.add_argument("--paper-root", type=Path, default=DEFAULT_SOURCES["paper"])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    decision, _ = build_attestation(
        {
            "formal": args.formal_root,
            "replay": args.replay_root,
            "replay_invariants": args.replay_invariants_root,
            "independent_audit": args.independent_audit_root,
            "paper": args.paper_root,
        },
        args.output,
        args.publish,
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if decision["verdict"].startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
