---
name: figure-redesign-task
description: ReSETP 图表重设计任务：诊断结论 + 方法论(Zotero范本/写死规范/Codex只填数) + 工作方式feedback
metadata: 
  node_type: memory
  type: project
  originSessionId: b15f032d-1e9c-453d-9aec-ea78a95aeb3f
---

**任务(PPO训练并行窗口启动)**: 把论文图表从"工程草稿/机器字段表"重做到顶刊级。user判定现有图表"可进垃圾桶"——看不出直观内容、像给机器看的字段表、有显示错误和审美问题, 和同级顶刊成品差距明显。

**方法论(user定调, 关键)**:
- 从 **Zotero 库**里直接相关的好期刊好文章(绿色VRP/EVRP/碳/ALNS/公平/动态VRP)找实验图表当**范本**, 模仿其设计 = 比自己设计稳当。不局限SETP期刊。
- 规范要**像素级写死**, 绝不给Codex自主设计的机会(Codex无审美/设计能力), Codex只负责**填数据+跑图**。
- **Claude自身审美也不全可靠**, 故尽量复刻成熟范本的形式/字段, 而非凭空设计。
- 提取范本的**通用设计形式/惯例**(图型/布局/配色/轴标注/字段组织/标题写法)用到自己数据上=学术惯例(约定俗成,非抄袭,无版权问题); 不搬范本的具体数据/文字/原图内容。

**工作方式feedback(user铁律, 所有任务通用)**: 任务开始前先**理解+确认+不懂随时问**, 再执行; 不在没理解清楚时动手。见 [[feedback-communication-style]]。

**图表诊断结论(Claude已看全7图, 2026-06-16)**: 基本全要重做。
- 🔴 **F4「48槽碳强度与充电负荷」=废图(空图)**: 左图γ曲线+两种充电负荷柱全没渲染(只剩灰色作业窗竖条), 右图峰/平/谷占比整个空白。最严重显示故障。
- 🟠 **F3「两层减碳瀑布」=假瀑布**: 名瀑布实为两根近等高柱, -1.5%差异看不出(把贡献画没了)。
- 🟠 **F5「碳敏感热力图」=假热力图**: 行(配额档)每行数值完全相同(配额维度无信息), 应改1D折线(碳价vs总碳)。
- 🟡 **F2** 八线一团+灰影糊; **F1路线图** 几十线交叉配色杂; **F6** 太空(5点近平线)。
- **通病**: 标题全带内部编号(F3/F5/F5b/F6)必须去; matplotlib默认草稿感; 相对最好=F5b(双轴+误差棒+阶梯响应)但也有编号+横轴42/50重叠。

**当前卡点**: Zotero连不上(Connection refused, local mode需开Zotero桌面应用); 语义搜索没装包(zotero_semantic_search不可用, 改用 zotero_search_items/advanced_search 关键词检索)。读范本图流程: 搜到item→zotero_get_attachment_path拿PDF路径→Read PDF页(能看图)或 zotero_read_pdf_pages。**等user开Zotero或给指定范本论文**, 再逐图写死像素级规范。

**窗口约束**: PPO训练中占满算力(40%/9h, 还要数小时), 此并行窗口只做不抢算力的 A(图表诊断+设计规范)/B(文本逻辑审查§1/2/4+§3提纲)/C(占位数字清单)/E(报告→表图映射), **不跑实验、不实际画图**(数字占位+先不跑, 等PPO完+数字定稿+算力再让Codex按规范重画)。D(可复现性声明)本窗口不做。要算力的F(加基线)/G(鲁棒性)等PPO快结束再上。

---

**范本论文清单+优先级(user提供, 2026-06-16; 现在只记不做, credits不够)**:
图表呈现风格模仿范本(对期刊+导师口味, 最高优先级, 均SETP):
1. **《双碳背景下复杂冷链物流模型及求解算法》**(师姐论文, **SETP封面论文**) = 呈现风格最高标杆, 最对导师+期刊口味。
2. **《碳交易机制下多中心混合车队配送路径和速度优化研究》**(SETP) = **图表主模仿对象**。
建模+实验素材(图型亦可参考):
3. 低碳视角下油电混合车队配送路径优化研究
4. Collaborative multidepot electric vehicle routing problem with time windows and shared charging stations
5. Routing a mixed fleet of electric and conventional vehicles under regulations of carbon emissions
6. The multi-depot vehicle routing problem with profit fairness (收益公平)
7. The bi-objective mixed-fleet vehicle routing problem under decentralized collaboration and time-of-use prices
**不局限这7篇**: 覆盖不全, 还要读Zotero其他相关论文补缺。user大量建模取材自这些。

