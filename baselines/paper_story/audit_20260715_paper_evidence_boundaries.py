#!/usr/bin/env python3
"""Audit manuscript claims against sealed ReSETP experiment evidence."""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
import statistics
import subprocess
import sys
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from baselines.paper_story import build_20260715_formal_evidence as evidence_builder

TEX = ROOT / "docs/paper_submission_final/paper_main.tex"
PAPER_DIR = TEX.parent
PAPER_PDF = PAPER_DIR / "paper_main.pdf"
PAPER_LOG = PAPER_DIR / "paper_main.log"
PAPER_FLS = PAPER_DIR / "paper_main.fls"
QUALITY_GATES = (
    ROOT / "docs/handoff/resetp_research_experiment_writing_quality_gates_20260715.md"
)
COMPLETION_MATRIX = ROOT / "docs/handoff/resetp_goal_completion_matrix_20260716.md"
HANDOFF = ROOT / "HANDOFF.md"
PROJECT_MEMORY = ROOT / "docs/handoff/memory/MEMORY.md"
DYNAMIC_MEMORY = ROOT / "docs/handoff/memory/dynamic-demand-integration.md"
PRD_MEMORY = ROOT / "docs/handoff/memory/project-prd-execution-v2.md"
FINAL_RECORD_MARKER = "E7正式结果终验"
TABLES = ROOT / "docs/paper_submission_final/generated_tables"
E1 = ROOT / "baselines/e1_model/e1_submission_20260711_committed/formal"
E1_SEAL_COMMIT = "28c91128855e50c5e6e6ebcafa6cfeb089ecddf5"
E2 = ROOT / "baselines/e2_alns/e2_final_10seed_20260711/formal"
E2_SEAL_COMMIT = "1180abf3e3bb6a69442403fc7521801babd7b4ac"
E2_SEAL_TAG = "e2-10seed-final-20260712"
E2_LEGACY_UNLISTED = {
    "baselines/e2_alns/e2_final_10seed_20260711/formal/baseline_parameter_appendix.csv",
    "baselines/e2_alns/e2_final_10seed_20260711/formal/baseline_parameter_appendix.md",
}
E2B = ROOT / "baselines/e2_alns/e2b_component_ablation_formal_20260715"
E3 = ROOT / "baselines/e3_ablation/e3_medium_paired_cost_formal_20260715"
E6 = ROOT / "baselines/e6_fairness/e6_profit_guarantee_frontier_20260715"
E7_FORMAL = ROOT / "baselines/e7_dynamic/e7_multinetwork_formal_20260715"
E7_REPLAY = ROOT / "baselines/e7_dynamic/e7_multiday_zero_search_replay_20260715"
E7_REPLAY_INVARIANTS = (
    ROOT / "baselines/e7_dynamic/e7_replay_invariants_audit_20260715"
)
E7_AUDIT = ROOT / "baselines/e7_dynamic/e7_multinetwork_independent_audit_20260715"
E7_EXHIBITS = (
    "e7_dynamic_policy_comparison.tex",
    "e7_dynamic_mechanism_diagnostics.tex",
    "e7_dynamic_charging_replay.tex",
    "e7_dynamic_interpretation.tex",
    "e7_dynamic_conclusion.tex",
    "e7_dynamic_abstract_zh.tex",
    "e7_dynamic_abstract_en.tex",
)
E7_REPLAY_INVARIANT_COUNTS = {
    "full_task_count": 30,
    "task_day_row_count": 840,
    "window_violation_count": 0,
    "station_capacity_violation_count": 0,
    "route_hash_failure_count": 0,
    "energy_hash_failure_count": 0,
    "emissions_recalculation_failure_count": 0,
    "route_search_evaluations": 0,
}
REQUIRED_EXPERIMENT_SURFACES = (
    "metadata.json",
    "raw_runs.csv",
    "decision.json",
    "artifact_hashes.json",
    "report.md",
)


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


def verify_manifest(root: Path) -> list[str]:
    manifest_path = root / "artifact_hashes.json"
    if not manifest_path.is_file():
        return [f"{display_path(root)}: artifact_hashes.json missing"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        return [f"{display_path(root)}: artifact_hashes.json is not an object"]
    label = display_path(root)
    observed = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and path.name != ".DS_Store"
        and ".tasks" not in path.parts
    }
    failures = [
        f"{label}: unlisted {relative}"
        for relative in sorted(observed - set(manifest))
    ]
    failures.extend(
        f"{label}: missing {relative}"
        for relative in sorted(set(manifest) - observed)
    )
    failures.extend(
        f"{label}: hash drift {relative}"
        for relative, expected in manifest.items()
        if (root / relative).is_file() and sha256(root / relative) != expected
    )
    return failures


