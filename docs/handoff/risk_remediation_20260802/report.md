# X1 风险逐项处置方案

状态：`X1_RISK_REMEDIATION_PLAN_COMPLETE`

范围：四类共19条风险，A类12条、B类4条、C类1条、D类2条。本文只给原始证据与可执行处置选择；没有修改 `docs/paper_v2/paper_main.tex`、代码或 `baselines/` 结果目录，也没有启动实验。

## 结论

A类12处全部可用现有原始文件纠正，其中11处推荐“改措辞”，第983行的6.08 m²推荐用当前运行值4.6376 m²补正。B类中，SOC=0找到了同类中文论文中完全同形的配送中心充电前零电量建模约定；0.40元/kWh只能作为政策锚定的统一情景，0.85/0.45和NL90仍没有覆盖目标车型精确配置的标定原件，推荐明确降为情景设定。C类应把“当前BKS”改成“Vidal等（2013）发表参考值”。D类的原始MV最好目标值和实际秒数都已在正式包中，无需重跑，只需机械抽取与聚合。

## A 类：12处来源措辞

### A01 真实设施点位（第928行）

事实：`paper_main.tex:928` 写“车场与客户位置基于真实设施点位构建”。原始 `facilities.csv` 表头及第2行给出 `depot_point_semantics=SCENARIO_ROAD_ACCESS_POINT_NOT_OBSERVED_TRUCK_GATE`；`orders.csv` 表头及第2行显示客户有 `osm_type/osm_id` 和固定 `order_seed`，属于从公开POI池抽取的假设服务点。

处置选项：一是【改措辞】写成“车场采用命名物流设施的构造道路接入点；客户由公开OSM POI池按固定种子抽样为假设服务点”，来源为 `data/ChinaInstances/china81_stage2_static_inputs_corrected_v3_20260723/facilities.csv` 与 `data/ChinaInstances/china81_order_attributes_gis_v2_20260723/orders.csv`；二是【删除】删去“真实设施点位”总括，只在数据说明表保留身份、坐标与观测边界，依据 `provenance_ledger.json:P07-P09`。

推荐与代价：推荐改措辞。它保留可复核的设施/POI身份，又消除把公开坐标理解为企业业务观测的风险。代价：`只改文字`。

### A02 真实道路计算（第929行）

事实：`paper_main.tex:929` 写“真实道路计算”。原始 `data/ChinaInstances/china81_local_directed_matrices_corrected_v10_20260723/metadata.json:1-31` 登记 `router=OSRM 26.7.3 CH Route API`、`profiles=[cv,ev]`、`ordered_pairs=1578948`、`euclidean_or_symmetry_fallback=false`，且缓存语义是同一冻结OSRM graph/profile；没有轨迹或逐时拥堵观测。

处置选项：一是【改措辞】写成“在冻结OSM路网快照上用OSRM 26.7.3静态profile计算有向路由距离与时间”；二是【删除】只删除“真实”二字，保留OSM/OSRM技术描述。两项均由上述metadata字段和OSRM Route service文档定位，无PDF页码。

推荐与代价：推荐第一项，既准确又可复现。代价：`只改文字`。

### A03 订单生成规则失真（第931-934行）

事实：正文写需求三段、服务8/12/18 min、30 min网格窗；原始 `orders.csv` 实际含需求139/208/278/347/417 kg五档、服务6/9/12/15/18 min和连续分钟窗，`metadata.json:1-22` 登记 `sampling=complete empirical rows with replacement`、`order_rows=5805`。

处置选项：一是【改措辞】明确需求为五档容量占比构造，服务时长与连续交付窗从公开外部案例完整行有放回重采样并保留联合关系；二是【删除】删去失效的具体规则，正文仅保留“需求为构造代理、服务与交付窗为案例迁移”，详细字段移至数据附表。来源为 `orders.csv` 的数值与三类 `classification` 字段、同目录metadata的sampling字段。

推荐与代价：推荐第一项；现有字段足以准确陈述，不需重生成。代价：`只改文字`。

### A04 厢式货车官方数据总括（第936行）

