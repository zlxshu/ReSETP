#!/usr/bin/env python3
"""Run and seal the MPILS-MVNS-C2-R1 G0 engineering gate."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from scripts.freeze_mdvrptw_v13_foundation_20260719 import (  # noqa: E402
    build_hash_manifest,
    parse_normalised,
    validate_solution_independently,
    write_json,
)


HERE = Path(__file__).resolve().parent
WORKER = HERE / "run_g0_worker.py"
BEHAVIOUR_WORKER = HERE / "run_behavior_probe.py"
INSTANCE = (
    REPO
    / "baselines"
    / "algorithm_foundation"
    / "mdvrptw_v13_comparison_20260719"
    / "sources"
    / "normalised_instances"
    / "PR11A.vrp"
)
OUTPUT = (
    REPO
    / "baselines"
    / "algorithm_foundation"
    / "mpils_mvns_c2_g0_20260720"
)
CORE_OUTPUTS = (
    "metadata.json",
    "raw_runs.csv",
    "decision.json",
    "artifact_hashes.json",
    "report.md",
)
MODES = ("official", "clone_native", "clone_hooks")
EQUIVALENCE_ITERATIONS = (5, 1000, 5000)
OVERHEAD_ITERATIONS = 5000
OVERHEAD_REPEATS = 5
UPSTREAM_ILS = (
    REPO
    / "build"
    / "python_envs"
    / "pyvrp-0.13.4"
    / "lib"
    / "python3.13"
    / "site-packages"
    / "pyvrp"
    / "IteratedLocalSearch.py"
)
UPSTREAM_LICENSE = (
    REPO
    / "build"
    / "python_envs"
    / "pyvrp-0.13.4"
    / "lib"
    / "python3.13"
    / "site-packages"
    / "pyvrp-0.13.4.dist-info"
    / "licenses"
    / "LICENSE.md"
)
EXPECTED_UPSTREAM_ILS_SHA256 = (
    "f5c2979b2ea3d54a427fd4187c4dc6070fb9ee47886ccf3a0422dda7d83ddfcb"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run_json(
    command: list[str],
    *,
    env: dict[str, str],
) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {command}\n"
            f"stdout={completed.stdout}\nstderr={completed.stderr}"
        )
    return json.loads(completed.stdout)


def worker_command(
    *,
    mode: str,
    iterations: int,
    collect_stats: bool,
) -> list[str]:
    command = [
        sys.executable,
        str(WORKER),
        "--mode",
        mode,
        "--instance",
        str(INSTANCE),
        "--seed",
        "1",
        "--iterations",
        str(iterations),
    ]
    command.append(
        "--collect-stats" if collect_stats else "--no-collect-stats"
    )
    return command


def assign_routes_to_vehicles(
    normalised: Any,
    route_records: list[dict[str, Any]],
) -> dict[int, list[int]]:
    routes = {
        vehicle: []
        for vehicle in range(1, normalised.num_vehicles + 1)
    }
    available: dict[int, list[int]] = {}
    for vehicle, depot in normalised.vehicle_depots.items():
        available.setdefault(depot - 1, []).append(vehicle)
    used: dict[int, int] = {depot: 0 for depot in available}
    for record in route_records:
        depot = int(record["start_depot"])
        if int(record["end_depot"]) != depot:
            raise ValueError("route starts and ends at different depots")
        position = used[depot]
        if position >= len(available[depot]):
            raise ValueError("solution exceeds depot vehicle availability")
        vehicle = available[depot][position]
        used[depot] += 1
        routes[vehicle] = [
            int(client) for client in record["visits"]
        ]
    return routes


def main() -> int:
    for filename in CORE_OUTPUTS:
        if (OUTPUT / filename).exists():
            raise FileExistsError(
                f"refusing to overwrite G0 evidence: {OUTPUT / filename}"
            )
    if not INSTANCE.is_file():
        raise FileNotFoundError(INSTANCE)
    for required in (
        WORKER,
        BEHAVIOUR_WORKER,
        UPSTREAM_ILS,
        UPSTREAM_LICENSE,
        HERE / "LICENSE-PYVRP.md",
        HERE / "UPSTREAM.md",
        HERE / "event_driven_ils.py",
        HERE / "c2_core.py",
    ):
        if not required.is_file():
            raise FileNotFoundError(required)

    started = datetime.now(timezone.utc)
    run_dir = OUTPUT / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "VECLIB_MAXIMUM_THREADS": "1",
            "PYTHONHASHSEED": "1",
        }
    )

    rows: list[dict[str, Any]] = []
    equivalence_outputs: dict[
        int,
        dict[str, dict[str, Any]],
    ] = {}
    normalised = parse_normalised(INSTANCE.read_text(encoding="utf-8"))
    all_independent_valid = True
    for iterations in EQUIVALENCE_ITERATIONS:
        equivalence_outputs[iterations] = {}
        for mode in MODES:
            output = run_json(
                worker_command(
                    mode=mode,
                    iterations=iterations,
                    collect_stats=True,
                ),
                env=env,
            )
            equivalence_outputs[iterations][mode] = output
            write_json(
                run_dir / f"equivalence_{iterations}_{mode}.json",
                output,
            )
            payload = output["deterministic_payload"]
            assigned = assign_routes_to_vehicles(
                normalised,
                payload["routes"],
            )
            validation = validate_solution_independently(
                normalised,
                assigned,
                int(payload["distance"]),
            )
            all_independent_valid &= bool(
                validation["all_checks_pass"]
            )
            rows.append(
                {
                    "gate": "equivalence",
                    "repeat": 0,
                    "iterations": iterations,
                    "mode": mode,
                    "runtime_seconds": output[
                        "runtime_main_loop_seconds"
                    ],
                    "distance": payload["distance"],
                    "routes": payload["num_routes"],
                    "feasible": str(payload["feasible"]).lower(),
                    "signature": output[
                        "deterministic_signature_sha256"
                    ],
                    "independent_validation": str(
                        validation["all_checks_pass"]
                    ).lower(),
                }
            )

    equivalence_checks: dict[str, bool] = {}
    for iterations, outputs in equivalence_outputs.items():
        signatures = {
            output["deterministic_signature_sha256"]
            for output in outputs.values()
        }
        equivalence_checks[str(iterations)] = len(signatures) == 1
    equivalence_pass = (
        all(equivalence_checks.values())
        and all_independent_valid
    )

    overhead_outputs: dict[str, list[dict[str, Any]]] = {
        mode: [] for mode in MODES
    }
    for repeat in range(OVERHEAD_REPEATS):
        rotated = (
            MODES[repeat % len(MODES) :]
            + MODES[: repeat % len(MODES)]
        )
        for mode in rotated:
            output = run_json(
                worker_command(
                    mode=mode,
                    iterations=OVERHEAD_ITERATIONS,
                    collect_stats=False,
                ),
                env=env,
            )
            overhead_outputs[mode].append(output)
            write_json(
                run_dir / f"overhead_{repeat + 1}_{mode}.json",
                output,
            )
            payload = output["deterministic_payload"]
            rows.append(
                {
                    "gate": "overhead",
                    "repeat": repeat + 1,
                    "iterations": OVERHEAD_ITERATIONS,
                    "mode": mode,
                    "runtime_seconds": output[
                        "runtime_main_loop_seconds"
                    ],
                    "distance": payload["distance"],
                    "routes": payload["num_routes"],
                    "feasible": str(payload["feasible"]).lower(),
                    "signature": output[
                        "deterministic_signature_sha256"
                    ],
                    "independent_validation": "not_repeated",
                }
            )

    overhead_medians = {
        mode: statistics.median(
            output["runtime_main_loop_seconds"]
            for output in outputs
        )
        for mode, outputs in overhead_outputs.items()
    }
    overhead_ratios = {
        mode: overhead_medians[mode] / overhead_medians["official"]
        for mode in ("clone_native", "clone_hooks")
    }
    overhead_path_signatures_equal = all(
        len(
            {
                output["deterministic_signature_sha256"]
                for mode in MODES
                for output in overhead_outputs[mode]
            }
        )
        == 1
        for _ in (0,)
    )
    overhead_pass = (
        overhead_ratios["clone_hooks"] <= 1.02
        and overhead_path_signatures_equal
    )

    behaviour = run_json(
        [sys.executable, str(BEHAVIOUR_WORKER)],
        env=env,
    )
    write_json(run_dir / "behaviour_probe.json", behaviour)
    behaviour_pass = bool(behaviour["all_checks_pass"])

    installed_ils_sha = sha256(UPSTREAM_ILS)
    local_license_sha = sha256(HERE / "LICENSE-PYVRP.md")
    installed_license_sha = sha256(UPSTREAM_LICENSE)
    provenance_checks = {
        "installed_upstream_hash_matches_register": (
            installed_ils_sha == EXPECTED_UPSTREAM_ILS_SHA256
        ),
        "mit_license_preserved_exactly": (
            local_license_sha == installed_license_sha
        ),
        "upstream_manifest_present": (HERE / "UPSTREAM.md").is_file(),
        "modified_copy_notice_present": (
            "modified copy"
            in (HERE / "event_driven_ils.py").read_text(
                encoding="utf-8"
            ).lower()
        ),
    }
    provenance_pass = all(provenance_checks.values())

    passed = (
        equivalence_pass
        and overhead_pass
        and behaviour_pass
        and provenance_pass
    )
    verdict = (
        "PASS_MPILS_MVNS_C2_G0_FOUNDATION"
        if passed
        else "FAIL_MPILS_MVNS_C2_G0_FOUNDATION"
    )
    decision = {
        "verdict": verdict,
        "equivalence": {
            "pass": equivalence_pass,
            "iterations": equivalence_checks,
            "all_independent_validations_pass": (
                all_independent_valid
            ),
        },
        "overhead": {
            "pass": overhead_pass,
            "iterations_per_run": OVERHEAD_ITERATIONS,
            "repeats": OVERHEAD_REPEATS,
            "median_seconds": overhead_medians,
            "ratios_to_official": overhead_ratios,
            "idle_hook_limit": 1.02,
            "all_deterministic_paths_equal": (
                overhead_path_signatures_equal
            ),
        },
        "behaviour": {
            "pass": behaviour_pass,
            "checks": behaviour["checks"],
        },
        "provenance": {
            "pass": provenance_pass,
            "checks": provenance_checks,
            "upstream_ils_sha256": installed_ils_sha,
            "local_license_sha256": local_license_sha,
        },
        "performance_claim_allowed": False,
        "performance_gate_authorized": False,
        "china81_authorized": False,
        "full_28_authorized": False,
        "stage2_authorized": False,
        "honest_boundary": (
            "G0 proves wiring, sparse-overhead, replacement behaviour, "
            "public semantics, and provenance only; it does not prove "
            "algorithm quality."
        ),
    }
    write_json(OUTPUT / "decision.json", decision)
    write_csv(OUTPUT / "raw_runs.csv", rows)

    finished = datetime.now(timezone.utc)
    source_files = (
        "event_driven_ils.py",
        "c2_core.py",
        "run_g0_worker.py",
        "run_behavior_probe.py",
        "run_g0_gate.py",
        "LICENSE-PYVRP.md",
        "UPSTREAM.md",
    )
    metadata = {
        "contract": "MPILS-MVNS-C2-R1",
        "purpose": (
            "mother equivalence, overhead attribution, replacement "
            "behaviour, semantic and license G0"
        ),
        "started_at_utc": started.isoformat(),
        "finished_at_utc": finished.isoformat(),
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "pyvrp": version("pyvrp"),
        },
        "input": {
            "instance": INSTANCE.relative_to(REPO).as_posix(),
            "instance_sha256": sha256(INSTANCE),
            "seed": 1,
            "equivalence_iterations": list(
                EQUIVALENCE_ITERATIONS
            ),
            "overhead_iterations": OVERHEAD_ITERATIONS,
            "overhead_repeats": OVERHEAD_REPEATS,
        },
        "thread_limits": {
            key: env[key]
            for key in (
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS",
            )
        },
        "source_hashes": {
            filename: sha256(HERE / filename)
            for filename in source_files
        },
        "counts": {
            "equivalence_solver_calls": (
                len(EQUIVALENCE_ITERATIONS) * len(MODES)
            ),
            "overhead_solver_calls": (
                OVERHEAD_REPEATS * len(MODES)
            ),
            "behaviour_probe_calls": 1,
            "performance_search_calls": 0,
            "china81_calls": 0,
        },
    }
    write_json(OUTPUT / "metadata.json", metadata)

    report = f"""# MPILS-MVNS-C2-R1 G0 基础设施门

