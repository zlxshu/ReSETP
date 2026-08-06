# MT1 多趟接口补齐与记账修复（2026-08-02）

## 终态

`HALT_E4_LOCKED_TERMINAL_KWH_TOTAL_MISMATCH`。权威证据目录为
`baselines/china_e3_e7/multitrip_interface_completion_20260802/`，完整根因、三份 E6 违反原数值、改法和验证见其 `report.md`。

## FACT

- E4 专用 `ContinuousSOCContract` 已接入 `prepare_multitrip_solution`，保留原 60%-20%-80%-次日60% 语义；90/90 份 `interface_directly_usable=true`。270/270 笔 `terminal_charges` 已写入 `depot_charge_ledger`，逐笔能量 binary64 与保存行一致。
- E6 的三份冲突根因是单路线静态检查不读取上趟余电和证书发车时刻。新完整检查先严格验证证书能量/曲线/时钟，再保留静态检查器的所有非跨趟约束。E6 900/900 通过；旧静态语义对三份仍分别产生 11/9/10 条违反，未删证据或放宽检查。
- 预先按 `record_id` 字典序取 E4 20 份、E6 20 份作单趟零搜索回归，每份目标值和 13 个关键分项全部 binary64 逐位一致。7 个相关测试文件共 52 项通过。
- `solver/src/setp_solver/cost.py`、`check.py`、`search/evaluation.py` 未修改；未运行搜索或正式实验。证据包锁定 Git 提交 `850cea5f3d3e11a21e073a7c1a45477a65a7a66f` 和全部涉及源码 SHA-256，`--check` 通过。

## HALT 原因

270 个保存 JSON 能量数字的无损十进制和为
`5869.852618210776059` kWh；它们与新账本各自的 binary64 合计均为
`5869.852618210776` kWh。任务锁定值 `5869.852618210777` 高 1 ULP
（`9.094947017729282e-13` kWh）。按用户规定，不得为过门修改账本或容差，故不得写
`MULTITRIP_INTERFACE_COMPLETE`。若用户后续纠正该锁定合计，应重新生成一个新日期目录，不覆盖本 HALT 证据。
