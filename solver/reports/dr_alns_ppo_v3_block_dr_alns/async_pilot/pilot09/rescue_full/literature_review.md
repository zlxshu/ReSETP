# Pilot09 Literature Review

- Zotero status: `PASS`
- Zotero API running: `True`

## Evidence

### A curriculum-based deep reinforcement learning framework for the electric vehicle routing problem

- source: `zotero` `7H4BZNNE`
- authors/year: Mertcan Daysalilar; Fuat Uyguroglu; Gabriel Nicolosi; Adam Meyers / 2026
- finding: Curriculum decomposition and phase-specific PPO stabilization are recommended for dense EVRP constraints.
- Pilot09 implication: Pilot08 already tested the main curriculum/stability recipe; next step is headroom diagnosis, not another identical long run.

### A curriculum-based deep reinforcement learning framework for the electric vehicle routing problem

- source: `zotero` `GKWV7NHV`
- authors/year: Mertcan Daysalilar; Fuat Uyguroglu; Gabriel Nicolosi; Adam Meyers / 2026
- finding: Curriculum decomposition and phase-specific PPO stabilization are recommended for dense EVRP constraints.
- Pilot09 implication: Pilot08 already tested the main curriculum/stability recipe; next step is headroom diagnosis, not another identical long run.

### HANDOFF Pilot08 WEAK and literature-first discipline

- source: `repo` `HANDOFF.md`
- authors/year: repo handoff / 2026
- finding: pilot08 = **WEAK（但比 pilot07 更干净、更有结论性）**。C 步 900s 等墙钟评测（C 工具 commit `f5b2f406`，C 结果 commit `750135d6`，**待 push**；提交链 ee342022→443527c6→f5b2f406→750135d6 干净线性、无分叉）：EVAL_BUDGET_900=13100（校准 runtime 884s）；选最优 held-out checkpoint=`update_0240`（final 精筛仅排第3，确有轻度末段退
- Pilot09 implication: Phase 1 must audit B2/C artifacts before running any new diagnostics, and Phase 3 must allow HALT_DR_HEADROOM.

### baseline catalog: Daysalilar curriculum DRL-EVRP

- source: `repo` `GKWV7NHV`
- authors/year: repo Zotero catalog / 2026
- finding: Daysalilar2026课程PPO-EVRPTW[GKWV7NHV](3阶段课程+改进PPO+异构图注意力,N=10训练泛化5-100); Wan2025 DRL-FSMVRP[6VNYWJ7Q](FRIPN+MDP秒级近优); Narayanan2022 RL-EVRP-V2G[BCBMVPMB](**RL vs MILP vs GA, RL快24×距最优<20%**)。**关键差异化: 它们是end-to-end神经构造(learning-to-construct), 我们DR-ALNS=RL导ALNS算子
- Pilot09 implication: Because Pilot08 already used small-to-large curriculum and phase-specific stabilization, the next fix should diagnose policy selection, meta-parameter headroom, reward alignment, and observations.

### baseline catalog: Wan DRL-FSMVRP state representation

- source: `repo` `6VNYWJ7Q`
- authors/year: repo Zotero catalog / 2025
- finding: Wan2025 DRL-FSM[6VNYWJ7Q]; Daysalilar2026 课程DRL-EVRP[GKWV7NHV]; Narayanan2022 RL-EVRP-V2G[BCBMVPMB]; Herdianto2025 ML引导启发式[X7N42RUB]。 **Claude推荐基线集**: Tier A(经典元启发+user旗舰混合)=GA/PSO/SA/TS/ACO/VNS/GA-VNS; Tier C(DR定位)=Wan/Daysalilar/Narayanan。诚实: 忠实复刻7+元启发是大工程,
- Pilot09 implication: Trace/profile diagnostics should look for observation aliasing in the current flat 19-dimensional state.

### baseline catalog: Narayanan EVRP action masking

- source: `repo` `BCBMVPMB`
- authors/year: repo Zotero catalog / 2022
- finding: Narayanan2022 RL-EVRP-V2G[BCBMVPMB]; Herdianto2025 ML引导启发式[X7N42RUB]。 **Claude推荐基线集**: Tier A(经典元启发+user旗舰混合)=GA/PSO/SA/TS/ACO/VNS/GA-VNS; Tier C(DR定位)=Wan/Daysalilar/Narayanan。诚实: 忠实复刻7+元启发是大工程, 建议先做SA(有)+GA+VNS+GA-VNS+ACO, 再加TS/PSO。 **⚠️2026-06-19 user调整**:
- Pilot09 implication: Pilot09 should explicitly test mask-aware stochastic evaluation because Pilot08 C used the standard ppo_block path.

### alns-crush-root-cause: PPO headroom against winner/AlphaUCB