事实：`paper_main.tex:936` 把两车统一称为国内在售厢式货车。`china81.py:638-685` 的CV是JAC K7厢式，EV是FOTON ES1快递版栏板。JAC官方网页快照 `docs/handoff/china_vehicle_parameter_sources_20260718/raw/jac_wling_k7_official_20260718.txt:1-21` 支持K7相应配置；福田官方《欧马可智蓝ES1单页》PDF p.12支持77.28 kWh栏板配置的质量/载重等字段，但不支持当前高度、0.85或0.45。

处置选项：一是【改措辞】逐车写准确上装，并把厂家字段与构造/迁移字段分开；二是【删除】删除整句厂家总括，由车型表逐字段标注“厂家/文献/情景”。

推荐与代价：推荐改措辞，保留真实存在的厂家证据且不整体抬高。代价：`只改文字`。

### A05 NL90被写成车型曲线（第938行）

事实：`paper_main.tex:938` 直接称电动车曲线；`charging_curve.py:76-82` 的实现确为断点 `(0,0.9,1.0)`、相对功率 `(1.0,0.5)`，但福田官方单页PDF p.12只给77.28 kWh配置的SOC20%-100%充电1 h，没有分段曲线。

处置选项：一是【改措辞】明确为“预设NL90情景”；Montoya等（2017）PDF pp.3-4只能支持非线性/分段建模，不能支持当前精确断点与倍率。二是【补出处】只有取得ES1 77.28 kWh同配置实测曲线并逐段复现0.9/0.5才恢复车型曲线说法；Schücking等（2017）作者稿PDF p.14的约90%案例来自Nissan Leaf，不能迁移为ES1标定。

推荐与代价：推荐改措辞；规则可回放但不可写成实测。代价：`只改文字`。

### A06 EV迎风面积6.08与运行值冲突（第983行）

事实：`paper_main.tex:983` 列CV 4.64、EV 6.08 m²；`china81.py:644,666-673,887` 对两车均使用 `0.85×2.2×2.48=4.6376` m²，且注释说明EV高度2.480 m是从CV迁移的构造值。

处置选项：一是【补数据】把EV表值补正为4.64 m²并给出公式及高度迁移边界；二是【删除】删去车型表的迎风面积行，改在情景参数表列统一值与构造性质。

推荐与代价：推荐补数据。运行真值已经存在，纠正表格不触发重跑。代价：`只改文字`。

### A07 表注混合四种证据等级（第991行）

事实：`paper_main.tex:991` 把空气阻力、投影因子和能耗系数统一称为公开情景代理与文献迁移；`china81.py:653-657,680-685` 及 `docs/handoff/ledger_input_provenance_01_20260728/report.md:69-93` 显示滚阻/能耗有Goeke/Demir映射，0.85与0.45没有原件映射，EV高度为构造迁移。

处置选项：一是【改措辞】拆成厂家规格、文献迁移、EV高度构造迁移、0.85/0.45未标定情景四层；二是【删除】删除总括表注，在每个参数行旁标来源类别。Goeke与Schneider（2015）PDF p.11 Table 4可支持其自身能耗参数，但其A=3.912、Cd=0.7不应迁移成当前车型标定。

推荐与代价：推荐改措辞，既保留已有文献来源，又准确降级两个无源值。代价：`只改文字`。

### A08 “现实数据与相关文献”覆盖过宽（第994行）

事实：`paper_main.tex:994-1036` 同时包含官方发布值、文献迁移、公开报价代理和未观测统一情景；`provenance_ledger.json:P13-P27` 给出的来源等级并不相同。

处置选项：一是【改措辞】以“官方发布值、文献迁移值、构造情景值”三组引出；二是【删除】删掉总括句，让各参数段自行说明来源类别。

推荐与代价：推荐改措辞，三组结构清楚且不损失信息。代价：`只改文字`。

### A09 重庆柴油价并非同日地方直录（第995-996行）

事实：正文把九城都写成2025-02-12地方发改部门公布值；原始 `baselines/china_e3_e7/pre_e3_full_chain_audit_20260723/diesel_price_2025_02_12_source_register.csv:1-10` 的重庆行明确为 `DERIVED_FROM_OFFICIAL_NDRC_PER_TON_AND_OFFICIAL_LOCAL_ADJACENT_RETAIL_TABLES`。

