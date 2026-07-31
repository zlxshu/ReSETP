# Memory Index

- [ReSETP 长期工作方法（2026-08-01，唯一正文）](user_operating_principles.md) —
  **所有代理强制先读。** 分两部分。第一部分 §1–§13 是十三条做事规则：不设无目标期刊原文页码支持的科学门槛；
  深读文献完整做法；卡点先查文献；新提案先查已关闭路线；删无信息量的防御性免责；允许事先设计放大器但禁止
  事后结果过滤；已批准范围内自主推进、真正需要用户决定时一次性收齐；对用户说人话、对执行者给编号施工小任务；
  单一事实源；按难度选模型；一任务一监控器。并明确区分代理可直接执行的事项与必须由用户拍板的研究选择。
  第二部分 §14–§20（2026-08-01 补录）是判断方法与经验规律：先找病灶不是加数据、地基不牢不推主线、
  设计直觉不是已证结论、让对手更强而非赢得更狠、目标不可达当场给算术、口径一致属呈现问题；
  对比要制造张力、先写下什么能否定自己、三条线不互相救场、主算法血统必须独立；
  单种子读数不可信、抽样不替代全量、先扣预算差、服务量会伪装成降本、数字带时代标签；
  多数停机是检验装置自身缺陷、排查顺序固定、门禁误伤改判据有次数上限、默认不开火；
  范围膨胀是最贵失败模式、沉没成本不算理由、对抗评审前置、先冻结再试水、授权边界是硬的；
  均值吃掉张力、形容词要有可核验定义、改生成器不改产物、展品不许美化、黑话不进对外文本；
  第二意见无事实裁决权、五级权威顺序、文档有时序、汇报前多处对齐、大节点复述全局、
  时间与目标冲突要明说、意外要登记。

- [碳强度双字段语义恢复（2026-08-01）](carbon_forecast_semantics_restore_20260801.md) —
  `REG-20260801-C01` 已完成：当前 China81 主稿同时定义预测/事后核算碳强度与排放；规划目标、
  参与收益和充电择时使用预测量，结果复算使用核算量；实验章明确 S1-2025 为省级情景投影且
  China81 两字段同值，故现有 E4 不含预测误差效应。25 页编译成功，数学审计 36/1/0，A-1 关闭。

- [未决问题清单（2026-07-31）](../open_issues_20260731.md) —
  **用户"稍后处理"的交付，四类；A-1 已于 2026-08-01 关闭。** A 其余需裁决（A-2 车队构成——
  电动车配额 25% 无依据且从未校验 77.28 kWh 续航，台账 L33 指错了对象；
  A-3 E3/E5/E7 三主线已获原则批准等开工令；A-4 碳强度情景敏感性数据已备齐）；
  B 只欠动手（建模章子节顺序、43 项里 25 项未披露来源类型、E5 快充 100c 待指令）；
  C 查过没查到（阻力系数 0.45、尖峰电价月份不匹配、E7 两项需小批诊断）；
  D 已执行备查（车队重算逐行全等、碳强度双字段语义已恢复、CEF 数据集补齐 MD5 7/7）。

- [诊断与整改主文档（2026-07-31）](../diagnosis_and_remediation_master_20260731.md) —
  **2026-07-31 之后 E3/E5/E7 整改的唯一入口，与之冲突的更早文档以它为准。**
  含：六组实验终态与证据；三条根因确诊（E3 错配 0/150 按构造为零、E5 两臂逐会话全等且
  折减区只 36/196 又不占稀缺时间、E7 模型缺出口+触发公式漏 ref:71 式(3-2) 第三项 t_n）；
  碳强度"预测/实际"两头落空（数据只一列且是省级情景投影）；43 项输入台账复查
  （11 官方观测 / 25 构造情景 / 7 工程假设，25 项未在正文披露；L33 车队权威仍基于旧车型未重算）；
  三份文献取证合并裁定（判整例不可行 34 篇 0 先例、错配率无人当入参、全部文献离场满电、
  Miyabe 2025 给出碳强度可照抄写法）；用户三条整改裁决；六条执行方案含前置依赖；
  七条未查清台账；八条接手方纪律。

- [三份文献取证的合并裁定（2026-07-31）](literature_verdict_20260731.md) —
  开工依据总汇。E7：判整例不可行在 34 篇里 0 篇采用，唯一出现处（Ojeda Rios 2021 p.8）是把
  「硬时间窗+不许拒单+有限车队」列为建模缺陷、逐字对位 E7；五类有出处出口（拒单/外包/软窗/顺延/
  重规划增派车辆）；触发公式漏了 ref:71 式(3-2) 第三项 t_n（动态信息接收窗右端），过期订单正落其区间；
  ref:18 只支持定时不支持定量=引用错配；STATIC_FIXED_RECOURSE 文献无对应物。
  E3：按行政区划派生登记车场 11 篇无先例；没有论文把错配率当入参（都是优化结果的事后统计）；
  车场数文献集中 4 或 6，我们 2 个在下界。E5：全部文献假定离场满电、充电在途中站，
  Keskin&Catay 命题1 已论证车场行前充电无决策含量；文献看可行性不看成本（Montoya 9/20 不可行但成本仅差 2.70%）；
  五个有出处方向 + 两个明确无出处方向；纠正了「电池 4.83 倍」的旧结论。
  E6：饶卫振两篇都没论证事后分摊、是框架自带顺序；退出值算法与我们 I 臂一致；都没遇到负节省/空核；
  都没提事中保参与。碳：Miyabe 2025 p.12 给出可直接照抄的写法（两端同一组预计算值并写明）。

- [E7 不可行根因（2026-07-31 只读诊断）](e7_root_cause_20260731.md) —
  114 个失败拆三块：A 24 个=新增订单被处理时时间窗已过期（50c 上"首个含过期订单的阶段"与
  实际失败阶段 5/5 精确相等，唯一无过期的 stream4 正是唯一 PASS，最极端 due−trigger=−5415.4s，
  与车队余量无关）；B 30 个=静态臂零自由度、跑前就写进自检通过条件；C 60 个=100c/150c 阶段 1
  即死、未定位到条件级，且预算 600 只在 50c 标定过、两规模从未做预算探针，"预算不够"与
  "结构无解"不可区分。两条独立发现：①84/84 滚动臂失败单元 evaluations=completed×1200+600 且
  28/28 组三臂报错逐字节相同 ⇒ 失败阶段只跑了臂无关的共享影子基准，臂对照从未开始；
  ②碳开关日初那一半没接线（corrected_initial_plan 收下 arm 后弃用、硬写 aware），缺陷早于 v3。
  唯一可信对照：50c seed4 协同开关真 binding（NO_COOPERATION 贵 20.786545%）。
  用户"屎山代码"假设部分成立但非主因。

- [机制作用条件在算例里不存在（2026-07-31）](mechanism_condition_absent_20260731.md) —
  只读复算两条 FACT：①E3 两个正式算例的 `registered_differs_from_nearest` 全为 False，
  错配率 0/150，且由 `china81.py:355`「客户城市→该城市唯一车场」按构造恒为零，
  1.4829% 只是路径合并收益、被测杠杆无实例；`ind_arm_run=false` 三臂实跑两臂。
  ②E5 的 L100 与 NL90 逐会话起止 SOC 与充电量完全相同（非线性只改时长不改决策），
  160/196 起始 SOC=0%、140/196 起充于第 0 秒行前充电、终止 SOC 中位 37.03%，
  只有 36/196 充到 100% 且时长差全部等于同一个 1264.6 秒、落在不稀缺的行前段。
  推论：E3 弱、E5 零是同一病——机制作用条件在算例里按构造不存在，与门禁无关；
  E7 是反方向同病（114/120 合法不可行，余量为零）。共同轴线是算例/参数标定。

- [城市群分层表重算+U1碳强度修正+U2/U4/S5复查（2026-07-31）](number_resolution_20260731.md) —
  S1两口径自检通过(方向排序一致)→选口径B(405单元flat)替换九层表；U1按方法节
  单一代表电网口径复算并直接替换正文(唯一被授权改TeX的一项)，发现"成渝日均碳强度
  显著更低"归因在新数据下不再成立；U2代码有值但来源标签不可验证(EV有厂商吻合值
  CV无)；U4/S5均在`ledger_input_provenance_01_20260728`目录找到完整来源(此前两轮
  审计未搜到)，S5尖峰电价官方文件注明2月不触发。报告：`docs/handoff/number_resolution_20260731/`。

- [paper_main.tex 按核对报告修复（2026-07-31）](tex_fix_20260731.md) —
  已修7处有据可依的问题(S2燃油价/S3车型/S4运行次数/D6 E7臂设计/D7摘要创新点时态/
  P1 E5表格/P5 E4图路径)；第二组4类(S1九层表/U1碳强度/U2U4阻力系数里程费率/S5U3
  尖峰电价)严格只列出未改；S1两种口径9行表已算出待用户选；latexmk编译成功25页
  未定义引用0。报告：`docs/handoff/tex_fix_20260731/`。

- [paper_main.tex 全篇数字与封存证据核对（2026-07-31）](tex_evidence_reconciliation_20260731.md) —
  只读核对34处数值/设计断言：19 MATCHED、5 STALE、4 UNSOURCED、6 PLACEHOLDER。
  致命：①`tab:china81-summary`九层表仍是陈旧批次(`e2_e3_reframing_20260731`点名
  但未替换)；②燃油价6.87/6.83/6.90是代码注释自证的superseded旧快照(应为分城市
  7.48/7.43/7.44/7.50)；③车型表EV列(140.41kWh/1000kg/3300kg)是07-27已批准变更
  前的旧车型(应为77.28kWh/1700kg/2600kg)；④E7小节文字(含摘要/创新点)描述
  "5臂/27单元"且用完成时态声称已考察动态需求交互，实际冻结设计为4臂×3算例×10种子
  且完整候选搜索评价数为0。报告：`docs/handoff/tex_evidence_reconciliation_20260731/`。

- [Paper V2 防御性与 AI 味表述清理（2026-07-31）](style_cleanup_20260731.md) —
  以当前工作树 TeX 为备份基线，逐项登记 41 处修改：防御性 8、AI 味 26、
  可读性 7。删除用户指定的原第 255、1629 行引导句，保留数据分母、比较协议、
  非等算力披露、模型近似与影子价语义。latexmk/XeLaTeX 两遍通过，24 页，
  未定义引用 0，overfull 1，underfull 1；报告和日志位于
  `docs/handoff/style_cleanup_20260731/`。

- [E4 充电时刻迁移机制图与正文主表（2026-07-30）](e4_figure_table_20260731.md) —
  只读使用封存 `action_timing_audit.csv`、E4 `raw_runs.csv` 与冻结 48 槽日历，
  新增实验 0。44,072 个会话日按 `energy_kwh` 全分母聚合并与 11,340 个配对解--日
  逐行闭合；固定共同解释日 2025-02-12 和北京/广州/重庆代表曲线。双面板矢量图、
  300 dpi PNG 与一行一指标正文表已完成，四项总量和百分比均来自封存总和。

- [E6 两中心 Shapley 事后结算（2026-07-31）](e6_allocation_20260731.md) —
  只读使用 E6 v3 的 40 个 I/U 状态行，搜索重跑 0。无转移口径保留
  0/20 自然帕累托、20/20 F 回退 I 和 1.511784% 行等权公平代价；预算平衡
  Shapley 结算下 19/20 个单元核非空，转移均值 817.374757 元，每名成员净改善
  均值 22.679075 元。100c seed 4 的系统节省 -1.135377 元，核为空且未采用
  外部补贴或跨单元补偿。

- [E7 v2 KeyError 已修、NL90/前夜日历启动契约 HALT（2026-07-30）](e7_dynamic_v2_20260731_halt.md) —
  沿用原四臂、15条冻结流、10 seeds 与预算规则；旧单文件 `instance_json` 已改为
  China81 八类真实源路径及分项哈希，零搜索检查通过。最小启动在共同初始计划漏传
  China81 prices 处崩溃；显式 prices 的零搜索诊断使 naive 通过，但 aware 又缺
  `charge_day_offset=-1` 的权威前夜碳曲线。未伪造输入、未改搜索，评价0、预算未锁、
  三规模未跑，终态 `HALT_PROBE_STARTUP_CURVE_CALENDAR_CONTRACT`。

- [E7 China81 动态实验探针启动 HALT（2026-07-30）](e7_dynamic_20260731_halt.md) —
  15 条冻结流、375 个事件与 donor 道路克隆条件核实；原 B1 不能回答静态受扰实际表现，
  已在搜索前显式预注册 `STATIC_FIXED_RECOURSE` 替代。零搜索预检通过后，50c 长探针
  在进入候选搜索前因读取不存在的 `source_paths["instance_json"]` 崩溃；评价 0、
  预算未选、正式三规模均未运行。按“崩溃即停”未修复重启，终态
  `HALT_PROBE_STARTUP_KEYERROR_INSTANCE_PATH`，三机制与动态效果均未观测。

- [E6 v3 线程冻结后的候选池回放与 I/U/F 终局（2026-07-30）](e6_fairness_v3_20260731.md) —
  四个数值线程变量固定为 1 后，仅重跑 JOINT 20 单元并重新判定；20/20 最终解、
  完整目标位、实际评价数、trace 与终止原因均和 E3 逐位一致，ZONE 重跑 0。
  2869 个完整可行事件形成 2764 个唯一候选，参与可行候选 0，故 F 有证据地在
  20/20 单元回退 I；自然帕累托 0/20，公平成本行等权 1.511784%。独立验收、
  75 文件重封清单和最后 `done.json` 均闭合，v3 AppleDouble 最终为 0。

- [E3 结构性对照输入完成、正式批技术 HALT（2026-07-30）](e3_structural_20260731.md) —
  旧扫描剩余 29 单元登记为 `NOT_BUILT_SUPERSEDED_DESIGN`，旧 106 个终态和
  56/56 等价证据不动。China81 客户 `city` 是现成行政归属的等价字段，装载器映射到
  同城唯一车场；两个指定算例行政归属与最近车场均完全重合。三臂各 2 份输入完成，
  探针 331 次自然耗尽并冻结 cap=400。正式批形成 26 个 trace 后因硬锁 IND/ZONE
  出现 14 个跨场候选真技术错误而 HALT：18 PASS、8 HALT、34 未运行，三效应不聚合。

- [E3/E6 输入构造性能攻坚中间状态（2026-07-30，后续已由结构性设计取代）](e3e6_input_builder_perf_20260730.md) —
  最终 C++ 冻结 First-Fit 构造器历史 56/56 等价、0 不一致；135 单元已有
  106 个权威终态、13 个严格不可行；当时 8 个 150/200c、50% 高负载单元在
  PGID 7965 下精确满核运行，另 21 个排队。该状态后来被期刊对齐结构性设计取代，
  29 个未终态单元未继续构造。固定映射 First-Fit 为多项式，但
  多目的地词典序完整映射存在性仍是组合问题；未完成前不得写 `done.json`，
  也不得擅自把精确合同改成贪心、任意路线分区或超时 UNKNOWN。

- [E5 文献曲线预注册暴露门停止（2026-07-30）](e5_literature_curve_20260731.md) —
  文献与 VRP-REP 原始 XML 共同锁定 `M17_22KW_NORMAL_PWL`：SOC 断点
  0/0.85/0.95/1，功率 21.9355/10.6667/3.3333 kW。既有 196 会话的 85%
  暴露为 36/196（18.367%），与 NL90 完全相同；80%--95% 计数均不变。
  按用户预设门判 `SKIPPED_CURVE_ALSO_UNEXPOSED`，新搜索 0/20、未观察新臂
  目标值、无三臂表。最终 E5 的 COMPLETE / `MECHANISM_BUT_TIE` 保持不变。

- [E5 v4 已认证单元无搜索终局聚合（2026-07-30）](e5_nonlinear_final_20260730.md) —
  用户授权修复 AppleDouble 枚举误报后，只读纳入 v4 的 40/40 已认证单元，
  `search_reruns=0`。清理前后真实文件均为 262，68 个 `._*` 精确清除，真实哈希
  集不变。NL90 可行 20/20，L100 假可行 0/20，共同 NL90 配对成本变化总体
  0.000%；196 个会话的时长增量均值/中位/最大为 232.270/0/1264.582 s。
  终局标签 `MECHANISM_BUT_TIE`，四端点与期刊式一行一算例表均已发布。

- [E5 v4 null 诊断闭合、40 单元完成、终端聚合 HALT（2026-07-30）](e5_nonlinear_v4_halt_20260730.md) —
  同 seed 逐位证明纯诊断字段不改搜索语义；双臂探针 368/368 个 null 均为容量/
  时间窗完整模型 `ValueError`，技术错误 0。正式 cap=400，50c 后 100c、10 seeds、
  两臂共 40/40 搜索 PASS，独立 checker 40/40 PASS。终端 loader 将 40 个真实
  certificate 与 40 个 AppleDouble `._*` 读成 80 并崩溃；按用户“崩溃即停”
  规则未修复继续，四端点 `NOT_AGGREGATED`、回答数 0。根终态
  `HALT_APPLEDOUBLE_CERTIFICATE_DENOMINATOR`。

- [E5 v3 上限预算修正与探针歧义 HALT（2026-07-30）](e5_nonlinear_v3_probe_halt_20260730.md) —
  用户批准把完整候选预算从精确配额改为上限；v3 runner/checker 已建立且受保护源码
  哈希闭合。1500-cap 探针首个 L100 单元因 trace 含
  `complete_objective=null` 在原子落盘前 HALT；上游用
  `INFEASIBLE_OR_ERROR` 同时表示合法不可行候选和捕获错误，现场未持久化 trace/
  failure strings，故不能可靠归类。按用户“不确定则停止”规则未修复重试，正式预算
  未选、正式单元 0、四端点 0；权威终态
  `HALT_PROBE_AMBIGUOUS_NULL_OBJECTIVE_TRACE`。

- [E5 v2 收敛探针技术 HALT（2026-07-30）](e5_nonlinear_v2_probe_halt_20260730.md) —
  新期刊对齐合同已废止旧 L/S/20%/pilot 门禁并授权 E5；v2 入口已建立，但
  1500 长探针的 L100 单元只实际评价 331 次、expected=1500，暴露
  `max_archive_candidates` 上限不能保证精确完整候选预算，故 fail closed 为
  `HALT_PROBE_NONEXACT_BUDGET`。未修复重试，正式 50c/100c 为 0，四端点 NOT_RUN；
  继续须用户另批预算精确消费技术方案。

- [⚠️ 文档层级校正 + E5/E3E6 交接（2026-07-29）](../session_handoff_20260729_document_hierarchy_and_e5_e3e6_state.md) — **冷启动先读这份再读其余强制入口**。READ_ME_FIRST 清单里的 MASTER 总纲/planning map(07-01)/PRD v2(07-02) **已不是当前执行入口**(MASTER第5行自陈被07-11覆盖；PRD的E2-G0~G5已被07-25 FINAL_STOP+07-27终局裁决作废)，其正文主体是**已退役的英国轨**(Goeke80/280kWh/09x-09y/DR-ALNS)；但记录纪律、结论标签制、禁改语义、四同步链、**已关闭路线台账**、不要做清单仍是硬约束。当前权威链=07-11拍板单→07-12 E3-E7设计→07-13 north star→07-17/20 China pivot→07-25行动合同→07-27 E2终局→07-28 `CONTRACT-E5E7-BLIND-01`→07-29算例选型裁决。并载E5/E3E6实时状态、结果盲合同硬约束(27单元统计/种子锁1-5不扩种/预算=完整候选数/首个结果后合同不可改)、`HALT_BUDGET_VALUE_NOT_APPROVED`待批项、`paper_main.tex:924-927`与27单元口径的设计漂移，以及看门狗三缺陷教训。参见[文档层级校正](document-hierarchy-correction.md)。

- [E2算法实验终局裁决（2026-07-27）](../e2_final_closeout_20260727.md) — `ALGORITHM_EXPERIMENTS_CLOSED_WITH_MIXED_EVIDENCE`。China81:MV对纯距离开源O臂354胜/46平/5负、平均降本1.9191%(全量405配对),但五级阶梯仅299/405,**不得称每层机制全面单调贡献**;O为新收敛式批、F/E/M/MV为v7固定迭代封存复用,必须披露非同批非同机非等算力。公开算例:固定MV-HGS-SP协议只复现13/18个目标(PR14A/PR15A/PR15B/PR16A/PR24A失败),**禁止写"18个新BKS全部由本文算法复现"或"公开算例上普遍优于纯HGS"**;新增5个独立认证更低候选(PR12A/PR14B/PR22B/PR23B/PR24B),仅PR14B可严格归因集合划分。验证:4测试+Ruff通过,15哈希匹配,16/16新witness证书PASS。主TeX尚未按校正登记册改写,属下一步论文任务。

- [E2算法线完整历程 2026-07-25至27（2026-07-27）](../e2_algorithm_journey_20260725_to_27.md) — 唯一权威时间线文档:三个月卡死病灶(China81载重闸门)→公开算例等预算检验揭穿264:0是预算差→四方向证据关闭(地理分解/池富集/对偶引导数学恒等/三层设计被Codex评审否)→喂饱迭代误差腰斩→ε热启动18个新BKS全部独立认证→用户三次关键纠正(不是新算法/不能造假但可以是陈2025级组合/China81须真正干过开源HGS且允许不等算力消融)→三层消融在等CPU下A0反而最优,已叫停转向China81。末节含三条可迁移教训,取代e2_algorithm_design_candidate_20260726.md作为叙事入口(该文件原样保留为失败现场)。

- [公开算例等预算检验：融合结构在等预算下无收益（2026-07-26）](e2_public_equal_budget_finding_20260726.md) — 封存P1的"MV-HGS-SP对母体264胜16平0负"是预算差撑出来的(cpu_ratio 1.47--2.00,434秒比240秒,此事直接读自封存数据)。等迭代6200代对照:hybrid vs 等预算母体+0.0963%(2胜4负),vs短预算母体-1.2411%,而等预算母体 vs 短预算母体-1.3361%——母体光靠给够预算就涨1.34%,超过hybrid相对短预算母体的1.24%领先。措辞边界:seed1六题,差值与种子噪声同量级,只支持"无可观测收益"不支持"更差",D4补seeds2--5中。同轮关闭地理分解(V13无局部性,BKS路线跨度215/全图282)与喂饱路线池(池喂到6--8倍仍三胜三负-0.088%)。三者是同一结论的三面:没有任何东西比把预算直接花在HGS迭代上更划算。新基准线=等迭代(最终等墙钟)真赢过PyVRP-HGS母体。

- [E2 三个月算法失败的根因=电动车载重闸门（2026-07-25）](e2_payload_gate_root_cause_20260725.md) — 电动车载质量1000kg对燃油车1735kg，总质量同为4495kg、整备质量差735kg精确等于载重差；搜索把路线装到中位1667kg紧贴燃油上限，2667个电动候选全部CAPACITY失败，仅9.8%路线可电动。断崖非渐变(1000/1300/1500/1735kg→9.8%/11.2%/15.2%/100%)。载重再平衡与拆分动用闲置车位两条杠杆实测增益均为0(683次拆分全被170元固定成本否决)。解释A(电动车不经济)已证伪:291/291可行候选严格更便宜。G3门0.50%在当前车型参数下不可达且与算法无关。用户同日授权Claude直接执行代码,Codex线停用。

- [E2 当前 China81 设定下算法探索最终停止（2026-07-25）](e2_current_setting_algorithm_exploration_final_stop_20260725.md) — 唯一未覆盖的资源类型感知染色体完成只读活动审计与 T0；冻结 G0 在 100/200 客户两臂均因固定资源组无法在有限车队/时间窗下切出可行路线而最终 STOP。当前设定已无可信未重复新路径；三视角只作机械备份。继续必须由用户在“外部证据驱动重建并从头重跑 E2”与“转为模型/情景/管理机制论文”之间作范围决定。

- [E2 v7 后算法强化与论文重构行动合同（2026-07-25）](../e2_post_v7_algorithm_paper_action_contract_20260725.md) — 完整外部算法和公开 BKS 证明强度，A/B/A+B、双向谱系与留一机制消融解释原因；沿用冻结 G0--G4，不为结果改门。G3 才支持 China81 `1+1>2`，G4 才可能支持公开 SOTA；格式以仓库内 `setp-new.cls` 和已登记官方格式文档为第一事实源，网页只核查更新，陈2025只补未明写处。当前不改在跑 v7、主 TeX、模型或评价器。结果盲论文底稿见[论文重写底稿](../e2_post_v7_paper_rewrite_blueprint_20260725.md)。

- [China E3 正式实验前全链路审计（2026-07-23）](china_e3_full_chain_audit_20260723.md) — 新地理/订单/运行参数/静态输入/有向矩阵权威验收86/86，运行时边界10/10、目标与检查器29/29、定向回归117/117；修正影响54/81实例和2221客户行，成都碳列影响15实例，日期对齐柴油候选若启用影响81/81。最终判`HOLD_E3_DECISIONS_AND_EXECUTION_BINDINGS_OPEN`、搜索评价0；D1--D6、正式runner/哈希见证和新保护语义版本闭合前不得启动E3，旧E2私有结果仅作历史证据。

- [深圳独立价区充电电价情景闭合（2026-07-23）](shenzhen_tariff_closure_20260723.md) — 按粤发改价格〔2018〕313号关闭到预注册情景层：独立计量EV充电设施执行大量用电/高需求相应电能量价并免基本费；既有`101--3000 kVA / 10 kV高供高计 / ≤250`行数值不变，真实命名车场合同仍不作声称。

- [E3前图1/图2几何与语义编码收口（2026-07-23）](e2_final_campaign_p3_p4_complete_20260722.md) — 图1虚线框在流线进出处留缺，节点文本使用自然字宽，终止菱形无问号且“是”箭杆展开；图2取消整图强制缩放，(a)增加第3条档案，(b)/(c)仅以浅灰底+粗框标识$\lambda_r=1$的路线/列。

- [E3前出版社格式基线（2026-07-23）](e2_final_campaign_p3_p4_complete_20260722.md) — 出版社现行细则优先、未明写处参照陈2025；论文不设伪代码，图1按正式runner顺序且回线避让，图2采用顺时针四宫格，均无底纹；图3左下、图4右上无框图例，图4题名为“不同算法迭代图”，坐标为时间(min)/成本(元)，连续单轴且无断轴、平滑、补点或内嵌；曲线仅为代理目标刷新快照的离线完整复核观测，不是全部候选的完整模型历史最优。表3覆盖54个节点并显式区分客户/车场/充电站，表7/8采用陈式分组表头，China81分层汇总独立为表9。22页逐页复核，XeLaTeX零错误/零未定义/零overfull，math_audit 36通过/1弱警告/0错误，可作为E3格式基线。

- [E2 S6-SUP-02 v7 恢复连续单轴（2026-07-22）](e2_final_campaign_p3_p4_complete_20260722.md) — 用户要求放弃断轴；v7图3图例移至左下角，图4恢复单一连续纵轴并回到右上图例，图3/图4数据仍与批准v4源逐字节一致，PDF实际栅格化通过。

- [E2 S6-SUP-02 v6 图形渲染修订（2026-07-22）](e2_final_campaign_p3_p4_complete_20260722.md) — v5保留；v6缩小图3图例、修复图4断轴呈现（上段2510--2610，图例移至下段右上），图3/图4数据与批准v4源逐字节一致，PNG/PDF实际栅格化通过，v6 manifest闭合。

- [E2 S6 支撑产物收口（2026-07-22）](e2_final_campaign_p3_p4_complete_20260722.md) — `S6-SUP-01/02/03` 均 PASS：仿真算例52行详细信息表、S3-TRAJ批准源的中文化断轴图3/图4 v5、PyVRP 0.12.2 HGS教育邻域清单；三套manifest共30项逐项哈希闭合，42个S6目录AppleDouble已清理。主TeX仍由Claude嵌入，终局标记未写。

- [E2 S3-TRAJ-CURVE-DEF-001 与 S5-REV-V4 收口（2026-07-22）](e2_final_campaign_p3_p4_complete_20260722.md) — 用户批准历史快照离线完整评分的单调 best-so-far 曲线定义；40/40 封存最终成本逐位一致、完整解零违约，HGS-M/seed10 的较低历史观测仅保留在轨迹、不替换表内成绩。S5 v4 产物与47项哈希已独立闭合，主TeX尚待重嵌编译。
- [E2 S3-TRAJ-V4 观察层硬门 HALT（2026-07-22）](e2_final_campaign_p3_p4_complete_20260722.md) — 40/40 观察重跑最终成本与封存 S3 逐位相等、完整解零违约；首次 HALT 是 snapshot_file 写回 bug，v1/v2 证据均保留。修复后离线完整评分发现 mechanism_ev/seed10 历史代理新最优骨架为2364.589958517462，低于封存最终2365.8780971446868，按预注册终点硬门判 HALT；不得删除该点或手工抬高终点，Figure4 v4/S5 PASS/终局标记待用户决定。
- [E2 S5-REV-V3 收口（2026-07-22）](e2_final_campaign_p3_p4_complete_20260722.md) — S5 v3 只做封存证据的版式/完整性修订：表5补PyVRP-HGS母体误差列并统一BKS相对误差、表6和China81汇总逐行加粗最低值、表4合计装载率按路线最大实际装载量/总容量改为96.433925%；v2文件与manifest保留，v3 manifest 19项零不匹配。S6需嵌入v3表体并重编译，S7仍未收官。

- [算法命名映射（2026-07-22）](../algorithm_naming_map_20260722.md) — 工程代号↔论文学名单一事实源:主算法MV-HGS-SP;三视角子算法 cv_only=HGS-F(燃油成本导向)/naive_ev=HGS-E(简化电动)/mechanism_ev=HGS-M(机制感知);ReSETP-ALNS是tex编的废名已删,ALNS不进表。代码保留代号,论文用学名,S5脚本按此映射。
- [E2终局战役最终决定（2026-07-22）](e2_final_campaign_p3_p4_complete_20260722.md) — 用户拍板:公开表证"优于已知算法"(P1已完成,0.905%全场第一);China81证"三视角融合1+1+1>3",对手=三视角子算法(cv_only/naive_ev/mechanism_ev)非ALNS;两个ALNS都不进表,ReSETP-ALNS是tex编的名字。S1 preflight已PASS；S2 v1 HALT 原样保留、按登记条目收口为 v2 `PASS_S2_FULL_THREEVIEW_WITH_REGISTERED_INFEASIBLE_UNIT`（810/810，1 个已登记不可行单元）；S3 PASS；S4 v1 伪覆盖 HALT 原样保留、v2 `PASS_S4_ROUTE_DETAIL`；S5 v1 A1/工程代号产物保留、v2 `PASS_S5_ARTIFACTS` 改为正文10行分层汇总+论文命名；链 `PASS_S2_TO_S5_CHAIN_V2`。**S6/S7已收官(2026-07-22 Claude)**:表5/表6/表4/汇总表/图4 v3脚本产物全嵌入tex(表4路径列转G/S编号简写并表注,序列零改动),五段分析+ETGA诚实注(19/28)+0.388s裁判必要性动机句+Rochat-Taillard/Wang2025先引后异novelty句,20页编译0错误0未定义0overfull零悬空文献;终局标记=`baselines/e2_final_campaign_20260720/ALGORITHM_EXPERIMENTS_CLOSED_20260720.md`,**算法冻结只引用不改动**。剩Git提交。

