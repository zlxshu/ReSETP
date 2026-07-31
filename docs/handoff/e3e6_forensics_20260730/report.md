# E3/E6 故障取证、现场清理与只读评估

日期：2026-07-30（Asia/Singapore）  
分支：`codex/reporting-pipeline`  
范围：故障定位、孤儿进程清理、只读改动面评估、E4 封存数据核对、历史 E3/E6 证据核对

## 结论摘要

- **FACT：** 2026-07-29 的三次 `preregister` 并不是自行“零输出立即退出”。v2、v3、v4 都在 CPU 活跃、进程仍存活时留下了 `manual_safe_stop` 现场，随后 monitor 以 `SIGTERM` 向整个进程组执行人工安全停止；`PROCESS_EXITED_WITHOUT_COMPLETION` 是停止后的状态分类，不是根因。
- **FACT：** 历史退出的直接调用链是 monitor 的 `stop` 子命令 → `command_control(..., SIGTERM, ...)` → `group_signal(...)` → `os.killpg(pgid, SIGTERM)`；执行点在 monitor 源码第 514、457、273 行。目标 runner 没有抛出异常，因此不存在可回收的 Python 错误堆栈或 `errno`。
- **FACT：** 三次运行尚处串行预注册输入构造；进程池只在后续 `pilot` 和 `formal` 阶段创建。信号量/进程池创建失败不能解释这三次 `preregister` 被停止。
- **FACT：** 对当前下一单元的隔离只读探针表明，耗时热点在 Z3 的 `solver.check(*assumptions)`，当前源码位置为 `run_e3e6_formal.py:2029`；探针持续 CPU 满载、内存增长而未自行退出，最终由本次诊断显式停止。
- **FACT：** 孤儿 `resource_tracker` 已安全恢复运行并通过管道 EOF 自行退出；它报告并清理 5 个泄漏的 POSIX 命名信号量。清理后五个名称逐一 `sem_open` 均返回 `errno=2 (ENOENT)`，SysV 信号量集清理前后均为 0。
- **FACT：** E4 封存 `raw_runs.csv` 有直接的完整模型成本字段。按封存全分母 11,340 行分别求和，CARBON 相对 ASAP 的系统总成本增加 **1.8453747639%**，方向为上升。
- **INFERENCE：** 若后续获批恢复 E3/E6，最稳妥的工程路径是新建较薄的编排入口、复用已审计输入与不变的搜索原语，而不是继续把恢复逻辑叠加到当前 3,769 行混合 runner；这不是重写算法。

## 1. 取得可诊断启动证据并定位真实死因

### 1.1 三次旧运行的直接现场

|运行|启动时间（+08）|人工停止现场|停止前状态|紧随其后的现场|
|---|---|---|---|---|
|v2|2026-07-29 22:38:56|`scenes/20260729-224153-manual_safe_stop/status.json`|PID/PGID 44487，`alive=true`，CPU 90.5%，RSS 33,600 KB，已运行 02:48|`20260729-224159-anomaly`，`alive=false`|
|v3|2026-07-29 23:07:34|`scenes/20260729-231240-manual_safe_stop/status.json`|PID/PGID 50032，`alive=true`，CPU 97.9%，RSS 634,784 KB，已运行 05:06|`20260729-231255-anomaly`，`alive=false`|
|v4|2026-07-29 23:18:15|`scenes/20260729-232503-manual_safe_stop/status.json`|PID/PGID 52748，`alive=true`，CPU 97.8%，RSS 163,456 KB，已运行 06:36|`20260729-232507-anomaly`，`alive=false`|

