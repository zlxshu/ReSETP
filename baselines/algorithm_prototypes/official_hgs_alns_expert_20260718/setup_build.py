#!/usr/bin/env python3
"""Build an isolated, auditable derivative of the pinned official HGS-CVRP."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


PINNED_COMMIT = "1a927955cd2861a29d978f0d359d6e647db9319c"
OFFICIAL_GENETIC_SHA256 = {
    "Genetic.cpp": "102f2dae07f2703a643de898615491ac144333e4f89ca39e3a4ee87bbfd6ecca",
    "Genetic.h": "3987fcd5a557af507bc72ac9da991bab4b6be14451fb8782cc25f0ffc94c181d",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(command: list[str], cwd: Path | None = None) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return completed.stdout


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()

    repo = args.repo.resolve()
    prototype = Path(__file__).resolve().parent
    official = repo / "build" / "official-hgs-cvrp-1a927955cd28" / "source"
    derived_root = repo / "build" / "official-hgs-alns-expert-20260718"
    derived_source = derived_root / "source"
    derived_build = derived_source / "build-resetp"

    if not official.is_dir():
        raise SystemExit(f"Missing pinned official source: {official}")
    commit = run(["git", "rev-parse", "HEAD"], cwd=official).strip()
    if commit != PINNED_COMMIT:
        raise SystemExit(f"Official source commit drift: {commit}")
    for name, expected in OFFICIAL_GENETIC_SHA256.items():
        actual = sha256(official / "Program" / name)
        if actual != expected:
            raise SystemExit(f"Official {name} drift: {actual}")

    if not derived_source.exists():
        shutil.copytree(
            official,
            derived_source,
            ignore=shutil.ignore_patterns(".git", "build-resetp", "._*"),
        )
    for name in ("Genetic.cpp", "Genetic.h"):
        shutil.copy2(prototype / name, derived_source / "Program" / name)

    configure_log = run(
        [
            "cmake",
            "-S",
            str(derived_source),
            "-B",
            str(derived_build),
            "-DCMAKE_BUILD_TYPE=Release",
        ]
    )
    # Build all upstream targets so the official C-interface test executable
    # exists as well as the command-line binary.
    build_log = run(["cmake", "--build", str(derived_build), "-j", "4"])
    test_log = ""
    test_status = "SKIPPED"
    if not args.skip_tests:
        test_log = run(["ctest", "--test-dir", str(derived_build), "--output-on-failure"])
        test_status = "PASS"

    binary = derived_build / "hgs"
    manifest = {
        "schema_version": "resetp.mechanism-expert-hgs-alns-build.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "official_repo": "https://github.com/vidalt/HGS-CVRP",
        "official_commit": PINNED_COMMIT,
        "official_source": str(official),
        "derived_source": str(derived_source),
        "binary": str(binary),
        "binary_sha256": sha256(binary),
        "modified_files": {
            name: sha256(prototype / name) for name in ("Genetic.cpp", "Genetic.h")
        },
        "upstream_tests": test_status,
        "boundary": (
            "CVRP-only mechanism-expert development binary. It does not implement "
            "ReSETP time windows, heterogeneous fleet, SOC, charging, carbon, "
            "fairness, dynamic requests, or multi-depot semantics."
        ),
    }
    derived_root.mkdir(parents=True, exist_ok=True)
    (derived_root / "build_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (derived_root / "configure.log").write_text(configure_log, encoding="utf-8")
    (derived_root / "build.log").write_text(build_log, encoding="utf-8")
    (derived_root / "test.log").write_text(test_log, encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