E7正式结果终验

- [China81 非线性充电动态继承 NL3a（2026-07-20）](china81_nonlinear_dynamic_nl3a_20260720.md) — 动态候选、趟链电池账、动作验证、低碳择时和滚动切割共用唯一非线性曲线；2个NL90动作时长零误差，缩时长/缺元数据失败关闭，动态残留恒功率公式0。只放行CV/EV两profile×三矩阵适配，不授权China81搜索。
- [China81 非线性充电成本—检查 NL2（2026-07-20）](china81_nonlinear_cost_check_nl2_20260720.md) — 静态充电构造、精确槽电量、碳择时、成本、利润和独立检查器共用起止电量与曲线身份；缩短动作和缺元数据动作双端失败关闭，L100逐位回归。零搜索夹具碳排从0.7265降至0.1211 kg，只放行动态继承和三道路profile适配NL3，不授权China81搜索。
- [China81 非线性充电核心 NL0（2026-07-20）](china81_nonlinear_core_nl0_20260720.md) — 生产级唯一曲线内核对冻结264,600行动作逐项复算，261,027个可行动作持续时间与分时电量均零差异，L100恒功率退化、24项测试、Ruff和保护文件零差异全过。只放行解结构与多趟排班NL1，不授权China81搜索或性能结论。
- [MPD-ILS-VNS 多阶段双节奏公开线停止（2026-07-20）](mpd_ils_vns_dual_regime_stop_20260720.md) — 快20%→宽60%→快20%在A组三题对宽单体3胜0负、对基础母体2胜1负，但总和仍微差2932约0.0152%，按双单体门STOP，未见B组未开。五机制常驻问询、同墙钟和独立验解均通过；停止公开比例/时点微调，转China81。
- [MDA-ILS-VNS 有限参数竞速停止（2026-07-20）](mda_ils_vns_parameter_race_stop_20260720.md) — 16个分层配置逐轮淘汰后，`race_08`在未见PR16A/20A/24A两种子确认中4胜2负、总目标更低且平均BKS gap改善0.441个百分点，但两处小负和0.688吞吐违反冻结门，判`STOP_PARAMETER_RACE_KEEP_FOUNDATION`，新BKS为0。保留“宽邻域广搜与基础快搜互补”信号，不救参数；下一候选只允许前期广搜—后期快搜并用未见B组确认。
- [MDA-ILS-VNS 后期分阶段路线精修停止（2026-07-20）](mda_ils_vns_late_stage_stop_20260720.md) — 依据陈雨蝶60%--80%后接VNS结构与基础门SwapStar真实改善，冻结70%后500/250两档；最佳档对A组1胜2平0负、总和只改善1009约0.0052%，额外调用本身无严格路线改善，未过至少2胜门。判`STOP_LATE_STAGE_VNS_KEEP_FOUNDATION`，确认题未打开，继续保留基础强母体。
- [MDA-ILS-VNS 自适应控制层停止（2026-07-20）](mda_ils_vns_adaptive_stop_20260720.md) — AILS-II启发的实际结构距离反馈已独立实现，基础臂5/100/1000迭代逐位等价；但A组最好自适应臂对强母体0胜0平3负，只保留55.0%--57.8%循环，三种自适应臂平均BKS gap均更差，判`STOP_ADAPTIVE_LAYER_KEEP_FOUNDATION`。确认题未打开，不救参数；保留已通过的SwapStar强母体。
- [MDA-ILS-VNS 强母体基础门（2026-07-20）](mda_ils_vns_foundation_20260720.md) — 结果前八配置筛选和A组开发选出只在刷新最好解时调用PyVRP原生SwapStar的候选；未见B组三题×两种子×60秒对原装母体5胜0平1负，平均BKS gap从1.041%降至0.648%，改善0.393个百分点，唯一负例0.093%。12解独立验解、33件哈希和全部汇总复算通过；新BKS为0，只放行下一层低成本确认/自适应设计，不放行完整28题、China81或阶段二。
- [MPILS-MVNS 第二候选两发协议终局（2026-07-20）](mpils_mvns_c2_two_fire_closeout_20260720.md) — 首发0胜0平3负后，A组三次母体按预登记15%公式把W/冷却从128唯一修订到1666；第二发触发降到2/0/2、吞吐病灶明显缓解，但仍1胜0平2负。唯一微胜发生在专用动作零触发时，三题机制动作刷新最好均为0，判`STOP_MPILS_MVNS_C2_REPLACEMENT_LINE_AFTER_SECOND_FIRE`；G2、28题、China81和阶段二不启动。
- [MPILS-MVNS 第二候选 G1 B组首发（2026-07-20）](mpils_mvns_c2_g1_b_first_fire_20260720.md) — G0和源码先冻结，G1合同再预登记；两个搜索前启动错误均留痕且未进入求解。PR11B/17B/21B同批seed1短门六解独立有效，性能0胜0平3负。候选只完成母体39.3%--50.7%迭代，28--39次昂贵触发为明确病灶，符合两发协议的W/冷却常数诊断条件；只允许A组一次诊断和一次常数修订，B组第二发再败即终止。
- [MPILS-MVNS 第二候选 G0 基础设施收口（2026-07-20）](mpils_mvns_c2_g0_20260720.md) — 保留Claude提出的强ILS母体、事件式三视角记忆、替换式多车场段扰动和母体精修主方向，纠正单种子因果夸大、AILS-II规则误引、PyVRP接口误判及China81算子误迁。上游/迁入母体在5/1000/5000迭代逐位一致，常驻事件层5000迭代×5中位开销0.811%，人工夹具证实原生扰动0调用、替换精修1调用和64/6/48/12限额。MIT空行失败、许可补正和一次源码卫生误判均原样保留；当前源码重过Ruff/编译/短等价/行为门，最终判`PASS_MPILS_MVNS_C2_G0_CURRENT_SOURCE`。性能、BKS、China81和阶段二均未运行，下一门待用户复盘。
- [MPILS-MVNS 第一候选收口（2026-07-19）](mpils_mvns_candidate1_closeout_20260719.md) — 陈雨蝶式工作名、机制常驻、同轨接线、多车场动作和独立验解均通过；三道已暴露开发题对PyVRP ILS母体为1胜0平2负，按逐题零负门判`STOP_ANY_LOSS_OR_INTEGRITY`。完整算法少跑17.1%--22.3%母体迭代，当前候选冻结，不开确认题、28题、China81或阶段二。
- [ReMIX V13六题开发门收口（2026-07-19）](remix_v13_six_instance_development_closeout_20260719.md) — 陈雨蝶式公开/China81比较基础、同路径与行为接线均闭合，但首个HGS供料+缩短ILS+五轮外置增强+MILP会审候选对六题较强核心为0胜0平6负，新BKS为0。全部18解独立有效、墙钟合规、34件哈希闭合；权威判`STOP_CURRENT_REMIX_V13_CANDIDATE_ALL_LOSS`，停下复盘，不进确认块、28题、China81或阶段二。
- [算法比较基础 v3：V13-MDVRPTW-28 + China81（2026-07-19）](algorithm_comparison_foundation_v3_20260719.md) — 先选经典强手、当前开源强手和最新相近混合体，再由其共同题反推公开主场。现行主场为28道大型多车场带时间窗题；28/28原题语义、当前BKS双检查和论文值抽取通过，当前可验BKS 28/28优于2026论文值。同路径母体/增强关闭/零预算三臂逐位一致。China81仍是唯一完整模型赛场；当前只完成基础，未跑性能。

- [算法比较基础 v2 历史候选：公开X-100 + China81（2026-07-19）](algorithm_comparison_foundation_20260719.md) — X-100来源和BKS零搜索审计有效保留，但“先定X题、再塞对手”的顺序已被v3取代；不得再据此决定论文主表。

- [机制成段生成最小性能门（2026-07-19）](mechanism_segment_generation_20260719.md) — 仓库核验纠正“机制从未生成”的绝对诊断，只补v7未覆盖的2--3客户跨车场成段邻域。结果盲54/108客户、三臂、seed1、B100中质量门通过：一题打平，一题改善1.254%，并出现路程更长但完整成本更低的真实采纳链；但墙钟中位3.298倍、最大4.694倍，按预注册判`STOP_SEGMENT_GENERATOR_NO_RESCUE`，冻结当前穷举实现，不扩三种子或阶段二。

- [机制计价的双路线重切零搜索行为门（2026-07-19）](mechanism_priced_pair_resplit_20260719.md) — 两臂共享39个切分候选和同一完成器，各精算4个；机制计价找到成本`150.06492395356452`的候选，里程前4原样停在`249.81140845994744`，独立穷举显示该候选仅列里程第13。27/27机械检查、11/11防篡改检查和独立只读审计通过，路线搜索/ALNS/HGS调用均为0。仅证明人工夹具上的行为与归因，不证明胜v7/HGS/ALNS；按用户要求暂停，不开新鲜小题或阶段二。

- [燃油路线退役—电动重整零搜索行为门（2026-07-19）](fuel_route_retirement_ev_repack_20260719.md) — 整条燃油路线退役、后悔重插和一级让位形成9个唯一骨架，预登记精算4个；唯一全电候选成本`685.7079097063714`，最低候选`661.4407527272798`，均高于源解`621.0831141941019`，接受0。AppleDouble事故原样保留，恢复仅做8次独立复算而未重跑算法，13/13最终制品和6/6事故哈希闭合。判`STOP_FUEL_ROUTE_RETIREMENT_EV_REPACK_BEHAVIOR`，禁止同题救援、D3、正式、全量和阶段二。

- [燃油长路线减负—电动化联动搬移零搜索行为门（2026-07-19）](../../baselines/algorithm_prototypes/unified_mechanism_alns_20260719/electrification_relocate_resize_behavior_gate_execution_recovery_v2/decision.json) — 恢复版只修验收程序并锁死算法/输入/阈值/预算。证据包独立审计通过，但20客户绑定场景3个完整候选均被通用收尾恢复为原解，成本不变、CV路线`1→1`、接受0；25客户全电对照逐位不变。判`STOP_ELECTRIFICATION_RELOCATE_RESIZE_BEHAVIOR`，禁止旧三题、新D3、正式、全量和阶段二；下一候选须固定搬移骨架并把真实电动化边界纳入联合筛选，用新鲜题验收。

- [结果盲Homberger改进空间与精确路线仓库功能门（2026-07-19）](../../baselines/algorithm_prototypes/algo_reset_20260719/homberger_headroom_audit/decision.json) — 官方压缩包每类在2--7号成员中按源SHA最小值盲选新题，未读BKS；纯HGS 2秒到10秒仅2/6严格改善，判`STOP_SHORT_HOMBERGER_STRICT_WIN_PURSUIT`。路线仓库集合划分人工预算0/1/2/5功能门通过，可混合HGS与ALNS互补路线，但无真实性能主张。

- [算法对照证据公平性降级（2026-07-19）](../algorithm_hgs_alns_fusion_reset_20260719.md) — 旧机制v7的HGS臂为100次暖启动重启且每次内部算力未按ReSETP完整评价展开，中性适配又无法表达完整模型；旧“9/9胜原装”降为历史开发信号。新2秒六题门亦因旧基线复用、墙钟超限、起点池不对称、训练题污染和跨题big-M聚合而不能作公平双赢证据，只能淘汰当前教育器。

- [HGS与ALNS真融合低成本复核及止损（2026-07-19）](../algorithm_hgs_alns_fusion_reset_20260719.md) — PyVRP 0.12.2正版HGS已归仓冻结；项目ALNS和成段移除+后悔修复均真正嵌入HGS子代教育，后者在4/6题产生接受但只胜纯HGS 1/6、双赢1/6，偶发频率2/4/8三档仍失败。判`STOP_CURRENT_GENERIC_EDUCATORS__GATE_NOT_FORMAL_DOUBLE_WIN_EVIDENCE`，不扩三种子或全量benchmark。

- [阶段一非算法部分最终可移交，阶段二未启动（2026-07-18）](../phase1_parallel_status_and_user_gate_20260718.md) — MC-005候选A已重建81份/5805行位置分配且27格内零身份重叠；九城情景道路接入点及冻结路网CV/EV 18/18通过；OSRM完整功能门18/18通过。用户已批准MC-004方法并明确暂时不进入阶段二；最终独立审计判`PASS_PHASE1_NONALGORITHM_HANDOFF_READY`，待批0、错误0、搜索评价0。未建全矩阵、正式实例或运行搜索，算法优化不在本次范围。

- [阶段一并行状态与用户终裁门（2026-07-18）](../phase1_parallel_status_and_user_gate_20260718.md) — 六线已推进到当前边界但整体未完成，阶段二未启动。G1a因RC类零触发停止完整G1；MC-002算力/功效包和重庆池27格门闭合；固定OSM 5/5通过；九主场0/9、两备选0/2及本地货运router/profile继续HALT。六项统计终裁、备选不替换决定、11点人工入口/准入/充电输入及MC-004重批仍是阶段一硬门。

- [G1阶段一低成本组件开发收口（2026-07-18）](../e2_alns_g1_stage1_closeout_20260718.md) — 用户批准基于论文/权威开源的最小成本通用组件开发。SISR因R类三种子实际调用为0淘汰；真正SWAP*通过独立活性门和当前源码C1/B160统一预算接入门。随后G1a 24/24完成，平均改善`0.003918%`等数值门通过，但RC三对零触发，判`STOP_TRUE_SWAPSTAR_BEFORE_FULL_G1`；全量G1的115,200次评价取消。模型机制算子等待自有复杂模型开发集。

- [六张审批单终裁同步与ALNS预算G0收口（2026-07-18）](../../baselines/e2_alns/e2_alns_budget_g0_20260718/decision.json) — MC-001/003/005及MC-006调查授权已按用户终裁同步，MC-002只批准27单元/配对/Holm/结果盲暴露原则，延后项不偷冻；G0新增candidate/reference/repair-delta三账和调用前硬预算门，静态BLOCK=0、unclassified=0、行为/回归186/186，判`PASS_ALNS_BUDGET_G0_COMPLETE`。旧HALT包保留，保护文件未改；下一步只放行Homberger G1开发，不放行正式Solomon或中国胜负实验。

- [EA-001授权口径纠正与隔离原型开工（2026-07-18）](../model_change_approval_register_20260718.md) — 用户授权自主创建独立原型和预算0/1/2/5非正式探针；逐项批准门只拦正式合入、模型/单位/参数变化、正式实验臂和论文主张。四份算法探索包已统一为`isolated_prototype_allowed_under_EA001=true`、`formal_search_allowed=false`并重算哈希；四条隔离原型与九城车场补证v3已开工。E7在02:51推进到6/9，运行期间继续禁止触碰`winner.py`，G0正式改码等待E7科学收口。

- [中国方案重建执行总看板（2026-07-18）](../china_rebuild_execution_dashboard_20260718.md) — 统一记录总目标、治理边界、事实状态、E7与后台监控、主线遗留、挂账和验收标准。正式结构为3城市群×9规模×3互斥复本=81；E3--E7目标为方向理想、效应够大、主要检验显著；完整中国重跑前依次闭合E7、硬基础设施、G0、分机制算法创新、两套强基线、非线性核心和用户审批。

- [ALNS分机制创新探索授权（2026-07-18）](../alns_mechanism_innovation_exploration_contract_20260718.md) — 用户授权对混合车队/补能、合作责任、时变碳/电价、参与公平和动态重规划五类机制自主检索开源/文献算子并设计自研候选，可做隔离原型和非正式探针；状态仅`APPROVED_FOR_EXPLORATION_ONLY`。任何候选合入正式ALNS、进入机制门/正式实验或形成论文创新主张，仍须用户逐项批准。

- [建模、单位、参数与新方法审批总规则（2026-07-18）](../model_change_approval_register_20260718.md) — 用户规定所有单位/代理/模型/参数变更和新算例生成、抽样配额、道路、能耗充电、算法、统计方法都须先报备、溯源核验、影响分析并获明确批准；批准后再同步代码、合同、HANDOFF、memory、测试和证据。2026-07-18终裁：MC-001条件批容量占比代理，MC-002仅批原则层，MC-003选C，MC-004暂不批，MC-005条件批GDP-PPS A，MC-006只批动作1+2调查，EA-001停止重复微探针。

- [算法探索主题3：碳、分时电价与非线性充电（2026-07-18）](algorithm_exploration_carbon_nonlinear_charging_20260718.md) — EA-001两轮研究已完成，固定路线非线性标签法、cspy/PathWyse、Cheng碳感知调度、Lin时变价VNS/TS和SAP共享容量排程已核原文/仓库/许可证；提出双oracle碳—价冲突自研候选和严格碳盲对照。全部仅探索，等待用户逐项批准。

- [中国V2基础设施纠错、普通商业车场、电价、碳日期与全实验切换（2026-07-17/18）](../china_full_experiment_cutover_and_uk_retirement_contract_20260718.md) — 当前权威：正式主集为3城市群×9梯度×3互斥复本=81；E7科学收口后UK轨只读退役。旧订单和手工城市配额已由机器HALT。九城普通商业车场身份来源已9/9快照验签，但正式货车门、准入和现场车辆充电仍0/9。2025-02七价区同月价表覆盖九城，绝对价缺口解除，车场合同档位仍HALT。2026碳插值禁止正式使用，正式月份为2025-02全28日；默认展示日A/B/C/D待用户在结果盲状态选择。有向道路采用同路径距离/时间/Σ(v²d)三矩阵；E7计时运行期间禁止重型解析和核心改动。

- [用户实验与论文要求总台账、实验重基线期间写作暂停（2026-07-17）](../user_requirements_traceability_and_writing_hold_20260717.md) — 汇总用户关于对比与张力、反常识边界、E1--E7、Solomon/BKS与自有算例分工、现代强基线、CPU/RT/Runs、ALNS不预设优越、TVCI与动态E7、Python数学审计、公式≤35、陈雨蝶第一母版、图表高保真外壳、政策起笔、单编号递增引用、字体字号、无附录和顾问只读治理的要求。当前实验方案正在大幅调整，论文正文/摘要/图表/结论保持WRITE-HOLD，解除条件见台账第7节。

- [中国V2九城普通商业车场、官方来源与地图池边界（2026-07-17/18）](../china_v2_parameter_lock_20260718.md) — 原铁路/港口/保税/口岸设施只读归档。九个普通商业仓库或配送中心的运营方/REIT来源快照和哈希已9/9闭合，天津另证实月台、卸货和停车场，北京/天津官方平面图证实入口候选；园区中心不得冒充货车门。正式入口、外来车准入和现场车辆桩均0/9。27/27城市要素池与81份互斥位置分配已通过，但订单属性、PPS城市配额、有向路网和中国核心仍HALT。

- [中国V2订单属性合同（旧设计已撤销，2026-07-17/18）](../china_order_attribute_contract_v2_20260718.md) — 旧需求三段、8/12/18分钟服务时间、手工时间窗权重、30分钟客户窗、手工城市配额与80%见证载重无足够依据，机器状态已改为`HALT_UNSUPPORTED_ORDER_ATTRIBUTE_DESIGN_AWAITING_RECALIBRATION`。保留81结构、三复本身份互斥、06:00--22:00研究时域、结果盲种子和零搜索见证；需求、服务、承诺窗须由中国订单数据/文献合成重建。

- [C31 成渝 100 客户 DRAFT-v2 结构门通过（2026-07-17）](../china_3x3_instance_probe_20260717.md) — 保留绵竹片区 HALT 后，最终采用成都青羊、德阳旌阳、眉山东坡、资阳雁江、乐山市中 33 个真实 OSM Map API 静态小块，客户配额固定为 55/10/17/3/15。候选通过 100 客户、2 车场、3 充电站、105 节点、48 槽重庆TVCI、加载器复算和 98.409748 km 覆盖足迹门；结构门、pytest、Ruff、py_compile 通过，搜索评价0次。判决=`PASS_DRAFT_STRUCTURE_GATE / NOT_READY_FOR_V2_FREEZE`，仍不能进入正式优化；E7清洁重跑仍在后台运行。

- [中国三地当前充电服务费缺口（2026-07-17）](../../baselines/e4_e5/china_policy_price_gate_beijing_20260717/decision.json) — 北京/广东/重庆独立零搜索包均判`HALT_*_CHARGING_SERVICE_FEE_OFFICIAL_NUMERIC_SOURCE_MISSING`；官方能确认分时段和部分历史电价，但公共充电服务费已市场化，缺当期官方中位/指导上限数字，不得用旧政策、二手OCR或估算填补。TVCI列可接入，但完整当前成本情景未冻结。

- [新增中国证据包AppleDouble复核（2026-07-17）](../china_3x3_instance_probe_20260717.md) — 价格来源门和C31 OSM草稿包首次独立校验发现外置卷`._*`旁车；已按`HASH_CONTAMINATED_APPLEDOUBLE`记录并清理，价格五件套17项哈希不变，C31源文件本体未改。

- [C31 3×3草稿构造与唯一冻结阻断（2026-07-17）](../china_3x3_instance_probe_20260717.md) — Map API分块静态快照36/36成功；jjj/prd/cy要素池分别为1595/26/3、1413/119/10、571/58/5；9个50/100/200客户DRAFT均已生成，9/9结构门通过、优化搜索0次。唯一阻断：`c31-cy-100c-01-DRAFT`覆盖半径3.7 km。v2初始16块后只扩绵竹16块，32次请求全HTTP 200；当前有效28块的成都青羊/绵竹扩大池/眉山东坡/资阳雁江池为481/47/4、0/14/0、17/9/0、13/3/0。固定25 POI/块时绵竹仍为0，未生成候选，初次HALT保存在`attempt_history.json`，当前仍判`HALT_C31_CY_100C_SELECTED_REAL_MAP_API_POOL_INSUFFICIENT`。不得把该限定HALT夸大为全都市圈无数据，绝不补随机点；仍不得进入正式实验或v2冻结。

- [京/粤/渝价格来源门完成（2026-07-17）](../china_region_price_source_gate_20260717.md) — 判决=`PARTIAL_CHINA_REGION_PRICE_SOURCE_GATE`；北京/广东/重庆TVCI列可直接接入，但北京和重庆为历史分时快照，广东仅广州/佛山且不覆盖深圳，四川电价未闭合。只有重庆保存同日6.90 CNY/L柴油值，其他地区吨价禁止自行换算；CEA只能作带日期内部影子价。五件套和17项哈希在`baselines/e4_e5/china_region_price_source_gate_20260717/`，未授权价格写入求解器或C31优化。

- [中国公开EV配送算例检索收口（2026-07-17）](../china_open_ev_vrp_instance_search_20260717.md) — 实际下载/读取重庆EV动态配送论文、LaDe重庆订单表、北京充电站、七城EV统计和公开取送订单数据；没有同一来源同时闭合多车场、EV/电池、充电站、客户需求与硬时间窗。判决=`HALT_NO_COMPLETE_OPEN_INSTANCE`，原始文件和SHA256在`data/ChinaInstances/open_sources_20260717/`；C31转为“公开数据做来源锚点+预注册自建”，不得拼接部分数据冒充公开完整实例。

- [E7接力启动与中国3×3支线恢复（2026-07-17）](../../HANDOFF.md) — 上一轮会话限额导致三条中国支线未产生结果；E7合同比较修复已通过真实合同与三种篡改测试。首次启动因未继承`PYTHONHASHSEED=0`在计算前HALT，输出目录未产生结果；随后用显式环境变量、原50评价/6 workers在`/private/tmp/.resetp-e7-timing-clean-rerun-20260717-takeover-env.monitor`启动并处于`RUNNING`。公开算例检索、京/粤/渝来源链、C31草稿构造由独立支线执行，仍禁止优化搜索。

- [E7清洁重跑当前启动阻断（2026-07-17）](../../../baselines/e7_dynamic/e7_timing_clean_rerun_20260717.py) — 代码修复与静态/定向测试已通过，但当前Codex环境的进程池探针在`SC_SEM_NSEMS_MAX`处被沙箱拒绝；Terminal/LaunchServices和用户级`launchctl submit`也不可用。为遵守非沙箱铁律没有调用监控`start`，重跑未启动，输出目录保持不存在/为空；需在真正非沙箱终端按原命令启动。

- [E7清洁重跑合同比较修复（2026-07-17）](../../../baselines/e7_dynamic/e7_timing_clean_rerun_20260717.py) — Codex仅改目标脚本：显式校验四个恢复谱系键和父合同禁带约束，再从子合同副本删除四键并保留原三键调度源豁免。真实父/子合同通过；`authorized_fix`篡改、未知第五键、父合同带`recovery_schema`三种定向篡改均拒绝。Ruff、py_compile和diff通过；脚本SHA-256=`1949837b7dff684962531f2216f3280a23f285d4e7047100e83c254f60238c8e`。重启前输出目录不存在/为空；监控配置没有固定旧脚本哈希。

- [中国3×3算例设计预注册（2026-07-17）](../china_3x3_instance_design_20260717.md) — 用户拍板：主场景转中国，3电网原型区域（京津冀/珠三角/成渝=煤电/风光/水电）×3规模{50,100,200}全交叉=9算例`c31-*`；字面全国算例被物理否决；英国轨退役留档；几何可风格化但碳曲线/价格必须官方来源；正式采纳点=NL统一重跑；v2冻结前禁止任何性能比较。同日Codex四任务并行：A=E7修复重启、B=京/粤/渝价格链、C=公开算例检索、D=数据探针+DRAFT构造。

- [E7清洁重跑HALT根因=脚本白名单bug（2026-07-17）](../../../baselines/e7_dynamic/e7_timing_clean_rerun_20260717.py) — `e7_timing_clean_rerun_20260717.py` run() 的父/子合同比较只豁免 `contract_sha256/source_file_hashes/source_commit_at_start` 三键，漏掉子合同按 `setp.e7.parent_child_recovery.v1` 架构必有的四个恢复谱系键（`recovery_schema/authorized_fix/parent_contract_sha256/recovery_task_ids`，18项任务ID），故任何情况都会在启动前抛 `RerunContractError`；两份合同文件本身已被 SHA-256 常量验签（父`bffdc512...e16f`/子`b703492...0721`），实质字段零漂移。修复=显式校验四键字面值/常量/18项子集后再比较其余键，不得笼统扩大豁免集。输出目录当时为空，无污染。修复提示词已交用户转 Codex；本轮 Claude 未改代码。

- [E7步骤1--6事件后链路静态预检（2026-07-17）](../e7_steps_1_to_6_postevent_preflight_20260717.md) — 六个收口入口和源码指纹均存在且可编译；暂停时效、重放不变量、独立总审计、论文展品和证明构建器21项测试通过。未读取正式E7目录或方向。28日零搜索重放入口自身不拒绝非空输出目录，因此COMPLETED事件后必须先做目录不存在/为空的外部门禁；本轮未改该脚本。该预检不代表E7完成。

- [客户责任结构图坐标轴意见裁决（2026-07-17）](../../paper_submission_final/generated_figures/e3_customer_structure.pdf) — 直接核对Soriano等（2023）正式PDF第8页图3，母版为无坐标轴、无边框、并列同尺度的类别空间图，图例只标成员符号和客户数；当前图采用相同语法且两面板共享坐标范围。因此拒绝机械增加坐标轴、尺度和单位，避免偏离指定母版并把机制示意误作地理测量图；图和数据未改，六图视觉门保持PASS。

- [公式语义上标正体化与审计防回退（2026-07-17）](../../paper_submission_final/paper_main.pdf) — `fix/km/fuel/elec/occ/tr/op/car`统一用`\mathrm{}`正体；新增数学门禁止裸斜体语义上标。旧审计器的`tr`匹配随正文正体化失配后已同步修正，正文未回退。数学审计28/0/1、两层模型7/7、35项论文回归、pending-E7故事门和六图视觉门通过；独立Tectonic编译22页A4并逐页检查第4--7页。TeX/PDF/log哈希=`972284a0...74c3`/`8a91addb...b2b8ae`/`d09c16ea...8f10`；实验数字和E7保护源未变。

- [英文题名10词硬门闭合（2026-07-17）](../../paper_submission_final/paper_main.pdf) — 旧英文题名按连字符词计为11词，修正为与20字中文题名逐项对应的10词`Multi-depot Collaborative Routing Model and Algorithm under Time-varying Carbon Intensity`。数学审计由1项失败回到27/0/1，两层模型7/7，25项论文回归和pending-E7故事门通过。Tectonic独立双遍编译22页A4并目检首页；未改公式、符号、实验数字或E7保护源。

- [4.1最终解分析展品合同（2026-07-17）](../paper_final_solution_exhibit_contract_20260717.md) — 预注册`N114`—地理聚集—seed1作为50客户正文主算例，不按结果挑种子；同一保存解生成路线责任图、实体车趟次充电表、参数表和解释，manifest最后发布。客户、排班、容量、时间、SOC、共享桩、成本和排放须独立复算，失败原样保留；最终算法冻结前不生成结果。

- [摘要公开Benchmark越权与英文题名纠正（2026-07-17）](../../paper_submission_final/paper_main.pdf) — Solomon四件套形成前，中英文摘要及E7摘要生成器不再声称公开算例结果；英文题名补回“协同”。未改公式、符号、实验数字或E7保护源；22页A4编译、论文生成/边界测试26项、Ruff和py_compile通过。

- [Solomon现代强基线零搜索接口（2026-07-17）](../e2_solomon_external_strong_baseline_interface_20260717.md) — PyVRP外部强基线按同机单线程墙钟轴，本文ALNS/LNS按完整候选评价预算轴，两轴禁止混表；560项正式接口按独立attempt、逐任务原子checkpoint和artifact哈希实现可恢复执行。PyVRP 0.13.4官方wheel、独立环境、Tbest累计增量解析和正式bundle适配器已通过v3的16项真实探针与32项接口测试；最终冻结器可哈希96个安装文件，冻结载荷本身也经`freeze_payload_sha256`校验。当前只缺E7步骤1--6证明与最终工具冻结，故仍为`HALT_EXTERNAL_BASELINE_PREREQUISITES`、Solomon搜索0次；官方HGS-CVRP不支持VRPTW，不能直接参赛。

- [Homberger 200客户开发集零搜索来源门（2026-07-17）](../e2_homberger_200_source_gate_20260717.md) — 12个预注册开发实例由SINTEF官方压缩包冻结，逐例结构、车辆上限、分组容量和时间窗12/12通过；权威判定为`PASS_HOMBERGER_200_ZERO_SEARCH_SOURCE_GATE`，五记录面在`e2_homberger_200_source_gate_20260717_v2`。来源快照不保存BKS或详细解路线，搜索评价0次；E7和预算闭合门以前不授权开发搜索。