- **FACT：** 三份 `manual_safe_stop` 现场都显示 runner 尚存活且 CPU 活跃；因此“进程先自行退出、monitor 后发现”与现场顺序不符。
- **FACT：** monitor 的 `experiment_monitor.py:449-457` 在 `stop --confirm-safe-stop` 时先保存 `MANUAL_SAFE_STOP` 现场，再发信号；`experiment_monitor.py:514` 把 `stop` 映射为 `SIGTERM`，`experiment_monitor.py:272-274` 对有 PGID 的任务调用 `os.killpg(pgid, sig)`。
- **FACT：** 真实退出调用是：

  ```text
  experiment_monitor.py:514
    command_control(args, signal.SIGTERM, None)
  experiment_monitor.py:457
    group_signal(runtime.get("pgid"), int(runtime["pid"]), sig)
  experiment_monitor.py:273
    os.killpg(pgid, signal.SIGTERM)
  ```

- **FACT：** 这是外部信号终止，不是 runner 在某一 Python 行发起的退出系统调用。历史现场没有保存 SIGTERM 到达瞬间的程序计数器，所以不能诚实地给出“历史 runner 正在执行的精确源码行”；可精确给出的退出行是上面的 monitor 第 273 行。
- **FACT：** 没有 Python 异常、OOM kill、进程池创建异常或信号量异常的历史堆栈。原因不是“日志漏记了异常”，而是当时没有异常路径：目标收到默认处理的 `SIGTERM` 后终止。

### 1.2 为什么 `experiment.stdout.log` 是 0 字节

- **FACT：** monitor 在 `experiment_monitor.py:420-421` 以无缓冲二进制追加方式打开 `experiment.stdout.log`，并把 runner 的 stdout 和 stderr 都指向该文件。因此若 runner 有 Python traceback，stderr 本应进入同一日志。
- **FACT：** 三次命令都没有 `python -u`，但这不是 0 字节的主要原因。`run_e3e6_formal.py:3753-3764` 只在 `build_preregistration()` 完整返回后才执行一次最终 `print(json.dumps(...))`；预注册单元循环 `run_e3e6_formal.py:2498-2501` 本身不逐单元向 stdout/stderr 打印。
- **FACT：** `run.log` 的单条 `REUSED_COMPLETED_D3_AFTER_INPUT_BUILDER_ONLY_FIX` 来自 `run_e3e6_formal.py:2479-2482`，随后进入长时间输入构造。runner 在函数返回前收到 SIGTERM，最终 JSON 从未打印，所以 stdout/stderr 合并文件保持 0 字节。
- **INFERENCE：** 即使旧命令加上 `-u`，在代码不增加阶段性诊断输出的前提下，人工停止前仍可能是 0 字节；`-u` 只能消除缓冲，不能产生原本不存在的日志事件。

### 1.3 当前隔离诊断：耗时点、信号量与内存

本次诊断在当前 unrestricted/非沙箱执行环境中进行，没有启动正式效果搜索，也没有写入旧正式结果目录。只执行了两个最小探针。

#### A. 同 Python 环境的最小进程池探针

- **FACT：** 使用项目 `pyvrp-hgs-0.12.2` Python、`python -u`、`spawn` 上下文和 `ProcessPoolExecutor(max_workers=2)` 创建两个简单任务，输出依次为 `BEFORE_EXECUTOR`、`AFTER_EXECUTOR`、`[4, 9]`、`AFTER_SHUTDOWN`，退出码 0，墙钟约 0.14 秒，峰值 RSS 约 16.6 MB。
- **FACT：** 探针时 `os.sysconf("SC_SEM_NSEMS_MAX")=87381`，`SC_SEM_VALUE_MAX=32767`；`ipcs -s` 为 0 个 SysV 信号量集。
- **FACT：** 当前环境的进程池和信号量创建可用；没有复现 `PermissionError`、`ENOSPC` 或 `OSError`。
- **INFERENCE：** 这只能排除“当前仍处信号量耗尽”；它不能倒推出 2026-07-29 更早时刻的全部资源状态。不过三次历史运行根本尚未到达进程池代码，因此历史 `preregister` 停止也无需依赖该推断。

#### B. 下一输入单元的隔离构造探针

