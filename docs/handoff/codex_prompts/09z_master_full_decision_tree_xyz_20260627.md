# 09z（主控/Goal 模式）— 一次跑完整棵 X/Y/Z 决策树

日期：2026-06-27　提出：Claude　执行：Codex　决策权：user
> user 指令："xyz 全部都去测试，连同 09y。" 即：跑 09y 定性后，**不要停在某个 verdict**，把 X / Y / Z 各自指向的下一步实验**全部执行**，最后给一个完整收口结论。
> 设计原则：**便宜诊断在前、昂贵搜索在后、每阶段独立 HALT**，避免无谓烧算力。每阶段产物独立落盘、独立 commit。

## 0. 先读 + 铁律（每阶段都适用）
- 读 `HANDOFF.md` + `docs/handoff/memory/`（必读 `alns-crush-root-cause.md`）+ 09v/09w/09x/09y 报告。
- **禁改 `cost.py`/`check.py`/`evaluation.py` 语义、`prices.py` 默认值、TeX。** 电池/场景一律**内存 override**（09w 已把 prices 贯通进搜索，勿回退）。
- 碳价钉死 0.05034；系统 py313/numpy2.3.5/`PYTHONHASHSEED=0`；数字绑 commit。
- 诚实优先：smoke/Stage A 非 T3；造不出/不闭合就 HALT 并写清原因；人话先行、结论分层。
- **完成后把 09v/09w/09x/09y/09z 提示词一并 `git add` 提交**（user 反映未跟踪文件找不到）。

---

## 阶段 0（便宜，必跑）= 09y 构造+经济测试
按 `09y_ev_feasibility_economics_construction_test_20260627.md` 执行：代表大算例（vanilla/multidepot/threeshift 150c-01、200c-01）构造 EV-maximal 可行解，评 cost/carbon，与全-CV 比，逐条记失败原因（续航/时窗/站容量）。产出**每实例** verdict ∈ {X 搜索找不到 / Y 真不划算 / Z 80kWh 造不出}。
> 阶段 0 是后续的指南针，但**两条轨都要跑**（见下），因为它们对论文都有信息价值。

---

## 阶段 1（Track A，对应 X 假设）= Goeke80 EV-seeded 暖启动重测
检验"大算例 EV 塌缩是不是搜索锚死在全-CV warm start"：
1. 用阶段 0 的 EV-maximal 解作 **EV-seeded 暖启动**（或给 `make_shared_initial_solution` 加 EV 播种选项，保留无播种默认护锚）。
2. 从 EV-seeded 起点，等墙钟重跑 **`alns_e2_carbon`(含 vehicle_type_swap+碳算子) vs LNS**，大算例 gradient（75-200c）× seeds1-3。
3. 测三件事：(a) 搜索结束 EV route share 是否**留得住**（vs 从全-CV 起 ~6%）；(b) ALNS 是否**因此甩开 LNS**；(c) 碳算子 best-improvement 次数是否**因 EV 在场而上升**（对照 09x 的 8/14万）。
- **判决**：EV 留得住且 ALNS 显著胜 LNS → **A_SEARCH_GAP_CONFIRMED**（Goeke80 混合故事+算法贡献靠暖启动救活）；EV 又塌回 ~6% → **A_NOT_SEARCH**（不是搜索问题，是经济，转 Track B/叙事）。

---

## 阶段 2（Track B，对应 Y/Z 假设）= 现代电池 regime 重测（EV 真在场处）
检验"换到 EV 真划算的 regime，ALNS/碳算子是否终于有用武之地"。**电池为内存诊断 override，不动默认、不写 TeX**（若日后定为论文场景，再走单独的 TeX/prices/bib/来源更新门）。
1. **闸 0 容量头寸（先做，零成本）**：读各大算例 `num_ev × max_trips / 所需总 route`，确认现代电池下硬上限**允许** EV ≥ 20%（否则 cap 封死，记 `B_CAP_BOUNDED` 并说明）。
2. **现代电池构造测**：在 280kWh（09h 现代卡车证据值）下重跑阶段 0 的 EV-maximal 构造——EV 是否变可行/划算（对照 80kWh 的 Y/Z）。
3. **算法对比（EV 在场）**：280kWh 下等墙钟跑 **`alns_e2_carbon` vs `alns_e2_carbon_ablation`(碳消融) vs LNS vs GA/PSO/VNS**，大算例 × seeds1-3，Wilcoxon。**此时 EV 真在场**，看：(a) ALNS 是否显著胜 LNS/GA/PSO；(b) **碳消融 on/off 是否终于显著**（对照 09x 在全-CV 下的 WEAK）；(c) EV route share / 低碳充电占比。
- **判决**：ALNS 胜且碳消融显著 → **B_MODERN_REGIME_WORKS**（混合故事+算法贡献的家在现代电池场景）；EV 在场但 ALNS 仍只平 → **B_MECHANISM_BUT_TIE**（算法贡献转 DR-ALNS）；现代电池也撑不起混合 → **B_NO_MIX_ANYWHERE**（改叙事：电气化→EV 主导/CV 主导，混合仅受约束场景）。

---

## 阶段 3 = 收口综合（必写）
汇总阶段 0/1/2，回答三个问题并给**单一推荐**：
1. **混合故事的家在哪**：Goeke80（靠暖启动救活，A_SEARCH_GAP）还是现代电池场景（B_MODERN_REGIME_WORKS）还是不存在（改叙事）。
2. **算法贡献成不成立**：哪个 regime 下 ALNS 显著胜 LNS/GA/PSO + 碳消融显著；不成立则明确转 DR-ALNS。
3. **下一步正式实验**：选定 regime → 正式 T3（含 8 基线）+ 若选现代电池则走 TeX/prices/bib/来源正式化门。
- 诚实兜底：若全部为 tie/no-mix，明确写"vanilla ALNS 在本问题是强基线非碾压者，算法创新主线=DR-ALNS；混合故事=受约束/现代电池场景"，不注水。

## 4. 验收
- 每阶段独立报告（人话先行、证据分层、判决明确）+ 独立 commit + HANDOFF `[M1]` run log。
- 阶段 1/2 等墙钟、0 采集失败或诚实 HALT_COLLECTION_COST、10/统计口径、零违约、py313 worker、prices 进搜索。
- 回归测试相关项全过；护锚（100-01 £4878 逐位、不漂）。
- 末尾把 09v-09z 提示词 git add 提交。

## 5. 不要做的事
- 不碰保护文件/默认参数/碳价/TeX（现代电池仅诊断 override）。
- 不把 smoke/Stage A 当 T3；造不出/不闭合就 HALT。
- 阶段 1 若 A_NOT_SEARCH、阶段 2 若 B_CAP_BOUNDED，**不要**硬凑，如实记并继续下一阶段。
- 不堆术语；先人话后标签。
