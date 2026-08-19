CROSS_AUDIT_CODEX_DONE

# Codex 独立交叉审核（2026-08-17）

## 口径与边界

- 范围：`pending_decisions.md` 中 59 个顶级登记槽（P43–P96，含重复/补充标题），并吸收 P43-I、P46 补充、P87 执行登记、P84 再纠正、P92 补充等子登记；另列 P81–P96 原话中提取的 30 条未编号要求。
- 四档判词仅用：`已落实(A级)`、`未落实`、`存疑(待A级取证)`、`已覆盖(被Pxx)`。没有“部分”。复合条目只要尚缺决定性部分，就判“未落实”，并分别写明已做与缺口。
- A 级是本轮直接打开源码、数据或原始 CSV/JSON 后核到的字段；B 级是报告/设计稿的结论；C 级是未找到可核证据。B 级没有单独支撑任何“已落实”。
- 证据级别评价的是“本判词靠什么得出”，不是完成度；因此 A 级原件也可以直接证明“未落实”或“存疑”。
- 独立性：本轮没有打开 `docs/handoff/compliance_checklist_20260817.md`，也没有在锁定下列新判词前读取上一轮 Codex 判词。
- 论文版本身份：`docs/handoff/CURRENT_PROJECT_CONTEXT.md:1776` 指定当前基础稿为 `paper_main_foundation.md`；名字更像新版的 `paper_main_foundation_v2_20260812.md` 不是本轮正文合规依据。
- r15（P95 三件事）在本轮取证截止时仍在施工。其 14 个在途源码/测试文件、`round15_three_approved_20260817/`、隔离区真删和 `.git/objects.round15.*` 被隔离，不用于本轮判合规。收尾复查时 PID 6013 已退出，`report.md`/`decision.json` 的文件系统 mtime 均为 `2026-08-17 22:23:57 +0800`；这是截止后的新状态，只登记、不让新报告自证完成。
- “已覆盖”只表示旧要求被后来的用户决定替换，不表示新要求已经实现。
- 路径约定：表内 `pending_decisions.md` 均指 `docs/paper_gci_dmm_vrp_20260804/pending_decisions.md`；“目标例”均指 `data/ChinaInstances/china81_final_suite_v2_20260815/instances/cn-jjj-50c-01-DEPOTSEARCH-d996f755bd/`；未写更长前缀的实验包目录均位于 `solver/reports/`。同名文件仍在单元格中给出唯一包目录，不能跨包替换。
- 本轮唯一写入是本报告。五个冻结文件只读，收尾 SHA-256 分别为：`cost.py=13ae664bae0e9c8b5033780fbbc43cedcd43c626ac1eb23023a4a667bd2d1bbd`、`check.py=1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072`、`search/evaluation.py=c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3`、`problem_hgs/charging.py=3a7da9df0241bed566240d9e9359be4b7dc6e0edd8a385d085ddce48482fc2a5`、`resetp_alns/support/charging.py=7c2d8df0427626ef7c1ab487dbb44360ea82e07d6e9ce3b0e889502f27cfc171`。

## 一、59 个登记槽逐条重查