- **FACT：** 旧目录已有 56 个输入单元，最后完成的是 `cn-jjj-150c-01-V2-LOCATIONS__mismatch25`；下一单元为同实例的 50% 错配输入。
- **FACT：** 隔离探针只装载该 bundle 并调用当前 `build_mapping`，没有调用 `run_search`、没有产生效果结果。`/usr/bin/sample` 的 743 个样本中，728 个落在 `Z3_solver_check_assumptions` 调用链；对应当前源码是 `run_e3e6_formal.py:2029` 的 `solver.check(*assumptions)`。
- **FACT：** 探针约 408 秒持续接近 100% CPU；停止前 RSS 曾约 1.03 GB，`/usr/bin/time` 记录峰值 RSS 1,269,661,696 字节。进程没有自行退出、没有 traceback、没有 OOM kill；本次诊断以 SIGTERM 显式终止，退出码 143。
- **FACT：** 诊断期间机器为 8 GiB RAM；一个资源快照的空闲页约 3,592×16 KiB（约 56.1 MiB），swap 已用约 3.49 GiB。该读数证明当时整体内存压力高，但不证明旧 runner 被 OOM 杀死。
- **INFERENCE：** 当前源码下，56/135 后“看似停住”的直接计算原因是 Z3 精确完成约束检查很重；高内存压力可能进一步拖慢它。现有证据不支持把它写成崩溃，更不支持把信号量耗尽写成三次历史停止的原因。

### 1.4 对四个重点问题的明确回答

- **FACT（在哪一行、哪个系统调用退出）：** 历史进程由 monitor `experiment_monitor.py:273` 的 `os.killpg(PGID, SIGTERM)` 终止；monitor 调用入口为第 514 行。历史 runner 的信号到达行未被保存，不能恢复。当前隔离探针的计算热点为 `run_e3e6_formal.py:2029` 的 Z3 `solver.check`，但不能把当前行号冒充三份旧源码的历史 PC。
- **FACT（是不是信号量）：** 不是三次 `preregister` 停止的直接原因。`preregister` 在 `run_e3e6_formal.py:2498-2501` 串行构造输入；进程池首次出现在后续 `pilot` 的第 2764-2767 行，正式阶段另在第 3318 行。
- **FACT（是不是内存）：** 现场证明内存压力高，但没有 OOM kill、`ENOMEM`、jetsam/系统杀进程记录或异常堆栈。直接终止原因是人工 SIGTERM；内存只能列为性能风险，不能列为死因。
- **FACT（stdout 为什么为 0）：** stdout/stderr 已正确合并重定向，但 runner 在预注册返回前没有 stdout 打印，且在唯一最终 `print` 前被 SIGTERM 终止。

## 2. 孤儿 `resource_tracker` 的核对与清理

### 2.1 清理前

- **FACT：** 清理前进程为 PID 41251、PPID 1、PGID 41229、状态 `T`，命令为 Python `multiprocessing.resource_tracker main(8)`。
- **FACT：** 进程开始时间为 2026-07-29 22:23:16；本次清理发生于 2026-07-30 02:03 左右，存活约 3 小时 40 分钟，不是“超过一天”。已知事实中的寿命描述被现场时间戳推翻。
- **FACT：** `lsof -p 41251` 显示 stdout/stderr 指向 `baselines/china_e3_e7/e5_nonlinear_20260729/monitor_runtime/runner.log`，FD 8 是一条管道；全局 `lsof` 未发现该管道仍有写端/对端持有者。进程无子进程、父进程已不存在，也没有 socket 或其他业务数据文件句柄。
- **FACT：** 清理前 `ipcs -s` 为 0 个 SysV 信号量集；`kern.sysv.semmni/semmns/semmsl/semmnu` 均为 87381，`semume=10`，`SC_SEM_NSEMS_MAX=87381`。
- **INFERENCE：** 父进程消失、管道无对端、tracker 被 SIGSTOP 卡住，说明它已不再服务于活跃 worker。恢复它读取 EOF、执行自身登记的清理，比直接 SIGKILL 更安全且保留了直接证据。

