# DR-ALNS 突破地图（2026-07-05）

> 目标不是把 DR-ALNS 包装成 future-work，而是倒推一个真实、公平、可复现、能在 E2-E7 中成为最强主算法的工程路线。
> 本文不改代码、不改 `cost.py` / `check.py` / `evaluation.py` 语义，只定义证据、闸门、突破假设和执行顺序。

## 0. 总目标

DR-ALNS 必须最终满足四个条件：

1. **真实**：所有结果由统一 evaluator/checker 导出，零违约，保留 raw CSV / JSON / report / commit hash / worker 环境。
2. **公平**：DR-ALNS、ALNS、GA/VNS/SA/GWO/ACO/IWD/GLNS/LNS 等对手同问题、同约束、同评价器、同预算口径；训练集、验证集、测试集严格分离。
3. **最强**：不仅赢 SA，也要赢健康文献基线和 tuned non-DR ALNS/AlphaUCB/meta；如果某个维度不能赢，必须明确是哪一维、为什么、如何补。
4. **支撑论文**：E2-E7 都要有 DR-ALNS 的位置：E2 算法强度，E3 机制消融，E4 碳情景适应，E5 充电时刻，E6 收益公平，E7 动态滚动重规划。

## 1. 已知的已知（Known knowns）

### 1.1 项目真目标

- ReSETP 是绿色 VRP 论文工程：多车场、CV/EV、EV 非线性充电、时变碳强度、碳交易、收益公平、动态需求滚动重规划。
- 真目标不是“赢 SA”，而是 DR-ALNS 真训练、有创新、打过 GA-VNS/GA/PSO/ACO/VNS/LNS/GWO/IWD 等文献主流算法。
- M1 是论文正式数字唯一基准；x86/3060 是 DR 训练和相对评测机，不能和 M1 混绝对值。

### 1.2 M1 线仍是当前论文主线，且场景/参数/运营约束尚未完全收口

- E2-E7 的正式实验角色已定义：E2 算法比较，E3 机制消融，E4 碳情景，E5 两层减碳，E6 公平，E7 动态。
- M1 线后续围绕电池、车辆/车次、充电容量、混合带、基线健康等问题持续重构。旧“正式数字”在新参数或新语义下可能要作废重跑。
- 这意味着 DR-ALNS 还有重新进入主线的窗口，但必须跟 M1 的最终模型/场景契约同步。

### 1.3 x86 线不是废线，已经产出关键仪器修复和 DR 证据

- Track21 修复了 winner-kernel/SearchPolicy 车队上限漏传，证明旧的“winner 卡死/弱”部分是坏仪器。
- Track23 修后结果：DR 的 no-tuning parity 站住；learned-destroy efficiency 没站住；dynamic heuristic 没吃掉 information headroom。
- 这不是最终失败结论，而是告诉我们：**现有 DR 只会调 operator/meta，不足以成为论文突破；必须把动作空间推到机制层和动态层。**

### 1.4 当前 DR 环境的硬结构

- 当前 block env 观测是 24 维，动作主要是 destroy/repair/q/threshold/exploration，可选 candidate generator 和 search-control。
- 当前动作空间没有显式公平头、跨车场协同头、充电时刻头、动态 reserve/defer/preposition 头。
- 当前 dynamic reward 基本没有真实动态信号；没有 rolling/dynamic 字段时 fallback 到 best_gain，出现动态字段时也只返回 0。这意味着它不可能靠现有 reward 真学会 E7。

## 2. 已知的未知（Known unknowns）

