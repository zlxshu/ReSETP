#!/usr/bin/env python3
"""Wait for the V7 release chain, then build a sealed paper candidate."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


REPO = Path(__file__).resolve().parents[2]
PAPER_DIR = REPO / "docs/paper_v2"
CAMPAIGN = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v7_small_archive_ledger_20260724"
)
RELEASE = CAMPAIGN / "release_chain"
OUT = CAMPAIGN / "paper_candidate_chain"
BUILD = OUT / "build"
PREREGISTRATION = CAMPAIGN / "paper_candidate_chain_preregistration_v1.json"
RELEASE_MONITOR = CAMPAIGN / ".e2-staged-v7-release-chain.monitor"
PAPER_TEXT = CAMPAIGN / "paper_text_gate"
ROUTE_TEXT = CAMPAIGN / "route_text_gate"
INTEGRATED_TEX = OUT / "paper_main_v7_integrated.tex"
POLL_SECONDS = 60


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def write_csv(path: Path, row: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    os.replace(temporary, path)


def verify_manifest(root: Path) -> None:
    manifest = read_json(root / "artifact_hashes.json")
    artifacts = manifest.get("artifacts", manifest.get("files"))
    if not isinstance(artifacts, dict) or not artifacts:
        raise RuntimeError(f"empty artifact manifest: {root}")
    for relative, expected in artifacts.items():
        path = root / relative
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"artifact hash drift: {path}")


def verdict(root: Path) -> str | None:
    decision_path = root / "decision.json"
    if not decision_path.is_file():
        return None
    return read_json(decision_path).get("verdict")


def require_pass(root: Path, expected: str) -> None:
    actual = verdict(root)
    if actual != expected:
        raise RuntimeError(f"{root}: expected {expected}, got {actual}")
    verify_manifest(root)


def heartbeat(stage: str, status: str, detail: str = "") -> None:
    write_json(
        OUT / "progress.json",
        {
            "schema": "resetp.e2-v7-paper-candidate-progress.v1",
            "stage": stage,
            "status": status,
            "detail": detail,
            "updated_at_utc": datetime.now(UTC).isoformat(),
        },
    )


def validate_preregistration() -> None:
    payload = read_json(PREREGISTRATION)
    if (
        payload.get("operation")
        != "WAIT_THEN_ZERO_SEARCH_V7_PAPER_CANDIDATE_BUILD"
        or payload.get("overwrites_main_tex") is not False
        or payload.get("starts_e3") is not False
    ):
        raise RuntimeError("paper candidate chain preregistration is invalid")
    for relative, expected in payload["source_hashes"].items():
        path = REPO / relative
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"paper candidate source drift: {relative}")


def wait_for_release() -> None:
    while True:
        actual = verdict(RELEASE)
        if actual is not None:
            if actual != "PASS_E2_STAGED_V7_RELEASE_CHAIN":
                raise RuntimeError(f"release chain did not pass: {actual}")
            if not (RELEASE / "done.json").is_file():
                raise RuntimeError("release chain PASS lacks done.json")
            verify_manifest(RELEASE)
            heartbeat("release_chain", "PASS", actual)
            return

        status_path = RELEASE_MONITOR / "status.json"
        state = "WAITING"
        if status_path.is_file():
            status = read_json(status_path)
            state = str(status.get("state", "UNKNOWN"))
            age = time.time() - status_path.stat().st_mtime
            if age > 600:
                raise RuntimeError(
                    f"release-chain monitor is stale for {age:.0f}s"
                )
            if state in {"ANOMALY", "FAILED", "STOPPED"}:
                raise RuntimeError(
                    f"release-chain monitor stopped in state {state}"
                )
        heartbeat("release_chain", "WAITING", f"monitor_state={state}")
        time.sleep(POLL_SECONDS)


def run_command(name: str, command: list[str], cwd: Path) -> None:
    heartbeat(name, "RUNNING", " ".join(command))
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    log_path = OUT / f"{name}.log"
    log_path.write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            f"{name} failed with exit code {completed.returncode}; "
            f"see {log_path}"
        )
    heartbeat(name, "PASS", str(log_path.relative_to(REPO)))


def materialize_text() -> None:
    if verdict(PAPER_TEXT) is None:
        run_command(
            "paper_text",
            [
                sys.executable,
                str(
                    REPO
                    / "baselines/e2_final_campaign_20260720/"
                    "materialize_e2_v7_paper_text.py"
                ),
            ],
            REPO,
        )
    require_pass(
        PAPER_TEXT,
        "PASS_E2_V7_PAPER_TEXT_MATERIALIZATION",
    )

    if verdict(ROUTE_TEXT) is None:
        run_command(
            "route_text",
            [
                sys.executable,
                str(
                    REPO
                    / "baselines/e2_final_campaign_20260720/"
                    "materialize_e2_v7_route_text.py"
                ),
            ],
            REPO,
        )
    require_pass(
        ROUTE_TEXT,
        "PASS_E2_V7_ROUTE_TEXT_MATERIALIZATION",
    )


def build_candidate() -> None:
    run_command(
        "paper_integration",
        [
            sys.executable,
            str(
                REPO
                / "docs/paper_v2/candidates/"
                "build_v7_integrated_paper.py"
            ),
            "--output",
            str(INTEGRATED_TEX),
        ],
        REPO,
    )
    if not INTEGRATED_TEX.is_file():
        raise RuntimeError("integrated TeX candidate was not created")


def compile_candidate() -> tuple[Path, Path, int]:
    BUILD.mkdir(parents=True, exist_ok=True)
    run_command(
        "latexmk",
        [
            "latexmk",
            "-xelatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            f"-outdir={BUILD}",
            "-jobname=paper_main_v7_integrated",
            str(INTEGRATED_TEX),
        ],
        PAPER_DIR,
    )
    pdf = BUILD / "paper_main_v7_integrated.pdf"
    log = BUILD / "paper_main_v7_integrated.log"
    if not pdf.is_file() or not log.is_file():
        raise RuntimeError("latexmk did not create the expected PDF and log")
    log_text = log.read_text(encoding="utf-8", errors="replace")
    forbidden_log = (
        "LaTeX Error:",
        "Package ReSETP Error:",
        "undefined references",
        "Citation `",
        "Overfull \\hbox",
        "Overfull \\vbox",
        "Underfull \\hbox",
        "Underfull \\vbox",
    )
    found = [token for token in forbidden_log if token in log_text]
    if found:
        raise RuntimeError(f"candidate TeX log contains: {found}")

    pdfinfo = subprocess.run(
        ["pdfinfo", str(pdf)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True,
    ).stdout
    page_lines = [
        line for line in pdfinfo.splitlines() if line.startswith("Pages:")
    ]
    if len(page_lines) != 1:
        raise RuntimeError("cannot read candidate PDF page count")
    pages = int(page_lines[0].split(":", maxsplit=1)[1].strip())

    fonts = subprocess.run(
        ["pdffonts", str(pdf)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True,
    ).stdout
    type3_lines = [
        line
        for line in fonts.splitlines()[2:]
        if " Type 3 " in f" {line} "
    ]
    if type3_lines:
        raise RuntimeError("candidate PDF contains Type 3 fonts")
    (OUT / "pdffonts.txt").write_text(fonts, encoding="utf-8")
    (OUT / "pdfinfo.txt").write_text(pdfinfo, encoding="utf-8")
    return pdf, log, pages


def clean_appledouble() -> int:
    removed = 0
    for path in sorted(OUT.rglob("._*")):
        if path.is_file():
            path.unlink()
            removed += 1
    return removed


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        validate_preregistration()
        wait_for_release()
        materialize_text()
        build_candidate()
        pdf, tex_log, pages = compile_candidate()
        removed = clean_appledouble()
        row = {
            "release_verdict": verdict(RELEASE),
            "paper_text_verdict": verdict(PAPER_TEXT),
            "route_text_verdict": verdict(ROUTE_TEXT),
            "page_count": pages,
            "latex_errors": 0,
            "undefined_references": 0,
            "overfull_boxes": 0,
            "type3_fonts": 0,
            "appledouble_removed": removed,
            "main_tex_overwritten": 0,
            "e3_started": 0,
        }
        write_csv(OUT / "raw_runs.csv", row)
        decision = {
            "schema": "resetp.e2-v7-paper-candidate.decision.v1",
            "verdict": "PASS_E2_V7_PAPER_CANDIDATE_BUILD",
            "compiled_pages": pages,
            "main_tex_overwritten": False,
            "formal_e3_started": False,
            "visual_review_required_before_main_merge": True,
            "integrated_tex_sha256": sha256(INTEGRATED_TEX),
            "pdf_sha256": sha256(pdf),
        }
        write_json(OUT / "decision.json", decision)
        write_json(
            OUT / "metadata.json",
            {
                "schema": "resetp.e2-v7-paper-candidate.metadata.v1",
                "created_at_utc": datetime.now(UTC).isoformat(),
                "source_hashes": {
                    str(path.relative_to(REPO)): sha256(path)
                    for path in (
                        RELEASE / "decision.json",
                        RELEASE / "artifact_hashes.json",
                        PAPER_TEXT / "decision.json",
                        PAPER_TEXT / "artifact_hashes.json",
                        ROUTE_TEXT / "decision.json",
                        ROUTE_TEXT / "artifact_hashes.json",
                        INTEGRATED_TEX,
                        tex_log,
                        Path(__file__).resolve(),
                        PREREGISTRATION,
                    )
                },
            },
        )
        (OUT / "report.md").write_text(
            "# E2 V7 integrated paper candidate\n\n"
            f"Decision: `{decision['verdict']}`.\n\n"
            f"The independently generated candidate compiled to {pages} "
            "pages with no TeX error, undefined reference, overfull box "
            "or Type 3 font. The protected main TeX was not overwritten "
            "and E3 was not started. Visual page-by-page review remains "
            "mandatory before any main-paper merge.\n",
            encoding="utf-8",
        )
        artifacts = {
            str(path.relative_to(OUT)): sha256(path)
            for path in sorted(OUT.rglob("*"))
            if (
                path.is_file()
                and path.name not in {"artifact_hashes.json", "done.json"}
                and not path.name.startswith("._")
                and not path.name.endswith(".tmp")
            )
        }
        write_json(
            OUT / "artifact_hashes.json",
            {
                "schema": "resetp.artifact-hashes.v1",
                "exclusions": [
                    "artifact_hashes.json",
                    "done.json",
                    "._*",
                    "*.tmp",
                ],
                "artifacts": artifacts,
            },
        )
        write_json(
            OUT / "done.json",
            {
                "schema": "resetp.e2-v7-paper-candidate-done.v1",
                "verdict": decision["verdict"],
                "decision_sha256": sha256(OUT / "decision.json"),
                "pdf_sha256": sha256(pdf),
            },
        )
        heartbeat("paper_candidate", "PASS", decision["verdict"])
        print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        write_json(
            OUT / "decision.json",
            {
                "schema": "resetp.e2-v7-paper-candidate.decision.v1",
                "verdict": "HALT_E2_V7_PAPER_CANDIDATE_CHAIN",
                "reason": str(exc),
                "main_tex_overwritten": False,
                "formal_e3_started": False,
            },
        )
        (OUT / "report.md").write_text(
            "# E2 V7 integrated paper candidate\n\n"
            "`HALT_E2_V7_PAPER_CANDIDATE_CHAIN`\n\n"
            f"Reason: {exc}\n\n"
            "No main-paper merge or E3 start was attempted.\n",
            encoding="utf-8",
        )
        heartbeat("paper_candidate", "HALT", str(exc))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