- [主稿显性模仿痕迹与章节层级纠正（2026-07-16）](../chen_yudie_2025_master_reverse_engineering_20260716.md) — 撤销算法章点名母版并接本文方法的拼接句，流程图源文件去除`chen`命名；模型、算法和数值试验目录按陈雨蝶原文实测编号收回。E2/E7缺证据时不再把内部阶段提示印进PDF，仍由原子门与审计阻断。当前21页PDF中简体“径”61处、繁体“徑”0处，正文不含陈雨蝶、母版、模板、阶段稿或不得投稿；15项论文回归与20项E2 runner回归通过。路线级展品未闭合前不伪造4.1.2最终解分析。

- [E2公开BKS后续启用清单（2026-07-16）](../e2_cvrplib_post_e7_activation_checklist_20260716.md) — E7释放共享内核后，依次执行冻结哈希确认、E2补丁重放、目标哈希验签、119项源码合同重算、定向测试和非沙箱hooks正式60项启动。runner已增加搜索前AST字段门：冻结版缺少三项真实计数字段时立即停止，不浪费一次搜索，不静默伪造计数；20项定向回归通过。

- [E7七件展品原子接入与PDF复编（2026-07-16）](../chen_yudie_2025_master_reverse_engineering_20260716.md) — 中文/英文摘要、三张动态表、解释文本和动态结论必须七件齐备才共同进入稿件；缺一时从PDF整体省略动态小节和结论，机器审计继续阻断，正文不再显示内部阶段提示。当前编译状态以上一条记录为准。

- [E7剩余17项已由hooks接续（2026-07-16）](../e7_exact_trigger_boundary_fix_proposal_20260716.md) — `winner.py`恢复冻结哈希后，非沙箱进程池探针和重复进程检查通过；按原50评价、6 workers与父—子输出合同启动，监控PID=`62970`，run-dir=`/private/tmp/.resetp-e7-parent-child-remaining-17-50.monitor`。健康阶段禁止手工轮询和读取中间方向，完成/异常只由hooks事件处理。

- [E7首任务恢复通过及共享内核复位（2026-07-16）](../e7_exact_trigger_boundary_fix_proposal_20260716.md) — 首个原失败任务已判`PASS_ORIGINAL_FAILURE_TASK_RECOVERED`；其余17项因E2开发改动造成`winner.py`冻结哈希漂移而被子合同正确拦截。E2改动已封存为`patches/e2_cvrplib_winner_metrics_20260716.patch`，可从`0eb31fd5...101b`精确重放到`0e49a7fc...e61d`；工作区共享内核已恢复E7冻结哈希且无diff，本轮未重启E7。活跃长跑期间修改共享内核前必须先查全部冻结合同。

- [E2公开基准报告与算法换代收口门（2026-07-16）](../e2_cvrplib_optimal_search_contract_20260716.md) — runner报告已补齐小/中/大规模分层和全部失败任务，16项定向测试与Ruff通过；SHA=`2ff322e1...12e77`只对应E2指标补丁生效时的延期合同，不是当前已恢复E7冻结内核的工作区合同。E7闭合后须重新应用补丁并重算/复核合同，方可运行公开BKS；只有跨规模、多种子且可归因的结构短板才触发一次ALNS大修。一旦换代，必须冻结单一新版本并统一重跑受影响的E2--E7及E7收口，不得混用新旧证据。

- [“路径”字形全文合同（2026-07-16）](../../../baselines/paper_story/audit_20260715_paper_evidence_boundaries.py) — 论文路由术语统一使用简体“路径”（“径”为 U+5F84）。主TeX、正式证据生成器、算法流程图源和当前PDF均已核对，未发现“路经/路劲/路徑/路迳/路逕”；证据边界审计已将这五类错字列为源文本和PDF的硬失败条件。

- [主稿图5浮动与网页参考文献版面修复（2026-07-16）](../../paper_submission_final/paper_main.pdf) — 图5由强制定位改为允许页顶浮动，消除第16页大面积留白，图5与图6连续落在第17页且图幅和图内字体未缩小；GRIDSERVE与Mer采用完整链接目标和精简显示网址，消除异常字距。22页A4 PDF真实编译通过，日志无Underfull/Overfull、未定义引用或LaTeX错误；公式、符号和实验数字未改。

- [E2 CVRPLIB真实最优公开算例合同（2026-07-16）](../e2_cvrplib_optimal_search_contract_20260716.md) — CVRPLIB X集六个`Opt=yes`算例按小中大三档固定；公开最优解经独立逐弧复算和本文距离退化评价器6/6完全一致、零违约，适配门通过。`k`不是硬路线数。正式搜索为六例×10种子×4000完整评价，E7释放CPU后启动；单例1000评价只作非正式冒烟，不进论文。
- [题名摘要与模型章第一母版重构（2026-07-16）](../chen_yudie_2025_master_reverse_engineering_20260716.md) — 中文题名改为20字的“时变碳强度下多车场协同路径优化模型及算法”；中英文摘要及E7自动生成器统一为无数字的政策矛盾—模型—算法—验证—结论节奏；模型章按问题描述、符号、目标函数、能耗与充电排放函数、完整模型重排。28个公式语义未变，数学27/0/1、两层7/7和4项定向测试通过；MiKTeX进程锁导致新PDF尚未形成，视觉验收不得沿用旧PDF。
- [GPT-5.6结果导向任务合同（2026-07-16）](../resetp_gpt56_outcome_contract_20260716.md) — 目标由投稿级交付、成功标准、证据与权限约束、输出和停止条件定义；陈雨蝶论文为第一母版，算法优势不得预设，E7与E2公开标准算例仍是完成门。
- [E7父—子恢复已授权并启动首任务（2026-07-16）](../e7_exact_trigger_boundary_fix_proposal_20260716.md) — 单行边界修复已应用，扩大回归96项通过；父合同`bffdc512...e16f`、正式子合同`b703492...0721`，旧`199b...`推导已更正。102个父断点只读保留，18个缺口写独立子目录；当前仅复跑原失败任务，50次评价和6 workers不变，由事件钩子监控。
- [陈雨蝶母版第四轮对齐与E7现场保持（2026-07-16）](../chen_yudie_2025_master_reverse_engineering_20260716.md) — 最终PDF逐页复核：流程判断改为“总体评价预算用尽”，收敛图宽高比1.0697且最小字号8.098 pt，表题/图题/表内正文均复核为9 pt等级；结论按机制发现、责任与参与、算法负证据、边界重排。21页稿通过数学27/0/1、证据边界和六图视觉门；E7进程已退出，本轮仅保留异常现场，未恢复。
- [E7恢复前父—子合同谱系闸门（2026-07-16）](../../../baselines/e7_dynamic/e7_pre_recovery_gate_20260716/report.md) — 102/120个父合同断点全部有效、18个缺口、0个无效，保护面和输入无漂移；单行修复会改变正式合同哈希，禁止直接打补丁后原地续跑，须经用户授权后采用旧断点只读保留、子断点独立写入、逐任务登记来源的恢复合同。
- [Goeke公开基准零长跑可行性审计（2026-07-16）](../../../baselines/e2_alns/goeke_public_benchmark_feasibility_20260716/report.md) — 官方180实例与本地副本逐字节一致，表11的180个比较值已抽取；但它们是距离目标下10次ALNS最好值而非证明BKS，且车队字段、单趟/多趟、目标和充电合同未对齐，禁止直接报告Gap%，须先过3实例独立适配门。
- [E7精确触发边界修复提案（2026-07-16）](../e7_exact_trigger_boundary_fix_proposal_20260716.md) — 正式源未改、102/120断点保留；单行边界修复已在临时影子副本通过机制门10项和相邻动态/充电测试93项，正式应用和恢复仍须用户明确授权。

- [Project plan overview](project-plan-overview.md) — global ReSETP paper plan: done / in-progress / left / ETA; role rule (Claude thinks+prompts only, Codex executes, no workflows)
- [Read me first for agents](../READ_ME_FIRST_FOR_AGENTS.md) — 强制启动入口: Codex/Claude 每轮先读, 再读 HANDOFF/PRD v2/planning map/memory/MASTER; 实验必须留四件套和 HANDOFF/memory 记录
- [Communication style（兼容入口）](feedback_communication_style.md) — 旧链接保留；规则正文已合并到 `user_operating_principles.md`，不得继续使用“总是先确认再执行”的旧概括。
- [Project PRD execution v2](project-prd-execution-v2.md) — 全项目 PRD/施工图 v2: 宏观路线、E2重点摸排、E1-E7 PDCA、DR-ALNS接入、记录制度、风险门槛; C1已判5174同值平台为ARTIFICIAL_HOMOGENIZATION，C1-R2=PARTIAL_OR_WEAK_SUPPORT(H2确认/H1未确认)，G4/G5冻结
- [Figure redesign task](figure-redesign-task.md) — remake paper figures to top-journal level via Zotero exemplars, pixel-locked specs, Codex only fills data; F4 is a blank/broken figure; blocked on Zotero connection
- [E3 full paper preview 20260713](../../paper_submission_final/e3_full_preview_20260713/E3_FULL_PAPER_PREVIEW.md) — complete paper-body preview from the first six-layer plan through strict v11 and the fixed ownership-mismatch branch; only approved reference shells are used for figures, while cooperation, fairness, vehicle, and mismatch evidence remain explicit tables with budget and extrapolation caveats
- [ALNS crush root cause](alns-crush-root-cause.md) — PPO/DR lane 全程日志; winner kernel £4878 健康 + venv 漂移教训; 2026-06-19 离线体检①=HALT_COLLECTION_COST + 监督探针破局设计; user纠正真目标=DR-ALNS真训练+创新干过GA-VNS/GA/PSO(非碾SA)
- [Algorithm pivot: CA-ALNS](algorithm-pivot-ca-alns.md) — 历史快照(2026-06-14/15); 注: 其"目标=碾压SA"口径已纠正(见 project-plan-overview 真目标=DR-ALNS真训练+创新, 干过GA-VNS/GA/PSO); rerun all experiments; carbon numbers change
- [Baseline algorithm catalog](baseline-algorithm-catalog.md) — Zotero整理: 各论文主流算法+item key+复刻来源+推荐基线集; keystone=周鲜成2021综述(在目标期刊); ALNS/DR-ALNS要赢过这些(GA/PSO/SA/TS/ACO/VNS/GA-VNS+混合)
- [IWD fidelity closeout](../iwd_fidelity_closeout_20260712.md) — IWD按文献公式修复并完成一次来源参数救援短门；两轮均未过P3/P4/P5，降级为失活/简化适配基线，不重跑90行，不改E2封存810行。
- [Deferred instance robustness](deferred-instance-robustness.md) — later task: re-run carbon stress on three-shift 100/150/200c instances (150/200 not generated yet)

