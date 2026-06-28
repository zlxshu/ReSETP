# DR-ALNS 升级方案蓝图：学习型破坏 + 碳感知控制，跑在全富 EVRP

> Claude 主线方案（2026-06-28，文献+源码彻底精读后定）。目标=救活拉垮的 DR-ALNS，使其成为论文领跑算法、能讲故事。**本文件是设计蓝图，不是 Codex 提示词**；执行分阶段、先小验后大投。证据与来龙去脉见 `HANDOFF.md` 2026-06-27/28 变更日志 + 记忆 [[dr-alns-winning-strategy]]。

## 0. 一句话
把 DR 从「在 6 个固定算子里挑」升级为「用神经策略**学习该拆哪些客户/哪块区域**(learned destroy) + 控**碳感知充电/出发时刻**」，配强军火(FRVCP 最优充电插入 / SISR / regret+2-opt)，跑在你独有的**全富 EVRP**(两层时变碳+EV非线性充电+公平+动态+混合CV/EV+多车场+时间窗)上。对通用场(GA/PSO/蚁群/水滴/VNS/AM)拉 ≥10%，小规模对精确解证近最优。

## 1. 为什么这么设计（决定性因素，链回证据）
- **DR 拉垮根因**：现 DR=「选算子/调权重」，上限≈调好的 ALNS（Reijnen +2%、我们 Pilot17 +0.57%、Cao 源码硬编码"DLNS 赢不了 ALNS 就 raise"三方实锤）。**必须升级动作空间，不能再选算子。**
- **差距来源**：富问题 × 强军火 × 比对象弱。富问题上通用基线离最优远 → 可拉 10-27%（周鲜成对 ALNS +9.7%/VNS +16.7%；本校谭云洁对 GA/ALNS/AM −27.6%）。
- **学习型破坏是 DR 真能超手搓 ALNS 的唯一已验证途径**（NLNS=学修复、NeuOpt=学 k-opt 移动；2024 NCO 综述点名"神经-OR 混合"+"富约束变体"为前沿，且**全文不提 EV 充电=国际空白地**）。

## 2. 架构（四层）
- **L0 强搜索基座**：winner kernel ALNS（已有，碾 SA 8.76%）+ **FRVCP 最优充电插入** + **SISR 字符串破坏**。
- **L1 学习型破坏（核心创新）**：per-customer 特征 → 注意力/指针策略 → 选 destroy 客户子集 → 交强 repair(regret2/3+2-opt)+FRVCP。借 NLNS/NeuOpt 的 region-select。
- **L2 碳感知/搜索控制（你独有）**：DR 控充电/出发时刻(卡电网最清洁时隙充电)、破坏规模、接受阈值。
- **大规模(150/200c)**：GLOP 式 cluster-first 分解 → 子问题跑 L1/L0 → 合并。

## 3. 精确接口设计（对着我们 `block_env.py`/`worker` 的改动）
现状：`BlockAlnsEnv` 动作=`MultiDiscrete`(destroy下标∈`BLOCK_DESTROY_IDS` + q/threshold/exploration + candidate-gen + search-control)；obs=24维汇总；`decode_block_action`→`client.block_step`→worker(py313)跑 block_size 迭代→返回 metrics/trace；reward=`_reward`；已有按状态掩码算子(GIRE 雏形)。

**改动（learned destroy）**：
1. **worker 吐逐客户特征**：现 worker 只回 24 维汇总；新增返回 `per_customer_features`（N×F 矩阵）。每客户特征(富问题给的弹药，比 CVRP 多)：坐标、demand、时间窗(早/晚/松紧)、所属车场、是否 EV 服务、距最近充电站、所在碳时隙强度 γ_t、该车场 profit(公平信号)、当前路线位置/前后弧成本、是否在长弧上。
2. **policy 加指针/注意力头**：现策略是定长 MultiDiscrete MLP；新增对变长客户集的 attention/pointer 头，对每个客户输出"移除分"→ top-k 或采样得 destroy 子集。(q_ratio 改由策略隐式决定移除数，或保留为粗控)
3. **新增"按给定集合移除"destroy 算子**：worker 端加 `remove_given_customers(ids)`，配现成强 repair(regret)+FRVCP。L1 即"策略选集合→worker 执行移除+修复"。
4. **约束处理用 GIRE 思想**（不靠硬掩码）：允许暂时不可行(电量/TW 超)，用我们已有的 `penalized_obj` BIG_M 罚——**我们 evaluation.py 天然就是 GIRE 那套**，让策略学会跨可行/不可行边界(NeuOpt 证明这比硬掩码强)。保留现有轻掩码做明显非法剪枝。
5. **训练**：复用 `train_async_block_ppo`(PPO+异步)框架；reward=Δbest 改进量+终局 gain(已有)；entropy 防塌缩(已有)；课程 route→energy→carbon(已有)。**注意**：之前 search-control 学成"早停套利"(Pilot17)，learned-destroy 后 reward 要确保"持续产出有效候选"被奖励、早停不套利。
6. **repair/charging 保持强**：regret2/3 + 2-opt(已有) + **FRVCP 最优充电插入**(从 Cao `RH`/`FH_complex` 或 Goeke FRVCP 借，替换现 RH 启发式)。

