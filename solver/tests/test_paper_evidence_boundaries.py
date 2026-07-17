from __future__ import annotations

import json
import re

from baselines.paper_story import audit_20260715_paper_evidence_boundaries as audit


def test_story_audit_manifest_is_exact(tmp_path) -> None:
    payload = b"sealed evidence\n"
    (tmp_path / "report.md").write_bytes(payload)
    (tmp_path / "artifact_hashes.json").write_text(
        json.dumps({"report.md": audit.sha256(tmp_path / "report.md")}),
        encoding="utf-8",
    )
    assert audit.verify_manifest(tmp_path) == []

    (tmp_path / "extra.txt").write_text("unlisted\n", encoding="utf-8")
    failures = audit.verify_manifest(tmp_path)
    assert failures == [f"{tmp_path}: unlisted extra.txt"]

    (tmp_path / "extra.txt").unlink()
    (tmp_path / "report.md").write_text("drift\n", encoding="utf-8")
    failures = audit.verify_manifest(tmp_path)
    assert failures == [f"{tmp_path}: hash drift report.md"]

    (tmp_path / "report.md").unlink()
    failures = audit.verify_manifest(tmp_path)
    assert failures == [f"{tmp_path}: missing report.md"]


def test_story_audit_rebuilds_and_hashes_all_seven_e7_exhibits(tmp_path) -> None:
    expected = {name: f"sealed {name}\n" for name in audit.E7_EXHIBITS}
    for name, text in expected.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    provenance = {
        "generated_hashes": {
            name: audit.sha256(tmp_path / name) for name in audit.E7_EXHIBITS
        }
    }
    assert audit.e7_generated_exhibit_failures(tmp_path, expected, provenance) == []
    target = tmp_path / audit.E7_EXHIBITS[0]
    target.write_text("tampered\n", encoding="utf-8")
    failures = audit.e7_generated_exhibit_failures(tmp_path, expected, provenance)
    assert any("does not reproduce" in failure for failure in failures)
    assert any("exhibit hash differs" in failure for failure in failures)


def test_story_audit_requires_complete_replay_invariant_counts() -> None:
    decision = {
        "status": "PASS_E7_REPLAY_INVARIANTS_AUDIT",
        **audit.E7_REPLAY_INVARIANT_COUNTS,
    }
    assert audit.replay_invariant_decision_failures(decision) == []

    decision["station_capacity_violation_count"] = 1
    assert audit.replay_invariant_decision_failures(decision) == [
        "E7 replay-invariants field differs: station_capacity_violation_count != 0"
    ]


def test_story_audit_requires_external_pause_timing_gate() -> None:
    assert "external_monitor_pause_timing_uncontaminated" in (
        audit.E7_REQUIRED_INDEPENDENT_CHECKS
    )


def test_story_audit_requires_all_five_experiment_record_surfaces(tmp_path) -> None:
    for name in audit.REQUIRED_EXPERIMENT_SURFACES:
        (tmp_path / name).write_text("{}\n", encoding="utf-8")
    assert audit.required_surface_failures(tmp_path) == []

    (tmp_path / "raw_runs.csv").unlink()
    assert audit.required_surface_failures(tmp_path) == [
        f"{tmp_path}: required experiment surface missing raw_runs.csv"
    ]


def test_story_audit_requires_final_marker_on_every_record_surface(
    tmp_path, monkeypatch
) -> None:
    paths = [tmp_path / name for name in ("HANDOFF.md", "MEMORY.md", "dynamic.md", "prd.md")]
    for path in paths:
        path.write_text(f"{audit.FINAL_RECORD_MARKER}\n", encoding="utf-8")
    monkeypatch.setattr(audit, "HANDOFF", paths[0])
    monkeypatch.setattr(audit, "PROJECT_MEMORY", paths[1])
    monkeypatch.setattr(audit, "DYNAMIC_MEMORY", paths[2])
    monkeypatch.setattr(audit, "PRD_MEMORY", paths[3])
    assert audit.final_record_failures() == []

    paths[2].write_text("pending\n", encoding="utf-8")
    assert audit.final_record_failures() == [
        f"final record marker missing from {paths[2]}: {audit.FINAL_RECORD_MARKER}"
    ]


