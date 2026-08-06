# D3 对抗性根因评审

- 任务编号：`D3`
- 终态：`D3_ROOTCAUSE_REVIEW_COMPLETE`
- 证据口径：只读复算与文献页码核对；未改代码、TeX 或 `baselines/`。

## 结论先行

| 问题 | 二选一判定 | 判据与最短理由 |
|---|---|---|
| E5 非线性充电 | **顶层设计** | 研究主张要求“曲线改变路线决策”，但冻结的“原车型能耗口径 × China81 见证路线”使 1040 条路线的耗电仅占电池 `11.767884%--85.780126%`，没有一条耗尽一块电池；原规则和 `max_coverage` 都产生 `0` 次公共站机会。换用已有文献的 95 km 续航参照后，同一批路线却有 `425/1040` 越界，故不能归因为“中国业务本来没有这种条件”。出处：`baselines/china_e3_e7/e5_enroute_nonlinear_20260801/b2_opportunity_audit_20260801/raw_runs.csv` 的 `route_count=1040`、`route_soc_pct` 极值和 `just_enough_public_stops=0`；同目录 `decision.json`；`b2_wang95_range_opportunity_20260801/decision.json` 的 `routes_over_95_km=425`、`share_over_95_km=0.40865384615384615`；Wang et al. (2026) PDF pp. 24, 26--27。
| E7 动态订单 | **顶层设计** | O1 的两个失败单元在触发时已经越过硬时间窗最迟发车时刻，搜索不能让时间倒退；O2 的人民币经济发车规则在研究问题冻结前没有先取得同语义、同单位、可移植的等待损失系数。真实业务里存在赔付、复购和销售后果，缺的是当前模型所需的人民币连续系数，不是“业务没有等待损失”。出处：`baselines/china_e3_e7/e7_o1_replanning_20260801/failure_diagnosis_20260801/decision.json` 的 `failure_classification=HARD_CONSTRAINT_INFEASIBLE_AT_TRIGGER`、`higher_budget_can_rescue_current_stage=false`；`docs/handoff/waiting_loss_evidence_20260802/done.json` 的 `candidate_count=15`、`usable_count=0`；同目录 `report.md` 第 10--16 行所列证据语义。
| 论断 R | **部分成立** | 两组的根因分类和“事前未检验机制显形条件”成立；但 R 把“15 个候选中 0 个可用”扩大成了文献对全世界的“不存在证明”，又把一个不存在且被相邻证据反驳的 E3 记录计作前次发作。因此 `third_occurrence=false`。

## 第一部分：逐组判据与回答

### E5

**FACT 1：原车型下没有途中补电的必要区间。** `b2_opportunity_audit_20260801/raw_runs.csv` 共 `1040` 行路线，独立复算得到 `route_energy_kwh=9.094221001679287--66.29088100604332`，除以 `77.28 kWh` 后 `route_soc_pct=11.767884318943176%--85.78012552541837%`。同目录 `decision.json` 记录 `route_count=1040`、`routes_over_85_pct=1`、`just_enough_public_stops=0`、`max_coverage_stop_saving_routes=0`；`report.md` 第 3--5 行确认原车型、77.28 kWh 和零公共站机会。这回答 (a)：1040 条路线耗电占电池比例的完整区间为 **11.767884%--85.780126%**，最高值仍低于 100%。

**FACT 2：低成本诊断不是崩溃或非法解。** `b2_low_cost_diagnostic_20260801/decision.json` 为 `row_count=4`、`ok_row_count=4`、`all_rows_retained=true`。其 `raw_runs.csv` 中 50c 和 100c 的 L100/M17 对分别具有完全相同的 `route_hash`，`public_charging_action_count=0`、`public_actions_over_85pct=0`、`violation_count=0`；总成本仅为 `3201.7645881707813` 对 `3201.7644879827817`、`6329.992480685919` 对 `6329.992280309919`。这排除了“预算不足或程序报错造成零效应”的直接解释。

**FACT 3：文献车型参照会显著改变机会集合。** `b2_wang95_range_opportunity_20260801/decision.json` 记录 `routes_over_95_km=425/1040`、`share_over_95_km=0.40865384615384615`；六个正式算例为 `31/187`，六个实例分别为 `3/27、3/27、6/26、7/35、6/36、6/36`。Wang et al. (2026) 的北京业务数据确为 `74.8 kWh、95 km`，见 PDF pp. 24, 26--27；仓库页级核对在 `docs/handoff/e5b_literature_and_infrastructure_diagnosis_20260801.md` 第 88--96 行。这回答 (b)：按该文献车型的 95 km 物理参照，**425 条**进入可能需要途中补电的区间；该数只是零搜索机会数，不是非线性优化后的效果数，边界见 `b2_wang95_range_opportunity_20260801/report.md` 第 3--6、16--18 行。