**做什么**: 论文全部图(F1-F6/F5b)+表(T1-T9)的顶刊级重设计规范。
**怎么做(执行流程, 待credits+Zotero开)**: ①开Zotero→关键词/作者搜这7篇拿item key; ②读PDF看图(zotero_get_attachment_path→Read PDF页, 或zotero_read_pdf_pages), 重点扒两篇SETP(封面冷链+碳交易多中心)的全部实验图表呈现 + 英文篇对应图型; ③为我们每个图/表匹配范本模板(哪篇哪张作模板); ④写死像素级规范(图型/布局/配色/字体/轴标注/图例/标题写法/字段组织), Codex只填数据跑图不设计; ⑤Zotero其他相关论文补缺口。
**为什么**: 现有图表像工程草稿(F4废图/F3假瀑布/F5假热力图), 与SETP顶刊成品差距大, 审稿第一印象垮; 复刻成熟SETP范本(尤其封面篇+主模仿篇)最稳、最对期刊+导师口味, 比Claude/Codex凭空设计可靠。
**何时**: **user credits不够, 现在不做, 仅登记。等credits恢复+Zotero开桌面应用再执行。**

---

**🖼️ 任务升级=壳复印工程(user 2026-06-17重定义, 取代"模仿风格")**:
核心规则: **不是模仿风格, 是复印参考图表外壳**。分工=灵魂(证明什么/保留什么结论/投什么风格)由user定; 躯体(图表外壳/表头结构/面板布局/线柱点图例注释)由参考文献定; 血肉(所有数值字段)来自ReSETP的CSV/JSON; 执行者Codex只复印壳+填数据; **禁止项: Claude和Codex都不自由设计/不擅自美化/不改图型/不换图表逻辑**。一句话: 用户定灵魂, 参考文献定躯体, ReSETP数据填血肉, Codex只复印灌数。
**四阶段**: ①建壳库(每张ReSETP图表先绑定参考论文图表, 没绑壳不许画) ②提取壳(每壳记: reference_id/来源论文页码/图表类型/面板结构/轴含义/视觉元素/图例位置/颜色灰度/线型点型/表格结构/可本地化项/禁止改动项) ③ReSETP数据适配矩阵(target_id/reference_shell/resetp_source/required_reference_slots/available_resetp_fields/mapping_status=PASS或HALT/missing_fields/allowed_localization/forbidden_changes; 数据放不进壳必须HALT, 不许Codex改壳) ④锁壳+锁字段后才写Codex施工提示词(复印哪张壳/截图在哪/每面板每线每列每表头来自哪个ReSETP字段/哪可替换文字/哪禁止变动/哪缺数据必须停)。
**参考壳映射表v1(user给的初始绑定, 待Zotero读图锁定)**: T3算法对比表→陈婉茹2023表5(三线表:算例+n/d+参考最优+每算法小列); F2收敛图→陈婉茹2023图2(简单收敛线, 不改复杂); F1路线图→陈婉茹2023图3(节点分布+路线方案双面板); T4主解分解→陈婉茹2023表9或同类动力配置表(待锁); T5消融表→陈婉茹2023表8(最优/均值/std/相对变化); T6两层碳表→冷链封面同类结果表(待锁); F3两层碳图→**必须先找壳否则不画**; F4充电时段图→Shi2025 Fig2/5/7(分时电价/充电占比壳); T7碳敏感表→陈婉茹2023表10(碳价行/配额列组); F5碳政策图→陈婉茹2023图4/5(不默认热力图除非壳就是); F5b碳价压力→Qiu2024 Fig5/6/8或陈婉茹图4/5(先锁壳); T8公平表→Soriano2023公平结果表(待锁); F6公平前沿→Soriano2023 Fig6(横轴公平/纵轴成本比/散点连线); T9动态滚动表→**无壳=NEEDS_REFERENCE_SHELL**(继续找动态/滚动调度参考表, 没壳不画)。范本7篇见上方清单, 冷链封面篇(陈婉茹2023)=风格标杆覆盖最多。
**停止条件(必停不许自己想办法)**: 没参考壳/壳与ReSETP数据结构不匹配/字段不存在/数据源混用不同实验目录/PPO未定稿却要写T3-F2/Codex需自判颜色线型布局/为好看改结论重心/user没批准壳与字段映射。
**执行顺序**: 1.等PPO跑完(不频繁探测) 2.同步做壳库(只读Zotero+当前论文图表, 不改文件) 3.对7篇逐张提壳, 先覆盖最明确的T3/F2/F1/T5/T7/F6 4.找不到壳的列NEEDS_REFERENCE_SHELL不硬画 5.建数据适配矩阵(查单一数据源) 6.每张图"壳+字段+禁改项"交user审核 7.批准后才写Codex提示词 8.Codex只生成草稿包不替换正式图 9.草稿user审后才进正式目录 10.PPO+大重跑定稿后才替换T3/F2等算法相关数字。
**当前下一步=生成"参考图表壳目录v1"**(回答四问: 每张图复印哪篇哪张/外壳固定结构/ReSETP数据能否填进去/不能是缺数据还是缺壳)。**credits有限→分批做, 从冷链封面篇优先(覆盖T3/F2/F1/T5/T7最多)**。任务名: PPO长跑期间的论文图表壳复印与数据适配计划。