- [Instance lineage](instance-lineage.md) — formal L-main v2 = 9 threeshift ladders only; mixed23/100-01 ARCHIVE_ONLY
- [ReSETP ALNS full independence](resetp-alns-independence.md) — algorithms/resetp_alns package; no N-Wouda runtime; PROVENANCE
- [Control console](control-console.md) — root one-click CONTROL_CONSOLE + PARAMETERS; input/output layout
- [M1/全项目] 2026-07-11（7.31 收稿调度裁决）：研究计划按证据依赖串行推进，只有已经批准的实验批次内部按 instance/seed/algorithm/parameter task 并行运行以利用 CPU；不得把“实验任务并行”误写成 E2、机制、动态、DR 等研究线同时推进。当前 30 次 E2 稳定性门结束后冻结算法方向：通过则只做一次最小正式 E2，不通过则降低算法主张；两种情况都禁止继续 E2 rescue。路线与止损日期见 `docs/handoff/project_parallel_execution_plan_20260711.md`。
- [M1/全项目] 2026-07-11（白话总实验管理体系）：`docs/handoff/project_experiment_master_plan_20260711.md` 是E0--E7总施工图，逐项写明科学问题、设计、任务量、指标、通过/HALT、论文表图和降级路径；`docs/handoff/project_board_20260711.md` 是实时看板；`docs/handoff/templates/EXPERIMENT_CARD_TEMPLATE.md` 是每批实验启动门。管理规则为一个科学问题在制、批内任务并行、结果绑定四件套、7.28后禁止探索实验。
- [M1/E2] 2026-07-11（staged hybrid稳定性门完成）：100c/150c/200c×seeds1--5×hybrid/LNS共30次全部OK、零违规、全部4000/4000 eval；hybrid相对LNS三个规模平均改善6.4477%/0.6880%/14.0797%，11/15成本胜，verdict=`STAGED_HYBRID_STABILITY_SUPPORTED`。边界：280kWh诊断、非正式T3、碳算子关闭。依7.31计划冻结hybrid并拒绝九规模/长预算继续调试，下一步仅做健康基线体检和一次最小正式E2。
- [M1/E2/E1] 2026-07-11（E2冻结、E1主结构通过）：E2 tag=`e2-submission-20260711`固定commit `0124623e`和hash锚，不再改写。E1在commit `c20dae18`完成280kWh最小结构门：20条mixed+5条CV-only零违规满4000；200c mixed的EV客户/需求/距离份额约86.1%/87.2%/82.2%，约60次充电，相对CV-only 4胜1负、平均便宜0.671%。EV-only 5条为`NOT_FOUND`而非不可行证明。详见`docs/handoff/e1_280_structure_closeout_20260711.md`。
- [M1/E3] 2026-07-11（累积消融部分支持）：200c×M0--M5×5 seeds=30/30零违规满4000，commit `b9a59c46`。时变碳同路线充电5/5降EV间接排放、平均20.96%；协同成本4胜1平但跨场仅1/5触发；theta=1公平可行5/5但M4天然已满足，公平绑定0/5。verdict=`E3_PARTIAL_MECHANISM_SUPPORT`，碳转E4、公平转E6。见`docs/handoff/e3_cumulative_ablation_closeout_20260711.md`。
- [M1/E2/E3/E6] 2026-07-11（Claude 顾问审计：跨场费口径分叉根因链）：E2 冻结 270 行未收论文声明的 c^tr=95£/客户（逐位复算证实 transship=0），冻结解实际跨场 hybrid 278 vs LNS 758（45 次合计）；协同被 95>80>85 算术锁死+全局车队池+两场均衡三重压制；公平是协同下游，E6 现行 θ 网格整段跳过实测 binding 区 1.0000-1.0146；E1（免费口径）与 E3（收费口径）将互相矛盾。建议与决策树见 `docs/handoff/claude_advisor_findings_20260711.md`；R1 口径三选一待 user 拍板，E6/E7 设计必须等口径决定。
- [M1/全项目] 2026-07-11（Claude 顾问问题总登记册）：`docs/handoff/claude_advisor_issue_register_20260711.md`——A 目标函数保真度集群（跨场费/公平关/配额 quota=0 vs CE=0.8E^base/TeX B=80）、B 算法故事（基线仅 4 个缺 GA-VNS、无 Wilcoxon、摘要无算法创新主张、4000 预算说服力）、C 叙事（E4 碳价 30 倍阈值故事在 280 场景翻转须换故事、E7 标题级承诺 HALT、顶刊标配未决、D=2 车场、实例命名 vs 实际客户数）、D 管理（看板与用户标准错位、7/31 排不下须做减法、Zotero 阻塞、HANDOFF 瘦身）。含一页决策地图九项，决策待 user 统一拍板。
- [M1/E2项目4] 2026-07-11（精细碳搜索短门）：提交`6d7167ed`新增隔离开关下的整段充电碳积分、统一成本选站/择时、高碳邻域删除和充电重建；默认E2算法身份未变。微型测试11项通过；`e2_refined_carbon_short_gate_20260711/`共12/12满400评价、零违规、保存解独立复算/hash通过。6/6配对有真实决策变化，EV间接排放合计-118.803kg、成本合计-77.294，但存在1组排放略升、1组成本+40.108，且部分收益混有路线/用电变化。verdict=`REFINED_CARBON_SHORT_GATE_SUPPORTED`，不等于纯择时贡献成立，也不授权4000门；下一步先完成E1--E7零搜索统一合同审计。
- [M1/全项目合同] 2026-07-11：E2冻结270/270解用当前checker只读回放均零违规、原免费跨场成本匹配；nearest-depot补算跨场hybrid278/LNS758。200c冻结hybrid在95英镑+E3独立收益基准下theta=1为0/5，费率0也仅1/5，说明E2只能保留为松弛合同下的内部算法比较，不能事后称完整公平模型。E1--E7合同矩阵已输出，当前阻塞=`BLOCK_FORMAL_E4_E7_PENDING_SUBMISSION_CONTRACT_DECISION`。证据`baselines/contract_audit/e1_e7_submission_contract_20260711/`，拍板单`docs/handoff/e1_e7_submission_contract_decision_20260711.md`。
- [M1/E2最终合同] 2026-07-11用户拍板：E2直接做9个L-main v3自有算例×9算法×10次×4000评价=810行，不设ALNS单独完整模型复核层；复用冻结225行主表，只补585行。280 kWh主场景、80 kWh备用，E2公平off、跨场费0。自有算例不套BKS/AVG/Gap%标准表；公开标准算例+BKS/AVG/Gap%+未经改动Goeke原始算法挂为E2后补实验。E2结束立即准备E3。客户归属、跨场费用和线性碳配额均保持研究挂账，公平只在E6及明确公平交互实验中从搜索阶段启用。唯一拍板单`docs/handoff/e1_e7_submission_contract_decision_20260711.md`。
- [M1/算法创新边界] 2026-07-11：当前 `staged ALNS--LNS hybrid + carbon-aware charging schedule` 是针对问题的组合式创新，不是已证明的全新ALNS。可主张400+3200+400的分阶段搜索和固定路线/车型/电量下的低碳充电重调度；不可主张独创ALNS、全新strong-bridge或路线/车型/站点/时刻全联合碳搜索。E2排名只证性能，不证新颖性。E2后补最近文献对照、普通ALNS/直接强重组/分阶段/分阶段加充电调度四臂消融、来源与复杂度边界；不足则维持“有效混合求解框架”表述。详见`docs/handoff/e1_e7_submission_contract_decision_20260711.md`和问题登记册B4a。
- [M1/E2长跑补充纪律] 2026-07-11：代表门18行通过后复用，正式剩余567项；E2统计锁定90组配对Wilcoxon符号秩检验+原始p值+Holm校正。长跑期间可做客户归属、跨场费、线性碳配额三项只读文献核对，但不得启动E3--E7实验或改变E2合同。Goeke公开标准算例+BKS/AVG/Gap%在7月24日前仅做可行性评估，做不完明确降级。
- [M1/碳配额建模核对] 2026-07-11：目标期刊陈婉茹等（2023）式(5)和Liu等（2020）式(15)均采用`碳价×(实际排放-配额)`；两文都明确说明外生固定配额不改变最佳路径，只平移碳成本/总成本。本文`p_car(DeltaE-CE)`因此视为正确的限额交易会计模型。后续不再跑CE改变路线的空转敏感性；真正决策杠杆为碳价与可变排放（含时变电网碳强度）。尚需统一论文CE参数口径；硬上限/分段价等若未来采用，属于新模型，须另行报批。
- [M1/客户归属文献核对] 2026-07-11：L-main现有`Node`/bundle没有owner或公司成员字段，1425条归属表明确由`nearest_depot_by_bundle_distance`事后生成，无法恢复真实历史归属。陈婉茹等（2023）只在初始解按最近车场分配、正式模型允许全局服务；Soriano等（2023）把独立经营所属车场`d_i`作为输入；Liu等（2020）按合作前公司自有客户定义；王勇等（2023）用时空聚类后最近中心指派。结论：最近车场可作为中性、可复现的合成独立经营基线，但不是行业规定或原始真值。E3/E6前由用户确认并冻结映射/hash；跨场费仍待查。
- [M1/跨场费用文献核对] 2026-07-11：未发现`95 GBP/跨场客户`行业统一价格，`prices.py`也明确将95标为代理。Gansterer/Soriano类合作模型主要算真实行驶成本并用收益下界或补偿处理企业利益；Fernández等（2018，DOI `10.1016/j.ejor.2017.08.051`）在需要货物跨车场搬运时按每对车场一次往返收固定启动费，测试`F={0,20,50}`为无量纲算例成本；王勇等按集中运输时间/距离计费。结论：当前`95×跨场客户数`费用对象和量纲均无充分依据。0可作完全共享基线；非零项应按真实车场间运输建模，或作为利润补偿；每客户代理若保留只能作明确标注的摩擦敏感性。最终模型待用户拍板。
- [M1/E2项目6只读补算] 2026-07-11：冻结280 kWh hybrid的45组aware/naive同路线保存解完成零搜索复算；45/45两臂零违规且路线、总用电、充电动作集合一致。排除15c结构性无EV后，EV客户/需求/距离份额86.082%/87.031%/81.544%，实体车辆份额64.615%；CV仍承担13.918%/12.969%/18.456%，29/40为混合解。929次、88711.268 kWh充电中911次、86737.553 kWh真实移时，同路线加权碳强度137.979降至123.605 gCO2/kWh，40/40降碳、合计1275.090 kg。全部充电发生在车场，公共站0，故当前正面故事是“偏电车+大量车场谷时充电”，不能写公共充电站选择已成立。证据`baselines/e2_alns/e2_280_fleet_charging_audit_20260711/`。
- [M1/E7新增订单服务时长V3] 2026-07-14：V2事件流漏存捐赠客户服务时长，运行时误用基础客户均值。V3为原110个新增订单补回捐赠客户原值，不重抽任何事件；排除新字段后275事件身份指纹仍为`cb81442db4225fa5f38562372a019afac1f481fa195f6256069681b821b8d391`，归属和参考发车表逐字节不变。正式加载器拒绝缺失、非正数或与捐赠客户不符的服务时长；V2搜索结果不作正式E7结论。详见`dynamic-demand-integration.md`。
- [M1/E2十种子配套拍板] 2026-07-11深夜：HGS=展望地位同DR-ALNS；4000完整评价vs文献25000迭代汇率差须明写+16000预检8项已授权顺手跑；F2收敛曲线/基线参数表/环境声明（可选附录）批准；自家算例连组内gap列都不报、BKS/Gap只在开源算例集；执行权交还Codex，收口链=verify→F2→16000预检→参数表→封存。见claude_advisor_issue_register_20260711.md末节。
- [M1/E2十种子并行调整] 2026-07-12：8逻辑核、8GB内存的M1机器从2 workers安全切换为6 workers；旧父进程和在途任务已清理，正式矩阵从608/810断点续跑。6 workers为当前上限，异常时退回4；不改变实验合同或结果口径。
- [M1/E2转X86交接] 2026-07-12：E2封存后才迁移到与`dr-x86`同机的16线程、16GB X86环境。迁移前必须完成verify/F2/16000预检/参数表/提交封存；迁移后先做依赖、hash、单解复算和极小E3短门，再从4起步、稳定后通常上到8 workers。清单见`docs/handoff/e2_x86_migration_handoff_20260712.md`。
- [M1/投稿合同拍板①跨场费] 2026-07-12：用户拍板主结果c^tr=0（完全共享）+0/10/25/50/95摩擦敏感轴（标注无现实标定代理）；真实距离建模挂账为可选加强，不改模型公式（用户原则：非致命漏洞不动建模）。与冻结E2实际口径一致，E2不动；E3须按此重跑。E4故事/客户归属/碳配额/跨机数字规矩等其余拍板项讨论进行中。
- [M1/投稿合同拍板②E4换故事] 2026-07-12：E4改为"碳价×充电时机"（0.5/1/2倍扫描，指标=充电搬动量/时段/碳降/成本，边际车型分工副线；主打图=充电搬家图+碳价响应曲线；管理启示重写）。旧"30倍阈值油换电"叙事作废，配额扫描轴删除。预注册两种诚实写法（响应显著/响应平各有可写结论）。不改模型公式。
- [M1/投稿合同拍板③④] 2026-07-12：③客户归属=冻结最近车场1425条映射（论文明写合成假设），不均衡归属场景计入手册作备选；④碳配额=实验保持配额0全额计价、论文口径对齐、删"配额影响路线"说法；用户要求配额讲出真故事，Claude"碳账户"方案被评"勉强凑数"未采纳，改为先查用户新补Zotero文献再议；硬上限/分段价变体挂账，新文献支持可重议。
- [M1/投稿合同拍板⑤跨机规矩] 2026-07-12：三条规矩确认（一张表一台机器/跨表只谈%/每表记出身）；用户偏好E3--E7尽量统一在M1，x86只作溢出备用，覆盖迁移交接单"以X86为主"默认。
- [M1/碳配额故事定稿+显著性核验] 2026-07-12：配额故事="总量管得住、时间管不住"（MS2025加州碳交易实证支撑，用户认可）。核验事实：280场景充电碳≈总碳一半(487/993kg)；择时充电省总碳约11.3%；锚定日真实碳强度49-199、日内4.1倍摆幅；30个真实日波动1.3x-4.5x可做全真实"电网波动日"敏感轴；时间盲账面低估真实排放约16%(初步,待E4零搜索正式化)。用户新补6篇OM文献已映射到E4/E6/E7故事层。
- [M1/E3--E7总设计定稿] 2026-07-12：用户批准，设计权威源=`docs/handoff/e3_e7_experiment_product_design_20260712.md`：七项拍板决定汇总、六章故事线一章一主打展品、通用合同、WP0前置（含prices.py c_tr 95→0四同步）、E3主梯30+摩擦轴25、E4三部分、E6两段式绑定聚焦、E7四臂×5流三交互、E2b四臂算法消融、产物规格总表、7/13--31排期（M1富余）。各批开工时Claude在对话中交付Codex提示词。
- [M1/图表新旧对账] 2026-07-12：总设计第9节=逐张判定表：07-03样板包为最终底版、壳目录v1为壳权威。T3删组内gap列和等墙钟占位列；T5加上一层Δ%+充电碳列；T7档位0.5/1/2；F5沿Qiu壳字段本地化（旧F5b废弃）；T9主表改四臂、事件流版降附录；新增四件绑已读壳（Shi Fig5/Fig7、陈婉茹图4a/表7）；T6/F3/F4/F7等原样沿用；废弃清单确认。mock字段=正式CSV契约。
- [M1/E2正式收口 2026-07-12] E2十种子810行已完成正式verify：9算法×9个L-main自有算例×10种子×4000完整评价，810/810零违规、当前checker复算通过、解和hash完整；总排名主算法`staged_hybrid_carbon_aware`第一，判决`E2_10SEED_PRIMARY_LEAD_SUPPORTED`。自有算例不报BKS/AVG/Gap%，Goeke标准算例和未经改动Goeke算法后补。
- [M1/E2收口配套 2026-07-12] F2收敛曲线和九算法参数附录已生成；formal目录819个AppleDouble元数据已清除并记录。2评价接线小测通过后，8项16000代表预检已启动，独立于810行主表，使用冻结执行提交和6 workers；异常只停最小任务并断点续跑。
- [M1/E2长预算预检收口 2026-07-12] 8项16000评价代表预检全部通过：8/8精确16000、零违规、解/hash齐全；hybrid总成本19933.954245低于LNS 22784.898943，3个旧4000负例全部改善，200c seed4强胜样本保持19.7043%优势，判决`E2_16000_PREFLIGHT_SUPPORTED`。这是补充稳健性证据，不改810行主表，E2线至此封存，下一步转E3。
- [M1/WP0 2026-07-12] E2封存后完成投稿合同冻结和E0地基复核：合同判决=`E1_E7_CONTRACT_FROZEN_BY_USER`，主场景280、c_tr=0、配额0会计项、最近车场映射冻结、公平仅E6/E7搜索臂启用；E0九个L-main v3共享起点全部零违规；3个E2冻结解在280覆盖下用新默认c_tr=0复算成本逐位一致。产物见`baselines/contract_audit/wp0_e0_check_20260712/`、`wp0_e2_replay_20260712/`和`docs/handoff/tex_sync_debt_20260712.md`。本WP0不启动E3–E7正式搜索。
- [M1/E2-IWD忠实度收口] 2026-07-12：按批准的IWD公式完成源码修复和唯一允许的来源参数救援。正式文献参数短门与`zhang_scaled`救援均为18/18行、800/800评价、零违规、解/hash齐全；两轮均P1/P2通过但P3/P4/P5未通过，判决=`IWD_FIDELITY_GATE_FAIL`。IWD降级为失活/简化适配基线，不重跑90行，不改E2封存810行；论文不得再写“九个基线都健康”，IWD须单独标注或后续按原文独立复刻。证据见`docs/handoff/iwd_fidelity_closeout_20260712.md`及两套gate目录。
- [M1/提示词骨架入册] 2026-07-12：应用户纠正（骨架进文档、Codex照单开工、不现场设计），总设计新增第16节=8个冷启动自包含提示词骨架按执行顺序：0 WP0（已执行存档）→0b合同公平条款修订（必做：WP0冻结的合同仍是旧"公平仅E6/E7"条款，须按第15节第2条改为系统方案实验全启用）→1 E3机制阶梯（主梯30+缩减梯20+摩擦轴20+四项零搜索审计）→2 E2b四臂消融→3 E4/E5碳批次→4 E6绑定聚焦→5 E7四臂动态→6表图统一生成→7写作欠账。【待填】参数（E6的r0网格、E7阶段预算）由上一批产出定。终局拍板=第15节（桩数A不设卡、公平范围A、E4数据源改M5解、E7公平基准C逐阶段因果重算、措辞写作五项）。
- [M1/提示词骨架详版+词典] 2026-07-12：应用户"像提示词一样细致、像词典一样全面"指示，第16节升级为逐字可发详版（每骨架含前置验证/产物目录命名/精确任务步骤/字段清单/验收打勾清单/判读引用/汇报模板/机时估算；E2b四臂A1-A4与E7四臂B1-B4精确定义；E4碳价三档绝对值0.02517/0.05034/0.10068；E6网格构造规则预注册）；新增第17节词典（环境/冻结锚/算例数据/入口/证据目录/39+新增字段/判决词/术语/统计/未决清单）。已吸收Codex新进展：IWD_FIDELITY_GATE_FAIL→论文改口"八健康基线+IWD简化适配标注失活"（写作清单第16条）；TVCI-ALNS公开名入术语词典与摘要定稿条目（机器标识staged_hybrid_carbon_aware不变）。
- [M1/TVCI-ALNS命名] 2026-07-12：用户将当前创新算法暂定命名为`TVCI-ALNS: Time-Varying Carbon-Intensity-Guided ALNS`，中文为“时变碳强度引导的自适应大邻域搜索”。新增代码展示/API名与中英文全称；`staged_hybrid_carbon_aware`继续作为封存E2原始证据的兼容机器标识。论文口径明确：TVCI-ALNS对应现有分阶段ALNS--LNS搜索内核加固定路线充电时刻碳感知重调度，不宣称全新基础ALNS或全联合碳搜索。
- [M1/E3结构审计] 2026-07-12（封存前发现，待拍板）：M0子搜索车队无上限（子包漏num_cv/num_ev）+打包纯改标签无时间检查+协同臂锚死M0（开新EV路由门被趟数堵死）→旧E3四个种子M1路由签名与M0逐位相同，"协同4胜1平"系化妆差异。骨架1"逐字一致"会继承此链，fee=0只解一把锁。三选项待用户拍板（推荐零改动加预注册诊断+无锚定M1探针5次）。详见`docs/handoff/e3_m0_search_asymmetry_audit_20260712.md`。
- [意外价值台账] 2026-07-12：`docs/handoff/serendipity_ledger.md` 建立并长期维护——实验过程意外的唯一集中登记处（包装成贡献点/故事/教训），15条初始条目含维护规则；变更日志记"发生了什么"，台账记"这件意外值多少"。
- [M1/E3干净结论研究计划] 2026-07-12：两轮文献+源码+旧30解回放完成。当前问题不是 IWD，也不是纯 ALNS 弱：论文写一车一趟/有限 m，代码以 #T 贴多趟标签但无时间/地点/电池衔接，M0 还无上限而 M1 被 M0 锚定。30/30 保存解按当前时间递推有物理车路线重叠（M0 596 对），不能当合法有限实体车队证据。80 GBP 固定费在参数文件明确为每班次/每趟派遣成本，现有按路线收费可保留；正式多趟模型只需在论文中明确这一点。`e3_clean_conclusion_research_plan_20260712.md` 定义：D1=采用文献多趟语义及两阶段排程实现（模型变更，须用户批准）或承认松弛口径；D2=各场资产口径（总14/14但无分场原始数据）亦须批准；推荐 70-Clean 以5行无锚定同资源 M1 控制替换100c M5，70完整性门过后加200c M0-M5 seeds6-10共30到100，升级不看结果方向。D1/D2 前仅做只读审计/设计，不开正式E3，不让E6/E7复用M0。
- [M1/E3 formal multi-trip feasibility] 2026-07-12：user 已批准 D1（真实实体车多趟）与 D2（合法独立M0实际资产上限，不设7/7）。对旧200c M0五个seed按满电出发、返场补电、同home depot/同车型连续趟的文献语义做固定路线精确趟链覆盖：最少EV=`51/55/52/55/50`，原始总上限只有14；CV=`6/3/4/3/4`。所有覆盖MILP为Optimal，seed1的59条EV路线中52条跨至少两个班次，说明旧#T打包不能靠排程补丁合法化。判决=`HALT_E3_FORMAL_TRIP_CONSTRUCTION_REQUIRED`：不得按第16节旧骨架启动70次，不得把51--55当新资产，E6/E7不得复用旧M0。下一重大决定=授权正式多趟路线构造重建，或降级为明示松弛敏感性；证据=`docs/handoff/e3_formal_multitrip_feasibility_audit_20260712.md`。
- [M1/论文定位终局裁定] 2026-07-12：三轮辩论（Claude"中心=时间"vs ChatGPT"主体=协同调度"）后 Claude 终局拍板=双层定位：主体=动态协同多车场油电混合车队调度，中心主张=分时碳强度使充电时机成为真实减排杠杆、其现实价值依赖协同/公平/滚动继承共同成立、四机制交互各有展品作证；防堆砌防线=交互证据（E3阶梯/E6绑定/E7三交互）而非主体宽窄。tex病灶="中心句存在但不承重"；算法故事以E2b为准；TVCI-ALNS首现必划界；充电站容量与配额从摘要卖点降级。权威口径=`docs/handoff/paper_positioning_final_ruling_20260712.md`（7条写作硬规则），仅管叙事包装，不改实验设计/模型公式/E2封存；D1多趟拍板仍先于一切包装。
- [M1/E3多趟重建裁定] 2026-07-12：用户拍板D3=A（正式多趟路线构造重建），HALT解除条件=结构可行性门。执行权威源=`docs/handoff/e3_multitrip_rebuild_ruling_20260712.md`：新严格检查版本化隔离、严禁重判E2/E1封存件（论文两层口径：正式模型严格多趟/E2路线级松弛比赛）；算法=C档（0124623e+40bd2883底座+合法性层+接口层，新冻结E3执行提交）；排程进搜索非事后过滤；废M0热启动、各层独立合法起点、恢复原70矩阵（30+20+20，控制臂撤销）；D2=排班最少车数目标、M0先14/14闭合、按seed冻结、失败HALT_M0_ASSET_CAP；新展品=每层实体车数/"合作让车队变小"；红线7/19结构门不过回落B口径、7/23未收口不升100；E1最小严格镜像挂账、E7趟链状态继承、TeX欠账+5项。cost/evaluation不动，check仅版本化新增。
- [M1/E3 22kW证据纠偏] 2026-07-12：60kW工程草稿结构/搜索/4000评价结果已改判；排班器从统一`prices` 取现22kW。22kW诊断的同一路线双口径结果：补满仅得21 EV贪心见证（不是全局不可行证明），部分补能得14 CV+14 EV合法见证；正式口径待用户在完整证据后拍板，70未启动。Volvo FL官方页面280--565kWh/43kW AC/150kW DC已记录，22kW仅作Mer AC代理。另已修新E3严格模式的开新趟门（数实体车而非数路线）并记录公共站拒绝。证据`e3_charging_power_and_collaboration_evidence_20260712.md`。
- [M1/E3实体车结构门] 2026-07-12：第一批通过。新排班合同不动旧检查/评价器，6项单元检查+61项回归检查通过；第1个200c算例的独立/共享两案均449客户、59趟、0路线违规、14油车+14电车、最长3趟/车，判`STRUCTURE_GATE_PASS`。正式70未授权未启动；顺序仍是小规模完整搜索→正常规模速度/质量检查→才可进70。证据`baselines/e3_ablation/e3_multitrip_structure_gate_20260712/`。
- [M1/E3真实排班搜索门] 2026-07-12：新E3开关下已堵住搜索快速记录绕过实体车检查的漏洞，旧E1/E2默认不变。200次接线门与4000次正常规模门均过：独立4000次/89.60s/改5.376%，共享4000次/357.79s/改4.502%，坉449客户唯一覆盖、路线有变、严格违规0。单seed共享最终贵于独立，只记录不做门槛、不调参救方向。证据`baselines/e3_ablation/e3_multitrip_search_gate_20260712/`和`e3_multitrip_model_gate_20260712/`。正式70未启动；下一步是新规则正式任务表/字段接线和启动前检查。
- [M1/E3 22kW复核收口] 2026-07-12：正式70仍未启动。v3双口径诊断：补满贪心见证=14 CV+21 EV（非全局不可行证明）；按需补电见证=14 CV+14 EV（非最少车辆/非正式口径证明）。60kW三门已作废；22kW预备目录因证书覆盖被标`SUPERSEDED_PRELIMINARY_ARTIFACT`。当前排班器读统一参数，实体车开新趟门已修；75项回归和hash复验通过。正式规则需要用户拍“补满+精确证明”或“明确允许两趟间按需补电+重跑小门”，不得自行改22kW。证据=`e3_charging_power_and_collaboration_evidence_20260712.md`、`e3_multitrip_structure_gate_22kw_20260712_v3/`。
- [M1/E3充电规则终局拍板] 2026-07-13：用户选定"趟间按需补电写成正式最小公式组"，22kW不动，"每趟补满"降为审计对照不进正式矩阵。正式文献边界：Zhen 2020只提供趟序和相邻趟时间骨架；Keskin–Çatay 2016提供部分充电上下界和充电耗时；Diefenbach等2023直接支持趟间部分/完全补电。Claude所称“满电出发不失一般性”不适用于本文含充电耗时、分时电价和分时碳排的模型，Zhen的车场作业时间也不能冒充充电时间。本文因此保留首趟继承电量，分开写不重叠与充电空档，允许等待低碳时段。详见 e3-partial-recharge-ruling.md 与 HANDOFF 07-13 条目。
- [M1/E3按需补电公式核验] 2026-07-13：论文最小公式组已接入并编译通过；V2排班规则只补下一趟真实缺口，新增趟间电量导出到正式成本/碳账本的接口。八项独立核验8/8通过，证据=`baselines/e3_ablation/e3_multitrip_formula_validation_20260713/`；旧E1/E2未倒查、正式70未启动。剩余阻断项：搜索候选解尚未自动合并趟间充电记录，完成该接线前不得启动200/4000门。
- [M1/E3过夜自主授权] 2026-07-13：用户睡前授权Codex整夜自主推进E3全链（接线→短门→200→4000→正式70→完整性门→自动升100），"成功"唯一定义=数据质量门+三类预注册结局之一如实成立，严禁结果方向救故事；夜间只可修机械bug，模型/参数/合同冻结；M0闭合失败=HALT等用户，不自动回落B口径。详见HANDOFF 07-13授权条目。
- [M1/E3过夜补充与运行器] 2026-07-13：正式70前加seed99的400评价合作可动性彩排和展品字段冒烟；合作同时报经营采纳值与严格搜索胜出，正式按种子成套推进。严格排班/趟间补电已接入每个搜索候选，投稿合同公平范围补全并升v3；统一种子优先runner提交`4e2bc074`支持8/200/4000、70和自动补30、断点指纹、实体车证书及跨场诊断。8评价烟雾2/2满预算零违规，不作结论。
- [M1/E3 200评价通行证] 2026-07-13：提交`a60ca171`修复跨场动作因整数触发点被前置扫描占用而整批漏做的问题；`9b224df1`分开验纯合作与带公平合作；`892b3ea3`修正公平拒绝字段；`7aea308f`锁门顺序、完整hash和故事胜出边界。最终`e3_v7_clean_20260713/preflight`为4/4满200零违规，纯合作197尝试/86合法/51接受/最终1跨场，公平层明确记录262次公平拒绝，判`E3_PREFLIGHT_PASS`。v4/v5 HALT只作诊断不进正式证据。下一步为4000评价质量/墙钟门，70尚未启动。
- [M1/E3正式70前全门通过] 2026-07-13：`e3_v7_clean_20260713/model_gate`的独立/纯合作2行均满4000零违规，耗时56/119秒，合作3987尝试/1505合法/804接受/最终1跨场；样本外seed99的400评价彩排同样可动，判`E3_MODEL_GATE_PASS`与`E3_REHEARSAL_PASS`。六件展品字段已从200门真实保存解导出并判`E3_EXHIBIT_FIELD_SMOKE_PASS`。模型/源码/参数冻结，正式70按4 workers、种子成套可启动。
- [M1/E3资产冻结纠正] 2026-07-13：v7阶段间会重写资产manifest的提交号，导致任务指纹漂移，已降为诊断。提交`18c2d834`新增v2不可变资产清单（22文件逐项hash，后续只读验证）。最终唯一通行证改为`e3_v8_clean_20260713`：同一源码、同一manifest下200门/4000门/seed99彩排全PASS，零违规，展品字段齐；正式70可启动且不得再改源码/模型/参数。
- [M1/Codex额度规则] 2026-07-13：额度变化/重置立即停全部子代理；重置后用5.6 Sol medium、关闭快速模式；后期稳定长跑改5.6 Luna max、普通速度。阶段关口低频读额度。主额度由88%重置到0%后已停子代理，桌面核实当前为`5.6 Sol 中`且无快速标记。
- [M1/E3正式100次完成] 2026-07-13：最终唯一证据=`baselines/e3_ablation/e3_v11_clean_20260713/`；正式70与自动追加30均满4000评价、零违规，`final100`复算100份成本、100份实体车证书、60对同路线充电和470个阶段hash全部通过，判`E3_FINAL100_PASS`。200客户合作严格胜出6/10、平均节省0.353%，预注册多数门通过但单侧配对秩检验p=0.348、统计不显著；实体车0/10减少，禁止写合作省车；同路线充电择时3/10有效、合计减排0.764%，只作E3次要张力；公平10/10最低收益比≥1。v9的100客户车型取整超上限和v10的公平起点不可行均在正式70前机械纠正，v9/v10只作诊断。表图数据与白话报告在`final100/exhibits/`和`final100/report.md`，阅读版`report.html`只通过结构检查，未通过浏览器自动截图检查。
- [M1/E3收口监工复核] 2026-07-13：v11唯一正式版100次收口，Claude独立复算6/10严格胜出、0.353%、p=0.348逐位一致，成本分项闭合，版本链v4-v10全为正式前机械停机、无跑完矩阵被丢弃。判定=中间结局偏正：机制成立（可动/多数有利/公平真拦截/摩擦划边界），性能主张降格（不显著、不省车0/10）。论文角度："纸面协同收益在真实排班下缩水到0.35%"=诚实新发现；充电择时被压缩（3/10、0.764%）移交E4主打。下一步E4+E1镜像+E3章TeX。
- [M1/E3理想化计划] 2026-07-13：权威源=docs/handoff/e3_idealization_program_20260713.md（总设计第18节指向）。三波保守优先：Wave1已批(错配轴+探针+存在性0.959%展品+受控暖启动对照对)；Wave2挂账(边界关联移除+跨场regret插入算子,伪代码/安全接入/验证协议已定稿,一次性不迭代)；Wave3挂账(预算加深凭探针)。E2封存零影响(合同域隔离)；E4源钉死v11 M5；三把尺子并存披露。文献已核=Shaw/Ropke-Pisinger经Keskin原文第5-6页；待核=Cruijssen/Gansterer-Hartl入库。
- [M1/E3理想化支线正式收口] 2026-07-13：按用户的长期习惯“先读源码与证据、先短探再长探、非必要不跑全量、结果无论方向都完整落盘”完成Wave1。暖启动公平门控只做seed1：A=12988.0817，B=13162.5641；B尝试368、完整候选111次被公平/车队/路线挡住，合法0/采纳0，故不做十种子暖启动正式统计。25%错配正式批次10/10严格胜出、平均16.552646%、p=0.001953、合作27/28辆，独立测量D0=8油+8电/D1=8油+7电；50%批次10/10、平均24.719286%、p=0.001953、合作28辆，独立测量D0=7油+12电/D1=8油+8电。测量车辆不是新资产，合作始终14+14。证据目录为`baselines/e3_ablation/e3_mismatch_formal_20260713_25/`、`..._50/`，两档raw_runs/metadata/decision/report/每种子文件和372项hash均复核通过；`e3_idealization_audit_20260713/`把0.959420%降为“最好解对照”而非下界，把种子波动降为诊断而非p值唯一原因。判决=`E3_MISMATCH_FORMAL_IDEAL`，只对固定算例/归属表作条件性结论；Wave2算子与Wave3预算未触发，v11/E2未动。
- [M1/E3错配轴监工判决] 2026-07-13：定性成立(两档10/10、p=0.001953、单张锁死归属表、合作锁14+14)；接受对Claude两处过度表述的纠正(0.959%非下界/噪声只是诊断)。论文级硬伤=合作4000评价vs独立每场200评价的十倍预算不对称，16.553%/24.719%量级与ASSET_INFEASIBLE判定均不设防；处置=公平预算修复批(独立每场2000,合计=合作4000,v11先例)，修复前禁止引用两个百分比。详见HANDOFF 07-13条目。
- [M1/E3一页纸总览] 2026-07-13：应用户"E3失控看不懂"反馈，落盘docs/handoff/e3_one_page_summary_20260713.md——四段大白话时间线+理想清单逐项对账+最终中心句+唯一悬置事项(公平预算修复批)+用户拍板记录。用户理解锚点，重大变更后须同步更新。
- [M1/E3故事剧本] 2026-07-13：应用户"产物看不懂/没法讲故事/充电图死展品"反馈，落盘docs/handoff/e3_paper_story_script_20260713.md——论文结果章按四幕故事分配证据(真车信任状/错配主戏/充电一句话引E4/公平拦截)，正文禁用E3/M0-M5内部代号，六层阶梯表降附录，48时段双柱图剔出正文，展品生死簿一览。前置=公平预算修复批完成后才可写16.553%/24.719%。另更正Claude两处表述:E3阶梯实为五机制非"三合一";E2b排期在E3后E4前非最后。
- [M1/E3整改总计划收拢] 2026-07-13深夜：用户判定"Codex越来越乱、再让它规划会搞砸"，Claude把四份互相冲突的计划(Claude故事剧本/Codex判决八阶段/五展品施工卡/标题规则反转)裁决合并为唯一有效版=docs/handoff/e3_rectification_master_plan_20260713.md。治理规则：Codex此后只执行编号任务T1-T6不再出计划；14项争议逐条裁决(中性标题/四幕分四家住E3只答归属一问/时间线进实验设置/公平进E6/摩擦进附录/三情境并列不连线/拦截数262是Claude引用错误正式为23674/"条件性理想结局"降级为待重跑确认含车辆结论/先探针后补齐/数据契约删"无效果=回炉"条款/建论文数据层)。故事剧本已标作废，一页纸已更正两处。下一步=发T1探针给Codex。
- [M1/E3证据驱动最终拨正] 2026-07-13：用户授权独立判断且强调故事优先，旧整改总计划降为历史，当前权威源=`docs/handoff/e3_evidence_led_reconstruction_20260713.md`。新E3用全部9张正式网络、地理聚集/空间混合两类成对客户组合、每类3种子、同起点同4000评价，54/54对PASS、108次零违规。地理聚集平均节省4.156758%(7/9,p=0.1796875)，空间混合19.826082%(9/9,p=0.00390625)，同网增量15.669325pp(9/9,p=0.00390625)。空间混合27/27种子真实换场且降本；省钱来自里程11.907pp、燃油6.798pp、电1.247pp，派车固定费反增0.126pp。实体车2/9减少、4/9增加、3/9不变，“合作省车”否定；充电空档无一致方向，旧0.764%因首趟时钟语义冻结，E4新时钟重跑。正式证据=`baselines/e3_ablation/e3_paired_cost_formal_v2_20260713/`，论文两图一表与正文预览在其`paper/`子目录。长期原则：旧故事和旧实验都可被证据推翻；实验服务论文正文，但不得为了故事改结果。
- [M1/E3证据驱动重构审计] 2026-07-13深夜：paired_cost_formal_v2科学面全过(数字逐位复算/108行预算4000对称/54对同起点sha相同/分项闭合/聚集不显著如实报)；新中心句="客户组合越偏离地理服务边界,跨场重分配价值越大(混合19.8%显著,聚集4.2%不显著),价值来自缩短行驶而非省车"。两项治理阻断：cost.py/check.py时钟修复未批未提交(技术上向后兼容,须用户明批+封存证据不变性回放)；全部改动未提交须分层commit。0.764%碳冻结归E4重跑。
- [M1/论文北极星] 2026-07-13深夜：应用户"目标/问题/原创性全失控"求助，落盘docs/handoff/paper_north_star_20260713.md——重申07-12已拍板双层定位(中心=分时碳强度使"几点充电"成为被四把运营锁锁住的减排杠杆)；原创性=四交叉点(碳强度非电价/严格可行性校准/四机制互锁/时间盲量化)，E3错配故事单独讲=文献旧路、作柱子=成立；实验-主张对账表判定覆盖充分、唯一大洞=中心命题直接证据未跑(E4=主检验非装饰)；两种E4结局预注册；关键路径=时钟拍板→E4→E6→E7→E2b→表图→写作。迷路即读此文。
- [M1/论文全书蓝图] 2026-07-13深夜：落盘docs/handoff/paper_blueprint_20260713.md——自顶向下：唯一研究问题→五章树(引言/模型/算法/实验四把锁/结论)→每节内容→图表形态(全部绑已批壳)→数据字段→反向实验约束。核心传导：E4须先定五字段(逐槽充电/双臂/三档碳价/双记账/新时钟)再跑否则主打图画不出；E6须带三态列+r0；E7须预写继承状态schema。与北极星配套：北极星管为什么,蓝图管长什么样。
- [M1/防嫁接审计] 2026-07-13深夜：嫁接检验法(借形不借魂;图放回源论文成立=嫁接)+逐实验审计+机制联动链(弹性→空档→签约→存续,每实验输出联动变量)已补进蓝图第5节；E4双臂充电搬家图=全文最原生一张图；三条字段级处方写死进未来任务书。
- [M1/蓝图北极星纠偏] 2026-07-13深夜：采纳Codex双审计——恢复07-12双层定位(撤"全文=时间杠杆")、四把锁降为四个并列问题、空档假说被数据证伪、嫁接检验法换防嫁接四问、E4设计重写(复算优先/网络×日统计/碳价时机分离/内部碳价)、E6描述性、E7降存续检验。真阻断=保存读取丢前夜预充字段+metadata来源号错写。待用户明批时钟修复+三项拨正。
- [M1/E3-E4读者层收口] 2026-07-13深夜：用户已批准的前夜充电语义完成保存读取往返、封存回放和来源补正；正式零搜索充电复算显示充电排放下降3.888%--4.877%，运营总排放仅下降0.352%--0.523%，95.5%--99.7%来自前夜，合作无稳定放大。E3正文分开讲“地理组织的直接价值”（成本/距离/燃油直接排放/用电量下降25.002%/35.478%/41.729%/23.869%，9/9同向）与“合作的剩余价值”（地理4.157%、7/9、p=0.180；空间交错19.826%、9/9、p=0.0039）；空档缩短只作排班紧凑辅助证据。权威预览=`docs/paper_submission_final/e3_e4_story_20260713/PAPER_STORY_PREVIEW.md`，3图2正文表坚持一件展品一件事、读者层无内部代号、引用就近。网络直径复算168.716--248.085公里，统一称基于英国城市坐标构造的区域/城际场景。北极星/蓝图已改为结果驱动版；旧时间杠杆唯一主线和四把锁作废；旧`paper_main.tex`禁止零碎混入口径，待剩余实验裁决后整体同步。
- [M1/全文图表母版纪律] 2026-07-14：图表不得自拟风格或跨论文拼装。先选单篇主母版，逐项实测字体、字号、线宽、颜色、标记、图幅、图例和留白后整体复刻；主母版无同型图时，才为该图启用单篇第二母版，并完整采用其整图视觉系统、记录图号和参数、在正文引用。全部图由代码从封存数据生成并嵌入矢量PDF。E2—E3主母版为陈婉茹等（2023）；客户责任结构图因主母版无同型图，唯一例外采用Soriano等（2023）Fig.3。合同=`docs/paper_submission_final/e2_e3_preview_20260714/SETP_VISUAL_CONTRACT.md`。
- 2026-07-14 私有仓库交付入口：根目录 `README.md` 是 Devpost/OpenAI Build Week 审查入口，必须保持项目介绍、最低成本验证、论文入口、证据纪律和 Codex/GPT-5.6 使用说明与仓库现实一致。仓库 URL=`https://github.com/zlxshu/ReSETP`，保持 PRIVATE，默认分支=`codex/reporting-pipeline`；`testing@devpost.com`→`devposttesting` 与 `build-week-event@openai.com` 两份 GitHub 邀请均已创建并待接受。个人账户仓库只有协作者级，远端显示 write；若赛事要求严格只读才迁组织仓库。README提交=`fa8d0aad`。
- [M1/E2-E3论文修正] 2026-07-14：主TeX已移除表2误入的数据行、为未完成实验保留正文占位、将附录置于参考文献前并修复结论页被罗马页码污染的问题。IWD水平收敛线经原始历史复核为封存旧简化适配在221客户网络10/10次零改进；修正版也未过有效性门。因此IWD仅描述性保留，强统计按8算法总体检验和7项成对比较，正文只称TVCI-ALNS显著优于5种通过实现核查的对照算法。零新搜索，PDF 18页两遍编译通过。
- [M1/E3关账+E4已完成澄清] 2026-07-14：E3两层故事入正文关账；IWD降级+E2收紧为"显著优于5种通过核查算法"（网络为统计单位，对GA-VNS/LNS不显著如实写）合规。E4主体已跑完(9978517d)：充电环节降3.9-4.9%但系统总排放仅降0.35-0.52%、95%以上来自前夜充电、合作未放大——预注册结局二命中，摘要重心合法转移至组织价值+协同剩余价值。剩余=E2b→E4整合→E6→E7(最大风险)→组装，余17天。
- [M1/E6参与条件正式整合] 2026-07-14：正式E6的54组配对、162行搜索经独立复算，确认同起点、两合作臂同4000评价预算、成本/收益/严格多趟证书闭合且E3封存零漂移。双方均不比各自经营差时，地理聚集/空间交错相对各自经营平均节省2.613%/16.590%；参与底线相对不限制单方收益的合作系统成本平均增加2.061%/2.141%，逐网络范围0--7.79%/0--4.23%。因程序在三份最终保存结果的嵌套可行集内筛选，负增幅被结构性排除，符号检验概率值从论文撤销，改报效应与网络计数；正文只称固定预算内已观测方案，不称全局最优或利润分配。证据=`baselines/e6_fairness/e6_participation_audit_20260714/`，论文层=`docs/paper_submission_final/e6_integration_20260714/`。
- [M1/E7当前执行点] 2026-07-14：五条冻结订单流通过整趟发车提前量检查；连续两次零路线调整接续在第二轮停止并保留HALT。单事件100次主算法小探针真实产生38个变化方案、28个可执行方案、13个接受方案，未来部分成本降9.003%，仅解除接线风险，不是正式E7结论。入口=`docs/handoff/memory/dynamic-demand-integration.md`，证据=`baselines/e7_dynamic/e7_v2_20260714/`。
- [M1/中文论文写作纪律] 2026-07-14：新增`docs/handoff/memory/paper-writing-style.md`。论文正文必须先学习Zotero中最接近的中文运筹学/管理科学文献如何依据证据组织同类章节，再据本文事实独立写作；不得照搬句子、拼接文风、把相关写成因果、隐藏不利结果或用实验台账替代结果分析。
- [M1/停机把关] 2026-07-14：E4/E6独立复核通过(E4四格3.89-4.88%/0.35-0.52%/前夜95-99.7%逐项对上,预测捕获85-89%;E6三处数字对齐,撤符号检验理由=选择偏倚,正确)。仓库比报告新一步(8937a2df事件流重生+触发门,零保护文件改动);旧补丁清理已实际执行。三批准建议:追认清理/同意E7代表网络方案(臂按降级裁决)/同意算法治理。E7=最大剩余风险,余17天。
- [M1/E7单流开跑门] 2026-07-14：221客户seed1的55次订单变化已由合作/各自经营两边在同一每阶段400评价预算内全部接住，客户守恒通过；两次机械停止版本完整保留，最终顺序为前200次局部调整与尚未发车客户重排交替、后200次局部调整。单流10.006%只作开跑门，不入论文；下一步正式五条冻结流。
- [用户长短跑执行习惯] 2026-07-14：新实验默认使用已安装的`codex-experiment-monitor`插件，监控配置必须适应任务真实写盘方式。`progress_files`只列真实增量文件；结束时一次写结果的批处理留空，不要求任务造心跳或改变输出节奏。正常`ai.enabled=false`，本地检查不耗模型额度；异常、阶段点、完成或人工检查才生成最小信息包。对话代理主动读取短跑/中程/长跑状态的最短间隔分别为5/10/15分钟，事件可立即处理。旧`scripts/run_with_status_hook.py`仅兼容既有任务。
- [用户并发执行习惯补充] 2026-07-14：8逻辑线程机器在任务独立、内存/散热/写入安全时尽量使用6--8进程；16逻辑线程机器按比例使用12--16进程，其他线程数同比换算。独立任务少于目标并发时只启动真实任务数，不复制任务凑占用；若内存、温度、磁盘争用或总吞吐变差，按实测退回最近稳定并发。已写入`project_experiment_master_plan_20260711.md`与`READ_ME_FIRST_FOR_AGENTS.md`。
- [M1/E7失败点预算检查] 2026-07-14：只重跑正式400评价批中停止的4个位置，每阶段提高到800次并用4进程并行；2/4恢复，seed2各自经营第11次变化与seed3合作第24次变化仍为800个变化方案、0个可执行方案，判`HALT_E7_800_BUDGET_PROBE`。因此不以继续加算力替代修正，下一步只在动态运行器内增加固定顺序的紧急新增订单直接插入检查，每个完整方案严格计一次，先复测仍失败的2个位置；E3及此前封存证据、公共主算法和保护文件不动。证据=`baselines/e7_dynamic/e7_v2_20260714/preflight/failed_stage_budget_800/`，运行状态钩子=`baselines/e7_dynamic/e7_v2_20260714/hooks/failed_stage_budget_800_v2/`。
- [M1/E7双触发正式口径纠正] 2026-07-14：事件生成器原本按“累计8个事件或距上次调整满3小时，先到者触发”计算触发时刻并据此筛选可撤回订单；论文贡献也声明定量--定时滚动重规划。近期逐事件运行把正式口径误换为55次立即响应，最短事件间隔仅9.34秒而单阶段曾达523秒，不能保证上一轮在下一事件前完成。正式E7因此恢复双触发：五条流分别7/8/7/7/7次调整，两臂合计72阶段；现有事件无需重生，因其资格本就按更晚的批触发时刻锁定。逐事件400/800及服务时长V3下400回放（1/4通过）统一降为高频压力诊断，不决定正式预算或算子。正式单流先行，必须记录每批事件、触发原因、忽略事件、实际计算时间与下一触发余量；忽略事件非零或未赶在下一触发前完成即停。
- [M1/E7迟到变更处理规则] 2026-07-14：双触发首流400评价门中，各自经营7/7批完成，合作在第3批因事件20（需求变化）和21（取消）所在整趟已于前两批重排后发车而停止；这不是搜索不可行，也不是事件重抽依据。已发车整趟继续执行、不回滚装货与路线；迟到的取消/改量明确记为`ignored_locked_event_ids`，新增订单绝不允许忽略。每批事件必须由“已应用+因发车锁定”两类无重无漏地覆盖，迟到变更数量作为动态压力结果公开。第一批8评价接线门2/2通过；回场再装货规则另由7项测试锁定。下一步按此规则重跑同一首流，仍要求客户守恒和计算赶在下一触发前完成。
- [M1/E7车辆状态感知修补] 2026-07-14：双触发失败根因是随机造路线时未看当前20辆实体车的车场、车型、回场时刻和电量，400增至800也不稳定。E7运行器新增确定性当前状态感知重排，不读未来事件、不改公共主算法或保护文件；独立臂仍锁原车场，完整候选一次预算对应一次严格排班检查，搜索前车型尝试另列。17项小测试通过。三个已知停止位置全部越过且客户守恒，判`E7_BATCHED_REPAIR_KNOWN_STOPS_PASS`；只授权下一步400次seed1双臂完整流，不能写论文结论。证据=`baselines/e7_dynamic/e7_v2_20260714/preflight/batched_repair_known_stops/`。
- [M1/E7双触发完整单流门] 2026-07-14：seed1合作/各自经营以每批400次完成全部7批，14阶段客户守恒和下一触发前完成均通过，判`E7_PAIRED_PREFLIGHT_PASS`。两臂合计5600预算，另有12次搜索前车型尝试和5514次完整候选检查分列；4条迟到取消/改量按已发车整趟不回滚记账，新增订单无忽略。合作成本相对各自经营为-9.953%，不利结果保留但不参与开跑门；下一步同合同五条流正式批。证据=`baselines/e7_dynamic/e7_v2_20260714/preflight/batched_stream1_400_asset_aware/`。
- [M1/E7五流机械批与同起点纠偏] 2026-07-14：旧合同五流×双臂共72阶段、28800评价全部跑通，事件、预算、运行时客户守恒、时间与哈希机械门全过；但合作/独立分别从E6 no_loss/independent起步，起始成本已差4.100%，五流节省混有起点和动态路径差异，不能进论文。批次完整保留为机械证据，下一轮两臂统一从independent冻结方案出发，仅切换跨场权利，并补逐阶段20辆车状态、客户集合、锁定动作、最终解与证书。
- [M1/E7同起点接线门] 2026-07-14：V3两臂统一从E6 geographic seed1 independent冻结方案/证书起步，只切换跨场许可；逐阶段20辆车状态、锁定路线/充电、客户集合、方案/证书、动态新增跨场名单和最终解均落盘。27项测试与seed1首批两臂各8次评价通过，同起点/预算/动作菜单/状态/客户/哈希全闭合；0.065%节省仅为接线现象，不门控后续。
- [M1/E2b-E3-E6正式补强] 2026-07-15：E2b 45个成对单元证明分阶段单独平均变差77.166、加入专用跨场算子后平均改善292.681、固定配送后的充电择时39/45降电动车间接排放；E3中等责任正式档使9/9网络斜率为正但仅4/9严格单调；E6五档270点中174次真实搜索、96档自然复用，地理聚集/空间交错保障到双方不吃亏的平均成本增幅为1.8956%/0.3857%。三项均已进入正文，禁止把不利或平台结果抹平。
- [M1/E7正式批前证据合同] 2026-07-15：V4冻结3网络×2责任×5流的双责任共同可响应事件，四臂为完整机制/禁止合作/不设参与底线/一次顺序插单。不可执行延续作为臂结果保留，不删除流、不扩预算。全日载荷增加逐次充电合法窗口见证：触发前已完成者仍须触发前完成，触发时进行中者固定时刻，缺少前趟证书者不向历史外推。V5 120任务预检通过；30份完整机制方案×28日电网日干运行840行，零搜索且路线/充电量哈希零漂移。
- [M1/E7可提交证据封装] 2026-07-15：最终`sessions.json`是120份会话权威载荷，`.tasks/`仅用于断点恢复并受`.gitignore`排除，因此正式`artifact_hashes.json`也排除`.tasks/`，避免新检出引用缺失文件。V5运行时含断点的132项哈希零失败，提交版13项哈希零失败；50次评价正式矩阵已由6 workers在事件驱动监控下启动，结果出来前不得预写方向。
- [M1/论文研究生产线] 2026-07-15：新增`docs/handoff/resetp_research_experiment_writing_quality_gates_20260715.md`，把用户提供的方法选择性转为ReSETP质量门：问题—可反驳主张—必要方法—对比证据—边界；每张图表按现象/数量/机制/边界解释；不利结果、失败臂和卡点是边界证据，不能被均值抹平。论文引言改为运营问题优先，贡献收束为三项。`baselines/paper_story/audit_20260715_paper_evidence_boundaries.py`负责从E2b/E3/E6/E7封存文件反查论文，当前只允许`--allow-pending-e7`；E7完成后最终模式必须通过。
- [M1/E7预封存审计纪律] 2026-07-15：正式矩阵监控完全交给hooks，对话代理不轮询。安全时用空闲能效核运行独立低优先级验证，但不复制正式任务、不改正式worker。预封存验收器已增加精确120任务矩阵、30×28同日电网集合、经济账本闭合、受控失败和响应时限检查；滚动充电边界、共享桩容量、路线/电量哈希及排放复算改由`audit_e7_replay_invariants_20260715.py`生成独立四件套后再接入总审计，避免修改受保护重放脚本。这些未提交准备不等同于正式证据。
- [M1/完整目标终验] 2026-07-15：`audit_20260715_paper_evidence_boundaries.py`不再只核E2b/E3/E6/E7；新增E1/E2历史清单适配和封存Git树双证明。E1旧清单50项、E2旧清单1335项哈希全过，完整目录分别相对`28c91128`和`1180abf3`零漂移；E2两份同提交参数表保持“旧清单例外+Git树覆盖”，不重写历史清单。另锁定统一中英文题目、无附录和五章顺序；pending审计通过但E7仍未就绪。
- [M1/论文构建终验] 2026-07-16：当前主稿经统一XeLaTeX入口重编为24页A4，21个实际输入均早于PDF，日志无致命/未定义引用，核心正文可提取，首页及算法页视觉无裁切。`STHeitiSC-Medium`在旧MiKTeX下无ToUnicode，导致黑体标题提取不完整；无安全等价CJK黑体且Tectonic临时构建未成功，故保留版式并显式报告warning。故事审计现会检查输入时序、日志、PDF尺寸/页数/正文提取和构建哈希；E7表格进入后必须重编。
- [M1/E7结果叙事反向门] 2026-07-16：E7展品由三张表扩为七件套：三表、中英文摘要、正文解释和结论。生成器从独立审计的30条配对/120项任务状态和28日重放六格汇总中强制写出失败身份、改善/变差/持平、最佳/最差单元、收入--成本--服务量分解、响应时限与固定任务重放边界；摘要同时列三类对照，不按结果挑选。最终故事审计会从封存CSV重算四段文字并逐字比较；四套E7决策未齐时七件套均不得存在。条件挂钩、17项测试和24页pending稿编译通过；正式运行继续由hooks独占监控。
- [M1/最终交付记录门] 2026-07-16：故事审计现要求E2b/E3/E6及最终四套E7证据各自具备metadata、raw runs、decision、artifact hashes和report五个真实记录面；最终模式还会检查HANDOFF、总memory、动态memory和PRD memory四处的统一收口标记。pending阶段不允许提前写该标记。19项定向回归通过，保护源零改动。
- [M1/总目标完成矩阵] 2026-07-16：`docs/handoff/resetp_goal_completion_matrix_20260716.md`逐项记录总目标要求、权威证据、已证明/未证明状态和hooks后的唯一收口顺序。E7正式、28日重放、不变量、总审计、七件展品、四处最终记录和终稿终验继续标未证明；故事审计锁定矩阵关键条款，禁止用局部PASS替代总目标完成。
- [M1/E7监控超时恢复] 2026-07-16：原事件监控在健康长跑满12小时后仅按配置上限发出`TIMEOUT`并SIGSTOP同一正式进程组，不是实验失败。7个保护对象哈希与原runtime记录逐项一致后，以监控器原生`resume`恢复PID/PGID 96207，六个既有worker恢复满载；不重启、不筛结果、不改预算、种子、worker或保护源。新v2监控只把观察期限延长到48小时，使用正式`RUN_FINISHED.json`和三项结果文件，心跳只读新事件包；无事件时继续禁止轮询。
- [M1/E7收口链执行修补] 2026-07-16：hooks无事件期间只审计下游脚本，不读正式结果。修复不变量审计在仓库路径注入前导入项目包、导致直接执行失败的问题，并增加仓库外隔离加载回归；独立总审计对非空旧输出硬拒绝覆盖，冻结重放目录非空则由完成矩阵规定停下留存。29项E7/论文聚焦测试通过，实验合同和保护源未改。
- [M1/E7外部暂停时效门] 2026-07-16：SIGSTOP区间核准为13934秒。因正式动态阶段以`time.perf_counter()`计时，新增事件证据文件和只读污染门：任何PASS阶段耗时达到该暂停长度均不得作为算法时效证据，须在28日重放前停止；恢复只能沿同一断点合同重跑未获得无污染完成的原任务。同步假执行器证明普通异常不会为失败任务写完成断点、恢复只补缺失任务。独立总审计与故事审计二次强制，35项聚焦测试通过，正式运行源和结果未读未改。
- [M1/全量回归边界] 2026-07-16：项目金标准Python下`solver/tests`为633 passed、1 skipped、5 failed（639 collected）；五项已归类为旧E2保护commit、旧E5车队上限/修复诊断、native autopsy旧字符串契约或未提交论文工作树保护，不进入正式E7/论文通过证据。扫描/规模单测按当前九张正式三班倒注册表和实体车硬上限修正，AppleDouble sidecar已从源码审计排除；E7/论文聚焦套件35 passed。
- [M1/数学审计与两层模型门] 2026-07-16：`paper_math_audit_20260716.py`当前为PASS（14项通过、0项失败、1项警告），`two_layer_model_gate_20260716.py`为7/7通过并授权TeX重构；唯一警告是固定碳配额在单一价格下只产生目标常数平移，需限定会计范围。此前`HALT_FORMALIZATION`为过时快照，已同步修正HANDOFF和写作纪律；E7及下游终验仍未完成。
- [M1/充电时间量纲显式化与静态终验] 2026-07-16：在主稿连续充电核算段明确时间变量统一以秒计、30 min换算为1800 s、功率以kW计，消除`/3600`的量纲歧义；公式和封存数据未改。重新编译20页A4后，pending故事审计、数学14/0/1、两层7/7通过，改动后的22项模型/E7/故事定向测试通过；E7正式与下游终验仍等待hooks事件。
- [M1/E7运行期论文并行收紧] 2026-07-16：hooks继续独占正式E7监控；代理未查询中间结果、未改冻结合同。主稿将正式碳信用统一为`CE=CE_d=0`，分开预测/实际碳强度与排放，改用连续时间充电桩并发容量，澄清`theta=0`与移除参与约束、原责任车场零摩擦及组件D关闭碳结算的口径；清除公开正文中的母版模仿内部措辞。数学门20/0/1、两层门7/7、pending故事门和11项定向测试通过，20页A4重编和抽页目检通过；固定配额常数平移及字体ToUnicode仍作为显式警告。E7及下游总收口仍等待hooks事件。
- [M1/外部中文AI审稿意见裁决与PDF字体修复] 2026-07-16：外部AI意见只作待验假设，裁决表=`docs/handoff/setp_external_ai_review_adjudication_20260716.md`。真实问题已修：中文黑体同时可见/可抽取、样本口径与28连续日说明、零摩擦上界、国内适用边界、固定功率与运营排放边界、分阶段算法降级、表5新增CV、正式术语及摘要两情形分列。错误意见已拒绝：当前图已嵌入，公共站/车场功率为60/22kW，持续时间与碳强度不重符，负协同和LNS不显著均已公开；不因评论强制引入LCA/非线性充电、替换ALNS或改变动态扰动合同。PDF为20页A4，数学20/0/1、两层7/7、pending故事审计和9项测试通过；`CE=0`仍是边界警告，E7仍待hooks收口。
- [M1/三方审稿裁决与结论重排] 2026-07-16：Codex以仓库证据裁决，Claude审逻辑/数学，DeepCode审中文期刊表达；两顾问只读且无事实裁决权。主稿已删减过度防御式表述，按机制发现重排结论，将算法降为大规模机制实验求解工具，局限压缩为碳/物理与数据/动态两段；补定义责任偏离指数，区分E4两种聚合口径，修正图题单位与比较范围，并以GRIDSERVE/Mer UK公开资料绑定60/22kW代理值。pending-E7审计通过，E7仍由hooks独占。裁决=`docs/handoff/setp_tri_advisor_review_adjudication_20260716.md`。
- [M1/公式与算法母版对齐] 2026-07-16：主稿按陈雨蝶/陈婉茹母版补齐基础物理、模式选择与关键算法公式，共28个唯一编号、低于35；式(24)--(27)为算法规则，式(28)为责任偏离指数。源汇流和初始载重显式闭合，且审计禁止裸`qquad`进入PDF。任何后续公式或符号改动仍须重跑`paper_math_audit_20260716.py`。当前数学26/0/1、两层7/7、pending故事门通过；E7未读取，继续由hooks独占。
- [M1/投稿图形视觉硬门] 2026-07-16：正文六张外部PDF数据图须通过`audit_setp_visual_contract_20260716.py`：最终文字不低于约8 pt，中文宋体常规、英文数字Times New Roman，彩色为主且有线型/点型/纹理第二编码，禁止嵌入栅格对象。当前六图全部PASS，最小文字7.979--8.550 pt；算法流程图继续使用母版黑白语法。
- [M1/陈雨蝶整本母版量化与算法前置] 2026-07-16：陈雨蝶等（2025）24页PDF的正文语义审计确认宋体10.5 pt、一级标题黑体12 pt、二级标题10.5 pt、图表题9 pt、表内主体9 pt，27公式、7实质图、13实质表；不能把知网叠加层字体当期刊规则。主稿已把符号表压为双组四列，并按母版改成“算法流程先行—四步ALNS—TVCI—滚动”顺序；实验末加入数值实验分析讨论，结论局限压成一段。全文21页A4，数学26/0/1、两层7/7；E7仍只等hooks。
- [M1/母版摘要与关键词句式收口] 2026-07-16：摘要现用“建立可行配送趟—实体车排班两层模型”，关键词首项统一为“多车场协同配送”，E7终稿生成器同步完整模型名称。21页PDF的标题页、模型页、算法页和实验起始页已逐页检查；数学26/0/1、pending故事审计及六图视觉审计通过。当前TeX/PDF哈希=`07b41f09eba3812587269e20467946826fd03ce2076e02ee0c4748c3d8199cb0`/`9992ab2bb753028fd54c94dedf81ee72f419b0534a9ae6437a562c6cb657b461`；E7仍仅由hooks监控。
- [M1/ALNS算子说明与实现闭合] 2026-07-16：算法步骤2按真实代码拆成基础破坏、可行修复和跨场邻域，补足边际里程、Shaw相关度、regret-2/3、车型充电修复及E6双向交换与其他实验单客户移动的合同差异。22页稿算法第7--9页无版面异常；数学26/0/1、4项回归和pending故事门通过。TeX/PDF哈希=`6c988bdf76f170f8c3856cdd2b95f5372e166862ba23b7a84f2782ad43d28fca`/`8cfcd6d31a9b4e1268489e58d199c10082bcf654d15735752afdfb7279710a44`；E7继续仅由hooks监控。
- [M1/核心符号表闭合] 2026-07-16：主符号表补齐核心集合、运营时域、载重/电量边界、时间与能耗物理量；两个过长符号组在9 pt单元格内分行，重编无overfull。数学审计新增符号表防回退门并为27/0/1，pending故事门通过。TeX/PDF哈希=`96a8a02f1d81688c87ba34a4d3831b6c5657ca8f527b51b89e286be31ee7d924`/`002905c470e6cb4d71a09fe293bcda9b974c0764844f7485f0af47279b049460`；E7仍由hooks独占。
- [M1/陈雨蝶逐段逐展品硬对齐] 2026-07-16：主稿按M1的章节动作和证据节奏继续收口；表内正文由约6.5 pt修正为8.97--9.00 pt，三线表0.40/0.30 pt，参数表无竖线。收敛图按M1图4重绘为近方形（宽高比1.067），插入0.56版心后最小字8.098 pt；图5统一CO₂e口径，流程图弱化负消融的“分阶段”视觉中心。完整句法与图表量化矩阵见`chen_yudie_2025_master_reverse_engineering_20260716.md`。当前数学27/0/1、pending故事与六图视觉门PASS；TeX/PDF哈希=`78dc9212a45492bc5638553c76b7fd3f7f3659d418a9b8117d66f65fd9c57970`/`42e1bbc7fb1085dc9ae519943a12a533e240204f9b5ccc02f761f98fe5cd4b13`。E7仍只由hook监控。
- [M1/E7非计时异常HALT] 2026-07-16：hook捕获`PROCESS_EXITED_WITHOUT_COMPLETION`；原始异常是N322历史交错责任、stream1、无参与底线机制中未来充电动作`EV_D1_5#T2`被错误列入locked动作，`_charging_window_witness()`拒绝后退出。该异常非计时、不能归因于外部SIGSTOP，禁止自动恢复。102/120合法断点保留，最终四件套和完成标志不存在，7项保护哈希一致；现场报告=`docs/handoff/e7_non_timing_anomaly_20260716.md`。下一步只允许先做隔离状态语义复现，再决定是否批准保护调度器最小修复与原合同补齐18项。
- [M1/陈雨蝶句法母版第二轮收口] 2026-07-16：主稿在不改公式和实验数字的条件下继续删除防御腔与实验台账，压缩摘要、引言、问题描述、算法步骤和结论，同时保留负消融、非显著算法差异、反转与非单调边界。当前21页A4；数学27/0/1、pending-E7故事门PASS。TeX/PDF哈希=`d3eb25e9a76a84b806a2453a42c3fd29d563cb1cbb09d4b1345dd74fcae81f54`/`b63b13d88644afe005d48fd9b57910c5b9b745c7ecd1e58220885d83f8b92296`；E7保持HALT。
- [M1/E2公开标准算例runner加固] 2026-07-16：CVRPLIB X集6例×10种子×4000评价保持待E7释放CPU后运行。新增官方BKS标量清单、独立bundle目录和v2 runner，硬锁金标准Python/NumPy、`PYTHONHASHSEED=0`、最多4 workers、源码与输入哈希、原子断点、严格任务身份和三路独立目标复算；worker不读取公开解路线，异常也写入失败行。零搜索预检闭合60任务、18个bundle文件和9项源码哈希，相关测试21项通过。正式搜索未启动；若公开算例显示跨规模结构短板，须在E7保护运行结束后经算法大修决策门冻结新版本，并一次性重跑受影响证据，禁止拼接新旧算法结果。
- [M1/符号表版面修整与数学复核] 2026-07-16：主符号表改为可跨页9 pt长表，删除重复`V_r`定义，公式(8)引导句增加剩余空间约束，流程图“是/否”改为8 pt，并压缩参与条件、跨场算子、负消融和局限段的防御式表达。数学审计27 PASS/0 FAIL/1 WARN，唯一WARN仍为线性碳价下固定配额只平移目标值。系统MiKTeX运行时持续挂起，最新TeX尚未生成可信新PDF；旧PDF视为过时，须在隔离TeX Live或修复后的MiKTeX中双编译并逐页复核。
- [M1/E2公开基准runner二次反向审计] 2026-07-16：正式runner新增断点载荷逐字段校验和精确6×10任务矩阵门，并冻结全部119项求解源码、禁止恢复先覆盖bundle、直接读取真实candidate/repair计数、绑定CVRPLIB官网HTML哈希与六行`Opt=yes`快照。当时15项runner测试和合同SHA=`ed8f2635...39116`已被后续报告补强取代；当前状态以本索引顶部“E2公开基准报告与算法换代收口门”记录为准。
- [M1/E7恢复沙箱阻断教训] 2026-07-16：授权单行边界修复后的首次父—子恢复启动0.16秒即崩，根因=启动会话沙箱拒绝`os.sysconf("SC_SEM_NSEMS_MAX")`（ProcessPoolExecutor建池必经），非研究代码问题；现场保留于parent-child监控scenes。以同一冻结命令非沙箱重启后worker满载执行原失败任务。铁律：多进程实验runner必须非沙箱环境启动。
- [M1/pending稿证据隔离与E2大修判定门] 2026-07-16：E7七件套未形成时，主稿的中英文摘要、关键词、引言动态贡献、讨论建议与结论动态条目均条件接入，动态结果缺失分支显示“阶段稿不得投稿”，并有测试防止缺证据稿静默伪装完成；正文删去“正式实验/正式统计/仅核验”等内部审计腔但保留失败运行披露，公开适配器和分阶段负证据仍有直接边界句。陈雨蝶母版在算法流程动机处形成事实性引用，42条文献42/42均被正文实际引用，并新增双向闭合门。数学审计27/0/1，pending故事、六图视觉和14项定向测试通过。Intel版MiKTeX挂起后，原生ARM Tectonic在非沙箱环境用缓存资源双遍编译出22页A4当前PDF，逐页渲染检查通过；仅保留CMEX9/10无ToUnicode和系统字体路径警告。E2只在公开标准算例显示跨规模、稳定、可归因的结构短板时触发一次ALNS大修；若触发，冻结单一新版本、做消融和独立测试并统一重跑受影响E2--E7证据，不拼接版本。
- [M1/简体“径”字形而非仅编码的验收门] 2026-07-16：标题黑体原先虽然源字符为U+5F84，`Arial Unicode MS`却实际渲染出繁体地区字形；以后“路径/口径/径”必须同时验收源字符、嵌入字体和成品页字形。中文黑体固定为`SimHei`优先、`Hiragino Sans GB W6`次选、`Heiti SC`兜底，禁止回退到通用Unicode字体；正文保持`Songti SC`。当前21页PDF标题已为现代简体字形，嵌入`HiraginoSansGB-W6`且无`ArialUnicodeMS`，16项论文边界测试通过。此前把可提取性视为字形正确的判断作废。
- [M1/标题可见性与出版社字号终验] 2026-07-16：`Hiragino Sans GB W6`虽能显示简体“径”，但用户端阅读器无法显示全部标题，因此撤销该回退。中文黑体改为`SimHei`优先、`Noto Sans CJK SC`次选、缺失即失败；成品PDF的Noto字体嵌入且`ToUnicode=yes`，标题和各级标题可见。字号不得在正文任意改写：官方类继续控制正文10.5 pt与一级标题小四号，图表题/表内9 pt，图内最终不低于8 pt。引言引用改为单编号并按首次出现严格递增；第4章正式编号、成本分项公式和E7动态设计恢复，未封存E7结果仍由原子门隔离。公式变更后的数学审计为27/0/1，两层模型门7/7；E7与E2公开基准未闭合前仍不投稿。
# 2026-07-17 Solomon主基准、BKS与CPU口径（当前权威版）

