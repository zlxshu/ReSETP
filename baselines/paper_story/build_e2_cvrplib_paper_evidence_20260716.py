#!/usr/bin/env python3
"""Build the manuscript table and neutral prose for the formal E2 CVRPLIB layer."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import tempfile
from typing import Any

from baselines.e2_alns import run_cvrplib_optimal_benchmark_20260716 as runner


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / "baselines/e2_alns/cvrplib_optimal_search_formal_20260716"
DEFAULT_OUTPUT = ROOT / "docs/paper_submission_final/generated_tables"
TABLE_NAME = "e2_cvrplib_benchmark.tex"
INTERPRETATION_NAME = "e2_cvrplib_interpretation.tex"
PROVENANCE_NAME = "e2_cvrplib_paper_evidence_manifest.json"
REQUIRED_SOURCE_FILES = (
    "metadata.json",
    "raw_runs.csv",
    "decision.json",
    "artifact_hashes.json",
    "report.md",
    "summary_by_instance.csv",
    "summary_by_tier.csv",
)
TIER_BY_INSTANCE = {
    "X-n101-k25": "small",
    "X-n120-k6": "small",
    "X-n200-k36": "medium",
    "X-n214-k11": "medium",
    "X-n313-k71": "large",
    "X-n322-k28": "large",
}
TIER_ZH = {"small": "小规模", "medium": "中规模", "large": "大规模"}


class E2PaperEvidenceError(RuntimeError):
    """Raised when formal E2 evidence is missing, incomplete, or inconsistent."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def truthy(value: object) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def verify_source_manifest(source: Path) -> None:
    manifest_path = source / "artifact_hashes.json"
    if not manifest_path.is_file():
        raise E2PaperEvidenceError("formal E2 artifact_hashes.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise E2PaperEvidenceError("formal E2 artifact_hashes.json is not an object")
    observed = {
        str(path.relative_to(source))
        for path in source.rglob("*")
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and ".tasks" not in path.parts
        and ".tmp-" not in path.name
    }
    if observed != set(manifest):
        raise E2PaperEvidenceError("formal E2 artifact manifest path set differs")
    drift = [
        relative
        for relative, expected in manifest.items()
        if sha256(source / relative) != expected
    ]
    if drift:
        raise E2PaperEvidenceError(f"formal E2 artifact hash drift: {drift}")


def load_and_validate(source: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    missing = [name for name in REQUIRED_SOURCE_FILES if not (source / name).is_file()]
    if missing:
        raise E2PaperEvidenceError(f"formal E2 evidence files are missing: {missing}")
    verify_source_manifest(source)
    metadata = json.loads((source / "metadata.json").read_text(encoding="utf-8"))
    decision = json.loads((source / "decision.json").read_text(encoding="utf-8"))
    if tuple(metadata.get("instances", ())) != runner.FORMAL_INSTANCES:
        raise E2PaperEvidenceError("formal E2 instance contract differs")
    if tuple(metadata.get("seeds", ())) != runner.FORMAL_SEEDS:
        raise E2PaperEvidenceError("formal E2 seed contract differs")
    if int(metadata.get("eval_budget", -1)) != runner.FORMAL_EVAL_BUDGET:
        raise E2PaperEvidenceError("formal E2 evaluation budget differs")
    if not bool(decision.get("matrix_complete")) or not bool(
        decision.get("formal_contract")
    ):
        raise E2PaperEvidenceError("formal E2 task matrix or contract is incomplete")
    expected_count = len(runner.FORMAL_INSTANCES) * len(runner.FORMAL_SEEDS)
    if int(decision.get("task_count", -1)) != expected_count:
        raise E2PaperEvidenceError("formal E2 decision task count differs")
    with (source / "raw_runs.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    expected_keys = {
        runner.task_key(instance, seed)
        for instance in runner.FORMAL_INSTANCES
        for seed in runner.FORMAL_SEEDS
    }
    observed_keys = [row.get("task_key", "") for row in rows]
    if len(observed_keys) != expected_count or set(observed_keys) != expected_keys:
        raise E2PaperEvidenceError("formal E2 raw task identity matrix differs")
    if len(set(observed_keys)) != len(observed_keys):
        raise E2PaperEvidenceError("formal E2 raw task identities are duplicated")
    bks = runner.load_bks_manifest()
    for row in rows:
        instance = row["instance"]
        seed = int(row["seed"])
        if instance not in runner.FORMAL_INSTANCES or seed not in runner.FORMAL_SEEDS:
            raise E2PaperEvidenceError("formal E2 raw row has an unexpected identity")
        if int(row["eval_budget"]) != runner.FORMAL_EVAL_BUDGET:
            raise E2PaperEvidenceError("formal E2 raw row has a changed budget")
        optimum = runner.official_optimum(bks, instance)
        if int(row["published_optimum"]) != optimum:
            raise E2PaperEvidenceError("formal E2 raw row has a changed BKS")
        if row["status"] == "OK":
            if not truthy(row["feasible"]) or not truthy(row["objective_match"]):
                raise E2PaperEvidenceError("formal E2 OK row fails feasibility or objective match")
            if int(row["violation_count"]) != 0:
                raise E2PaperEvidenceError("formal E2 OK row contains a violation")
            if int(row["evaluations"]) != runner.FORMAL_EVAL_BUDGET:
                raise E2PaperEvidenceError("formal E2 OK row is under-evaluated")
            pure_cost = float(row["pure_cost"])
            expected_gap = 100.0 * (pure_cost - optimum) / optimum
            if not math.isclose(float(row["gap_pct"]), expected_gap, abs_tol=1e-10):
                raise E2PaperEvidenceError("formal E2 gap does not recompute")
    return rows, {"metadata": metadata, "decision": decision}


def valid_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if row["status"] == "OK"]


def summarize_instance(instance: str, rows: list[dict[str, str]]) -> dict[str, Any]:
    group = [row for row in rows if row["instance"] == instance]
    valid = valid_rows(group)
    result: dict[str, Any] = {
        "instance": instance,
        "customers": int(group[0]["customers"]) if group[0]["customers"] else None,
        "bks": int(group[0]["published_optimum"]),
        "task_count": len(group),
        "valid_count": len(valid),
        "failure_count": len(group) - len(valid),
    }
    if valid:
        costs = [float(row["pure_cost"]) for row in valid]
        gaps = [float(row["gap_pct"]) for row in valid]
        elapsed = [float(row["elapsed_seconds"]) for row in valid]
        result.update(
            {
                "best_cost": min(costs),
                "mean_cost": statistics.fmean(costs),
                "std_cost": statistics.stdev(costs) if len(costs) > 1 else 0.0,
                "mean_gap_pct": statistics.fmean(gaps),
                "std_gap_pct": statistics.stdev(gaps) if len(gaps) > 1 else 0.0,
                "mean_elapsed_seconds": statistics.fmean(elapsed),
            }
        )
    return result


def display_number(summary: dict[str, Any], field: str, digits: int) -> str:
    if field not in summary:
        return "--"
    return f"{float(summary[field]):.{digits}f}"


def render_table(summaries: list[dict[str, Any]]) -> str:
    lines = [
        r"\begin{tabular*}{0.98\linewidth}{@{\extracolsep{\fill}}lrrrrrrrr@{}}",
        r"\toprule",
        r"算例 & 客户数 & BKS & 有效/10 & 失败 & 最好值 & 平均值 & 平均Gap/\% & 平均耗时/s \\",
        r"\midrule",
    ]
    for summary in summaries:
        customers = "--" if summary["customers"] is None else str(summary["customers"])
        lines.append(
            f"{summary['instance']} & {customers} & {summary['bks']} & "
            f"{summary['valid_count']}/10 & {summary['failure_count']} & "
            f"{display_number(summary, 'best_cost', 1)} & "
            f"{display_number(summary, 'mean_cost', 1)} & "
            f"{display_number(summary, 'mean_gap_pct', 2)} & "
            f"{display_number(summary, 'mean_elapsed_seconds', 1)} \\\\"
        )
    lines.extend([r"\bottomrule", r"\end{tabular*}"])
    return "\n".join(lines) + "\n"


def render_interpretation(
    rows: list[dict[str, str]], summaries: list[dict[str, Any]]
) -> str:
    total_failures = sum(summary["failure_count"] for summary in summaries)
    tier_parts: list[str] = []
    for tier in ("small", "medium", "large"):
        tier_summaries = [
            summary
            for summary in summaries
            if TIER_BY_INSTANCE[summary["instance"]] == tier
            and "mean_gap_pct" in summary
        ]
        if tier_summaries:
            mean_gap = statistics.fmean(
                summary["mean_gap_pct"] for summary in tier_summaries
            )
            tier_parts.append(f"{TIER_ZH[tier]}{mean_gap:.2f}\\%")
        else:
            tier_parts.append(f"{TIER_ZH[tier]}无有效运行")
    valid_summaries = [summary for summary in summaries if "mean_gap_pct" in summary]
    if valid_summaries:
        best = min(valid_summaries, key=lambda item: item["mean_gap_pct"])
        worst = max(valid_summaries, key=lambda item: item["mean_gap_pct"])
        range_text = (
            f"逐算例平均Gap最低为{best['instance']}的{best['mean_gap_pct']:.2f}\\%，"
            f"最高为{worst['instance']}的{worst['mean_gap_pct']:.2f}\\%。"
        )
    else:
        range_text = "六个算例均未形成可用于计算Gap的有效运行。"
    failure_text = (
        "60项任务均通过独立可行性和目标值复算。"
        if total_failures == 0
        else f"60项任务中有{total_failures}项失败或无效，具体身份与原因见实验记录。"
    )
    if len(rows) != 60:
        raise E2PaperEvidenceError("formal E2 interpretation requires exactly 60 rows")
    return (
        "在4000次完整方案评价下，小、中和大规模的实例等权平均Gap分别为"
        + "、".join(tier_parts)
        + "。"
        + range_text
        + failure_text
        + "该实验只检验标准CVRP上的基础路径搜索内核，"
        "不代替多车场、混合车队、充电和时变碳强度机制的完整模型实验。\n"
    )


def build(source: Path, output: Path) -> dict[str, Any]:
    rows, contracts = load_and_validate(source)
    summaries = [summarize_instance(instance, rows) for instance in runner.FORMAL_INSTANCES]
    table = render_table(summaries)
    interpretation = render_interpretation(rows, summaries)
    atomic_write(output / TABLE_NAME, table)
    atomic_write(output / INTERPRETATION_NAME, interpretation)
    source_hashes = {
        name: sha256(source / name) for name in REQUIRED_SOURCE_FILES
    }
    provenance = {
        "source": display_path(source),
        "source_contract_sha256": contracts["metadata"]["contract_sha256"],
        "source_decision_verdict": contracts["decision"]["verdict"],
        "source_matrix_complete": contracts["decision"]["matrix_complete"],
        "source_all_valid": contracts["decision"]["all_valid"],
        "source_hashes": source_hashes,
        "generated_hashes": {
            TABLE_NAME: sha256(output / TABLE_NAME),
            INTERPRETATION_NAME: sha256(output / INTERPRETATION_NAME),
        },
    }
    atomic_write(
        output / PROVENANCE_NAME,
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
    )
    return provenance


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = build(args.source.resolve(), args.output.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