**📐 壳目录v1进展(2026-06-17, 已读封面篇全文)**:
- 范本key已确认: 冷链封面篇(陈雨蝶等2025"双碳背景下复杂冷链物流模型及求解算法")=**6KCQCP66**, PDF本地路径 `/Users/zhouleixishu/Zotero/storage/AYDB6KXP/陈雨蝶 等 _ 2025 _ 双碳背景下复杂冷链物流模型及求解算法.pdf`(24页, 无outline); 同作者2023联合配送篇=N9NVJ4FH; 公平篇Soriano2023=IF3WEZZJ。作者是**陈雨蝶**(非陈婉茹)。
- **user映射表编号多处记错, 已按封面篇实际内容修正**(教训: 以实际图表为准): T3→表5(三线表,对✓); T5→表8(决策目标对比,对✓); **F2收敛→图4**(非图2,图2是移民示意); **F1路线→图5**(非图3,图3是时变路网速度图像; 图5是a独立b分区c联合三面板路线); **T7碳敏感→表7**(非表10; 表10是速度函数对比; 表7=碳价×配额×碳排×碳成本×总成本×占比); T4主解分解→表9(配送模式对比)或表4(路径明细)待定。
- **表壳可从文本直接提取(已读到结构)**: 表5(T3三线表:instances|Q|BKS|各算法Best./avg.|末行Avg); 表8(T5消融:列=距离/F-F1/F-F6/F本文,行=13项指标); 表7(T7碳敏感:碳价分组×配额行); 表9(配送模式:独立/分区/联合+变化%); 表10(速度函数S/R对比); 表2(算例节点:编号/XY/时间窗/三产品需求); 表4(路径明细:路径/距离/成本/时间/油耗/碳/num/装载率)。
- **图壳已看图提取(2026-06-17)**: **F2收敛←图4**(单面板折线; 横轴=运行时间/min, 纵轴=目标值总成本; 仅3条线不同线型+颜色平滑下降; 图例在图内; caption在图下居中。复印=砍到3-4条关键算法+单面板+去灰影; 封面篇图4无箱线分布,F2终值分布部分无壳待另找)。**F1路线←图5**(三子面板横排a/b/c; 每面板=客户节点小点+配送中心突出标记+车辆路线连线配色区分; (a)(b)(c)标各子图下。复印=统一节点标记+配送中心突出+克制配色+多面板; 我们F1是节点分布|路线方案双面板,套其节点/配色规范)。图1流程图/图3时变路网/图6速度函数=我们暂不直接对应(我们无速度图,有时变碳强度)。
- **看图方法(重要,内置Read读PDF失败)**: 内置Read找不到poppler(PATH不含/opt/homebrew/bin)。正确法: Bash `/opt/homebrew/bin/pdftoppm -png -r 150 -f <页> -l <页> "PDF路径" /tmp/setp_shells/<前缀>` 转PNG, 再Read那个PNG。poppler已装(brew)。封面篇PDF=/Users/zhouleixishu/Zotero/storage/AYDB6KXP/...pdf。
- **封面篇壳目录v1=完成✅**(覆盖T3表5/T5表8/T7表7表壳 + F2图4/F1图5图壳)。

