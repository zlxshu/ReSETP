#!/usr/bin/env python3
"""Build the phase-one OSRM 26.7.3 freight-profile smoke evidence.

The fixture is deliberately tiny.  It verifies only two model-relevant rules:
an EV that is taller than a 3.0 m limit must detour, and an hgv=no shortcut
must not be used.  It does not build a China graph, matrix, or solver instance.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OSRM_PREFIX = Path("/opt/homebrew/opt/osrm-backend")
SOURCE_PROFILE = OSRM_PREFIX / "share/osrm/profiles/car.lua"
OUT = ROOT / "data/ChinaInstances/phase1_osrm_smoke_v2_20260718"
BIN = OSRM_PREFIX / "bin"

VEHICLES = {
    "cv": {"height": 2.480, "width": 2.200, "length": 5.995, "weight": 4495},
    "ev": {"height": 3.250, "width": 2.200, "length": 5.995, "weight": 4495},
}

FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="ReSETP phase-one smoke">
  <bounds minlat="0.0000" minlon="0.0000" maxlat="0.0030" maxlon="0.0030"/>
  <node id="1" lat="0.0000" lon="0.0000" version="1"/>
  <node id="2" lat="0.0010" lon="0.0015" version="1"/>
  <node id="3" lat="0.0000" lon="0.0030" version="1"/>
  <node id="4" lat="0.0030" lon="0.0000" version="1"/>
  <node id="5" lat="0.0030" lon="0.0030" version="1"/>
  <node id="6" lat="0.0000" lon="0.0015" version="1"/>
  <way id="101" version="1">
    <nd ref="1"/><nd ref="2"/><nd ref="3"/>
    <tag k="highway" v="primary"/>
    <tag k="name" v="Height Limited Direct"/>
    <tag k="maxheight" v="3.0"/>
    <tag k="maxspeed" v="50"/>
  </way>
  <way id="102" version="1">
    <nd ref="1"/><nd ref="4"/><nd ref="5"/><nd ref="3"/>
    <tag k="highway" v="primary"/>
    <tag k="name" v="Unrestricted Detour"/>
    <tag k="maxspeed" v="50"/>
  </way>
  <way id="103" version="1">
    <nd ref="1"/><nd ref="6"/><nd ref="3"/>
    <tag k="highway" v="primary"/>
    <tag k="name" v="Forbidden HGV Shortcut"/>
    <tag k="hgv" v="no"/>
    <tag k="maxspeed" v="50"/>
  </way>
</osm>
"""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(args)}\n"
            f"{result.stdout}\n{result.stderr}"
        )
    return result


def build_profile(source: str, vehicle: dict[str, float | int]) -> str:
    result = source
    replacements = {
        "vehicle_height = 2.0": f"vehicle_height = {vehicle['height']:.3f}",
        "vehicle_width = 1.9": f"vehicle_width = {vehicle['width']:.3f}",
        "vehicle_length = 4.8": f"vehicle_length = {vehicle['length']:.3f}",
        "vehicle_weight = 2000": f"vehicle_weight = {vehicle['weight']}",
        "access_tags_hierarchy = Sequence {\n      'motorcar',": (
            "access_tags_hierarchy = Sequence {\n      'hgv',\n      'motorcar',"
        ),
        "restrictions = Sequence {\n      'motorcar',": (
            "restrictions = Sequence {\n      'hgv',\n      'motorcar',"
        ),
    }
    for old, new in replacements.items():
        if result.count(old) != 1:
            raise RuntimeError(f"expected exactly one profile token: {old!r}")
        result = result.replace(old, new)
    return result


