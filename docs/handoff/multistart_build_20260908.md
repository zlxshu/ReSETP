# 第 1 轮多起点 ＋ 代理锚点冻结：施工与验证（2026-09-08）

**任务来源**：用户 2026-09-08——"用什么组合什么比例算法随意，只要能产生最优解"。

**范围**：改 Python 外层，**没有动 C++ 内核**、没有动 4.3 动力配置的固定比例逻辑、
没有改论文、没有 git commit。前置诊断见
`docs/handoff/fleet_dispersion_diagnosis_20260908.md`（病灶在第 1 轮）与
`docs/handoff/fleet_dispersion_kernel_vs_python_20260908.md`（病灶在 Python 外层，
对症的是档 b 的前两条）。

**关于"谁跑的"**：仓库 `CLAUDE.md` 的角色铁律写着 Claude 不运行代码、不改代码，
由 Codex 执行。本轮的代码改动、单元测试与求解器运算都是 Claude 按当日派工指令直接做的，
**属于越过那条规矩**，与 2026-09-08 上午那 12 跑探针同一性质，在此明记。
产物落在新目录，没有覆盖任何既有实验包。

---

## 0. 一句话

第 1 轮从"一个起点一次抽签"改成"起跑 3 次、按内核自己的代理最优留下最好的那一次"，
并把内核 EV 代理的两个路线无关锚点从"每跑各估各的、每轮还要重估"改成
**全批共用的常数**。两件事各有开关，各自可以单独关掉；库内默认逐位复现改动前的行为，
正式命令行入口的默认改成了新行为。

---

## 1. 改了哪几个文件、每处为什么

改动共 4 个文件（3 改 1 新）。**没有碰 `third_party/setp_hgs_kernel/`（C++ 内核）**，
没有碰 4.3 动力配置的固定比例逻辑，没有碰论文，没有 git commit。
（本实验不存在"受保护文件"，见 2026-09-03 的记忆条目。）

| 文件 | 改后 SHA256 |
|---|---|
| `solver/src/setp_solver/algorithms/problem_hgs/runner.py` | `45dfb90d19bacc5ab5b605e892ab524aae67ffd566e75ffeac4d3884c0768cd4` |
| `solver/src/setp_solver/algorithms/problem_hgs/contracts.py` | `cddabae9e9d9c5754d725abff7b29178395fb3d638aa2ba68186f0dc7947dd6b` |
| `solver/scripts/run_problem_hgs_private_technical.py` | `c2bbcab090ea9b67e150cb9a0957905c8563700034c39bea11d3d4a390213f35` |
| `solver/tests/test_problem_hgs_round_one_starts.py`（新建） | `a51af9bfcf9221bc7f8e000a80665674d685a6284751e38bc19fcdc6b3e78b92` |

### 1.1 `runner.py`