**Soriano2023壳=完成✅(IF3WEZZJ, 13页, PDF=/Users/zhouleixishu/Zotero/storage/PLSR8GG4/...pdf)**:
- 图表定位: Fig6公平前沿在p10, Fig5前沿+利润演化p10, Fig2前沿解类型示意p5, Table4公平对比表p9。
- **F6公平前沿←Fig6**: 双目标帕累托前沿散点图; 横轴=Fairness Objective公平度量, 纵轴=Cost Objective成本; 散点=不同方案解, 图例区分两公平口径(horizon vs daily, 对我们=不同公平阈值或公平开关); 多面板按实例(C8/U8)。复印=横轴公平/纵轴成本帕累托散点。**数据适配风险(HALT检查)**: 我们F6现仅3可行点构不成饱满前沿→需多跑公平阈值点 或 简化单面板; 现有"θ vs成本+不可行红叉"风格要改成前沿散点。
- **T8公平表←Table4**: 多级表头(实例规模分组×avg/max/min子列×方案行)。我们T8是"阈值θ×指标"结构不同→**T8壳待斟酌**: 可能更适合套封面篇表7"分组敏感性表"而非Soriano Table4。
- **下一篇范本待读**: Shi2025→F4充电(key未搜); Qiu2024→F5b碳价压力(key未搜); 碳交易机制多中心混合车队篇(SETP主模仿,key未搜)。F3两层碳/F5碳热力图/T9动态滚动仍NEEDS_REFERENCE_SHELL。
- **看图流程已验证**: pdftoppm转PNG(/tmp/setp_shells/)→Read PNG。读全文本用zotero_read_pdf_pages(超大则存文件,用python/jq在文件里定位caption页码,勿整读进context)。

**陈婉茹主模仿篇壳=完成✅(NKRC4JZU, 16页, 碳交易多中心混合车队, SETP, PDF=/Users/zhouleixishu/Zotero/storage/5GXPYVZH/...pdf)**:
- **⚠️纠正两次映射误判**: user映射表"陈婉茹2023 表5/图2/图3/表8/表10"**全部正确**, 对应的就是本篇(NKRC4JZU)。之前两轮我误判(说作者应是陈雨蝶/说F2F1编号错位)——是我拿冷链篇(陈雨蝶6KCQCP66)去核对陈婉茹篇编号, 核错了篇。**陈婉茹与陈雨蝶是两个不同作者的两篇不同SETP论文**: 陈婉茹NKRC4JZU=主模仿对象(映射本意来源, 混合车队主题最贴我们EV+CV); 陈雨蝶6KCQCP66=冷链封面篇(风格标杆)。两篇同SETP风格一致, 壳可互补。
- **陈婉茹篇=T3/F2/F1/T5/T7主模仿基准(映射全对)**: T3←表5(三线表 Ins.|n/d|BKS(Ref.)|各算法Gap%+t|Average行|Nbks行); F2←图2(单面板收敛折线,横轴迭代次数,纵轴路径长度,单线平滑下降~350次收敛; F2终值分布箱线本篇无壳待定); F1←图3(双面板(a)节点地理分布散点+(b)路线方案,不同颜色=不同车辆/实线燃油虚线电动/经纬度坐标——**与我们F1双面板完全同构**); T5←表8(算法消融 算法|最优解|平均值|Gap%|时间); T7←表10(碳价×碳限额双组敏感)。
- **额外壳**: 表9(车队动力配置:电/燃车辆数×固定/电耗/油耗/碳交易/碳排/总成本→**T4/T6车型反事实候选**, 极贴我们CV/EV); 图4(碳价×车队动力占比堆叠+不同碳价路径→**F5b碳价压力候选**, 未细看); 图5+表11(速度优化分组柱状,我们无速度但结构可参考)。

**🔎 壳目录v1审核结论(user审核, 2026-06-17)**:
- **算法命名规范(全论文)**: 用标准学术名 **SA / ALNS / DR-ALNS**, 禁用"winner kernel"等内部代号。SA=模拟退火基线; ALNS=我们主算法(原winner kernel); DR-ALNS=PPO控制(若成功)。
- **T7**: 套表(陈婉茹表10), **取消热力图**。✅锁定。
- **F5碳热力图=取消**: 与T7表(碳价×配额)内容重叠, 且user几乎没在范本见过热力图(不符学术惯例/不挑战审稿审美)。碳价敏感性由 T7表 + F5b曲线 覆盖。
- **F2**: 去箱线(绝大多数收敛图无箱线=惯例), 纯收敛曲线; 除非找到带箱线范本才保留。✅
- **T5**: 套陈婉茹表8结构OK; 可选新增"算法策略消融"(消融ALNS组件)若意义明确必要(等算法定稿判)。✅
- **F6公平前沿(Claude建议, 待user确认)**: 本质是**公平阈值θ约束扫描, 非Soriano双目标帕累托**。建议改"θ(横轴)vs总成本(纵轴)响应曲线"(可行连线+不可行标记), **补跑加密θ网格(如0.80-1.10每0.05)** 使曲线饱满。壳找"参数敏感性响应曲线"类(陈婉茹图4a碳价响应/Qiu敏感性), **Soriano Fig6降级参考**(双目标帕累托与我们约束法不完全对)。
- **T4 vs T6(Claude建议, 待user确认)**: 陈婉茹表9(车队动力配置×成本碳)=车型反事实→对应**T4主解车型反事实**; **T6两层碳**(直接/间接碳分解)结构不同, 另找碳分解表壳(缺口)。
- **当前缺壳(读完Shi/Qiu后去其他论文找)**: F6响应曲线壳、T6两层碳分解壳、F3两层碳图、T9动态滚动表。
- **顺序**: 审核(本轮)→user确认F6/F5/T4建议→读Shi2025(F4)/Qiu2024(F5b)→找其他论文补缺壳。