def test_legacy_manifest_allows_only_declared_historical_exceptions(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    root = tmp_path / "evidence"
    root.mkdir()
    payload = root / "report.md"
    payload.write_text("sealed\n", encoding="utf-8")
    exception = root / "late_parameter_table.csv"
    exception.write_text("name,value\n", encoding="utf-8")
    (root / "artifact_hashes.json").write_text(
        json.dumps(
            {
                "file_count": 1,
                "files": [
                    {
                        "path": "evidence/report.md",
                        "sha256": audit.sha256(payload),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    allowed = {"evidence/late_parameter_table.csv"}
    assert audit.verify_legacy_manifest(root, allowed_unlisted=allowed) == []
    assert audit.verify_legacy_manifest(root) == [
        "evidence: legacy unlisted evidence/late_parameter_table.csv"
    ]


def test_current_paper_build_is_current_and_searchable() -> None:
    failures, info, warnings = audit.verify_paper_build()
    assert failures == []
    assert info["page_count"] >= 20
    assert info["input_file_count"] >= 10
    assert isinstance(warnings, list)


def test_story_audit_title_contract_matches_current_tex() -> None:
    text = audit.TEX.read_text(encoding="utf-8")
    assert rf"\Title{{{audit.CURRENT_TITLE_ZH}}}" in text
    assert rf"\ETitle{{{audit.CURRENT_TITLE_EN}}}" in text


def test_pending_paper_has_a_hard_e2_public_benchmark_hook() -> None:
    text = audit.TEX.read_text(encoding="utf-8")
    preamble, _ = text.split(r"\begin{document}", maxsplit=1)
    for filename in audit.E2_PUBLIC_EXHIBITS:
        assert rf"\IfFileExists{{generated_tables/{filename}}}" in preamble
    assert preamble.count(r"\IfFileExists{generated_tables/e2_solomon_") == len(
        audit.E2_PUBLIC_EXHIBITS
    )
    for filename in audit.E2_PUBLIC_GENERATED_EXHIBITS:
        assert f"generated_tables/{filename}" in text
    assert r"\newif\ifETwoPublicReady" in preamble
    assert r"\ETwoPublicReadyfalse" in preamble
    assert "generated_tables/e2_solomon_paper_evidence_manifest.json" in preamble
    assert r"\ifETwoPublicReady" in text
    assert "阶段稿提示" not in text
    if not all(
        (audit.E2_PUBLIC / filename).is_file()
        for filename in audit.E2_PUBLIC_REQUIRED_SOURCE_FILES
    ):
        assert not any(
            (audit.TABLES / filename).is_file()
            for filename in audit.E2_PUBLIC_EXHIBITS
        )


def test_solomon_main_table_uses_sintef_hierarchical_metrics() -> None:
    text = audit.TEX.read_text(encoding="utf-8")
    start = text.index(r"\subsubsection{Solomon标准算例实验}")
    end = text.index(r"\subsubsection{本文模型实验}", start)
    section = text[start:end]
    for required in audit.E2_SOLOMON_MAIN_TABLE_REQUIRED_TERMS:
        assert required in section
    for forbidden in audit.E2_SOLOMON_MAIN_TABLE_FORBIDDEN_TERMS:
        assert forbidden not in section
    assert "generated_tables/e2_solomon_class_summary.tex" in section


def test_paper_uses_one_atomic_e7_exhibit_gate() -> None:
    text = audit.TEX.read_text(encoding="utf-8")
    preamble, body = text.split(r"\begin{document}", maxsplit=1)
    assert r"\newif\ifESevenReady" in preamble
    assert r"\ESevenReadyfalse" in preamble
    assert r"\ESevenReadytrue" in preamble
    for filename in audit.E7_REQUIRED_PAPER_FILES:
        assert f"generated_tables/{filename}" in preamble
    assert preamble.count(r"\IfFileExists{generated_tables/e7_dynamic_") == len(
        audit.E7_REQUIRED_PAPER_FILES
    )
    assert r"\IfFileExists{generated_tables/e7_dynamic_" not in body


def test_path_term_uses_the_simplified_jing_glyph_everywhere() -> None:
    checked_sources = (
        audit.TEX,
        audit.ROOT
        / "baselines/paper_story/build_20260715_formal_evidence.py",
        audit.ROOT
        / "docs/paper_submission_final/generated_figures/algorithm_flow.tex",
    )
    for source in checked_sources:
        text = source.read_text(encoding="utf-8")
        assert "路径" in text
        for forbidden in audit.FORBIDDEN_PATH_GLYPHS:
            assert forbidden not in text

    paper_sources = (
        source
        for source in (audit.ROOT / "docs/paper_submission_final").rglob("*.tex")
        if not source.name.startswith("._")
    )
    traditional_jing = chr(0x5F91)
    for source in paper_sources:
        assert traditional_jing not in source.read_text(encoding="utf-8")


def test_chinese_heading_font_cannot_fall_back_to_arial_unicode() -> None:
    text = audit.TEX.read_text(encoding="utf-8")
    font_preamble = text.split(r"\begin{document}", maxsplit=1)[0]
    forbidden_fallback = "Arial" + " Unicode MS"
    assert forbidden_fallback not in font_preamble
    assert r"\IfFontExistsTF{SimHei}" in font_preamble
    assert "Noto Sans CJK SC" in font_preamble
    assert "Hiragino Sans GB" not in font_preamble
    assert "Heiti SC" not in font_preamble
    assert r"\PackageError{ReSETP}" in font_preamble


def test_paper_body_does_not_expose_the_reference_template() -> None:
    text = audit.TEX.read_text(encoding="utf-8")
    body = text.split(r"\begin{thebibliography}", maxsplit=1)[0]
    assert "陈雨蝶" not in body
    assert "母版" not in body
    assert "模板" not in body
    assert "模仿" not in body
    assert "algorithm_flow_chen" not in text
    assert "阶段稿提示" not in body
    assert "本稿不得" not in body
    assert not re.search(r"见(?:图|表)[^。\n]{0,80}\\cite", body)


def test_paper_uses_the_designated_model_and_algorithm_chapter_hierarchy() -> None:
    text = audit.TEX.read_text(encoding="utf-8")
    required = (
        r"\section{模型建立}",
        r"\subsection{问题描述}",
        r"\subsection{目标函数}",
        r"\subsection{车辆能耗与充电排放函数}",
        r"\subsection{模型建立}",
        r"\section{算法设计}",
        r"\subsection{算法流程}",
        r"\subsection{算法步骤}",
        r"\section{数值试验}",
        r"\subsection{实验设计和最终解分析}",
        r"\subsubsection{实验设计}",
        r"\subsubsection{比较方案与统计口径}",
        r"\subsubsection{模型与实现检验}",
        r"\subsection{算法有效性分析}",
        r"\subsubsection{Solomon标准算例实验}",
        r"\subsubsection{本文模型实验}",
        r"\subsubsection{算法组件作用分析}",
        r"\subsection{各机制分析}",
        r"\subsubsection{客户空间组织与协同成本}",
        r"\subsubsection{时变碳强度下的充电排放}",
        r"\subsubsection{合作参与条件}",
        r"\subsubsection{动态订单下的协同价值}",
        r"\subsection{数值试验分析讨论}",
    )
    positions = [text.index(token) for token in required]
    assert positions == sorted(positions)
    assert r"\subsection{符号说明}" not in text
    assert r"\subsection{时变碳强度充电择时}" not in text
    assert r"\subsection{滚动重规划与终止规则}" not in text
    assert r"\textbf{比较方案与统计口径。}" not in text
    assert r"\textbf{模型与实现检验。}" not in text


def test_introduction_citations_are_single_and_first_appearance_ordered() -> None:
    text = audit.TEX.read_text(encoding="utf-8")
    body, bibliography = text.split(r"\begin{thebibliography}", maxsplit=1)
    introduction = body.split(r"\section{引言}", maxsplit=1)[1].split(
        r"\section{模型建立}", maxsplit=1
    )[0]
    assert not re.findall(r"\\cite\{[^}]*,[^}]*\}", introduction)
    assert all(
        sentence.count(r"\cite{") <= 1
        for sentence in re.split(r"[。！？；\n]+", introduction)
    )

    first_appearance: list[str] = []
    for group in re.findall(r"\\cite\{([^}]+)\}", body):
        for label in group.split(","):
            label = label.strip()
            if label not in first_appearance:
                first_appearance.append(label)
    definitions = re.findall(r"\\bibitem\{([^}]+)\}", bibliography)
    assert first_appearance == definitions[: len(first_appearance)]


def test_dynamic_design_is_visible_but_results_remain_atomically_gated() -> None:
    text = audit.TEX.read_text(encoding="utf-8")
    heading = text.index(r"\subsubsection{动态订单下的协同价值}")
    result_gate = text.index(r"\ifESevenReady", heading)
    result_input = text.index(r"\input{generated_tables/e7_dynamic_interpretation.tex}")
    gate_end = text.index(r"\fi", result_input)
    assert heading < result_gate < result_input < gate_end
    assert "机制比较设置四种运行方式" in text[heading:result_gate]


def test_setp_typography_is_controlled_by_the_official_class() -> None:
    text = audit.TEX.read_text(encoding="utf-8")
    class_text = (audit.TEX.parent / "setp-new.cls").read_text(encoding="utf-8")
    assert r"\documentclass{setp-new}" in text
    assert r"\PassOptionsToClass{zihao={5}}{ctexart}" in class_text
    assert r"format     = \bfseries\zihao{-4}" in class_text
    assert r"\fontsize{9pt}{10.5pt}\selectfont" in text


def test_every_bibliography_entry_is_defined_once_and_cited() -> None:
    text = audit.TEX.read_text(encoding="utf-8")
    definitions = re.findall(r"\\bibitem\{([^}]+)\}", text)
    citations = {
        label.strip()
        for group in re.findall(r"\\cite\{([^}]+)\}", text)
        for label in group.split(",")
    }

    assert len(definitions) == len(set(definitions))
    assert citations == set(definitions)


def test_current_e2b_e3_e4_and_e6_identity_matrices_are_exact() -> None:
    assert audit.e2b_identity_failures(audit.E2B) == []
    assert audit.e3_identity_failures(audit.E3) == []
    assert audit.global_hash_manifest_failures(
        audit.E4 / "artifact_hashes.json", expected_count=262
    ) == []
    assert audit.e4_identity_failures(audit.E4) == []
    assert audit.e6_identity_failures(audit.E6) == []