- source: `repo` `docs\handoff\memory\alns-crush-root-cause.md`
- authors/year: repo handoff memory / 2026
- finding: PPO现实天花板=匹配kernel(从而碾压SA), 不太可能超过kernel。 **⚠️ 2026-06-16晚: 下方V3一度被误判为"退化丢失作废", 但提示词③已证 winner kernel健康、碾压成立(干净环境逐seed复现£4878/£4779)。V3碾压结论实际有效, 真问题是winner kernel非自包含确定性bug(同seed不同进程结果不同)。以文末"🔑真相修正"为准。** **2026-06-16 V3 决定性验证(⚠️已作废-代码丢失且退化, 见文末事故)**: - **100-
- Pilot09 implication: Pilot09 should stop same-shape PPO long training if stochastic policy and AlphaUCB-meta diagnostics cannot find reliable train+held-out headroom.

### algorithm-pivot-ca-alns: protect solver semantics and fair harness

- source: `repo` `docs\handoff\memory\algorithm-pivot-ca-alns.md`
- authors/year: repo handoff memory / 2026
- finding: CA-ALNS = Carbon-Aware ALNS, built ON the Wouda `alns` library.** Fix budget+operators (P2a, running) → fair vanilla baseline; add carbon-aware/charging-timing-aware destroy-repair operators (P2b = the real algorithm contribution, tied to time-varying grid car
- Pilot09 implication: The rescue tool may diagnose controller choices and traces, but must not rewrite cost, feasibility, evaluation, or winner-operator semantics.

### A curriculum-based deep reinforcement learning framework for the electric vehicle routing problem

- source: `web` `https://arxiv.org/abs/2601.15038`
- authors/year: Mertcan Daysalilar; Fuat Uyguroglu; Gabriel Nicolosi; Adam Meyers / 2026
- finding: CB-DRL decomposes EVRPTW into routing, energy, and full-constraint phases with phase-specific PPO hyperparameters, value/advantage clipping, and small-to-large generalization.
- Pilot09 implication: Pilot08 already applied this family of fixes and trained healthily, so Pilot09 should look for headroom/action-space issues rather than repeat the same long curriculum PPO run.

### Online Control of Adaptive Large Neighborhood Search Using Deep Reinforcement Learning

- source: `web` `https://ojs.aaai.org/index.php/ICAPS/article/view/31507`
- authors/year: Robbert Reijnen; Yingqian Zhang; Hoong Chuin Lau; Zaharah Bukhsh / 2024
- finding: DR-ALNS is framed as online ALNS operator selection and parameter configuration.
- Pilot09 implication: Pilot09 should separately test operator-choice headroom and parameter-only headroom instead of assuming one PPO policy must learn both.

### DR-ALNS: Deep Reinforced Adaptive Large Neighborhood Search

- source: `web` `https://github.com/RobbertReijnen/DR-ALNS`
- authors/year: Robbert Reijnen et al. / 2024
- finding: The public DR-ALNS implementation ties the method to the ICAPS 2024 online-control paper.
- Pilot09 implication: Use trace/profile diagnostics before redesigning the controller; compare learned operator choices against the classical adaptive selector.

### A Deep Reinforcement Learning-Based Adaptive Large Neighborhood Search for Capacitated Electric Vehicle Routing Problems

- source: `web` `https://ieeexplore.ieee.org/document/10660531/`
- authors/year: Chao Wang; Mengmeng Cao; Hao Jiang; Xiaoshu Xiang; Xingyi Zhang / 2024/2025
- finding: Recent EVRP work applies DRL specifically to ALNS operator selection.
- Pilot09 implication: Keep the rescue bounded to learning/search-control diagnostics before changing EVRP feasibility or cost semantics.

### A Reinforcement Learning Approach for Electric Vehicle Routing Problem with Vehicle-to-Grid Supply

- source: `web` `https://arxiv.org/abs/2204.05545`
- authors/year: Ajay Narayanan et al. / 2022
- finding: RL can be much faster than MILP/GA while staying within a quality gap, but it is not necessarily better quality.
- Pilot09 implication: Treat a DR result that is only near AlphaUCB as meaningful speed/learning evidence, not automatic quality dominance.

### Deep Reinforcement Learning for Solving the Fleet Size and Mix Vehicle Routing Problem

- source: `web` `https://arxiv.org/abs/2512.24251`
- authors/year: Pengfu Wan; Jiawei Chen; Gangyan Xu / 2025
- finding: FSMVRP DRL uses specialized embeddings for fleet composition and routing decisions.
- Pilot09 implication: Pilot09 should record whether the current 19-dimensional flat observation aliases fleet-mix states; if so, the next fix is richer state representation, not more PPO episodes.