### 2.2 清理动作与结果

- **FACT：** 本次只向 PID 41251 发送 `SIGCONT`。tracker 恢复后从已断开的管道读到 EOF，发出 Python 自身的泄漏警告、清理资源并自行退出；没有使用 `kill -9`，没有删除目录或原始结果。
- **FACT：** tracker 报告 5 个泄漏的 POSIX 命名信号量：

  ```text
  /mp-d6r7ujj8
  /mp-hs_imh65
  /mp-1odsla7i
  /mp-bo_utwi2
  /mp-ice2lqxt
  ```

- **FACT：** 清理后 PID 41251 消失，系统中无其他 `multiprocessing.resource_tracker`；对上述五个名称分别调用 `sem_open(name, 0)` 均返回 `errno=2 (ENOENT)`。
- **FACT：** 清理后 `ipcs -s` 仍为 0；`kern.sysv.semmni/semmns/semmsl/semmnu=87381`、`semume=10`、`SC_SEM_NSEMS_MAX=87381` 均未变化。

|资源口径|清理前|清理后|分类|
|---|---:|---:|---|
|SysV 在用信号量集（`ipcs -s`）|0|0|**FACT**|
|已知被 tracker 登记的 POSIX 泄漏名称|5|0/5 仍存在|**FACT**|
|`SC_SEM_NSEMS_MAX` 配置上限|87381|87381|**FACT**|
|孤儿 tracker|1|0|**FACT**|

- **FACT：** macOS 的 `ipcs` 只显示 SysV IPC，不提供“POSIX 命名信号量全系统剩余配额”计数。因此不能把 87381 误写成实时剩余量；可直接确认的是五个已知泄漏名已全部不存在。
- **FACT：** tracker 退出时把泄漏警告追加到原 E5 `runner.log`。该文件清理前为 56 字节、SHA-256 `64962291ee23...`，内容只有一条 `PREFLIGHT_PASS`；清理后为 327 字节、SHA-256 `95289df770356d7a91b29137269b220a9038bcc84cfb3a00c5939c44d810c317`。这是授权清理产生的追加证据，没有删除或覆盖旧行。

## 3. 删除 pilot 预算阶梯与饥饿判据的只读改动面

本节仅评估，不实施，不批准固定预算值，不触及 `route_pool_sp.py`。

### 3.1 `run_e3e6_formal.py` 的函数与行段

|行段（当前 3,769 行版本）|现有职责|若改为用户另行批准的固定完整候选预算|
|---|---|---|
|6-8，62，75|模块说明与 `PILOT_SEEDS` 接线|删除 pilot 叙述和不再使用的种子常量/接线|
|2635-2654|预注册中的 `budget_pilot` 阶梯、两条饥饿判据和选择规则|改成固定预算来源、审批/合同标识与全臂共用规则；不在本报告填写数值|
|2703-2737 `pilot_worker`|运行单元、读取 L/S、判 starved|整体删除|
|2740-2839 `run_pilot`|逐档建进程池、汇总、选择预算、写 pilot 产物|整体删除|
|3083-3087，3109|formal worker 从 pilot decision 取预算并传给搜索|改为从固定合同/命令配置读取同一批准预算|
|3126-3130|记录固定预算及 L/S 诊断|预算字段保留；L/S 可只作诊断或删除，但不能继续作选择门|
|3277-3279，3314|formal 强制先跑 pilot，并把 selected budget 写进 progress|删除 pilot 调用，直接记录固定预算|
|3635-3639|最终 decision 读取 pilot 选择|改记固定合同预算及来源|
|3671-3689|报告读取并渲染 pilot 阶梯表|删除，换成固定预算口径说明|
|3747-3748，3755-3756|CLI 暴露 `pilot` 子命令|删除该子命令及分派|