| 序号 | 编号 | 要求要点 | 判词 | 证据级别 | 本轮直接证据 | 已做什么；缺什么 |
|---:|---|---|---|:---:|---|---|
| 1 | P43 | 算例重建 A–K；含两个同号 P43-I：最小接线、60 kW；恢复两班、EV 溢价、三大机制与论文口径 | 未落实 | A | `data/ChinaInstances/china81_final_suite_v2_20260815/instances/cn-jjj-50c-01-DEPOTSEARCH-d996f755bd/shift_contract.json:2-34`；`solver/src/setp_solver/china81.py:47-52,948-1008`；`solver/reports/time_carbon_3arms_20260817/raw_runs.csv:2-5`；`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:21,33-45,213-248,294-304` | 已有两班、午休回场、7.2 m³、EV 220 元/日、60 kW 与健康见证；三臂正式行全未跑，当前稿仍是单企业、多视角旧算法与恒功率基础模型，A–K 没有整体闭环。 |
| 2 | P44 | 单一货币总账；企业看钱、政府看排放；另做碳价扫描 | 未落实 | A | `docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:101-136,288-330`；`solver/reports/time_carbon_3arms_20260817/raw_runs.csv:2-5` | 单目标货币总账已经写入模型；碳价扫描、可复核“甜点”结果与正式三臂数据没有产生。 |
| 3 | P45 | 同机净机等墙钟；保留时间列、删除完成代数；冻结 HGS 不进公开正式表 | 未落实 | A | `docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:270-276` | 表壳已有时间列且已删完成代数；但正式结果包不存在，稿件只写“同机开源求解器”，未钉死其身份，不能 A 级证明等墙钟已执行或冻结 0.12.2 HGS 已排除。 |
| 4 | P46（含补充） | 81 例按 30%–45% 可争夺统一重锚；优先换真实都市圈车场，不硬造客户；达不到要 FLAG | 已覆盖(被P65) | A | `pending_decisions.md:235-247,717-726,749-763` | P65 后来明令“不再按可争夺比例最高”且“不重摆客户几何”；低可争夺反而是现行协同判据。旧 30%–45% 门不能再用来判 d996 失败。套件 81/82 冲突仍是缺陷，转入 P92 根审计而非复活 P46。 |
| 5 | P47 | 由本算法、本算例、本机收敛曲线定预算；平台点加余量；收敛图同时入文 | 未落实 | A | `docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:258,274,278-286`；`solver/reports/fix_cost_cache_20260817/deep_summary.json:48-63` | 有诊断性深跑点，但原件明确标注不是正式收敛结果；稿件仍是占位，正式预算尚未由最终算法曲线冻结。 |
| 6 | P48 | 班次可达性 fail-closed；两班都不可达则 FLAG；混合车队健康用 below/above 两侧非零 | 已落实(A级) | A | `solver/scripts/build_china81_suite_rebuild_20260812.py:342-490,1885-1927`；目标例 `shift_contract.json:14-20`；`suite_health_v2.csv:83` 原字段 `PASS_TWO_SIDES` | 构建器、班次合同和健康字段均直接存在；本条允许失败后 FLAG，不要求每例都通过 P46 的几何门。 |
| 7 | P53 | 代表算例统一到京津冀单一算例 | 已覆盖(被P65) | A | `pending_decisions.md:265-303,684-764`；P65 选中 `cn-jjj-50c-01-DEPOTSEARCH-d996f755bd` | 原来只定地区/候选族；P65 用新的事前协同筛选与实例身份替换了具体选择规则。 |
| 8 | P53 补充 | 公平章保留；统一实例为 jjj-50c PRDFIX 一族 | 已覆盖(被P63/P65) | A | `pending_decisions.md:286-303,391-453,684-764` | 公平章由 P63 重新定义，具体实例由 P65 改选 d996；旧 PRDFIX 指定不再是当前合同。 |
| 9 | P51（2026-08-13） | 充电账、全公司排放、全公司货币总账三尺度同处、同序、带分母全报 | 未落实 | A | `docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:288-306`；`solver/reports/time_carbon_3arms_20260817/raw_runs.csv:2-5` | 稿件表壳已列运营成本、充电侧排放和系统排放，但无真实值、固定顺序与分母回填；原始包只有失败探针，三条正式臂未跑。 |
| 10 | P61 | 排程承认班次起点/车场开门；默认关、合同实例开；不放宽 checker | 已落实(A级) | A | `solver/src/setp_solver/algorithms/problem_hgs/evaluation.py:433-568`；`solver/src/setp_solver/search/multitrip_schedule.py:389-398`；目标例 `shift_contract.json:23-31` | 源码把班次最早发车传入排程，合同给出 AM 480、PM 780 分钟；没有用放宽 checker 代替。 |
| 11 | P64 | 内部统一按构造数据；但正文不写“一切均为构造”的总声明 | 已落实(A级) | A | `pending_decisions.md:353-389`；`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:254-258` | “内部统一认定构造”的决定已正式留档；当前稿只对实例和仿真订单的实际构造性质作局部说明，没有写“全文一切数据均为构造”的总免责声明。 |
| 12 | P63 | 公平章、参与约束与分法；多企业术语；两/四车场算例体系 | 未落实 | A | `docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:21,41,250-338`；目标例 `enterprise_assignment.csv:1-51`；`solver/reports/main3b_backend_20260816/raw_runs.csv:2-4` 原字段 `fairness_status=NOT_WIRED_FAIRNESS_NOT_IN_DYNAMIC_DECISION` | 25/25 企业归属文件已建；当前稿仍写单一企业/车场归属且没有公平节，动态原始行也明确 fairness 未接入。 |
| 13 | P62 | 只跑 DEPOTSWAP、禁止其他新 China81 族 | 已覆盖(被P62-A) | A | `pending_decisions.md:454-527` | 当晚 P62-A 明确解封 FS、PRDFIX、METRO、DP、GZ-FS、DEPOTSWAP，旧禁令不再适用。 |
| 14 | P62-A | 解封全部新 China81；旧 V2 继续禁；算法运行前不预锁统一实例 | 存疑(待A级取证) | A | 六个新套件目录现存；`pending_decisions.md:490-527,684-764` | 数据目录可见，且后续 P65 已改变“不预锁”的阶段状态；当前实例路由/测试入口有 r15 在途文件，不能据其当前内容证明所有新族都真能加载且旧 V2 全禁。缺稳定版入口映射与逐族加载原始记录。 |
| 15 | P58（作废令） | 废除照搬 Du 的上下两格负荷图；先定要证明的话再选体裁 | 已落实(A级) | A | `pending_decisions.md:528-545`；`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:300-304` | 当前图壳已改为上格碳强度、下格两策略充电量，不再把两种策略各占一格照搬 Du；这里只判“旧体裁已废”，不把占位图冒充成成图。 |
| 16 | P58（旧原文） | 旧式上下两面板、碳强度只放下格 | 已覆盖(被P58作废) | A | `pending_decisions.md:528-564` | 紧邻的新 P58 明确把旧体例实质作废；不得再把旧图当未完成任务。 |
| 17 | P59 | 单幅混合车队图：横轴碳价，纵轴 EV/CV 数量 | 未落实 | A | `docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:308-314` | 当前只有车队可用结构表壳，没有碳价扫描图和真实数据。 |
| 18 | P60 | 恢复公平分配表，按单干/分摊/节约量/比例组织 | 未落实 | A | `docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:250-338`（实验章无公平节/表）；`solver/reports/main3b_backend_20260816/raw_runs.csv:2-4` | 公平正式表未进入稿件；动态数据仍标公平未接线。 |
| 19 | P57 | 私有统一算例上的本文算法收敛图；先比较消融曲线再决定单/多线 | 未落实 | A | `docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:278-286`；`solver/reports/fix_cost_cache_20260817/deep_summary.json:62` | 只有占位图；现有深跑被原件限定为验收副产物，不能冒充正式收敛曲线。 |
| 20 | P56 | 指定旧车场对、客户不动并重算可争夺性 | 已覆盖(被P65) | A | `pending_decisions.md:623-636,684-764`；目标例 `nodes.csv:1-3` | P65 后来按另一套事前协同收益规则选中 d996 车场对，旧指定不再控制统一实例。 |
| 21 | P54 | 柴油 7.48 元/L；公共充电服务费 0.4 元/kWh | 已落实(A级) | A | `data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723/tariff_carbon_hourly_calendar.csv:1-2` 原值 `0.4, 7.48, diesel_parameter_status=APPROVED_CHINA_E3_FORMAL_RELEASE_001`；`solver/src/setp_solver/china81.py:1085-1102,1339-1360` | 当前运行时明确要求批准状态并读取 7.48；旧候选列仍保留 `PENDING...` 作为历史身份，不是现行状态。服务费原字段为 0.4。 |
| 22 | P55 | 最终浮点常量直接存储；EV 非能源里程成本不得运行时相加 | 已落实(A级) | A | `solver/src/setp_solver/china81.py:47-52,985-1004`；`data/ChinaInstances/china81_private_rebuild_v1_20260811/vehicle_costs.csv:1-3` | 运行时直接取 `EV_NON_ENERGY_CNY_PER_KM=0.9145`；0.6700 与 0.2445 分项只留在来源表，没有在成本链运行时相加。 |
| 23 | P52 | 每个机制臂从头重优化路线；统一完整评价；多种子 | 未落实 | A | `docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:294-302`；`solver/reports/time_carbon_3arms_20260817/raw_runs.csv:2-5` | 第一组表壳允许联合重优化，但第二组仍固定路线/车型/服务关系；实际三臂没有完成，更无多种子统一完整评价。 |
| 24 | P49 | 公开改搜索内核争优；私有做问题导向创新；两手都抓 | 未落实 | A | `solver/reports/fullflow_smoke_20260817/raw_runs.csv:2-14`；`solver/reports/fullflow_smoke_20260817/decision.json:3-16` | 私有静态/消融探针可跑；公开入口 BROKEN，时变碳和混合车队也 BROKEN，双线未闭环。 |
| 25 | P50 | 图表壳→效应规格→算法/算例→施工→回填的倒推方法 | 存疑(待A级取证) | B | `docs/paper_gci_dmm_vrp_20260804/figure_first_design_chain_20260812.md:1-89`；`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:250-330` | 能看到图表壳和过程报告，但它们只能证明“写过方法/占位”，不能 A 级证明后续每项施工都由图表目标倒推。缺图壳—数据—runner—成图的一一原始映射。 |
| 26 | P51（旧待决） | 在充电侧账与全系统账之间二选一 | 已覆盖(被P51-20260813) | A | `pending_decisions.md:304-318,678-682` | 新 P51 取消二选一，改为三个尺度全报。 |
| 27 | P65 | 多企业协作身份；编号对半归属；按一阶协同收益事前选 d996 | 未落实 | A | 目标例 `enterprise_assignment.csv:1-51`、目标例 `enterprise_assignment.provenance.json:2-24`；`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:21,41` | 25/25 归属与 d996 已落数据；摘要、引言和问题描述仍是单一企业/车场归属，模型身份没有同步。 |
| 28 | P66 | 企业归属追加；静/动态整体设计；先死因普查；低成本探针；平级对撞 | 未落实 | A | 目标例 `enterprise_assignment.provenance.json:2-24`；`solver/reports/fullflow_smoke_20260817/decision.json:3-21` | 归属追加与低成本全流程普查已做；整条动态/公平/混合载具仍有三处 BROKEN，设计没有达到本条整体完成态。 |
| 29 | P67 | EV 异常修复、完整教育后提交；公开/私有三位一体；混合翻译器；分法按成绩选 | 未落实 | A | `solver/reports/fix_decoder_dag_20260817/raw_runs.csv:2-6`；`solver/reports/fullflow_smoke_20260817/raw_runs.csv:2-14`；`solver/reports/main3b_backend_20260816/raw_runs.csv:2-4` | 翻译器/DAG 与完整评价链有 A 级原件；公开仍 BROKEN，动态公平未接，分法正式选择与全流程成绩未完成。 |
| 30 | P68 | 有条件自主施工；同一门两败或优点受损就停；不越冻结/正式实验边界 | 存疑(待A级取证) | B | `solver/reports/sc0_witness_adapter_20260816/decision.json:1-18`、`solver/reports/sc1_ownership_wiring_20260816/decision.json:1-18`、`solver/reports/sc2_switch_wiring_20260816/decision.json:1-18`、`solver/reports/sc3_charging_gap_20260817/decision.json:1-23` 只提供分散结论 | 没有一份 A 级事件账把每个门的尝试次数、停/继续原因、保护边界串起来。缺逐门原始事件和哈希对照，不能仅凭报告判“遵守”。 |
| 31 | P69 | 批准 SC8；查问题→设计→辩证→施工；重大变化同步四份事实源 | 未落实 | A | `solver/reports/fix_decoder_dag_20260817/raw_runs.csv:2-6`；仓库检索 `FIX_S0_HALT` 只命中 `docs/handoff/CURRENT_PROJECT_CONTEXT.md:516`，未命中 `pending_decisions.md`、`HANDOFF.md`、`docs/handoff/memory/MEMORY.md` | SC8/DAG 有原始运行，但已知重大事实没有同步进四处，直接违反 P69-4；不能用设计/对辩报告掩盖同步缺口。 |
| 32 | P70 | 8 组合小阵列联合调 U/邻域/μλ/num_close；按 family 共参；再由数据定第二轮 | 已覆盖(被P79) | A | `pending_decisions.md:958-971,1294-1307` | P79 后来明令算法定稿在前并“暂缓 P70 调参阵列”；旧阵列当前不应施工。暂缓不等于调校已完成。 |
| 33 | P71 | 目标导向的平级博弈；不把手段当目的；困难时绕路 | 已覆盖(被P83/P84/P90) | A | `pending_decisions.md:973-996,1408-1468,1560-1582` | P83 细化换维打法，P84 细化平级协作，P90 细化 ROI；以后三条为现行口径。 |
| 34 | P72 | 动态流独立接入且关闭态不污染基础例；非线性充电用于物理保真；纠正公平退化假设 | 已落实(A级) | A | `data/dynamic_streams/cn-jjj-50c-01-DEPOTSEARCH-d996f755bd_q500_t30_17ffb3f5d091/metadata.json:2-29,56-68`；同目录 `generation_rules.json:2-10`、`serviceability_check.csv:2-11`；`solver/src/setp_solver/charging_curve.py:86-116`；`/Users/zhouleixishu/Zotero/storage/72THJGSQ/Montoya 等 _ 2017 _ The electric vehicle routing problem with nonlinear charging function.pdf` PDF p.1；`/Users/zhouleixishu/Zotero/storage/2JBQSR8A/21级邱莹莹大论文.pdf` PDF pp.30-31；`solver/reports/c7_fairness_ledger_20260816/ledger_partial.json:67-89` | 流有独立哈希、生成规则和服务性检查；基础实例哈希被保存；源码是 PWL 曲线。原论文直接说明忽略非线性会导致不可行/过贵，基座原文则是每次充满加标量充电速率；公平原始账的 r1/r2 数值确实不同。 |
| 35 | P73 | 单种子比较不可判读；丢失产物不得当结果 | 已覆盖(被P79/P80) | A | `pending_decisions.md:1037-1074,1294-1356` | P79 后定正式 10 seeds，P80 后定持久产物和丢失结果降级；旧单种子数字不再承担结论。 |
| 36 | P74 | 删除第三方外包语义；动态触发按本例分布冻结；复用 runner | 已落实(A级) | A | `docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:316-328`；`solver/reports/main3b_backend_20260816/metadata.json:3-33`；同目录 `raw_runs.csv:1-4` 原字段 `outsourced_customer_ids` 为空、两在线臂 `defer_triggered=False`；同目录 `main3b_incremental_git_diff.patch:1-4` | 当前稿没有第三方外包语义；小接线试验两臂同用 defer 且不定价；阈值按本例均量 `k=2` 与双班次在开跑前冻结，并沿用既有 `run_dynamic_experiment.py`。P75 对其发表充分性的质疑另判，不倒写成 P74 未接线。 |
| 37 | P75 | 动态触发先查文献；不把演示阈值冒充正式阈值；区分手段与效应 | 存疑(待A级取证) | A | `docs/handoff/dynamic_replanning_literature_20260731/report.md:403-450`（B 级总述）；`/Users/zhouleixishu/Zotero/storage/2JBQSR8A/21级邱莹莹大论文.pdf` PDF p.59 原值 `q=500kg,T=30min`；`data/dynamic_streams/cn-jjj-50c-01-DEPOTSEARCH-d996f755bd_q500_t30_17ffb3f5d091/generation_rules.json:10` 仍写 500 kg 协议移植，`solver/reports/main3b_backend_20260816/metadata.json:19-33` 则写测试用 569.4 kg | 已直接核到邱论文唯一一处定量阈值，但没有逐篇打开报告所称的其余 33 篇原文，不能 A 级确认“34 篇仅一篇支持定量触发”。现有 500/569.4 分属流生成与小接线时代，尚缺正式协议定版；演示值没有冒充正式值。 |
| 38 | P76 | 先只测量 900 秒慢因；纯提速须逐位一致 | 已落实(A级) | A | `solver/reports/speed_diag_20260816/decomposition.csv:2-23`；同目录 `done.json:2-27`；`solver/reports/fix_d2_decoder_cache_20260817/raw_runs.csv:2-3`；`solver/reports/fix_decoder_dag_20260817/raw_runs.csv:2-6` | 测量先行且未改源码；热点量化到充电修复/时序链；后续 D2、DAG 前后 fingerprint、成本、服务量一致。 |
| 39 | P77 | MAIN-3b 首次小样本配对数据的历史登记 | 已落实(A级) | A | `solver/reports/main3b_backend_20260816_pre_cross_metric_fix/paired_results.csv:2`；同目录 `raw_runs.csv:2-4`；`solver/reports/main3b_backend_20260816/paired_results.csv:2` | P77 的 `4998.334867470886/-56.89089033838536` 与 pre-fix 原件逐值相符；当前目录已更正为 `4922.16156627131/+19.28241086119033`。P77 是真实历史快照，不能拿来当当前数字。 |
| 40 | P78 | 安全精确缓存优先；有证明下界才筛选；拒绝 top-k/事后调 k | 已覆盖(被P81/P87) | A | `pending_decisions.md:1259-1293,1357-1383,1479-1498`；`solver/reports/fix_d2_decoder_cache_20260817/raw_runs.csv:2-3`；`solver/reports/fix_cost_cache_20260817/raw_runs.csv:2-6` | 后续用户只授权了可证明等价的 D2 和最小 cache 修复，并用逐位一致验收；P78 的待批方案不再单独作为施工授权。 |
| 41 | P79 | 不预设预算；正式 10 seeds；算法定型后才正式跑/出图；废除 platform 叙事 | 存疑(待A级取证) | A | `solver/reports/time_carbon_3arms_20260817/metadata.json:3-9` 明示 technical；`solver/reports/fix_cost_cache_20260817/deep_summary.json:62` 明示 bounded acceptance；`docs/paper_gci_dmm_vrp_20260804/paper_main_foundation.md:289-291` 仍占位 | 当前可见包没有冒充正式实验，但“所有正式运行均 10 seeds、预算由曲线定”尚无正式包可验。缺算法定型后的 10-seed 元数据和预算冻结原件。 |
| 42 | P80 | 长/正式/交接跑落仓库；交接持久产物而非进程；旧丢失结果降级 | 已落实(A级) | A | `solver/reports/fix_cost_cache_20260817/deep_summary.json:2-18,62-63`；同目录 `raw_runs.csv:2-6`；`solver/reports/main3b_backend_20260816_pre_cross_metric_fix/` 仍保存 | P80 后的长验收完整落在仓库并有终态、服务量和恢复入口；旧版结果也以时代目录保存而非靠活进程。 |
| 43 | P81 | 近可行充电/时间窗候选进不可行池；不得冒充可行；批准 D2 等价提速 | 已落实(A级) | A | `solver/src/setp_solver/algorithms/problem_hgs/charging.py:685-793,844-852`；`solver/src/setp_solver/algorithms/problem_hgs/evaluation.py:473-612`；`solver/reports/grand_cleanup_20260817/private_200_lineage.jsonl:2-20`；`solver/reports/fix_d2_decoder_cache_20260817/raw_runs.csv:2-3` | 不可行候选带 violation 类型进入 `target_pool=infeasible`；D2 前后终态 fingerprint、成本、服务量逐值相同。 |
| 44 | P82 | 公开冻结自研件；私有全开消融；每包记录 active/sleeping | 未落实 | A | `solver/reports/grand_cleanup_20260817/public_PR11A_120/metadata.json:22-36`；`solver/reports/grand_cleanup_20260817/private_static_200/metadata.json:197-260`；`solver/reports/time_carbon_3arms_20260817/metadata.json:47-60`；`solver/reports/fullflow_smoke_20260817/segment_06_dynamic/metadata.json:1-180` | 公开、私有、时变碳三类已有正确记录；但 P82 明令“每个实验包”记录 active/sleeping，同日下午生成的动态包 180 行内没有该字段。缺动态等其余机制包的逐包清单，不能以三份样本冒充全量。 |
| 45 | P83 | 几轮无果换高维办法；查朴素逻辑与文献；见好夯实后收手 | 已落实(A级) | A | `solver/reports/decoder_structure_probe_20260817/raw_runs.csv:2-3`；`solver/reports/fix_decoder_dag_20260817/raw_runs.csv:2-6`；`solver/reports/fix_cost_cache_20260817/deep_summary.json:62-63` | 译码器从局部缓存问题转为 DAG 结构改写，800 圈 decode 约 840 秒降到 1.60 秒且语义一致；随后只做有界验收并收手。 |
| 46 | P84 | Claude/Codex 平级、双向主动；Claude 仅联络；每份 Codex 报告答下一步/原因 | 未落实 | A | `pending_decisions.md:1427-1448,1622-1632` | “再纠正”原文直接登记第 10–14 轮仍是单向派活，说明该要求当时连续未落实；本轮虽改成独立交叉审计，尚未完成双方对账，不能提前改判。 |
| 47 | P85 | 夜间非重大不打扰；重大问题收齐再等；有数学/物理证明可自主改算法结构 | 存疑(待A级取证) | A | `solver/reports/fix_decoder_dag_20260817/raw_runs.csv:2-6`；同目录 `source.diff:1-228`、`parity_100.json:1-30`、`parity_800.json:1-31` | DAG 个案满足“结构证据+逐位一致”；但夜间提问纪律和所有自主结构改动属于持续行为，单个个案不能证明全量。缺逐任务授权/升级账。 |
| 48 | P86 | Codex xhigh 起步、日常 max、高难 ultra；Claude/Codex 分工但平级 | 存疑(待A级取证) | A | 现场 r15 进程命令含 `gpt-5.6-sol`、`model_reasoning_effort=ultra`；`pending_decisions.md:1469-1478` | 只证明 r15 这一单用 ultra，不能证明算法阶段所有 Codex 会话均符合档位规则；缺会话启动原始清单。 |
| 49 | P87 | 只最小改 `cost.py` 根除 id 缓存泄漏；其他四冻结文件不动；五级验收 | 已落实(A级) | A | `solver/src/setp_solver/cost.py:46-50,139-152`；`solver/reports/fix_cost_cache_20260817/hashes_before_after.json:4-34`；同目录 `raw_runs.csv:2-6`、`deep_summary.json:2-46` | 唯一授权文件哈希改变；其余四个哈希不变；200/800 等价、1046 圈服务完整、缓存计数平台和内存峰值均有原始字段。 |
| 50 | P88 | 长跑只属正式实验；探索/修复用最短可判定测试并设判据/墙钟 | 已落实(A级) | A | `solver/reports/fullflow_smoke_20260817/metadata.json:1-66` 的 `hard_bounds`；`solver/reports/fix_cost_cache_20260817/deep_summary.json:62-63`；`solver/reports/time_carbon_3arms_20260817/metadata.json:3-9,27-45` | 三个包均自报技术/有界验收而非正式实验，并在失败条件满足时停止，没有用长跑救故事。 |
| 51 | P89 | 向母体/强手学源码；HGS 已有件不得自造；重复自建件换开源；先单例低预算全流程 | 未落实 | A | `solver/src/setp_solver/algorithms/problem_hgs/population.py:1-20,291-486`；`solver/reports/foundation_review_20260817/component_medical_records.csv:14`；`solver/reports/fullflow_smoke_20260817/decision.json:3-16` | 单例全流程普查已做；自建 population/兼容主体仍在，原始全流程有 3 段 BROKEN，替换工作未完成。 |
| 52 | P90 | 用 ROI 判断每件工作：效应回报/时间成本，开源自建只是手段 | 存疑(待A级取证) | B | `solver/reports/foundation_review_20260817/assembly_replacements.csv:1-11` 的 ROI 列；同目录 `report.md:1-220` | 有 ROI 表述和估算，但这类报告结论不能证明每个后续任务都先做了 ROI 取舍。缺任务级“预估损失—投入—结果”原始台账。 |
| 53 | P82 补充 | 休眠判据是“非必要”；时变碳三臂必须开多趟以维持解成立 | 已落实(A级) | A | `solver/reports/time_carbon_3arms_20260817/metadata.json:47-60` 原字段 `multi_trip=因解可行性必要而启用` | 多趟明确列在 active，不再按“不是被测机制”机械关闭；探针随后因另一结构闭包失败并诚实停机。 |
| 54 | P91 | 修法、探针、验收器、哨兵、脚手架也先查内核/开源/文献；查不到才自写并记范围 | 未落实 | A | `solver/reports/p31_boundary_weld_20260817/literature_note.md:1-13`（一例有记录）；`solver/reports/fix_d2_decoder_cache_20260817/metadata.json:1-45`、`solver/reports/fix_cost_cache_20260817/metadata.json:1-93` 未形成逐修法现成方案检索字段 | 个别修复有出处，但不是每个修法/装置都有检索范围和“适配还是自写”的 A 级记录；执行口径未普遍落地。 |
| 55 | P92 | 仓库真清理、管线捋清、根级一次审透；源头错则追全部下游 | 未落实 | A | `solver/reports/grand_cleanup_20260817/decision.json:1-20` 原字段 `CLEANUP_PARTIAL`；`solver/reports/foundation_review_20260817/interface_contracts.csv:2-15` | 已有管线/接口病历；清理原件自认只完成部分，隔离区真删和 Git 瘦身属于 r15 在途，不能提前计完成。 |
| 56 | P93 | 所有活跃算法件、实验载具和每个接口做高标准总审；能跑不算完成；优先组装开源 | 存疑(待A级取证) | B | `solver/reports/foundation_review_20260817/component_medical_records.csv:1-15`、同目录 `interface_contracts.csv:1-15`、`component_axis_scores.csv:1-16` | 三张总审表是报告型盘点，且多行 `unknown`；本轮没有逐一回开所有 evidence 指向的源码，因此不能用它们单独支撑“全部审完”。缺逐件 A 级复核签名/哈希。 |
| 57 | P94 | 砍防御性噪音与非必要代码；保留服务量、checker、可行性、逐位一致、哈希和诚实记账 | 未落实 | A | `solver/reports/foundation_review_20260817/component_medical_records.csv:5-15` 的多项“削/换”；当前对应源码仍存在；P95 删除/改写在 r15 在途 | 已列出应削/应换及保护边界；实际源码清退没有稳定完成态，不能把“列病历”当“已砍完”。 |
| 58 | P95 | 截断假完成链、隔离区真删、Git 非重写镜像瘦身；三件做完立即停 | 存疑(待A级取证) | A | 取证截止时 PID 6013 仍运行且 `solver/reports/round15_three_approved_20260817/report.md` 不存在；收尾文件系统原值：PID 已退出，`done.json` mtime=`2026-08-17 22:22:45 +0800`，`report.md`/`decision.json` mtime=`2026-08-17 22:23:57 +0800` | 截止后出现终态候选，但本轮按用户边界没有打开或采用 r15 在途产物判合规。缺下一轮对三件原始删除清单、旧/新 Git 大小、commit/hash 与停止信号的 A 级复开，不能由新报告自证。 |
| 59 | P96 | 全部要求清单式对账；公开不得输母体；实验/机制先能跑再跑快；两代理都查 | 未落实 | A | `solver/reports/fullflow_smoke_20260817/raw_runs.csv:2-14`；同目录 `decision.json:3-16`；`solver/reports/time_carbon_3arms_20260817/raw_runs.csv:2-5` | 本文件完成了 Codex 独立清单，但实体状态仍是公开 BROKEN、时变碳 BROKEN、混合车队 BROKEN；Claude 独立清单尚待双方比对，不能说 P96 完成。 |