def required_surface_failures(root: Path) -> list[str]:
    """Require the five user-facing experiment record surfaces, not only a manifest."""
    label = display_path(root)
    return [
        f"{label}: required experiment surface missing {name}"
        for name in REQUIRED_EXPERIMENT_SURFACES
        if not (root / name).is_file()
    ]


def final_record_failures() -> list[str]:
    failures: list[str] = []
    for path in (HANDOFF, PROJECT_MEMORY, DYNAMIC_MEMORY, PRD_MEMORY):
        if not path.is_file():
            failures.append(f"final record surface missing: {display_path(path)}")
            continue
        if FINAL_RECORD_MARKER not in path.read_text(encoding="utf-8"):
            failures.append(
                f"final record marker missing from {display_path(path)}: {FINAL_RECORD_MARKER}"
            )
    return failures


def verify_legacy_manifest(
    root: Path, *, allowed_unlisted: set[str] | None = None
) -> list[str]:
    """Verify the old ``file_count/files`` manifest without rewriting it."""

    allowed = allowed_unlisted or set()
    label = display_path(root)
    manifest_path = root / "artifact_hashes.json"
    if not manifest_path.is_file():
        return [f"{label}: legacy artifact_hashes.json missing"]
    manifest = read_json(manifest_path)
    rows = manifest.get("files")
    if not isinstance(rows, list):
        return [f"{label}: legacy manifest files list missing"]
    failures: list[str] = []
    if int(manifest.get("file_count", -1)) != len(rows):
        failures.append(f"{label}: legacy manifest file_count differs")
    listed: set[str] = set()
    root_prefix = f"{label}/"
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            failures.append(f"{label}: legacy manifest row {index} is not an object")
            continue
        relative = str(row.get("path", ""))
        expected = str(row.get("sha256", ""))
        if not relative.startswith(root_prefix):
            failures.append(f"{label}: legacy path escapes evidence root: {relative}")
            continue
        if relative in listed:
            failures.append(f"{label}: duplicate legacy path {relative}")
            continue
        listed.add(relative)
        path = ROOT / relative
        if not path.is_file():
            failures.append(f"{label}: legacy missing {relative}")
        elif sha256(path) != expected:
            failures.append(f"{label}: legacy hash drift {relative}")
    observed = {
        str(path.relative_to(ROOT))
        for path in root.rglob("*")
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and path.name != ".DS_Store"
    }
    unexpected = observed - listed
    if unexpected != allowed:
        failures.extend(
            f"{label}: legacy unlisted {relative}"
            for relative in sorted(unexpected - allowed)
        )
        failures.extend(
            f"{label}: declared legacy exception absent {relative}"
            for relative in sorted(allowed - unexpected)
        )
    return failures