- E2公开算法能力验证采用Solomon 56个100客户VRPTW算例为主，CVRPLIB六例降为回退。主口径是SINTEF分层目标：先最小车辆数、再最小双精度欧氏距离；DIMACS单目标/1位截断距离仅作历史回退或补充证据，不得与SINTEF主表混用。
- 本地`/Volumes/移动硬盘（512G）/VRP/算例/solomon-100.zip` SHA-256为`8a0a72cbe6b7f8f9988ace4ebde0378ec34943acaaac47f2c408915e41887747`；C101与官方VRPTWController提交`87de6d63eca1c8d4b5862c7a850fdc5a40595fe1`字节一致。论文表中的BKS只能作为候选线索，须交叉核对算例、目标、舍入、可行性与最优标志。
- Solomon 56例全部冻结为最终测试集，不用于调参。算法改进只在非Solomon开发集；主表优先PyVRP/HGS等现代强基线，弱匹配老算法不再占据主表。文献表中的`CPU`解释为计算时间，另报`RT`、`Tbest`、`Runs`以及硬件/线程；不同机器的原始CPU时间不得直接支持优越性。内部ALNS/LNS/消融在预算G0闭合后按同一完整评价预算比较。
- SINTEF零搜索门已完成：56例BKS二元组逐例复算、无BKS搜索bundle逐字段/双精度矩阵回读和CPU口径门均通过。正式560项搜索未授权；search worker不得导入BKS，父进程仅在搜索后封存复算。E7仍由hooks运行；其完成前不修改`winner.py`或启动搜索。
- 最终ALNS改进合同限定为三个结构候选，并设置G0--G4硬门。Solomon 56例全部禁调参；12个Homberger 200客户实例作开发。候选若预算外评分、连续失败或必须改变问题定义才能改善即停止。只有最终外部测试支持时才允许写优越性，详见`docs/handoff/e2_alns_upgrade_outcome_contract_20260717.md`。
- 主TeX的公开基准原子门已改为Solomon四件套：12例预注册展示表、56例类别汇总表、解释文本和来源manifest；缺一不进入PDF。当前PDF因正式搜索未完成而不显示该小节。
- 早期DIMACS bundle与PassMark标准化合同只作历史回退/机器探索记录。正式SINTEF bundle不含BKS；正式表按同机线程合同报告CPU、RT、Tbest与Runs，不用PassMark换算声称异机算法更优。

# 2026-07-17 中国时变碳强度与价格情景

- 中国情景不再寻找并不存在的“官方全国逐时实测库”，而用官方2023省级年均因子作固定对照、Li等*Scientific Data* 2026的31省S1—2025逐时投影作中国TVCI情景、现有NESO 48槽作英国真实外部对照。小时值只阶梯复制为两个半小时槽，不插值伪造精度。
- 中国价格主情景为上海—2025年7月—人民币：CEA 75.02元/tCO2e，上海一般工商业10 kV谷/平/峰/尖峰终端电价0.3191/0.6811/1.1637/1.4352元/kWh，0号柴油最高零售价6.88元/L，公共充电服务费典型0.42元/kWh。道路物流未被全国碳市场直接覆盖，CEA价格只是内部碳影子价/政策扩围/上游传导情景，不得写为物流企业当期法定履约成本。
- 本文保持配送作业阶段CO2边界，不为回应外部评论而强制引入全LCA。中国365日充电重放和12个事前选定的季节代表日保留日际反转；反常识结果、近零改善、成本—排放冲突和英国结论不可迁移均作为正式结果保留。完整冻结合同见`docs/handoff/china_policy_scenario_contract_20260717.md`。
- Figshare v3 S1文件MD5与源端一致；首次全工作簿审计因2055年6个、2060年51个空值保留HALT记录。当前权威v2只授权无缺失的S1—2025，2055/2060禁用；2025年8760小时已无插值复制为17520个半小时槽，所有365日均通过积分守恒，上海12个代表日按结果盲规则冻结。判定为`PASS_CHINA_TVCI_2025_SOURCE_GATE_WITH_FUTURE_YEAR_NULLS_RECORDED`，搜索0，证据目录`baselines/e4_e5/china_tvci_source_gate_20260717_v2/`。
- 上海政策价格机器门绑定13份官方快照，生成CEA内部碳影子价、柴油最高零售价、充电服务费、48槽分时电价和配送作业阶段排放因子。判定`PASS_CHINA_POLICY_PRICE_ZERO_SEARCH_GATE`，搜索0，证据目录`baselines/e4_e5/china_policy_price_gate_20260717/`。其中CEA严禁写成道路物流企业当期法定碳成本，柴油价严禁写成车队实际交易价。

# 2026-07-17 非线性充电稳健性复算

- 固定功率充电不预先判为核心模型失效。正确顺序是对封存正式方案先做SOC暴露审计，再做`L->NL-E`与`L->NL-C`固定路径复算，重新核对时间窗、实体车趟次、共享桩并发、SOC和分时排放。
- 只有正式方案非线性不可行、充电择时标题级方向反转、仅调时刻无法恢复可行，或必须改路径/车型/车辆/充电站/充电量时，才升级核心模型并重跑受影响证据。若结论几乎不变，该结果同样是对线性简化适用边界的正式支持。
- 数学接口用累计时间函数`xi_s(b)`和分段功率积分，必须经过单调/连续/功率不递增、电量守恒、恒功率退化、候选点精确性和独立可行性门。通用三段曲线冒烟为`PASS_GENERIC_NL_CHARGING_FORMULA_SMOKE`，不得当作真车工程标定。完整合同见`docs/handoff/nonlinear_charging_robustness_contract_20260717.md`。
- 纯复算器`baselines/e4_e5/nonlinear_charging_replay_20260717.py`已实现分段曲线、充电时长、跨槽电量积分、候选起始时刻和权重选时。首轮单测暴露并修正了相邻数组错用严格`zip`的基础错误；修正后5项数学回归、Ruff和py_compile通过。它尚未接入路径搜索或封存方案，不代表非线性实验完成。

# 2026-07-17 ALNS评价预算闭合静态审计

- 零搜索AST审计识别31个相关评分调用点：5个明确记入`EvalBudget`，24个仍阻断闭合，0个未分类。封存历史原始表重算确认未计费完整解评分11547次，实际/报告评价数均值比13.830。权威判定为`HALT_ALNS_BUDGET_CLOSURE_REQUIRED`，证据目录=`baselines/e2_alns/e2_alns_budget_closure_static_20260717/`。E7后G0要求：搜索期完整候选评分与预算一对一；初始/终局/历史/断点复算可不占搜索预算，但须独立记数；静态无BLOCK后还须过零/极小预算行为门。通过前禁止正式Solomon/Homberger胜负测试。

# 2026-07-17 E7论文展品重建与原子就绪门

- E7论文接入不再只检查七个文件是否存在。`build_20260715_formal_evidence.py`统一重建三表、正文解释、结论和中英文摘要，并用`e7_dynamic_paper_evidence_manifest.json`绑定来源根、来源哈希、builder哈希、七件展品哈希及120任务、30配对、6单元、840逐日配对覆盖。发布时manifest最后落盘，主TeX只有七件展品加manifest共八个文件齐全才进入E7分支。
- 28日电网日结果由840行封存逐日记录重新聚合；政策比较和大部分机制诊断由30条配对及120条任务状态重算。独立总审计CSV没有逐流跨场服务字段，因此跨场流数量只能作为来源manifest约束的衍生字段保留，不能声称由论文生成器从底层会话独立复算。生成与审计定向测试、聚焦联合测试、Ruff、py_compile、XeLaTeX和pending故事门已通过；这不代表E7正式结果已经完成。
# 2026-07-17 当前主稿Desk-reject硬门

- [当前主稿Desk-reject风险门（2026-07-17）](../paper_desk_reject_gate_20260717.md) — 当前标题、成本公式、简体“径”、单句单篇引文和无母版穿帮已通过；一级阻断现为ALNS预算、Solomon公开Benchmark、E7正式结果、代表性最终解展品和非线性充电`NL->NL`核心升级。算法命名、分阶段负消融、旧弱基线、中国正式情景和图轴仍是后续门；五个一级门关闭前不把润色文本标为投稿版。

# 2026-07-17 ALNS完整方案评价预算G0修复合同

- [ALNS完整方案评价预算G0修复合同（2026-07-17）](../e2_alns_budget_g0_patch_plan_20260717.md) — 31个评分调用点中24个仍阻断，历史隐藏完整评分11,547次；修复采用candidate/reference/repair-delta三通道和超限前检查，不能机械补`budget.record()`。E7十步收口前只冻结方案，不动共享`winner.py`；G0须通过静态零阻断、零/极小预算、逐候选一对一计费、独立复算和重放门，失败则继续`HALT_ALNS_BUDGET_CLOSURE_REQUIRED`并禁止Homberger/Solomon胜负搜索。

# 2026-07-17 引言引用与编译版面闭合

- 引言文献叙述现执行单句单篇引用，测试禁止同一中文句或分号单元含多个`\cite`，参考文献首次出现顺序继续递增。真实编译捕获符号长表的新分页错误后，删除表尾空行并给表头保留18行最小空间；当前22页PDF的首页、引言、表1、章节标题、符号表和成本函数页已目检，35项定向测试与pending-E7故事审计通过。TeX/PDF/log哈希为`269a4e8ab3fe1674be3a2188439820bf56522baf9d5323306f6aa668f0cbe752`/`bf3a1ecdda3584b7cdf2b0a44197815d967031d5a0ee110f72f068f0e2fa4790`/`1b3f6bf5cbf59adfe4a9c4dad5ced3162fac5017b112e78c9d9d525432c84184`。本轮未改公式、符号和实验数字；公开BKS与E7仍不得写成已完成。

