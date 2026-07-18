#!/usr/bin/env python3
"""Merge frozen Sichuan/Chongqing PBFs and build CY-wide CV/EV OSRM graphs."""

from __future__ import annotations

import csv
import json
import os
import subprocess
from pathlib import Path

from build_china_stage2_local_osrm_graphs_20260718 import (
    COMPLETION,
    CV_PROFILE,
    DEFAULT_OUTPUT,
    EV_PROFILE,
    REPO,
    atomic_json,
    graph_files,
    profile_inputs,
    run_stage,
    sha256,
    utc_now,
    verify_runtime,
    write_artifact_hashes,
)


SICHUAN = REPO / "data/ChinaInstances/china_mc004_mc006_preclosure_v4_20260718/fixed_osm_inputs/sichuan-260716.osm.pbf"
CHONGQING = REPO / "data/ChinaInstances/china_mc004_mc006_preclosure_v4_20260718/fixed_osm_inputs/chongqing-260716.osm.pbf"
MERGE_OUT = REPO / "data/ChinaInstances/china_stage2_chengyu_merged_osm_v1_20260718"


def main() -> int:
    if not (DEFAULT_OUTPUT / COMPLETION).is_file():
        raise RuntimeError("base ten-graph build must complete first")
    runtime = verify_runtime()
    MERGE_OUT.mkdir(parents=True, exist_ok=True)
    merged = MERGE_OUT / "chengyu-260716.osm.pbf"
    source_hashes = {"sichuan": sha256(SICHUAN), "chongqing": sha256(CHONGQING)}
    if not merged.exists():
        subprocess.run(
            ["osmium", "merge", SICHUAN, CHONGQING, "-o", merged],
            cwd=REPO, check=True,
        )
    merge_manifest = {
        "schema": "resetp.china-stage2.chengyu-merged-osm.v1",
        "sources": {
            "sichuan": {"path": str(SICHUAN.relative_to(REPO)), "sha256": source_hashes["sichuan"]},
            "chongqing": {"path": str(CHONGQING.relative_to(REPO)), "sha256": source_hashes["chongqing"]},
        },
        "merged_path": str(merged.relative_to(REPO)),
        "merged_sha256": sha256(merged),
        "merge_tool": subprocess.run(["osmium", "--version"], capture_output=True, text=True, check=True).stdout.splitlines()[0],
        "search_evaluations": 0,
    }
    atomic_json(MERGE_OUT / "metadata.json", merge_manifest)
    environment = dict(os.environ)
    environment["LUA_PATH"] = runtime["lua_runtime"]["profile_root"] + "/?.lua;;"
    raw_path = MERGE_OUT / "raw_runs.csv"
    rows: list[dict] = []
    for profile in profile_inputs():
        graph_dir = DEFAULT_OUTPUT / "graphs" / "chengyu" / profile.name
        graph_dir.mkdir(parents=True, exist_ok=True)
        graph_base = graph_dir / f"chengyu-{profile.name}.osrm"
        manifest = graph_dir / "graph_manifest.json"
        if not manifest.exists():
            run_stage(
                [runtime["osrm-extract"]["path"], "--profile", str(profile.path),
                 "--threads", "6", "--output", str(graph_base), str(merged)],
                environment, graph_dir / "extract.log", "chengyu", profile.name,
                "extract", rows, raw_path,
            )
            run_stage(
                [runtime["osrm-contract"]["path"], "--threads", "6", str(graph_base)],
                environment, graph_dir / "contract.log", "chengyu", profile.name,
                "contract", rows, raw_path,
            )
            files = graph_files(graph_dir)
            atomic_json(manifest, {
                "identity": f"chengyu/{profile.name}",
                "generated_utc": utc_now(),
                "pbf_sha256": sha256(merged),
                "profile_sha256": profile.sha256,
                "files": {str(p.relative_to(graph_dir)): sha256(p) for p in files},
            })
    atomic_json(MERGE_OUT / "decision.json", {
        "verdict": "PASS_CHENGYU_MERGED_CV_EV_LOCAL_GRAPHS",
        "graph_count": 2, "search_evaluations": 0, "formal_search_allowed": False,
    })
    (MERGE_OUT / "report.md").write_text(
        "# 成渝合并道路图\n\n四川与重庆两份冻结 PBF 经 osmium 合并后，分别构建 CV/EV "
        "OSRM 26.7.3 CH 图，用于跨川渝有向路径。零求解器搜索，正式搜索仍关闭。\n",
        encoding="utf-8",
    )
    hashes = {
        str(p.relative_to(MERGE_OUT)): sha256(p)
        for p in sorted(MERGE_OUT.iterdir())
        if p.is_file() and p.name != "artifact_hashes.json" and not p.name.startswith("._")
    }
    atomic_json(MERGE_OUT / "artifact_hashes.json", hashes)
    write_artifact_hashes(DEFAULT_OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