## 4. gap-maker 军火清单（来源）
| 军火 | 作用 | 来源 |
|---|---|---|
| 学习型破坏(pointer/attention 选客户) | DR 真超手搓 ALNS | NLNS/NeuOpt/师瑞阳/谭云洁 |
| FRVCP 最优充电插入 | EV 质量真增益 | Cao 代码 RH/FH_complex、周鲜成、Goeke |
| 碳感知充电/出发时刻 | 卡电网清洁时隙=你独有两层时变碳 | 周鲜成(躲拥堵同思路)；本项目机制 |
| SISR 字符串破坏 | 强破坏 | Cao 代码 string_removal、Christiaens2020 |
| GIRE 可行/不可行探索 | 硬约束处理 | NeuOpt；我们 penalized_obj 已支持 |
| GLOP 式分解 | 大规模 150/200c | GLOP AAAI24 / L2D |
| 公平/跨车场/多趟 算子 | 你机制变算子 | 本项目 |

## 5. 验证设计（"领先第二名 10%"在此落地）
- **主擂台**：DR-ALNS vs GA/PSO/蚁群/水滴(IWD)/VNS/AM(**正常发挥不削弱**) on 全富问题 50-200c → 目标平均 ≥10%、每规模 ≥0。
- **可信度锚**：小规模 5/10/25c vs 精确解 CPLEX/branch-price(李得成模板) gap→0(堵"只赢弱鸡")。
- **消融(证每个 gap-maker)**：①learned-destroy vs operator-select(证学习型破坏增量)②全军火 vs 去FRVCP/去碳感知(证各 gap-maker)③vs 强 winner kernel(诚实小幅增量+省迭代)。

## 6. 论文故事（能吹且不虚）
*首个把「学习型破坏(neural destroy) DR-ALNS」做到「两层时变碳+EV非线性充电+公平+动态」全富 EVRP 的工作；正落在 NCO 综述点名的两大前沿(神经-OR 混合 + 富约束变体)的**国际空白地**(综述全文不提 EV 充电)；小规模经精确解验证近最优，全富问题对 6 个主流元启发平均领先 ≥10%，碳感知机制额外省 X% 碳。*

## 7. 风险 + 分阶段（先小验后大投，别重蹈烧夜训覆辙）
- **阶段 A（不烧大算力，验核心假设）**：实现 ①worker 逐客户特征 ②policy 指针头 ③remove-given-set 算子 ④GIRE 罚；**小规模 25/50c** 训练+评测，验证 **learned-destroy 真 > operator-select、且对 GA/PSO 拉开、对精确解 gap→0**。这是去/留的分水岭。
- **阶段 B（A 验证有效后）**：补 FRVCP + 碳感知时刻 + GLOP 分解；全规模 50-200c 训+评+消融。
- **诚实 caveat**：神经法质量多在简单题追平、赢在速度；我们靠"富问题拉通用场 + 小规模证近最优"两条腿。learned-destroy 是国际已验证方法，但在富 EVRP 上要自己调通(状态特征、reward 防早停套利、变长指针头的 PPO 稳定性)。
- **铁律不变**：不改 cost/check/evaluation/winner 语义；worker py313/numpy2.3.5；只 x86 相对；先证据后单点改动再短测；烧大算力前必过阶段 A。

## 8. 下一步
解除暂缓后，写**阶段 A 的 Codex 提示词**：worker 逐客户特征 + remove-given-set 算子 + policy 指针头 + GIRE 罚 + 25/50c 小验证(learned-destroy vs operator-select vs GA/PSO + vs 精确解 gap)。**先把"学习型破坏真比选算子强"这个核心假设用小算力证了，再决定全量投入。**