# 2026-07-17 Homberger开发bundle适配门

- [Homberger 200客户开发bundle适配门](../e2_homberger_200_development_bundle_gate_20260717.md) — 12个预注册200客户实例已转换为双精度通用bundle并由项目加载器逐字段回读，搜索评价0，搜索可读文件不含BKS。判`PASS_HOMBERGER_200_DEVELOPMENT_BUNDLE_GATE`，证据在`baselines/e2_alns/homberger_200_development_bundles_20260717/`；E7十步收口和ALNS预算G0闭合前仍禁止G1开发搜索。

# 2026-07-17 非线性充电正式固定方案复算

- E3的108份封存排班和E4的28个完整电网日完成零搜索复算。`L->L`独立闭合132 300次动作；主曲线`NL90_mild`的`L->NL-E/C`有168个seed--day方案不可行、14个方向反转，压力曲线`NL80_stress`为476和28。判决=`PASS_NL_CHARGING_REPLAY_CORE_UPGRADE_REQUIRED`；独立审计逐项核对264 600行动作、18 144行方案、6 048行配对、输入/源码/产物哈希及电量守恒并通过。E7十步收口与ALNS预算G0之前不得改共享求解器；之后必须执行`NL->NL`并重识别受影响E2--E7证据，不得只保留可行或有利子集。证据目录=`baselines/e4_e5/nonlinear_charging_robustness_replay_20260717/`。
- 核心升级采用一个共享$\xi/H$内核和非线性趟次链后向递推，`ChargingAction`须显式带起止SOC与曲线ID；成本、检查、排班、动态和证书不得各自重写充电时长。执行顺序为E7十步收口→ALNS预算G0→非线性内核→Homberger开发→Solomon外测→同版本重跑E2--E7与中国情景。完整方案=`docs/handoff/nonlinear_charging_core_upgrade_plan_20260717.md`。
- 独立原型的非线性多趟排班数学门已通过：累计时间逆函数最大往返误差0，恒功率两趟递推退化为(78,50) kWh，非线性后向递推与0.001 kWh稠密扫描误差$8.917\times10^{-13}$ kWh，容量不足链被拒绝；判决=`PASS_NONLINEAR_MULTITRIP_FORMULA_GATE`。该结果只授权E7/G0后实施，不授权当前修改共享求解器。

# 2026-07-17 PyVRP 0.13.4候选强基线工具门

- PyVRP 0.13.4当前使用仓库内独立解释器`build/python_envs/pyvrp-ils-0.13.4/bin/python`；旧用户目录解释器自2026-07-19起不再是当前合同依赖。官方wheel SHA-256=`49b84319fcfcd2206c05f55e970d090ab054d577a1d82cbac276d376fe89970c`。归仓复验权威版为`baselines/e2_alns/pyvrp_0134_tool_probe_20260717_v4_repo_runtime/`；v3及更早目录只作历史记录。v4不读Solomon或BKS，正式搜索评价为0，原生API和正式bundle适配器检查均通过。
- 0.13.4将统计点放在`Statistics.data`，将逐迭代耗时增量放在`Statistics.runtimes`。外部基线适配器已改为累计增量后读取首次达到最终可行最好成本的Tbest；适配器与冻结构建器32项接口测试通过。3客户合成VRPTW的v3探针16/16通过，并真实走通正式bundle适配器的旧Model API分支；Solomon正式搜索评价为0，判定=`PASS_PYVRP_0134_CANDIDATE_TOOL_PROBE`。
- 新零搜索预检不再报告`NO_COMPATIBLE_EXTERNAL_STRONG_BASELINE_INSTALLED`，只保留`E7_STEPS_1_TO_6_ATTESTATION_MISSING`与`EXTERNAL_BASELINE_TOOL_FREEZE_MISSING`，证据在`baselines/e2_alns/e2_solomon_external_baseline_preflight_pyvrp0134_20260717/`。这只是候选工具冻结；E7证明形成前不得创建最终授权冻结或启动56例×10种子正式搜索。
- 最终冻结只允许由`build_final_external_baseline_freeze_20260717.py`在精确授权串和E7步骤1--6证明同时存在时创建，且拒绝覆盖。候选阶段已验证96个PyVRP安装文件可逐项哈希，最终冻结尚未生成。墙钟由PyVRP官方1000客户VRPTW两小时协议按客户数线性外推至100客户，再按冻结PassMark因子1.837换算为标准720 s/本机391.94338595536203 s；这只是本文预注册外推假设，不是官方Solomon协议。4个worker均单线程，计时公平轴与内部完整候选评价轴分表。

# 2026-07-17 PyVRP实验设计入稿与当前PDF

- 主稿算法有效性分析补入PyVRP 0.13.4现代强基线的选择依据、同机单线程墙钟轴与内部完整候选评价轴，并新增Wouda--Lan--Kool 2024正式期刊文献；Solomon结果原子门内预注册391.943 s、4 worker、10种子及CPU/RT/Tbest/Runs口径，未提前声称胜负。
- XeLaTeX双遍重编为22页A4，30项论文测试与pending-E7故事审计通过，日志无未定义引用、版面溢出或LaTeX错误；第11页目检层级、表格和新增段落正常。TeX/PDF/log SHA-256=`568d922ec4886e8bdc356bc6bdccf0a961ed66166bd8b32b7bc51c130781f31a`/`3d54681c859a17568fbf38083fc1fd86487bbce3af819603c7704b9bb8fccd04`/`3f4e276261c3e74e01e18d0ed3dd6999f69fc80727b20d6c1a8848dc4f0dbd82`。未改公式、符号或实验数字。
# 2026-07-17 E7时效污染清洁重跑

正式E7已产生120个任务，但外部SIGSTOP持续13934秒，污染9个N322任务的stage-1 elapsed_seconds；步骤1--6在时效门HALT。已启动`e7_timing_clean_rerun_20260717.py`（SHA-256=`dedaaf140e20809ba19672169d149e2526ac03a5e0960dce41a3e83015fce304`）及独立hooks目录`/private/tmp/.resetp-e7-timing-clean-rerun-20260717.monitor`，严格50 evaluations、6 workers、PYTHONHASHSEED=0、原事件流/种子/四臂，隔离输出；4个parent任务用Git提交`17df1cd2`旧探针，5个child任务用`8b2de296`修复探针。脚本不会覆盖旧正式包，并要求新阶段耗时小于13934秒、去除elapsed_seconds后的语义载荷与历史同合同一致、父/子历史120个任务断点哈希前后不变。完成/异常事件前不读取中间方向，不运行下游重放。

# 2026-07-17 中国 81 个自建算例谱系

当前中国主集不是旧 C31 的 3×3，而是三区域×9 客户梯度×3 变体=81 个 DRAFT。地点使用已有 OSM 快照中的命名真实地图 POI，需求/服务/TW逐客户继承同梯度 Goeke--Schneider 公开源文件并按 8/9 映射到三班；中国订单真实性、工业候选车场、缺失充电容量和直线距离均已在 `china-81-instance-lineage-20260717.md` 与 `china_81_instance_design_20260717.md` 明确划界。81/81 结构门通过但搜索评价为0，正式实验仍未授权。

# 2026-07-17 P1 九城全量池现场

# 2026-07-17 中国V2车型、设施与硬参数审计

- 中国车型候选锁到江淮1卡威铃K7柴油配置和福田欧马可智蓝ES1·140，来源快照、字段边界和哈希在`docs/handoff/china_vehicle_parameter_sources_20260718/`。九城命名设施 manifest 见`docs/handoff/china_facility_manifest_v2_20260718.json`；官方来源抓取7/9成功保存本地原始响应，深圳 TLS 失败、东莞 URL 404 均保留，不用搜索摘要替代。
- 清洁来源批次为`data/ChinaInstances/china_facility_sources_v2_20260718_clean/`；首次`._*`污染批次不作证据，清洁批次已去除旁车文件并完成哈希回读。新增`baselines/china_instances/audit_china_instance_contract_v2_20260718.py`，将需求、时间窗、服务时间、载重、设施、充电、道路矩阵、48槽TVCI和CNY设为零搜索硬门；历史中国DRAFT被明确拒绝。
- `data/ChinaInstances/china_parameter_lock_v2_20260718.json`仍为`NOT_FORMAL`、`formal_search_allowed=false`。设施坐标/运营核验、道路矩阵、车场桩合同、按车型核心参数化、中国48槽分时电价目标函数和NL核心未闭合前，禁止中国正式E1--E7或公开算例胜负批次。

- 新脚本=`baselines/china_instances/extract_china9_full_pool_20260718.py`，只做查询框推导、OSM下载/转换、去重和审计；不改算例、不改solver、不搜索。九城旧基线（命名POI/工业候选/公共站）为北京963/18/2、天津79/5/1、石家庄22/1/0、深圳297/39/4、东莞29/19/0、广州651/29/2、佛山332/26/4、成都442/39/4、重庆80/11/1；北京963由旧catalog中`anchor=jjj_beijing`的全框原始响应复算，不能因缺少`logical_anchor`而漏计。新池因本机DNS/外网出口阻断判`HALT_ENV_NETWORK_EGRESS_UNAVAILABLE`，九城新计数全部留空；双路服务两小时停止条件未触发。现场输出=`data/ChinaInstances/china9_city_full_pool_20260718/`，三大区域旧快照参考候选各12条，四件套、raw网络探针、逐文件SHA-256、AppleDouble清理记录和6项回读测试齐全；网络恢复后原目录可续跑，P4仍待用户拍板。

# 2026-07-17 中国V2九城运营场址与互斥81合同

- 九城具体运营场址候选、地图UID和BD09MC原始坐标已齐；38条运营/硬参数来源保存35条并覆盖9城。BD09MC不进入正式经纬度，货车入口、门禁、停车容量和场内车辆桩继续独立设门。
- 运营/开发主体字段已闭合到可公开表述层，但天津港北疆16×320kW、深圳规划1068货车位/642充电车位、佛山6+10×60kW线索均不得冒充九城现场统一参数。九城`formal_depot_parameter_lock=false`。
- 中国主集保持9梯度×3城市群×每格3个互斥算例=81。01/02/03使用同一基础时间窗分布，客户地图身份、客户ID和订单种子不得重叠；宽/紧时间窗是独立敏感性轴，不得与三复本混用。
- 道路矩阵合同已锁设计：WGS84道路节点、冻结OSM有向距离/时间矩阵、不可达即HALT；禁止BD09MC直填、欧氏×1.4和结果后换点。正式生成仍等九城入口坐标、公共站合同和中国化核心。

# 2026-07-17 中国81三复本客户池闭合

- 结构唯一口径为3城市群×9客户梯度×每格3个互斥复本=81；不是三个层级各三个。01/02/03在同格内客户OSM身份和订单种子零重叠，跨规模允许复用。
- 九城Overpass基础池已从缺4项恢复为27/27城市要素成功。固定配额下首轮互斥充足性为24/27；未削配额，使用官方OSM Map API对石家庄/重庆扩大框做4×4分块，32/32成功，客户池45→105、126→305。
- 最终27/27格通过`PASS_81_MUTUAL_EXCLUSIVITY_POOL_GATE`，跨城市OSM身份冲突为0。该门只证明源池足以构造三个互斥复本；V2正式实例、订单见证、场址、路网和充电参数仍未闭合。
- 已进一步实际生成81份客户位置分配、共5805行；每格三个复本零OSM身份重叠，逐实例城市配额精确匹配，判`PASS_81_DISJOINT_LOCATION_ASSIGNMENTS_BUILT`。这里只完成位置层，不能称完整V2实例。

# 2026-07-18 算法探索主题2：合作责任重划与参与公平

- 按EA-001和用户指定的`academic-deep-research`两轮要求完成5外部候选+1自研候选，交付目录=`docs/handoff/algorithm_exploration_20260718/collaboration_fairness/`，判决=`EXPLORATION_ONLY_AWAITING_USER_APPROVAL`；未改solver、`winner.py`、E7或正式实验合同。
- 当前E6公平并非纯事后筛选：`fairness_enabled`、`P_d0`和`theta`已经进入完整候选评价、局部搜索和修复后检查。短板是每个违规成员只加一个`BIG_M`，不看公平赤字大小；跨场专用邻域主要为单边界客户或双方各一个客户，缺少公平导向多步链和路线池重组。
- Soriano等（2023）本机Zotero全文已核：Eq.11为`P_d >= P_hat*P_d0`，重构插入分数使用公平修正项，Proximity removal按到其他车场距离排序，局部搜索只允许公平可行移动。PDF SHA256=`07bf3ac92303eab0b7d9e713606334b1db262097692eeedce6942056392544e2`；未发现作者开源代码。
- PyVRP v0.13.4固定提交=`18815548d04a90a0e5eea2a0bed53a81ea9d2d49`，MIT许可证已核，真实SwapStar、SwapTails和Exchange源码/测试存在；只能借用算子结构，不能绕过ReSETP充电、多趟、公平和完整评价。路线池SP候选须先审计列可加性：非零碳配额下当前成员碳成本分摊不简单路线可加。
- 推荐探索顺序：Soriano式公平修正插入隔离原型→MIT署名真实SWAP-star/SwapTails适配→路线列可加性审计→再试公平赤字跨场链—路线池自研组合。EA-001已授权独立原型与预算0/1/2/5功能探针；G0闭合前不得作性能优越性判断，合入正式求解器、机制门、正式实验或论文主张仍须用户批准。

# 2026-07-18 算法探索主题4：E7动态滚动重规划

- 按EA-001和用户指定的`academic-deep-research`两轮要求完成5个文献/开源候选和1个精细自研候选，交付目录=`docs/handoff/algorithm_exploration_20260718/dynamic_replanning/`，判决=`EXPLORATION_ONLY_AWAITING_USER_APPROVAL`、`formal_search_allowed=false`。未读取当前E7中间结果，未改E7保护文件、`winner.py`、正式solver、事件流、模型、单位或实验合同。
- 文献核验的高匹配方向为：Wang等（2024）的当前状态伪车场与时间窗兼容快速插入、Pillac等（2012）的路线稳定双目标pBiALNS、Vallée等（2020）结合Ropke--Pisinger regret的有界ejection重插入。必须保留边界：`O(1)`只指单候选位置时间窗检查；上述论文均未核到可直接复用的官方代码。
- 开源核验：OR-Tools Apache-2.0源码明确支持锁定在线路由已行驶前缀并从既有assignment继续求解；dvrpsim MIT可导出车辆实时状态并记录求解耗时但不是算法；PyVRP MIT有warm start但无硬冻结；RoutingBlocks有EVRPTW站点邻域但根目录无LICENSE；N-Wouda/ALNS只是通用框架。
- 自研候选“事件条件稳定—责任—碳联合ALNS”把事件类型、冻结边界、稳定修复、未承诺客户责任重分配和固定路线充电重排拆成可开关层，并预设稳定性/响应时间/责任/碳四项可证伪消融。推荐下一步四个独立微探针，但均须用户另行批准；G0闭合前不得宣称性能胜负。

# 2026-07-18 EA-001合作责任/参与公平隔离功能原型

- 隔离目录=`baselines/algorithm_prototypes/collaboration_fairness_20260718/`。固定三车场四客户人工微例完成`BASE/PROX_ONLY/FAIR_ONLY/PROX_FAIR`四臂与预算0/1/2/5的16行功能探针；未导入或修改正式solver、`winner.py`、E7、模型、单位或正式合同。
- 判决=`PASS_FUNCTION_ACTIVITY_ACCOUNTING_ONLY`：完整评价计数不越界，预算0无候选评价，公平赤字幅度交换会改变接收车场，所有记录由独立模块复算一致；9项单测、Ruff、`py_compile`和五件记录哈希闭合。
- 只允许引用功能、活性、计数和复算结论。G0仍未闭合；该原型不构成性能、正式E3/E6、中国算例或论文创新证据，正式接入仍须用户批准。

# 2026-07-18 EA-001动态重规划隔离微探针

- 隔离目录=`baselines/algorithm_prototypes/dynamic_replanning_20260718/`。四个手工微例覆盖当前车辆状态伪车场序列化/回读、硬冻结前缀、自有有界regret/ejection预算计数和路线稳定性指标独立复算；OR-Tools 9.15.6755只作两车外部锁定语义对照。
- 判决=`PASS_FUNCTION_ACTIVITY_ACCOUNTING_ONLY`：状态回读等值；自有与OR-Tools前缀均保持且故意污染被拒绝；预算0/1/2/5计数严格为0/1/2/5，深度2弹射在预算2首次激活；两套稳定性实现对换车客户2、有向未来弧对称差6、车辆—位置变化2、Levenshtein距离2完全一致。
- 13项pytest、Ruff、`py_compile`、7项主体哈希和AppleDouble清理均通过。未读E7中间结果，未改正式solver、`winner.py`、E7、模型、单位或正式合同。人工评价不等于正式ReSETP评价，不支持性能主张，正式接入仍须用户批准。

# 2026-07-18 EA-001时变碳/非线性充电隔离原型

- 隔离目录=`baselines/algorithm_prototypes/carbon_nonlinear_charging_20260718/`。人工固定微路线的穷举oracle和clean-room前向时间—SOC标签原型覆盖两个充电机会、三段行驶、时间窗、SOC、两段式非线性充电和逐槽变化的价格/碳信号；全部数值只作测试夹具，不是正式参数或离散精度。
- 判决=`PASS_ISOLATED_FUNCTION_ACTIVITY_ACCOUNTING_ONLY`：预算0/1/2/5的完整评价计数和最佳完整状态逐位一致；无限预算支配实际激活且与穷举最优一致；分段非线性充电和跨信号槽积分均激活。9项pytest与Ruff通过，五件记录和哈希闭合。
- MIT `cspy==0.1.2`只在有限可行计划图上完成最短路交叉检查；未声称原生支持非线性资源扩展。其分发版本0.1.2与模块版本0.1.0差异已记录；临时仓库内虚拟环境已删除，最终目录不含环境、AppleDouble或缓存。
- 本批只支持功能、活性和计数结论；未导入或修改正式solver、`winner.py`、E7、模型、单位、参数或合同。正式接入、碳价权重、时间/SOC离散、正式实验和论文主张仍须用户批准。

# 2026-07-18 中国九城主车场入口—通行—充电带网补证 v3

- 独立证据包=`data/ChinaInstances/china_depot_gate_closure_probe_v3_20260718/`；不存在的`docs/handoff/china_depot_site_evidence_v2_20260718.md`没有被补造，真实v2输入锚点为`data/ChinaInstances/china_depot_site_evidence_v2_20260718/report.md`、同目录机器记录和正式候选manifest。
- 机器判决=`PARTIAL_EVIDENCE_GAIN_CURRENT_PRIMARY_STILL_HALTED_ALTERNATIVES_READY_FOR_USER_REVIEW`。当前九个主场址仍为0/9正式闭合；北京、广州、佛山、重庆四点只获得入口或资产身份补强。入口WGS84、外部配送车准入/时段/预约、场址绑定的已投运枪数/功率/接口/货车资格三条硬门均保持0/9，不用园区中心、门卫建筑、地图POI或规划值代替。
- 九城共保留16个未应用的替代候选，每城至少1个；优先人工核验深圳坪山智慧物流港、重庆京东亚洲一号、广州丰厚物流园充电站和天津东疆京津物流园。北京两个参数较完整的候选仍只是获批/建设规模，不得写成投运。
- 人工最小清单为每城1项、共9项。正式替换数0，未改场址合同、模型、单位、代码或E7，`formal_search_allowed=false`。来源URL、30份本地快照、逐点CSV、候选CSV、人工清单、raw/decision/report/hash齐全；按`source_snapshots`相对路径和明确校验行格式复算的快照树SHA-256=`334b48a53b206cabc7350e0d35f7faea50f69c05136bd332386c25ab551992bc`。
- [M1/E7步骤1--6正式科学收口 2026-07-18] 用户批准成对时效验收v2后，九项清洁计时重跑以已完成断点零重算收口：父系4项相对误差−0.38%至+1.63%，子系5项稳定移除5964.73--6812.21秒共同暂停偏移，非计时载荷一致、历史包未改、结果方向未参与纳入。暂停审计=`PASS_E7_EXTERNAL_PAUSE_TIMING_GATE_V2`且未解决污染0；28日零搜索重放为30×28=840行，不变量审计窗口/共享桩/路线/电量/排放全过；120任务总审计23项全过并保留2个受控失败；七件论文展品和来源manifest已发布。最终`e7_steps_1_to_6_attestation_20260717.json`为`PASS_E7_STEPS_1_TO_6_ATTESTATION_READY`、`search_version_closed=true`。AppleDouble污染包和卫生补丁前版本均另名保留；最终包AppleDouble为0。该证明只适用于当前冻结算法/线性物理版本，后续换代须统一重跑。
- [阶段一三项阻断集中审批单（2026-07-18）](../phase1_three_blockers_approval_sheet_20260718.md) — 公开入口证据已推进到不能替代物业确认的边界；固定OSRM源码构建和单个裁剪小地图测试已具备条件；ES1厢式宽2200 mm、高3050/3250 mm得到官方同行参数；MC-002六条规则已压缩。P1-APP-01至05未获用户明确批准前，不实施坐标转正、安装、profile或统计冻结。
- [阶段一P1-APP-01至05全准与最小充分口径（2026-07-18）](../phase1_three_blockers_approval_sheet_20260718.md) — 用户批准五项并要求忽略论文通常不建模的多余现场尽调。车场硬门缩为可信设施、可复算道路点、冻结路网可达；门禁/预约/停车/真实枪台账不建模不声称。ES1尺寸和MC-002已回填，隔离profile静态2/2通过；v5.27.1在当前AppleClang 16被旧sol2兼容性阻断，是否改钉OSRM 26.7.3待用户批准。
- [官方HGS先B后A（2026-07-18）](../../../baselines/e2_alns/official_hgs_b_gate_20260718/report.md) — 固定官方HGS-CVRP提交在三个非冻结CVRP开发题的3种子×3秒结果盲门达到`GO_A_ENGINEERING_DISCOVERY`，三题相对当前ALNS中位成本改善11.22%--12.74%；随后完成原生C++本机固定安装、官方5项测试、严格Python CLI桥和独立复算，A桥判`HGS_CPP_PYTHON_BRIDGE_READY`。只放行隔离CVRP工程，不放行VRPTW/完整ReSETP、正式测试集、E2--E7重跑或阶段二。
- [中国订单属性方法补充批准与TeX同步（2026-07-18）](../../../baselines/model_verification/china_order_attribute_formula_validation_20260718/report.md) — 基础方法锁为容量占比需求代理、来源论文`0.1 h/m3`案例服务时长和1222条交付订单完整经验行联合重采样；不得冒充实测重量、实测停站时长或独立边际抽样。机器合同仍禁止正式搜索。主TeX已加入公式、边界和Zhang（2025）引用；Python验证、数学审计、两层模型门和XeLaTeX双编译通过，阶段二未启动。

# 2026-07-18 机制化HGS--ALNS隔离开发止损

- 用户批准HGS外层加ALNS内层及“每个机制一个算法”的故事，但把等算力同时胜纯HGS和纯ALNS设为硬门。算法原始来源已补入追溯表和主TeX，XeLaTeX编译通过。
- 隔离骨架预算0/1/2/5计数正确；三结构九对B100仅6/9双赢，通用组合未过。多起点教育降为3/9，已停止。
- 按用户建议设计结果盲“多车场单时段才启用、其他退回ALNS”开关：25客户小门3/3双赢且禁用6/6零漂，但多车场10/15/20/25/50客户放大门仅4/15双赢；20与50客户中位分别退步5.97%和6.22%，只有25客户中位改善7.58%。不得按已观测的25客户规模事后设开关。
- 最终判`HOLD_MULTIDEPOT_SWITCH`，正式试验和阶段二均未放行。后续只允许四个机制动作在各自病灶开发集上独立过门，不再调通用外壳比例。

# 2026-07-18 取消开关后的机制算法强化

- 用户要求取消多车场识别开关并继续优化。交错式群体子代+短ALNS教育在多车场五规模十五任务仅1/15双赢，已止损；ALNS主体+跨场责任移动+车型补能收口为5/15，且跨场动作大多失活，不能声称多车场机制成功。
- 280kWh诊断开发面上，25/50客户六个B100配对任务6/6同时胜纯HGS式外层和纯ALNS；20客户B100为1负2平。20客户单独升至B500后，组合与纯ALNS三种子均精确到`621.2913242409613`，纯HGS仍差。
- 现有合同要求每个配对任务严格双赢且平局失败，因此机器总判仍为`HOLD_REDESIGN_NOT_DOUBLE_WIN`。正式试验、正式合入、China81、E2--E7和阶段二均未放行；若要把共同饱和值平局改成非退步通过，须用户另批。

# 2026-07-18 阶段二 G1 独立输入线

- 用户批准在 G1 开发期间独立推进不依赖 G1 的输入、数据与治理工作，并要求立即执行。
- 可完成范围包括本地道路图和矩阵准备、九城基础设施与中国参数证据、MC-001 订单属性层、China81 数据层、零搜索数据检查以及统计、运行和审计基础设施。
- 正式验收继续挂账：G1 冻结前不得作正式算法验收、China81 胜负实验、非线性机制正式验收、强基线正式比较或论文结论。
- 执行合同为 `docs/handoff/china_stage2_g1_independent_execution_contract_20260718.md`，审批登记为 MC-007。
- 首个独立产物 `data/ChinaInstances/china81_order_attributes_mc001_v1_20260718/` 已通过零搜索构建检查，共 81 个实例、5805 条订单记录、81 个确定性种子。
- 本地 OSRM 首次运行因缺少 Lua profile 库路径在北京 CV extract 前停止；失败目录留证，补齐 `LUA_PATH` 后以 4 线程重启并已完成北京 CV/EV。道路图完成前不启动全矩阵。
- 可恢复有向三矩阵执行器、China81 独立就绪台账、九城公共站证据审计和正式搜索 fail-closed 守卫均已建立并通过测试。
- 公共站现状为冻结 OSM 池 8/9 城有候选、正式功率/枪数证据 0/9；车场充电、四项中国成本代理和 E5/E7 数值实质效应阈值进入 `china_stage2_pending_freezes_v1_20260718.json`，未静默写入默认值。

# 2026-07-18 原装开源底线与机制优先 ALNS 转向

- 用户明确把“新算法必须胜过原装开源算法”定为 E2 底线。固定 280 kWh、20/25/50 客户、三共同种子、B100 的五方开发门中，机制优先 ALNS 同时严格胜固定官方 Vidal HGS-CVRP 中性适配和原装 `alns 7.0.0` 中性适配 9/9；相对当前项目 ALNS 为 6 胜、3 平、0 负。九任务总墙钟比当前 ALNS 约慢 11.9%，但快于两套原装开源对照；几秒级短门不作正式速度结论。该结论只属于开发小门，不等于正式 E2 已通过。
- HGS 内嵌贡献被两轮止损：直接插入版只在 1/6 对优于去掉 HGS 的版本，HGS 先手仅直接改善 1/6；官方 HGS 原生路线进入路线池的两题 seed1 探针也没有最终增益。官方 HGS 从内部组件降为必须击败的外部强对照，禁止再称“HGS--ALNS 成功融合”。
- 第一项有拆件效果的机制是车型—充电整套方案选择：25/50 客户六对相对拿掉该步骤的版本 6/6 严格胜出；20 客户三对仍到 `621.2913242409613` 平局。多车场责任、公平、碳—电价和动态订单仍未证明。总判=`HOLD_FULL_CONTRACT_SMALL_SATURATION_OR_COMPONENT_GAP`、`formal_search_allowed=false`；改平局规则、正式合入、正式 E2、China81、E2--E7 重跑和阶段二均须另批。

# 2026-07-18 阶段二 G1 独立输入自主冻结

- 用户授权把全部不需要 G1 的工作一次性完成并由代理自主解决；审批登记为 MC-008。
- 静态输入包 `china81_stage2_static_inputs_v1_20260718` 已闭合 81 实例、5805 订单、九城设施、
  12096 条 2025-02 电价—碳槽、成本代理和 E5/E7 数值阈值，搜索评价为 0。
- 场充 22 kW×2 枪、公共充电 60 kW×1 枪和 0.40 CNY/kWh 服务费均为构造情景，
  不得冒充车场或站点观测。深圳能量电价使用本地两部制表电量项情景。
- 道路流水线负责十张基础图、成渝合并图、CV/EV 共 1,578,948 个有向同路线三矩阵和
  81 实例零搜索审计；G1 冻结前正式 SOC、算法搜索与 China81 胜负仍禁止。

# 2026-07-18 阶段二 G1 独立输入执行终局

- 权威道路输入改为 APFS 构建并验签归档的区域稀疏连通图 v5，六张 CV/EV 图全部完成；
  exFAT v1--v3 和诊断 v4 只保留为失败证据。
- 权威矩阵 v9 已物化 1,578,948 个有向点对，不可达 0、搜索评价 0，没有欧氏、对称复制
  或直线回退。独立诊断对零时长终端子段、同吸附点、亚分辨率点和 8 个有向绕点修复逐行留证。
- `china81_g1_independent_frozen_v2_20260718` 为 81/81 通过，机器判
  `PASS_CHINA81_G1_INDEPENDENT_DATA_FROZEN__G1_PHYSICAL_SEARCH_ACCEPTANCE_HELD`。
  MC-008 完成，唯一挂账为 `G1-FREEZE-MERGE=HELD_BY_DESIGN`；正式物理与搜索仍禁止。

# 2026-07-18 阶段一机制驱动ALNS统一开发收口

- 没有修改“平局失败”规则。固定路线、车型、电量和充电时长后，精确碳择时把旧20客户共同值从`621.2913242409613`降到`621.0831141941019`且零违规，证明旧值不是全局最优。
- 当前身份锁为机制驱动ALNS，HGS仅作固定强开源对照。五个部件分别处理跨车场责任、车型—补能整套选择、固定时长碳择时、参与收益缺口和冻结历史的新增订单；各自账本分开，责任分支与绕过分支取较优者，最终独立复算。
- 统一证据=`baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/mechanism_v7_stage1_closeout_gate/`，判`PASS_STAGE1_ALGORITHM_INFRASTRUCTURE_DEVELOPMENT_CLOSEOUT`。静态九项9/9同时严格胜官方HGS中性适配、原装`alns 7.0.0`中性适配和当前项目ALNS；多车场十八项4项绑定改善`1.2652%--5.6731%`、14项精确不倒退；公平固定100%独立收益底线1项绑定修复、2项零动作；冻结E7单事件未来少1条路线并降成本`29.675379`。
- 62行原始记录与六件展品哈希独立重算通过，15项回归通过，`cost.py/check.py/search/evaluation.py`零差异。边界：公平仅1个绑定任务、动态仅1个真实事件、三个多车场强对照为事后确认，非线性充电和分时电价未接；正式性能、正式合入、China81、E2--E7重跑和阶段二仍须用户另批。
- 来源手册补齐Cheng等碳感知充电与Kullman等固定路线精确充电依据；主TeX只补方法来源与`frvcpy`参考文献，未写开发胜负或新公式。latexmk/XeLaTeX重编24页，无未定义引用、Overfull、Underfull或LaTeX错误。

