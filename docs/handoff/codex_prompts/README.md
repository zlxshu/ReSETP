# Codex 提示词存档（按序发）

每条发给 Codex 前，让它**先完整读仓库根 `HANDOFF.md` + `docs/handoff/memory/baseline-algorithm-catalog.md`**（项目单一事实源、8 基线设计转录、公平对比 harness 接口、环境铁律、来龙去脉）。

- `01_offline_probe.md` — 轨①：DR 离线探针 + 课程预备。**已跑，verdict = PROMISING**（r2_delta≈1.05）。留档/复现用。
- `02_baselines.md` — 轨②：8 文献基线复刻 + 公平对比。**已实现接入，但 HALT_BASELINE_THROUGHPUT**（eval/s 3.96–11.04 < 17.78）。被 03 接续。
- `03_baseline_speedup.md` — 轨②续：基线提速 + 正式公平对比（**当前要发的那条**）。

环境铁律：全部在 **M1 基准机**、系统 Python `/opt/anaconda3/bin/python3.13` + numpy 2.3.5 跑（数字要与 £4878/£5347 锚同环境可比）。Codex 冷启动、读不了论文——提示词已把目标/背景/实现/验收/边界/捷径写全，arXiv 论文可自取、中文期刊设计已转录在 baseline-algorithm-catalog.md。