1. **最终主场景未知**：M1 线还在确定电池容量、EV/CV 混合带、车辆/车次语义、车场充电容量、公共桩稀缺等运营约束。DR 训练场景不能脱离这个最终契约。
2. **DR 真 headroom 在哪未知**：operator selection 已多次近似持平；真正 headroom 可能在动态预判、充电时刻、跨车场协同、公平约束下的可行修复，而不是传统 destroy/repair。
3. **强对手强度未知**：基线必须先健康。不能再出现 120 eval 或 warm-start 原样返回导致的假胜利。
4. **E2-E7 每个模块中的 DR 角色未知**：不能只在 E2 赢一次；必须设计 DR 在 E3/E4/E5/E6/E7 中各自可解释、可测量的优势。
5. **训练算力边界未知**：全预算 16000 eval 训练太贵；必须用小/快课程、离线 oracle、蒸馏、surrogate、domain randomization，再在正式预算只做 held-out 评测。

## 3. 未知的已知（Unknown knowns：仓库里其实已经暴露但没被用满的东西）

1. **动态 reward 是空的**：当前 DR 说是 dynamic phase，但 reward 没有真正的动态状态价值，E7 不可能靠它突破。
2. **动作空间太低层**：只挑 destroy/repair/q/threshold，很容易天花板等于 tuned AlphaUCB/meta。要赢，必须让 DR 控制“机制动作”：是否预留 EV 续航、是否延期服务、是否跨车场调度、是否牺牲短期成本换公平/碳/未来需求。
3. **M1 线的运营约束变化可能正好创造 DR headroom**：当加入车场桩容量、车辆复用、收益公平、动态冻结状态后，静态 ALNS 的手调参数更难跨场景泛化，DR 的 regime-aware 控制才有价值。
4. **E7 信息成本是真池子，但现有启发式没吃到**：headroom 存在不等于动作有效。下一步不是直接训 PPO，而是先构造能吃 headroom 的非学习 oracle/启发式，再蒸馏给 DR。
5. **公平 E6 可能是突破口**：公平约束引入跨车场收益保留下界，普通 ALNS 可能会频繁破坏公平可行性；DR 可以学“公平余量安全动作”和“跨车场服务分配”。但前提是 Pi_d^0 / Pi_d / min ratio 已稳定导出。

## 4. 未知的未知（Unknown unknowns，需要防的黑天鹅）

1. M1 和 x86 代码分叉导致 DR 训练在旧语义上成功、迁回后失效。
2. E2 基线或 DR 对手再次出现“跑满但没动”“没跑满却计入”“warm start 原样返回”的假结果。
3. 训练/验证泄漏：用 E-UK100_01 或正式 E2/E7 测试集调参后再报胜利。
4. 场景机制没有 leverage：碳价/碳强度/充电容量/动态事件过弱，导致 DR 没东西可学。
5. DR 学到 reward hack：早停、少 eval、规避困难客户、牺牲公平/碳指标，只在单一 cost 上假优。
6. 对手被低估：GA/PSO/ACO/IWD/GLNS/LNS 如果没有各自合理编码、调参、预算和健康门，DR 的胜利不可信。

## 5. 重新定义 DR-ALNS：从“调算子”升级为“机制感知控制器”

DR-ALNS 不应再只是 operator picker。新定义：

> DR-ALNS = winner ALNS 搜索引擎 + 机制感知神经控制器，控制搜索在不同问题状态、碳情景、公平约束和动态事件下的动作选择与预算分配。

推荐动作头：

1. **Operator/meta head（保留）**：destroy/repair/q/threshold/exploration。
2. **Charging timing head（新增）**：候选充电时刻/站点/是否延迟到低碳 slot；只在 E5/E4 有信号时启用。
3. **Fleet/vehicle-type head（新增）**：CV/EV 转换、EV route eligibility、续航安全余量。
4. **Fairness head（新增）**：跨车场服务是否允许、保护哪个 depot 的 profit ratio、修复时优先插入哪个 depot 的客户。
5. **Dynamic anticipation head（新增）**：reserve capacity、commit/defer、vehicle preposition、阶段预算分配、是否保留 EV SOC 给未来事件。
6. **Regime/MoE gate（新增）**：根据规模、EV share、carbon cost share、fairness slack、dynamic event density 选择专家策略。