# 2026-07-19 完整模型融合两刀止损

- 精确集合划分路线仓库在预登记多车场25/50客户筛选中分别选0条HGS路线，组合逐位退回ALNS+共享机制专家，判`STOP_ROUTE_POOL_FUSION_NO_STRONG_INCREMENTAL_SIGNAL`；人工互补路线功能通过不等于真实性能。
- 候选源码先冻结，再用既有`build_full_source_threeshift`、donor02和25/50源规模生成60/112客户两道新结果盲开发题。把车型--补能和碳择时放到每个ALNS完整候选接受前，完整评价两臂均100/100且可行，但相对v7倒退7.207%/5.416%，另耗1456/2297次路线代理评价，判`STOP_MECHANISM_NORMALIZED_ACCEPTANCE_NO_STRONG_SIGNAL`。
- 两条均按预登记纪律停止，不扩三种子、不调旧题、不跑全量、不进阶段二。v7仍是阶段一最强候选，但旧9/9开源对照证据已降级，尚未满足新结果盲、同批、对称预算/墙钟的纯HGS与纯ALNS正式双赢底线。

# 2026-07-19 China81 G1 独立链失败关闭复核

- 修复矩阵构建无条件 PASS、诊断自证计数、最终冻结缺少 81/5805 与上游哈希硬门、
  一键入口只看文件存在四类漏洞；关键记录面现在必须被哈希清单覆盖并逐文件验签。
- 首次真实复算因新审计器误用区域坐标笛卡尔积而 HALT；修正为构建合同中的实例内有向
  对并集并加入回归后，六批计数、1,578,948 对、81/81 和 5805 条订单重新独立闭合。
- 复核包判 `PASS_CHINA81_FAIL_CLOSED_REVIEW__FORMAL_G1_GATE_REMAINS`；未运行算法
  搜索，唯一开放项仍是 `G1-FREEZE-MERGE=HELD_BY_DESIGN`。

# 2026-07-19 电动化联动搬移行为门止损

- 首次行为门在场景成绩写入前因验收程序误读账本层级失败；原失败目录只读保留。恢复版只修验收程序，算法、输入、阈值和预算均由登记哈希锁死。
- 恢复版证据包7件齐全，19个输入、130个源依赖、4个保护文件、账本和哈希独立闭合；ALNS/HGS/完整路线搜索均为0。
- 20客户绑定场景构造44个中性搬移、10个可行唯一候选、完整收尾3个，但三者都恢复原解，成本`621.0831141941019`不变、燃油路线`1→1`、接受0。25客户全电对照成本`603.1548339805785`和完整内容逐位不变，收尾调用0。
- 判`STOP_ELECTRIFICATION_RELOCATE_RESIZE_BEHAVIOR`，不触发旧三题、新D3、正式、全量或阶段二。当前证据否定的是“先搬移、再允许通用责任收尾撤回”的组合，不证明所有固定搬移—联合车型补能候选无效。

# 2026-07-19 燃油路线退役—电动重整行为门止损

- 依据路线退役、待安置池、后悔重插和有限让位思想独立实现；固定客户骨架后再做车型—补能—碳完成。无新增第三方源码或许可证依赖。
- 零搜索绑定题形成9个唯一骨架并精算4个。最低候选成本`661.4407527272798`，唯一燃油路线`1→0`候选成本`685.7079097063714`，均高于源解`621.0831141941019`；接受0。全电25客户对照严格零动作，路线搜索0。
- 首次调用后的AppleDouble事故单独保留；恢复仅从原始CSV和快照做8次独立复算，不重跑算法。13/13最终文件、6/6事故文件及四个候选快照独立验签通过，旁文件0。
- 判`STOP_FUEL_ROUTE_RETIREMENT_EV_REPACK_BEHAVIOR`。不得在同一20客户题调参救援，不得D3、正式、全量或阶段二。负结果说明事后严格改善式退役跨不过暂时变差的过渡；后续若继续，应另立“搜索中共同形成路线、车型、补能和车场”的候选，先过新鲜最低成本门。

# 2026-07-19 结果优先混合算法阶段一终局

- 用户最终限定：公开性能只使用有独立BKS的原始开源算例；私有性能只使用China81。
- `SEG-GEN-02`的64/6/48/12有界生成、5项单测、接入冒烟和零搜索行为门通过；英国
  夹具只作行为回归，donor03性能门在0次搜索时取消。
- 三组互斥Solomon+BKS开发门中，`ALNS-WARM-HGS-01`对HGS为3胜2平1负、对项目
  ALNS为6胜0负，但因一题多车而汇总失败；`ALNS-DUAL-ELITE-HGS-02`对HGS为
  2胜1平3负、对ALNS为5胜1平0负。两者均时间公平且独立可行，但没有总胜HGS，
  公开融合开发停止，不造第三候选或启动56题。
- China81公平运行器在导入求解器前失败关闭：G1和China81最终冻结缺失，公开混合
  强阳性也缺失，搜索评价0。AppleDouble无重跑修复确认10份清单的普通文件旧哈希
  全部一致，只剔除旁车项；权威零搜索独立审计44/44通过。该PASS只证明证据自洽，
  不表示算法目标完成，不放行China81、阶段二或论文优胜结论。
- 详细记忆：`docs/handoff/memory/outcome_first_hybrid_20260719.md`。

# 2026-07-19 HGS-AEALNS-03 公开最小门与尸检

- 用户允许尝试后，冻结`EA-HYBRID-004`：公开只用六个此前融合门未见的原始
  Solomon+BKS题，纯PyVRP 0.12.2 HGS与候选共同seed1、共同初解、单线程、每臂5秒；
  China81和阶段二保持关闭。
- 四项核心单测和1秒行为冒烟通过。正式门对HGS为2胜2平2负：R109/R208严格胜，
  C106/C205平，RC105/RC205负；RC105候选23路、纯HGS 15路。候选相对BKS多车
  合计11，HGS为3，判`STOP_HGS_AEALNS_03_ANY_LOSS`。
- 独立零搜索审计重算12解的覆盖、容量、时间窗、路线数、距离、哈希和胜负，
  60/60通过。两个额外零搜索测试确认修复代理不看时间窗，也没把新车固定费放进
  插入排序；“单次只收改善”不能保证等墙钟整机不退步。
- AILS-II的XL CVRP成绩不能替代ReSETP VRPTW公开证据；只收改善层也不能构造性保证
  同墙钟不输。当前候选冻结，不在已见六题救援。若继续须另批安全语义候选和全新留出题；
  修时间窗/固定费/路线数/完整可行有直接依据，但没有必胜HGS保证。
- 权威尸检=`docs/handoff/hgs_aealns_03_forensics_and_next_decision_20260719.md`。

# 2026-07-20 PyVRP V13 时间—质量曲线

- 原装PyVRP 0.13.4 ILS在PR11B/PR17B/PR21B、seed1、单线程下从8.5秒延长到
  60/300秒，三题gap均连续下降；300秒gap为0.215%/0.720%/1.007%。
- 五分钟关闭原8.5秒BKS差距的89.86%/76.18%/71.30%，判
  `TIME_CONTINUES_HELPING_ALL_THREE`。这否定“凭8.5秒短门立即换母体”，不撤销
  C2 STOP，也不证明正式28题、新BKS或调参收益。
- 证据=`baselines/algorithm_foundation/pyvrp_v13_time_quality_curve_20260720/`；
  下一方向须另批受控配置/长预算研究，China81和阶段二未启动。

# 2026-07-20 China81 非线性充电排班 NL1

- 新动作兼容携带起止电量和曲线 ID，新多趟证书冻结曲线 ID/参数哈希；历史六字段
  动作仍可读。多趟可达电量、趟间补能、后向压缩和首趟预充统一调用 NL0 曲线内核。
- 同一两趟夹具在 L100 下 1 辆实体 EV 可接续，在 NL90 下必须 2 辆，证明非线性物理
  已进入排班而非只在报告层。非线性持续时间最大误差约 `3.98e-13` 秒，电量误差 0，
  L100 最大漂移约 `3.13e-13` 秒；84 项相关回归和 Ruff 全过。
- 全量回归仍为 830 通过、12 个基线/旧契约可复现失败、1 跳过，不称全绿。权威包
  `baselines/model_verification/china81_nonlinear_schedule_nl1_20260720/` 判
  `PASS_NL1_CURVE_AWARE_MULTITRIP_SCHEDULE`。仍为零搜索；只放行 NL2 的成本、
  碳排、择时和检查器同核闭合。

# 2026-07-20 China81 非线性充电成本—检查 NL2

- 充电修复、精确分时电量、碳排、成本、利润、碳择时和独立检查器已绑定动作起止电量
  与曲线 ID。高 SOC 夹具首槽为 `8.333333333333334 kWh`，旧均匀摊分为
  `5.555555555555555 kWh`；缩短动作和缺元数据动作均失败关闭，L100 新旧记录逐位
  一致。
- 零搜索碳择时夹具从 `0.7265247116695909 kg` 降到
  `0.12108745194493127 kg`。目标回归与 Ruff 通过；全量为 835 通过、12 个基线
  可复现失败、1 跳过。
- 权威包
  `baselines/model_verification/china81_nonlinear_cost_check_nl2_20260720/` 判
  `PASS_NL2_NONLINEAR_COST_CHECK_AND_TIMING`。动态继承和 China81 三道路
  profile 适配仍未闭合，正式搜索继续 false；只放行 NL3。

# 2026-07-20 MV-HGS-SP 阶段一算法结构冻结

- PyVRP 身份已纠正：0.12.2 是 HGS，0.13.4 是 ILS；旧多视角 ILS 结果不得支撑
  HGS 故事。最终候选使用三个真正 HGS 视角、完整非线性模型精英重排和
  SciPy/HiGHS 精确路线池重组，名称冻结为
  `MV-HGS-SP`（多视角混合遗传搜索—精确路线池重组算法）。
- H4 为 2 胜 1 平 0 负；H5 新题为 2 胜 1 平 0 负；H6 三题三种子为
  5 胜 4 平 0 负。75 客户层平均改善约 0.128222%，150 客户层约
  0.453327%，25 客户层全平；九解全部可行，34 项相关测试和 Ruff 通过，
  H6 十个登记文件哈希一致。
- 该证据只证明精确重组相对同批三个 HGS 视角中最好的完整父方案有方向稳健性。
  它额外使用精确重组时间，尚未完成等墙钟纯 HGS/ALNS、China81 全量或
  V13/BKS。公平/动态没有独立搜索贡献，ALNS 后接探针无增益。
- H0 早期适配器哈希因后续扩展而漂移；H6 当前源码和证据哈希全匹配。裁决
  `PASS_PRIVATE_DIRECTIONAL_ARCHITECTURE_FREEZE`，正式搜索和阶段二继续关闭。
  详见 `docs/handoff/memory/mv_hgs_sp_stage1_closeout_20260720.md`。
- [E2终局战役施工图](../e2_final_algorithm_experiment_construction_20260720.md) — 07-20: 陈雨蝶表4/5/6/图4逐字段模仿+China81全量+跑完即关算法实验; P0-P5自动推进零询问; A/B/C/D主张阶梯预注册; PyVRP列=0.12.2真HGS母体(已裁定登记)
- [论文V2全面重写](paper-v2-rewrite-20260720.md) — 07-20: 陈模板逐段对齐+邱基座+全切China81+MV-HGS-SP算法章; 择时候选集δ_l修正; 新增碳价×配额与决策目标两节(批准待排期); 数据全占位待封存CSV回填

# 2026-07-23 中国 E3–E7 适配底座

- 新增 `baselines/china_e3_e7/` 与
  `data/ChinaInstances/china_e3_e7_foundation_contract_v1_20260723.json`；本轮只做 planning、
  证据、统计、图表和论文接线，不启动正式搜索。
- 预检 81/81 bundle、27 个 primary cell、5805 个订单通过；E3–E6 生成 3240 条 planning-only
  任务，E7 只登记 2025 条全量投影和 75 条结果盲接线门。合同继续
  `formal_search_allowed=false`、`search_evaluations=0`，E2 未改，UK 只读归档。

# 2026-07-24 E2 算法排雷与机制展示算例

- [E2算法修复与机制图](e2_algorithm_repair_and_mechanism_case_20260724.md) — 档案路线全复用开发门通过；两段三视角交换与重组回馈均按预登记HALT；100客户机制展示算例十种子主方法对三单视角均10胜0平0负。真混合 G1 v6 因无直接协同停止；首个独立 TAILORED-DP-VNS 强解改善门0/3停止。第二个可行性引导候选以零完整目标通过G0，但强解门仅1/3且只有200客户题2-opt*改善0.000045%，按合同STOP；打包异常用零搜索恢复，未重跑。未过不得进A/B/A+B、E3或论文。
- 中国主日历明确为 2025 年 2 月完整 28 日；2025-02-12 仅为共同解释日。raw schema 区分
  `formal_run`、`daily_replay`、`stage_diagnostic`；表格还要求绑定 raw SHA 的独立复算证书。
- 适配交接说明见 `docs/handoff/china_e3_e7_foundation_adapter_contract_20260723.md`。

# 2026-07-24 E2 v4 正式重跑与论文方法合同

- v4正式E2采用唯一通过开发门的“全部完整档案路线进入路线池”版本，405任务运行中；
  每任务三视角各5000次HGS迭代、80次完整候选评价、5 s限时MIP，完成后必须零搜索
  独立复算1620个保存方案。正式结果未封存前不得复用旧China81表图或提前宣称通过。
- 机制展示算例与图4分别受终点门和形状门约束：主方法对三单视角零负且达到8/8/7个
  最低胜场；四条真实轨迹各至少8点、6次严格下降，终点等于封存成绩。陈式外观只能由
  真实算法行为产生，禁平滑、插值、断轴、换种子或结果后换题。
- 论文方法名称已改为“多视角混合遗传搜索—限时MIP路线池重组算法”。真实流程为
  三个独立HGS视角、完整模型复核档案、全部复核档案路线去重入池、5 s HiGHS MIP、
  完整复核和单调接受；不存在旧稿所写的HGS-M母体、轮换热启动、4轮延续、600路线
  上限或精确最优承诺。方法防回退测试纳入E3发布回归。
- 正式总表出现前另立E2论文强度预登记：405对和81个五种子均值对三个单视角均须
  零负，并满足严格胜场、平均降幅、9层覆盖与Holm校正显著性门；不通过则E2数据如实
  保留但不称论文成功，S3--S5与E3继续关闭。

# 2026-07-24 E2 v4 正式通过并进入 E3 放行

- `corrected_china81_rerun_v4_20260724` 已完成 405 个正式任务、1620 个保存方案及
  全量独立重放；成本、排放、完整模型可行性、城市--日期--半小时档位、出发前充电和
  有限车队全部复算一致。E2 原始门和独立重放门均 PASS。
- 结果盲论文强度门 PASS：405 单元对 HGS-F/HGS-E/HGS-M 为
  307/98/0、168/237/0、140/265/0；81 个五种子均值为
  66/15/0、43/38/0、35/46/0；总体平均成本降低
  0.844%、0.376%、0.528%，三组 Holm 校正检验均 `p<0.001`。
- 结果盲仿真算例仅用于节点与路线明细；机制展示算例正式十种子为
  10/0/0、9/1/0、10/0/0。图4轨迹真值门通过，直接连接真实观测点，无断轴、
  平滑、补点或事后换种子；主稿表8、图4、表9已换为 v4 封存数据并编译、数学审计通过。
- E3 v6 合同已冻结但继续 `formal_search_allowed=false`。下一步必须通过 fresh
  运行臂语义、参数一致性、结果盲预算、发布回归和 GO 门；旧 E3/E5 历史红灯不得借
  本次 E2 通过改判。

# 2026-07-24 E2 v5 两阶段多视角组合复跑

- 用户随后否决 v4 大量持平与阶梯图终态；v4 证据保留但当前稿重新打开。车型热启动
  映射和已验 MIP 解被再次贪心解码两个实现错误已修复，18 项定向测试通过。
- 稳定路线重组超加性已 STOP；主张收敛为三视角完整模型最优可行解组合，限时 MIP
  只作辅助描述。冻结算法为每视角 5000+20000 次、每任务 280 次完整核算、两次
  30 秒 MIP、历史质量/差异档案各 12。
- 新鲜 6 题种子18确认对 F/E/M 为 5/5/6 个严格胜场且均零负，平均降幅
  0.766351%/0.148621%/0.383106%，只放行 v5 正式全量。权威预登记与监控配置位于
  `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v5_staged_portfolio_20260724/`。
  完成 405 任务、1620 独立重放、预登记强度门和 S3--S5 前，E3 继续关闭。

# 2026-07-24 E2 v5 HALT 与 v6 计数修订

- v5 在第13个任务因小题真实完整模型核查276而未达到280硬门，HALT证据原样保留。
- 用户批准的 v6 只把已保存 HGS-F 解的重复完整模型评价作为明确登记的预算补足，不改核心算法、搜索随机流、输入、评价器、参数或成绩；真实搜索核查数和补足次数分列。
- v6 预登记、运行器和监控在 baselines/e2_final_campaign_20260720/corrected_china81_rerun_v6_budget_recheck_20260724/；v6 完成、独立重放和强度门前 E3 继续关闭。

# 2026-07-24 E2 v6 小档案 HALT 与 v7 修复

- v6 在 `cn-cy-10c-01-V2-LOCATIONS/seed1` 因旧档案验收要求小题也必须出现额外差异
  候选而 HALT；隔离复现确认六阶段迭代、120 快照、历史引用和四解可行性均正常，
  唯一情况是一个阶段只有 20 个不同候选且已全部选入。
- V7 账本改为选入数必须等于 `min(24, 不同候选数)`；只有候选数超过 24 时才强制
  正数差异余量。搜索、评价器、种子、迭代、MIP 和预算不变。V5/V6 证据保留，安全
  标签为 `safety/e2-v6-halt-before-ledger-fix-20260724`。
- V7 三题预检通过前不得启动 405 题；正式完成、1620 解独立重放、论文强度门和
  S3--S5 通过前 E3 继续关闭。
- V7 三题预检已判 `PASS_D6_E2_STAGED_V7_PREFLIGHT`：10/100/200 客户任务全部
  PASS，12 个返回解均通过完整模型可行性检查；每题总核查 280、历史快照 120。
  10 客户题为 276 次真实核查加 4 次固定解重复核算，100/200 客户题均为 280 次
  真实核查且无需补足；档案选择和四份哈希清单全部闭合，定向回归 16 项通过。只授权
  从零启动正式 405 任务，不复用预检结果，独立重放、强度门、S3--S5 和 E3 仍未放行。
- V7 预检与后续冻结链已提交为 `9b80ca59`，开跑前安全标签为
  `safety/e2-v7-preflight-pass-before-formal-20260724`；正式 405 任务已从空目录以
  3 个并行单线程任务启动并由监控器保护。完成前不得根据中间结果改代码、参数、论文
  或后续验收规则。
- S4 v2 静态接线存在确定字段错误：S3 汇总不含 `witness_sha256`，v2 却从汇总行
  读取。未读取正式结果行即另冻 v3，只从固定规则选中种子的封存任务原始行读取并
  核对解指纹；选择规则、解、分数、验解和零搜索边界均不变。9 项源指纹和最小模拟
  接线测试通过，后续只执行 v3，v2 留档。
- 未读取正式结果行即冻结 S5 零搜索表图生成器：全宽中文三线表、紧凑和 27 层完整
  汇总并存，图3固定 2025-02-12 参数权威及左下无框城市群图例，图4只用真实在线
  完整模型观测、连续坐标和全数据 3% 留白，禁断轴/平滑/插值，图例按固定最少遮挡
  规则选择。旧封存数据形状与中文字体测试通过，6 项源指纹闭合。
- S4 v3 与 S5 接力监控原无完成标记，正常退出会被误报异常；已给两个零搜索入口
  增加含决定和关键产物指纹的 `done.json`，并同步监控与登记指纹。算法、成绩、
  选择和表图规则未变。
- 已冻结等待式 E2 自动接力：不重复启动正式批，正式 405 任务指定 PASS 后才顺序
  执行 1620 解复算、强度门、S3、S4 v3、S5；任一步失败即停，不救援、不改参数。

# 2026-07-24 V7 算法章候选稿（主稿保护期）

- V7 正式 405 任务运行期间不改 `paper_main.tex`。独立候选稿位于
  `docs/paper_v2/candidates/algorithm_section_v7_candidate.tex`，图1/图2位于
  `docs/paper_v2/generated_figures/v7_candidates/`。
- 候选稿只反映冻结的实际流程：三视角独立 HGS、5000+20000 次两阶段搜索、同视角
  完整精英热启动、两次 30 s 限时 MIP、完整模型和独立检查器最终择优。MIP 只作为
  辅助候选生成，不保证严格改进，不写等计算量主张。
- 图1、图2均为透明黑白线框，无伪代码、无装饰底纹、无结果性公式；图2以四块中文
  说明候选档案、完整检查、路线合并去重和限时组合/择优。独立预览 3 页编译无版面
  越界并已放大目检。正式结果链全部 PASS 前不得并入主稿。
- V7 实验段候选改用5000+20000次、280次登记完整核查和两次30 s限时MIP；表图路径
  只接受V7封存产物，缺失即报错。`materialize_e2_v7_paper_text.py`在结果前冻结，
  全链PASS后才从封存证据自动生成结果段和独立五件套，禁止人工抄数或恢复路线组合
  超加性、MIP必然改进、等计算量优势等已停止主张。
- V7前置候选标题为“时变碳强度下多车场混合车队动态协同配送模型与算法”。摘要和
  引言改为问题驱动：重点是协同方案在实体车、充电、参与和动态状态层面共同可执行，
  不再把机制堆叠或“HGS+MIP”名称当创新。7篇2024--2026年Zotero直接相关文献完成
  元数据和原文核对，证据说明见
  `e2_v7_frontmatter_literature_revision_20260724.md`；候选3页编译和目检通过。
- 模型章V7候选把动态需求与车辆状态继承前移到问题定义，固定正式顺序为问题/动态、
  符号、能耗、充电、六类成本与总目标、约束；总目标移到全部约束之前。构造情景边界
  显式写明，公式与标签不改。独立预览1页无版面警告。
- V7论文接入新增两道结果前保险。`materialize_e2_v7_route_text.py`只从S4/S5封存
  表4自动生成路线结构说明，避免新表与旧正文数字错配；`build_v7_integrated_paper.py`
  只生成独立候选稿并锁定主TeX及候选源指纹，发布链、结果文字门和路线文字门任一未
  PASS即拒绝接入。无结果结构检查已通过，主TeX和正式数据未改。
- `run_e2_v7_paper_candidate_chain.py`已冻结为发布后等待链：现有E2发布链PASS后才
  自动物化两类文字、生成独立候选稿并检查编译/引用/版面框/Type 3字体；不覆盖主稿、
  不启动E3，候选PASS仍需逐页视觉验收和显式合并。

# 2026-07-24 真混合算法硬门

- 当前 v7 保留为强 HGS 家族基线，不再把三种 HGS 视角和路线池 MIP 包装成独立算法
  融合。最终候选另立 A=HGS、B=机制感知破坏—修复、A+B=双向协同。
- 用户要求的“1+1>2”是结果硬门：相同完整候选评价预算下，A+B 同时优于 A 与 B，
  并有 HGS→破坏修复→HGS 后继续改善的谱系证据；最终取优不算，达不到即停。
- 新算法必须对应客户顺序、双车场、油电车型、有限车队、充电/发车时刻、分城市和
  分时电价/碳强度/柴油价及动态状态，不能套用通用算法后改名。
- 公开 BKS/SOTA 另设资格门；China81 为构造情景，不得自封 SOTA。合同与详细门槛见
  `docs/handoff/e2_genuine_hybrid_hgs_rr_contract_20260724.md`，审批条目为
  `E2-GENUINE-HYBRID-HGS-RR-001`。
- 独立开发包已接通 A、B、A+B、有限车队车场/车型 DP、充电策略短名单、regret
  重构、路线局部缓存和双向阶段调度。A+B 的完整评价固定约60/40分配：80次为
  `1+16+16+16+15+16`，280次为`1+56+56+56+55+56`，其HGS内部迭代数也只取A的60%。
- 防伪门要求整路线真换场、双向片段两边都交换、油电真翻转、充电地点/能量/时刻真
  改变；充电站不得当客户。普通种群输出没有可验证父母关系，不能再凭“新签名且更优”
  冒充回送解后代；每个HGS阶段的三个固定代理视角分别只对第一热启动解执行一次
  可追踪局部搜索，A与A+B均固定为每次运行9次；A+B回送时第一解固定为RR解，只有
  这条直接路径的完整成本继续下降才计协同增益。
- 第二轮静态审计修掉单车场崩溃、一个无可行动作导致整轮误停、时间窗固定重复选择、
  跨场候选无界、无目标车型车位仍翻转、充电重排重复原方案、局部车型/充电操作误重建
  整解和时间窗被当前车型误拒等实现错误；时间窗压力改按统一排程后的真实剩余时间。
  33项轻量测试通过；权威静态G0
  v10子门13/13通过，判
  `PASS_G0_STATIC_SEMANTICS__REAL_BUNDLE_PREFLIGHT_PENDING`。这不证明真实China81
  可行性、性能或1+1>2。v6因新增验收脚本局部变量错误形成12/13 HALT并原样留档；
  v9因时间窗操作升级后旧夹具仍固定修改第一条路线形成12/13 HALT；两份失败均原样
  保留。v10的19项输入与4项产物哈希复核一致。真实bundle子门已结果盲预注册，合同模式确认三题及55个
  选定输入文件哈希一致，且v7运行时硬拒绝执行；零搜索回放与G1须等v7释放资源。
- 开发题按输入哈希盲选为 jjj-25c-02、prd-100c-03、cy-150c-03，正式确认必须以
  其余78题为主。旧完成器一次调用含多次内部完整评分，新A/B/A+B不得沿用旧外层调用
  计数。
- G1 微型门已在结果前冻结：三题×种子1×A/B/A+B，每臂80次可见完整评价；A总计
  75000次HGS内部迭代，A+B固定使用60%，最多3 workers。入口核对31项源码指纹与
  55个输入文件，34项轻量测试通过；当前被v7、发布链和未完成真实G0三重阻断，
  新搜索次数仍为0。

# 2026-07-25 E2 v7 后算法强化与论文重构行动合同

- 用户批准立即行动，但“成为 SOTA”仍是待验证资格，不是预写结论。新合同把证据
  分成两条：完整外部算法和公开 BKS 回答强度，A/B/A+B、双向传递谱系和留一机制
  消融回答原因；HGS-F/HGS-E/HGS-M 降为内部视角分析。
- 算法不另造结果门，继续沿用已冻结 G0--G4。G1/G2 只允许逐级扩大，G3 才支持
  China81 `1+1>2`，G4 才可能支持公开 BKS/SOTA；失败即保留证据并停止，不用换题、
  换种子、调图、改坐标或改门救援。
- 论文按问题驱动重构标题、摘要、引言、模型顺序、算法叙事和 E2--E7 证据体系；
  官方出版社规范优先，未明写处才参照陈雨蝶 2025。本论文不设伪代码，流程图必须
  与实际实现一一对应。
- 当前只落盘行动合同，未改在跑 v7、释放链、真混合等待链、模型公式/符号、主 TeX、
  评价器或封存数据。权威文件为
  `docs/handoff/e2_post_v7_algorithm_paper_action_contract_20260725.md`；结果盲的标题、
  摘要、引言、模型、算法图、E2 表图和 E3--E7 递进结构底稿为
  `docs/handoff/e2_post_v7_paper_rewrite_blueprint_20260725.md`。

# 2026-07-25 E2 v7 机械放行与定时监控

- `e2-v7-30` 每 30 分钟只读检查在跑 v7；正常不通知，异常不自修，终态后先暂停自身。
- 新增结果盲机械放行登记和零搜索入口。只有正式 405/405、1620 解完整可行、独立
  witness 复算逐份成本一致且可行、哈希闭合、原完整发布链已终态，才可放行真混合
  低成本开发。
- 机械 PASS 不等于论文效果 PASS，不覆盖 S3--S5、BKS/SOTA，也不自动启动重复
  G0/G1 链。当前仅 `CONTRACT_ONLY_PASS`，没有新搜索。

# 2026-07-25 E2 v7 正式/复算 PASS 与发布恢复

- 正式 405/405、1620 解完整可行 PASS；独立复算 1620/1620 成本一致且可行 PASS。
- 原发布接力因外层五分钟停滞误判和内层僵尸进程命令误判卡死；用户确认安全结束
  进程组 76777，异常现场保留。
- 恢复 v2 不重跑两个已通过阶段，只继续原冻结效果门、S3、S4 v3、S5；26 项登记
  指纹和 2434+85 项上游哈希清单执行前闭合。
- 原效果门结果为 `HOLD_E2_STAGED_PORTFOLIO_NOT_PAPER_STRONG`，旧发布链诚实 HALT；
  机械完整性门 PASS。机械真混合接力仅改上游资格，v3 的三题、种子、三臂、80 次
  评价、60/40、算子和所有硬门不变，顺序为 G0 → 资源探针 → G1。

# 2026-07-25 真混合真实 G0 HALT

- 机械接力在零搜索真实 G0 停止：三道预登记开发题均无完整可行短名单候选，
  `search_iterations=0`；资源探针和 G1 未运行，不能作性能或 `1+1>2` 结论。
- 封存 witness 在解码前均完整可行，且三份都是车队上限内的全燃油方案。共同失败源
  是新解码器只按 `_single_route_cost` 成本筛前 6 个分配，却没有路线局部硬约束检查，
  也没有固定保留已知可行的当前分配。
- v1 未保存候选级违约类型，故不得猜测具体是哪类硬约束。任何修复须先另立登记，
  保留 v1 HALT，只补局部硬约束过滤、可行 incumbent 保留、违约明细和测试；用户
  批准前不得改代码或重跑。

# 2026-07-25 真混合 G1 v6 STOP

- G1 v5 因局部覆盖例外过宽在结果读取前终止，4 个部分结果只计路径、不读目标值、
  不复用。例外收窄后 38 项测试、G0 v3 3/3 和六进程资源门 6/6 通过。
- G1 v6 九项全部完成、每臂 80 次完整评价、全可行、replay 零差异。A+B 相对
  `min(A,B)` 为 1 胜 2 平，唯一改善 0.894%，直接协同改进证据为 0。