## 二、编号冲突补记（不计入 59）

| 稳定别名 | 要求要点 | 判词 | 证据级别 | 证据与缺口 |
|---|---|---|:---:|---|
| P43@L56-ALG | 保留底座和完整评价器，成熟零件串行组合；Oracle 只作稀有裁判；私有 A0 起消融 | 已覆盖(被P89/P91) | A | `pending_decisions.md:56,1528-1559,1603-1621`。P89/P91 后来把“保留/自写哪些基础设施”的规则改成优先开源/文献并要求修法溯源；旧 P43 不能再单独支配施工。当前替换尚未完成，已在 P89/P91 行判未落实。 |

说明：`pending_decisions.md:56` 的旧登记表 P43 与 `:91` 起的新 P43 同号；新 P43 内 `:161`、`:169` 又有两个同名 P43-I。本报告不擅改项目编号，59 的分母仍按顶级登记槽；旧表 P43 作为影子条公开列出，避免静默漏掉。

## 三、P81–P96 原话中的未编号要求

这些是从条文中的用户原话提取、去掉纯提问后形成的细粒度清单；不计入 59。

| 口头项 | 要求 | 判词 | 级别 | 证据；缺什么 |
|---|---|---|:---:|---|
| O01 | 近可行候选要保留，不能全扔 | 已落实(A级) | A | `solver/reports/grand_cleanup_20260817/private_200_lineage.jsonl:2-20` 有不可行池留存；P81 源码见主表。 |
| O02 | 同意修 D2 重复计算，必须等价 | 已落实(A级) | A | `solver/reports/fix_d2_decoder_cache_20260817/raw_runs.csv:2-3` 前后逐字段一致，耗时下降。 |
| O03 | 不要把所有问题归成一个原因，要查分层病灶 | 已落实(A级) | A | `solver/reports/fullflow_smoke_20260817/raw_runs.csv:2-14` 同时暴露 import、初始化闭包、CLI 缺口三类独立故障。 |
| O04 | 公开侧冻结自研问题件 | 已落实(A级) | A | `solver/reports/grand_cleanup_20260817/public_PR11A_120/metadata.json:22-36` 私有件全部 false。 |
| O05 | 私有侧全开并做消融 | 已落实(A级) | A | `solver/reports/fullflow_smoke_20260817/raw_runs.csv:5-7` 有全开及两条关闭臂；`solver/reports/grand_cleanup_20260817/private_static_200/metadata.json:197-260` 有活动计数。 |
| O06 | 每个实验只让必要组件工作，并记录开/睡清单 | 未落实 | A | `solver/reports/time_carbon_3arms_20260817/metadata.json:47-60` 与 `solver/reports/grand_cleanup_20260817/public_PR11A_120/metadata.json:22-36` 做到；`solver/reports/fullflow_smoke_20260817/segment_06_dynamic/metadata.json:1-180` 没有 active/sleeping 字段。 |
| O07 | 有转机就夯实，随后收手，不陷执念 | 存疑(待A级取证) | A | `solver/reports/fix_decoder_dag_20260817/raw_runs.csv:2-6` 与 `solver/reports/fix_cost_cache_20260817/deep_summary.json:62-63` 证明 DAG 个案收口；缺覆盖所有后续任务的事件账。 |
| O08 | 几轮不成且非致命，就换更高维办法 | 已落实(A级) | A | `solver/reports/fix_decoder_dag_20260817/raw_runs.csv:4-6` 显示由局部补丁转 DAG 后的结构性改善。 |
| O09 | 严查低级/朴素逻辑，必要时查文献 | 已落实(A级) | A | `solver/reports/speed_diag_20260816/decomposition.csv:2-23` 与 `solver/reports/fix_decoder_dag_20260817/parity_100.json:1-30`、`parity_800.json:1-31`；不是只靠报告描述。 |
| O10 | Claude/Codex 都须主动探索、反驳、真实交流 | 未落实 | A | `pending_decisions.md:1622-1632` 直接登记连续五轮仍单向派活。 |
| O11 | 每份 Codex 报告回答接下来做什么、为什么 | 存疑(待A级取证) | B | 样本 `solver/reports/fix_decoder_dag_20260817/report.md:69-71`、`solver/reports/fullflow_smoke_20260817/report.md:104-110` 有该段；未逐份打开全部 Codex 报告，缺全量索引核验。 |
| O12 | Claude 只是联络员，不是 Codex 上级 | 未落实 | A | 同 `pending_decisions.md:1622-1632`；本轮对账完成前仍不能宣告纠偏完成。 |
| O13 | 非重要问题不打扰；重要问题收齐讲明再等 | 存疑(待A级取证) | C | 属持续交互行为，仓库没有完备原始提问账；不能凭印象判已做到。 |
| O14 | 算法结构改动必须有数学/物理证明且服务目标 | 已落实(A级) | A | `solver/reports/fix_decoder_dag_20260817/source.diff:1-228`、同目录 `parity_100.json:1-30`、`parity_800.json:1-31`、`raw_runs.csv:2-6` 构成当前结构改动闭环。 |
| O15 | 除真正需要用户决定外，其余工作自主推进 | 存疑(待A级取证) | C | 无可穷尽的授权/提问原始账；单个任务不能证明全量。 |
| O16 | 算法阶段 Codex xhigh 起步、日常 max、高难 ultra | 存疑(待A级取证) | A | 只核到 r15 为 ultra；缺所有算法会话启动记录。 |
| O17 | 正式实验才长跑；探索/修复用最短判定测试 | 已落实(A级) | A | `solver/reports/fix_cost_cache_20260817/deep_summary.json:62-63`、`solver/reports/time_carbon_3arms_20260817/metadata.json:3-9`、`solver/reports/fullflow_smoke_20260817/metadata.json:10-31` 均明确技术/有界身份。 |
| O18 | 把打平/胜过者当老师，学源码、架构和原始写法 | 未落实 | A | 已有学习报告，但 `solver/src/setp_solver/algorithms/problem_hgs/population.py:1-20,291-486` 仍保留自建主体，尚未完成迁移。 |
| O19 | 有开源/文献现成件就不自造，已有重复件要换掉 | 未落实 | A | `solver/reports/foundation_review_20260817/component_medical_records.csv:5-15` 仍列多项“换/削”，且 `solver/src/setp_solver/algorithms/problem_hgs/population.py:291-486` 等对应源码仍在。 |
| O20 | 先用单实例、最低预算跑通/查清完整流程，再谈大跑 | 已落实(A级) | A | `solver/reports/fullflow_smoke_20260817/raw_runs.csv:2-14` 覆盖七段并诚实保留三处失败；“跑通”在这里按先做全链普查而非伪称全 PASS。 |
| O21 | 效应是回报、时间是成本，用 ROI 判断工作 | 存疑(待A级取证) | B | `solver/reports/foundation_review_20260817/assembly_replacements.csv:1-11` 有 ROI 报告列；缺逐任务事前—事后原始账。 |
| O22 | 修 bug、探针、验收器也必须先查现成并记录出处 | 未落实 | A | `solver/reports/p31_boundary_weld_20260817/literature_note.md:1-13` 仅证明一例；`solver/reports/fix_d2_decoder_cache_20260817/metadata.json:1-45`、`solver/reports/fix_cost_cache_20260817/metadata.json:1-93` 没有统一检索字段。 |
| O23 | 仓库真清、管线捋清、根级审计一次做透 | 未落实 | A | `solver/reports/grand_cleanup_20260817/decision.json:1-20` 原字段 `CLEANUP_PARTIAL`；r15 仅在本轮截止后出现终态候选，尚未复核。 |
| O24 | 源头错就查所有下游，并点名半坏基础设施 | 存疑(待A级取证) | B | `solver/reports/foundation_review_20260817/interface_contracts.csv:2-20` 列了下游/接口但多列 `unknown`；它是报告型盘点，缺逐证据源复开。 |
| O25 | 每个算法件、实验件、传递接口都按高标准审，能跑不算 | 存疑(待A级取证) | B | `solver/reports/foundation_review_20260817/component_medical_records.csv:1-35`、同目录 `interface_contracts.csv:1-20`、`component_axis_scores.csv:1-35` 是导航，不足以 A 级证明“每个”都重查。 |
| O26 | 砍防御性/非必要代码，同时保留真实合同 | 未落实 | A | `solver/reports/foundation_review_20260817/component_medical_records.csv:5-35` 已区分“削/换/留”；相应稳定源码仍存在，清退未完成。 |
| O27 | P95 三件做完立刻收手 | 存疑(待A级取证) | A | 取证截止时 r15 仍运行；收尾时 PID 已退出且终态候选文件出现，但按隔离边界未复开其内容，尚不能核定“三件做完才停”。 |
| O28 | 公开不得输给自己的母体 | 未落实 | A | `solver/reports/fullflow_smoke_20260817/raw_runs.csv:2-4` 公开入口在比较前即 BROKEN，无成绩可证明不输。 |
| O29 | 实验和机制先能正常跑，再谈跑快 | 未落实 | A | `solver/reports/fullflow_smoke_20260817/raw_runs.csv:8-11` 时变碳、混合车队 BROKEN；`solver/reports/time_carbon_3arms_20260817/raw_runs.csv:3-5` 未跑。 |
| O30 | 全部要求逐条清单查，两代理都查，不能漏/跳步 | 未落实 | A | Codex 本清单已形成；Claude 清单尚未对账，59 项分歧清单尚未生成。 |