## 6. 突破假设（按价值排序）

### H1：动态 E7 是最大突破口

原因：E7 天然有 sequential decision，full-information static 与 rolling myopic 已有显著 information cost。普通 ALNS 每阶段重跑是 myopic；DR 可以学 anticipatory policy。  
前置条件：必须先有非学习 oracle/启发式能吃掉信息成本，否则 PPO 没老师、没动作、没奖励。

路线：
1. 固定 M1 最终场景后，生成动态事件族：低/中/高 event density，早/中/晚到达，空间聚集/分散，碳峰谷错位。
2. 对每个场景跑三类对照：full-information oracle、myopic rolling ALNS、handcrafted anticipatory heuristic。
3. 若 heuristic 能稳定降低 information cost ≥2-5pp，再做 DR imitation + PPO fine-tune。
4. E7 报告指标不只看 total cost：还看 information cost reduction、served/pending/cancelled、frozen route integrity、SOC reserve、fairness state inheritance。

### H2：E6 公平约束可制造 DR 差异化

原因：收益公平是论文独有机制之一，普通 ALNS/GA/VNS 不一定知道如何保 depot profit ratio。  
路线：
1. 先让 M1 完成 Pi_d^0、Pi_d、min ratio 导出。
2. 构造 fairness slack 特征：每个 depot 的 profit ratio gap、跨车场服务收益/损失、未来插入风险。
3. 训练 fairness-safe repair selector：优先选择不破坏公平余量的 insertion/cross-site service。
4. E6 中 DR-ALNS 目标：在高 theta 下保持可行率、少惩罚、少成本上升。

### H3：E4/E5 碳与充电时刻需要场景旋钮增强

原因：当前默认场景碳成本占比/充电时刻杠杆可能太弱；DR 没东西可学。  
路线：
1. 先做 scenario leverage table：carbon price、quota tightness、gamma amplitude、depot charging capacity、public station capacity。
2. 只在 carbon cost share 和 timing delta 达到阈值的场景训练 carbon/charging head。
3. 对照必须包括 naive charging、carbon-aware heuristic、winner ALNS、DR-ALNS。
4. 若默认场景弱，可把强碳场景作为 E4 sensitivity，而不是硬说默认场景 DR 碳显著。

### H4：E2 算法强度要靠“强底座 + DR 泛化/免调参/anytime”

原因：静态终值上，tuned non-DR ALNS/meta 可能很强。DR 的可写优势可能是：少调参、跨场景稳、短预算 anytime 更快达到好解。  
路线：
1. E2 至少报三组指标：final cost、time/evals-to-target、across-regime robustness。
2. tuned ALNS/meta 是强对手，必须纳入；不能只打默认 AlphaUCB。
3. DR 若终值只平手，但在多场景免调参、短预算达到目标快，可作为“学习型自适应搜索控制”贡献。

## 7. 必须重建的公平实验协议

### 7.1 数据切分

- Train：只用小/快合成实例和非正式 siblings，不含 E2/E7 正式测试实例。
- Validation：用于 checkpoint 选择和超参选择。
- Test：E2-E7 正式表，绝不回流训练。
- 每个 split 都记录 seed range、instance family、battery/charging/fairness/dynamic regime。

### 7.2 对手调参公平

- DR 允许离线训练，但不能用 test。非 DR 对手也要有 validation 调参机会。
- 比较对象至少包括：winner ALNS、tuned AlphaUCB/meta、SA、GA、VNS、GWO、ACO、IWD、GLNS/LNS、必要时 small-instance exact/lower bound。
- 任何基线必须过健康门：actual_evals/eval_budget、wall-clock、best update、solution hash、best<warm 或 VALID_BUT_WEAK 三态，不能把无效行当输家。

### 7.3 DR 判级