- 权威判定为 `STOP_G1_NO_HYBRID_GAIN`。机械正确不等于效果通过；不得调参、重跑、
  换题、扩大 G2--G4、启动 E3 或声称 `1+1>2`、BKS、SOTA、论文可用。
- [强 HGS 深化失败后的唯一候选（2026-07-25）](e2_dual_guided_resource_order_20260725.md)
  — 官方 ILS 能改善弱起点但对强 HGS 热启动 0/3 改善；冻结该候选后，结合全部
  历史 STOP 与一手文献，只预登记“对偶价格引导的资源耦合次序重构”。其冻结实现
  在 6 workers 零成绩工程门中仅 1/6 题产生 1 个合格结构，另外 5/6 为 0；候选
  目标评价 0，判 `HALT_ZERO_OBJECTIVE_ENGINEERING_OR_RESOURCE_GATE`，G0 未启动，
  用户最终裁决 `FINAL_STOP_DUAL_GUIDED_RESOURCE_ORDER_NO_RESCUE`，禁止实现语义
  审查、原题原候选救援或改名复活；未另行完成文献与失败复核前不得启动下一候选。
- [资源—时隙定价路线生成候选（2026-07-25）](../e2_resource_slot_pricing_candidate_review_20260725.md)
  — 新一轮一手文献与全部封存失败复核后，只保留一个实质不同候选：在车场—车型
  分层稀疏时空图中，用双向资源标签直接生成新客户次序；载重、时间、电量、非线性
  充电和地域—日期—时段成本在生成时同步更新，有限车队与共享桩时隙对偶价格直接
  进入扩展排序。冻结三题×`LOCAL/RESOURCE-SLOT`共六任务的低成本门；当前仅证据
  审查和预登记。后续获批的冻结零目标工程门在进入`main()`前因同名
  `test_engineering`模块解析到旧封存目录而退出；候选完整目标评价0，真实任务与G0
  均未启动。用户随后只授权一次不改变机制/题/预算/阈值的纯接线v2；v2静态精确模块
  检查6/6通过，但正式六进程工程门的worker均因无法导入动态加载的runner模块退出，
  完成0/6、完整目标评价仍为0，判
  `HALT_ZERO_OBJECTIVE_ENGINEERING_OR_RESOURCE_GATE`，G0仍未启动。按v2任一失败
  即STOP的授权曾关闭。用户随后明确覆盖该限制，只授权v3修spawn worker并增加
  真实算例前六进程冒烟。v3冒烟6/6且六个不同PID，真实零目标工程6/6 PASS、完整
  目标评价0；但随后G0六任务的裸`import run_g0`全部解析到旧对偶候选runner，
  报`KeyError: 'k'`，完成0/6、完整候选评价0、无witness、无独立复算。性能门未被
  评价，按本轮授权不建v4、不重启。这是G0启动解析结论，不是算法效果结论，也不授权
  E3、论文、BKS/SOTA或`1+1>2`。终局记录见
  [v3工程PASS与G0 HALT](../e2_resource_slot_pricing_v3_g0_halt_20260725.md)。
- [资源—时隙定价最终隔离与效果门 STOP（2026-07-25）](e2_resource_slot_pricing_final_stop_20260725.md)
  — 用户最后授权根因级唯一包隔离，v1--v3 原证据保留且算法/题/预算/门槛零改。
  六进程身份冒烟和零目标工程门均 6/6 PASS；冻结 G0 六任务 6/6 完成、违约 0、
  独立重放 6/6 闭合。但 `RESOURCE-SLOT` 对三道强 HGS 起点改善 0/3、胜 LOCAL
  0/3，且没有选入旧池外负约化成本新次序路线或资源价格归因，正式判
  `STOP_RESOURCE_SLOT_PRICING_NO_LOW_COST_STRONG_HGS_HEADROOM`。禁止救援、
  扩大 China81、E3、BKS/SOTA、论文性能或 `1+1>2` 主张。
- [RC-EV-Split 状态规模停止（2026-07-25）](e2_algorithm_repair_and_mechanism_case_20260724.md) — 给定客户顺序联合切路线、车场、车型、非线性充电、有限车队和共享桩的精确标签法：15客户229状态完成，75/150客户均触发500,000状态硬上限，候选完整目标评价0，判`HALT_RC_EV_SPLIT_G0_STRUCTURE_OR_SCALE`；禁止加上限/束宽救援，下一步只可审计路线列池+限时MIP组装。
- [资源耦合 HGS 代理误判门最终停止（2026-07-25）](e2_resource_coupled_hgs_misranking_stop_20260725.md)
  — 六个冻结 `HGS-M` witness、576 个固定动作候选完成零搜索审计；仅 32 个能由
  完整模型完成，严格代理排序逆转 3/6，但完整严格改善 0/6、代理前八名漏掉改善
  0/6，判 `STOP_RCE_HGS_NO_VERIFIED_PROXY_MISRANK_HEADROOM`。禁止候选/动作/
  题/witness/阈值救援；三视角 HGS 与 v7 只作受保护备份，不开放 E3 或论文性能。

# 2026-07-27 China81 距离基线 O 开发集

- 权威目录：`baselines/algorithm_prototypes/china81_vs_opensource_20260727/`。
  用户授权采用 Claude 后来的执行修正：只新跑 `distance_only` O 臂 27 单元，
  F/E/M/MV 的 108 行只读复用 2026-07-24 v7 封存批。
- O 采用 PyVRP 0.12.2 HGS、`NoImprovement(3000)`、无墙钟算法停机；六进程门
  6 个不同 PID PASS。27/27 O 解完整可行、精确验解违约 0；最终 135/135 行，
  artifact manifest 复算失败 0。
- 开发集读数：MV 对 O 27/0/0，平均改进 2.284993816614392%；完整阶梯只
  15/27。E→M 为 4 改善、12 平、11 回退，是主要断点。可以说开发集上 MV
  稳定优于纯距离 O；不能说 O→F→E→M→MV 每层全面单调，也不能把新 O 与旧四臂
  写成同批、同机、同停止规则或等算力。
- O 的 27 个任务合计 CPU 1905.900621 秒、墙钟 2012.2741639169399 秒；停止代数
  3002--23537，中位 7159。旧四臂封存行只有 CPU，没有可独立恢复的墙钟字段。
- 当前裁决 `DEVELOPMENT_COMPLETE`，不自动授权全 81 题×5 seed 确认集。

# 2026-07-27 China81 距离基线 O 全量确认

- `china81_vs_opensource_20260727` 已完成确认集：81 题 × 5 种子 × 5 臂，共
  2025/2025 行；其中 O 新跑 405，F/E/M/MV 从 v7 封存只读复用 1620。
- 独立核验：2025 主键唯一；405 个 O 全部 PASS、精确可行、违约 0；81 题各 5 种子；
  runner/adapter 哈希零漂移；7 个产物哈希零失败；pytest 2/2、Ruff PASS。
- MV 对 O = 354 胜/46 平/5 负，平均改进 1.919118015025895%。可写“总体优于纯距离
  开源 HGS”，不可写“逐单元全面支配”。
- 完整 O→F→E→M→MV 阶梯仅 299/405；逐层改善/平/回退为 268/115/22、
  290/86/29、79/249/77、114/291/0。不能把每层机制包装成普遍单调正贡献。
- O 选择来源为纯距离搜索 390、共同初始解安全网 15。O 累计 CPU 18435.601032 秒，
  累计逐单元墙钟 19388.929480863968 秒，停止迭代最小/中位/最大
  3001/4121/30509。历史四臂与新 O 批不是同批、同机、同停止规则或等算力。
- 本裁决只关闭 China81 真开源对照。E2 整体关闭仍受公开新 BKS 的算法归属核验
  （当前 MV-HGS-SP 仅实测 2/18）和最终论文主张接线约束。

# 2026-07-27 E2 终局：公开归属 13/18，实验关闭

- 剩余 16 个公开新 BKS 目标按冻结 MV-HGS-SP 协议全跑，合并原 2 题后为
  13/18 PASS、5/18 FAIL；失败 PR14A、PR15A、PR15B、PR16A、PR24A，判
  `STOP_NOT_ALL_TARGETS_REPRODUCED`。禁止写 18/18 全复现或公开普遍优于 HGS。
- 16/16 新 witness 独立证书 PASS；另产生 5 个更低本地候选：PR12A 8147.450、
  PR14B 8653.985、PR22B 6402.949、PR23B 8316.672、PR24B 10482.724。
  仅 PR14B 的新增 0.183 严格归因 SP；其余为 HGS 或并列。
- 新 16 题累计进程 CPU 20790.890369 秒、逐任务墙钟和 21398.633284083975 秒；
  旧 2 题历史时间字段口径不同，不并入。
- 结合 China81 MV 对 O 354/46/5、平均改进 1.919118015025895%，E2 算法实验封存为
  `ALGORITHM_EXPERIMENTS_CLOSED_WITH_MIXED_EVIDENCE`。终局见
  `docs/handoff/e2_final_closeout_20260727.md`；主 TeX 同步属后续写作，不授权救援。

# 2026-07-27 公开算例 13/18 复现缺口诊断（论文可引用口径）

- 权威文档：`docs/handoff/e2_reproduction_gap_diagnosis_20260727.md`。
- 五题未复现 = 两类协议差异，非计算错误、非算力不足：
  ①阶梯截断 PR16A/PR24A（目标出自 12000→24000→40000 三级链共 76000 代，固定协议
  3×12000 只买前两级，MV 逐轮读数与该链逐级对应）；②max-of-N vs 单条链 PR14A/PR15A/PR15B
  （目标为两次独立 18000 代热启动的较好者；MV 单轮迭代与机时反而更多；PR15B 落在较差那次上，
  0.041 即两次之差）。
- 机制：SP 的 `min()` 仅保证单轮内不劣于自身路线池（48/48 成立），装配解写回作下轮起点后
  轨迹与纯 HGS 分叉，故无跨轨迹支配。禁止用"算力不足"为由重跑。
- 16 题全部低于 2013 年公布 BKS（−0.005%--−0.083%）**不得写成算法性能优势**（BKS 热启动
  + min 接受，不变差是结构性的），只能作为"公开基准值仍可改进"的基准侧发现留在热启动副账本。
- 论文 V2 §4.2 已改写第一批（见 HANDOFF 同日条目）；表 `tab:china81-summary` 加 O 列 + 编译
  为 Codex 待办；E3--E7 共 27 处占位仍无数据（China E3 仍 HOLD）。

# 2026-07-27 E2 统一重跑第 0 步环境阻断

- `E2-RERUN-UNIFIED-01` 第 0 步在目标 workspace-write 沙箱只做了一次 6-worker
  `spawn` 探针；`ProcessPoolExecutor._check_system_limits()` 调用
  `os.sysconf("SC_SEM_NSEMS_MAX")` 时得到 `PermissionError: [Errno 1] Operation not
  permitted`。合同要求改用非沙箱，当前会话无该通道，故判
  `HALT_NON_SANDBOX_EXECUTION_UNAVAILABLE`，不以单进程或其他沙箱配置替代。
- 45 个盲试跑与 2025 个正式单元均为 0；K=3000 的 95% L/S 门没有数据，K 不能定档。
  柴油价只补审批与 `prices.py` 注释痕迹，默认值和受保护三文件未改。代码级审计确认
  完成器读取城市柴油价、O 的严格改善安全网规则不变、五臂无需改保护文件即可另立统一
  runner。证据目录为 `baselines/e2_rerun_unified_01_step0_20260727/`。
- 同日第三、四条补跑续接时，会话仍只有 `workspace-write` 沙箱且禁止申请提权；按冻结
  合同未重试六进程配置、未降并发、未启动 runner。上一轮完整 traceback 已从会话日志
  恢复并追加到 `report.md` 和 `environment_probe.json`；45 单元仍为 0，K 与缩放仍未定。

# 2026-07-27 RESEARCH-EV-PAYLOAD-01 取证记忆节点

- 权威报告：`docs/handoff/research_ev_payload_01_20260727/report.md`；这是事实与描述统计，
  不构成载质量参数选择。五个官方完整样本均为 4495 kg，配置值 950--1700 kg，4/5 个车型的
  已列配置全部高于 1000 kg。
- 有效规则边界：GB 1589-2016 没有新能源商用车额外总质量额度；工信部联通装〔2022〕3号附件
  第一条第（二）项仅将新能源轻型货车排除在最低载质量利用系数要求之外；地方便利通行是路权，
  不是核定质量豁免。2026 GB 1589 修订材料仍是征求意见稿。
- Zotero 定向样本 6 篇：4 篇 EV/ICE 同载重，1 篇 EV 较低，1 篇 EV 较高；没有论文明确以
  电池质量推导 EV 载重折减。检索技术边界与 PDF 哈希见报告证据目录。
- 原始服务器页面字节因沙箱 DNS 限制未能保存；现有哈希对应规范化页面文本快照。后续如需原始
  HTML/PDF 字节哈希，应在非沙箱网络环境按已存 URL 复抓，不能把当前哈希冒充原始响应哈希。

## E3/E6 执行绑定只读预检（2026-07-27）

- [E3E6-BINDING-PREFLIGHT-01 报告](../../../baselines/china_e3_e7/e3e6_binding_preflight_01_20260727/report.md)
  — 只读静态审计与设计取证；搜索评价 0。D3 多维容量硬锁可在受保护文件之外实现，
  但旧语义门和预算 pilot 的算法源码哈希已漂移，须在用户拍板与源码冻结后重放。
  旧独立车场子搜索不能直接消费当前 China81 权威，且不等价于同算法硬锁对照。
  D2 推荐输入驱动 `R_d`、储备 1.25 与 1.10/1.25/1.50 面板，2 x 22 kW 仅为构造
  情景；D4 推荐 80 次完整候选、单线程、墙钟仅熔断并补 CPU 独立报告。
  81 实例可聚合为 27 格且格内三图互斥，但跨规模客户身份复用显著，27 格不能无条件
  解释为 IID 地区样本。状态=`DRAFT_BINDING_OPTIONS_AWAITING_USER_APPROVAL`。

## E2-RERUN-UNIFIED-01 新车型预检与统一批启动（2026-07-27）

- 新 EV 绑定为 `FOTON-AUMARK-ES1-EXPRESS-STAKE`，1700/2600/4495 kg、
  77.28 kWh；迎风高度 2.480 m 是
  `HEIGHT_ASSUMED_SYMMETRIC_WITH_CV_FIELD_INCOMPLETE` 情景假设，不是官方
  配置车高。旧值、柴油价新旧痕迹和外层轮次定义见
  `docs/handoff/model_change_approval_register_20260718.md`。
- 九题完整模型预检在
  `baselines/e2_rerun_unified_01_20260727/vehicle_feasibility_preflight/`
  判 `PASS_NEW_VEHICLE_PAIR_FEASIBILITY_PREFLIGHT`：9/9 可行、四类违约均为 0，
  EV 客户占比中位数 32.5%（范围 28.0%--56.0%），历史基线 7.8%。
- China81 五臂同批基础矩阵 2025 单元已用 6 个 spawn 进程启动，状态
  `FULL_UNIFIED_RERUN_RUNNING`，并非完成证据。K=3000 和饥饿加倍规则冻结；
  MV 最多 3 轮、连续 2 轮无严格改进即停。不得在最终四件套、独立验解和论文表源
  全部生成前引用胜负或平均改进。

## E2-RERUN-UNIFIED-01 第 0 步收敛试跑（2026-07-27）

- `baselines/e2_rerun_unified_01_step0_20260727/` 是第三、四条权威证据：
  9 题 x 5 臂 = 45/45 单元、6 个 `spawn` 进程、seed 1。MV 三视角每个都
  独立跑完 `NoImprovement(3000)`。
- K=3000 只有 20/45 满足 `L/S < 0.5`。原轨迹推导的全局 K=21000 和
  `K(n)=max(5000,110n)` 都使 43/45 过 95% 门，但未重跑验证。大规模层
  15/15 偏晚，小规模层中位 S=3101 是早停/饥饿指纹。
- 本门只报机时、收敛形状和工程可行性，不是臂间成本或性能证据。第 1 步
  2025 单元仍未授权且未启动；旧 HALT 记录已保留。

## E2-RERUN-UNIFIED-01 正式批洁净重启（2026-07-27）

- 首次 6-worker 正式批与另一 6-worker 收敛池重叠，限时 MIP 的墙钟求解工作
  不可比；安全停止时的 165 个完整尝试行全部归档到
  `baselines/e2_rerun_unified_01_20260727/contaminated_partial_run_oversubscribed/`，
  只能作诊断证据，不得用于论文、臂间比较、饥饿判定或正式续跑。
- 洁净批从空任务账本以 4 workers 重启；其余 STEP1-040 合同不变。运行器持续
  检查外部实验 Python 池，发现后先写证据并暂停整批。正式 `artifact_hashes.json`
  排除所有 `.monitor` 目录及受污染归档。
- PID/PGID 23367 已进入 `RUNNING`；首个原子检查点 3/2025，监控 findings=0，
  隔离守卫无异常。当前只是健康启动证据，不是完成或臂间胜负证据。

## PAPER-ALGCHAPTER-01 算法章正式协议接线（2026-07-27）

- 报告：`docs/handoff/paper_algchapter_01_20260727/report.md`。
- `docs/paper_v2/paper_main.tex` 的算法步骤已改为三阶段、六步骤：三视角逐一
  `NoImprovement(K)`、跨轮累积路线池、限时 MIP 路线池集合划分、`min()` 安全网、
  最好解写回和外层收敛停机。`algorithm_flow.tex` 的右侧回线说明移到回线内侧。
- E2 禁止主张扫描通过，China81 现有数字与 `DATA_PLACEHOLDER` 未改。历史封存表图
  被明确区分于新正式协议，不能作为新协议已验证的证据。
- 当前 XeLaTeX/MiKTeX 在受限环境中于读取源文件前阻塞，Tectonic 离线资源亦不可用；
  状态为 `WRITING_COMPLETE__HALT_XELATEX_RUNTIME_UNAVAILABLE`。旧21页 PDF 不属于
  本任务；后续必须补两遍 XeLaTeX、日志计数和流程图逐页渲染复核。

## E3E6-GATES-01 前置门（2026-07-29）

- 详细记忆：`docs/handoff/memory/e3e6_gates_01_20260729.md`；权威证据：
  `baselines/china_e3_e7/e3e6_gates_01_20260729/`。
- D2-A 在当前 K7/ES1 车型对下以 81 个零搜索 witness 通过；144 个逐场 `R_d`
  与旧只读权威相同。D3 当前源码四层守卫闭合，但只有 45 个多车场实例能在处理臂
  构造跨场服务；36 个单车场实例拓扑上不可能，故总判决
  `HALT_AT_GATE_2_D3`。
- D4 未运行且未查看臂间成本；源码预检确认固定 80 次完整候选评价而非
  `NoImprovement`。后续必须等用户裁定单车场实例适用域或处理臂定义，执行代理
  不得自行放宽门槛。

## E4-CARBON-TIMING-01 固定解零搜索复算（2026-07-29）

- 详细记忆：`docs/handoff/memory/e4_carbon_timing_20260729.md`；权威证据：
  `baselines/china_e3_e7/e4_carbon_timing_20260729/`。
- 405 个 MV 固定解×28 电网日共 11340/11340 行，完整搜索候选为 0；充电侧排放
  减幅 54.9704%，系统总排放减幅 9.7463%，电费增加 134.8798%，移动电量
  98.3386%。有效规模区间为 `[10, 200]`，必须同时报告明显电费权衡。
- 405 个源解与 22680 个两臂解独立复算均为 0 违约；受保护三文件未改。
  v3 择时值逐行等同 v4，但 v3 缺正式批准状态列；profile 用 v3，非择时 bundle
  外壳用 v4，边界不得省略。请求 4 workers 因沙箱权限机械回退为 1 worker。

## E3-RESPONSIBILITY-MISMATCH-01 当前源码门二 PASS、预注册 HALT（2026-07-29）

- 详细记忆：`docs/handoff/memory/e3_responsibility_mismatch_20260729.md`；
  权威目录：`baselines/china_e3_e7/e3_mismatch_20260729/`。
- 门二在当前源码和多车场适用域上 45/45 PASS；36 个单车场按用户更正排除。
  主展品 `cn-prd-50c-01-V2-LOCATIONS` 的 0/25/50% 三档共同输入均在 D2-A
  上限内通过独立检查器。
- 稳定性预注册未封口：当前 50% 哈希错配使
  `cn-jjj-100c-01-V2-LOCATIONS` 天津场需 10 条路线而 D2-A 总上限为 7；
  另有 12 个三/四车场实例缺唯一的“另一车场”目的地规则。状态
  `HALT_PREREGISTRATION_METHOD_APPROVAL_REQUIRED`，pilot/正式搜索均未启动，
  未读取臂间成本差异。任何条件化映射、D2 扩展、部分服务或主展品单独放行均须
  用户明确批准。

## E5-NONLINEAR-CHARGING-01 盲 pilot 结构性 HALT（2026-07-29）

- 详细记忆：`docs/handoff/memory/e5_nonlinear_charging_01_20260729.md`；
  权威目录：`baselines/china_e3_e7/e5_nonlinear_20260729/`。
- 32/56/80/160/240 五档结果盲 pilot 均不通过；两臂各档饥饿单元数为
  12/11/12/13/13（分母始终 15）。150 条 pilot 记录不含目标值或臂间成本差。
- 160 与 240 档中，50c-01 的 9 个相同种子对两臂都在 `S-1` 最后严格改进；
  当前扩档只在最终路线池重组前增加评价，结构上不能提供重组后的剩余预算。
  判决 `HALT_PILOT_STARVATION_SCHEDULE_NOT_CONSTRUCTIBLE`，320 单元和正式搜索
  均为 0。继续须用户批准重组后评价调度或另一饥饿定义。
- 四个强制科学端点均为
  `NOT_RUN_UPSTREAM_PILOT_STARVATION_GATE_HALT`；不得推断科学方向。终态四件套、
  报告、HALT `done.json` 和保护哈希已闭合。

## E3--E7 技术底座候选与用户决策边界（2026-07-30）

- 详细记忆：`docs/handoff/memory/mechanism_foundation_options_20260730.md`；候选底座：
  `baselines/china_e3_e7/mechanism_foundation_20260730/`；E5 B 技术复判：
  `baselines/china_e3_e7/e5_option_b_assessment_20260730/`。
- 三题候选输入与 15 条 E7 JSON/TSV 事件流已通过零搜索技术验收，但算例分工、E5 A/B、
  E7 阶段预算均保持 `AWAITING_USER_APPROVAL`；正式搜索仍为 0。
- 方案 B 只读取盲态改进序列复判为 12/9/7/5/5（每臂分母 15）；240 档仍不通过，
  即使用户批准 B 也须从 320 档继续盲 pilot。不得把技术可构造写成方法已批准。

## Codex → 新 Claude 主交接（2026-07-30）

- 当前第一入口：`docs/handoff/session_handoff_20260730_codex_to_new_claude.md`；随后必须完整读
  老 Claude 的 `session_handoff_20260729_document_hierarchy_and_e5_e3e6_state.md`。
- 新交接纠正旧实时状态：当前无实验/项目监控运行；E5 HALT、E3/E6 56/135 故障现场、
  E7 未批预算均未被技术底座解除。E3--E7 算例分工、E5 A/B 和 E7 阶段预算仍须用户批准。
- `396e2931` 中旧 E3/E6 目录只作故障/中间证据留档，不得把提交状态误认作可执行授权。

## E3-ZONE-JOINT-COMPARISON-20260731 正式收口（2026-07-30）

- 详细记忆：`docs/handoff/memory/e3_zone_joint_20260731.md`；权威目录：
  `baselines/china_e3_e7/e3_zone_joint_20260731/`。40/40 正式单元与独立认证通过，
  `done.json.status=COMPLETE`，共同候选上限 400，先 50c 后 100c。
- 硬锁候选 bug 的可证实路径是 `epochal_hgs.py::_run_exact_epoch` 的
  `terminal_population_archive`；旧 14/14 异常均来自该路径。修复把完整补全后
  仍跨场的硬锁候选作为正常约束筛除并计入消费，不改算子、JOINT 或路线池语义。
  JOINT 50c seed1 改前/改后解哈希与完整目标逐位一致。
- 行政 `customer_home_depot` 与最近车场为同一输入（50c 0/50、100c 0/100），
  因而不跑恒等的 IND。JOINT 相对 ZONE 降本 2.272759%/0.693115%，总体等权
  1.482937%；车辆减少但距离和碳排均上升，必须保留该权衡，不能包装成全面改善。
- 故障前 18 个 PASS 目标值和旧 L-main 数字未进入效应判断。若用次近车场、更细
  行政区划或容量均分构造 IND，属于新科学定义，继续前必须用户裁决。

## E6-FAIRNESS-20260731 成员账本闭合、候选池缺失停机（2026-07-30）

- 详细记忆：`docs/handoff/memory/e6_fairness_20260731.md`；权威目录：
  `baselines/china_e3_e7/e6_fairness_20260731/`。状态
  `HALT_E3_NESTED_CANDIDATE_SOLUTIONS_NOT_PERSISTED`，`search_reruns=0`。
- 既有 `calculate_depot_profits()` 足以核算成员收益；I/U 分别复用同 seed 的
  E3 ZONE/JOINT 最终解，20 对成本分摊全部闭合。θ=1 下 U 自然帕累托为
  0/20（两个算例各 0/10）。
- E3 JOINT trace 只有逐候选总成本/状态，没有候选解或成员账本；运行时候选池
  已消失，故 F、公平代价和 F 弱势成员改善均不可识别，不能用 I 回退冒充最低成本
  F。继续须用户批准 U-only 候选持久化回放；当前只保留 E3 降本少车但里程/碳排
  上升的完整权衡。

## E6-FAIRNESS-V2-20260731 候选池补齐与 I/U/F 收口（2026-07-30）

- 详细记忆：`docs/handoff/memory/e6_fairness_v2_20260731.md`；权威目录：
  `baselines/china_e3_e7/e6_fairness_v2_20260731/`。只重跑 JOINT 20 个单元，
  ZONE 重跑 0 个；20/20 最终解、目标浮点位、消费数、分类 trace 和终止原因均与
  E3 逐项一致，受保护源哈希未漂移。
- 2869 个完整可行评价事件形成 2764 个逐单元去重候选；路线、车场、客户、充电、
  完整目标和成员账本均已持久化并由独立 checker 复算。嵌套候选只用于同单元 F
  筛选，没有被当作独立样本。
- θ=1 下 U 自然帕累托为 0/20；参与可行候选总数也是 0，故 20/20 个 F 均依合同
  回退到 I。F 相对 U 的成本增量为 50c 2.325615%、100c 0.697952%、两算例行
  等权总体 1.511784%；弱势成员收益改善总体均值 755.018 元。
- 结论不是公平机制成功：不允许转移支付时，当前候选空间中的跨场协同无法同时满足
  两方参与。解释必须同时保留 E3 的有限降本/少车与里程、碳排上升权衡。转移支付
  及 Shapley/MCRS/贡献分摊均未采用，属于待用户裁决的新研究范围。

## E6-POSTHOC-TRANSFER-PAYMENT-TEX-20260731 数学复核与论文应用

- 详细报告：`docs/handoff/transfer_payment_applied_20260731/report.md`；
  状态 `COMPLETE`。输入为 v3 fairness 和 allocation 的封存 `raw_runs.csv`，
  两个算例各 10 个种子，全 20 单元进入复算。
- 独立实现按排列定义计算两人 Shapley 值，6/6 项数学检查通过。预算平衡最大绝对
  误差为 0 元；19 个核非空单元的个体理性违规为 0；100c seed 4 的
  \(\Delta=-1.135377416539\) 元，个体理性最小收款之和为
  1.135377416540 元，与预算平衡矛盾。
- 用户批准稿的 11 处原文全部精确匹配并应用到 `paper_main.tex`。XeLaTeX 编译
  成功，PDF 25 页，未定义引用 0，Overfull/Underfull 各 1 处。全文结算口径一致，
  中文与英文摘要同步，新增符号均在正文使用，新增四项引用均有文献条目。
- 本轮实验重跑 0；参与下界、`\theta=1`、目标函数、路线约束以及 `cost.py`、
  `check.py`、`search/evaluation.py`、`profit.py` 保持原值。

## E3-MISMATCH-RESTART-20260731 全量错配复核与源合同漂移停机

- 详细记忆：`docs/handoff/memory/e3_mismatch_restart_20260731.md`；权威目录：
  `baselines/china_e3_e7/e3_mismatch_20260731/`。状态
  `HALT_SOURCE_CONTRACT_HASH_DRIFT_BEFORE_SEARCH`，probe/formal/search
  evaluations 均为 0。
- 81 实例、5805 客户全量审计确认 6 个非零错配实例、24 个错配客户
  （0.413437%），与对抗性审查一致；三个 150c 和三个 200c 全部预注册，
  IND/ZONE/JOINT、种子 1--10 和预算探针规则均在搜索前锁定。
- 等待算力时，预注册源合同 SHA-256 从 `075f0093...f503b5e` 漂移为
  `0e10e8ea...742c35`；监控按硬门 `SIGSTOP` 并保存现场。六个求解/搜索保护
  文件未漂移，漂移后的合同未重签。重启须用户指定合同权威版本并使用新目录。

## E7-DYNAMIC-V3-150C-PARALLEL-20260730 完成

- 详细报告：
  `baselines/china_e3_e7/e7_dynamic_v3_20260731/parallel_150c_report.md`；
  150c 40/40，`scale_complete.json=COMPLETE_150c`，40 个单元均为
  `LEGAL_INFEASIBLE`，没有补零或替换目标。
- 100c 保护基线 16 个非 `._*` 文件终验哈希 16/16 不变；终验现场 100c
  34/40、六 workers 仍运行。150c 因外部 100c 扩到六 workers 而按负载证据从
  4 降为 2，总并发维持 8；科学配置与六个保护源均未改。

## E3--E7 文献重建底座（2026-08-01）

- 详细记忆：`docs/handoff/memory/e3_e7_rebuild_foundation_20260801.md`；状态
  `AWAITING_USER_APPROVAL`。新目录为 `e3_scattered_ownership_20260801`、
  `e5_enroute_nonlinear_20260801`、`e6_contractor_participation_20260801`、
  `e7_trigger_policies_20260801`。
- E3 临时混合车队短试有强效应但不能正式使用；Soriano `40 CV/场、0 EV` 的 12 个初始输入均可行，
  卡点是共享入口错误要求 EV>0。E5 不换旧 50c/100c 算例，100c 在 `22 kW/16 kWh` 下出现线性
  方案的非线性物理假可行。E6 当前短试实际零合作效应，根因是未接散乱客户归属。E7 触发和合法车辆底座
  已就绪，正式事件流未选。
- 13 项定向测试通过，E5/E6 60 项产物哈希一致。正式车队、E4 初始电量与联合目标、E5 容量范围、
  E6 所有权/摩擦语义、E7 完整事件流五项必须由用户一次性拍板；不得把短试或技术底座写成正式结果。