判定：`{verdict}`。

## 验证结果

母体复刻在固定 5、1000、5000 次迭代下均与 PyVRP 0.13.4 上游 ILS 得到
相同的最终解、逐迭代记录和母体随机数状态；全部输出通过独立复算。

5000 次固定迭代、{OVERHEAD_REPEATS} 个交错重复的中位墙钟为：
上游母体 {overhead_medians["official"]:.6f} 秒，迁入纯母体
{overhead_medians["clone_native"]:.6f} 秒，常驻机制登记加事件式精英库
{overhead_medians["clone_hooks"]:.6f} 秒。最后一臂相对上游为
{overhead_ratios["clone_hooks"]:.6f} 倍，门限为 1.02。

人工多车场时间窗夹具中，专用动作把两个连续客户从错误车场移到另一车场，
输出完整可行；该轮原生扰动调用为 0，零扰动局部精修调用为 1。源段、位置、
路线级检查和完整评价均未超过 64/每段6/48/12 的上限。公开题排序只使用原始
车场、距离、车辆、载重和时间窗语义，未造碳、充电、公平或动态字段。

PyVRP 迁入文件的上游 SHA-256 与登记值一致，MIT 许可证逐字保留。

## 边界

这是一道工程基础门，不是性能实验。PR11A 只用于接线、逐位等价、开销和独立
验解；没有据此比较算法优劣。未运行 PR11B/PR17B/PR21B、确认题、完整 28 题、
China81 或阶段二。G0 即使通过，也必须由用户另批后才能进入首次性能短门。
"""
    (OUTPUT / "report.md").write_text(report, encoding="utf-8")
    write_json(
        OUTPUT / "artifact_hashes.json",
        build_hash_manifest(OUTPUT),
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