def _git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def verify_sealed_git_tree(
    root: Path, commit: str, *, annotated_tag: str | None = None
) -> list[str]:
    """Prove that the current evidence tree is byte-identical to its seal commit."""

    label = display_path(root)
    failures: list[str] = []
    commit_check = _git(["cat-file", "-e", f"{commit}^{{commit}}"])
    if commit_check.returncode != 0:
        return [f"{label}: seal commit unavailable: {commit}"]
    if annotated_tag:
        resolved = _git(["rev-parse", f"{annotated_tag}^{{}}"])
        if resolved.returncode != 0 or resolved.stdout.strip() != commit:
            failures.append(
                f"{label}: annotated tag does not resolve to seal commit: {annotated_tag}"
            )
    tree = _git(["ls-tree", "-r", "--name-only", commit, "--", label])
    if tree.returncode != 0:
        return failures + [f"{label}: cannot read sealed git tree"]
    expected_paths = {row for row in tree.stdout.splitlines() if row}
    current_paths = {
        str(path.relative_to(ROOT))
        for path in root.rglob("*")
        if path.is_file() and not path.name.startswith("._") and path.name != ".DS_Store"
    }
    for relative in sorted(current_paths - expected_paths):
        failures.append(f"{label}: file added after seal {relative}")
    for relative in sorted(expected_paths - current_paths):
        failures.append(f"{label}: sealed file missing {relative}")
    diff = _git(["diff", "--quiet", commit, "--", label])
    if diff.returncode == 1:
        failures.append(f"{label}: tracked bytes or modes drifted after seal")
    elif diff.returncode != 0:
        failures.append(f"{label}: git diff against seal commit failed")
    return failures


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=PAPER_DIR,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def verify_paper_build() -> tuple[list[str], dict[str, Any], list[str]]:
    """Verify that the current PDF is a successful, current build of the TeX tree."""

    failures: list[str] = []
    warnings: list[str] = []
    info: dict[str, Any] = {}
    for required in (TEX, PAPER_PDF, PAPER_LOG, PAPER_FLS):
        if not required.is_file():
            failures.append(f"paper build artifact missing: {display_path(required)}")
    if failures:
        return failures, info, warnings

    log_text = PAPER_LOG.read_text(encoding="utf-8", errors="replace")
    fatal_patterns = {
        "undefined control sequence": r"Undefined control sequence",
        "undefined citation or reference": (
            r"LaTeX Warning:.*undefined|Citation .* undefined|Reference .* undefined|"
            r"There were undefined references"
        ),
        "multiply defined labels": r"multiply defined",
        "fatal TeX stop": r"Emergency stop|Fatal error|^!",
    }
    for label, pattern in fatal_patterns.items():
        if re.search(pattern, log_text, flags=re.IGNORECASE | re.MULTILINE):
            failures.append(f"paper compile log contains {label}")
    if "Output written on paper_main.xdv" not in log_text:
        failures.append("paper compile log lacks successful XeLaTeX output marker")

    pdf_mtime = PAPER_PDF.stat().st_mtime_ns
    input_paths: set[Path] = set()
    for line in PAPER_FLS.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("INPUT "):
            continue
        raw = Path(line[6:])
        path = raw if raw.is_absolute() else PAPER_DIR / raw
        path = path.resolve()
        try:
            path.relative_to(PAPER_DIR.resolve())
        except ValueError:
            continue
        if path == PAPER_PDF.resolve():
            continue
        if path.suffix.lower() in {
            ".tex",
            ".cls",
            ".sty",
            ".pdf",
            ".png",
            ".jpg",
            ".jpeg",
            ".eps",
        }:
            input_paths.add(path)
    missing_inputs = sorted(str(path) for path in input_paths if not path.is_file())
    stale_inputs = sorted(
        str(path.relative_to(ROOT))
        for path in input_paths
        if path.is_file() and path.stat().st_mtime_ns > pdf_mtime
    )
    if missing_inputs:
        failures.append(f"paper build inputs missing: {missing_inputs}")
    if stale_inputs:
        failures.append(f"paper PDF is older than inputs: {stale_inputs}")

    pdfinfo = _run_command(["pdfinfo", str(PAPER_PDF)])
    if pdfinfo.returncode != 0:
        failures.append("pdfinfo could not read paper_main.pdf")
    else:
        page_match = re.search(r"(?m)^Pages:\s+(\d+)", pdfinfo.stdout)
        page_count = int(page_match.group(1)) if page_match else 0
        info["page_count"] = page_count
        if page_count < 20:
            failures.append(f"paper PDF unexpectedly short: {page_count} pages")
        if "Page size:       595.28 x 841.89 pts (A4)" not in pdfinfo.stdout:
            failures.append("paper PDF is not the expected A4 page size")

    extraction = _run_command(["pdftotext", "-layout", str(PAPER_PDF), "-"])
    if extraction.returncode != 0:
        failures.append("pdftotext could not extract the compiled manuscript")
    else:
        extracted_compact = re.sub(r"\s+", "", extraction.stdout)
        for fragment in (
            "兼顾收益公平与时变碳强度的动态协同多车场混合车队路径优化",
            "TVCI-ALNS",
            "本文研究区域—城际配送场景下的动态协同多车场混合车队路径优化问题",
            "结果并未呈现“每增加一个组件都改善成本”的整齐阶梯",
            "五档实验覆盖9张网络、2类责任和3个种子",
            "本文同时记录每个重规划阶段的墙钟计算时间",
            "本文仍存在一定局限",
        ):
            if re.sub(r"\s+", "", fragment) not in extracted_compact:
                failures.append(f"compiled PDF text missing: {fragment}")

    fonts = _run_command(["pdffonts", str(PAPER_PDF)])
    if fonts.returncode == 0:
        non_unicode_fonts = [
            line.split()[0].split("+", 1)[-1]
            for line in fonts.stdout.splitlines()[2:]
            if len(line.split()) >= 7 and line.split()[6] == "no"
        ]
        if non_unicode_fonts:
            warnings.append(
                "embedded fonts without ToUnicode mapping: "
                + ", ".join(sorted(set(non_unicode_fonts)))
            )
        info["non_unicode_font_count"] = len(set(non_unicode_fonts))
    else:
        warnings.append("pdffonts unavailable; font mapping was not inspected")

    info.update(
        {
            "input_file_count": len(input_paths),
            "tex_sha256": sha256(TEX),
            "pdf_sha256": sha256(PAPER_PDF),
            "log_sha256": sha256(PAPER_LOG),
        }
    )
    return failures, info, warnings


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def require(text: str, fragment: str, failures: list[str], label: str) -> None:
    if fragment not in text:
        failures.append(f"manuscript missing {label}: {fragment}")


