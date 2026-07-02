# Codex 提示词存档（按序发）

每条发给 Codex 前，让它**先完整读 `docs/handoff/READ_ME_FIRST_FOR_AGENTS.md`**，并按其中清单读取 `HANDOFF.md`、PRD v2、规划地图、memory index、当前任务提示词和相关 memory 节点。读完前不得动手、不得跑实验、不得下论文结论。

DR lane（x86）历史：
- `01_offline_probe.md` — 轨①：DR 离线探针。**已跑，verdict = PROMISING**。留档。
- `04`–`07` — DR 课程 pilot 机制搭建/跑/迁移/缩预算（x86 lane，留档；详见 HANDOFF 变更日志）。

轨②=E2（算法对比 → T3/F2）历史与当前：
- `02_baselines.md` — 8 基线初版接入。**HALT_BASELINE_THROUGHPUT**，被 03 接续。
- `03_baseline_speedup.md` — 基线提速 + 16000-eval 对比。**已发、已 HALT**：提速实现但正式对比未过；体检暴露 5 基线 std=0 没搜索、LNS 赢 ALNS、等-eval 口径对慢基线跑不通。**被下面 08–11 的 E2 重构取代。**

**E2 重构（当前主线，2026-06-21，按阶段顺序发）**：
- `08_e2_instance_generation.md` — 阶段①：生成 69 算例基准（goeke_uk 原味 + 多车场 + 三班，3 类×9/5 档×3，ReSETP 口径 best-found 不挂 BKS）。**零算法风险，先发。**
- `09_e2_alns_literature_best.md` — 阶段②：winner ALNS 强化到文献最优（修“摸不到全油车”，偷 LNS 大邻域+成本感知修复，消融定稿）。**改全论文算法底座、下游 E1–E7 需重跑。**
- `10_e2_baselines_literature_best.md` — 阶段③：8 基线按源论文重做到文献最优（现随机键版太弱、std=0），加“真在搜索”硬门禁。
- `11_e2_protocol_and_run.md` — 阶段④+⑤：等墙钟协议+硬超时，69 算例正式跑出 T3（best-found/gap%/time/Wilcoxon/收敛曲线）。

E2 09 系列诊断续线（2026-06-22/23）：
- `09b_e2_alns_scan_bridge.md` — 扫描桥接 GLNS/LNS 构造；已 HALT，暴露 200c 方差/全油盆地问题。
- `09c_e2_alns_sa_acceptance.md` — SA 接受准则修复；已 HALT，稳定性改善但未过门。
- `09d_e2_alns_throughput.md` — 吞吐根因与提速；已 HALT，吞吐不是主因，GLNS/LNS 在全油主导 regime 更强。
- `09e_instance_param_diagnostic.md` — 小算例参数诊断；已完成，25/50c 小算例 mixed 本就最优，不能诊断全油退化。
- `09f_largescale_allcv_diagnostic.md` — 大算例 all-CV 诊断；已完成，100/150c 是 mixed best 存在但均值不稳，200c 是真实 all-CV best+mean 占优，40km/h fixed replay 可翻盘但未重优化。
- `09g_urban_reopt_confirmation.md` — **暂停/降级为草案**：只适用于“城市/本地配送速度”场景确认。用户已指出当前大算例偏跨城/高速，不能直接把 40km/h 当主线参数。
- `09h_parameter_evidence_review.md` — **当前下一步**：先做 2020+ 文献/Zotero/行业证据矩阵 + 当前路线 regime 审计 + 证据约束 fixed replay，确认速度/电池哪个现实参数可用。
- `09i_evidence_bound_reopt_confirmation.md` — 09h 后续：只对 09h 证明“证据成立且 near-flip/flip”的场景做真实重优化确认。

环境铁律：全部在 **M1 基准机**、系统 Python `/opt/anaconda3/bin/python3.13` + numpy 2.3.5 跑（数字要与 £4878/£5347 锚同环境可比）。Codex 冷启动、读不了论文——提示词已把目标/背景/实现/验收/边界/捷径写全，arXiv 论文可自取、中文期刊设计已转录在 baseline-algorithm-catalog.md。
