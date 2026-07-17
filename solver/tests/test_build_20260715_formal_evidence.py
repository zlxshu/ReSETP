from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import pytest

from baselines.paper_story import build_20260715_formal_evidence as builder


def _seal(root: Path) -> None:
    manifest = {
        str(path.relative_to(root)): builder.sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json"
    }
    (root / "artifact_hashes.json").write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )


def _table_summaries() -> tuple[pd.DataFrame, pd.DataFrame]:
    paired = []
    replay = []
    for network in builder.E7_NETWORK_LABELS:
        for condition in builder.E7_CONDITION_LABELS:
            paired.append(
                {
                    "network": network,
                    "condition": condition,
                    "paired_complete_stream_count": 5,
                    "full_executable_stream_count": 5,
                    "no_cooperation_executable_stream_count": 5,
                    "no_participation_executable_stream_count": 5,
                    "simple_insertion_executable_stream_count": 5,
                    "full_day_participation_floor_met_count": 5,
                    "full_streams_with_cross_site_service": 2,
                    "full_stage_deadline_miss_count": 0,
                    "full_deadline_comparable_stage_count": 10,
                    "full_vs_no_cooperation_better_worse_tied": "3/2/0",
                    "full_vs_no_participation_better_worse_tied": "2/3/0",
                    "full_vs_simple_insertion_better_worse_tied": "4/1/0",
                    **{
                        f"{field}_mean": 1.0
                        for comparison in builder.E7_COMPARISONS
                        for field in comparison[1:]
                    },
                }
            )
            replay.append(
                {
                    "network": network,
                    "condition": condition,
                    "arm": "full",
                    "pooled_charging_reduction_pct": 4.0,
                    "pooled_total_operational_reduction_pct": 0.5,
                    "improved": 100,
                    "worsened": 30,
                    "tied": 10,
                    "stream_day_count": 140,
                }
            )
    return pd.DataFrame(paired), pd.DataFrame(replay)


def test_e7_table_renderers_are_order_invariant_and_complete() -> None:
    paired, replay = _table_summaries()
    shuffled_paired = paired.sample(frac=1.0, random_state=17).reset_index(drop=True)
    shuffled_replay = replay.sample(frac=1.0, random_state=23).reset_index(drop=True)
    renderers = (
        (builder.render_e7_policy_comparison, 19),
        (builder.render_e7_mechanism_diagnostics, 7),
    )
    for renderer, row_terminator_count in renderers:
        assert renderer(paired) == renderer(shuffled_paired)
        assert renderer(paired).count(r"\\") == row_terminator_count
    assert builder.render_e7_charging_replay(replay) == builder.render_e7_charging_replay(
        shuffled_replay
    )
    assert builder.render_e7_charging_replay(replay).count(r"\\") == 7


def test_e7_replay_summary_tamper_and_missing_day_are_rejected() -> None:
    rows = []
    for network in builder.E7_NETWORK_LABELS:
        for condition in builder.E7_CONDITION_LABELS:
            for stream in range(1, 6):
                for day in builder.E7_OPERATING_DAYS:
                    rows.append(
                        {
                            "network": network,
                            "condition": condition,
                            "stream": stream,
                            "arm": "full",
                            "operating_day": day,
                            "actual_charging_saving_kg": 0.1,
                            "immediate_actual_charging_emissions_kg": 1.0,
                            "direct_emissions_kg": 7.0,
                            "charging_reduction_pct": 10.0,
                            "route_hash_preserved": True,
                            "energy_hash_preserved": True,
                        }
                    )
    raw = pd.DataFrame(rows)
    recomputed = builder.summarize_e7_replay(raw)
    tampered = recomputed.copy()
    tampered.loc[0, "pooled_charging_reduction_pct"] += 0.01
    with pytest.raises(builder.E7PaperEvidenceError, match="differs from recomputation"):
        builder.validate_e7_replay_summary(tampered, recomputed, "tampered")
    with pytest.raises(builder.E7PaperEvidenceError, match="exact 3 x 2 x 5 x 28"):
        builder.summarize_e7_replay(raw.iloc[:-1])