## 四、取证截止时的在途隔离范围（不作合规证据）

r15 取证截止快照：PID 6013，命令含 `gpt-5.6-sol` 与 `model_reasoning_effort=ultra`，当时仍运行。收尾时进程已退出、终态候选文件已出现；以下内容仍按本轮冻结边界不用于上表判定：

- `solver/scripts/experiment_acceptance.py`
- `solver/scripts/run_problem_hgs_private_technical.py`
- `solver/scripts/run_component_interaction.py`
- `solver/scripts/run_private_ablation.py`
- `solver/scripts/run_dynamic_experiment.py`
- `solver/scripts/run_mixed_fleet_experiment.py`
- `solver/scripts/run_public_v2_28_clean_ruler.py`
- `solver/tests/test_experiment_acceptance.py`
- `solver/tests/test_public_clean_ruler_worker_env.py`
- `solver/tests/test_mixed_fleet_experiment_harness.py`
- `solver/tests/test_component_interaction_harness.py`
- `solver/tests/test_private_ablation_harness.py`
- `solver/tests/test_dynamic_experiment.py`
- `solver/tests/test_main3b_protocol.py`
- `solver/reports/round15_three_approved_20260817/**`、`_quarantine_20260817/` 真删关联项、`.git/objects.round15.*`

## 五、计数