| 行 | 改了什么 | 为什么 |
|---|---|---|
| 431–438 | 新增模块常量 `ROUND_ONE_STARTS = 1` | 库内默认＝改动前行为。注释里写清依据：同一张代理成本表下内核最好一跑与最差一跑差 36.9–60.3 元代理（前一份诊断 §2.4），一次运算的成败在第 1 轮就基本定了（第 1 轮精确最优与最终成本秩相关 0.748） |
| 644–646 | 函数新增三个关键字参数 `round_one_starts`、`frozen_reload_gap_seconds`、`frozen_first_trip_window_open_second` | 三个都默认"不生效"，调用方不明说就走老路 |
| 702–747 | 两段函数文档 | 说清多起点的选优判据、K 个起点**不是**互相独立的复制（`rng` / `local_search` / `penalty_manager` 是共享且带状态的），以及冻结治的是方差不是深度 |
| 811–815 | `round_one_starts < 1` 直接报错 | 与既有的 `stop_after_nonimproving_rounds`、`max_outer_rounds` 同一写法 |
| 860–870 | 冻结时 `reload_gap_seconds` 从函数入口就取常数 | 第 1 轮的引擎在入口脚本已按常数建好，这里让第 2 轮起的重建拿到同一个数 |
| 907–911 | 第 2 轮起的工厂调用补传 `first_trip_window_open_second` | **这条同时修了一个既有的漏**：`make_route_engine` 只记得构造时给过的 kwargs，而第 2 轮起的工厂调用从来没带过首班窗口开启时刻，于是该锚点在第 2 轮就悄悄退回契约的末班结束时刻（19:00）。**只在冻结时补传**，`population` 档下一个字不动 |
| 918–939 | 把 `init` 拆成"确定性的投影种子 `projected`"＋"每个起点各自的随机补员" | 种子投影是确定性的，每轮算一次就够；`kernel_seed_*_by_round` 的记账仍是每轮一条，与改动前对齐 |
| 941–982 | 第 1 轮循环 K 次，把 `(kernel_result, population, trace)` 作为一组存起来，按 `trace.best_cost` 取最小的那一组 | **三样必须一起选**：精确阶段读的是 `natives = [kernel_result.best, *population]`，只选 `kernel_result` 而 `population` 留在最后一个起点上，会让赢家的最优个体配上输家的末代种群，而且盘上看不出来 |
| 983–995 | 第 1 轮记 `round_one_starts` 与每个起点一条摘要 | 起点之间的代理值、圈数、墙钟、谁被选中，全部落盘，事后不必重推 |
| 996–999 | `improvement_events` / `round_gap` 只吃赢家的轨迹 | 否则落选起点的一段长等待会把 `round1_max_improvement_gap` 抬高，等于顺手把"确认轮耐心"这个旋钮也拧了——那正是 2026-09-08 上午探针单独测过、值 9.4–21.9 元的另一个旋钮，混进来就无从归因 |
| 1127 | 冻结时不再每轮重估预留 | 第 2 轮起换题的直接来源（125 个确认轮播种 5 091 个种子里 647 个被判不可行） |
| 1154–1163 | 把两个冻结值写进记账 | 事后可核 |

**总圈数怎么算**：`total_iterations` 与 `crossover_calls` 计**全部 K 个起点**（真花掉的时间），
`kernel_round_summaries[0]` 只报赢家。两个视角靠 `round_one_start_summaries` 对得上，
不是矛盾。

### 1.2 `contracts.py`

201–215 行加四个记账字段（`round_one_starts`、`round_one_start_summaries`、
`frozen_reload_gap_seconds`、`frozen_first_trip_window_open_second`），
580–610 行加对应的序列化。都默认 `None`／空列表，读作"这条路径没有记录"，
与该文件已有的约定一致。

### 1.3 `run_problem_hgs_private_technical.py`

| 行 | 改了什么 |
|---|---|
| 124–158 | 两个常数 `PROXY_REFERENCE_RELOAD_GAP_SECONDS = 1757.5422714695778`、`PROXY_REFERENCE_FIRST_TRIP_WINDOW_OPEN_SECOND = 56808.17676999999`，以及正式入口的两个默认值常量。注释里写全推导与"不缩小可行域"的证明 |
| 1793–1841 | 两个新开关 `--round-one-starts`（默认 3）与 `--proxy-estimate-source {population,reference}`（默认 reference） |
| 2683–2695 | `reference` 时预留取常数，不看本跑初始种群 |
| 2734–2745 | `reference` 时首班窗口开启时刻取常数 |
| 2766–2782 | 把来源与常数写进 `route_engine_wiring` |
| 2245–2259 | 拦下 `--reload-gap-quantile 1.0` ＋ `--proxy-estimate-source reference` 这对互斥承诺（前者的对外承诺是"预留＝见证解最大趟、逐位复现 2026-09-05 前"，后者是"预留＝全批共用常数"），静默让其中一句赢会让谁都读不出这一跑到底预留了多少 |
| 2962–2975 | 把三个参数传给轮循环；`population` 档下两个冻结值都传 `None` |

---

## 2. "参照解"这一条与派工letter不同，必须先说清

派工写的是"从**所有运算共享的参照解**确定两个代理参数"。**这一条按字面做不了，
原因不是代码结构，是那个参照解本身没有这两个统计量。**

2026-09-08 离线核验（只读，没有开搜索，脚本在 scratchpad，不落仓库）：
本入口的参照解（`_build_context` 返回的见证解）是**纯燃油的**——

```
duties: 8 辆燃油车（CV_...×8），每辆 1–3 趟
reference inter-trip sessions (n=0): []
reference reload p75 = None
reference first-trip-window open = None
reference EV trips n=0
```

