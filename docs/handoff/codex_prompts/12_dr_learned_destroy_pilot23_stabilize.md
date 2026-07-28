# Codex 提示词 12 — Pilot23 学习型破坏「稳定化 + 峰值 checkpoint 确认」（自动·分阶段·过夜）

> Claude 写定（2026-06-28）。**Pilot22 是突破被不稳定盖住**：三条文献修法(POMO shared baseline + 5/3/1/0 reward + validation-cost G1)生效，held-out 验证从 −15.9% 冲到 **+11.5% 峰值**，零违约/熵地板 ok/loss 有限；**唯一坏的是 `kl_ok=False`(KL 爆) + 末段回落到 +2.4%**=经典 PPO 后期失稳 + 未做 checkpoint 选择。本轮**不重起炉灶**，只解这两件已知问题。冷启动、本文件自包含。

## 0. 开工前必读
`HANDOFF.md` 2026-06-28 段 + Pilot22 产物 `solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot22_grounded_fixes/`(report/update_log/validation_rows/checkpoints) + Pilot22 代码(`pilot22_*`/`learned_destroy*`) + `docs/handoff/codex_prompts/10_*.md` §9(过夜铁律全用)/`11_*.md`(三修法).

## 1. 文献依据解法（公认可引用；网络额度满，均为标准技术）
- **解法1 — 选峰值 checkpoint + 独立测试集复核（最便宜、最关键）**：NCO/RL 通用做法是**按验证选最佳 checkpoint、在独立 test 上报结果**（POMO/AM/RL4CO）。Pilot22 已有 +11.5% 峰值 → 该用峰值那个 checkpoint，而非 final。**但必须防泄漏**：选 checkpoint 的 validation 与最终报告的 test 要**分开**（否则 +11.5% 是选择偏差）。
- **解法2 — target-KL early stopping（直接修 `kl_ok=False`）**：PPO(Schulman 2017)/SB3/CleanRL 标准——当 epoch 内 `approx_kl > target_kl` 即停止本次更新，防 KL 爆与峰后崩。
- **解法3 — LR 退火 + 减小 clip/减少 ppo_epochs**：标准 PPO 后期稳定化，降更新幅度、止回落。
- 保留 Pilot22 已生效的 POMO shared baseline + 5/3/1/0 reward + 验证-cost 判据 + 熵地板(仅防塌缩)。

## 2. 阶段执行（自动先后串行，带闸；§9 过夜铁律全用）

**Stage A — 峰值 checkpoint 独立测试复核（不训练，先跑，可能直接出结果）**：
- 定位 Pilot22 验证峰值(+11.5%)对应 checkpoint（或最近保存的；若未单独存峰值 ckpt，从周期 checkpoint 里取验证最高那个；都没有则记 `PEAK_CKPT_MISSING` 跳到 Stage B）。
- 在**全新独立测试集**（新 bundle + 新 seeds，**与训练/验证不重叠**；25/50c 为主，可加 100c）上确定性评 learned(峰值ckpt) vs operator-select vs random vs worst_removal，同预算同 worker py313。
- **闸 GA**：峰值 ckpt 在独立 test 上 **平均 ≥+5%、每规模≥0、稳超 random 与 worst_removal、零违约、worker py313/NumPy2.3.5** → `PASS_LEARNED_DESTROY_CKPT`（经标准 checkpoint-selection 的合格结果）→ **绿灯 Phase B，不必再训**，写报告结束。若掉到 <+2% → 峰值是验证噪声/选择偏差 → 进 Stage B。介于 2–5% → `WEAK`，记录并仍进 Stage B 试稳定化。

**Stage B — 稳定化重训（仅 GA 未达 PASS）**：在 Pilot22 基础上加 **解法2(target-KL early stop)+解法3(LR 退火/减 clip/减 epochs)**；**validation 与 test 严格分离**；周期保存 + **显式保存 best-validation checkpoint**。
- **闸 G1(稳定版)**：validation 达峰且**保持稳定**（连续若干 update `kl_ok=True`、gain_slope 不为负、best-validation 不比峰值回落超阈值）→ 过；若仍 KL 爆/峰后崩塌 → `HALT_POLICY_UNSTABLE_V2`+诊断（建议更小 lr/clip、更强 KL 约束、或减小 batch）。

**Stage C — 独立 test 正式判级（仅 G1 过）**：best-validation checkpoint 在**独立 test**上 vs operator-select/random/worst_removal。`PASS_LEARNED_DESTROY`(≥+2%每规模≥0稳超random/worst零违约→Phase B)/`WEAK`/`HALT_LEARNED_DESTROY`(诚实负结果)。

## 3. resume guard + 边界 + 过夜铁律
沿用 11 §3 resume guard（禁 `--resume` 绕过 HALT 类 state 进后续 stage）。不改 `cost.py/check.py/search/evaluation.py/winner_operators.py`；worker py313+NumPy2.3.5；runner py312 cu124；只 x86 相对；飞行前检查；周期 checkpoint；全局墙钟≤6h；防 OOM；**禁过夜 push/rebase**(dr-x86 留人工 reconcile)；只 force-add 小产物(报告+CSV+best ckpt)；增量写 `pilot23_progress.log`；连续 3 次自修失败升级诊断停；每改动记"症状→出处→改哪→为什么"。

## 4. 交付物
`pilot23_report.md/json`(Stage A 峰值 ckpt 独立 test 结果 + 稳定化落地+出处 + G1 曲线 + Stage C 判级 + 人话"这对目标意味着什么")、`pilot23_stageA_independent_test.csv`、`pilot23_update_log.csv`(含 KL/validation 曲线)、`pilot23_phase_rows.csv`、best-validation ckpt/小模型。最终人话报：峰值 ckpt 在独立 test 上保不保得住 +10%、KL 稳没稳、判级、下一步(Phase B / 继续稳定化 / future-work)。

## 5. 资料顺序
先读 HANDOFF+Pilot22 产物+代码 + PPO target_kl(SB3/CleanRL)/POMO checkpoint 实践，再单点改、阶段跑、带闸自停。不得用"我猜"替代查文献/读码。
