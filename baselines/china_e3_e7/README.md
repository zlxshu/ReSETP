# 中国 E3–E7 适配底座

这个目录只负责中国主线的合同、任务投影、证据字段、统计、图表和论文产物接线。当前合同是 `FOUNDATION_ONLY_FORMAL_SEARCH_DISABLED`；运行入口不会启动求解器搜索。

默认底座：

```bash
python3 baselines/china_e3_e7/adapter.py foundation
```

只读预检和任务投影：

```bash
python3 baselines/china_e3_e7/adapter.py preflight
python3 baselines/china_e3_e7/adapter.py plan --out /tmp/china-e3-e7-plan
```

后续正式批次完成并封存 raw ledger 后，统计、图和表分别由下列入口生成：

```bash
python3 baselines/china_e3_e7/adapter.py aggregate --raw path/to/raw_runs.csv --out path/to/aggregates
python3 baselines/china_e3_e7/adapter.py plot --raw path/to/raw_runs.csv --out path/to/figures
python3 baselines/china_e3_e7/adapter.py tables --aggregate path/to/aggregates --out path/to/paper_tables
```

表格生成还要求 `aggregates/independent_recalc_certificate.json` 为 `PASS_INDEPENDENT_RECALC`，且证书绑定当前 raw CSV 的 SHA-256 和合同 ID。没有正式结果时只生成状态与规格文件，不生成空白结果 PDF/PNG，也不写论文数字。

E4 和 E7 使用 2025 年 2 月完整 28 日面板；`2025-02-12` 只是共同解释日。日级回放用 `daily_replay`，动态阶段诊断用 `stage_diagnostic`，二者不能被统计器误当作独立正式运行行。

`run` 当前必然 fail-closed。未来正式 release 必须单独审查 MV-HGS-SP/完整非线性评价器的执行接线，并显式改变合同和审批记录；不得把旧 UK/ALNS runner 改名后直接复用。