两个估计器在这样的解上都返回 `None`：`population_inter_trip_reload_seconds` 找不到
`trip_index >= 2` 的充电会话，`population_first_trip_window_open_second` 找不到电动行程。
落到 `None` 就退回两个**已知更差**的旧值：预留退回见证解最大趟的 2031.67 s 过度预留
（2026-09-05 已判定为病灶之一），窗口退回契约末班结束 19:00（实测代理 1.243
对精确 0.873 元/kWh）。

所以 `reference` 落在**一个全批共用的常数**上。这与
`fleet_dispersion_kernel_vs_python_20260908.md` 档 b2 的原话
（"取一个全批共用的常数"）一致，也比派工给的次选方案（"第一轮估一次后冻结，
跨运算仍有差异"）更彻底——次选方案去不掉跑间方差，而跑间方差正是要治的病。
**开关名仍叫 `reference`，语义是"全批共用的参照取值"，不是"参照解自己的统计量"。**
这条差异写进了源码注释、命令行帮助文本，并有一条单元测试
（`test_the_reference_solution_carries_neither_statistic`）钉着：
哪天参照解变成含电动车的解，那条测试会红，届时"从参照解估"才重新成为一个选项。

### 2.1 常数怎么定的，为什么不会缩小可行域

规则**在开跑前定死**：取现行估计器在四臂各 10 跑（共 40 跑）上实测值的**中位数**。

| 参数 | 40 跑实测范围 | 中位数（即常数） |
|---|---|---|
| 趟间预留 `reload_gap_seconds` | 1348.00 – 2117.39 s | **1757.5422714695778 s** |
| 首班窗口开启 `first_trip_window_open_second` | 55618.62 – 58731.65 s | **56808.17676999999 s** |

产物出处：`solver/reports/grid2x2_v3_20260906/beijing/P=0.2/{MT-HGS,MTC-HGS}` 与
`solver/reports/charging_arrangements_20260906/{cost_min,carbon_min}` 各 10 跑的
`metadata.json`，字段 `route_engine_wiring.reload_gap_round1.seconds` 与
`route_engine_wiring.first_trip_window_open_round1.second`。

**"预留取大了会把可行解判成不可行"这条记忆的守门检查**（2026-09-05 实测：2614.1 s
把 33 个精确可行解里的 25 个判为内核不可行）：

四臂各自 10 次里**成本最优**的那一跑，当时实际用的预留分别是
**1803.67 / 1961.77 / 1820.27 / 2044.94 s**，四个都**大于**本常数 1757.54 s。
预留只往时长矩阵上加、不进弧成本，所以**在更大预留下内核找得到的解，在更小的预留下
必然仍旧可行**。这是单调性论证，不需要再跑一次投影验证。

另外，预留大小与最终成本在盘上**没有方向**：40 跑按中位数切两半，
低半均值 2651.29 元、高半均值 2651.48 元；组内 Spearman(预留, 成本) 为
+0.345 / +0.030 / +0.297 / +0.079。所以这个常数不是在挑一个"对结果有利"的值。

### 2.2 窗口常数会改变两个臂的代理电价，这一点要写明

`first_trip_window_open_second` 通过"首班充电窗口从哪一行日历开始"决定早班代理电价。
40 跑实测的映射（每臂自己的择时策略挑槽，所以逐臂不同）：

- 只看电价、两者：窗口在 55618–58731 s 全区间内**不改变**选中槽（分别恒为 0.68639、0.68027 元/kWh）；
- 即充、只看碳：以 57600 s 为界翻转——低于 57600 选 15:30 那槽（0.87294），
  高于选 16:00 那槽（0.89018）。

常数 56808.18 s 低于 57600 s，所以即充与只看碳两臂在 `reference` 下拿到 **0.87294**。
在现有 10 跑里，即充有 2/10、只看碳有 6/10 落在这一侧。**即充臂因此拿到的是它历史上
的少数侧**——但这是"中位数"这条事先定死的规则的结果，不是挑出来的：诊断 §2.2 已证明
即充臂 0.89018 那组里同时装着该臂最好的一跑（代理 2660.00）和最差的一跑（2713.17），
盘上没有证据说哪个价格更好。代理电价只是搜索的指路牌，**精确结算一分钱不受影响**。

---

## 3. 默认行为逐位不变：实测哈希

