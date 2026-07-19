# 有界双视图档案旧三题 P1 执行合同

状态：`FROZEN_BEFORE_FIRST_SCORE`

本文件只加固 `bounded_dual_view_archive_contract_20260719.md` 已批准的旧三题一次性小门，不改变算法、预算、候选容量、排序规则或通过阈值。

## 1. 唯一允许的运行

只允许：

- `L-main-threeshift-20c-01`
- `L-main-threeshift-25c-01`
- `L-main-threeshift-50c-01`
- 每题 seed 1
- 每臂完整搜索候选预算 B=100
- 控制臂关闭档案，候选臂开启档案

输出目录固定为：

`baselines/algorithm_prototypes/unified_mechanism_alns_20260719/bounded_dual_view_archive_p1_training_gate`

运行器拒绝其他输出目录。正式评分前必须先创建不可覆盖的 `attempt_started.json`；只要该目录存在，运行器就拒绝第二次启动。中止或崩溃也必须留下尝试现场，不能换目录重跑。

隐藏工作进程还必须同时看到父进程临时令牌和上述正式尝试文件，不能脱离唯一父进程入口被误调用。

失败现场只能由本进程刚创建的尝试目录写入。已有 PASS、STOP 或失败现场被后续调用拒绝时，后续进程只能返回错误，绝不能改名、覆盖或重新封存旧现场。

## 2. 输入和行为门冻结

三题必须逐文件匹配此前已经烧过的现场：

`baselines/algorithm_prototypes/unified_mechanism_alns_20260719/contextual_expert_p1_training_gate/metadata.json`

该历史现场记录的 Git 头为 `0be072577935797a5f51c992c8aba415ffad49a4`。当前三题的 27 个文件必须与其中 `input_hashes` 的库存和 SHA-256 完全一致；否则在任何评分前停止。

正式行为门必须同时满足：

- `decision.json` 为 PASS 且只放行旧三题；
- 正式展品清单全部匹配；
- 17 个源文件、40 个输入文件和 3 个保护文件与行为门 metadata 的哈希全部匹配；
- 行为门源码提交是当前 HEAD 的祖先；
- 正式证据已跟踪且无工作树改动；
- AppleDouble 封存为 `CLEANED_AND_READY_TO_REHASH`，当前零 `._*`。

任何一项不满足都必须在启动工作进程前拒绝评分。

## 3. 公平计时和账本

控制与候选逐题使用同一完整起点、同一 B、同一主搜索、同一普通终局处理和同一独立复算器。必须核对原始搜索精确内容、路线骨架、历史、算子及两个随机数状态。

墙钟以父进程包住整个工作进程的时间为准，包含 Python 启动、导入、求解、复算、序列化和退出。求解器自报时间与工作进程包住求解调用的时间只作为交叉核验，二者误差不得超过 `max(0.05 秒, 工作进程时间的 5%)`；父进程墙钟不得短于工作进程求解时间。

候选增加的便宜预估、额外终局、复算和序列化成本全部由候选承担，不得从墙钟中扣除。

## 4. 冻结判定

以下条件全部成立才 PASS：

- 3/3 最终不倒退；
- 至少 2/3 严格胜；
- 三题改善率中位数至少 1%；
- 最大倒退不超过 1%；
- 档案在至少 2/3 题严格贡献；
- 候选/控制父进程墙钟比中位数不超过 1.25；
- 候选/控制父进程墙钟比最大不超过 1.50；
- 所有候选预算、复算、局部工作、可行性、完整内容见证、父进程复核和计时账闭合。

阈值失败但执行证据完整时，判 `STOP` 并返回码 1；账本、哈希、复算或执行合同失败时返回码 2；只有全部通过才返回码 0。

STOP 后不得调整 12 个预筛候选、3 个终局候选、排序规则、预算、实例、种子或计时口径进行救援。下一候选只能转向合同中已登记的跨路线机制算子。

## 5. 封存

正式目录必须包含并验签：

- `attempt_started.json`
- `metadata.json`
- `raw_runs.csv`
- `comparisons.json`
- `decision.json`
- `archive_candidates.json`
- `solution_witnesses.json`
- `report.md`
- `run_finished.json`
- `monitor_completion.json`（只在所有正式哈希复核完成后写入）
- `appledouble_seal.json`
- `artifact_hashes.json`

外置盘写盘若生成 AppleDouble，必须先登记瞬时 `HASH_CONTAMINATED_APPLEDOUBLE`，再只清理本次唯一正式目录，确认零边车后重算并再次逐件核验哈希。不得重写原始 CSV。

PASS 只允许锁定候选并进入一次新鲜 D3 最小门，以完成当前目标模式中的低成本新鲜验证；STOP 不允许进入 D3。无论 PASS 或 STOP，都不授权 HGS/纯 ALNS 正式对比、阶段二或全量实验。
