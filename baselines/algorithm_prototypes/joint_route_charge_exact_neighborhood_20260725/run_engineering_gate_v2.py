"""JRC v2 proof and zero-objective/resource gate."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp
import os
from pathlib import Path
import py_compile
import time
import traceback


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--registration", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.project_root).resolve()
    if str(root) not in os.sys.path:
        os.sys.path.insert(0, str(root))
    from baselines.algorithm_prototypes.joint_route_charge_exact_neighborhood_20260725.common import (
        verify_registration,
    )
    from baselines.algorithm_prototypes.joint_route_charge_exact_neighborhood_20260725.engineering_worker_v2 import (
        inspect_task_with_resource,
    )
    from baselines.algorithm_prototypes.joint_route_charge_exact_neighborhood_20260725.exact_neighborhood import (
        synthetic_six_customer_equivalence,
    )
    from baselines.algorithm_prototypes.joint_route_charge_exact_neighborhood_20260725.v2_common import (
        artifact_manifest,
        verify_v2_registration,
        write_csv,
        write_json,
    )
    from baselines.algorithm_prototypes.joint_route_charge_exact_neighborhood_20260725.worker_entry import (
        EXPECTED_MODULE,
        worker_identity,
    )

    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    metadata = {
        "schema": "resetp.jrc-exact-nh-engineering.v2",
        "contract_id": "E2-JRC-EXACT-NH-001",
        "execution_harness": "absolute-v2",
        "real_neighborhood_search_launched": False,
        "workers": args.workers,
    }
    rows = []
    try:
        if args.workers != 6:
            raise RuntimeError("frozen engineering gate requires six workers")
        if Path.cwd().resolve() != root:
            raise RuntimeError("engineering main cwd is not the project root")
        if Path(args.registration).resolve().name != "g0_registration_v2.json":
            raise RuntimeError("unexpected JRC v2 registration path")
        v1 = verify_registration()
        v2 = verify_v2_registration()
        if (
            v2["tasks"] != v1["tasks"]
            or v2["limits"] != v1["limits"]
            or v2["pass_rules"] != v1["pass_rules"]
        ):
            raise RuntimeError("JRC v2 scientific contract differs from v1")
        for raw in v2["protected_sha256"]:
            if raw.endswith(".py"):
                py_compile.compile(raw, doraise=True)
        proof = synthetic_six_customer_equivalence()
        if not proof.get("equivalent"):
            raise RuntimeError("six-customer equivalence proof failed")

        context = mp.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=6, mp_context=context
        ) as executor:
            identities = list(executor.map(worker_identity, range(6)))
        expected_worker = str(
            (
                root
                / "baselines/algorithm_prototypes/"
                "joint_route_charge_exact_neighborhood_20260725/"
                "worker_entry.py"
            ).resolve()
        )
        if any(
            row["module"] != EXPECTED_MODULE
            or row["file"] != expected_worker
            or row["expected_file"] != expected_worker
            for row in identities
        ):
            raise RuntimeError("zero-instance worker identity mismatch")

        release_at = time.time() + 2.0
        payloads = [
            (task, release_at) for task in v2["tasks"]
        ]
        with ProcessPoolExecutor(
            max_workers=6, mp_context=context
        ) as executor:
            rows = list(
                executor.map(inspect_task_with_resource, payloads)
            )
        rows.sort(key=lambda row: row["task_id"])
        if len({row["worker_pid"] for row in rows}) != 6:
            raise RuntimeError("real-start resource gate did not use six workers")
        if any(
            row["selected_customer_count"] != 8
            or row["real_neighborhood_search_launched"]
            or row["worker_cwd"] != str(root)
            for row in rows
        ):
            raise RuntimeError("real-start zero-objective gate mismatch")
        aggregate_peak = sum(row["peak_rss_mib"] for row in rows)
        if os.cpu_count() is None or os.cpu_count() < 8:
            raise RuntimeError("frozen six-worker gate requires 8 logical CPUs")
        if aggregate_peak > float(v2["limits"]["aggregate_rss_mib"]):
            raise RuntimeError(
                f"aggregate worker peak {aggregate_peak:.3f} MiB exceeds "
                f"{v2['limits']['aggregate_rss_mib']} MiB"
            )
        decision = {
            "status": "PASS_JRC_EXACT_NH_ENGINEERING_GATE_V2",
            "pass": True,
            "six_customer_proof": proof,
            "zero_instance_worker_identities": identities,
            "real_start_inspections": len(rows),
            "distinct_real_start_worker_pids": 6,
            "aggregate_worker_peak_rss_mib": aggregate_peak,
            "real_neighborhood_search_launched": False,
            "authorization": "only the frozen six-task JRC G0 v2 may proceed",
        }
        write_csv(output / "raw_runs.csv", rows)
        write_json(output / "metadata.json", metadata)
        write_json(output / "decision.json", decision)
        (output / "report.md").write_text(
            "# JRC v2 工程门\n\n"
            "结论：`PASS_JRC_EXACT_NH_ENGINEERING_GATE_V2`。\n\n"
            "六客户独立穷举等价证明、静态哈希、零算例进程身份、六个"
            "真实起点只读复算、八客户邻域选择和六进程资源门全部通过；"
            "真实邻域效果搜索未启动。\n",
            encoding="utf-8",
        )
        write_json(
            output / "artifact_hashes.json", artifact_manifest(output)
        )
        write_json(
            output / "done.json",
            {"status": decision["status"], "pass": True},
        )
        return 0
    except Exception as exc:
        decision = {
            "status": "FINAL_STOP_JRC_EXACT_NH_ENGINEERING_GATE_V2",
            "pass": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "scientific_candidate_modified": False,
        }
        if rows:
            write_csv(output / "raw_runs.csv", rows)
        else:
            write_csv(
                output / "raw_runs.csv",
                [{"status": "NO_REAL_EFFECT_SEARCH_LAUNCHED"}],
            )
        write_json(output / "metadata.json", metadata)
        write_json(output / "decision.json", decision)
        (output / "report.md").write_text(
            "# JRC v2 工程门\n\n"
            f"结论：`{decision['status']}`。\n\n"
            f"失败：{type(exc).__name__}: {exc}\n",
            encoding="utf-8",
        )
        write_json(
            output / "artifact_hashes.json", artifact_manifest(output)
        )
        write_json(
            output / "done.json",
            {"status": decision["status"], "pass": False},
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
