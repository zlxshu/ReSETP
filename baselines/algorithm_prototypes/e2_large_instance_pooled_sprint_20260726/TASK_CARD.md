# E2-LARGE-INSTANCE-POOLED-SPRINT-001

目标：在 PR16A、PR16B、PR20A、PR24A 上复用 D7 的独立全长 HGS → 跨种子路线汇池 → 精确集合划分机制，检查大题带是否产生汇池增益或经独立复算的新 BKS。

输入：`boundary_probe_20260726/d7_long_runs_pooled.py`、V13 正规化实例与当前 BKS 路线证书。

允许改动：本隔离目录内的运行常量、算例清单、输出路径、非语义测量/审计与五记录面；任务结束后只向 `HANDOFF.md` 和相关 memory 追加事实。

禁止改动：`solver/src/setp_solver/`、封存 P1/P3/P4、China81、主 TeX、D7 参考实现本体、搜索/采集/汇池/集合划分机制。

停止规则：仅用迭代条件；集合划分固定 300 秒且不重试；最低 20,000 代仍装不下时按 PR16A→PR16B→PR20A→PR24A 减题；资源探针推算六进程峰值超过 4096 MB 时正式运行降为 3 workers；保护文件漂移或异常时保留现场并停止。

产物：`metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json`、`report.md`；中间路线池 JSON、监控现场、标定和资源探针证据保留但不纳入五件套哈希之外的论文证据范围。
