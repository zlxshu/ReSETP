from __future__ import annotations

import json

import pandas as pd

from baselines.paper_story import build_20260715_formal_evidence as builder


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
                    "full_vs_no_participation_better_worse_tied": "2/2/0",
                    "full_vs_simple_insertion_better_worse_tied": "4/0/0",
                    "full_minus_no_cooperation_net_profit_mean": 10.0,
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
                        }
                    )
    pd.DataFrame(paired_rows).to_csv(audit / "paired_summary.csv", index=False)
    pd.DataFrame(raw_rows).to_csv(audit / "raw_runs.csv", index=False)
    pd.DataFrame(task_rows).to_csv(audit / "task_status.csv", index=False)
    pd.DataFrame(replay_rows).to_csv(replay / "summary.csv", index=False)

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
    assert economics.count("禁合作 & +10.0 & +15.0 & +5.0 & +1.00 & +20.0") == 6
    assert economics.count("无参与底线 & -2.0 & +0.0 & +2.0 & +0.00 & +0.0") == 6
    assert economics.count("顺序插单 & +8.0 & +8.0 & +0.0 & +0.50 & +10.0") == 6
    assert "5/5/4/5 & 4/4 & 3/5 & 1/10 & 3/1/0 & 2/2/0 & 4/0/0" in diagnostics
    assert "4.00 & 0.50 & 100/30/10 & 140" in charging
    assert "120个任务，形成24/30个四臂完整配对" in interpretation
    assert "6个受控不可执行单元" in interpretation
    assert "50客户—地理聚集—流5—无参与底线" in interpretation
    assert "6个阶段超过下一触发间隔" in interpretation
    assert "只能解释为批量滚动决策支持" in interpretation
    assert "相对禁合作的净收益差均值为+2.5，改善/变差/持平为18/6/0" in interpretation
    assert "最有利单元是50客户—地理聚集—流1（+7.0）" in interpretation
    assert "最不利单元是50客户—地理聚集—流4（-2.0）" in interpretation
    assert "840组配对，改善/变差/持平为600/180/60" in interpretation
    assert "路径—充电联合优化的证据" in interpretation
    assert "动态正式矩阵形成24/30个四臂完整配对" in conclusion
    assert "不能压缩成单一优化目标" in conclusion
    assert "动态正式矩阵形成24/30个四臂完整配对" in abstract_zh
    assert "+2.5（18/6/0）、-2.0（0/24/0）、+8.0（24/0/0）" in abstract_zh
    assert "完整机制有6个阶段超过下一触发间隔" in abstract_zh
    assert "The formal dynamic matrix yields 24/30 complete four-arm pairs" in abstract_en
    assert "+2.5 (18/6/0) versus no cooperation" in abstract_en
    assert "batch rolling decision support rather than real-time optimization" in abstract_en