**Shi2025+Qiu2024壳=完成✅(2026-06-17, 5篇指定范本全读完)**:
- **F5b碳价压力←Qiu2024(QLD6M6FA) Fig5/6/7** ✅: 双轴图, 横轴碳价(对数刻度), 左轴总成本/碳排(折线), 右轴车辆数ICEVs/EVs(柱状)。展示碳价↑→碳排↓+EV替换ICEV。与我们F5b(碳价×总碳排+EV路线数双轴+误差棒)吻合。Qiu Fig8(a)(b)双面板(多调控CT/CTD/CO×碳价×TC/CEs)备选。PDF=/Users/zhouleixishu/Zotero/storage/5EKAGHKW/...pdf。
- **F4充电←Shi2025(IB9ZNJR3) 部分** 🔶: Shi充电图主要是"场景×成本柱状对比"(Fig5场景充电价格/Fig7 TOU vs固定电价充电成本双面板/Fig8利润)。F4"充电策略对比/峰平谷占比"部分→借Shi Fig7双面板柱状。**F4核心"48槽时变碳强度+充电负荷叠加图"Shi无壳→缺壳, 去充电调度论文找**(库里Carbon-aware EV charging=TK9YAAPC候选)。PDF=/Users/zhouleixishu/Zotero/storage/K4WVSUAB/...pdf。

**🗂️ 壳目录v1最终盘点(5篇指定范本读完)**: 已锁壳: T3←陈婉茹表5; F2←陈婉茹图2(去箱线); F1←陈婉茹图3(双面板); T5←陈婉茹表8; T7←陈婉茹表10(表非热力图); T4←陈婉茹表9; F5b←Qiu Fig5(双轴); 风格←陈雨蝶冷链。壳型定待数据: F6(θ响应曲线, 补跑加密θ网格, 壳用陈婉茹图4a/Qiu式响应曲线非Soriano帕累托)。部分/待斟酌: F4(Shi Fig7策略对比部分+时变叠加缺壳); T8(Soriano Table4待斟酌或套陈婉茹分组表)。**缺壳=去其他论文找**: F4时变碳强度+充电负荷叠加(充电调度论文,TK9YAAPC候选)、F3两层碳图、T6两层碳分解表、T9动态滚动表。取消: F5碳热力图。不找: F2箱线(去掉)。

**7张壳全部user确认✅(2026-06-17) + 施工细节规范(Codex画图阶段必须执行)**:
- **F1路线**: 图形大小/颜色/形状/比例像素级高度一致; **坐标轴单位正确处理、数值别太大→等价缩小**(我们坐标±60000km, 换单位如百km/千km或缩放, 别显示巨大数值); **不强行凑左右双面板**(不硬塞); 保证正确显示与观感; **算例太大不便展示则换小算例演示**(允许范围内, 如用25c/100c而非219c)。
- **F2收敛**: 注意y轴数值步进大小, 使收敛效果/趋势显著(别被压平到看不出差异)。
- **T5消融**: 机制开关名**标准化**, 禁口语/黑话。规范术语如: 无碳感知调度/无多车场协同/无收益公平/完整模型(或英文 w/o carbon-aware, w/o collaboration, w/o fairness, full model)。
- 通用: 所有图表数值单位、轴范围、步进都要符合学术惯例+让趋势显著, 不挑战审稿固化审美。

**🔧 缺壳进度(2026-06-17, 开始找其他论文)**:
- **F4充电=补齐✅**: 时变叠加部分←**TK9YAAPC(Carbon-Aware EV Charging, Cheng2022, 7页) Fig6**(上下双子图: 上=碳强度C(t)曲线duck curve+碳排放, 下=充电负荷u(t)朴素baseline vs碳感知carbon-aware两组, 横轴Time 0-24h, 图例区分策略; 核心=碳感知把负荷移到低碳时段)——完全对应我们F4"48槽碳强度+充电负荷"。占比部分←Shi Fig7柱状对比。PDF=/Users/zhouleixishu/Zotero/storage/57ITRNUI/...pdf。F4单场景版=单面板上下双子图(碳强度|充电负荷)。
- **T9动态滚动→待读 EDLCS6I6**(Dynamic EVRP+新需求到达, 最贴) 或 HN59F5EX(rollout)。
- **F3/T6两层碳(直接燃油+间接电网碳)→仍缺**: 中文"间接碳排放/全生命周期"无果, 待英文词(well-to-wheel/direct-indirect emission/scope)搜; 我们特色概念, 范本可能少。
- 候选库存: TK9YAAPC(F4✅用了)/HEQNHHVF/JC9NLZJA(充电碳); 6Z9A3BFA(清单4协同EV共享充电); 9ATD3MU5(时空VRP碳)。

