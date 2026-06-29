# 09x（已更正重写）— 造「碳感知 ALNS 算子」作为真算法创新，再公平对比

> ⚠️ 本文件更正了同名旧稿。旧稿前提（"winner kernel 缺 vehicle_type_swap、补通用算子+局部搜索"）**是错的**：
> - `vehicle_type_swap` 当前**已在** winner_operators.py:39/135（旧稿因 grep 漏看误判为缺失）。
> - 局部搜索/路线消除**已做消融、证明有害、已默认关闭**（见 `docs/handoff/memory/alns-crush-root-cause.md` 第24行）。
> - 项目自己早已定论（同记忆第27行）：winner kernel 只是"正确实现的标准 ALNS，靠实现非新颖取胜"，**算法创新必须来自「碳感知算子」或 DR-ALNS**。
> 故本步不再堆通用算子，改为执行项目自己定的、但**从未动手**的创新：碳感知搜索算子。

日期：2026-06-27　提出：Claude（已亲读代码+Zotero/网络文献+22KB根因记忆）　执行：Codex　决策权：user

---

## 0. 先读 + 行为铁律
- 完整读 `HANDOFF.md` + `docs/handoff/memory/`（**必读** `alns-crush-root-cause.md` 全文，理解"通用调优已穷尽、创新=碳感知/DR"）；读 `CLAUDE-FABLE-5.md`/`AGENTS.md` 诚实/克制/不谄媚。
- **禁改 `cost.py`/`check.py`/`evaluation.py` 语义。** 允许新增碳感知算子（在 `alns_wouda.py` 旁或新文件），并接入 `WinnerOperatorSet` 的**新标签变体**。
- 碳价钉死 `0.05034`；`Q=3650,B=80,v=25`；prices 已贯通搜索（09w，勿回退）；系统 py313/numpy2.3.5/`PYTHONHASHSEED=0`；数字绑 commit。
- 诚实优先：smoke/Stage A 不当正式 T3；拿不准/不闭合就 HALT；报告人话先行、结论分层、开头复述目标。

## 1. 目标（一句话）
**造一组「碳感知」destroy/repair 算子**，让 ALNS 在搜索过程中（而不仅在末尾算分时）利用两层碳 + 时变碳信号导航，验证它能否：(a) 在时变碳下把 EV 价值真正搜出来（缓解大算例 EV 塌缩），(b) 公平胜过碳盲的 LNS/GA/PSO，(c) 用**碳消融**证明增益来自碳感知（非 cost）。

## 2. 为什么这是对的方向（自包含证据）
- **通用算子已穷尽**：当前 6 destroy（random/worst/shaw/whole-route/route-segment/vehicle_type_swap）+3 repair（greedy/regret2/regret3）齐全；局部搜索/路线消除消融有害已关。再堆通用算子无意义。
- **碳目前只进目标、不进搜索**：算子实现 `alns_wouda.py`，碳仅通过 `evaluate(..., context.carbon_profile, ...)`（:846）进入被打分的目标；`worst_customer_removal` 按**成本**移除、`shaw_related_removal` 按距离/时间/需求、充电插入**可行性优先**——**无一用碳/时变碳做选择**。
- **碳信号可用**：`EvaluationContext.carbon_profile`（evaluation.py:49）+ worker metrics 已暴露 `E_cv_direct/E_ev_indirect/E_total/cost_carbon/carbon_quota_kg`（见根因记忆/09a audit）。碳感知算子**可建**。
- **数据动机**：09w 显示 10c（EV 活跃）ALNS 赢 LNS −30%，但 75-200c 全平、EV 塌到 ~6%；时变碳下 EV 的优势本应来自"低碳时段充电"，而当前充电算子碳盲，没在用这一点。
- **文献支撑**：Goeke-Schneider 2015（基准来源，ALNS）；Demir-Bektaş-Laporte 污染路由 ALNS（排放感知算子先例）；Keskin-Çatay 2016（站算子）；EJOR 2024 算子综述。ALNS 是 EVRP SOTA，非花瓶；缺的是**问题专属（碳）感知**这层。