def test_e7_source_manifest_rejects_hash_drift(tmp_path: Path) -> None:
    root = tmp_path / "sealed"
    root.mkdir()
    payload = root / "payload.csv"
    payload.write_text("a,b\n1,2\n", encoding="utf-8")
    _seal(root)
    builder.verify_e7_source_manifest(root)
    payload.write_text("a,b\n1,3\n", encoding="utf-8")
    with pytest.raises(builder.E7PaperEvidenceError, match="hash drift"):
        builder.verify_e7_source_manifest(root)


def test_e7_manifest_is_withdrawn_before_interrupted_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "tables"
    output.mkdir()
    (output / builder.E7_PROVENANCE_NAME).write_text("old\n", encoding="utf-8")
    for name in builder.E7_EXHIBIT_NAMES:
        (output / name).write_text("old\n", encoding="utf-8")
    exhibits = {name: f"new {name}\n" for name in builder.E7_EXHIBIT_NAMES}
    original_replace = os.replace

    def interrupted_replace(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        if source_path.parent.name.startswith(".e7-paper-stage-") and destination_path.parent == output:
            raise OSError("injected publication interruption")
        original_replace(source, destination)

    monkeypatch.setattr(builder.os, "replace", interrupted_replace)
    with pytest.raises(OSError, match="publication interruption"):
        builder.publish_e7_bundle(output, exhibits, {"schema_version": "test"})
    assert not (output / builder.E7_PROVENANCE_NAME).exists()


def test_e7_tables_keep_economic_decomposition_and_diagnostics(tmp_path, monkeypatch) -> None:
    audit = tmp_path / "audit"
    replay = tmp_path / "replay"
    tables = tmp_path / "tables"
    audit.mkdir()
    replay.mkdir()
    tables.mkdir()
    monkeypatch.setattr(builder, "E7_AUDIT", audit)
    monkeypatch.setattr(builder, "E7_REPLAY", replay)
    monkeypatch.setattr(builder, "TABLES", tables)

    (audit / "decision.json").write_text(
        json.dumps(
            {
                "verdict": "PASS_E7_MULTINETWORK_FORMAL_AND_REPLAY_INDEPENDENT_AUDIT",
                "controlled_arm_failure_count": 6,
            }
        ),
        encoding="utf-8",
    )
    paired_rows = []
    replay_rows = []
    raw_rows = []
    task_rows = []
    for network in ("N114", "N221", "N322"):
        for condition in ("geographic", "historical_mixed"):
            paired_rows.append(
                {
                    "network": network,
                    "condition": condition,
                    "expected_stream_count": 5,
                    "paired_complete_stream_count": 4,
                    "full_executable_stream_count": 5,
                    "no_cooperation_executable_stream_count": 5,
                    "no_participation_executable_stream_count": 4,
                    "simple_insertion_executable_stream_count": 5,
                    "full_day_participation_floor_met_count": 4,
                    "full_streams_with_cross_site_service": 3,
                    "full_stage_deadline_miss_count": 1,
                    "full_deadline_comparable_stage_count": 10,
                    "full_maximum_stage_elapsed_seconds": 42.0,
                    "full_vs_no_cooperation_better_worse_tied": "3/1/0",
                    "full_vs_no_participation_better_worse_tied": "0/4/0",
                    "full_vs_simple_insertion_better_worse_tied": "4/0/0",
                    "full_minus_no_cooperation_net_profit_mean": 2.5,
                    "full_minus_no_cooperation_revenue_mean": 15.0,
                    "full_minus_no_cooperation_cost_mean": 5.0,
                    "full_minus_no_cooperation_completed_customer_count_mean": 1.0,
                    "full_minus_no_cooperation_completed_demand_mean": 20.0,
                    "full_minus_no_participation_net_profit_mean": -2.0,
                    "full_minus_no_participation_revenue_mean": 0.0,
                    "full_minus_no_participation_system_cost_mean": 2.0,
                    "full_minus_no_participation_completed_customer_count_mean": 0.0,
                    "full_minus_no_participation_completed_demand_mean": 0.0,
                    "full_minus_simple_insertion_net_profit_mean": 8.0,
                    "full_minus_simple_insertion_revenue_mean": 8.0,
                    "full_minus_simple_insertion_cost_mean": 0.0,
                    "full_minus_simple_insertion_completed_customer_count_mean": 0.5,
                    "full_minus_simple_insertion_completed_demand_mean": 10.0,
                }
            )
            replay_rows.append(
                {
                    "network": network,
                    "condition": condition,
                    "pooled_charging_reduction_pct": 4.0,
                    "pooled_total_operational_reduction_pct": 0.5,
                    "improved": 100,
                    "worsened": 30,
                    "tied": 10,
                    "stream_day_count": 140,
                }
            )
            for stream in range(1, 6):
                executable = stream < 5
                raw_rows.append(
                    {
                        "network": network,
                        "condition": condition,
                        "stream": stream,
                        "all_four_arms_executable": executable,
                        "full_day_participation_floor_met": executable,
                        "full_minus_no_cooperation_net_profit": 10.0 - 3.0 * stream if executable else "",
                        "full_minus_no_cooperation_revenue": 15.0 if executable else "",
                        "full_minus_no_cooperation_cost": 5.0 if executable else "",
                        "full_minus_no_cooperation_completed_customer_count": 1.0 if executable else "",
                        "full_minus_no_cooperation_completed_demand": 20.0 if executable else "",
                        "full_minus_no_participation_net_profit": -2.0 if executable else "",
                        "full_minus_no_participation_revenue": 0.0 if executable else "",
                        "full_minus_no_participation_system_cost": 2.0 if executable else "",
                        "full_minus_no_participation_completed_customer_count": 0.0 if executable else "",
                        "full_minus_no_participation_completed_demand": 0.0 if executable else "",
                        "full_minus_simple_insertion_net_profit": 8.0 if executable else "",
                        "full_minus_simple_insertion_revenue": 8.0 if executable else "",
                        "full_minus_simple_insertion_cost": 0.0 if executable else "",
                        "full_minus_simple_insertion_completed_customer_count": 0.5 if executable else "",
                        "full_minus_simple_insertion_completed_demand": 10.0 if executable else "",
                    }
                )
                for arm in ("full", "no_cooperation", "no_participation", "simple_insertion"):
                    failed = stream == 5 and arm == "no_participation"
                    task_rows.append(
                        {
                            "network": network,
                            "condition": condition,
                            "stream": stream,
                            "arm": arm,
                            "execution_status": "HALT_NO_EXECUTABLE_CONTINUATION" if failed else "PASS",
                            "deadline_comparable_stage_count": 2 if arm == "full" else 0,
                            "stage_deadline_miss_count": (
                                1 if arm == "full" and stream == 1 else 0
                            ),
                            "maximum_stage_elapsed_seconds": 42.0 if arm == "full" else 0.0,
                        }
                    )
    pd.DataFrame(paired_rows).to_csv(audit / "paired_summary.csv", index=False)
    pd.DataFrame(raw_rows).to_csv(audit / "raw_runs.csv", index=False)
    pd.DataFrame(task_rows).to_csv(audit / "task_status.csv", index=False)
    replay_raw_rows = []
    for network in ("N114", "N221", "N322"):
        for condition in ("geographic", "historical_mixed"):
            cell = 0
            for stream in range(1, 6):
                for day in builder.E7_OPERATING_DAYS:
                    saving = 0.1 if cell < 100 else (-4.4 / 30 if cell < 130 else 0.0)
                    replay_raw_rows.append(
                        {
                            "network": network,
                            "condition": condition,
                            "stream": stream,
                            "arm": "full",
                            "operating_day": day,
                            "actual_charging_saving_kg": saving,
                            "immediate_actual_charging_emissions_kg": 1.0,
                            "direct_emissions_kg": 7.0,
                            "charging_reduction_pct": 100.0 * saving,
                            "route_hash_preserved": True,
                            "energy_hash_preserved": True,
                        }
                    )
                    cell += 1
    replay_summary = builder.summarize_e7_replay(pd.DataFrame(replay_raw_rows))
    replay_summary.to_csv(replay / "summary.csv", index=False)
    replay_summary.to_csv(audit / "replay_summary.csv", index=False)
    pd.DataFrame(replay_raw_rows).to_csv(replay / "raw_runs.csv", index=False)
    (audit / "metadata.json").write_text("{}\n", encoding="utf-8")
    (audit / "report.md").write_text("fixture\n", encoding="utf-8")
    (replay / "metadata.json").write_text("{}\n", encoding="utf-8")
    (replay / "report.md").write_text("fixture\n", encoding="utf-8")
    (replay / "task_inventory.json").write_text("[]\n", encoding="utf-8")
    (replay / "decision.json").write_text(
        json.dumps(
            {
                "status": "PASS_E7_28DAY_ZERO_SEARCH_CHARGING_REPLAY",
                "paired_day_row_count": 840,
                "route_search_evaluations": 0,
            }
        ),
        encoding="utf-8",
    )
    _seal(audit)
    _seal(replay)

    builder.build_e7()

    economics = (tables / "e7_dynamic_policy_comparison.tex").read_text(
        encoding="utf-8"
    )
    diagnostics = (tables / "e7_dynamic_mechanism_diagnostics.tex").read_text(
        encoding="utf-8"
    )
    charging = (tables / "e7_dynamic_charging_replay.tex").read_text(
        encoding="utf-8"
    )
    interpretation = (tables / "e7_dynamic_interpretation.tex").read_text(
        encoding="utf-8"
    )
    conclusion = (tables / "e7_dynamic_conclusion.tex").read_text(encoding="utf-8")
    abstract_zh = (tables / "e7_dynamic_abstract_zh.tex").read_text(encoding="utf-8")
    abstract_en = (tables / "e7_dynamic_abstract_en.tex").read_text(encoding="utf-8")
    assert economics.count("禁合作 & +2.5 & +15.0 & +5.0 & +1.00 & +20.0") == 6
    assert economics.count("无参与底线 & -2.0 & +0.0 & +2.0 & +0.00 & +0.0") == 6
    assert economics.count("顺序插入基线 & +8.0 & +8.0 & +0.0 & +0.50 & +10.0") == 6
    assert "5/5/4/5 & 4/4 & 3/5 & 1/10 & 3/1/0 & 0/4/0 & 4/0/0" in diagnostics
    assert "4.00 & 0.50 & 100/30/10 & 140" in charging
    assert "120个任务，其中24/30个订单流的四种机制均可执行" in interpretation
    assert "6个受控不可执行单元" in interpretation
    assert "50客户—地理聚集—流5—无参与底线" in interpretation
    assert "6个阶段超过下一触发间隔" in interpretation
    assert "只能解释为批量滚动决策支持" in interpretation
    assert "相对禁合作的净收益差均值为+2.5，改善/变差/持平为18/6/0" in interpretation
    assert "最有利单元是50客户—地理聚集—流1（+7.0）" in interpretation
    assert "最不利单元是50客户—地理聚集—流4（-2.0）" in interpretation
    assert "840组配对，改善/变差/持平为600/180/60" in interpretation
    assert "路径—充电联合优化的证据" in interpretation
    assert "动态实验中，24/30个订单流的四种机制均可执行" in conclusion
    assert "不能压缩成单一优化目标" in conclusion
    assert "建立可行配送趟—实体车排班两层路径优化模型" in abstract_zh
    assert "通过区域配送网络、连续电网日和动态事件流检验模型与算法" in abstract_zh
    assert "公开算例" not in abstract_zh
    assert "充电择时是路径与车型减排的补充" in abstract_zh
    assert not any(char.isdigit() for char in abstract_zh)
    assert 200 <= len(abstract_zh.replace(r"\%", "%").strip()) <= 300
    assert "A two-layer routing model is established" in abstract_en
    assert "Regional delivery networks, consecutive grid days" in abstract_en
    assert "Public instances" not in abstract_en
    assert "charging timing complements route- and fleet-based abatement" in abstract_en
    provenance = json.loads(
        (tables / builder.E7_PROVENANCE_NAME).read_text(encoding="utf-8")
    )
    assert provenance["coverage"] == {
        "formal_tasks": 120,
        "stream_pairs": 30,
        "network_condition_cells": 6,
        "replay_pairs": 840,
        "reader_facing_exhibits": 7,
    }
    assert provenance["builder_sha256"] == builder.sha256(Path(builder.__file__).resolve())
    assert provenance["generated_hashes"] == {
        name: builder.sha256(tables / name) for name in builder.E7_EXHIBIT_NAMES
    }