处置选项：一是【改措辞】写成八城使用官方区域零售表，重庆7.50元/L由国家每吨调价与重庆相邻日期官方表推导为情景值；二是【补出处】重新检索重庆市2025-02-12有效原表，只有直接表核对7.50后才恢复统一“地方公布”说法。

推荐与代价：推荐改措辞；已封存推导链可回放，额外历史检索对数值结论没有增量。代价：`只改文字`。

### A10 60/22 kW缺少情景边界（第1036行）

事实：`facilities.csv` 将公共站60 kW/1枪标为 `UNIFORM_PREDECLARED_SCENARIO_PROXY`，车场22 kW/2枪标为 `UNIFORM_PLANNED_CAPACITY_SCENARIO_PROXY`；`station_observed_boundary` 明示OSM只支持位置/标签身份。

处置选项：一是【改措辞】写成所有公共站统一预设60 kW/1枪、所有车场统一预设22 kW/2枪，均非命名设备观测；二是【补出处】逐站取得运营商价目/铭牌和逐车场合同，按设施重新登记，值有变化时重算依赖充电时长的结果。

推荐与代价：推荐改措辞；统一容量本来就是当前算例定义。代价：`只改文字`。

### A11 三条核心电网与运行映射不符（第1040-1042行）

事实：正文称京津冀、珠三角、成渝分别使用北京、广东、重庆三列；`china81.py:70-125` 和运行日历实际绑定Beijing、Tianjin、Hebei、Guangdong、Sichuan、Chongqing六列。

处置选项：一是【改措辞】逐城列六列映射，说明珠三角四城共享广东列；二是【删除】删去“三个核心电网”的解释，仅在参数表列实际绑定。

推荐与代价：推荐改措辞；运行映射已明确，不需重算。代价：`只改文字`。

### A12 “81个自有算例”歧义（第1545行）

事实：`paper_main.tex:1545` 写“中国81个自有算例”；虽然第923-927行已说由本文构建，但结语没有再次限定仿真性质。订单metadata登记 `instances=81` 和重采样规则。

处置选项：一是【改措辞】改成“本文构建的中国三大城市群81个仿真算例”；二是【删除】删去“自有”，写“公开标准算例与China81仿真算例”。

推荐与代价：推荐第一项，信息最完整。代价：`只改文字`。

## B 类：4个无源参数的真实检索结果

### 检索覆盖与证据边界

| 方向 | 已核定来源 | 页码/条款 | 能支持什么 | 不能支持什么 |
|---|---|---|---|---|
| 国家价格文件 | 国家发改委《发改价格〔2014〕1668号》 | PDF p.2，第2条 | 服务费原为地方上限，之后逐步放开、通过市场竞争形成 | 九城公共货运站统一0.40 |
| 地方收费文件 | 天津《津发改工业〔2023〕56号》；中山《中发改价管〔2021〕178号》；深圳市政府价格答复 | 天津HTML“保障措施”第3项；中山第1-2条；深圳答复正文，均无页码 | 0.40在天津特定居民小区项目是上限；广东/深圳实行市场调节价 | 把0.40写成九城、所有公共站、实验日期的观测价 |
| 国家车辆标准 | `GB/T 27840-2021`及其公开征求意见稿 | 稿PDF p.II、p.2 §5.2、pp.5-6 §6.2.4-6.3 | 重型商用车行驶阻力应来自滑行试验或推荐阻力系数 | 当前两车型0.85投影因子与Cd=0.45的配置级标定 |
| 厂家文件 | 江淮威铃K7官方页；福田欧马可智蓝ES1官方单页 | JAC快照1-21；福田PDF p.12 | 指定配置的尺寸、质量、载重；ES1 77.28 kWh和SOC20%-100%约1 h | 0.85、Cd=0.45及SOC-功率曲线 |
| 同类/目标期刊文献 | 黄志红等（2024）《中国管理科学》 | 期刊p.70，式(15)-(16) | 配送中心充电决策前电量为0的建模约定 | 目标企业班前SOC实测 |
| 非线性充电文献 | Montoya等（2017）；Schücking等（2017） | Montoya PDF pp.3-4；Schücking作者稿PDF p.14 | 非线性/分段曲线方法；另一车型约90%案例 | ES1的0.9断点和0.5倍率 |