**🏁 缺壳最终判断+壳目录建壳阶段完成(2026-06-17)**:
- 两层碳/well-to-wheel中英文搜均无库存范本。**结论: F3/T6/T9不必专门找新论文**——它们是通用学术图表型, 用已读范本的通用壳装即可(仍出自真实论文真实图型):
  - **T6两层碳表→对比表壳(陈婉茹表9式: 方案×碳/成本列, 装CV-only vs混合)**。
  - **F3两层碳图→堆叠/分组柱状壳(每方案一柱分直接燃油碳/间接电网碳; 范本Shi Fig5/Qiu式分组柱)**。
  - **T9动态滚动表→分阶段表壳(stage行×指标列; 范本陈婉茹/Qiu多行对比表)**。EDLCS6I6只有HTML无PDF看图走不通; 若user要动态VRP专门范本可再找HN59F5EX, 但通用分阶段表够用。
- **壳目录v1"建壳+提壳"阶段=完成**: 所有13图表都有壳来源(指定范本锁定T3/F1/F2/T5/T7/T4/F5b/F4/风格 + 通用图型F3/T6/T9/T8 + F6响应曲线待补跑θ)。取消F5热力图/F2箱线。
- **下一步=第三阶段"数据适配矩阵"**: 验证ReSETP的CSV/JSON字段能否填进各壳, 缺字段HALT; 注意施工规范(F1坐标轴缩放/F2步进显著/T5机制名标准化/算例太大换小算例)。之后才第四阶段写Codex施工提示词。读范本共6篇: 陈雨蝶6KCQCP66/陈婉茹NKRC4JZU/Soriano IF3WEZZJ/Shi IB9ZNJR3/Qiu QLD6M6FA/Cheng TK9YAAPC。