def replay_invariant_decision_failures(decision: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if decision.get("status") != "PASS_E7_REPLAY_INVARIANTS_AUDIT":
        failures.append("E7 replay-invariants audit decision does not pass")
    for field, expected in E7_REPLAY_INVARIANT_COUNTS.items():
        try:
            observed = int(decision.get(field, -1))
        except (TypeError, ValueError):
            observed = -1
        if observed != expected:
            failures.append(f"E7 replay-invariants field differs: {field} != {expected}")
    return failures


def e6_endpoint_summary() -> dict[tuple[str, float], tuple[float, float]]:
    with (E6 / "selected_frontier.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    seed_groups: dict[tuple[str, str, float], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        alpha = float(row["alpha"])
        if alpha in {0.0, 1.0}:
            seed_groups[(row["instance"], row["condition"], alpha)].append(row)
    network_rows: dict[tuple[str, float], list[tuple[float, float]]] = defaultdict(list)
    for (_instance, condition, alpha), group in seed_groups.items():
        network_rows[(condition, alpha)].append(
            (
                statistics.fmean(float(row["cost_increment_pct"]) for row in group),
                statistics.fmean(
                    float(row["selected_minimum_profit_ratio"]) for row in group
                ),
            )
        )
    return {
        key: (
            statistics.fmean(row[0] for row in values),
            statistics.fmean(row[1] for row in values),
        )
        for key, values in network_rows.items()
    }


def audit(*, allow_pending_e7: bool) -> dict[str, Any]:
    failures: list[str] = []
    text = TEX.read_text(encoding="utf-8")
    quality_text = QUALITY_GATES.read_text(encoding="utf-8")
    completion_text = COMPLETION_MATRIX.read_text(encoding="utf-8")
    paper_build_failures, paper_build_info, paper_build_warnings = verify_paper_build()
    failures.extend(paper_build_failures)

    sealed_e1_e2_failures: list[str] = []
    sealed_e1_e2_failures.extend(verify_legacy_manifest(E1))
    sealed_e1_e2_failures.extend(
        verify_sealed_git_tree(E1, E1_SEAL_COMMIT)
    )
    sealed_e1_e2_failures.extend(
        verify_legacy_manifest(E2, allowed_unlisted=E2_LEGACY_UNLISTED)
    )
    sealed_e1_e2_failures.extend(
        verify_sealed_git_tree(E2, E2_SEAL_COMMIT, annotated_tag=E2_SEAL_TAG)
    )
    failures.extend(sealed_e1_e2_failures)

    forbidden_appendix = re.search(
        r"\\appendix\b|\\begin\{appendix(?:es)?\}|\\section\{附录\}", text
    )
    if forbidden_appendix:
        failures.append("manuscript contains an appendix despite the no-appendix contract")
    expected_sections = ["引言", "问题描述及模型建立", "求解算法框架", "实验设计", "结论"]
    observed_sections = re.findall(r"(?m)^\\section\{([^}]+)\}", text)
    if observed_sections != expected_sections:
        failures.append(
            f"manuscript section sequence differs: {observed_sections}"
        )

    require(
        text,
        "区域—城际配送的困难并不只是寻找一组低成本路线",
        failures,
        "problem-first introduction",
    )
    require(
        text,
        r"\Title{兼顾收益公平与时变碳强度的动态协同多车场混合车队路径优化}",
        failures,
        "unified Chinese title",
    )
    require(
        text,
        r"\ETitle{Dynamic Collaborative Multi-depot Mixed-fleet Vehicle Routing with Profit Fairness and Time-varying Grid Carbon Intensity}",
        failures,
        "unified English title",
    )
    require(
        text,
        "本文围绕一个运营问题展开：订单持续变化时",
        failures,
        "single operating problem",
    )
    contribution = text.split("本文的主要工作为：", 1)[-1].split("\n", 1)[0]
    if "；4)" in contribution:
        failures.append("manuscript contribution paragraph still contains four competing items")
    for fragment in (
        "重要运营问题 → 可被结果否定的主张 → 必要模型与算法 → 有解释力的对照证据 → 适用边界",
        "结果方向不得作为扩跑、删流、换实例或放宽预算的门槛",
        "现象—数量—机制—边界",
        "不把“算法必须显著最好”设为论文成立条件",
    ):
        require(quality_text, fragment, failures, "ReSETP research-writing quality gate")
    for fragment in (
        "要求—证据矩阵",
        "E7小中大三网络×两责任×五流×四臂",
        "hooks事件后的唯一收口顺序",
        "不得把预检结果替代正式结果",
        "只有全部命令各自成功且矩阵所有项均已证明",
    ):
        require(completion_text, fragment, failures, "ReSETP goal-completion matrix")

    for evidence in (E2B, E3, E6):
        failures.extend(required_surface_failures(evidence))
        failures.extend(verify_manifest(evidence))

    e1 = read_json(E1 / "decision.json")
    if (
        e1.get("verdict") != "E1_280_STRUCTURE_SUPPORTED"
        or int(e1.get("mixed_rows", -1)) != 20
        or int(e1.get("cv_only_ok", -1)) != 5
        or int(e1.get("ev_only_not_found", -1)) != 5
    ):
        failures.append("E1 sealed decision differs from the accepted structure gate")

    e2 = read_json(E2 / "decision.json")
    if (
        e2.get("verdict") != "E2_10SEED_PRIMARY_LEAD_SUPPORTED"
        or int(e2.get("matrix_rows", -1)) != 810
        or int(e2.get("algorithms", -1)) != 9
        or int(e2.get("instances", -1)) != 9
        or int(e2.get("eval_budget", -1)) != 4000
        or int(e2.get("zero_violation_rows", -1)) != 810
        or int(e2.get("recalculation_ok_rows", -1)) != 810
    ):
        failures.append("E2 sealed decision differs from the accepted 810-row benchmark")
    require(
        text,
        f"TVCI-ALNS平均名次为{float(e2['primary_mean_rank']):.2f}",
        failures,
        "E2 primary mean rank",
    )
    require(
        text,
        "显著优于5种通过实现核查的对照算法",
        failures,
        "E2 restrained comparison claim",
    )
    require(
        text,
        "IWD为本研究的简化适配结果",
        failures,
        "E2 IWD implementation boundary",
    )

    e2b = read_json(E2B / "decision.json")
    if e2b.get("verdict") != "E2B_FORMAL_EVIDENCE_READY" or not e2b.get(
        "formal_inference_allowed"
    ):
        failures.append("E2b formal decision is not inference-ready")
    ba = e2b["paired_summary"]["B_minus_A_total_cost"]
    cb = e2b["paired_summary"]["C_minus_B_total_cost"]
    dc = e2b["paired_summary"]["D_minus_C_ev_indirect"]
    require(
        text,
        f"B相对A平均成本增加{float(ba['mean_delta']):.2f}",
        failures,
        "negative staged-search result",
    )
    require(
        text,
        f"{ba['right_better']}个改善、{ba['right_worse']}个变差、{ba['ties']}个持平",
        failures,
        "staged-search sign counts",
    )
    require(
        text,
        f"C相对B平均降低{abs(float(cb['mean_delta'])):.2f}",
        failures,
        "cross-depot operator result",
    )
    require(
        text,
        f"{cb['right_better']}个单元改善、{cb['right_worse']}个变差、{cb['ties']}个持平",
        failures,
        "cross-depot operator sign counts",
    )
    require(
        text,
        f"平均下降{abs(float(dc['mean_delta'])):.3f} kg",
        failures,
        "charging-timing emissions result",
    )
    require(
        text,
        "不把单独的分阶段设置写成普遍有效的性能增强",
        failures,
        "E2b claim boundary",
    )

    e3 = read_json(E3 / "decision.json")
    if e3.get("status") != "FORMAL_COMPLETE" or not e3.get(
        "trend_inference_allowed"
    ):
        failures.append("E3 medium formal decision does not allow trend inference")
    require(
        text,
        (
            f"平均协同节省分别为{float(e3['old_geographic_observed_mean_saving_pct']):.2f}\\%、"
            f"{float(e3['medium_selected_network_mean_saving_pct']):.2f}\\%和"
            f"{float(e3['old_mixed_observed_mean_saving_pct']):.2f}\\%"
        ),
        failures,
        "E3 three-level means",
    )
    require(
        text,
        f"只有{e3['raw_strictly_monotone_networks']}/9张网络严格逐档增加",
        failures,
        "E3 non-monotonic boundary",
    )
    require(
        text,
        "不支持把它写成每张网络都严格单调",
        failures,
        "E3 interpretation boundary",
    )

    e6 = read_json(E6 / "decision.json")
    if e6.get("status") != "PASS_E6_PROFIT_GUARANTEE_FRONTIER" or not e6.get(
        "formal_complete"
    ):
        failures.append("E6 frontier decision is incomplete")
    endpoints = e6_endpoint_summary()
    geo0 = endpoints[("geographic", 0.0)]
    geo1 = endpoints[("geographic", 1.0)]
    mixed0 = endpoints[("mixed", 0.0)]
    mixed1 = endpoints[("mixed", 1.0)]
    require(
        text,
        f"地理聚集情形的最低收益比从{geo0[1]:.3f}提高到{geo1[1]:.3f}",
        failures,
        "E6 geographic profit ratios",
    )
    require(
        text,
        f"平均系统成本增幅从0增加到{geo1[0]:.2f}\\%",
        failures,
        "E6 geographic endpoint cost",
    )
    require(
        text,
        f"空间交错情形的无约束方案平均最低收益比已经为{mixed0[1]:.3f}",
        failures,
        "E6 mixed unrestricted ratio",
    )
    require(
        text,
        f"保障推进到1时平均成本增幅仅为{mixed1[0]:.2f}\\%",
        failures,
        "E6 mixed endpoint cost",
    )
    require(
        text,
        "曲线无需逐档严格上升",
        failures,
        "E6 non-strict frontier boundary",
    )

    for filename in E7_EXHIBITS:
        require(
            text,
            f"generated_tables/{filename}",
            failures,
            f"E7 table hook {filename}",
        )
    require(
        text,
        "只有当阶段计算时间不超过下一触发间隔时",
        failures,
        "dynamic response-time criterion",
    )
    require(
        text,
        "批量滚动决策支持",
        failures,
        "non-realtime terminology boundary",
    )

    e7_ready = all(
        (root / "decision.json").is_file()
        for root in (E7_FORMAL, E7_REPLAY, E7_REPLAY_INVARIANTS, E7_AUDIT)
    )
    if not e7_ready:
        if not allow_pending_e7:
            failures.append(
                "E7 formal/replay/replay-invariants/independent-audit decisions are not all sealed"
            )
        if any((TABLES / filename).is_file() for filename in E7_EXHIBITS):
            failures.append("E7 manuscript exhibit exists before all E7 decisions are sealed")
    else:
        for evidence in (E7_FORMAL, E7_REPLAY, E7_REPLAY_INVARIANTS, E7_AUDIT):
            failures.extend(required_surface_failures(evidence))
            failures.extend(verify_manifest(evidence))
        failures.extend(final_record_failures())
        formal = read_json(E7_FORMAL / "decision.json")
        replay = read_json(E7_REPLAY / "decision.json")
        replay_invariants = read_json(E7_REPLAY_INVARIANTS / "decision.json")
        independent = read_json(E7_AUDIT / "decision.json")
        if formal.get("verdict") not in {
            "E7_FORMAL_EVIDENCE_COMPLETE",
            "E7_FORMAL_EVIDENCE_COMPLETE_WITH_ARM_FAILURES",
        } or formal.get("failures"):
            failures.append("E7 formal decision is not complete")
        if replay.get("status") != "PASS_E7_28DAY_ZERO_SEARCH_CHARGING_REPLAY":
            failures.append("E7 28-day replay decision does not pass")
        failures.extend(replay_invariant_decision_failures(replay_invariants))
        if (
            independent.get("verdict")
            != "PASS_E7_MULTINETWORK_FORMAL_AND_REPLAY_INDEPENDENT_AUDIT"
        ):
            failures.append("E7 independent audit decision does not pass")
        independent_checks = independent.get("checks", {})
        for field in (
            "replay_invariants_decision_pass",
            "replay_invariants_artifact_hashes_pass",
            "replay_invariant_row_count_840",
            "replay_charger_capacity_and_trigger_windows_pass",
        ):
            if independent_checks.get(field) is not True:
                failures.append(f"E7 independent audit did not enforce {field}")
        for filename in E7_EXHIBITS:
            if not (TABLES / filename).is_file():
                failures.append(f"sealed E7 manuscript exhibit missing: {filename}")
        pair_frame = pd.read_csv(E7_AUDIT / "raw_runs.csv")
        task_frame = pd.read_csv(E7_AUDIT / "task_status.csv")
        paired_frame = pd.read_csv(E7_AUDIT / "paired_summary.csv")
        replay_frame = pd.read_csv(E7_REPLAY / "summary.csv")
        expected_interpretation = evidence_builder.render_e7_interpretation(
            pair_frame, task_frame, paired_frame, replay_frame, independent
        )
        expected_conclusion = evidence_builder.render_e7_conclusion(
            pair_frame, paired_frame, replay_frame, independent
        )
        expected_abstract_zh, expected_abstract_en = evidence_builder.render_e7_abstracts(
            pair_frame, paired_frame, replay_frame, independent
        )
        for filename, expected in (
            ("e7_dynamic_interpretation.tex", expected_interpretation),
            ("e7_dynamic_conclusion.tex", expected_conclusion),
            ("e7_dynamic_abstract_zh.tex", expected_abstract_zh),
            ("e7_dynamic_abstract_en.tex", expected_abstract_en),
        ):
            path = TABLES / filename
            if path.is_file() and path.read_text(encoding="utf-8") != expected:
                failures.append(f"sealed E7 result prose is stale or altered: {filename}")
        dynamic_text = expected_interpretation + expected_conclusion
        controlled = formal.get("controlled_arm_failures", [])
        if int(independent.get("controlled_arm_failure_count", -1)) != len(controlled):
            failures.append("E7 formal and independent controlled-failure counts disagree")
        if controlled:
            require(
                dynamic_text,
                f"{len(controlled)}个受控不可执行单元",
                failures,
                "controlled E7 arm failures",
            )
        with (E7_AUDIT / "paired_summary.csv").open(
            newline="", encoding="utf-8"
        ) as handle:
            paired = list(csv.DictReader(handle))
        deadline_misses = sum(
            int(row["full_stage_deadline_miss_count"]) for row in paired
        )
        if deadline_misses:
            require(
                dynamic_text,
                f"{deadline_misses}个阶段超过下一触发间隔",
                failures,
                "E7 deadline misses",
            )
        else:
            require(
                dynamic_text,
                "全部可比较阶段均满足实时响应条件",
                failures,
                "E7 realtime result",
            )

    checks = {
        "e1_e2_sealed_and_undrifted": not sealed_e1_e2_failures,
        "no_appendix_and_setp_section_sequence": not forbidden_appendix
        and observed_sections == expected_sections,
        "paper_build_current_and_content_extractable": not paper_build_failures,
        "paper_build_info": paper_build_info,
        "paper_build_warnings": paper_build_warnings,
        "e2b_manifest_and_claims": not any("E2b" in row or "e2_alns" in row for row in failures),
        "e3_manifest_and_claims": not any("E3" in row or "e3_ablation" in row for row in failures),
        "e6_manifest_and_claims": not any("E6" in row or "e6_fairness" in row for row in failures),
        "e7_ready": e7_ready,
        "required_experiment_surfaces": not any(
            "required experiment surface missing" in row for row in failures
        ),
        "final_records_updated": e7_ready and not any(
            "final record" in row for row in failures
        ),
        "pending_e7_allowed": allow_pending_e7,
        "manuscript_path": str(TEX.relative_to(ROOT)),
    }
    return {
        "status": "PASS" if not failures else "FAIL",
        "mode": "pending_e7" if allow_pending_e7 else "final",
        "checks": checks,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-pending-e7", action="store_true")
    args = parser.parse_args()
    result = audit(allow_pending_e7=args.allow_pending_e7)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