59 个登记槽（唯一主分母）：

- 已落实(A级)：16
- 未落实：22
- 存疑(待A级取证)：10
- 已覆盖(被Pxx)：11
- 合计：59

30 个未编号口头项（另算）：

- 已落实(A级)：10
- 未落实：11
- 存疑(待A级取证)：9
- 已覆盖(被Pxx)：0
- 合计：30

编号冲突影子条 `P43@L56-ALG` 不进入任一分母。

## 六、最可能被误诊的三条（新判词已先锁定）

| 条目 | 本轮独立判词 | 为什么最容易误诊 | 上一轮 Codex 判词 |
|---|---|---|---|
| P54 | 已落实(A级) | 权威 CSV 同时保留旧候选状态 `PENDING...` 和现行状态 `APPROVED...`；只看前者会漏掉运行时实际读取的批准列。 | 已跳步 |
| P62-A | 存疑(待A级取证) | “目录存在”和“报告称六族可用”都不等于稳定入口已逐族加载、旧 V2 已被排除；上一轮把 B 级/存在性证据抬成了完成。 | 已落实 |
| P77 | 已落实(A级) | pre-fix 原件与当前更正目录各自都是真的；不带时代标签会把历史登记误成假数据，或把旧值误当当前值。 | 部分落实 |

## 七、接下来该干什么（按 P84）

1. 等 Claude 的独立 59 项清单完成，只比对“编号—判词—证据时代”，先生成分歧表，不合并措辞。
2. 对每个分歧只回到双方共同认可的 A 级原件定案；优先先核 P54 的双状态列、P62-A 的稳定入口/旧 V2 排除、P77 的 pre-fix/当前时代链。
3. r15 已在本轮截止后出现终态候选；下一轮仅重审 P95 及明确受 14 个隔离文件影响的行，不借机重开其余 59 项，也不新增门禁、合同或审计器。
4. 实体主线先修公开入口、时变碳结构闭包、混合车队参数接口三处 BROKEN；三者能正常跑后，才进入 P47/P79 的收敛标定和正式多种子实验。

CROSS_AUDIT_CODEX_END