### B01 公共充电服务费0.40元/kWh

事实：`tariff_carbon_48slot_calendar.csv` 表头及第2行把服务费固定为0.4，并明确标成 `UNIFORM_SCENARIO_PROXY_NOT_MARKET_OBSERVATION`；正文第1029-1030行只称叠加运营商服务费，没有给0.40的来源。

处置选项：一是【改措辞】保留0.40，但明确为九城统一政策锚定情景。国家《发改价格〔2014〕1668号》PDF p.2第2条、天津《津发改工业〔2023〕56号》特定项目上限、中山和深圳市场调节价规则共同说明其可作情景，但不能作九城观测。二是【补出处】按冻结日期逐一保存 `facilities.csv` 中九城命名公共站的运营商价目/支付页，只有逐站一致才升级为观测；否则按站重算成本。

推荐与代价：推荐改措辞。现有权威材料足以解释情景范围，却明确不能证明统一观测；降级不改变封存数值。代价：`只改文字`。

### B02 迎风面积投影因子0.85与风阻系数0.45

事实：`china81.py:638-685,885-887` 对CV和EV统一使用 `A=0.85×2.2×2.48=4.6376` 和 `Cd=0.45`；两个内部source_id均无原件映射，EV高度还在代码中明确为构造迁移。JAC官方页与福田PDF p.12均不含0.85/Cd字段。

处置选项：一是【改措辞】把两值分别写成未按目标配置标定的统一气动情景，给出公式、两车型共享值和EV高度迁移。`GB/T 27840-2021`的公开稿p.2 §5.2、pp.5-6 §6.2.4-6.3规定以滑行试验或推荐行驶阻力系数确定阻力，并不为目标车型给出这两个值。二是【补出处】向厂家或型式/滑行试验资料检索K7厢式与ES1栏板的配置级道路阻力或CdA，必须逐车覆盖并回放精确数值。三是【删除】删除当前两主值，改用配置级道路阻力/能耗率重建能耗层并重跑；已被2021版全部代替的2011版公式不能冒充当前标定。

推荐与代价：推荐改措辞。国家标准、厂家文件和同类文献均已检索，仍没有精确原件；把值诚实限定为统一情景的代价远低于重建能耗层，也不会把Goeke等其他车型的参数误写成实测。代价：`只改文字`。

### B03 EV初始SOC=0

事实：`china81.py:891-895` 设 `initial_ev_battery_kwh=0.0`，仓库没有目标企业班前SOC观测。黄志红等（2024）在《中国管理科学》期刊p.70式(15)-(16)明确令车辆到达配送中心的电量为0、离开电量等于中心充入量，提供了完全同形的建模约定。

处置选项：一是【补出处】引用黄志红等p.70，将0解释成“配送中心出发前充电决策的模型初态”，不写成企业实测。二是【改措辞】若不引用该约定，则称“零初始能量压力情景”，并与Montoya PDF p.4、Keskin与Çatay作者稿p.3的常见满电离场约定区分。三是【删除】改为满电离场并重新求解全部依赖车场充电的结果。

推荐与代价：推荐补出处。同类中文物流EV论文可直接支撑模型语义；只需准确限定，不需重跑。代价：`只改文字`。

### B04 NL90分段充电曲线

事实：`charging_curve.py:76-82` 的精确规则是断点0/0.9/1.0和相对功率1.0/0.5；福田官方PDF p.12只给77.28 kWh配置的SOC20%-100%充电1 h。Montoya PDF pp.3-4的数据来自另一电池/充电站，Schücking作者稿p.14是Nissan Leaf，均不能标定ES1。