**VERDICT E5：顶层设计。** 对 (c) 的严格回答不是“纯算例偶然”，也不是“只要写下 77.28 kWh 就在逻辑上注定”。电池容量单独不能决定路线耗电；但在 **77.28 kWh 原车型能耗参数与这批 China81 路线共同冻结** 时，`max(route_energy)/battery=85.780126%<100%` 已经零搜索可知，之后再增加搜索预算也造不出途中补电必要性。文献车型在同一路线集上给出 `425/1040` 的反例，推翻“中国这类业务天然没有条件”；未在冻结“主张 × 车型 × 算例”前做比例筛查，属于顶层设计失误。

### E7

**FACT 1：36 个 O1 单元中的两个失败具有同一个直接原因。** `probe_three_sizes_seeds1to3_eval8_count_20260801/decision.json` 为 `cell_count=36`、`passed_cell_count=34`、`all_results_retained=true`。失败均为 `cn-prd-150c-01-V2-LOCATIONS`、seed 3、第 18 批：固定 30 分钟规则与“累计 20% 或最多 30 分钟”规则；该目录 `report.md` 第 70--72、86--89 行保存了 `NoExecutableContinuation` 原文。

`failure_diagnosis_20260801/decision.json` 进一步记录两种规则 `batch_count_each_policy=18`、`batch_sequences_identical=true`。C135 于 `56463.580381... s` 出现、在 `57600 s` 被处理；所有四车场、两车型的最迟发车均早于触发，最宽松的深圳 CV/EV 也只能在 `57332.43306 s` 前离场，故已晚 `267.56694 s`。当时 `35` 辆车全部在状态表，`19` 辆可用、`11` 辆从未出车；直接原因不是缺车，而是 **触发规则把 C135 留到了硬时间窗已不可达的时刻**。出处：`failure_diagnosis_20260801/report.md` 第 5、11、15--27、31--44 行。

**ANSWER：预算或算法不能解决当前两单元。** 同一模型、同一触发时刻和同一允许动作下，`latest_departure-trigger=-267.56694 s` 是硬不可行证书；`failure_diagnosis_20260801/decision.json` 明确给出 `higher_budget_can_rescue_current_stage=false`。更多候选评价或换搜索算法不能生成已经过去的发车时刻。因此 (b) 的回答是 **不能**。

**FACT 2：人民币等待损失系数没有通过设计所需的来源门。** `docs/handoff/waiting_loss_evidence_20260802/done.json` 为 `candidate_count=15`、`usable_count=0`；`candidates.json` 的 15 个 `usable_for_china81` 全为 `false`。这不是“等待没有经济后果”：同目录 `report.md` 第 10--14 行已经找到中国赔付、销售、选择实验等后果，只是均不等于“从订单到达起、承诺时限内，每多等一分钟的人民币损失”。倪冠群等（2025）PDF pp. 3875--3876 的规则虽为 `(发车时刻−到达时刻)×c×货量`，却明写“不失一般性令 c=1”，发车费仍为抽象 `C`；Gautam & Geunes (2024) pp. 97, 99, 101--102 的 `h=0.6/1.2/2.4`、`φ=100` 是模型情景和敏感性，不是企业人民币标定。页级核对见 `waiting_loss_evidence_20260802/report.md` 第 118--124 行。

**VERDICT E7：顶层设计，且事前可预见。** 对 (c) 的准确说法是：在选定“可与 China81 人民币成本直接相加”的经济发车研究问题前，先查其两个核心来源的单位、标定方式和适用场景，就能发现手头只有归一化参数或情景参数，因而 **缺少可用系数这一设计阻断可以事前发现**。但 `15/15` 不可用只证明本次可核验来源没有可直接移植值，不能写成数学意义上的“文献证明世界上不存在该值”。研究问题先冻结、必要经济输入后取证，根因属于顶层设计而非业务或程序。

## 第二部分：是否为同一失误的第三次发作

### 第一条历史记录：同型，但不是新的独立次数

`docs/handoff/memory/mechanism_condition_absent_20260731.md` 第 10--24 行记录 E3 的 `registered_differs_from_nearest=False` 为 `0/150`，且 `loader_derivation="customer city -> the unique depot in that same city"`，使错配按构造为零；第 31--47 行记录 E5 两臂 196 个会话的起止 SOC 和充电量逐会话全等，只有 `36/196=18.37%` 进入产生曲线时长差的区间。这与当前 E5/E7 的共同层面相同：正式搜索前即可检查的机制必要条件没有先验过门。它同时已包含 E5，因此不能把当前 E5 再计为一个独立的“新发作”。

三者的机制事实并不完全相同：旧 E3 是处理变量按构造为零；E5 是路线能量需求不触发途中充电；E7-O1 是等待后出现负可行余量，属于“过度进入不可行区”；E7-O2 是研究问题缺少可标定的经济输入。`mechanism_condition_absent_20260731.md` 第 56--57 行也把 E7 称为“反方向的同一类病”，而不是与 E3/E5 数学上同一个条件。

### 第二条所谓历史记录：不存在，且相邻证据反驳其内容

