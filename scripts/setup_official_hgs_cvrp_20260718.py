#!/usr/bin/env python3
"""Install the pinned official HGS-CVRP locally without changing Python."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
OFFICIAL_URL = "https://github.com/vidalt/HGS-CVRP.git"
PINNED_COMMIT = "1a927955cd2861a29d978f0d359d6e647db9319c"
DEFAULT_PREFIX = REPO / f"build/official-hgs-cvrp-{PINNED_COMMIT[:12]}"
TRACKED_LICENSE = REPO / "third_party/hgs-cvrp/LICENSE"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(command: list[str], *, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"{completed.stdout}{completed.stderr}"
        )
    return completed.stdout + completed.stderr


def shared_library(build: Path) -> Path:
    if sys.platform == "darwin":
        candidates = (build / "libhgscvrp.dylib",)
    elif sys.platform.startswith("linux"):
        candidates = (build / "libhgscvrp.so",)
    elif sys.platform == "win32":
        candidates = (
            build / "hgscvrp.dll",
            build / "Release/hgscvrp.dll",
        )
    else:
        raise RuntimeError(
            f"unsupported platform for HGS shared library: {sys.platform}"
        )
    existing = [path for path in candidates if path.is_file()]
    if len(existing) != 1:
        raise RuntimeError(
            f"expected exactly one HGS shared library, found {existing}"
        )
    return existing[0].resolve()


def atomic_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", type=Path, default=DEFAULT_PREFIX)
    parser.add_argument("--repo-url", default=OFFICIAL_URL)
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    source = prefix / "source"
    # Upstream executable tests resolve ../Instances relative to the build
    # directory, so the build must remain directly inside the source checkout.
    build = source / "build-resetp"
    manifest_path = prefix / "install_manifest.json"
    if not TRACKED_LICENSE.is_file():
        raise FileNotFoundError(
            f"tracked HGS license is missing: {TRACKED_LICENSE}"
        )

    if source.exists():
        if not (source / ".git").is_dir():
            raise RuntimeError(f"refusing non-git existing source directory: {source}")
        # FAT/exFAT-backed macOS workspaces can materialize AppleDouble sidecars,
        # including invalid .git/objects/pack/._*.idx files. Clean only this
        # managed install checkout before asking Git to inspect it.
        if shutil.which("dot_clean"):
            run(["dot_clean", "-m", str(source)])
        current = run(["git", "rev-parse", "HEAD"], cwd=source).strip()
        dirty = run(
            [
                "git",
                "status",
                "--porcelain",
                "--untracked-files=no",
            ],
            cwd=source,
        ).strip()
        if current != PINNED_COMMIT or dirty:
            raise RuntimeError("existing HGS source is not the pinned clean checkout")
    else:
        prefix.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", args.repo_url, str(source)])
        if shutil.which("dot_clean"):
            run(["dot_clean", "-m", str(source)])
        run(["git", "checkout", "--detach", PINNED_COMMIT], cwd=source)

    run(
        [
            "cmake",
            "-S",
            str(source),
            "-B",
            str(build),
            "-DCMAKE_BUILD_TYPE=Release",
            "-DBUILD_TESTING=ON",
        ]
    )
    run(["cmake", "--build", str(build), "-j", "4"])
    ctest_output = run(["ctest", "--test-dir", str(build), "--output-on-failure"])
    if "100% tests passed" not in ctest_output:
        raise RuntimeError("upstream HGS test output did not confirm a complete pass")

    binary = build / "hgs"
    if not binary.is_file():
        raise RuntimeError(f"built binary missing: {binary}")
    library = shared_library(build)
    source_license = source / "LICENSE"
    if sha256(source_license) != sha256(TRACKED_LICENSE):
        raise RuntimeError(
            "upstream HGS license differs from the tracked repository copy"
        )
    manifest = {
        "schema_version": "resetp.official-hgs-cvrp-install.v2",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "official_repo": OFFICIAL_URL,
        "clone_source": args.repo_url,
        "pinned_commit": PINNED_COMMIT,
        "source_dir": str(source),
        "build_dir": str(build),
        "binary": str(binary),
        "binary_sha256": sha256(binary),
        "library": str(library),
        "library_sha256": sha256(library),
        "license": "MIT",
        "license_sha256": sha256(source_license),
        "tracked_license": str(TRACKED_LICENSE),
        "tracked_license_sha256": sha256(TRACKED_LICENSE),
        "rebuild_script": str(Path(__file__).resolve()),
        "rebuild_script_sha256": sha256(Path(__file__).resolve()),
        "cmake_cache_sha256": sha256(build / "CMakeCache.txt"),
        "upstream_tests": "PASS",
        "integration_boundary": (
            "Official CVRP engine only. This install does not add time windows, "
            "heterogeneous fleets, SOC, charging, carbon, fairness, or ReSETP semantics."
        ),
    }
    atomic_json(manifest_path, manifest)
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