- **FACT：** 直接改动面约覆盖 175 行现有代码/文字；其中约 135 行是可整体删除的 `pilot_worker`、`run_pilot` 和 CLI/报告接线，其余是固定预算来源、元数据、decision 与报告字段的替换。
- **INFERENCE：** 净改动量预计为删除约 130-150 行、增加或改写约 25-40 行，另需对独立检查器、task card/monitor 配置做小范围同步。该估计不包含任何算法改动，也不包含新的正式搜索。
- **FACT：** `baselines/china_e3_e7/run_e5_nonlinear_20260729.py:58-62` 是另一份独立阶梯/阈值实现；删除 E3/E6 的 pilot 不会自动修订 E5，且 E5 已 HALT，不应顺手改。

### 3.2 是否触及路线池搜索语义、是否改变解质量

- **FACT：** 若只删除预算 pilot，并把用户批准的固定预算原样传入现有 `e3.run_search`，同时不改 `baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py`，路线池候选生成、倒数第二次/最后一次评价调度和最终证书语义都不变。
- **FACT：** 该改动不修复、移动或重新解释 `route_pool_candidate_or_parent` 与 `final_independent_certificate` 的评价顺序；它只是停止用由该顺序污染的 L/S 指标选择预算。
- **FACT：** 搜索预算本身会影响被评价候选数与最终 incumbent，所以固定预算与旧阶梯最终选中的预算若不同，输出解可能不同。
- **INFERENCE：** 不能事先保证解质量严格上升、下降或不变。较多评价通常提供更多搜索机会，但启发式轨迹、最终路线池和随机状态使“必然更优”不是可证明结论。

### 3.3 对已封存 E2、E4 的影响

- **FACT：** 只要新 E3/E6 入口使用独立输出目录、不覆盖封存产物、不修改保护 solver 文件，也不修改 E4 所使用的封存 E2 解，E2 与 E4 的既有哈希证据不会因后续 runner 变化而失效。
- **FACT：** E4 是对 405 个冻结 MV 解的固定路线、零搜索择时回放；E3/E6 的预算选择逻辑不在其执行链中。
- **INFERENCE：** 若未来反而修改共享 `route_pool_sp.py` 的执行顺序，并用新算法身份重新生成 E3/E6，那会改变新结果的可比性与算法身份，但仍不会追溯性改写已封存 E2/E4；只有覆盖原文件、伪称同一算法身份或保护哈希漂移才会伤害封存证据。

### 3.4 继续修改旧 runner 还是写更小入口

- **FACT：** 当前 runner 实际为 3,769 行。它同时承载多版精确责任映射/Z3 完成、D3 复用、输入冻结、pilot、formal 多进程、E3 配对、E6 I/U/F、审计、图表与报告；三次重启记录的 runner 哈希也彼此不同，已有 56 个未完成输入目录需要隔离保留。
- **INFERENCE（推荐）：** 新建较薄的 E3/E6 编排入口更省总恢复时间、也更容易审计。它应复用当前已审计的输入读取/证书、未改的搜索与评价原语，并只实现固定预算接线、LOCK/FREE、I/U/F、独立核验和新输出目录；这不是重写 solver 或算法。
- **INFERENCE：** 如果目标仅是机械删除 pilot，直接在旧文件上做约 175 行手术会更快；但用户当前目标还包括故障可诊断性、旧现场隔离、减少自建约束和恢复正式证据链。综合这些要求，继续在 3,769 行文件上叠加分支的回归面和取证歧义更大。
- **FACT：** 本建议不包含预算数字、阈值批准、路线池语义修改或正式效果搜索授权。

## 4. E4 封存数据的系统总成本方向

已只读核对：

```text
baselines/china_e3_e7/e4_carbon_timing_20260729/magnitude_diagnostics.json
baselines/china_e3_e7/e4_carbon_timing_20260729/raw_runs.csv
baselines/china_e3_e7/e4_carbon_timing_20260729/metadata.json
baselines/china_e3_e7/e4_carbon_timing_20260729/report.md
```

