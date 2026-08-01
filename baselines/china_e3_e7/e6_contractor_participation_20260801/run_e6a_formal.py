#!/usr/bin/env python3
"""Run one resumable E6-A instance/seed unit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PROTOTYPE = REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
for path in (HERE, PROTOTYPE, REPO / "solver/src", REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_pilot06_direct_15 as runner

FORMAL_ITERATIONS = 100
FORMAL_ARCHIVE = 8
FORMAL_SP_SECONDS = 5.0
SMOKE_ITERATIONS = 1
SMOKE_ARCHIVE = 1
SMOKE_SP_SECONDS = 0.2

APPROVED_MAPPING_SHA256 = {
    "cn-prd-150c-01-V2-LOCATIONS": "962c926f1d0b702f9b6a27d7b8e130691a86f2ba272f5c211d8b9abd57c0a8ab",
    "cn-prd-150c-02-V2-LOCATIONS": "3e5ca59fc5fd5a37acad2fbed1786fc4846125b14e15746190b4783b7ae5713d",
    "cn-prd-150c-03-V2-LOCATIONS": "1d9e816fe73a97156f7c45a8b0884cd6059a9b643e241ef774c58c524ada5497",
    "cn-prd-200c-01-V2-LOCATIONS": "92fdeaf927cbd7d2ed0d2402e354968ae3812c61cc08bc161b94b63906995b1e",
    "cn-prd-200c-02-V2-LOCATIONS": "ee5a7c648addb21b772ce23bc6e230c0f4a27e6ae8daf40a325ac916d698da47",
    "cn-prd-200c-03-V2-LOCATIONS": "f538668afb6b378257485e39c500409a5d8d0bcd86901891937008b4a5671ec7",
}

EXPECTED_SOURCE_HASHES = {
    "baselines/china_e3_e7/e3_scattered_ownership_20260801/run_e3_capacity_rank_aligned.py": "6fb8687808c6d60a4679b6e80458b2d2f82cd3c1602516b77e2637a54aecd5ba",
    "baselines/china_e3_e7/e3_scattered_ownership_20260801/run_e3_scattered_ownership.py": "5cf2554c3c7db7ef78d32d68f609ae1b6637a635242022e6f943c326c98bc336",
    "baselines/china_e3_e7/e3_scattered_ownership_20260801/shared_runtime.py": "7661e904d6ebe3c43e6f5fdf26537e9302610e33bd532ed0efb56eeda8a72459",
    "baselines/china_e3_e7/e3_scattered_ownership_20260801/source_p_sequences.csv": "ba1226f149b04678487879640d5123413a35fe3b5bf37715127d3c76f70283c3",
    "baselines/china_e3_e7/e3e6_gates_01_20260729/gate1_d2a/fleet_caps.csv": "48fcf934e480504d22981e850e24ce0daa7ff11b2f73d4f806b6396cd9fcd367",
    "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py": "976ef21d4952b3c488300de9a8d3e351411305d26f1e2601ca17c15185d462c1",
    "baselines/china_e3_e7/e6_contractor_participation_20260801/e6_methods.py": "7b51b2b644b880935c1e8f912b56d4a031de134eb0250e7820bba3e55f001449",
    "solver/src/setp_solver/check.py": "9c81e254e05591667c8225965bb9d0ba4e8bbfc53eb0f8c61ffdb4325a1403a8",
    "solver/src/setp_solver/cost.py": "2717b4b4de39bb4c2a9a1bda602f4420cb3e3b1e87faa83678dfa64f88fc80be",
    "solver/src/setp_solver/search/evaluation.py": "c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3",
}

APPROVED_PILOT = HERE / "pilot09_direct_15_independent_initial_20260801"


def source_audit() -> dict[str, Any]:
    observed = {name: runner.sha256(REPO / name) for name in EXPECTED_SOURCE_HASHES}
    changed = [
        name
        for name, expected in EXPECTED_SOURCE_HASHES.items()
        if observed[name] != expected
    ]
    if changed:
        raise RuntimeError(f"formal source hash changed: {', '.join(changed)}")
    if not runner.verify_manifest(APPROVED_PILOT):
        raise RuntimeError("approved E6-A pilot artifact hash changed")
    current_sources = (
        Path(__file__),
        Path(runner.__file__),
    )
    return {
        "expected_source_hashes": EXPECTED_SOURCE_HASHES,
        "observed_source_hashes": observed,
        "all_sources_match": True,
        "approved_pilot_manifest_match": True,
        "runner_source_hashes": {
            str(path.relative_to(REPO)): runner.sha256(path) for path in current_sources
        },
    }


def _protect_pilots(output: Path) -> None:
    resolved = output.resolve()
    try:
        relative = resolved.relative_to(HERE.resolve())
    except ValueError:
        return
    if relative.parts and relative.parts[0].startswith("pilot"):
        raise ValueError("formal output must not overwrite a pilot directory")


def _completed_decision(
    output: Path,
    *,
    instance_id: str,
    seed: int,
    smoke: bool,
) -> dict[str, Any] | None:
    if not (output / "artifact_hashes.json").exists():
        return None
    if not runner.verify_manifest(output):
        raise RuntimeError("completed unit artifact hash mismatch")
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    expected_role = "SMOKE_ONLY" if smoke else "FORMAL_PANEL_UNIT"
    expected_budget = (
        (SMOKE_ITERATIONS, SMOKE_ARCHIVE, SMOKE_SP_SECONDS)
        if smoke
        else (FORMAL_ITERATIONS, FORMAL_ARCHIVE, FORMAL_SP_SECONDS)
    )
    observed = (
        metadata["iterations_per_view"],
        metadata["archive_candidates_per_view"],
        metadata["route_pool_sp_seconds"],
    )
    if (
        metadata["instance_id"] != instance_id
        or metadata["seed"] != seed
        or metadata["evidence_role"] != expected_role
        or observed != expected_budget
    ):
        raise RuntimeError("completed output belongs to a different unit")
    return json.loads((output / "decision.json").read_text(encoding="utf-8"))


def run_unit(
    output: Path,
    *,
    instance_id: str,
    seed: int,
    smoke: bool = False,
) -> dict[str, Any]:
    _protect_pilots(output)
    completed = _completed_decision(
        output, instance_id=instance_id, seed=seed, smoke=smoke
    )
    if completed is not None:
        return completed
    iterations, archive, sp_seconds = (
        (SMOKE_ITERATIONS, SMOKE_ARCHIVE, SMOKE_SP_SECONDS)
        if smoke
        else (FORMAL_ITERATIONS, FORMAL_ARCHIVE, FORMAL_SP_SECONDS)
    )
    return runner.run(
        output,
        runner.MULTI_MEMBER_INITIAL_COMMON,
        instance_id=instance_id,
        seed=seed,
        iterations=iterations,
        archive=archive,
        sp_seconds=sp_seconds,
        audit_fn=source_audit,
        expected_mapping_sha256=APPROVED_MAPPING_SHA256[instance_id],
        include_method_b=False,
        evidence_role="SMOKE_ONLY" if smoke else "FORMAL_PANEL_UNIT",
        resume=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--instance", required=True, choices=tuple(APPROVED_MAPPING_SHA256)
    )
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    result = run_unit(
        args.output,
        instance_id=args.instance,
        seed=args.seed,
        smoke=args.smoke,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