- `DR_WIN_REAL`：E2-E7 主指标均显著优于最强健康对手，或在 E2 final + E7 dynamic information-cost reduction 上形成论文主胜利。
- `DR_STRONG_PARITY_PLUS_MECHANISM`：终值与最强对手持平，但免调参/短预算/动态/公平至少两项显著更优。
- `DR_MECHANISM_ONLY`：只在 E4/E5/E6/E7 某机制场景有效，E2 静态不称最强。
- `HALT_NO_ACTION_HEADROOM`：非学习 oracle 都吃不到 headroom，禁止直接训练 PPO。

## 8. 执行路线图

### Phase 0：统一事实源与代码语义

1. 明确 M1 当前最终分支和 dr-x86 差异：哪些修复必须从 x86 port 回 M1，哪些 M1 参数/运营约束必须反向进入 x86。
2. 锁定 SearchPolicy/fleet/fleet-trip/charging capacity 语义。
3. 把所有旧 DR 报告标注：pre-Track21 contamination、post-Track21 clean、superseded。

### Phase 1：先找 headroom，不训练

对 E2-E7 分别做 leverage/oracle gate：

- E2：best static meta vs DR-relevant oracle selector 的上界。
- E3：机制层打开/关闭时，哪些动作真影响成本/碳/公平。
- E4：碳价/配额/gamma 是否产生决策翻转。
- E5：固定路线下 aware vs naive charging 是否有足够 delta。
- E6：fairness slack 是否导致普通 repair 高违约/高惩罚。
- E7：anticipatory heuristic 是否能降低 information cost。

无 headroom 的模块不训练；先改场景或动作。

### Phase 2：构建机制动作头

按优先级实现：

1. Dynamic anticipation head：reserve/defer/preposition/budget allocation。
2. Fairness-safe repair head：depot profit ratio slack aware insertion。
3. Charging timing head：low-carbon slot / station choice / delay charging。
4. Regime MoE gate：scale、EV share、carbon share、fairness slack、event density。

### Phase 3：训练方式从 PPO 单兵改为“三段式”

1. **Oracle/imitation**：用 cheap oracle、best-of-k、full-information、fairness-safe heuristic 生成标签。
2. **Contextual bandit/offline RL**：先验证状态特征能预测动作收益。
3. **PPO fine-tune**：只在已证明有 headroom 的动作面上微调，避免盲训。

### Phase 4：E2-E7 正式评测

- M1 出正式数字；x86 只训练模型和做相对预筛。
- 模型迁回 M1 后只做 inference + fixed evaluator。
- E2-E7 每个表都同时报告：DR、best non-DR、健康基线、显著性、预算、违约、数据 split。

## 9. 当前下一刀

不应该直接“再训一个 PPO”。下一刀应是：

1. **对齐 M1 最终场景契约**：电池、车次、充电容量、fairness baseline、dynamic runner 是否已定。
2. **补 DR 动作空间缺口审计**：列出 E2-E7 每个机制需要的 action head、obs feature、reward signal、oracle label。
3. **跑 headroom-first gate**：E7 dynamic 和 E6 fairness 优先；如果非学习 heuristic/oracle 能吃到 headroom，再训练。
4. **把 Track23 结论改写为“旧动作空间结论”**：operator/meta DR 只到 parity，不代表机制型 DR-ALNS 没希望。

## 10. 给 Codex 的硬约束

- 不许把旧 Track 的 HALT/MARGIN/WEAK 改写成胜利。
- 不许在没有 non-learning headroom 的动作面上直接 PPO。
- 不许用正式 test 调模型或选 checkpoint。
- 不许比较不同 evaluator/checker/worker/python/numpy 的绝对成本。
- 不许把 x86 绝对值放进论文表；x86 只负责训练和预筛，M1 负责正式数字。
- 每个实验必须有：metadata.json、raw_runs.csv、decision.json、artifact_hashes.json、report.md、commit hash、worker integrity。
