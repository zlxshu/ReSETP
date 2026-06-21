# 提示词⑨ — E2：把主算法 ALNS 强化到文献最优形态（阶段②）

> 先读 `HANDOFF.md` + `docs/handoff/memory/baseline-algorithm-catalog.md` + `docs/handoff/memory/alns-crush-root-cause.md`。M1 系统 Python、`codex/reporting-pipeline` 分支。**本阶段依赖阶段①的 69 算例已生成。**

## 为什么要做（实证根因，别当成调参）
03 HALT 体检发现：在“全油车最优”的算例（如 L-main）上，**LNS 基线赢了我们的 winner ALNS 5.4%（10/10 seed）**——LNS 收敛到全油车（£7882），winner 与公平 SA 都卡在电车重的解（£8330/£8320）。路线数两者相同（~64），差别在**车型**。读码确认：`alns_wouda.py:589 vehicle_type_swap` 已是**双向**（CV→EV + EV→CV 都试），所以**不是方向问题**；瓶颈是**单路线 swap + 纯爬山（HillClimbing）跳不出电车局部最优**，而 LNS 的大邻域整批重建能做全局跳变。`WinnerKernelConfig.include_route_elimination` 默认 `False`（路线消除算子默认不启用）。

**目标**：把 ALNS 强化到**文献最优形态**，使它在全油车最优的算例上也能摸到全油车盆地（追平/超过 LNS），并在 69 算例上整体稳居第一梯队。**所有强化点必须来自文献、不得自创**（user 铁律）。

## 设计来源（照抄/适配，禁止自创）
- **经典 ALNS**：Ropke & Pisinger 2006（自适应算子选择：权重轮盘+评分 σ1/σ2/σ3、反应因子；SA 接受；noise）；吴廷映2023 [4MNLGZZF]（destroy=Shaw 相似 R=α·dist+β·time+γ·|l_i−l_j| + random；repair=greedy+regret；w=(1−δ)w+δπ/θ；15000 迭代）。
- **大邻域到全油车的关键**：高娇娇2024 GLNS [TAQUPN3F]（扫描构造 + LNS：random/相似 removal、最远/后悔 repair + SA 接受）——LNS 正是靠“整路移除→后悔重建”摸到全油车。把这套**大 q + 车型感知重建**能力补进 ALNS。
- 仓库现成算子在 `solver/src/setp_solver/search/alns_wouda.py`（`vehicle_type_swap`/`whole_route_removal`/`route_elimination_removal`/`shaw`/`greedy/regret2/regret3` 等）+ `winner_operators.py`（`WinnerOperatorSet`/`run_winner_kernel`）。**复用现成算子原材料，按文献组合，别重造。**

## Phase 0 — 诊断（先报告再改）
- 取阶段①里若干“全油车最优”的算例（先在 vanilla/multidepot 的中大规模上找，用 cv_only vs ev_only vs mixed 三策略快验哪些是全油车最优）。
- 复现“winner 卡电车 / LNS 到全油车”，**对照两者搜索轨迹**：winner 为什么 `vehicle_type_swap`+`whole_route_removal`+regret 重建后仍停在电车？是 q 太小（一次只动 1-2 路线）/ 接受准则（纯爬山过不去山脊）/ 还是 regret 重建偏好把客户塞回电车路线？给出实证结论。
- 输出 `baselines/e2_alns/diagnosis.md`。

## Phase 1 — 强化（照文献组合，逐项可开关 + 记 flag）
按诊断结论，从下列**文献组件**里组合（每项做成 flag、默认状态由 Phase 2 消融定，别一次全开）：
1. **自适应大 q**：destroy 规模随阶段自适应放大（Ropke-Pisinger/吴廷映），使一次能清空多条路线、触发车型重指派。
2. **车型感知 / 成本感知 repair**：regret/greedy 重建时按**真成本**（含 cost_fix、fuel vs elec+occ、两层碳）选车型与插入位，而非纯距离——直击“修复盲目塞回电车”。
3. **路线消除大邻域**（`route_elimination_removal`，`include_route_elimination=True` 重新评估）：移除最弱整路、强制重分配，仅当总成本下降才接受。注意：旧 V2 消融曾判它“有害”，**必须在新 69 基准上重测，不得照搬旧结论**。
4. **真自适应算子选择**（Ropke-Pisinger 轮盘权重 + σ 评分 + 反应因子），替代固定 AlphaUCB（若诊断显示算子选择是瓶颈）。
5. **接受准则**：SA(Metropolis) 或 RRT/LAHC（吴廷映用 SA），让搜索能过山脊到全油车；纯爬山作为对照保留。
6. **嵌入式局部搜索**（2-opt/Or-opt/relocate，复用 `improve_solution_locally` 或 candidates 现成）精修。

## Phase 2 — 消融 + 定稿（数据说话，诚实）
- 在阶段①的 69 算例（或代表性子集 + L-main）上，对每个组件做**加入/移除消融**，记 best/mean/std + 是否反输 LNS。**只保留实证有益的组件**，有害的诚实关掉并记录（别因为“文献有”就硬留）。
- 验收标准：定稿版 ALNS 在“全油车最优”的算例上**不再被 LNS 系统性击败**（追平或更优），在有余量的算例上仍领先公平 SA 与中弱基线；全程零违约。
- **确定性**：定稿版在系统 Python + `PYTHONHASHSEED=0` 下同 seed 同结果（内部确定）。

## ⚠️ 扩散影响（必须在报告里写明）
winner ALNS 是 E1–E7 全程的 PRIMARY 算法。**一旦强化，commit `9da7f8b` 锁定的全部正式数字（£4878 锚、E1–E7、表图）都需重跑**。本阶段**只交付强化后的算法 + 消融证据 + 新基准下的内部确定性**；E1–E7 的统一重跑是后续单独任务，本阶段不做、但报告要提示“下游需重跑”。

## 边界
- 禁改 `cost.py`/`check.py`/`evaluation.py` 语义（唯一真值源）。强化只动 `alns_wouda.py`/`winner_operators.py` 等算子/选择/接受层。
- 不自创算法：每个组件标注文献出处（Ropke-Pisinger / 吴廷映 / 高娇娇）。
- 系统 Python 金标准环境；每组件/数字绑 commit；测试过；跑不出诚实 HALT 不注水。

## 交付
`baselines/e2_alns/{diagnosis.md, ablation.md, final_report.md}` + 强化后算子代码 + 单测 + 消融数据 + 多次 commit（写 hash + 各组件 flag 默认值 + 文献出处）。
