from __future__ import annotations

from pathlib import Path

from baselines.model_verification import paper_math_audit_20260716 as audit


def conditional_abstract_tex() -> str:
    return (
        r"\IfFileExists{generated_tables/e7_dynamic_abstract_zh.tex}{"
        r"\Abstract{\input{generated_tables/e7_dynamic_abstract_zh.tex}}}"
        r"{\Abstract{待完成摘要}}"
    )


def test_active_abstract_uses_pending_branch_until_final_file_exists(
    tmp_path: Path, monkeypatch
) -> None:
    paper = tmp_path / "paper.tex"
    monkeypatch.setattr(audit, "PAPER", paper)

    assert audit.active_abstract(conditional_abstract_tex()) == "待完成摘要"


def test_active_abstract_uses_generated_final_branch(
    tmp_path: Path, monkeypatch
) -> None:
    paper = tmp_path / "paper.tex"
    final = tmp_path / "generated_tables/e7_dynamic_abstract_zh.tex"
    final.parent.mkdir()
    final.write_text("正式动态摘要", encoding="utf-8")
    monkeypatch.setattr(audit, "PAPER", paper)

    assert audit.active_abstract(conditional_abstract_tex()) == "正式动态摘要"


def test_current_manuscript_closes_carbon_and_participation_semantics() -> None:
    tex = audit.PAPER.read_text(encoding="utf-8")
    rows = {row["check"]: row for row in audit.audit_notation_and_cost_semantics(tex)}

    required = {
        "成本与碳价的语义上标使用正体",
        "电网碳强度量纲与数值范围闭合",
        "预测碳强度与事后实际碳强度分离",
        "充电桩容量按连续时间并发核验",
        "正式碳信用合同与证据一致",
        "参与底线关闭语义准确",
        "原责任车场的跨场摩擦为零",
    }
    assert required <= rows.keys()
    assert all(rows[name]["status"] == "PASS" for name in required)


def test_bare_semantic_superscript_is_rejected() -> None:
    tex = audit.PAPER.read_text(encoding="utf-8")
    mutated = tex.replace(r"C_{kp}^{\mathrm{op}}", r"C_{kp}^{op}", 1)
    assert mutated != tex

    rows = {row["check"]: row for row in audit.audit_notation_and_cost_semantics(mutated)}
    assert rows["成本与碳价的语义上标使用正体"]["status"] == "FAIL"


def test_pending_manuscript_cannot_look_like_completed_e7_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    tex = audit.PAPER.read_text(encoding="utf-8")
    pending_paper = tmp_path / "paper_main.tex"
    pending_paper.write_text(tex, encoding="utf-8")
    monkeypatch.setattr(audit, "PAPER", pending_paper)

    abstract = audit.active_abstract(tex)
    assert "动态事件流检验模型与算法" not in abstract
    assert "滚动重规划结果表明" not in abstract
    assert "阶段稿提示" not in tex
    assert "E7动态正式证据尚未接入" not in tex
    assert r"\newif\ifESevenReady" in tex
    assert r"\ifESevenReady" in tex
    assert r"\input{generated_tables/e7_dynamic_policy_comparison.tex}" in tex
