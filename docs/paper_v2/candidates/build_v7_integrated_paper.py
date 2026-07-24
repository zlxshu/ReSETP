#!/usr/bin/env python3
"""Build a fail-closed V7 paper candidate without overwriting paper_main.tex."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[3]
PAPER = REPO / "docs/paper_v2/paper_main.tex"
CANDIDATE_DIR = REPO / "docs/paper_v2/candidates"
REGISTRATION = CANDIDATE_DIR / "v7_paper_integration_registration.json"
CAMPAIGN = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v7_small_archive_ledger_20260724"
)
LATEX_ARTIFACT_ROOT = (
    "../../baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v7_small_archive_ledger_20260724/artifacts"
)

SOURCES = {
    "frontmatter": CANDIDATE_DIR / "frontmatter_v7_candidate.tex",
    "introduction": CANDIDATE_DIR / "introduction_v7_candidate.tex",
    "model_opening": (
        CANDIDATE_DIR / "model_problem_dynamic_v7_candidate.tex"
    ),
    "algorithm": CANDIDATE_DIR / "algorithm_section_v7_candidate.tex",
    "e2_protocol": CANDIDATE_DIR / "e2_experiment_protocol_v7_candidate.tex",
    "references": CANDIDATE_DIR / "references_v7_candidate.tex",
}

PASS_GATES = (
    (
        CAMPAIGN / "release_chain",
        "PASS_E2_STAGED_V7_RELEASE_CHAIN",
    ),
    (
        CAMPAIGN / "paper_text_gate",
        "PASS_E2_V7_PAPER_TEXT_MATERIALIZATION",
    ),
    (
        CAMPAIGN / "route_text_gate",
        "PASS_E2_V7_ROUTE_TEXT_MATERIALIZATION",
    ),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_manifest(root: Path) -> None:
    manifest = read_json(root / "artifact_hashes.json")
    artifacts = manifest.get("artifacts", manifest.get("files"))
    if not isinstance(artifacts, dict) or not artifacts:
        raise RuntimeError(f"empty artifact manifest: {root}")
    for relative, expected in artifacts.items():
        path = root / relative
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"artifact hash drift: {path}")


def require_pass(root: Path, expected: str) -> None:
    decision = read_json(root / "decision.json")
    if decision.get("verdict") != expected:
        raise RuntimeError(
            f"{root}: expected {expected}, got {decision.get('verdict')}"
        )
    verify_manifest(root)


def validate_registration() -> None:
    payload = read_json(REGISTRATION)
    if (
        payload.get("operation")
        != "FAIL_CLOSED_V7_PAPER_CANDIDATE_INTEGRATION"
        or payload.get("overwrites_main_tex") is not False
    ):
        raise RuntimeError("paper integration registration is invalid")
    if sha256(PAPER) != payload["protected_main_tex_sha256"]:
        raise RuntimeError(
            "paper_main.tex changed after registration; review it before merge"
        )
    for relative, expected in payload["source_hashes"].items():
        path = REPO / relative
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"registered source drift: {relative}")


def read_source(name: str) -> str:
    return SOURCES[name].read_text(encoding="utf-8").strip()


def replace_span(
    text: str,
    start: str,
    end: str,
    replacement: str,
) -> str:
    start_index = text.find(start)
    if start_index < 0:
        raise RuntimeError(f"missing replacement start marker: {start}")
    end_index = text.find(end, start_index + len(start))
    if end_index < 0:
        raise RuntimeError(f"missing replacement end marker: {end}")
    if text.find(start, start_index + len(start), end_index) >= 0:
        raise RuntimeError(f"ambiguous replacement start marker: {start}")
    return (
        text[:start_index]
        + replacement.rstrip()
        + "\n\n"
        + text[end_index:]
    )


def replace_environment_with_label(
    text: str,
    environment: str,
    label: str,
    replacement: str,
) -> str:
    label_token = rf"\label{{{label}}}"
    label_index = text.find(label_token)
    if label_index < 0:
        raise RuntimeError(f"missing label: {label}")
    begin_token = rf"\begin{{{environment}}}"
    end_token = rf"\end{{{environment}}}"
    begin_index = text.rfind(begin_token, 0, label_index)
    end_index = text.find(end_token, label_index)
    if begin_index < 0 or end_index < 0:
        raise RuntimeError(f"cannot locate {environment} for {label}")
    end_index += len(end_token)
    return (
        text[:begin_index]
        + replacement.rstrip()
        + text[end_index:]
    )


def inject_e2_results(protocol: str, narrative: str) -> str:
    first_gate = (
        "% RESULT_TEXT_GATE:\n"
        "% Insert only the independently materialized V7 ten-seed cost/CPU,\n"
        "% win-tie-loss and genuine-trajectory paragraph here."
    )
    second_gate = (
        "% RESULT_TEXT_GATE:\n"
        "% Insert only the independently materialized V7 405-task, "
        "81-instance,\n"
        "% 27-layer, overall-reduction and Holm-adjusted inference "
        "paragraph here."
    )
    generated_header = (
        "% Generated from sealed V7 PASS evidence; do not hand-edit.\n"
    )
    if narrative.startswith(generated_header):
        narrative = narrative[len(generated_header) :]
    separator = "\n\\paragraph{全量算例结果。}\n"
    if separator not in narrative:
        raise RuntimeError("sealed E2 narrative lacks the two result blocks")
    first, second = narrative.split(separator, maxsplit=1)
    second = "\\paragraph{全量算例结果。}\n" + second
    if protocol.count(first_gate) != 1 or protocol.count(second_gate) != 1:
        raise RuntimeError("E2 result gates are missing or duplicated")
    return protocol.replace(first_gate, first.strip()).replace(
        second_gate,
        second.strip(),
    )


def public_table_block() -> str:
    note = (
        "注：表中数值为相对BKS的误差百分比；"
        "文献列取原论文报告的最好值；"
        "PyVRP-HGS与MV-HGS-SP为同机、相同时间上限、"
        "种子1--10的结果。"
    )
    return (
        "\\begin{table}[H]\n"
        "\\centering\n"
        "\\caption{标准算例实验结果}\n"
        "\\label{tab:v13-results}\n"
        "\\setptabsetup\n"
        f"\\input{{{LATEX_ARTIFACT_ROOT}/table_public_benchmark.tex}}\n"
        f"\\tabnote{{{note}}}\n"
        "\\end{table}"
    )


def carbon_figure_block() -> str:
    return (
        "\\begin{figure}[H]\n"
        "\\centering\n"
        "\\includegraphics[width=0.74\\linewidth]"
        f"{{{LATEX_ARTIFACT_ROOT}/figure3_carbon_profile.pdf}}\n"
        "\\caption{三大城市群典型日电网碳强度曲线}\n"
        "\\label{fig:carbon-profile}\n"
        "\\end{figure}"
    )


def move_objective_before_constraints(text: str) -> str:
    objective = (
        "\\begin{equation}\n"
        "\\min F=F_1+F_2+F_3+F_4+F_5+F_6. "
        "\\label{eq:obj}\n"
        "\\end{equation}\n"
    )
    if text.count(objective) != 1:
        raise RuntimeError("overall objective is missing or duplicated")
    text = text.replace(objective, "", 1)
    constraint_heading = "\\subsection{模型建立}"
    if text.count(constraint_heading) != 1:
        raise RuntimeError("constraint subsection heading is ambiguous")
    replacement = (
        "六类成本共同构成本文的总体目标函数：\n"
        + objective
        + "\n\\subsection{约束条件}"
    )
    return text.replace(constraint_heading, replacement, 1)


def transform(strict: bool) -> str:
    text = PAPER.read_text(encoding="utf-8")
    frontmatter = (
        "% --- 中文信息 ---\n" + read_source("frontmatter")
    )
    text = replace_span(
        text,
        "% --- 中文信息 ---",
        "\\begin{document}",
        frontmatter,
    )
    text = replace_span(
        text,
        "\\section{引言}",
        "% --- 文献比较表 ---",
        read_source("introduction"),
    )
    text = replace_span(
        text,
        "\\subsection{问题描述}",
        "\\begin{table}[H]\n\\centering\n\\caption{符号说明}",
        read_source("model_opening"),
    )
    text = replace_span(
        text,
        "\\subsection{动态需求处理}",
        "% ================================================================\n"
        "% SECTION 3:",
        "",
    )
    text = move_objective_before_constraints(text)
    text = replace_span(
        text,
        "\\section{算法设计}",
        "% ================================================================\n"
        "% SECTION 4:",
        read_source("algorithm"),
    )

    text = replace_environment_with_label(
        text,
        "table",
        "tab:v13-results",
        public_table_block(),
    )
    text = replace_environment_with_label(
        text,
        "figure",
        "fig:carbon-profile",
        carbon_figure_block(),
    )

    if strict:
        result_text = (
            CAMPAIGN / "paper_text_gate/e2_result_narrative.tex"
        ).read_text(encoding="utf-8")
        route_text = (
            CAMPAIGN / "route_text_gate/route_detail_narrative.tex"
        ).read_text(encoding="utf-8").strip()
        protocol = inject_e2_results(
            read_source("e2_protocol"),
            result_text,
        )
    else:
        route_text = (
            "\\subsubsection{最终解分析}\n\n"
            "% V7_ROUTE_TEXT_GATE: wait for sealed S4/S5 evidence.\n"
            "\\begin{table}[H]\n"
            "\\centering\n"
            "\\caption{仿真实验最终路径表}\n"
            "\\label{tab:final-solution}\n"
            "\\end{table}"
        )
        protocol = read_source("e2_protocol")

    text = replace_span(
        text,
        "\\subsubsection{最终解分析}",
        "\\subsection{算法有效性分析}",
        route_text,
    )
    text = replace_span(
        text,
        "\\subsubsection{本文模型实验}",
        "\\subsection{碳交易机制分析}",
        protocol,
    )

    if "\\bibitem{ref:89}" not in text:
        text = text.replace(
            "\\end{thebibliography}",
            read_source("references")
            + "\n\n\\end{thebibliography}",
            1,
        )
    validate_transformed(text, strict=strict)
    return text


def validate_transformed(text: str, strict: bool) -> None:
    required_once = (
        "\\section{引言}",
        "\\section{模型建立}",
        "\\section{算法设计}",
        "\\section{数值实验}",
        "\\subsection{问题描述与动态决策过程}",
        "\\subsection{约束条件}",
        "\\label{eq:trigger}",
        "\\label{eq:customer_update}",
        "\\label{eq:accumulation}",
        "\\label{eq:obj}",
        "\\label{fig:carbon-profile}",
        "\\label{fig:convergence}",
        "\\label{tab:final-solution}",
        "\\label{tab:algorithm-comparison}",
        "\\label{tab:china81-summary}",
    )
    for token in required_once:
        if text.count(token) != 1:
            raise RuntimeError(
                f"integrated candidate must contain once: {token}"
            )
    figure_sources = (
        (
            REPO
            / "docs/paper_v2/generated_figures/v7_candidates/"
            "algorithm_flow_v7_candidate.tex",
            "\\label{fig:algorithm-flow}",
        ),
        (
            REPO
            / "docs/paper_v2/generated_figures/v7_candidates/"
            "route_pool_v7_candidate.tex",
            "\\label{fig:route-pool}",
        ),
    )
    for path, label in figure_sources:
        if path.read_text(encoding="utf-8").count(label) != 1:
            raise RuntimeError(f"figure source lacks one label: {path}")
    objective_index = text.index("\\label{eq:obj}")
    first_constraint_index = text.index("\\label{eq:trip_flow}")
    if objective_index >= first_constraint_index:
        raise RuntimeError("overall objective still appears after constraints")

    forbidden = (
        "\\subsection{动态需求处理}",
        "corrected_china81_rerun_v4_20260724",
        "figure3_carbon_profile_v14",
        "figure4_convergence_v14",
        "三视角合计严格完成80次完整候选评价",
        "随后在5 s上限内完成路线池重组",
        "1+1+1",
        "伪代码",
        "\\begin{algorithmic}",
    )
    for token in forbidden:
        if token in text:
            raise RuntimeError(f"stale or forbidden paper text remains: {token}")
    for reference in range(89, 96):
        token = rf"\bibitem{{ref:{reference}}}"
        if text.count(token) != 1:
            raise RuntimeError(f"new reference is missing or duplicated: {token}")
    if strict and (
        "RESULT_TEXT_GATE" in text
        or "V7_ROUTE_TEXT_GATE" in text
    ):
        raise RuntimeError("sealed result text was not fully inserted")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="validate source boundaries without reading result rows",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=CANDIDATE_DIR / "paper_main_v7_integrated.tex",
    )
    args = parser.parse_args()

    validate_registration()
    if args.check_only:
        transform(strict=False)
        print("V7 paper integration structure: PASS (no result rows read)")
        return 0
    for root, expected in PASS_GATES:
        require_pass(root, expected)
    integrated = transform(strict=True)
    output = args.output.resolve()
    if output == PAPER.resolve():
        raise RuntimeError("this builder must not overwrite paper_main.tex")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(integrated, encoding="utf-8")
    print(f"V7 integrated paper candidate: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