处置选项：一是【改措辞】保留并明确称“NL90预设非线性情景”，外部文献只支撑方法，不支撑精确参数。二是【补出处】取得同一ES1配置、明确功率和温度条件下的SOC-时间/功率曲线并重新拟合；若不是0.9/0.5，重跑E5及依赖充电时长的结果。三是【删除】删除精确车型曲线主张；若删除NL90结果，还应同步删除第1489-1509行对应实验叙述。

推荐与代价：推荐改措辞。当前文献与厂家页都不能闭合车型标定，跨车型迁移的审稿风险高于把它诚实写成预设情景。代价：`只改文字`。

## C 类：公开算例参考值标签

### C01 “当前BKS”失实（第1111行）

事实：`paper_main.tex:1111` 称当前逐题BKS；正式 `decision.json.table5[*].bks` 使用固定参考列，`baselines/algorithm_prototypes/boundary_probe_20260726/NEW_BKS_TABLE.csv` 的表头明确叫 `bks_2013`，且18行给出低于该列、`certificate=PASS`的仓库内候选。因此这不是已核验的当前共同体BKS。

处置选项：一是【改措辞】将正文、表头、表注统一改成“Vidal等（2013）发表参考值/Ref.(2013)”，误差明确相对固定参考值，PR17B只称达到2013参考值；依据Vidal等（2013）作者稿PDF p.23 Table 8及`bks_2013`字段。二是【补出处】检索作者维护页或公开注册表，保存访问日期并逐题核对28个值；不匹配时必须重算误差，仓库内候选不能自动升级为共同体BKS。三是【删除】删除“当前”和“最好解”标签，仅写“2013参考目标”。

推荐与代价：推荐改措辞。它与现有分母完全一致，不需重算；保留“当前”会被仓库内18个更低认证候选直接反驳。代价：`只改文字`。

## D 类：公开算例表的必要字段

### D01 逐实例MV原始最好目标值

事实：`paper_main.tex:1130-1165` 只列相对参考值的Best/avg百分比；`p1_formal_gate/decision.json.table5[*].hybrid_best` 已保存28题原始值，例如PR11A=6672.748、PR17B=4771.155，`raw_runs.csv.hybrid_cost`可独立按实例取最小值核对。

处置选项：一是【补数据】在正文表加入MV原始Best列，从decision的`hybrid_best`抽取并用raw_runs的`min(hybrid_cost)`交叉校验。二是【补数据】保留正文宽表，在补充材料建立instance、2013参考值、MV原始Best、gap逐题表并交叉引用。三是【删除】若无法提供原值，则删除正文逐实例gap宽表，只保留集合级汇总，把完整逐题数据作为补充材料。Vidal 2013 PDF pp.20,23、Lei 2026 PDF p.39、Schneider 2014 PDF pp.13-16、Goeke 2015 PDF p.15、Zhao 2024 PDF p.10均把原始目标与gap/BKS并列。

推荐与代价：推荐第一项。数据已在正式包中，同一行呈现最便于复算gap，审稿风险最低。代价：`重算已有数据`。

### D02 逐实例或汇总运行时间

事实：`paper_main.tex:1106-1109,1130-1165` 只有时间比1.47-2.00，没有实际秒数。`p1_formal_gate/raw_runs.csv` 共280个数据行，每行保存 `mother_cpu_seconds` 与 `hybrid_cpu_seconds`。只读聚合结果为母体均值231.943327 s、范围77.132099-240.520478 s，MV均值433.776769 s、范围115.820906-482.222701 s。

处置选项：一是【补数据】按instance对10种子分别取母体和MV平均秒数，加入逐题表，表注定义处理器秒并给全体均值/范围。二是【补数据】版面受限时只补集合级上述均值/范围，保留1.47-2.00逐题均值比范围。三是【删除】删除时间比和逐实例性能表，只保留目标质量汇总。Vidal 2013 PDF pp.20,23、Lei 2026 PDF p.39、Schneider 2014 PDF pp.13-16、Goeke 2015 PDF p.15、Zhao 2024 PDF pp.9-10均报告实际时间。

推荐与代价：推荐第一项。280行时间数据已齐全，按实例聚合无需重跑，信息量显著高于单一时间比。代价：`重算已有数据`。