- **FACT：** `raw_runs.csv` 直接包含 `asap_full_model_cost_cny` 和 `carbon_full_model_cost_cny`，所以封存数据并非缺少系统总成本字段。
- **FACT：** `magnitude_diagnostics.json` 和 `report.md` 只直接汇总了充电电费，不直接保存完整模型总成本的总体百分比。
- **FACT：** 按 `report.md:23` 的既有汇总口径，对 11,340 行封存直接字段分别求和（不是重新调用 cost evaluator，也不是重新运行 E4）：

  ```text
  ASAP full-model cost sum   = 37,560,607.87242930705060 CNY
  CARBON full-model cost sum = 38,253,741.85126328260640 CNY
  delta                      =    693,133.97883397555580 CNY
  CARBON vs ASAP             = +1.8453747638699909%
  ```

- **FACT：** 系统总成本方向为 **上升**，CARBON 相对 ASAP 增加 **1.8454%**（四位小数）。
- **FACT：** 这与已知的充电排放 −54.9704%、系统排放 −9.7463%、充电电费 +134.8798% 一起构成“减排但增成本”的权衡，不能写成排放与成本同时改善。
- **FACT：** 四个指定文件中可用的成本字段/汇总为：

  |层级|可用字段|
  |---|---|
  |`raw_runs.csv` 每行|`asap_charging_electricity_cost_cny`、`carbon_charging_electricity_cost_cny`、`asap_full_model_cost_cny`、`carbon_full_model_cost_cny`|
  |`magnitude_diagnostics.json` 总体|ASAP/CARBON 充电电费总额及电费变化百分比|
  |`report.md` 总体/分组|充电电费变化百分比|

- **FACT：** 这四个文件没有把固定成本、里程成本、燃油成本、占用成本、转运成本、碳成本分别展开为 E4 两臂的独立字段；排放字段不是成本分项。

## 5. 当前参数配置、历史弱效应与可能的可观测区间

### 5.1 当前 2026-07-29 runner 的实际配置

- **FACT：** 当前 `run_e3e6_formal.py:58-63` 的主实例为 `cn-prd-150c-01-V2-LOCATIONS`，E3 名义错配档为 **0%、25%、50%**，两臂为 LOCK/FREE。
- **FACT：** 当前 E6 没有 α/θ 公平网格。预注册只列 I/U/F 三态（第 2645-2647 行）；F 从 U 的嵌套候选加 I fallback 中选参与约束可行的最低系统成本方案，`build_fair_state` 在第 3016-3020 行固定 `theta=1.0`。
- **FACT：** 因此“当前 E6 公平参数网格”若特指 2026-07-29 runner，答案是：**不存在网格，只有 θ=1 的参与保障终点**。

### 5.2 2026-07-13 E3 历史证据

- **FACT：** 零错配 v11 的 200c 十种子结果为 6/10 严格胜、平均账面改善 0.353316%、单侧配对秩检验 p=0.34765625、0/10 省车；直接证据在 `e3_v11_clean_20260713/final100/report.md:5-9` 和 `decision.json:12-14`。
- **FACT：** 同一历史计划的搜索波动诊断显示，独立成本样本标准差约为均值 1.151%，极差约为均值 2.818%；0.353% 小于该观测波动量级，但这不能证明 p 值只由搜索噪声造成。
- **FACT：** 旧 L-main 200c、零跨场费、固定错配表的历史轴只有 25% 与 50% 两个非零档：25% 为 10/10、平均节省 16.552646%；50% 为 10/10、平均节省 24.719286%。证据在 `e3_idealization_program_20260713.md:155-161` 和 `mismatch_x_friction_data.csv:7-8`。
- **FACT：** 两个旧错配档的“各自经营测量起点”都需要超过原每场 7 油+7 电资产，文档明确标为资产内不可行后的测量值；这些条件性结果不能直接当成当前 China81 150c 的正式效应。
- **INFERENCE：** 现有数据只支持“零错配效应弱，而在该旧固定算例的 25%-50% 错配条件下出现大效应”。0%-25% 之间没有历史采样，无法从现有数据定位首次可观测阈值，更不能把 25% 宣布为普遍阈值。
- **INFERENCE（设计建议）：** 若用户以后批准参数设计，应把注意力放在能实际改变责任分配、独立可行域和可接受跨场候选的非零错配区间；历史 25%-50% 可作为待验证区间的证据来源，但必须在当前 China81 构造上重新做结果前冻结，不能把旧 L-main 数值移植为论文结论。

