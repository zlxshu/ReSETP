# E3 结构性对照：技术 HALT 封存

状态：`HALT_TECHNICAL_ERROR_CROSS_SITE_CANDIDATE_UNDER_HARD_LOCK`。

## 结论

旧 PGID 7965 在接手时已经不存在，随后再次确认无对应进程组；旧输入目录的 106 个权威终态、13 个严格 `INFEASIBLE_INPUT` 和 56/56 First-Fit 等价证据均未删除或覆盖。旧设计剩余 8 个活动单元和 21 个排队单元共 29 个，已在本目录登记为 `NOT_BUILT_SUPERSEDED_DESIGN`，明确不是不可行、也不是失败。

China81 实例没有字面名为 `registered_depot` 的列，但有现成的客户 `city` 行政归属；装载器把客户城市确定性映射到同城唯一车场，形成 `customer_home_depot`。因此没有为 IND 新造参数。两个预定算例中，这个行政映射与有向道路最近车场完全重合：50c 为 0/50，100c 为 0/100。IND 和 ZONE 的责任映射与加锁问题因此相同；这个输入身份事实不依赖正式搜索结果。

IND、ZONE、JOINT 各 2 份输入均成功构造，C++ 冻结 First-Fit 与 Python `_pack_depot` 逐组一致，完整初解复算违规 0，构造无组合爆炸。1500-cap 的 JOINT 主算例 seed-1 收敛探针实际消费 331 个完整候选后自然耗尽，技术错误 0；按预注册规则向上取整留余量，将正式共同预算上限冻结为 400。

## 正式批停止原因

正式矩阵原定 2 算例 × 3 臂 × 10 种子，共 60 单元，最多 2 workers。批次运行到 26 个单元形成完整 trace 时，18 个达到 PASS，8 个处于“trace 已持久化、最终验证前 HALT”。这 8 个全部是 50c 的硬锁 IND/ZONE 单元（种子 3、5、6、7），累计出现 14 个技术错误候选；异常原文为：

```text
hard home-depot control candidate contains cross-site service
```

这些候选不是 `null objective` 的合法容量/时间窗不可行，也不在白名单内。它们表示硬车场责任控制下仍进入了跨场候选，是搜索/控制链的真技术错误。按合同“合法不可行继续，真技术错误 HALT”，监控进程组已先暂停、保存现场，再停止；其余 34 个单元未启动或未形成权威 trace。未删除异常候选，未将其改写成 `INFEASIBLE_INPUT`，未修算法后重跑。

## 结果边界

由于 60 单元全分母未完成，三臂期刊式 Best/Avg/Gap%、车辆数、时间和实际评价数主表没有生成；IND→ZONE、ZONE→JOINT、IND→JOINT 三个正式效应均为 `NOT_AGGREGATED_DUE_TO_TECHNICAL_HALT`。18 个 PASS 解只作为故障前现场保存，不用于论文效应、显著性或方向判断。旧 L-main 的 16.55%/24.72% 没有进入本次判决，也没有迁移为论文证据。

`raw_runs.csv` 保存 26 个实际运行单元的状态：18 个 PASS 行带完整目标/解证书，8 个 HALT 行保留空目标并链接相应 trace。独立 HALT checker 在单独进程中重新验证 18/18 PASS 解的完整目标、客户覆盖、违规和解哈希，并复核 8/8 HALT trace 中的 14 个技术错误字符串及计数。四个受保护源文件哈希未漂移。

## IND 调查的备选边界

本任务没有采用合成 IND。若未来放弃现有行政城市归属，客观备选包括按距离次近车场（依据明确但人为制造错配强度）、按更细行政区划映射（需新增可靠边界与车场对应来源）、按容量均分（可平衡资源但不是历史/行政登记）。这属于新的科学定义，需要用户另行裁决，不能作为本次技术 HALT 的自动修复。

## 文件与完成信号

四件套 `metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json` 与本报告同目录。外置卷产生的 AppleDouble 旁车在封存前按精确 `._*` 范围清理，记录为 `HASH_CONTAMINATED_APPLEDOUBLE_CLEANED_BEFORE_SEAL`；真实证据文件不变。哈希枚举排除 `._*`、`__pycache__`、`.pytest_cache`、临时文件和目录外监控运行态。`done.json` 最后写入，状态为 `HALT_TECHNICAL_ERROR_CROSS_SITE_CANDIDATE_UNDER_HARD_LOCK`，不是 `COMPLETE`。
