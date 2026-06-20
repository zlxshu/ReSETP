# M1 Claude 开工简报（盘到 M1 后，给 M1 上的 Claude）

> Claude(x86) 写于 2026-06-20。这是给迁回 M1 后那个 Claude 会话的开工指引。

## 第一件事
完整读仓库根 `HANDOFF.md` + `docs/handoff/memory/` 全部文件（单一事实源：机器/环境坑、三条工作线、纪律、来龙去脉、变更日志）。读完再动。

## 你是谁、在干什么
- 你在 **M1 基准机（macOS/ARM）= 论文所有正式数字的唯一来源**。系统 Python `/opt/anaconda3/bin/python3.13` + numpy 2.3.5，£4878/£5347 锚就是这里来的。
- **x86(Windows) 正在并行跑 DR-ALNS pilot**（在 `dr-x86` 分支、`D:\ReSETP`，与你完全隔离）。**你留在 `codex/reporting-pipeline` 分支，不要碰 `solver/rl/`（那是 x86 的 DR lane）。**
- **⚠️ 关键区别**：本项目"只报相对%、不比绝对值"那条铁律**只适用于 x86 的 DR**。**你在 M1 出的是绝对正式数字**（对标 £4878/£5347 锚，碾压/持平判级照旧）。别把 x86 的相对%口径套到你的基线对比上。
- 角色照旧：M1 的 Claude 只思考/判断/写 Codex 提示词/写文档，不跑不改代码；M1 的 Codex 执行。与 user 平实中文。

## 你的两条论文保底线（按优先级）
1. **轨②｜8 个 ALNS 文献基线正式对比（论文刚需，先做）**：
   - 现状=已实现接入、零违约跑通，但 HALT 在吞吐（eval/s 3.96–11.04 < 17.78）。
   - **执行提示词已就绪**：`docs/handoff/codex_prompts/03_baseline_speedup.md`（profile→提速→16000/900s 或放宽墙钟的公平对比→出表+Wilcoxon+收敛曲线）。你的活=判 03 的提速思路对不对、派给 M1 的 Codex、核结果。
   - **注意**：DR-ALNS 还在 x86 pilot、未就绪，所以这轮对比是 **ALNS(winner kernel) + 公平 SA vs 8 基线**（GA/PSO/VNS/ACO/GA-VNS/LNS/GWO/IWD），DR 列等 x86 pilot 出结果、合并后再补。
   - 真目标=证明 ALNS 打得过这些文献主流（不只赢 SA）；诚实：哪个没赢/没收敛如实写。
2. **图表｜顶刊级壳复印（design-heavy，你主导）**：
   - 方案=`docs/handoff/memory/figure-redesign-task.md`（壳目录已建完，下一步=数据适配矩阵→Codex 填数出草稿→你审→进正式）。需要**开 Zotero 桌面应用**读范本图。
   - 方法论铁律：壳由参考文献定、数据来自 ReSETP、Codex 只复印灌数不自由设计。**你（M1 Claude）主导设计像素级规范**，别让 Codex 自由发挥；图表数字等大重跑已定稿（commit 9da7f8b），可直接用。

## 同步与合并
- 先 `git pull` 取最新（x86 已 push 到 `codex/reporting-pipeline`，HEAD≈5ad097e8 之后）。
- x86 的 DR pilot 跑完后，其 `dr-x86` 分支 + 小产出（模型.pt/相对%报告）会合并进来；HANDOFF 变更日志冲突时，x86 条目标 `[x86/DR]`、你标 `[M1]`，两边追加行都保留（合并时 Claude reconcile）。
- 你每次决策/ Codex run 后，在 HANDOFF 变更日志追加一条标 `[M1]` 的 run log。

## 边界
- 不动 `solver/rl/`（x86 的 DR lane）；禁改 `cost.py`/`check.py`/`search/evaluation.py` 语义；不动 winner kernel 算子逻辑。
- 基线/图表都在 M1 系统 Python 跑（别在任何 RL venv 跑，数值会漂）。
- 跑不出诚实 HALT，不注水、不混旧数据。