### 5.3 2026-07-15 E6 历史公平网格与 binding 证据

- **FACT：** 历史 `e6_profit_guarantee_frontier_20260715/metadata.json:2-9` 的 α 网格为 **{0, 0.25, 0.5, 0.75, 1.0}**。
- **FACT：** 它不是固定 θ 网格。`metadata.json:36` 定义

  ```text
  theta(alpha) = mu + alpha * (1 - mu)
  ```

  其中 `mu` 是同组无约束合作方案中较弱车场的利润比；α=0 为无约束方案，α=1 对应 θ=1。

- **FACT：** 54 个 spec 中，24 个的无约束方案已自然满足双方不吃亏，后四档直接复用 α=0；只有 30 个 spec 有 `mu<1`，即存在可能 binding 的空间。
- **FACT：** 在固定候选池的 `selected_frontier.csv` 中，正成本增量 spec 数随 α 为：α=0.25 时 12/30，α=0.5 时仍为 12/30，α=0.75 时 14/30，α=1 时 16/30。相邻档共发生 25 次方案切换，涉及 16/54 个 spec；α=0.25→0.5 之间只有 1 次切换。
- **FACT：** 观测到正成本增量时，α=0.25 对应 θ 范围约 0.877348-0.993813；α=0.75 对应约 0.917194-0.997938；α=1 全部为 θ=1。不同 spec 的 `mu` 不同，所以不能用一个全局 θ 数字描述 binding 点。
- **INFERENCE：** “α=0.25 与 0.5 的正增量数量相同、两档之间仅一次方案切换，而靠近 α=1 又出现更多切换”与“粗网格跨过不少实例各自的 binding 转折”相符；但离散候选池和启发式搜索也会产生平台，不能把所有平坦段都解释成纯粹网格过粗。
- **INFERENCE（设计建议）：** 可能产生可观测公平效应的参数区间应限定在 `mu<1` 的 spec，并围绕每个 spec 从当前无约束 `mu` 向 θ=1 推进时实际发生候选可行集/最优候选切换的局部区间；现有数据尤其提示接近参与保障端的区间更常 binding。若以后获批设计，应采用按 spec 自适应检查这些已观测切换区间，而不是再加一个未经批准的全局阈值。
- **FACT：** 该建议只是历史数据上的设计诊断，不是对当前 E6 参数的修改，不批准新 α/θ 网格，也不把“可构造”写成“公平机制必有显著代价”。

## 完整性与边界

- **FACT：** 本次没有启动任何正式效果搜索；最小进程池探针只计算整数平方，Z3 探针只进入输入映射构造，E4 只读取封存字段。
- **FACT：** 没有修改 `solver/src/setp_solver/cost.py`、`solver/src/setp_solver/check.py`、`solver/src/setp_solver/search/evaluation.py`。报告写入前核对的 SHA-256 分别为：

  ```text
  2717b4b4de39bb4c2a9a1bda602f4420cb3e3b1e87faa83678dfa64f88fc80be  cost.py
  9c81e254e05591667c8225965bb9d0ba4e8bbfc53eb0f8c61ffdb4325a1403a8  check.py
  c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3  evaluation.py
  ```

- **FACT：** 未删除、覆盖或重命名任何旧失败现场或封存原始证据；唯一由清理动作引起的既有文件变化是 E5 `runner.log` 追加了 tracker 自身的五信号量清理警告，原第一行仍保留。
- **FACT：** 没有替用户批准方法、预算或阈值；没有修改算法或 `route_pool_sp.py`。
