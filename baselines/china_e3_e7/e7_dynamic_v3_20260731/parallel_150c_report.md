# E7 150c 并行运行报告

任务：在保留 100c 已完成单元的前提下，启动并监督冻结的 E7 150c 四臂、种子 1--10 正式矩阵。

## 启动核验

- 启动时间：2026-07-30 15:19:04 +08:00。
- 150c 入口：项目锁定 Python 以 `python -u run_e7_dynamic.py formal --scale 150c --workers 4` 启动。
- 150c 进程组：PGID 95357；四个计算子进程 95363、95364、95365、95366 启动后均为 `RN`，均有持续 CPU 占用。
- 数值线程环境：`OMP_NUM_THREADS=1`、`OPENBLAS_NUM_THREADS=1`、`MKL_NUM_THREADS=1`、`VECLIB_MAXIMUM_THREADS=1` 显式传入。
- 内存门：8 GiB 物理内存；启动前 macOS memory-pressure 可用比例 29%，四 workers 获准启动。
- 冻结合同：预算锁、四臂、种子、事件流、算例和评价语义未改；`cost.py`、`check.py`、`search/evaluation.py`、`profit.py`、`route_pool_sp.py`、`epochal_hgs.py` 未改。
- 监控：`monitor_parallel_150c.json`，自动 AI 关闭，完成标志为 `formal/150c/scale_complete.json`。

## 100c 保护现场

初始聊天快照称 100c 已完成 14 个单元；现场在 15:18 已有 16 个非 AppleDouble 任务文件。启动 150c 前已保存这 16 个文件的 SHA-256 清单。启动后复核 16/16 哈希一致。

原 100c PGID 67744 在 15:17:16 因监控器发现受保护 runner 哈希漂移而被暂停，随后被外部现场动作移除；本任务未向该进程组发送信号。15:18 后另一个外部现场动作以 PGID 95029、6 workers 恢复 100c，任务数推进至 17。该组未由本任务启动或修改。

## PID 75334

PID 75334 是 `baselines/china_e3_e7/e3_mismatch_20260731/run_campaign.py run --workers 2` 的独立 E3 孤儿主进程。它处于 `TNs`，PPID=1，无活动子进程，RSS 约 0.4 MiB，与 E7 目录无写盘关系。由于尚无可核实的权威完成标志，本任务保留该进程，不清理、不恢复。

本任务没有向 PID 75334 发送任何信号。终验时该 PID 已不在进程表；这是外部现场变化，不能归因为本任务清理或恢复。

## 运行治理

150c 首次以 4 workers 启动后，外部现场同时把 100c 扩到 6 workers，形成 10 个计算进程。1 分钟负载一度超过 20，单 worker CPU 从原约 98% 降到约 60%。按实验手册的资源证据，本任务只对 150c 降级，不触碰 100c。

四 worker 父进程 PGID 95357 随后被外部动作移除；四个在途子进程自然退出，没有半写任务文件。150c 从既有 2 个原子任务断点以 PGID 98280、2 workers 恢复，使总计算并发回到 8。恢复后两个 150c worker 约 80%--92% CPU，100c 六个 worker约 89%--96% CPU。

监控器曾因 `stale_seconds=1200` 在长单元仍持续高 CPU 时误报进度停滞并 SIGSTOP。既有 100c 单元墙钟已证明可超过 3,200 秒；本任务将监控阈值改为 7,200 秒，对同一 PGID 发送 SIGCONT 并重新附着。实验没有重启，预算、状态和在途任务未改变。

## 最终结果

- 150c：40/40 个任务文件齐全，全部为合同允许的 `LEGAL_INFEASIBLE`；合法不可行保留在分母，没有补零或惩罚目标。
- 完成标志：`formal/150c/scale_complete.json`，状态 `COMPLETE_150c`，`marker_sha256=3c5b1314f5e8e30410529f1652356f96f2bc850fd0c77bd45c7f8a5456691c68`。
- 冻结预算：每个搜索 pass 上限 600；每阶段总上限 1200。预算是上限，不是配额。
- 100c：终验时 34/40，PGID 95029 及六个计算子进程仍为 `RN`；本任务未向其发送信号。
- 100c 保护：启动前现场实际已有的 16 个非 AppleDouble 任务文件，终验时 SHA-256 逐文件 16/16 一致；其余文件由 100c 自身继续写出。
- 线程环境：四个数值线程变量始终显式为 1。
- 文件口径：任务统计和哈希枚举均排除 `._*`；监控目录不作为论文证据。
- 保护文件终验：`cost.py`、`check.py`、`search/evaluation.py`、`profit.py`、`route_pool_sp.py`、`epochal_hgs.py` 的 SHA-256 与冻结值一致。
- 终验资源：8 逻辑核；memory-pressure 可用比例 54%；负载 9.59/12.47/13.47。
- 终验总 `RN` 计算进程数：6，全部属于仍在运行的 100c；150c 已正常退出。

本报告只确认 150c 规模执行完整及运行治理事实。40/40 合法不可行是正式结果状态，不被改写为有限目标或机制效果。