## 3. 要造的碳感知算子（最小集，每个挂动机）
1. **worst-carbon removal**：移除"单位服务碳贡献最高"的客户/路段（长柴油腿的 `E_cv_direct`，或被迫在高碳时段充电的 EV 腿），对照现有 worst-**cost** removal。
2. **carbon-relatedness Shaw removal**：在现有 shaw 相似度（距离/时间/需求）上**加一维碳/时段耦合**，聚簇碳相关客户一起移除重排。
3. **low-carbon charging (re)insertion**：充电插入/平移算子，把 EV 充电**调度进低碳时段**（用 `carbon_profile` 选 slot），对照现有可行性优先充电。这是时变碳下 EV 价值的直接来源。
4. （可选）**carbon-biased vehicle_type_swap**：在"充电可落进低碳窗"的路线上优先 CV→EV，给已有 swap 加碳偏置。

实现要点：复用 `context.carbon_profile` 与现有 `_best_station_insert`(charging.py:490)；新算子返回 `actual_evals_added` 据实累加；不改目标/可行性语义（cost/check/evaluation 不动）。

## 4. 隔离与护锚（别砸正式数字）
- 碳感知算子只进**新标签变体**（如 `alns_e2_carbon`），**不改** canonical winner kernel 默认行为；100-01 锚 `4878.331796187524` 逐位冻结（闸 A，不符即 HALT 回滚）。
- 承 09w 闸 B：搜索 context 的 `prices.B_battery_kwh` 等于 override；固定 EV-heavy 解 80 vs 280kWh check/evaluate 不同。

## 5. 公平对比 + 碳消融
- 同 `evaluate/check`、同暖启动、等墙钟、10 seed、Wilcoxon、零违约、py313 worker。
- **碳消融（关键，证明创新来源）**：碳感知算子 **on vs off** 对照，看增益是否来自碳感知；并报每实例 EV route share / 低碳时段充电占比 / 碳排，证明机制真起作用（非 cost 取巧）。
- 对比集：先 `alns_e2_carbon` vs `alns_e2_throughput`（碳盲基准）vs LNS；过了再加 GA/PSO/VNS/GA-VNS。

## 6. 可证伪判决（预注册，三条路都干净）
- **PASS_CARBON_AWARE_OPERATORS**：碳消融显示碳感知算子带来显著增益，且 `alns_e2_carbon` 在时变碳口径下显著胜碳盲 ALNS 与 LNS（Wilcoxon p<0.05），同时大算例 EV/低碳充电占比上升 → **真算法创新成立** → 进正式 T3 + 扩 GA/PSO/VNS。
- **WEAK_CARBON_SIGNAL**：碳感知算子增益不显著或仅打平 → 碳感知搜索此问题增益薄 → 算法创新主线转 **DR-ALNS**（探针 PROMISING），ALNS 诚实定位"正确实现的强基线 + 机制差异化"。
- **REAL_DEGENERACY**：即便低碳充电算子也救不起大算例 EV → EV 大规模真不经济 → 诚实改叙事（电气化→EV 主导；混合仅受约束场景）。

## 7. 验收 + 报告
- 闸 A/B 证据；碳消融 on/off 表；Stage A/B 闭合或诚实 HALT；判决给 §6 之一。
- 回归测试 `test_cost/test_check/test_search/test_e2_alns_throughput/test_metaheuristic_baselines` + 新算子单测全过。
- 报告人话先行、结论分层；引用 Goeke-Schneider 2015 / Demir 污染路由 / Keskin-Çatay 2016 / EJOR 2024 综述。
- 产物 commit；HANDOFF 追加 `[M1]`：造了哪些碳感知算子、碳消融结果、判决、下一步。

## 8. 不要做的事
- 不再堆通用算子/不重开局部搜索-路线消除（已消融有害）。
- 不碰 cost/check/evaluation；不让 100-01 锚漂；不回退 09w。
- 不为出 PASS 调碳价/来源外电池/藏违约；不把 smoke/Stage A 当正式 T3。
- 不堆术语；先人话后标签。
