# E5-NONLINEAR-CHARGING-01 盲 pilot 结构性 HALT（2026-07-29）

权威证据目录为 `baselines/china_e3_e7/e5_nonlinear_20260729/`。原子终态是
`done.json.status=HALT`，HALT 码为
`HALT_PILOT_STARVATION_SCHEDULE_NOT_CONSTRUCTIBLE`。这不是 E5 的正向、
接近零、负向或混合科学结果。

批准边界保持不变：主展品 `cn-prd-50c-01-V2-LOCATIONS` 使用种子 1--10，
中规模验证 `cn-prd-100c-02-V2-LOCATIONS` 使用种子 1--5；
`cn-prd-150c-01-V2-LOCATIONS` 因 0/40 个封存会话进入 SOC>90% 折半段、
最高 SOC 65.05% 而排除。两臂仍为 `L100_control` 与 `NL90_mild`，没有更改
算例、种子、物理曲线、HGS 迭代、MIP 限时、分母或统计端点。

结果盲 pilot 完成五个完整候选评价档。32 档两臂各有 12/15 个饥饿单元，
56 档各 11/15，80 档各 12/15，160 档各 13/15，240 档各 13/15；全部超过
“`L/S>0.5` 单元占比不得超过 20%”的上限。五档共 150 个臂单元，均完整落入
`raw_runs.csv`。pilot 任务文件与档位判决只含 L、S、L/S、无目标值的改进布尔
序列、资源信息和盲态声明，不含任何目标值或臂间成本差。

HALT 的结构性证据是：160 档中，50c-01 的种子 1--8、10 对两臂都在
`L=159,S=160` 才最后严格改进；240 档中同一组种子对两臂都在
`L=239,S=240` 才改进。当前 `route_pool_sp.py` 将最终路线池重组候选固定放在
倒数第二次完整评价，将最终独立证书固定放在最后一次；向上扩档只增加此前三个
HGS 视角的档案候选。对最终重组产生严格改善的单元，扩到 320、400 或更高仍会
保持 `L=S-1`，不能提供改进后的剩余预算。因此 240 完成后，在 320 任何单元
落盘前停止；继续需要用户批准重组后确定性完整候选评价调度，或明确批准另一饥饿
定义。任何重排、追加搜索算子或改口径都属于方法变更，执行代理不得自行实施。

正式预算未冻结，`execution_lock.json` 不存在，正式方案与共同非线性证书均为 0。
共同非线性可行率、线性计划假可行数与原因、共同可行单元成本效应、逐会话 SOC
与时长差统一记为 `NOT_RUN_UPSTREAM_PILOT_STARVATION_GATE_HALT`。不得引用 pilot
收敛形状推断任何臂间科学方向。

任务目录已形成 `metadata.json`、`raw_runs.csv`、`decision.json`、
`artifact_hashes.json`、`report.md`、`halt_certificate.json` 与 HALT
`done.json`。169 个非监控、非 AppleDouble 产物哈希复核通过；`cost.py`、
`check.py`、`search/evaluation.py` 的关闭哈希与跑前锁一致。本任务使用独立
`monitor.json` 且 `ai.enabled=false`，仅监控本 E5 目录；单产物看门狗在
`report.md` 首次出现后打印 `READY` 并退出。外置盘生成的精确 `._*`
AppleDouble 旁文件已清除且从未进入清单。
