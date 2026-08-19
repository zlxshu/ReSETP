# CONVERGE-LONG 任务书：整夜收敛观测（发给 Codex，自包含）

先读 `docs/handoff/codex_standing_charter_20260817.md`（P84）。本任务是**机械执行**：
启动一次长收敛观测并守到收尾。**零代码改动、不改算例、不碰保护文件。**

## 为什么（一句话）

解码器 DAG 重写已逐位验收（`fix_decoder_dag_20260817/`，800 迭代墙钟 1598.8→745.5 秒）。
P79 收敛判据＝曲线形态、判官＝用户看图；`T_conv` 是全环节最重要的待测数
（`algorithm_phase_prd_20260817.md` §4.2）。本跑给第一读数。

## 命令（与 800 档探针**同轨延长**，只改三处：输出目录、迭代上限、安全墙钟）

```
python solver/scripts/run_problem_hgs_private_technical.py \
  solver/reports/converge_long_20260817 \
  --instance-id cn-jjj-50c-01-DEPOTSEARCH-d996f755bd --seed 11 \
  --iterations 200000 --max-runtime-seconds 16200 \
  --stagnation-patience 500 --penalty-solutions-between-updates 50 \
  --fleet-parameter-class endogenous --population-mode copied_hgs_defaults \
  --proposal-config combat --route-layer-crossover --depot-assignment-operator \
  --trajectory off --education-depth-limit 1
```

要点：`--iterations 200000` 是**不触发的上限**；实际停止＝16200 秒（4.5 小时）安全墙钟。
这是 P79 口径的观测跑（不预设科学预算，墙钟只是运营安全绳）；
同参数保证与 100/200/400/800 档**同一确定性轨迹**的延长——已有 14 个改进点直接续上。

## 你要做的

1. 用你惯用的正确环境（与 `decode_growth_probe` 相同的 venv/入口）**同步**执行上述命令，
   等它自然收尾（预计 4.5 小时；你保持会话等待，命令期间你不消耗推理）。
2. 收尾后写 `solver/reports/converge_long_20260817/report.md`：
   首行 `CONVERGE_LONG_DONE`（或 `_HALT`），末行 `CONVERGE_LONG_END`。内容：
   - 完成迭代数、终止原因（迭代/墙钟哪个触发）、总墙钟；
   - `convergence.csv` 的改进点总数、首末各 5 行；
   - **形态描述**（大白话：还在掉？平了多久？最后一次改进在第几圈/第几秒）——
     只描述，不判"收敛与否"（那是用户看图的事，验收乙类）；
   - 最优成本、可行性、服务客户数/需求量（红线必报）；
   - 若中途异常：如实报现场，保留全部产物。
3. `done.json`＋`resume.md`（若被打断如何从同命令重跑；本跑确定性，重跑即复现）。
4. 结尾按章程给"我认为接下来该干什么、为什么"。

## 边界

不动 `hybrid_decoder.py` 与任何源码；不碰三保护文件与 `charging.py`；
期间不启动第二个求解进程（M1 8GB）；产物全落上述仓库目录（P80）。
