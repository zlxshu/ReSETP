#!/usr/bin/env python3
"""Build the frozen local OSRM graphs for the G1-independent China lane.

This runner is intentionally sequential on the 8 GB reference machine.  It
does not build matrices and never calls the solver.  A graph is accepted only
after both ``osrm-extract`` and ``osrm-contract`` succeed and every generated
file is hashed.  Existing accepted graphs are verified and reused; incomplete
graph directories are a hard stop rather than being silently deleted.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = (
    REPO / "data/ChinaInstances/china_stage2_local_osrm_graphs_20260718"
)
PHASE1_RUNTIME = (
    REPO / "data/ChinaInstances/phase1_osrm_smoke_v2_20260718/metadata.json"
)
CV_PROFILE = (
    REPO
    / "data/ChinaInstances/phase1_osrm_smoke_v2_20260718/"
    "freight_cv_v2673.lua"
)
EV_PROFILE = (
    REPO
    / "data/ChinaInstances/phase1_osrm_smoke_v2_20260718/"
    "freight_ev_v2673.lua"
)
PBF_INVENTORY = (
    REPO
    / "data/ChinaInstances/china_mc004_mc006_preclosure_v4_20260718/"
    "osm_freeze_inventory.csv"
)
COMPLETION = "LOCAL_OSRM_GRAPHS_COMPLETE.json"
VERDICT = "PASS_LOCAL_OSRM_26_7_3_FROZEN_GRAPHS_READY"


class GraphBuildError(RuntimeError):
    """The frozen graph build contract cannot be satisfied."""


@dataclass(frozen=True)
class FrozenInput:
    region: str
    pbf: Path
    sha256: str


@dataclass(frozen=True)
class Profile:
    name: str
    path: Path
    sha256: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "region",
        "profile",
        "stage",
        "status",
        "started_utc",
        "finished_utc",
        "elapsed_seconds",
        "returncode",
        "log_path",
        "detail",
    ]
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def read_inputs() -> list[FrozenInput]:
    rows: list[FrozenInput] = []
    with PBF_INVENTORY.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            path = REPO / row["path"]
            rows.append(
                FrozenInput(
                    region=row["region"],
                    pbf=path,
                    sha256=row["sha256"],
                )
            )
    if [row.region for row in rows] != [
        "beijing",
        "hebei",
        "guangdong",
        "sichuan",
        "chongqing",
    ]:
        raise GraphBuildError("frozen PBF inventory identity/order drift")
    return rows


def profile_inputs() -> list[Profile]:
    return [
        Profile("cv", CV_PROFILE, sha256(CV_PROFILE)),
        Profile("ev", EV_PROFILE, sha256(EV_PROFILE)),
    ]


def verify_runtime() -> dict[str, Any]:
    frozen = json.loads(PHASE1_RUNTIME.read_text(encoding="utf-8"))
    binaries: dict[str, dict[str, str]] = {}
    for name in ("osrm-extract", "osrm-contract", "osrm-routed"):
        resolved = subprocess.run(
            ["/usr/bin/which", name],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        path = Path(resolved)
        actual = sha256(path)
        expected = frozen["runtime_binaries"][name]
        if actual != expected:
            raise GraphBuildError(
                f"{name} hash drift: expected {expected}, got {actual}"
            )
        version = subprocess.run(
            [str(path), "--version"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if version != "v26.7.3":
            raise GraphBuildError(f"{name} version drift: {version}")
        binaries[name] = {
            "path": str(path),
            "version": version,
            "sha256": actual,
        }
    source_profile = Path(frozen["source_profile"])
    lua_library = source_profile.parent / "lib/set.lua"
    if not source_profile.is_file() or not lua_library.is_file():
        raise GraphBuildError(
            f"frozen OSRM Lua profile library missing: {source_profile.parent}"
        )
    binaries["lua_runtime"] = {
        "profile_root": str(source_profile.parent),
        "set_lua_sha256": sha256(lua_library),
    }
    return binaries


def graph_files(graph_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in graph_dir.iterdir()
        if path.is_file()
        and not path.name.startswith("._")
        and path.name not in {"graph_manifest.json"}
    )


def verify_existing_graph(graph_dir: Path) -> bool:
    manifest_path = graph_dir / "graph_manifest.json"
    if not graph_dir.exists():
        return False
    if not manifest_path.exists():
        raise GraphBuildError(
            f"incomplete graph directory preserved for inspection: {graph_dir}"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for relative, expected in manifest["files"].items():
        path = graph_dir / relative
        if not path.is_file() or sha256(path) != expected:
            raise GraphBuildError(f"accepted graph hash drift: {path}")
    return True


def run_stage(
    command: list[str],
    environment: dict[str, str],
    log_path: Path,
    region: str,
    profile: str,
    stage: str,
    rows: list[dict[str, Any]],
    raw_runs_path: Path,
) -> None:
    started = utc_now()
    monotonic = time.monotonic()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.run(
            command,
            cwd=REPO,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    elapsed = time.monotonic() - monotonic
    row = {
        "region": region,
        "profile": profile,
        "stage": stage,
        "status": "PASS" if process.returncode == 0 else "FAIL",
        "started_utc": started,
        "finished_utc": utc_now(),
        "elapsed_seconds": f"{elapsed:.6f}",
        "returncode": process.returncode,
        "log_path": str(log_path.relative_to(REPO)),
        "detail": "sequential frozen graph build",
    }
    rows.append(row)
    atomic_csv(raw_runs_path, rows)
    if process.returncode != 0:
        raise GraphBuildError(
            f"{region}/{profile} {stage} failed; see {log_path}"
        )


def write_artifact_hashes(output: Path) -> None:
    hashes: dict[str, str] = {}
    for path in sorted(output.rglob("*")):
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
            and ".tmp" not in path.name
        ):
            hashes[str(path.relative_to(output))] = sha256(path)
    atomic_json(output / "artifact_hashes.json", hashes)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--threads", type=int, default=6)
    args = parser.parse_args()
    if not 1 <= args.threads <= 8:
        raise GraphBuildError("--threads must be in [1, 8]")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / COMPLETION).exists():
        raise GraphBuildError("completion marker already exists; refusing overwrite")

    runtime = verify_runtime()
    environment = dict(os.environ)
    environment["LUA_PATH"] = (
        runtime["lua_runtime"]["profile_root"] + "/?.lua;;"
    )
    inputs = read_inputs()
    profiles = profile_inputs()
    for frozen_input in inputs:
        if not frozen_input.pbf.is_file():
            raise GraphBuildError(f"missing frozen PBF: {frozen_input.pbf}")
        actual = sha256(frozen_input.pbf)
        if actual != frozen_input.sha256:
            raise GraphBuildError(f"PBF hash drift: {frozen_input.pbf}")

    metadata = {
        "schema": "resetp.china-stage2.local-osrm-graphs.v1",
        "generated_utc": utc_now(),
        "authorization": (
            "APPROVED_STAGE2_G1_INDEPENDENT_INPUT_WORK__FORMAL_SEARCH_BLOCKED"
        ),
        "osrm_algorithm": "CH",
        "threads": args.threads,
        "sequential_graph_jobs": True,
        "runtime": runtime,
        "pbf_inputs": [
            {
                "region": item.region,
                "path": str(item.pbf.relative_to(REPO)),
                "sha256": item.sha256,
            }
            for item in inputs
        ],
        "profiles": [
            {
                "name": item.name,
                "path": str(item.path.relative_to(REPO)),
                "sha256": item.sha256,
            }
            for item in profiles
        ],
        "solver_search_evaluations": 0,
        "formal_search_allowed": False,
    }
    atomic_json(output / "metadata.json", metadata)

    raw_runs_path = output / "raw_runs.csv"
    rows: list[dict[str, Any]] = []
    if raw_runs_path.exists():
        with raw_runs_path.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))

    completed: list[str] = []
    for frozen_input in inputs:
        for profile in profiles:
            identity = f"{frozen_input.region}/{profile.name}"
            graph_dir = output / "graphs" / frozen_input.region / profile.name
            if verify_existing_graph(graph_dir):
                completed.append(identity)
                atomic_json(
                    output / "checkpoint.json",
                    {"updated_utc": utc_now(), "completed": completed},
                )
                continue
            graph_dir.mkdir(parents=True, exist_ok=False)
            graph_base = graph_dir / f"{frozen_input.region}-{profile.name}.osrm"
            run_stage(
                [
                    runtime["osrm-extract"]["path"],
                    "--profile",
                    str(profile.path),
                    "--threads",
                    str(args.threads),
                    "--output",
                    str(graph_base),
                    str(frozen_input.pbf),
                ],
                environment,
                graph_dir / "extract.log",
                frozen_input.region,
                profile.name,
                "extract",
                rows,
                raw_runs_path,
            )
            run_stage(
                [
                    runtime["osrm-contract"]["path"],
                    "--threads",
                    str(args.threads),
                    str(graph_base),
                ],
                environment,
                graph_dir / "contract.log",
                frozen_input.region,
                profile.name,
                "contract",
                rows,
                raw_runs_path,
            )
            files = graph_files(graph_dir)
            if not files or not graph_base.with_suffix(".osrm.hsgr").exists():
                raise GraphBuildError(f"contracted graph files missing: {identity}")
            atomic_json(
                graph_dir / "graph_manifest.json",
                {
                    "identity": identity,
                    "generated_utc": utc_now(),
                    "pbf_sha256": frozen_input.sha256,
                    "profile_sha256": profile.sha256,
                    "files": {
                        str(path.relative_to(graph_dir)): sha256(path)
                        for path in files
                    },
                },
            )
            completed.append(identity)
            atomic_json(
                output / "checkpoint.json",
                {"updated_utc": utc_now(), "completed": completed},
            )

    expected = [
        f"{frozen_input.region}/{profile.name}"
        for frozen_input in inputs
        for profile in profiles
    ]
    if completed != expected:
        raise GraphBuildError("graph completion identity drift")
    decision = {
        "schema": "resetp.china-stage2.local-osrm-graphs.decision.v1",
        "verdict": VERDICT,
        "graph_count": len(completed),
        "graph_identities": completed,
        "solver_search_evaluations": 0,
        "formal_search_allowed": False,
        "next_gate": "local_route_api_health_and_full_directed_matrix_build",
    }
    atomic_json(output / "decision.json", decision)
    (output / "report.md").write_text(
        "# China阶段二本地OSRM图构建\n\n"
        f"判定：`{VERDICT}`。五份冻结PBF分别使用CV/EV货运profile，"
        "顺序完成10套OSRM 26.7.3 CH图的extract和contract，并保存逐文件哈希。"
        "本任务没有生成道路矩阵、没有调用求解器，正式搜索评价为0。"
        "`formal_search_allowed=false`继续生效。\n",
        encoding="utf-8",
    )
    atomic_json(
        output / COMPLETION,
        {
            "schema": "resetp.china-stage2.local-osrm-graphs.complete.v1",
            "completed_utc": utc_now(),
            "verdict": VERDICT,
            "graph_count": len(completed),
        },
    )
    write_artifact_hashes(output)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GraphBuildError as error:
        print(f"HALT: {error}", file=sys.stderr)
        raise SystemExit(2) from error
