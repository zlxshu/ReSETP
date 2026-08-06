---
name: formal-ablation-200c-20260803
description: "XA2 200客户三臂组件消融重跑、判别力自检与停止结论"
metadata:
  node_type: memory
  type: experiment_result
  effective_date: 2026-08-03
  status: active
---
> ⚠️ **2026-08-03 结论待重估**：本文件的实验走 China81 MV-HGS-SP 求解路径，
> 该路径已确诊缺陷——PyVRP 代理问题不施加每车场实体车数上限，HGS 候选补全时被全数拒绝
> （异常在 `epochal_hgs.py:532-543` 静默吞掉），最终解恒为共同初始解，
> **随机种子与迭代预算对结果均无影响**。凡本文件中涉及算法性能、判别力、
> 臂间差异、"最优解"的表述一律以
> [solver_completion_reject_root_cause_20260803.md](solver_completion_reject_root_cause_20260803.md)
> 为准；受影响范围的逐包判定见 `docs/handoff/asset_audit_20260803/`。修复后须重跑。

# XA2：200 客户组件消融重跑

状态：`DECISION/FACT`，终态 `XA2_ABLATION_COMPLETE`。

权威证据目录：`baselines/china_e3_e7/formal_ablation_200c_20260803/`。本文件只作索引与结论正文；
逐次数字以该目录的 `raw_runs.csv`、`decision.json`、`metadata.json`、`artifact_hashes.json`、
`report.md`、`discriminability_check.json` 和 `units/` 完整解为准。

## 1. 跑前固定设计

唯一算例在任何搜索前固定为 `cn-prd-200c-01-V2-LOCATIONS`。选择理由不是先跑多题再挑：它与
上一轮 100 客户正式实验同属 PRD、同为规范 `-01` 重复项，只把规模提高到 China81 当前最大
200 客户；`cn-prd-200c-02`、`cn-prd-200c-03` 和其他算例均未运行。fleet authority v3 对该题
0/25/50/75/100% 五档已有零搜索 `CERTIFIED` 见证。共同起点经完整 completion、多趟排班和
独立评分后为 35 条路线、22 辆实体车、0 违约，预检目标值 7820.1814723598745 元；四车场总上限
为 32 辆。

三臂是 MV-HGS-SP 完整臂、HGS-M-SP（删除多视角）和 MV-HGS（删除限时 MIP 路线池重组）。
种子固定为 2026080201--2026080210。每次最多 2000 次 HGS 迭代，或各活动种群连续 150 次无改善；
完整搜索评价上限同为 100。三臂使用同一共同起点、种子集、完整评价器和独立验解器。严格多趟
开启；固定成本按去重实体车数计费，`c_fix=170` 元；车场充电并发不设上限；公共站并发仍取算例
给定值；车队上限使用 fleet authority v3。

跑前预注册的否定条件是：HGS-M-SP 减完整臂的配对平均成本差不为正，则不支持多视角有正贡献；
MV-HGS 减完整臂的配对平均成本差不为正，则不支持限时 MIP 路线池重组有正贡献；任一组件不获
支持，则不支持“每个被检验组件都有贡献”的总主张。若 30 个目标值全同，直接报告最大规模无可测
差异，不换算例、不换种子、不加预算。

## 2. 结果

30/30 个单元全部 `PASS_FEASIBLE`，技术错误、预算超限、墙钟安全停止和缺解均为 0。三臂所有
目标值均为 7820.1814723598745 元；每臂 Best=Avg=7820.1814723598745，稳定性 Gap=0，可行数
10/10。HGS-M-SP 对完整臂、MV-HGS 对完整臂、HGS-M-SP 对 MV-HGS 三组配对均为
0 胜/10 平/0 负，配对成本差 0 元、百分比 0%。

判别力自检回答为 `NO`。科学终态为 `NO_MEASURABLE_DIFFERENCE_AT_CHINA81_MAX_SCALE`：
**在 China81 现有最大规模下，三部件不产生可测差异。** 多视角贡献、限时 MIP 路线池重组贡献
和总组件贡献三项预注册主张均不获支持。本任务到此停止，不再换题、换种子或加预算。

## 3. 全平支撑量

|算法臂|迭代范围（均值）|完整评价范围（均值）|CPU min范围（均值）|可行|
|---|---:|---:|---:|---:|
|MV-HGS-SP|1569--2000（1739.1）|94--100（96.5）|1.2689--1.5703（1.4330）|10/10|
|HGS-M-SP（去多视角）|441--1203（747.4）|37--68（49.6）|1.2268--1.9026（1.4370）|10/10|
|MV-HGS（去限时MIP路线池）|1569--2000（1739.1）|94--100（96.5）|3.6220--4.4760（4.2351）|10/10|

三臂迭代区间不重叠，逐种子三臂迭代数完全相同为 0/10，逐种子迭代跨度为 630--1200；因此不能
把全平解释成三臂在相同迭代附近偶然同时停止。另一方面，逐种子三臂完整解结构按规范 JSON 逐位
相同为 10/10，说明它们尽管搜索过程和计算投入不同，最终都返回同一个共同初始解结构。

## 4. 完整性与边界

metadata 在搜索前锁定 123 个源码/输入 SHA-256、git 提交 `850cea5f3d3e11a21e073a7c1a45477a65a7a66f`、
脏工作树清单、多趟开关、实体车计费、车场并发、authority 版本、唯一算例与选择理由。30 份完整解
均保存并登记字节 SHA 与结构 SHA，独立复算 30/30 通过；99 个 artifact 哈希复算通过。
`artifact_hashes.json` 排除了 `._*`、`__pycache__`、`.pytest_cache` 与监控目录。

上一轮 `baselines/china_e3_e7/formal_algorithm_20260802/` 的跑前/跑后树清单哈希一致，未删除、移动
或覆盖。`docs/paper_submission_final/paper_main.tex`、`solver/src/setp_solver/check.py`、
`solver/src/setp_solver/search/evaluation.py` 的跑前/跑后哈希一致。

监控器因受限 macOS 会话不能读取进程表，在 0 行时误报 `PROCESS_EXITED_WITHOUT_COMPLETION`；现场
保留在输出目录的 `.experiment-monitor/`。正式 runner 实际继续写盘，首个结果出现后没有重启或复制
任何任务，最终 30/30 由同一任务清单闭合。这个监控误报是执行环境事实，不改变实验合同或结果。
