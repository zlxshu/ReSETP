#!/usr/bin/env python3
"""Recover the interrupted XD solution archive and validation ledger.

The attempt-4 scorer completed ``raw_runs.csv`` and the aggregate artifacts,
but two concurrently opened temporary streams left the final solution archive
and validation ledger with different valid prefixes.  This recovery preserves
and verifies those prefixes, deterministically regenerates only their missing
suffixes, and compares a full in-memory replay with the already written raw
rows.  It never invokes route search.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any, TextIO


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "baselines/china_e3_e7/carbon_timing_rescore_20260802"
RUNNER_PATH = ROOT / "baselines/china_e3_e7/run_carbon_timing_rescore_20260802.py"
EXPECTED = 22_770
BATCH = 200
PREREG_SHA256 = "fe0a984a1a1f1a388e32ae2ab94a6b91b6e23c4313f6c75d8d9f720f46927feb"

PROGRESS = OUT / "recovery_progress.json"
VERIFICATION = OUT / "recovery_verification.json"
RECOVERY_DONE = OUT / "recovery_done.json"
RECOVERY_DIR = OUT / ".archive_recovery_v3"
PRIOR_RECOVERY_DIRS = (
    OUT / ".archive_recovery_v2",
)
LOCK = RECOVERY_DIR / "recovery.lock"
SOLUTION_NEXT = RECOVERY_DIR / "solutions.next.jsonl.gz.tmp"
VALIDATION_NEXT = RECOVERY_DIR / "validation.next.jsonl.tmp"
SOLUTION_CHECKPOINT = RECOVERY_DIR / "solutions.checkpoint.jsonl.gz.tmp"
VALIDATION_CHECKPOINT = RECOVERY_DIR / "validation.checkpoint.jsonl.tmp"
SNAPSHOT = OUT / ".recovery_attempt4_concurrent_writer_corrupt_20260803"


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_solution_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_runner() -> Any:
    spec = importlib.util.spec_from_file_location("xd_rescore_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import runner: {RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read_raw_rows() -> list[dict[str, str]]:
    with (OUT / "raw_runs.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != EXPECTED:
        raise RuntimeError(f"raw row count {len(rows)} != {EXPECTED}")
    if len({row["record_id"] for row in rows}) != EXPECTED:
        raise RuntimeError("raw record ids are not unique")
    return rows


def scan_solution_prefix(
    path: Path, rows: list[dict[str, str]]
) -> tuple[int, str | None]:
    count = 0
    error: str | None = None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for count, line in enumerate(handle, 1):
                if count > len(rows):
                    raise RuntimeError(f"solution overflow in {path}")
                payload = json.loads(line)
                expected = rows[count - 1]
                calculated = canonical_solution_sha256(
                    payload["complete_solution"]
                )
                if payload["record_id"] != expected["record_id"]:
                    raise RuntimeError(
                        f"solution record mismatch at {count}: "
                        f"{payload['record_id']} != {expected['record_id']}"
                    )
                if payload["solution_sha256"] != calculated:
                    raise RuntimeError(f"embedded solution hash mismatch at {count}")
                if expected["solution_sha256"] != calculated:
                    raise RuntimeError(f"raw solution hash mismatch at {count}")
    except EOFError as exc:
        error = f"EOFError: {exc}"
    return count, error


def scan_validation_prefix(
    path: Path, rows: list[dict[str, str]]
) -> tuple[int, str | None]:
    count = 0
    error: str | None = None
    try:
        with path.open(encoding="utf-8") as handle:
            for count, line in enumerate(handle, 1):
                if count > len(rows):
                    raise RuntimeError(f"validation overflow in {path}")
                payload = json.loads(line)
                expected = rows[count - 1]
                if payload["record_id"] != expected["record_id"]:
                    raise RuntimeError(
                        f"validation record mismatch at {count}: "
                        f"{payload['record_id']} != {expected['record_id']}"
                    )
                if payload["status"] != expected["status"]:
                    raise RuntimeError(f"validation status mismatch at {count}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        error = f"{type(exc).__name__}: {exc}"
    return count, error


def choose_solution_prefix(
    rows: list[dict[str, str]],
) -> tuple[Path, int, str | None]:
    candidates = [
        path
        for path in (
            OUT / "solutions.jsonl.gz",
            SOLUTION_CHECKPOINT,
            SOLUTION_NEXT,
            *(
                candidate
                for directory in PRIOR_RECOVERY_DIRS
                for candidate in (
                    directory / "solutions.checkpoint.jsonl.gz.tmp",
                    directory / "solutions.next.jsonl.gz.tmp",
                )
            ),
        )
        if path.is_file()
    ]
    if not candidates:
        raise RuntimeError("no solution prefix candidate exists")
    scanned = [(path, *scan_solution_prefix(path, rows)) for path in candidates]
    return max(scanned, key=lambda item: item[1])


def choose_validation_prefix(
    rows: list[dict[str, str]],
) -> tuple[Path, int, str | None]:
    candidates = [
        path
        for path in (
            OUT / "validation_ledger.jsonl",
            VALIDATION_CHECKPOINT,
            VALIDATION_NEXT,
            *(
                candidate
                for directory in PRIOR_RECOVERY_DIRS
                for candidate in (
                    directory / "validation.checkpoint.jsonl.tmp",
                    directory / "validation.next.jsonl.tmp",
                )
            ),
        )
        if path.is_file()
    ]
    if not candidates:
        raise RuntimeError("no validation prefix candidate exists")
    scanned = [(path, *scan_validation_prefix(path, rows)) for path in candidates]
    return max(scanned, key=lambda item: item[1])


def preserve_interrupted_scene() -> dict[str, str]:
    SNAPSHOT.mkdir(exist_ok=True)
    hashes: dict[str, str] = {}
    for name in (
        "solutions.jsonl.gz",
        "validation_ledger.jsonl",
        "raw_runs.csv",
        "decision.json",
        "metadata.json",
        "summary.json",
        "report.md",
    ):
        source = OUT / name
        target = SNAPSHOT / name
        if source.is_file() and not target.exists():
            shutil.copy2(source, target)
        if target.is_file():
            hashes[name] = sha256_path(target)
    write_json(
        SNAPSHOT / "snapshot_manifest.json",
        {
            "schema": "resetp.xd-attempt4-interrupted-scene.v1",
            "reason": "concurrent temporary writers produced inconsistent valid prefixes",
            "files": hashes,
            "preserved_only": True,
        },
    )
    return hashes


def copy_solution_prefix(source: Path, count: int, target: TextIO) -> None:
    copied = 0
    try:
        with gzip.open(source, "rt", encoding="utf-8") as handle:
            for copied, line in enumerate(handle, 1):
                if copied > count:
                    break
                target.write(line)
                if copied == count:
                    break
    except EOFError:
        pass
    if copied != count:
        raise RuntimeError(f"copied solution prefix {copied} != {count}")


def copy_validation_prefix(source: Path, count: int, target: TextIO) -> None:
    copied = 0
    with source.open(encoding="utf-8") as handle:
        for copied, line in enumerate(handle, 1):
            if copied > count:
                break
            target.write(line)
            if copied == count:
                break
    if copied != count:
        raise RuntimeError(f"copied validation prefix {copied} != {count}")


class RecoveryState:
    def __init__(
        self,
        *,
        rows: list[dict[str, str]],
        solution_prefix: int,
        validation_prefix: int,
        solution_text: TextIO,
        validation_text: TextIO,
        solution_raw: io.BufferedWriter,
        validation_raw: TextIO,
        prereg_before: str,
    ) -> None:
        self.rows = rows
        self.solution_prefix = solution_prefix
        self.validation_prefix = validation_prefix
        self.solution_text = solution_text
        self.validation_text = validation_text
        self.solution_raw = solution_raw
        self.validation_raw = validation_raw
        self.prereg_before = prereg_before
        self.solution_recomputed = 0
        self.validation_recomputed = 0
        self.errors: list[str] = []

    def sync(self, phase: str) -> None:
        self.solution_text.flush()
        self.solution_raw.flush()
        os.fsync(self.solution_raw.fileno())
        self.validation_text.flush()
        os.fsync(self.validation_raw.fileno())
        current = max(self.solution_recomputed, self.validation_recomputed)
        write_json(
            PROGRESS,
            {
                "schema": "resetp.xd-archive-recovery-progress.v1",
                "status": "RUNNING",
                "phase": phase,
                "recovery_workspace": str(RECOVERY_DIR.relative_to(ROOT)),
                "recomputed_records": current,
                "expected_records": EXPECTED,
                "solution_prefix_reused": self.solution_prefix,
                "validation_prefix_reused": self.validation_prefix,
                "solution_suffix_written": max(
                    0, self.solution_recomputed - self.solution_prefix
                ),
                "validation_suffix_written": max(
                    0, self.validation_recomputed - self.validation_prefix
                ),
                "next_record_id": (
                    self.rows[current]["record_id"]
                    if current < len(self.rows)
                    else None
                ),
                "route_search_executed": False,
                "search_evaluations": 0,
                "pre_registration_sha256": self.prereg_before,
                "error_count": len(self.errors),
            },
        )


class SelectiveWriter:
    def __init__(self, kind: str, target: TextIO, state: RecoveryState) -> None:
        self.kind = kind
        self.target = target
        self.state = state
        self.prefix = (
            state.solution_prefix if kind == "solution" else state.validation_prefix
        )

    def write(self, text: str) -> int:
        if self.kind == "solution":
            self.state.solution_recomputed += 1
            count = self.state.solution_recomputed
            payload = json.loads(text)
            expected = self.state.rows[count - 1]
            calculated = canonical_solution_sha256(payload["complete_solution"])
            if payload["record_id"] != expected["record_id"]:
                self.state.errors.append(f"solution_record:{count}")
            if payload["solution_sha256"] != calculated:
                self.state.errors.append(f"solution_embedded_hash:{count}")
            if expected["solution_sha256"] != calculated:
                self.state.errors.append(f"solution_raw_hash:{count}")
        else:
            self.state.validation_recomputed += 1
            count = self.state.validation_recomputed
            payload = json.loads(text)
            expected = self.state.rows[count - 1]
            if payload["record_id"] != expected["record_id"]:
                self.state.errors.append(f"validation_record:{count}")
            if payload["status"] != expected["status"]:
                self.state.errors.append(f"validation_status:{count}")
        if count > self.prefix:
            self.target.write(text)
        if self.kind == "validation" and count % BATCH == 0:
            self.state.sync("RECOMPUTE_AND_APPEND_MISSING_SUFFIX")
        return len(text)


def acquire_lock() -> int:
    try:
        descriptor = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        try:
            pid = int(LOCK.read_text(encoding="utf-8").strip())
            os.kill(pid, 0)
        except (ValueError, ProcessLookupError):
            LOCK.unlink()
            descriptor = os.open(
                LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644
            )
        else:
            raise RuntimeError(f"recovery already active with pid {pid}")
    os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
    os.fsync(descriptor)
    return descriptor


def main() -> int:
    RECOVERY_DIR.mkdir(exist_ok=True)
    lock_descriptor = acquire_lock()
    try:
        rows = read_raw_rows()
        prereg_before = sha256_path(OUT / "pre_registration.json")
        if prereg_before != PREREG_SHA256:
            raise RuntimeError(f"pre-registration drift: {prereg_before}")
        snapshot_hashes = preserve_interrupted_scene()
        solution_source, solution_prefix, solution_error = choose_solution_prefix(
            rows
        )
        validation_source, validation_prefix, validation_error = (
            choose_validation_prefix(rows)
        )
        solution_output = (
            SOLUTION_CHECKPOINT
            if solution_source == SOLUTION_NEXT
            else SOLUTION_NEXT
        )
        validation_output = (
            VALIDATION_CHECKPOINT
            if validation_source == VALIDATION_NEXT
            else VALIDATION_NEXT
        )
        solution_output.unlink(missing_ok=True)
        validation_output.unlink(missing_ok=True)

        runner = load_runner()
        with solution_output.open("wb") as solution_raw, gzip.GzipFile(
            fileobj=solution_raw, mode="wb", mtime=0
        ) as solution_gzip, io.TextIOWrapper(
            solution_gzip, encoding="utf-8"
        ) as solution_text, VALIDATION_NEXT.open(
            "w", encoding="utf-8"
        ) as validation_text:
            copy_solution_prefix(solution_source, solution_prefix, solution_text)
            copy_validation_prefix(
                validation_source, validation_prefix, validation_text
            )
            state = RecoveryState(
                rows=rows,
                solution_prefix=solution_prefix,
                validation_prefix=validation_prefix,
                solution_text=solution_text,
                validation_text=validation_text,
                solution_raw=solution_raw,
                validation_raw=validation_text,
                prereg_before=prereg_before,
            )
            state.sync("VALID_PREFIXES_COPIED")
            with runner.model_config_scope(runner.MODEL_CONFIG):
                fixed_rows, line_number = runner.process_fixed(
                    SelectiveWriter("solution", solution_text, state),
                    SelectiveWriter("validation", validation_text, state),
                    0,
                )
                joint_rows, line_number = runner.process_joint(
                    SelectiveWriter("solution", solution_text, state),
                    SelectiveWriter("validation", validation_text, state),
                    line_number,
                )
            state.sync("FULL_REPLAY_FINISHED")
            if state.errors:
                raise RuntimeError(
                    f"recovery replay mismatches: {state.errors[:20]}"
                )
            if state.solution_recomputed != EXPECTED:
                raise RuntimeError(
                    f"solution replay {state.solution_recomputed} != {EXPECTED}"
                )
            if state.validation_recomputed != EXPECTED:
                raise RuntimeError(
                    f"validation replay {state.validation_recomputed} != {EXPECTED}"
                )

        regenerated_rows = [*fixed_rows, *joint_rows]
        recomputed_csv = SNAPSHOT / "raw_runs.recomputed_for_recovery.csv"
        runner.write_csv(recomputed_csv, regenerated_rows)
        raw_sha = sha256_path(OUT / "raw_runs.csv")
        recomputed_raw_sha = sha256_path(recomputed_csv)
        if raw_sha != recomputed_raw_sha:
            raise RuntimeError(
                f"full raw replay differs: {raw_sha} != {recomputed_raw_sha}"
            )

        solution_count, solution_terminal_error = scan_solution_prefix(
            solution_output, rows
        )
        validation_count, validation_terminal_error = scan_validation_prefix(
            validation_output, rows
        )
        if solution_count != EXPECTED or solution_terminal_error is not None:
            raise RuntimeError(
                f"recovered solution archive invalid: {solution_count}, "
                f"{solution_terminal_error}"
            )
        if validation_count != EXPECTED or validation_terminal_error is not None:
            raise RuntimeError(
                f"recovered validation ledger invalid: {validation_count}, "
                f"{validation_terminal_error}"
            )
        prereg_after = sha256_path(OUT / "pre_registration.json")
        if prereg_after != prereg_before:
            raise RuntimeError("pre-registration changed during recovery")

        final_solution_checkpoint = (
            SOLUTION_NEXT
            if solution_output == SOLUTION_CHECKPOINT
            else SOLUTION_CHECKPOINT
        )
        final_validation_checkpoint = (
            VALIDATION_NEXT
            if validation_output == VALIDATION_CHECKPOINT
            else VALIDATION_CHECKPOINT
        )
        shutil.copy2(solution_output, final_solution_checkpoint)
        shutil.copy2(validation_output, final_validation_checkpoint)
        solution_output.replace(OUT / "solutions.jsonl.gz")
        validation_output.replace(OUT / "validation_ledger.jsonl")
        verification = {
            "schema": "resetp.xd-archive-recovery-verification.v1",
            "status": "PASS_ARCHIVE_SUFFIX_RECOVERY",
            "cause": "concurrent temporary writer race after one writer renamed its streams",
            "disposition": "reused verified prefixes and regenerated only missing suffix artifacts",
            "solution_prefix_source": str(solution_source.relative_to(ROOT)),
            "solution_prefix_reused": solution_prefix,
            "solution_prefix_terminal_error": solution_error,
            "solution_suffix_regenerated": EXPECTED - solution_prefix,
            "validation_prefix_source": str(validation_source.relative_to(ROOT)),
            "validation_prefix_reused": validation_prefix,
            "validation_prefix_terminal_error": validation_error,
            "validation_suffix_regenerated": EXPECTED - validation_prefix,
            "final_solution_count": solution_count,
            "final_validation_count": validation_count,
            "raw_runs_sha256": raw_sha,
            "full_recomputed_raw_runs_sha256": recomputed_raw_sha,
            "raw_runs_byte_for_byte_reproduced": True,
            "pre_registration_sha256_before": prereg_before,
            "pre_registration_sha256_after": prereg_after,
            "interrupted_scene_snapshot": str(SNAPSHOT.relative_to(ROOT)),
            "interrupted_scene_hashes": snapshot_hashes,
            "route_search_executed": False,
            "search_evaluations": 0,
        }
        write_json(VERIFICATION, verification)
        write_json(
            PROGRESS,
            {
                "schema": "resetp.xd-archive-recovery-progress.v1",
                "status": "COMPLETE_ARCHIVES_REBUILT_FROM_VALID_PREFIXES",
                "expected_records": EXPECTED,
                "solution_prefix_reused": solution_prefix,
                "solution_suffix_regenerated": EXPECTED - solution_prefix,
                "validation_prefix_reused": validation_prefix,
                "validation_suffix_regenerated": EXPECTED - validation_prefix,
                "pre_registration_sha256": prereg_after,
                "route_search_executed": False,
                "search_evaluations": 0,
            },
        )
        write_json(
            RECOVERY_DONE,
            {
                "schema": "resetp.xd-archive-recovery-done.v1",
                "status": "COMPLETE_ARCHIVES_REBUILT_FROM_VALID_PREFIXES",
                "solution_records": EXPECTED,
                "validation_records": EXPECTED,
                "recovery_workspace": str(RECOVERY_DIR.relative_to(ROOT)),
                "pre_registration_sha256": prereg_after,
                "route_search_executed": False,
                "search_evaluations": 0,
            },
        )
        print(json.dumps(verification, ensure_ascii=False), flush=True)
        return 0
    finally:
        os.close(lock_descriptor)
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
