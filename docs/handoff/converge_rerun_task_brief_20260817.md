# CONVERGE-RERUN 任务书：重跑收敛观测（发给 Codex，启动即退，不陪跑）

先读 `docs/handoff/codex_standing_charter_20260817.md`。**本任务只做启动，3 分钟内退出。**

## 背景（你上一轮自己写的现场）

上一跑被外部 `SIGKILL`（`converge_long_20260817/report.md`，`CONVERGE_LONG_HALT`）。
`FACT`（Claude 查明的凶手证据）：交换区 4096M 已用 2876M——**8G 内存被压爆，
系统内存压力杀进程**（本机有跑死两次前科，AGENTS 6.2）。
主要浮动内存占用者之一是整夜陪跑的 codex 壳本身。**故本次改为：你启动完就退出，
求解器孤儿化独跑，监控交给会话内的轻量哨兵（已含内存采样）。**

## 你要做的（全部动作，别的不做）

1. 核对入口与保护文件哈希与 `converge_long_20260817/resume.md` 收口值一致；
2. 用 resume.md 里验证过的配方启动（**注意它的两个教训：带 PYTHONPATH；
   输出目录让 runner 自建，不预建**），输出目录 `solver/reports/converge_long_20260817_rerun`：

```bash
cd /Volumes/移动硬盘（512G）/ReSETP && \
nohup env PYTHONPATH=.:/Volumes/移动硬盘（512G）/ReSETP/solver/src:/Volumes/移动硬盘（512G）/ReSETP/third_party/setp_hgs_kernel \
build/python_envs/setp-independent-hgs/bin/python \
  solver/scripts/run_problem_hgs_private_technical.py \
  solver/reports/converge_long_20260817_rerun \
  --instance-id cn-jjj-50c-01-DEPOTSEARCH-d996f755bd --seed 11 \
  --iterations 200000 --max-runtime-seconds 16200 \
  --stagnation-patience 500 --penalty-solutions-between-updates 50 \
  --fleet-parameter-class endogenous --population-mode copied_hgs_defaults \
  --proposal-config combat --route-layer-crossover --depot-assignment-operator \
  --trajectory off --education-depth-limit 1 \
  > solver/reports/converge_rerun_launch_20260817.stdout.log 2>&1 & disown
```

3. 把求解器 PID 写入 `solver/reports/converge_rerun_launch_20260817.pid`；
4. 等 60–120 秒，确认进程存活且输出目录出现 `convergence.csv` 首行；
5. 写一页 `solver/reports/converge_rerun_launch_20260817.md`：
   首行 `RERUN_LAUNCHED`（或 `RERUN_LAUNCH_FAILED`＋现场），PID、启动时刻、核对的哈希；
   **然后立即退出**——不陪跑、不轮询、不写完成报告（收尾报告由哨兵通知后另写）。

## 边界

零代码改动；不碰保护文件与 `charging.py`；不删不动上一跑的中断现场；
不把两跑曲线拼接。若启动两次仍失败：停，保留现场，报告首行 `RERUN_LAUNCH_FAILED`。