def route(base: Path, port: int, output: Path) -> dict:
    routed = subprocess.Popen(
        [
            str(BIN / "osrm-routed"),
            str(base),
            "--algorithm",
            "CH",
            "--ip",
            "127.0.0.1",
            "--port",
            str(port),
            "--threads",
            "1",
        ],
        cwd=base.parent,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    url = (
        f"http://127.0.0.1:{port}/route/v1/driving/"
        "0.0000,0.0000;0.0030,0.0000?steps=true&overview=false"
    )
    try:
        last_error: Exception | None = None
        for _ in range(50):
            try:
                with urllib.request.urlopen(url, timeout=1) as response:
                    payload = json.load(response)
                output.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                return payload
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last_error = exc
                time.sleep(0.1)
        raise RuntimeError(f"osrm-routed did not become ready: {last_error}")
    finally:
        routed.terminate()
        try:
            routed.wait(timeout=5)
        except subprocess.TimeoutExpired:
            routed.kill()
            routed.wait(timeout=5)


def main() -> None:
    required = [
        SOURCE_PROFILE,
        BIN / "osrm-extract",
        BIN / "osrm-contract",
        BIN / "osrm-routed",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"missing OSRM 26.7.3 inputs: {missing}")

    OUT.mkdir(parents=True, exist_ok=True)
    fixture_path = OUT / "restriction_fixture.osm"
    fixture_path.write_text(FIXTURE, encoding="utf-8")
    source_text = SOURCE_PROFILE.read_text(encoding="utf-8")

    version = run([str(BIN / "osrm-extract"), "--version"], cwd=OUT)
    version_text = (version.stdout + version.stderr).strip()
    if "v26.7.3" not in version_text and "26.7.3" not in version_text:
        raise RuntimeError(f"unexpected OSRM version: {version_text}")

    lua_path = str(OSRM_PREFIX / "share/osrm/profiles/?.lua") + ";;"
    env = dict(os.environ)
    env["LUA_PATH"] = lua_path
    rows: list[dict[str, object]] = []

    with tempfile.TemporaryDirectory(prefix="resetp-osrm-smoke-") as tmp_name:
        tmp = Path(tmp_name)
        for index, (label, vehicle) in enumerate(VEHICLES.items()):
            profile_path = OUT / f"freight_{label}_v2673.lua"
            profile_path.write_text(
                build_profile(source_text, vehicle), encoding="utf-8"
            )
            osm_path = tmp / f"{label}.osm"
            shutil.copy2(fixture_path, osm_path)
            base = tmp / f"{label}.osrm"

            extract = run(
                [
                    str(BIN / "osrm-extract"),
                    str(osm_path),
                    "--profile",
                    str(profile_path),
                    "--small-component-size",
                    "0",
                    "--threads",
                    "1",
                    "--output",
                    str(base),
                ],
                cwd=tmp,
                env=env,
            )
            contract = run(
                [str(BIN / "osrm-contract"), str(base), "--threads", "1"],
                cwd=tmp,
            )
            build_text = extract.stdout + extract.stderr
            (OUT / f"{label}_build.log").write_text(
                "\n".join(
                    [
                        f"osrm_version={version_text}",
                        f"vehicle={label}",
                        "extract_returncode=0",
                        "contract_returncode=0",
                        "hgv_restriction_registered="
                        + str("  hgv" in build_text).lower(),
                        "fixture_nodes=6",
                        "fixture_ways=3",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            payload = route(base, 5181 + index, OUT / f"{label}_route.json")
            if payload.get("code") != "Ok" or not payload.get("routes"):
                raise RuntimeError(f"{label} route failed: {payload}")

            route0 = payload["routes"][0]
            names = [
                step.get("name", "")
                for leg in route0.get("legs", [])
                for step in leg.get("steps", [])
                if step.get("name")
            ]
            expected = (
                "Height Limited Direct"
                if label == "cv"
                else "Unrestricted Detour"
            )
            expected_used = expected in names
            forbidden_used = "Forbidden HGV Shortcut" in names
            passed = expected_used and not forbidden_used
            rows.append(
                {
                    "vehicle": label,
                    "height_m": vehicle["height"],
                    "expected_way": expected,
                    "expected_way_used": expected_used,
                    "hgv_no_shortcut_used": forbidden_used,
                    "distance_m": route0["distance"],
                    "duration_s": route0["duration"],
                    "status": "PASS" if passed else "FAIL",
                }
            )

    with (OUT / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    all_pass = all(row["status"] == "PASS" for row in rows)
    verdict = (
        "PASS_OSRM_2673_FREIGHT_RESTRICTION_SMOKE"
        if all_pass
        else "HALT_OSRM_2673_FREIGHT_RESTRICTION_SMOKE"
    )
    metadata = {
        "schema": "resetp.phase1.osrm-smoke.v2",
        "approval_ids": ["P1-APP-01", "P1-APP-03", "P1-APP-04"],
        "approved_version_change": "OSRM 26.7.3",
        "runtime_version": version_text,
        "runtime_binaries": {
            path.name: sha256(path)
            for path in [BIN / "osrm-extract", BIN / "osrm-contract", BIN / "osrm-routed"]
        },
        "source_profile": str(SOURCE_PROFILE),
        "source_profile_sha256": sha256(SOURCE_PROFILE),
        "scope": "synthetic restriction smoke only",
        "full_province_graphs_run": False,
        "full_matrices_run": False,
        "solver_search_evaluations": 0,
    }
    (OUT / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    decision = {
        "schema": "resetp.phase1.osrm-smoke-decision.v2",
        "verdict": verdict,
        "checks": {
            "cv_uses_3m_height_limited_way": rows[0]["expected_way_used"],
            "ev_3_25m_avoids_3m_height_limited_way": rows[1]["expected_way_used"],
            "cv_avoids_hgv_no_shortcut": not rows[0]["hgv_no_shortcut_used"],
            "ev_avoids_hgv_no_shortcut": not rows[1]["hgv_no_shortcut_used"],
        },
        "formal_search_allowed": False,
        "full_matrix_run": False,
        "next_action": (
            "close phase-one non-algorithm routing prerequisite"
            if all_pass
            else "halt and repair the isolated freight profile"
        ),
    }
    (OUT / "decision.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report = f"""# 阶段一 OSRM 26.7.3 最小货车规则验证

判决：`{verdict}`

本包只验证两条会改变道路结果的规则。2.480 m 柴油车走 3.0 m
限高的较短道路；3.250 m 纯电车避开该路并走无高度限制的绕行道路；
两车都没有使用标为 `hgv=no` 的更短道路。

运行时固定为 `{version_text}`。两份 profile 只改变冻结车型外廓，
并在访问和转向限制层级前增加 `hgv`，没有自创中国速度。没有建立
五省图、九城全矩阵或正式算例，求解器搜索评价为 0。
"""
    (OUT / "report.md").write_text(report, encoding="utf-8")

    files = sorted(
        path
        for path in OUT.iterdir()
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    )
    hashes = {
        "schema": "resetp.artifact-hashes.v1",
        "files": [{"path": path.name, "sha256": sha256(path)} for path in files],
    }
    (OUT / "artifact_hashes.json").write_text(
        json.dumps(hashes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(verdict)

    if not all_pass:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
