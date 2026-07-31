#!/usr/bin/env python3
"""Reseal the completed E6-v3 package after monitor-owned stdout settles.

This is a packaging-only closeout.  It does not import or invoke the solver,
does not modify any formal candidate, and does not rerun either search arm.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TASK_ID = "E6-FAIRNESS-V3-20260731"
MONITOR_STDOUT = (
    "baselines/china_e3_e7/e6_fairness_v3_20260731/"
    "experiment.stdout.log"
)
REQUIRED_THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}
PROTECTED_HASHES = {
    "solver/src/setp_solver/cost.py":
        "2717b4b4de39bb4c2a9a1bda602f4420cb3e3b1e87faa83678dfa64f88fc80be",
    "solver/src/setp_solver/check.py":
        "9c81e254e05591667c8225965bb9d0ba4e8bbfc53eb0f8c61ffdb4325a1403a8",
    "solver/src/setp_solver/search/evaluation.py":
        "c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3",
    "solver/src/setp_solver/profit.py":
        "216c4f16f2e26f1c2840fa272adbf1e3ccb056c3de9403dd15b71fa5edfef1dc",
    (
        "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/"
        "route_pool_sp.py"
    ): "976ef21d4952b3c488300de9a8d3e351411305d26f1e2601ca17c15185d462c1",
    (
        "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/"
        "epochal_hgs.py"
    ): "655fa347b52a3e8ac20c5da6213c84b09ac90f96c1513ca95554753aad3f8a91",
}
EXCLUDED_DIRS = {"__pycache__", ".pytest_cache", "monitor_runtime"}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_direct(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(
            payload,
            handle,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def verify_preconditions() -> tuple[dict[str, Any], dict[str, str]]:
    wrong_env = {
        name: os.environ.get(name)
        for name, expected in REQUIRED_THREAD_ENV.items()
        if os.environ.get(name) != expected
    }
    if wrong_env:
        raise RuntimeError(f"HALT_THREAD_ENV_NOT_FROZEN:{wrong_env}")

    drift = {
        name: {
            "expected": expected,
            "actual": sha256(ROOT / name),
        }
        for name, expected in PROTECTED_HASHES.items()
        if sha256(ROOT / name) != expected
    }
    if drift:
        raise RuntimeError(
            "HALT_PROTECTED_HASH_DRIFT:"
            + json.dumps(drift, ensure_ascii=False, sort_keys=True)
        )

    done = read_json(HERE / "done.json")
    verification = read_json(HERE / "independent_verification.json")
    if done.get("status") != "COMPLETE":
        raise RuntimeError("HALT_SOURCE_DONE_NOT_COMPLETE")
    if verification.get("status") != "PASS":
        raise RuntimeError("HALT_INDEPENDENT_VERIFICATION_NOT_PASS")
    if done.get("units_total") != 20:
        raise RuntimeError("HALT_UNIT_DENOMINATOR_DRIFT")
    if verification.get("verified_units") != 20:
        raise RuntimeError("HALT_VERIFIED_UNIT_DENOMINATOR_DRIFT")
    if verification.get("joint_rerun_bitwise_identical_units") != 20:
        raise RuntimeError("HALT_JOINT_BITWISE_VERIFICATION_DRIFT")
    if verification.get("candidate_unique_solutions_verified") != 2764:
        raise RuntimeError("HALT_CANDIDATE_UNIQUE_COUNT_DRIFT")
    if verification.get("participation_satisfying_candidates_verified") != 0:
        raise RuntimeError("HALT_PARTICIPATION_COUNT_DRIFT")

    old_manifest = read_json(HERE / "artifact_hashes.json")
    missing: list[str] = []
    mismatches: list[dict[str, str]] = []
    for rel, expected in old_manifest["files"].items():
        path = ROOT / rel
        if not path.is_file():
            missing.append(rel)
            continue
        actual = sha256(path)
        if actual != expected:
            mismatches.append(
                {"path": rel, "expected": expected, "actual": actual}
            )
    if missing:
        raise RuntimeError(
            "HALT_OLD_MANIFEST_MISSING:" + json.dumps(missing)
        )
    if old_manifest.get("schema") == (
        "resetp.e6-fairness-v3.artifact-hashes.v1"
    ):
        if [row["path"] for row in mismatches] != [MONITOR_STDOUT]:
            raise RuntimeError(
                "HALT_UNEXPECTED_OLD_MANIFEST_DRIFT:"
                + json.dumps(mismatches, ensure_ascii=False, sort_keys=True)
            )
        stdout_mismatch = mismatches[0]
    elif old_manifest.get("schema") == (
        "resetp.e6-fairness-v3.artifact-hashes.v2"
    ):
        permitted_packaging_drift = {
            relative(HERE / "postrun_closeout_v3.py"),
            relative(HERE / "metadata.json"),
            relative(HERE / "decision.json"),
            relative(HERE / "report.md"),
        }
        if not {
            row["path"] for row in mismatches
        }.issubset(permitted_packaging_drift):
            raise RuntimeError(
                "HALT_RESEALED_MANIFEST_DRIFT:"
                + json.dumps(mismatches, ensure_ascii=False, sort_keys=True)
            )
        stdout_mismatch = read_json(HERE / "metadata.json")[
            "postrun_closeout"
        ]["automatic_manifest_mismatch"]
    else:
        raise RuntimeError("HALT_UNKNOWN_MANIFEST_SCHEMA")
    return old_manifest, stdout_mismatch


def update_closeout_surfaces(
    old_manifest: dict[str, Any],
    stdout_mismatch: dict[str, str],
    appledouble_paths: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    closed_at = now_iso()
    appledouble_list_sha256 = canonical_sha256(appledouble_paths)
    old_metadata = read_json(HERE / "metadata.json")
    prior_closeout = old_metadata.get("postrun_closeout", {})
    initial_cleanup_count = int(
        prior_closeout.get(
            "appledouble_initial_cleanup_count",
            96,
        )
    )
    closeout = {
        "status": "PASS",
        "completed_at_utc": closed_at,
        "reason": "MONITOR_STDOUT_MUTATED_AFTER_AUTOMATIC_MANIFEST",
        "automatic_manifest_id": prior_closeout.get(
            "automatic_manifest_id",
            old_manifest["manifest_id"],
        ),
        "resealed_predecessor_manifest_id": old_manifest["manifest_id"],
        "automatic_manifest_mismatch": stdout_mismatch,
        "automatic_manifest_other_mismatches": 0,
        "mutable_monitor_stdout_excluded_from_resealed_manifest": True,
        "appledouble_initial_cleanup_count": initial_cleanup_count,
        "appledouble_corrective_cleanup_performed": True,
        "appledouble_input_count_this_reseal": len(appledouble_paths),
        "appledouble_input_path_list_sha256":
            appledouble_list_sha256,
        "appledouble_remaining_after_cleanup": 0,
        "scientific_evidence_changed": False,
        "search_rerun_during_closeout": False,
    }

    metadata = old_metadata
    metadata["postrun_closeout"] = closeout
    exclusions = list(metadata.get("file_enumeration_exclusions", []))
    if "experiment.stdout.log (monitor-owned mutable stdout)" not in exclusions:
        exclusions.append(
            "experiment.stdout.log (monitor-owned mutable stdout)"
        )
    metadata["file_enumeration_exclusions"] = exclusions

    decision = read_json(HERE / "decision.json")
    decision["artifact_manifest_resealed"] = True
    decision["postrun_closeout_status"] = "PASS"
    decision["mutable_monitor_stdout_excluded_from_manifest"] = True
    decision.pop("appledouble_removed_count", None)
    decision["appledouble_final_scan_remaining"] = 0
    decision["scientific_evidence_changed_during_closeout"] = False
    decision["decision_id"] = canonical_sha256(
        {key: value for key, value in decision.items() if key != "decision_id"}
    )

    report_path = HERE / "report.md"
    report = report_path.read_text(encoding="utf-8")
    marker = "\n## 封装后复核\n"
    if marker in report:
        report = report.split(marker, 1)[0].rstrip() + "\n"
    report += (
        marker
        + "\n自动清单生成后，监控器仅向 `experiment.stdout.log` 追加了最终完成行，"
        + "导致该监控日志成为旧清单中唯一的哈希漂移；其余条目均一致。该日志不属于"
        + "科学证据，现按“监控运行态”从重封清单排除，原文件保留。重封前精确删除本"
        + f"交付目录内首批 {initial_cleanup_count} 个 `._*` AppleDouble 伴生文件，"
        + "并对外置盘在封装写入期间重现的伴生文件继续做精确清理，最终扫描为 0；"
        + "独立验收、正式候选、逐单元状态、原始表、保护文件哈希及科学结论均未改变。"
        + "重封清单完成后再最后写入 `done.json`。\n"
    )

    write_json_direct(HERE / "metadata.json", metadata)
    write_json_direct(HERE / "decision.json", decision)
    with report_path.open("w", encoding="utf-8") as handle:
        handle.write(report)
        handle.flush()
        os.fsync(handle.fileno())
    return metadata, decision


def clear_extended_attributes() -> None:
    for path in HERE.rglob("*"):
        if not path.is_file() or path.name.startswith("._"):
            continue
        result = subprocess.run(
            ["xattr", "-c", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode not in (0,):
            raise RuntimeError(
                "HALT_XATTR_CLEAR_FAILED:"
                f"{path.relative_to(HERE)}:{result.stderr.strip()}"
            )


def remove_all_appledouble() -> list[str]:
    paths = sorted(
        (
            path
            for path in HERE.rglob("._*")
            if path.is_file() or path.is_symlink()
        ),
        key=lambda path: path.as_posix(),
    )
    relative_paths = [path.relative_to(HERE).as_posix() for path in paths]
    for path in paths:
        path.unlink()
    remaining = [
        path.relative_to(HERE).as_posix()
        for path in HERE.rglob("._*")
        if path.is_file() or path.is_symlink()
    ]
    if remaining:
        raise RuntimeError(
            "HALT_APPLEDOUBLE_CLEANUP_INCOMPLETE:"
            + json.dumps(remaining, ensure_ascii=False)
        )
    return relative_paths


def build_manifest() -> dict[str, Any]:
    files: dict[str, str] = {}
    for path in sorted(HERE.rglob("*")):
        local_parts = path.relative_to(HERE).parts
        if (
            not path.is_file()
            or path.name.startswith("._")
            or path.name in {
                "artifact_hashes.json",
                "done.json",
                "experiment.stdout.log",
            }
            or path.suffix == ".tmp"
            or any(part in EXCLUDED_DIRS for part in local_parts)
        ):
            continue
        files[relative(path)] = sha256(path)
    payload = {
        "schema": "resetp.e6-fairness-v3.artifact-hashes.v2",
        "created_at_utc": now_iso(),
        "files": files,
        "exclusions": [
            "._* (AppleDouble; removed before reseal)",
            "__pycache__",
            ".pytest_cache",
            "monitor_runtime",
            "experiment.stdout.log (monitor-owned mutable stdout)",
            "*.tmp",
            "artifact_hashes.json (self-reference)",
            "done.json (completion signal written last)",
        ],
        "scientific_evidence_changed_during_reseal": False,
    }
    payload["manifest_id"] = canonical_sha256(payload)
    write_json_direct(HERE / "artifact_hashes.json", payload)
    return payload


def write_done_last(
    manifest: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    old_done = read_json(HERE / "done.json")
    done = {
        key: value
        for key, value in old_done.items()
        if key not in {
            "done_id",
            "created_at_utc",
            "appledouble_removed_count",
        }
    }
    done.update(
        {
            "created_at_utc": now_iso(),
            "status": "COMPLETE",
            "joint_rerun_bitwise_identical": True,
            "units_naturally_pareto": 0,
            "units_total": 20,
            "units_f_equals_i": 20,
            "fairness_cost_pct": 1.511783666875632,
            "candidate_pool_persisted": True,
            "f_state_computed": True,
            "joint_search_units_rerun": 20,
            "zone_search_units_rerun": 0,
            "artifact_manifest_id": manifest["manifest_id"],
            "decision_id": decision["decision_id"],
            "done_written_last": True,
            "postrun_closeout_status": "PASS",
            "appledouble_remaining": 0,
            "monitor_stdout_excluded_from_manifest": True,
        }
    )
    done["done_id"] = canonical_sha256(done)
    write_json_direct(HERE / "done.json", done)
    return done


def main() -> int:
    old_manifest, stdout_mismatch = verify_preconditions()
    appledouble_paths = sorted(
        path.relative_to(HERE).as_posix()
        for path in HERE.rglob("._*")
        if path.is_file() or path.is_symlink()
    )
    clear_extended_attributes()
    _, decision = update_closeout_surfaces(
        old_manifest,
        stdout_mismatch,
        appledouble_paths,
    )
    clear_extended_attributes()
    removed_before_manifest = remove_all_appledouble()
    manifest = build_manifest()
    clear_extended_attributes()
    removed_after_manifest = remove_all_appledouble()
    # The external filesystem has coarse timestamp resolution.  Crossing one
    # full two-second tick makes the final completion signal unambiguous.
    time.sleep(2.1)
    done = write_done_last(manifest, decision)
    removed_after_done: list[str] = []
    stable_scans = 0
    for _ in range(12):
        clear_extended_attributes()
        removed_after_done.extend(remove_all_appledouble())
        time.sleep(0.2)
        if not any(
            path.is_file() or path.is_symlink()
            for path in HERE.rglob("._*")
        ):
            stable_scans += 1
            if stable_scans >= 3:
                break
        else:
            stable_scans = 0
    else:
        raise RuntimeError("HALT_APPLEDOUBLE_DID_NOT_SETTLE")
    removed_this_reseal = (
        len(removed_before_manifest)
        + len(removed_after_manifest)
        + len(removed_after_done)
    )
    remaining_appledouble = [
        path.relative_to(HERE).as_posix()
        for path in HERE.rglob("._*")
        if path.is_file() or path.is_symlink()
    ]
    if remaining_appledouble:
        raise RuntimeError(
            "HALT_POST_DONE_APPLEDOUBLE_REAPPEARED:"
            + json.dumps(remaining_appledouble, ensure_ascii=False)
        )
    if (HERE / "done.json").stat().st_mtime_ns <= (
        HERE / "artifact_hashes.json"
    ).stat().st_mtime_ns:
        raise RuntimeError("HALT_DONE_NOT_NEWER_THAN_MANIFEST")
    print(
        "POSTRUN_CLOSEOUT_PASS "
        f"manifest_files={len(manifest['files'])} "
        f"appledouble_removed_this_reseal={removed_this_reseal} "
        f"done_id={done['done_id']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