内核由 `SystemRandom` 播种（`kernel_proposals.py:295-297`），两次跑本来不可能自然重放，
所以"逐位不变"是这样实测的：把 `kernel_proposals.SystemRandom` 换成一个固定返回同一个
种子的桩，让整条随机流可复现，然后把**改动前的 `runner.py` 原样复制成一个临时模块**，
同一个夹具（真算例、`stagnation_patience=300`、`confirming_round`、
`confirming_patience_floor=50`）在改动前后各跑一遍，比对一个把
最优解指纹、总成本、总圈数、轮数、逐轮耐心、逐轮内核摘要、全部改善事件、
逐轮预留、种子可行性计数、逐轮是否改善、交叉调用数、完整评价数、增量评价数
全部串起来的 JSON 的 SHA256。

改动后跑的是**库内默认**（`round_one_starts=1`、两个冻结值均为 `None`）。

| 种子 | 改动前 | 改动后 |
|---|---|---|
| 20260908 | `cb8d82f1e1ff5c7edce3d772e36fa43dc8e435d6ddc1d4f6c5aaaf715e1a847d` | `cb8d82f1e1ff5c7edce3d772e36fa43dc8e435d6ddc1d4f6c5aaaf715e1a847d` |
| 7 | `13481638d4ef2d805a55ddc4e01ad57ff65b6de4a9a50b1355f5a1a7a67fc63f` | `13481638d4ef2d805a55ddc4e01ad57ff65b6de4a9a50b1355f5a1a7a67fc63f` |

两个种子各跑两遍，四组八次全部对上（同一档重复跑也逐位相同，说明这个夹具本身在固定
种子下是确定性的，比对才有意义）。临时模块已删除，不留在仓库里。

**要说清的一条**：这证明的是**库内默认**逐位不变。**正式命令行入口的默认行为按派工要求
改了**——`--round-one-starts` 默认 3、`--proxy-estimate-source` 默认 reference。
也就是说，此后任何一条不带这两个开关的命令，跑出来的都不再是 2026-09-08 之前的东西。
要复现旧行为，命令里要显式写 `--round-one-starts 1 --proxy-estimate-source population`。
`solver/reports/rerun_split_20260908/joblist.txt` 那 201 条、以及别处已落盘的批命令，
若原样重跑都会走新默认，这一点必须在重跑前知道。

---

## 4. 单元测试

新文件 `solver/tests/test_problem_hgs_round_one_starts.py`，8 条：

1. `test_library_default_is_one_start`——库内默认必须是 1。
2. `test_round_one_starts_must_be_at_least_one`（0 与 −1 两参数）——校验报错。
3. `test_one_start_records_exactly_one_start_and_that_start_is_the_round`——K=1 时
   起点摘要只有一条，且圈数／改善数／代理最优与第 1 轮逐位相同，总圈数仍等于各轮之和，
   两个冻结字段为 `None`。
4. `test_three_starts_keep_the_lowest_kernel_proxy_best`——K=3 时三条摘要、恰好一个被选中、
   选中者的代理最优 ≤ 其余起点；第 1 轮报出去的就是选中的那个起点；
   总圈数＝三个起点＋后续各轮（即落选起点的圈数确实计进去了）；
   `round1_max_improvement_gap` 只由赢家的改善轨迹算出。
5. `test_frozen_reload_gap_is_the_same_number_in_every_round`——冻结后
   `reload_gap_seconds_by_round` 每一轮逐位等于传进去的常数。
6. `test_the_reference_solution_carries_neither_statistic`——把 §2 那次离线核验钉进仓库。
7. `test_entry_defaults_are_three_starts_and_the_shared_constants`——正式入口默认档，
   以及两个常数确实落在 40 跑实测窗口内。

全量：`pytest solver/tests -q` → **412 passed, 12 warnings, 23 subtests passed in 416.96s**
（需先设 `PYTHONPATH=$PWD:$PWD/solver/src:$PWD/third_party/setp_hgs_kernel:$PWD/models/src`，
仓库没有 conftest.py，这是既有前提）。

---

## 5. 验证：四臂各 3 次（12 跑）

命令**逐字**取自 `solver/reports/rerun_split_20260908/joblist.txt` 的四臂 run_01 行
（第 1／147／157／41 行），只改输出目录并追加
`--round-one-starts 3 --proxy-estimate-source reference`。
清单 `joblist.txt`、执行器 `run_one.sh`、启动器 `launch_all.sh`、日志 `launcher.log`
都在 `solver/reports/multistart_probe_20260908/`。三并行。

（结果见本文件 §6，以及 `solver/reports/multistart_probe_20260908/README.md`。）

---