用户点名的 `docs/handoff/memory/e3-lever-is-fleet-pooling.md` 在当前工作树不存在，`git log --all -- docs/handoff/memory/e3-lever-is-fleet-pooling.md` 也无历史记录。最接近的现存原文是 `docs/handoff/mechanism_lever_rethink_20260731/report.md`：王勇等（2023）pp. 1134, 1138--1139 的五级实验确实固定客户归属并改变资源共享，报告成本 `10992.7→6240.5`；但陈雨蝶等（2025）p. 16 的独立→分区已降成本 `31.18%`，分区→联合的资源共享追加仅 `3.44%`，该报告第 100--108 行明确判定文献方向冲突、不能作统一杠杆归因。更直接地，`baselines/china_e3_e7/e3_pooling_probe_20260731/probe_results.json` 的同种子成本显示 POOLED 相对 JOINT 分别约 `−0.038% / 0.000% / −0.036%`；`mechanism_condition_absent_20260731.md` 第 59--60 行已记为证伪。因此“真实杠杆已证实是车队池化，而项目测了客户重指派”不是已记录成立的前次事实。

**VERDICT：`third_occurrence=false`。** 可以确认的是一个反复出现的宽泛流程失误，不能确认 R 所说的三次独立同型记录。其共同失误动作，用一句可操作的话表述为：**在冻结研究主张与情景前，没有把文献给出的机制必要条件逐项映射到候选算例，并用零搜索检查这些必要条件的可行集合是否非空。**

## 第三部分：事前可检验性

答案是 **有**，而且仓库现有两项零搜索筛查正是雏形。检验对象必须是“必要作用空间”，不是预先要求效应方向或自造显著性阈值。

### E5 零搜索暴露检查

对每条冻结候选路线计算 `route_energy_kwh / battery_capacity_kwh`。在满电离场口径下，值超过 `1` 才产生单电池无法完成该路线、因而必须取得途中能量的物理必要性；`1` 是电池能量守恒边界，不是经验阈值。若采用 Wang 文献车型，则直接检查 `ev_road_distance_km > 95 km`，其中 `95 km` 与 `74.8 kWh` 均来自 Wang et al. (2026) PDF pp. 24, 26--27。若研究主张还要求“非线性段”显形，则必须另检查实际充电区间是否与所选曲线的非线性段相交；Montoya et al. (2017) pp. 2--3 给出约 80% 后的折减形状，pp. 17--18 报告约 12% 的途中充电超过 80%，所以应使用所选文献曲线自身的断点，不能新造统一 SOC 合格线。

`b2_opportunity_audit_20260801` 对 1040 条路线的复算正是这种检查：它在零搜索下得到最大 `85.780126%`、公共站机会 `0`，足以在正式算法前否定“原场景中曲线会改变途中充电路线”的必要前提。`b2_wang95_range_opportunity_20260801` 则示范了用文献阈值做敏感性机会筛查；其 `425/1040` 只判“机会非空”，不预判效应。

### E7 零搜索暴露检查

对每个动态订单和每个允许的车场—车型，倒推 `latest_departure`，再计算候选等待规则下的余量 `max(latest_departure) - (arrival_time + wait)`；阈值为 `0`，因为负值按模型硬时间窗定义即不可达，不是研究者自造效果线。候选等待值必须来自所选文献规则：本项目 O1 的 10%/20% 累计比例来自 Ninikas & Minis (2020) p. 14，见 `probe_three_sizes_seeds1to3_eval8_count_20260801/report.md` 第 3--5 行；“定量或最多 30 分钟”的母体来自邱莹莹（2024）p. 24 式 (3-2)，其算例参数 `T=30 min`、`q=500 kg` 见同文 pp. 47 附近，仓库逐页核对为 `docs/handoff/diagnosis_and_remediation_master_20260731.md` 第 464--470 行。30 分钟只能是该文献规则的候选观察点，不能提升为普适业务阈值。

`e7_o2_dispatch_20260801/zero_search_15_streams_20260801/decision.json` 已用 `search_evaluations=0`、`solver_runs=0` 检查 15 条流、300 单：立即/等待 10/20/30 分钟仍可达的订单分别为 `300/298/295/293`，最紧订单仅余 `3.384 min`（同目录 `report.md` 第 7--16 行）。这就是时机—硬窗事前筛查的雏形，并已能预警 30 分钟规则会让 7 单越过可行边界。

经济发车规则还需并列做一个“参数可标定性门”：候选来源必须同时满足与“订单到达至发车等待”同语义、人民币单位、订单/时间尺度和 China81 适用边界。倪冠群等（2025）pp. 3875--3876 的 `c=1` 归一化与 Gautam & Geunes (2024) pp. 97, 99, 101--102 的情景参数都不能通过该门；`waiting_loss_evidence_20260802/candidates.json` 的 `15/15 false` 是执行结果。这个门只判研究问题能否按声称的人民币口径实例化，不判经济发车机制本身真假。

## 证据完整性

本次逐项重算了以下七份 `artifact_hashes.json` 所列文件，SHA-256 均与清单一致：E5 的三个 B2 目录、E7-O1 的 36 单元目录与失败诊断目录、E7-O2 的零搜索目录、`docs/handoff/waiting_loss_evidence_20260802/`。哈希枚举与本交付均排除 `._*`。

`status = D3_ROOTCAUSE_REVIEW_COMPLETE`
