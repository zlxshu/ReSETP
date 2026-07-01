# Codex 提示词 20 — Track20：动态动作面「启发式 sanity」（先证动作能吃到 headroom，再谈训 DR）

> Claude 写定（2026-06-30）。Track18 Stage0 实测**动态 headroom 很大**(20/20 健康，mean `information_cost_pct=43.99%`)——但 `track18_policy_audit.md` + 代码证实**当前没有动态在线决策接口**(`_run_stage_plan` 纯 myopic、`_dynamic_reward` 遇动态 key 直接 return 0)。**所以先做非学习启发式 sanity：证明"预留运力/承诺-延后/车辆预定位"这类在线动作能不能真把 information_cost 降下来。降不动=这 43.99% 现有动作吃不到、训 DR 白烧；能降=DR 才值得建。本轮不训练任何 DR。** 冷启动自包含、自动、带闸、不谄媚、不拿"headroom 大"当"DR 有戏"。

## 0. 边界 + 过夜铁律（沿用 `10_*.md` §9）
不改 `cost.py/check.py/search/evaluation.py/winner_operators.py` 的评分/可行性语义；`dynamic.py` 可**新增 policy 回调钩子**(不改既有 myopic 求解与评分)；worker py313+NumPy2.3.5；只 x86 相对%；飞行前检查；墙钟≤6h；禁过夜 push/rebase/prune；只 force-add 小产物；每改动记"症状→出处→改哪→为什么"。

## 1. Stage 0 — 加最小动态动作接口（非学习）
给 `run_rolling_reoptimization` 加一个 **policy 回调**：在每个 rolling stage 决策点，允许一个外部策略函数注入以下**可解释动作**之一/组合（作用于 `_run_stage_plan` 的初始解/约束/承诺集，**不改 evaluate/check**）：
- **reserve_capacity**：给预期到达(add)预留部分运力(不满载承诺)。
- **commit / defer**：本阶段哪些已揭示客户先承诺、哪些延到下阶段。
- **vehicle_preposition**：把空闲/返程车辆预置到高到达率区域。
默认 policy = 现状 myopic（回调返回"照旧"），确保零改动时结果与 Track18 一致（回归验证）。

## 2. Stage 1 — 启发式策略跑 headroom 场景（不训练）
用**手写启发式**实现上面动作（如：按历史 add 率预留 X% 运力；对时间窗宽松客户 defer；按事件热力预定位），在 Track18 那 20 个 headroom 场景(25/50c、同 seed、同事件流)上跑，与 **myopic 基线**同口径比 `information_cost` 与总成本。每场景零违约、健康字段完整。

## 3. Stage 2 — 判级（决定 DR 值不值得建）
- `HEURISTIC_MOVES_HEADROOM`：启发式动作使 mean `information_cost` 显著下降(如相对 myopic ≥+3%、多场景一致、零违约) → **在线动作确实能吃到 headroom** → DR 值得建(下一步接 PPO 学更优策略)。
- `HEURISTIC_FLAT`：启发式动作降不动 information_cost(±) → **这块 headroom 现有动作面吃不到**(可能是全信息不可达/承诺不可逆/预算协议造成的不可约损失) → **训 DR 无意义**，先重想动作面或诚实记 DR future-work。
- 报告须拆分：information_cost 里**多少被启发式减少了**(可约) vs **剩余**(暂不可约)。

## 4. 交付物
`track20_action_sanity_report.md/json`(动作接口说明 + 启发式 vs myopic 的 information_cost 变化 + 可约/不可约拆分 + 判级 + 人话"在线动作能不能吃到那 43.99%、DR 值不值得建")、`track20_rows.csv`、回归证明(默认 myopic 回调=Track18 结果)。

## 5. 资料顺序
先读 HANDOFF + `dynamic.py`(rolling/`_run_stage_plan`/information_cost) + `track18_policy_audit.md`/`track18_headroom.csv` + 动态 VRP anticipatory 文献(Ulmer 等：哪些 information gap 可被在线策略约减)。先加接口→启发式 sanity→再谈训 DR；不拿"headroom 大"或欠训当赢、不谄媚。