**📊 数据适配第三阶段=完成(2026-06-17, 读schema.py+registry.py+runner.py+实地验CSV)**:
- 主数据字段表=reporting/schema.py EXPERIMENT_FIELDS(27字段): instance/algorithm/seed/budget + 成本分解(cost_fixed/distance/fuel/electricity/occupancy/cross_site/carbon_trading/total) + **碳两层(diesel_carbon_kg直接 + charging_carbon_kg间接 + total_carbon + stake充电碳占比)** + ev_count/cv_count/cross_site_customers + profit_by_depot_json + feasible/elapsed/evals。**两层碳字段完备**→F3/T6数据PASS。
- 图表数据来源(runner.py): F1←f1_route_nodes/lines.csv; F2←f2_algorithm_curves/finals.csv; F4←f4_48slot_charging.csv; F5b←t7b_carbon_stress.csv+seed_detail; 表←formal/tables/*.csv。
- **实地验CSV(行数)**: f4_48slot_charging=**97行(数据在!)**、f1_nodes=225/lines=66、f2_curves=5785-21960/finals=161、t7b_carbon_stress=9、t4_decomp=13。**关键: F4空图≠数据缺, 是figures.py figure_f4_48slot_charging画图代码bug(97行数据没渲染)→重画时Codex修渲染**。
- **数据适配结论**: ✅数据齐字段够=T3(补n/d+BKS从算例/下界)/T4/T5/T6/F1/F2/F3/F5b; ⚠️F4数据齐但画图bug(重画修); 🔶维度待确认=T7碳价(t7b有)/T8θ/T9 stage(公平x1/动态E7报告里, 重跑确保记录); ❌**F6=唯一数据HALT**(runner.py:366实锤"当前reports无完整θ扫描, 其余点样张水印"→必须补跑θ)。
- **要点**: 数据基本全齐(13图仅F6真缺数据), 字段结构齐=壳填得进; 但数字是坏ALNS跑的=要等大重跑(修好winner kernel)替换。**待办: ①F6补跑θ扫描 ②F4修画图代码渲染 ③大重跑替换全部数字 ④T3补n/d+BKS**。
- **顺序**: 1数据适配(完成)→2审核(进行)→user确认后第四阶段写Codex施工提示词(数字待大重跑)。

**🧩 图表样板定稿实现(2026-07-03, Codex, mock-only / no solver)**:
- 新增 `solver/src/setp_solver/reporting/design_templates.py` 与 runner `design-templates`，输出到 `docs/paper_submission_final/design_templates/`；只读 `mock_data/*.csv`，不走 formal fallback，不覆盖正式 `generated_tables/` 或 `generated_figures/`。
- 样板包含 `mock_data/`、T1/T3/T4/T5/T6/T7/T8/T9 的 `.tex` 表片段、F1-F7 的 PDF+PNG、`DATA_CONTRACT.md`、`design_preview.tex`、`design_preview.pdf`、`design_template_report.md`。所有 mock 图带“样例数据/非实验结果”水印，表片段带同义注释。
- 契约调整落地：T3 加均值/std/偏差/可行率/等eval/等墙钟/显著性；T4 转置成仅油/仅电/混合反事实分解；T5 使用“均值±std + 相对完整模型Δ% + 显著性 + 跨场/公平”结构；T6/F3 统一三行链条“仅油车重优化→混合朴素充电→混合碳感知择时”；T7/F5 删除配额热力图轴，改碳价响应；T8/F6 用细 θ 网格和不可行底纹；T9/F7 承载动态事件、冻结/重规划、信息成本、跨场、公平、低碳充电占比。
- `paper_main.tex` 只做编辑性修复：去掉算法数/残句/3条事件流/25客户等旧口径，F5 改为优先未来 response curve，未改模型公式与旧数字结论。验证：reporting 单测 15 passed，样板预览与主文档均可 XeLaTeX 编译；全量 `solver/tests` 仍有 5 个非 reporting 旧链失败。

**🔁 大重跑提示词②已写好(2026-06-17, 可与离线体检①并行发Codex)**:
- formal_runner.py跑E0-E7(resumable/RunKey去重), PRIMARY_ALGORITHM="ALNS-Wouda"(candidates.py:40)。**E1-E7→表图**: E1主解+车型反事实→T4(+F1); E2算法对比→T3/F2源; E3消融M0-M5→T5; E4碳价×配额→T7/F5b; E5 replay→T6/F3/F4源; **E6 theta扫描→T8/F6**; E7动态→T9。
- **F6的θ扫描数据=跑E6生成**(之前以为要专门补, 其实E6就是; 大重跑E6加密θ网格0.80-1.10每0.05→F6饱满前沿, 解锁)。**F4数据来自E5(97行在), 空图是figure_f4渲染bug**。
- **大重跑核心=锁PRIMARY为winner kernel**: 全程设winner_variant_flags(SETP_ALNS_CRUSH_*=0关有害加料)+系统Python(/opt/anaconda3/bin/python3.13+numpy2.3.5)+PYTHONHASHSEED=0; **先验E2/100-01=£4878碾压SA£5347零违约再全跑**(旧R2是"加料开"次优ALNS-Wouda, 全废)。
- 阶段: 0锁PRIMARY→1跑E1-E7(E6加密θ/各10seed/零违约)→2重生成表图(修F4渲染/算法名标准化ALNS-Wouda→ALNS·scikit-opt-SA→SA/T5机制名规范/碳占位→终值)→3 DR-ALNS列依离线体检①(WEAK→不含或future work; PROMISING且CUDA训出→后补)。终值绑commit+环境可复现。
- **算力**: 大重跑E1-E7各10seed×16000eval=天级以内(非PPO 7.5天), 与离线体检①并行。②跑完→图表第四阶段(选B)有真数字。
- 当前: 离线体检①已发Codex跑(2026-06-17); 大重跑②待user发。
- **封面篇不覆盖**: F6公平前沿(→Soriano IF3WEZZJ Fig6)、F5碳热力图(→表7改造或另找)、F4充电(→Shi2025)、F5b碳价压力(→Qiu2024)、T9动态滚动(NEEDS_REFERENCE_SHELL)、T8公平表(→Soriano)。这些范本待读(Shi2025/Qiu2024/碳交易多中心篇key未搜)。
- **壳提取格式样板(T3←表5)**: 壳ID/类型/列结构/行结构/可本地化项/禁止改动项/ReSETP数据源。每张图表按此格式产出。

**🎨 全文图表仿制纪律（2026-07-14，用户明确要求，长期有效）**:
- 全文先选一篇与目标期刊和研究主题最接近的论文作为主母版，字号、字体、线宽、颜色、标记、图幅、图例和留白均从其 PDF 实测后统一复刻，禁止凭感觉“学术化美化”。
- 若主母版没有某类图，才允许为该图另找一篇真正同型的论文；该图必须整体采用第二母版的完整视觉系统，禁止从多篇论文分别借颜色、线型、图例或标记后拼装。
- 每次启用第二母版，必须记录文献、图号、为何主母版不适用、采用的实测参数，并在论文中引用。目标期刊的强制字体、图题和矢量格式规范优先于母版。
- 图表全部由代码从封存数据生成，正文嵌入矢量 PDF；禁止生成式图片、手工描图和像素级事后修改。
- E2—E3 当前主母版=陈婉茹等（2023，《系统工程理论与实践》）；E3 客户责任结构图因陈文没有同型图，唯一例外完整采用 Soriano 等（2023）Fig. 3。实测合同见 `docs/paper_submission_final/e2_e3_preview_20260714/SETP_VISUAL_CONTRACT.md`。

**📐 主稿落地后的统一尺寸与图例规则（2026-07-14，覆盖旧预览细节）**:
- 算法收敛图改以陈雨蝶等（2025）Fig. 4 的多算法迭代曲线为同型母版；九种算法必须全部展示，正文、表格、曲线与图例统一使用英文缩写，不再中英混排。
- 所有正文数据图的图例均放在图内右上角。不得把图例移到图外；应通过延长横纵轴可视范围、压缩数据曲线占比并预留右上空白，避免遮挡曲线或散点。图例、线条和边框保持细线，不靠粗线或大色块制造区分。
- 正文常规三线表统一使用相同字号、行距和 `0.84\linewidth` 表宽；仅逐网络附录宽表使用 `0.92\linewidth`。极少数信息密度确实更高的表才允许另行放宽，必须说明原因。
- 当前主稿的九算法图使用221客户网络、10次运行的中位收敛轨迹；正式数据到4000次评价，显示横轴延长到4400，纵轴也额外留白，图例为图内右上角三列。客户责任图同样统一为图内右上角，并为图例扩展坐标范围。

**🅰️ PPO线最新(2026-06-17, 详见 [[alns-crush-root-cause]] PPO V3段)**: per-step PPO已判WEAK(策略塌缩固定动作, 100-01 ppo£6086>>alpha£4878>random_full£4781; random_full是winner算子空间强随机非弱基线)。已转block-level DR-ALNS controller(block_ppo, action[7,4,5,4,4]=destroy/repair/q/threshold/exploration, block128, 125 RL steps/episode)。

**Claude把关V3(2026-06-17, user要求控制Codex"试试水"工作)**:
- 设计层面**方向正确,非乱搞**: block-level对齐Reijnen DR-ALNS文献(读了本地参考实现); 动作空间18000→2240; "or_alpha_ucb"档给PPO保底退化; reward改block后真实best-cost改善不奖励讨巧; gate设计能验证block环境。
- **风险点(把关发现)**: ①exploration_ratio第5维是Codex自创(标准DR-ALNS仅4维),需验证有用否则噪声; ②reward的route-count改善可能与best-cost(含固定成本=路线×£80)double-count; ③gate真判据=random_block/alpha_ucb_block有没有被block化拖差。
- **gate实测(seed1-4 partial)**: official=alpha_ucb_env每seed完全相等(5055/4779/4791/4872)锚复现✓; **棋盘好=block化没弄坏搜索**: random_block(4761-4814)≈random_full(4788), seed3 random_block£4761<official£4779; alpha_ucb_block略逊(seed2/3差£100+,因q被固定0.16而random_block q分散)。gate大概率PASS。
- **冷静预判(关键)**: random_block已太强(接近/偶超winner kernel)→和per-step同困境,DR学习增益空间仍薄。block化修了"信用分配"工程问题, 但没解决"强随机基线→PPO难超"的根本问题。
- **下一步控制**: 等gate全表(seed5-10)确认→PASS后只训小pilot(72000步,勿百万步)→判据ppo_block能否稳定≤random_block/alpha_ucb_block→**仍输则诚实止损**(DR=future work/可学习替代, 算法主贡献押winner kernel碾压SA8.8%+机制创新), 绝不因"block化对了/gate过了"包装成"DR成功"。

**2026-07-14正文复核补丁**：表2的摩擦代理值说明已移出数据行，保留为表后口径说明；未完成实验统一使用正文占位，不用旧试跑填图表。附录置于参考文献之前，且必须在 `\appendix` 前 `\clearpage`，否则模板会把结论所在页一并重置为罗马页码。IWD在221客户收敛图中的水平线来自封存旧简化实现10/10次未改善共同起点，是失活证据而非稳定收敛；图中可为完整披露保留IWD，但强统计不得纳入IWD，算法优势计数不得借它扩张。