## 外部出处清单

1. 国家发展改革委：《国家发展改革委关于电动汽车用电价格政策有关问题的通知》，发改价格〔2014〕1668号，PDF p.2，第2条。<https://zfxxgk.ndrc.gov.cn/upload/images/202210/20221041741876.pdf>
2. 天津市发展改革委：《2023年民心工程居民小区公共充电桩建设实施方案》，津发改工业〔2023〕56号，HTML“保障措施”第3项，无页码。<https://fzgg.tj.gov.cn/zwgk_47325/zcfg_47338/zcwjx/fgwj/202303/t20230302_6126439.html>
3. 中山市发展改革局：《关于电动汽车充电服务费实行市场调节价的通知》，中发改价管〔2021〕178号，第1-2条，HTML无页码。<https://www.zs.gov.cn/zsfgj/gkmlpt/content/1/1932/post_1932582.html>
4. 深圳市政府价格答复：电动汽车充电电价和服务费实行市场调节价，答复正文，HTML无页码。<https://www.sz.gov.cn/hdjlpt/detail?pid=3111028>
5. 国家市场监督管理总局、国家标准化管理委员会：`GB/T 27840-2021 重型商用车辆燃料消耗量测量方法`，现行标准状态页。<https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=D91422B6B4CB611CE115EF416AA92047>
6. 中国汽车技术研究中心：GB/T 27840修订征求意见稿，PDF p.II、p.2 §5.2、pp.5-6 §6.2.4-6.3。<https://www.catarc.org.cn/upload/201908/20/201908201530245058.pdf>
7. 北汽福田汽车股份有限公司：《欧马可智蓝ES1单页》，快递版77.28 kWh配置见PDF p.12。<https://aumark.foton.com.cn/profile/upload/2025/08/08/%E6%AC%A7%E9%A9%AC%E5%8F%AF%E6%99%BA%E8%93%9DES1%E5%8D%95%E9%A1%B5-NEW_20250808124334A003.pdf>
8. 黄志红、黄卫来、郭放（2024）：《考虑电池损耗的电动物流汽车充电设施选址与充电策略协同优化研究》，《中国管理科学》32(6):68-78，期刊p.70式(15)-(16)，DOI `10.16381/j.cnki.issn1003-207x.2021.1636`。<https://www.zgglkx.com/CN/article/downloadArticleFile.do?attachType=PDF&id=19208>
9. Montoya A, Guéret C, Mendoza J E, Villegas J G (2017). The electric vehicle routing problem with nonlinear charging function. *Transportation Research Part B*, 103:87-110, PDF pp.3-4, DOI `10.1016/j.trb.2017.02.004`.
10. Schücking M et al. (2017). Charging strategies for economic operations of electric vehicles in commercial applications. *Transportation Research Part D*, 51:173-189, author preprint PDF p.14, DOI `10.1016/j.trd.2016.11.032`.
11. Vidal T et al. (2013). A hybrid genetic algorithm with adaptive diversity management for a large class of vehicle routing problems with time-windows. *Computers & Operations Research*, 40:475-489, author PDF pp.20,23, DOI `10.1016/j.cor.2012.07.018`.
12. Lei Z, Hao J K (2026). A GPU-accelerated hybrid method for a class of multi-depot vehicle routing problems, arXiv:2605.05208, PDF p.39.
13. Schneider M, Stenger A, Goeke D (2014). The electric vehicle-routing problem with time windows and recharging stations. *Transportation Science*, PDF pp.13-16, DOI `10.1287/trsc.2013.0490`.
14. Goeke D, Schneider M (2015). Routing a mixed fleet of electric and conventional vehicles. *European Journal of Operational Research*, 245:81-99, PDF pp.11,15, DOI `10.1016/j.ejor.2015.01.049`.
15. Zhao et al. (2024). HGS with dynamic-programming split comparator, *European Journal of Operational Research*, PDF pp.9-10, DOI `10.1016/j.ejor.2024.04.011`.

完整机器可读内容见 `risks.json`；每条均含 `id`、`class`、原始事实、定位、至少两项处置选择、推荐与代价档。
