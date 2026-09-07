# 降本减排措施分类——来自文献综述的取证与合并树

调查日期 2026-09-08。**只读调查**：未改动论文、未跑求解器、未改 Zotero 库。
服务对象：`docs/paper_v2/paper_main.tex` 第 1215 行起的 4.4.3 节（不同碳减排政策对比分析）。
任务约束：4.4.3 要先"分类列出目前普遍采用的降本减排措施"，**分类必须出自文献综述的原文用词，不得自行归纳**；展示形式为思维导图 / 树状图。

---

## 零、一句话结论与两道判断题

**结论**：能满足"分类来自文献"的要求，但**不能靠一篇综述**——运筹与车辆路径这一族的综述里没有以政策工具为分类维度的（本轮再次证实），可用的分类分散在四个不同领域的综述里。本报告把它们合并成一棵五枝的树，**每个节点都注明出自哪篇文献哪一页的原文用词**，本文实测的措施在树上标星。

**一条必须先说的实情**：任务要求"至少一篇分类来自目标期刊或同级中文期刊的综述"，**这一条只能部分满足**。目标期刊的绿色车辆路径综述（周鲜成等 2021）全文对碳税、补贴、碳限额、碳配额、政策五词零命中（已做抽取器自检），它按目标函数形态分类，不按政策工具；这不是漏检，是这一族综述确实没有。**替代物本轮找到了**：目标期刊的陈婉茹等 2023（论文已引，`ref:23`）表 1 第 3322 页有一列「碳规制政策」，取值为碳限额 / 碳税 / 限额碳交易 / 无——**是目标期刊里现成的碳政策分类与中文用词，但载体是研究论文的文献总结表，不是综述**。建议把"这一族综述里没有政策工具分类"直接写成 4.4.3 的一句话，从缺口变成一句有证据的表述（第五节给了示范段落）。

**判断题（只需回答做 / 不做）**

| # | 事项 | 选它意味着 | 推荐 |
|---|---|---|---|
| 判-1 | 4.4.3 现有的"价格信号协调类 / 碳定价类 / 车队经济性类"三类名称，是否改成本报告第四节的综述原文一级名称？ | 改：一级名称全部有综述出处，抗"信息不全 / 自造分类"的质疑；代价是一级由 3 支变 5 支，正文那段要重写约 8 行，且要新增 6 条参考文献。不改：现名读起来更贴本文实验，但三个名称在任何综述里都查不到，评审若追问出处只能答"作者归纳"。 | **改** |
| 判-2 | 是否在 4.4.3 开头加一张分类图，用"类目带 × 措施列 + 打点"的形式（能在同一张图里同时标出措施属于哪一类、本文测没测、它改不改决策）？ | 加：解决"分类列不全"的观感问题；比纯树状图省版面；代价是多占约三分之一栏，且 4.4 节已有图 4、图 6 两张。不加：分类只能用文字列举，读者要自己在脑子里搭层级；另注意目标期刊同类分类的现成展示形式是"文献总结表"（见 S0），不是树图，走表格路线也有先例。 | **加** |

---

## 一、证据分级与本轮的工具约束

- **【已核原文】**＝本轮实际打开 PDF 或期刊网页，分类名称、页码、图号来自正文或图题。
- **【已核摘要】**＝只打开了权威书目库（Crossref / RePEc）的逐字摘要，正文未取到。摘要里写死的分类可以引，正文页码不得编造。
- **【转述】**＝只见检索引擎或图库条目的二手描述，正文与图题均未打开。**不得进论文正文**，只作线索。
- **【未找到】**＝按附录检索式检索后零命中，且已做抽取器自检。

**本轮的工具约束（写下来，免得下一位代理重踩）**

1. **Zotero 语义检索不可用**：`zotero_semantic_search` 返回 "Semantic search is not available. Install the required packages with: pip install zotero-mcp-server[semantic]"。本轮只能用 `zotero_search_items` 的**子串匹配**，中文检索词必须短（"综述""政策"），长查询会把结果缩到零。
2. **多家中文期刊站点对本机 403**：电子科技大学学报社科版（`social.uestc.edu.cn`，刘名武等 2022 综述）、中国环境管理（`zghjgl.ijournal.cn`）、Cardiff ORCA、Oxford ORA 均返回 403 或反爬页。curl 换 UA 与 Referer 亦无效。这几篇只能标【未找到】或【转述】。
3. **能取到全文的路径**：中国工程科学（`engineering.org.cn` → `jf2.hep.com.cn` 302 跳转后可下）、城市与环境研究（`rieco.ajcass.com` 直链 PDF）、UC Davis ITS（`itspubs.ucdavis.edu`）、RePEc 摘要页、Crossref API。

**复用声明**：本报告不重复检索 `docs/handoff/carbon_policy_instruments_survey_20260906.md`（24 类工具目录、A/B/C"是否改变决策"三分法、碳价扫描惯例、各工具的效应数字与页码）与其列出的九份前置调查。本轮**新做**的只有一件事：**综述层面的分类取证**——哪篇综述、第几页、用什么原文词、分成几级、有没有分类图、图长什么样。

**顺带更正一条**：`carbon_policy_instruments_survey_20260906.md` 附录空白 #2 把 Moghdani 等 2021 的绿色车辆路径综述记为 *Omega*。经 Crossref 核对，正确出处是 **Journal of Cleaner Production, 2021, 279: 123691, doi:10.1016/j.jclepro.2020.123691**。该文正文本轮仍未取到，其一级分类维度仍为【转述】，不得进正文。

---

## 二、逐篇综述的分类取证

### S0　陈婉茹等 2023——**目标期刊里现成的碳政策分类，且带中文原文用词**（本轮最重要的新取证）

| 项 | 内容 |
|---|---|
| 出处 | 陈婉茹, 徐光明, 张得志, 曹健. 碳交易机制下多中心混合车队配送路径和速度优化研究[J]. **系统工程理论与实践, 2023, 43(11): 3320–3335.**（论文 bibitem 已有，`ref:23`；Zotero `NKRC4JZU`，PDF 全文本轮已读） |
| 类型 | **研究论文，不是综述**——但其第 2 章的文献梳理里有一张按碳政策分类的**文献总结表** |
| 分类所在 | **表 1「混合车队配送相关文献总结」，p.3322** |
| 分类原文（逐字抄录表头与该列取值） | 表头：`作者 ǀ 年份 ǀ 多配送中心 ǀ 时间窗 ǀ 可变车速 ǀ 实际能耗 ǀ 碳排放 ǀ **碳规制政策**`；「碳规制政策」列的取值只有四种：**碳限额**（Islam 等 2021）、**碳税**（Yu 等 2021）、**无**（Al-Dalain 等 2021、范厚明等 2022、侯登凯等 2022、Amiri 等 2023）、**限额碳交易**（本文 2023） |
| 表的形式 | **文献总结表**：行＝7 篇文献 + 本文，列＝8 个属性；前六个属性列用 √ 标记有无，最后一列「碳规制政策」直接写政策名称。**不是树状图。** |
| 全文词频（已做抽取器自检） | 碳交易 65、碳价 17、碳限额 12、限额碳交易 8、政策 7、碳税 1、碳配额 1、碳规制 1、**碳补偿 0、碳抵消 0**。自检：同文件"碳排放""电动车"等词高频，说明抽取正常 |
| 证据等级 | **【已核原文】** |

**这一条同时解决三件事**：

1. **中文一级用词有了目标期刊出处**：「**碳规制政策**」这五个字是目标期刊里现成的上位词，比自造的"碳定价类"强；下位词「碳限额」「碳税」「限额碳交易」三项也是目标期刊原文，可直接做树上的中文节点名。
2. **同时暴露一个缺口**：「碳补偿 / 碳抵消」在该文全文**零命中**——中文侧这一格没有目标期刊先例，若树上要保留这一支，中文名只能取自 Qiu 等 2024（IJPR，英文 carbon offset）或丁澍与邱玉琢学位论文的摘要用词，须在正文注明。
3. **给出了目标期刊的现成展示形式**：这一族分类在目标期刊里的呈现方式是**文献总结表**，不是树状图。这是判-2 的重要背景——走表格路线在目标期刊里有直接先例，走树图路线则要跨领域借版式（见第六节）。

**局限要写明**：它是研究论文的文献梳理表，不是文献综述；其分类只覆盖碳政策一支，不覆盖电价、购置补贴、路权等其余四支。所以它**不能单独承担 4.4.3 的分类**，只能做碳政策那一支的中文命名与目标期刊背书。

---

### S1　Waltho, Elhedhli & Gzara 2019——碳排放政策的四分法（本树第 1 支的唯一来源）

| 项 | 内容 |
|---|---|
| 出处 | Waltho C, Elhedhli S, Gzara F. Green supply chain network design: A review focused on policy adoption and emission quantification[J]. **International Journal of Production Economics, 2019, 208: 305–318.** doi:10.1016/j.ijpe.2018.12.003（Crossref 已核） |
| 类型 | 文献综述（覆盖 2010—2017 年中的绿色供应链网络设计文献） |
| 分类维度 | **政策采用（policy adoption）**——这是本轮找到的**唯一**以碳政策为组织轴的综述 |
| 分类原文（逐字） | "We find that supply chain network design has mostly incorporated **four policies: carbon cap, carbon offset, cap-and-trade and carbon tax**." |
| 同段的效应判断（逐字） | "All four policies succeed to achieve substantial emission reductions with a slight increase in total cost; mostly by configuring the supply chain to use lower-emitting resources." |
| 层级 | 一级：environmental policies；二级：上述四项并列，无三级 |
| 分类图 | **正文未取到（Elsevier 全文付费墙，本机 403）**，因此**不知道**该文是否有分类图。摘要为 RePEc 逐字页 |
| 证据等级 | **【已核摘要】**——四政策的名称与并列关系可引；页码只能引 305–318 的整篇范围，**不得写"见第 X 页图 Y"** |

**为什么这一支值得当一级**：它把本文表 13 已有的碳价、碳配额两行放进了一个有综述背书的四格里，缺的两格（carbon cap 硬约束、carbon offset）正好可以在树上保留为"未实测分支"。这比自造"碳定价类"三个字强得多。中文对应词不必自造，同期刊已有现成用法：陈婉茹等 2023（SETP 43(11)）用"碳交易机制/碳限额"，李进、张江华 2014（SETP 34(7)）用"碳交易机制"，Qiu 等 2024（IJPR 62(16)）用 CC / CT / CTD / CO 四缩写。

---

### S2　Hardman 等 2017——电动车购置端财政激励的四分法（本树第 2 支）

| 项 | 内容 |
|---|---|
| 出处（期刊版） | Hardman S, Chandan A, Tal G, Turrentine T. The effectiveness of financial purchase incentives for battery electric vehicles – A review of the evidence[J]. **Renewable and Sustainable Energy Reviews, 2017, 80: 1100–1111.** doi:10.1016/j.rser.2017.05.255（Crossref 已核） |
| 本轮实际打开的版本 | 同一批作者的机构报告版 **UCD-ITS-RR-17-24 / EVS30 会议版**（`itspubs.ucdavis.edu`，开放获取），§1.2 "Introduction to Purchase Incentives" 第 3–4 页、§2.2 "Incentives Considered" 第 6 页 |
| 类型 | 文献综述（系统梳理 35 项研究） |
| 分类原文（逐字，§1.2 p.3–4） | "Purchase incentives take several different forms; they can be grouped into **four different types of incentive**… The four types of incentive are: **Point of Sale Grant Incentives** … **VAT and Purchase Tax Exemptions** … **Post purchase rebates** … **Income tax credits**" |
| 每类的定义（逐字节选） | Point of Sale Grant Incentives：*"reduce the purchase price of a BEV when a consumer buys the vehicle"*；VAT and Purchase Tax Exemptions：*"allow buyers of BEVs to pay lower or zero VAT or pay no purchase tax"*；Post purchase rebates：*"financial incentives being given to consumers after they have purchased the vehicle"*；Income tax credits：*"allow buyers of BEVs to pay a reduced income tax bill at the end of the financial year"* |
| **补集的原文名称**（逐字，§2.2 p.6，这一句极有用） | "The review therefore does not include incentives such as **free parking, access to infrastructure, bus lane access, high occupancy vehicle (HOV) lane access, toll road access** or any other benefits PEVs drivers receive when using their vehicles… they are not applied at point of sale and are known as **reoccurring or indirect incentives**." |
| 分类图 | **Table 1**（p.4），图题逐字："Breakdown of purchase incentives for the top 9 markets for BEVs including the value of the incentives."——形式是**国家 × 四类激励的勾选矩阵**（行＝9 个国家，列＝四类激励 + 本币金额 + 美元金额，格内打勾），**不是树状图** |
| 证据等级 | **【已核原文】**（报告版页码）。若要引期刊版页码，须另核 RSER 80:1100–1111 的对应页 |

**注意**：本轮打开的是机构报告版，页码与 RSER 期刊版不同。正文引用请写期刊版出处，页码若要精确到节，须补核期刊版；或按本仓库惯例只引整篇。这一条已列入第七节未核清单。

---

### S3　Hardman 2019——复发性与非财政激励（本树第 3 支）

| 项 | 内容 |
|---|---|
| 出处 | Hardman S. Understanding the impact of reoccurring and non-financial incentives on plug-in electric vehicle adoption – A review[J]. **Transportation Research Part A: Policy and Practice, 2019, 119: 1–14.** doi:10.1016/j.tra.2018.11.002（Crossref 已核，**单作者**） |
| 类型 | 文献综述，且是 S2 的明确补集（S2 §2.2 把这一族排除在外，本文专门补上） |
| 分类原文（逐字，摘要） | "Reoccurring and non-financial incentives include **special lane access for PEVs (e.g. HOV/carpool lanes, bus lanes), parking incentives, charging infrastructure development, road toll fee waivers, and licensing incentives**. They also include **disincentives such as gasoline tax or annual vehicle taxes**." |
| 另一句可引的原文 | "Due to these differences, it is challenging to **rank the importance of these incentives**, however existing research shows that they all can have a positive impact on PEV adoption." |
| 层级 | 一级：reoccurring and non-financial incentives；二级：五项正向 + 一项抑制（disincentives）；无三级 |
| 分类图 | **正文未取到**（Elsevier 付费墙；eScholarship 条目页本机取回 0 字节），是否有分类图**未知** |
| 证据等级 | **【已核摘要】** |

**这一支对本文的价值**：中国城市的**限行 / 路权优惠**与**牌照优惠**在这里有综述层面的英文原名（special lane access、licensing incentives），不用自造词；而"低排放区 / 燃油车进城收费"落在同支的 disincentives 侧，本仓库 09-06 表已有 Bruglieri 等 2025（TRE 201:104230，收费倍数扫描多数算例路线不动）与刘长石等 2026（系统科学与数学 46(1)，限行区放开电车服务范围总成本 −14.1%）两条实证可挂。

---

### S4　Albadi & El-Saadany 2007——需求响应项目的完整分类树（本树第 4 支；**正文与图题已核**）

| 项 | 内容 |
|---|---|
| **本轮实际打开并核实的版本** | Albadi M H, El-Saadany E F. **Demand Response in Electricity Markets: An Overview**[C]//**2007 IEEE Power Engineering Society General Meeting. Tampa, FL: IEEE, 2007: 1–5.** doi:10.1109/PES.2007.385728（Crossref 已核；PDF 全文本轮已下并读） |
| 同族的期刊版 | Albadi M H, El-Saadany E F. A summary of demand response in electricity markets[J]. Electric Power Systems Research, 2008, 78(11): 1989–1996. doi:10.1016/j.epsr.2008.04.002（Crossref 已核书目；**正文未取到**，故本报告一律引 2007 会议版） |
| 类型 | 综述性 overview，摘要逐字："This paper presents an overview of demand response (DR) in electricity market. **The definition and a classification of demand response will be presented.**" |
| 分类图 | 该文 **Fig.1**，图题逐字：**"Classification of Demand Response Programs"**（第 2 页左栏下部）。形式为**纵向缩进式大纲树**（四级缩进的纯文字层级，无方框、无连线、无底色），与 S7 的带框横向树是两种不同做法 |
| **分类原文（逐字抄录 Fig.1 全部节点）** | ```Demand Response Programs → Incentive Based Programs (IBP) → Classical → Direct Control / Interruptible/Curtailable Programs；Market Based → Demand Bidding / Emergency DR / Capacity Market / Ancillary services market。Price Based Programs (PBP) → Time of Use (TOU) / Critical Peak Pricing (CPP) / Extreme Day CPP (ED-CPP) / Extreme Day Pricing (EDP) / Real Time Pricing (RTP)``` |
| 正文对该图的说明（逐字，p.1–2） | "Different DR programs are shown in Fig.1. These are **Incentive-Based Programs (IBP) and Priced Based Programs (PBP)**. IBP are further divided into **classical programs and market based programs**. Classical IBP include Direct Load Control programs and Interruptible/Curtailable programs. Market based IBP includes Emergency DR programs, Demand Bidding, Capacity Market, Ancillary services market." |
| 关于 TOU 的定位（逐字，p.2） | "These rates include **Time of Use (TOU) rate, Critical Peak Pricing (CPP), Extreme Day Pricing (EDP), Extreme Day CPP (ED-CPP), and Real Time Pricing (RTP)**. **The basic type of PBP is TOU rates.** These rates of electricity prices per unit consumption differ in different blocks of time. The rate during peak periods is higher than the rate during other off-peak periods. **The simplest TOU rate has two time blocks; the peak and the off-peak.**" |
| 证据等级 | **【已核原文】**（图题、四级节点名、说明段落均逐字抄自 PDF） |

**这条把上一版报告的最大风险消掉了**：本文实测的"谷段设在午间"属于 TOU，而 TOU 的上位名称（Price Based Programs）此前只是转述；现在整棵子树的原文用词、图号、图题都已核实，**不再有"实测节点挂在未核父节点下"的问题**。

**中文对应词**：分时电价（TOU）在本文参考文献里已有一手政策文件出处（`ref:ndrc-tou` 发改价格〔2021〕1093 号、`ref:hebei-tou` 冀发改能价〔2022〕1364 号），中文名不必另找。CPP / EDP / ED-CPP / RTP 四项在中文侧未找到目标期刊先例，树上保留英文原名加中文直译即可，并注明未实测。

---

### S5　李晓易等 2021——中文侧的减排举措五分法（本树第 5 支的中文用词来源）

| 项 | 内容 |
|---|---|
| 出处 | 李晓易, 谭晓雨, 吴睿, 徐洪磊, 钟志华, 李悦, 郑超蕙, 王人洁, 乔英俊. 交通运输领域碳达峰、碳中和路径研究[J]. **中国工程科学, 2021, 23(6): 15–21.** doi:10.15302/J-SSCAE-2021.06.008 |
| 类型 | 中国工程院战略研究（综述性路径研究，非严格文献综述）；开放获取，本轮已下全文 |
| 分类原文（逐字，摘要 p.015） | "结合交通运输的发展趋势，进一步从**优化运输结构、提升运输装备能效、推广应用低碳运输装备、提高运输组织效率、鼓励绿色出行**等方面着手，详细分析并总结了推动交通碳达峰、碳中和的举措建议" |
| 层级与页码（正文，§五 pp.018–020） | 一级："五、推动交通运输领域碳达峰、碳中和的举措与建议"（p.018 起）；二级五项，逐字：**（一）优化运输结构**（p.018）、**（二）提升运输装备能效**（p.018）、**（三）推广应用低碳运输装备**（p.018–019）、**（四）提高运输组织效率**（p.019）、**（五）鼓励绿色出行**（p.020） |
| 每类的定性原话（逐字节选） | （一）"优化运输结构是碳达峰阶段的主要举措之一，需加快大宗货物和中长距离货物运输的'公转铁''公转水'"；（三）"推广应用低碳运输装备是推动交通碳中和的关键举措，应加快新能源运输装备研发、分场景适配的电动化进程"；（四）"提高运输组织效率也是推动交通碳达峰、碳中和的关键举措，应加快发展智慧交通，推广高效组织模式" |
| 分类图 | 该文只有两张数据图（图 1 我国交通运输领域 CO₂ 排放量占比、图 2 公路运输各类车型 CO₂ 排放情况），**无分类树图** |
| 证据等级 | **【已核原文】** |

**这一支解决什么**：它是**中文侧唯一能拿到的、有页码的一级用词来源**，而且它的（三）（四）两项正好覆盖本文的两件事——车队电动化落在"推广应用低碳运输装备"，多车场协作配送落在"提高运输组织效率"。中文正文写"本文的措施属于……"时可以直接借这两句原话，不用自造上位词。

**局限要写明**：它是全交通运输口径（含铁路、水路、航空、客运），不是城市配送口径；它的五类是"举措"不是"政策工具"，与 S1–S4 不在同一个分类维度上。因此本报告**不把它当合并树的一级**，只当"中文一级用词的先例 + 第 5 支的挂靠点"。

---

### S6　史丹等 2017——中文侧的碳交易 vs 碳税比较（第 1 支的中文佐证）

| 项 | 内容 |
|---|---|
| 出处 | 史丹, 张成, 周波, 杨璐. 碳排放权交易的实践效果及其影响因素：一个文献综述[J]. **城市与环境研究, 2017(4): 93–110.**（文章编号 2095-851X(2017)04-0093-18；栏目标注"·学术综述·"） |
| 类型 | 学术综述（中文），开放获取，本轮已下全文 |
| 分类维度（逐字，摘要） | "作者从**碳排放权交易理论的发展历程、与征收碳税的减碳机制比较、碳排放权交易的实施效果及其影响因素**这四个维度，系统归纳、梳理和评价了有关碳排放权交易的最新文献" |
| 可引的比较原话（逐字，正文 pp.095–096 一带） | "在成本上，碳交易机制比碳税机制的**信息成本更低**；但在实施成本上，碳交易机制相较于碳税机制并不占据优势。从减排激励效果来看，碳交易机制的有效性高于碳税"；"可以看出，碳交易和碳税机制**各有利弊**"；"碳交易和碳税这两种机制**融合实施**的减排效率和经济效率高于仅仅采用其中一种机制" |
| 分类图 | 全文为经济学综述体裁，**无分类图**（正文按"一、二、三、四"文字分节，PDF 为全角排版，`grep` 一级标题需处理全角空格） |
| 证据等级 | **【已核原文】**（页码为文章起止 93–110；具体引句所在页需按 PDF 页码换算，见第七节未核清单） |

**用途**：如果 4.4.3 要写一句"碳税与碳交易两类工具在文献里长期并列比较"，这是中文侧有页码的出处；且"两种机制融合实施优于单一机制"这句，正好给本文表 12 的组合方案提供中文文献支持——比自己论证"协同"更省事。

---

### S7　Asghari & Mirzapour Al-e-hashem 2021——负面发现 + **本报告推荐的图形皮囊**

| 项 | 内容 |
|---|---|
| 出处 | Asghari M, Mirzapour Al-e-hashem S M J. Green vehicle routing problem: A state-of-the-art review[J]. **International Journal of Production Economics, 2021, 231: 107899.** doi:10.1016/j.ijpe.2020.107899（本地 Zotero `2NPAEYEV`，PDF 全文已读） |
| 类型 | 系统性文献综述，覆盖 2000—2020 年 313 篇 |
| **负面发现（逐词计数，已做抽取器自检）** | 全文 `carbon tax` 命中 **1**、`cap-and-trade` **1**、`subsid` **0**、`incentive` **0**、`toll` **0**、`policy` 11（其中多为 "charging policy"）、`regulation` 3。**该综述没有任何政策工具分类。** 自检：同文件 `Table` 与 `Fig.` 命中数十次、`metaheuristic` 高频，说明抽取正常，上面这些零不是坏工具造成的 |
| 它的分类维度 | **Fig. 2**（p.3），图题逐字："**Conceptual framework used for classifying the green vehicle routing problems.**"——一级 Problem characteristics / Solution methodologies；二级 Types of engines、Objectives、Scenarios、Interacted with traditional VRP、Exact、Heuristic、Metaheuristic；叶子 30 项 |
| 其中与本文直接相关的叶子（逐字） | Types of engines → **Conventional fossil fuel-powered vehicles / Alternative-fuel powered vehicles / Hybrid electric vehicles**；Scenarios → **Uncertain data / Fleet type / Charging policy / Charging/Consumption function / Charger composition** |
| 另一张分类图 | **Fig. 3**（p.4），图题逐字："**Classification of the most common metaheuristics in solving the Green-VRPs.**" |
| 证据等级 | **【已核原文】**（图题、页码、节点名均逐字抄自 PDF；两张图已渲染 PNG 目视核对版式） |

**这一篇同时解决两件事**：①它证实"绿色车辆路径综述里没有政策工具分类"这条不是只有周鲜成 2021 一例，是这一族的共性（与 09-06 报告的结论一致，可以在正文写成一句贡献性表述）；②它的 Fig.2 / Fig.3 是**同领域、同期刊层级、且节点规模与本文可比**的分类图皮囊，见第六节。

---

### S8　周鲜成等 2021——目标期刊的绿色车辆路径综述（负面发现，复用既有取证）

出处：周鲜成, 周开军, 王莉, 刘长石, 黄兴斌. 物流配送中的绿色车辆路径模型与求解算法研究综述[J]. **系统工程理论与实践, 2021, 41(1).** doi:10.12011/SETP2020-2300（Zotero `DTPTHXZV`）

`carbon_policy_instruments_survey_20260906.md` 第一节已做逐词计数并自检：**碳税 0、税 0、补贴 0、碳限额 0、配额 0、政策 0**，而同文件"碳排放"139、"环境"14、"策"15。其分类维度是**目标函数形态**——摘要逐字："将 GVRP 模型分为**油耗/碳排放最小化 VRP、综合成本最小化 VRP 和多目标 VRP** 三种类型"。

**本轮不重复检索，直接复用。** 结论：**目标期刊的这篇综述不能用作政策工具分类的来源**，但它是"这一族综述按什么分类"的直接证据，可以在 4.4.3 开头引一句，说明本文为何要跨领域取分类。

---

### S9　本轮未取到正文的候选（列出来，免得下一位重找）

| 文献 | 为什么值得再试 | 本轮结果 |
|---|---|---|
| Santos G, Behrendt H, Teytelboym A. Part II: Policy instruments for sustainable road transport[J]. Research in Transportation Economics, 2010, 28(1): 46–91.（另有 Part I: Externalities and economic policies in road transport, 同卷 2–45） | 道路交通政策工具综述的经典两篇，一级分类为 physical / soft / knowledge policies（Part II）与 economic instruments（Part I），层级完整 | Cardiff ORCA、Oxford ORA、ScienceDirect 三个入口对本机全部 **403**。**【转述】**，不得进正文 |
| 刘名武, 林强, 王晓斐. 供应链减排运作决策研究现状与发展趋势[J]. 电子科技大学学报(社科版), 2022. doi:10.14071/j.1008-8105(2022)-1001 | 中文综述，按"政府政策强制减排 / 供应链企业间合作减排 / 企业数字化技术赋能减排"三视角组织，正是本文需要的中文一级用词 | 站点 **403**（含 curl 换 UA）。**【转述】** |
| 交通领域减污降碳协同控制研究回顾及展望[J]. 中国环境管理, 2023(2). | 中文"回顾及展望"体裁，含协同控制措施分类 | 站点连接被重置。**【未找到正文】** |
| Moghdani R, et al. The green vehicle routing problem: A systematic literature review[J]. **Journal of Cleaner Production, 2021, 279: 123691.** | 国际绿色车辆路径综述，一级分类维度待核（不是 Omega，见第一节更正） | 正文未取到。**【转述】** |
| Demir E, Bektaş T, Laporte G. A review of recent research on green road freight transportation[J]. European Journal of Operational Research, 2014, 237(3): 775–793. | 公路货运绿色化综述，可能含措施分类 | 正文未取到（付费墙）。**【未核】** |

---

## 三、四篇综述的分类维度不在同一个轴上（这一节必须先看）

| 综述 | 它在给什么分类 | 分类的"被分对象" |
|---|---|---|
| Waltho 2019 | 碳排放政策 | **政府定的碳价规则** |
| Hardman 2017 / 2019 | 电动车激励 | **政府给企业/消费者的钱与权** |
| Albadi & El-Saadany 2007 | 需求响应项目 | **电力公司给用户的价格与合约** |
| 李晓易 2021 | 交通碳减排举措 | **行业要做的事** |
| Asghari 2021 Fig.2 | 绿色车辆路径问题的建模特征 | **企业自己能动的决策变量** |

**所以合并树的一级不是"同一维度的五类"，而是"五个出手方"**：碳价规则、购置端补贴、使用端权利与费用、电价与需求响应、企业自身的路径与充电决策。这一点在正文里要用一句话交代清楚，否则评审会问"为什么把碳税和分时电价并列"。09-06 报告的 A/B/C 三分法（改车队 / 只改充电时刻 / 只平移成本）**是同一批工具的另一种切法**，它按"是否改变决策"切，正好可以作为树的第二个维度（见第六节备选图式，用打点矩阵同时表达两个维度）。

---

## 四、合并树（每个节点标注出处；★＝本文 4.4.3 已实测）

```
配送车队降本减排措施
│
├─【1】碳规制政策  environmental policies
│      分类的**来源**：Waltho, Elhedhli & Gzara 2019, IJPE 208:305–318（摘要逐字：four policies）
│      中文**节点名的来源**：陈婉茹等 2023, SETP 43(11), 表 1, p.3322（列名「碳规制政策」及其取值，已核原文）
│      ├─ 碳税  carbon tax（单位碳价）★ 本文实测 0.075 / 1.0 / 1.2 / 1.5 元·kg⁻¹，另做 0→5 密扫
│      │     中文名出处：陈婉茹等 2023 表 1「碳税」（Yu 等 2021 一行）
│      ├─ 限额碳交易  cap-and-trade（碳限额与交易 / 碳配额）★ 本文实测配额 200 kg
│      │     中文名出处：陈婉茹等 2023 表 1「限额碳交易」（该文本身一行）
│      ├─ 碳限额  carbon cap（硬约束）　○ 未实测
│      │     中文名出处：陈婉茹等 2023 表 1「碳限额」（Islam 等 2021 一行）
│      │     未实测原因：需在可行性检查里加 E_total ≤ cap，落点是受保护文件，改动代价与收益不匹配
│      └─ carbon offset（碳抵消 / 碳补偿）　○ 未实测
│            **中文名无目标期刊先例**：陈婉茹等 2023 全文对「碳补偿」「碳抵消」零命中；
│            可引的中文用词只有丁澍与邱玉琢学位论文摘要的「碳补偿」（Zotero `GIXBUQQZ`，**该条目无 PDF 附件，只有摘要**），
│            英文用词见 Qiu 等 2024 IJPR 62(16) Table 8 的 CO 一行。树上须给这一格加脚注说明
│            未实测原因：目标里与 cap-and-trade 只差一个 max(0,·)；本文配额档位下二者退化为同一式，无新增信息
│
├─【2】购置端财政激励  financial purchase incentives
│      来源：Hardman, Chandan, Tal & Turrentine 2017, RSER 80:1100–1111（四类逐字，见 S2）
│      ├─ Point of Sale Grant Incentives（购车时点补助）★ 本文实测：按购置价差全额补贴、折 24 元/日
│      ├─ VAT and Purchase Tax Exemptions（增值税与购置税减免）　○ 未实测
│      ├─ Post purchase rebates（购后返款）　○ 未实测
│      └─ Income tax credits（所得税抵免）　○ 未实测
│            后三项未实测的共同原因：在本文的日运营模型里，四者都只改变电动车的日均固定成本一个参数，
│            数值相同则解相同；区分它们需要多期购置决策与企业税务结构，超出本文模型边界
│
├─【3】复发性与非财政激励  reoccurring and non-financial incentives
│      来源：Hardman 2019, TR-A 119:1–14（摘要逐字，见 S3）；该文是【2】的明确补集
│      ├─ special lane access（HOV/carpool lanes, bus lanes；对应中国的路权优惠）　○ 未实测
│      ├─ parking incentives（停车优惠）　○ 未实测
│      ├─ charging infrastructure development（充电设施建设）　○ 未实测
│      ├─ road toll fee waivers（通行费减免）　○ 未实测
│      ├─ licensing incentives（牌照优惠）　○ 未实测
│      └─ disincentives: gasoline tax, annual vehicle taxes（燃油税、年度车辆税；同族含低排放区与限行）　○ 未实测
│            本支整体未实测的原因：本文弧行驶时间取自路网矩阵，没有区域属性，也没有"进城一次"的计次逻辑，
│            要测须先改算例的空间结构；已有的对照证据可引 Bruglieri 等 2025 TRE 201:104230（收费倍数多数算例路线不动）
│            与刘长石等 2026 系统科学与数学 46(1):209–228（放开电车服务范围总成本 −14.1%）
│
├─【4】需求响应项目  Demand Response Programs
│      来源：Albadi & El-Saadany 2007, IEEE PES General Meeting: 1–5, **Fig.1「Classification of Demand
│      Response Programs」**（节点名逐字，已核原文）
│      ├─ Price Based Programs (PBP)（价格型）
│      │    ├─ Time of Use (TOU)（分时电价）★ 本文实测：谷段设在午间（河北南网、山东深谷等已实施）
│      │    │     该文原话："The basic type of PBP is TOU rates."；中文出处 `ref:ndrc-tou`、`ref:hebei-tou`
│      │    ├─ Critical Peak Pricing (CPP)　○ 未实测：本文日历为固定时段表，无尖峰事件日
│      │    ├─ Extreme Day CPP (ED-CPP)　○ 未实测：同上
│      │    ├─ Extreme Day Pricing (EDP)　○ 未实测：同上
│      │    └─ Real Time Pricing (RTP)　○ 未实测：本文用固定时段电价 + 逐时碳强度，未做实时价格
│      └─ Incentive Based Programs (IBP)（激励型）
│           ├─ Classical
│           │    ├─ Direct Control（直接负荷控制）　○ 未实测：本文充电时刻由企业决策，无第三方直控
│           │    └─ Interruptible/Curtailable Programs（可中断负荷）　○ 未实测：同上
│           └─ Market Based
│                ├─ Demand Bidding　○ 未实测：本文不参与电力市场报价
│                ├─ Emergency DR　○ 未实测：同上
│                ├─ Capacity Market　○ 未实测：同上
│                └─ Ancillary services market　○ 未实测：同上
│      （若嫌 IBP 一支与配送车队距离过远，可在图上把它整支折叠为一个节点并加"本文不涉及"的注，
│        但不要删掉——删掉就回到"分类列不全"的老问题）
│      ★ 本文另一项实测"午间充电按谷价补贴"**在该综述的分类里没有精确对应节点**——
│        它是对特定时段用电的定向补贴，介于价格型与激励型之间。最接近的文献用词是 Du 等 2025 的"碳普惠"
│        与 Wu, Yücel & Zhou 2022（M&SOM 24(5)，本文 bibitem 已有）的 smart charging 商业模式，两者均非综述。
│        **建议在树上把它画成挂在"价格型"下的一个带虚线框的节点，并在图注写明"该措施在现有综述分类中无对应节点"**——
│        这是本文的一个小贡献点，不要藏起来。
│
└─【5】企业自身的建模决策  problem characteristics（企业侧，不是政府工具）
       来源：Asghari & Mirzapour Al-e-hashem 2021, IJPE 231:107899, Fig.2, p.3（节点名逐字）
       ├─ Types of engines
       │    ├─ Conventional fossil fuel-powered vehicles
       │    ├─ Alternative-fuel powered vehicles
       │    └─ Hybrid electric vehicles
       │      ★ 本文的混合车队（燃油 + 电动）即此支；中文一级用词可借李晓易等 2021 §五（三）"推广应用低碳运输装备"（p.018–019）
       ├─ Fleet type　★ 本文实测：各情形均重新优化车型与车队构成
       ├─ Charging policy　★ 本文实测：充电时刻与充电量重新优化
       ├─ Charging/Consumption function　（本文已建模：非线性充电与分时电价，见 2.2 节，非 4.4.3 的比较项）
       └─ Charger composition　○ 未实测：本文桩型固定 22 kW，未做桩型/桩数扫描
          另：多车场协作配送在本文 4.5 节单独比较，中文用词可借李晓易等 2021 §五（四）"提高运输组织效率"（p.019）
```

**本文 4.4.3 实测措施在树上的位置汇总（5 项单一 + 2 项组合）**

| 本文措施 | 树上位置 | 综述原文节点名 |
|---|---|---|
| 单位碳价 | 1 | carbon tax |
| 碳配额与交易 | 1 | cap-and-trade |
| 电动车购置补贴（折日） | 2 | Point of Sale Grant Incentives |
| 谷段设在午间 | 4 | time-of-use (TOU) |
| 午间充电按谷价补贴 | 4 下的**新增节点** | **综述分类中无对应节点** |
| 组合：谷段午间 + 购置补贴 | 4 + 2 | 跨支组合 |
| 组合：再加碳价 1.2 元·kg⁻¹ | 4 + 2 + 1 | 跨支组合 |

**五支里本文覆盖了四支**（1、2、4、5），完全没碰的是第 3 支（复发性与非财政激励）。这个"四中取一未做"的事实，用图表达出来比用文字辩解更有说服力。

---

## 五、可以直接写进 4.4.3 的一段话（供参考，不是定稿）

> 现有文献对降本减排措施的分类并不在同一维度上：绿色车辆路径的综述按目标函数形态或建模特征分类（周鲜成等 2021；Asghari 和 Mirzapour Al-e-hashem 2021），并不涉及政策工具；绿色供应链网络设计的综述指出该领域主要采用碳限额、碳抵消、碳限额与交易和碳税四类政策（Waltho 等 2019），混合车队配送文献亦按碳限额、碳税与限额碳交易区分（陈婉茹等 2023）；电动车推广侧的两篇综述把激励分为购置时点的财政激励（Hardman 等 2017）与路权、停车、通行费、牌照等复发性与非财政激励（Hardman 2019）；电力侧的综述把用户侧措施分为价格型与激励型需求响应项目，分时电价是价格型中最基本的一种（Albadi 和 El-Saadany 2007）。本文按上述文献的原有名称汇总为图 X，并从中选取与本文问题直接相关的措施进行比较。

（**注**：这段引用了五条新参考文献（Waltho、Hardman ×2、Albadi、Asghari）加两条已有文献（周鲜成待新增、陈婉茹 `ref:23` 已有），完整信息见第七节。周鲜成等 2021 目前不在论文 bibitem 里，需新增。）

---

## 六、图怎么画：皮囊来源与版式规格

### 6.1 先做"是否同类"的判定（本仓库既有规矩，图 3 与图 4 两次翻车都栽在这一步）

| 判定项 | Asghari 2021 Fig.2 | 本文拟画的分类树 | 判定 |
|---|---|---|---|
| 这张图为原作者证明了哪句话 | "我这篇综述用这个框架来组织 313 篇文献"——它是**读者导航图**，不是结果图 | "目前普遍采用的降本减排措施有这些类，本文测了其中哪几个"——同样是**导航图 + 覆盖度声明** | **同类** |
| 对象规模 | 1 根 + 2 一级 + 7 二级 + 30 叶 ≈ **40 个节点** | 1 根 + 5 一级 + 约 8 中间层 + 约 28 叶 ≈ **42 个节点** | **同量级，可移植** |
| 有没有"绝大多数格子为零"的风险 | 无（每个叶子都有文献） | 无（每个叶子都有文献；未实测的叶子照样有文献支撑） | **无** |

**这与图 3、图 4 两次翻车是不同的情形**：那两次的原型对象（常州全市负荷、城市级充电负荷曲线）比本文对象大两个数量级，堆叠柱与曲线画出来绝大多数为零；这次的原型是同一学科、同一期刊层级、节点数同量级的分类框架图，可以直接移植。

### 6.2 推荐皮囊（首选）：Asghari & Mirzapour Al-e-hashem 2021, IJPE 231:107899, **Fig. 2, p.3**

图题逐字："Conceptual framework used for classifying the green vehicle routing problems."

**版式逐项描述（已渲染 PNG 目视核对）**

| 要素 | 规格 |
|---|---|
| 走向 | **横向，左 → 右**，三层（根 / 一级 / 二级 / 叶实为四层） |
| 根节点 | 置于最左，**文字竖排**（旋转 90°）的圆角矩形，高度贯穿整图，宽度很窄 |
| 节点形状 | 全部为**等高圆角矩形**，细蓝色描边（约 0.5 pt），**白色填充**，黑色文字**居中** |
| 同层对齐 | 同一层的节点**左边缘对齐、宽度一致**；叶子节点全部纵向密排于最右一列 |
| 连线 | 从父节点**右边缘中点**出发，先走一小段水平线，再以**直斜线**扇形连到各子节点**左边缘中点**；线为细黑/深灰，无箭头 |
| 留白 | 节点之间纵向间距约等于节点高度的 0.35 倍；无网格、无底色、无阴影、无外框 |
| 字号 | 约 7–8 pt（正文 9–10 pt 的期刊里） |
| 占宽 | 跨栏（本文为单栏则占整页宽），高度约 0.55 页 |

### 6.3 备选皮囊（**本报告更推荐**）：同文 **Fig. 3, p.4**

图题逐字："Classification of the most common metaheuristics in solving the Green-VRPs."

**版式**：左侧是**用大花括号括起的分组类目带**（每组一条淡色底色横带，组内 2–3 行类目名，左侧竖排一个总名"Metaheuristics"）；右侧是**具体算法的竖排列名**（ACO、BCO、DEA…共 15 列，列名竖排）；中间用**圆点**标记"这一类目包含这个算法"；列之间用细虚线分隔。

### 6.3b 第三种可选版式：Albadi & El-Saadany 2007, Fig.1（缩进式大纲树）

同一棵树也可以照 Albadi 的做法画：**纯文字的四级缩进大纲，无方框、无连线、无底色**，只靠缩进量表达层级，最左一行是根名"Demand Response Programs"。优点是极省版面、编译零风险（`itemize` 嵌套即可）、四级层级也不显拥挤；缺点是"图"的观感弱，容易被当成正文列表。**若版面紧张或编译环境保守，这是最稳的一版。**

### 6.3c 三种版式的取舍

| 版式 | 出处 | 能表达 | 占版面 | 施工风险 |
|---|---|---|---|---|
| 带框横向树 | Asghari 2021 Fig.2 | 层级 | 大（约 0.55 页） | forest 包，中等 |
| 类目带 × 打点矩阵 | Asghari 2021 Fig.3 | 层级 + 本文测没测 + 改不改决策 | 中 | tabular 即可，低 |
| 缩进式大纲树 | Albadi 2007 Fig.1 | 层级 | 小 | 极低 |
| （对照）文献总结表 | 陈婉茹等 2023 表 1 | 文献 × 属性 | 中 | 极低，**且是目标期刊现成体裁** |

**为什么推荐打点矩阵**：本文要在图上同时表达**两件事**——①措施属于哪一类（综述分类）；②本文测了哪几个（覆盖度）。Fig.2 的纯树只能表达①，要表达②得靠额外的底色或标记，容易花；Fig.3 的"类目带 × 措施列 + 打点"天然能表达两件事，甚至能表达第三件——09-06 报告的 A/B/C 三分法（改车队 / 只改充电时刻 / 只平移成本）可以做成右侧的第二组列，一张图把"谁分的类""本文测没测""它改不改决策"全说清楚，**且比树更省版面**。

### 6.4 TikZ 画法建议

**首选（Fig.2 式横向树）**：用 `forest` 包最省事。

```latex
\usepackage{forest}
\begin{forest}
  for tree={
    grow'=east,                 % 向右生长
    draw, rounded corners=2pt,  % 圆角矩形
    line width=0.4pt,
    draw=blue!55,               % 细蓝边
    fill=white,
    align=center, font=\scriptsize,
    anchor=west, child anchor=west, parent anchor=east,
    edge={-, line width=0.35pt, black!70},
    edge path'={ (!u.parent anchor) -- ++(4pt,0) |- (.child anchor) }, % 短水平段+折线
    l sep=14pt, s sep=3pt,
    minimum height=13pt, inner xsep=4pt,
  }
  [配送车队\\降本减排措施, rotate=90, anchor=center
    [碳排放政策\\{\tiny Waltho 等 2019}
      [碳税（单位碳价）$\bigstar$] [碳限额与交易$\bigstar$] [碳限额硬约束] [碳抵消] ]
    [购置端财政激励\\{\tiny Hardman 等 2017} ... ]
    ...
  ]
\end{forest}
```

要点：①`grow'=east` + `parent anchor=east / child anchor=west` 复制横向扇形；②`edge path'` 用"短水平段 + `|-`"复制折线连接；③根节点 `rotate=90` 复制竖排根；④未实测节点用 `draw=black!30, text=black!55` 弱化，实测节点加 `$\bigstar$` 或 `line width=0.8pt` 加粗边框；⑤"午间充电按谷价补贴"用 `dashed` 边框表示"综述分类中无对应节点"。

**备选（Fig.3 式类目带 × 打点矩阵）**：用 `tikz` + `matrix of nodes`，或直接用 `tabular` + `\textbullet` 加 `\cline` 与 `\rowcolor`（`xcolor` 的 `table` 选项）实现，比 TikZ 更稳、更容易在期刊模板里过编译。左侧类目带的花括号用 `\draw [decorate, decoration={brace, amplitude=5pt}]`。

### 6.5 图注该写什么（三句以内，照本仓库表注纪律）

建议：`图 X　降本减排措施分类。各分支的类目名称照录相应文献原文：碳规制政策依 Waltho 等[?]，其中文名称依陈婉茹等[?]表 1；购置端财政激励依 Hardman 等[?]；复发性与非财政激励依 Hardman[?]；需求响应项目依 Albadi 和 El-Saadany[?]图 1；企业侧建模特征依 Asghari 和 Mirzapour Al-e-hashem[?]图 2。★ 为本文 4.4.3 实测的措施，虚线框节点在上述文献的分类中无对应节点。`

（三句以内，符合本仓库表注纪律。注意"碳规制政策"这一支的**分类**出自 Waltho 等、**中文名**出自陈婉茹等，是两处来源，图注里必须分开写，不能合成一句。）

---

## 七、未核清单（正文不得假装有）与需新增的参考文献

### 7.1 未核清单

1. ~~Albadi & El-Saadany 的 Fig.1~~——**本轮已补核**：2007 IEEE PES GM 会议版全文已取到，Fig.1 图题与全部节点名逐字核实。期刊版（EPSR 2008）正文仍未取到，若改引期刊版则不得写"见其图 1"。
2. **Waltho 等 2019 的正文**——只取到逐字摘要。四政策的名称可引，**但不得写"见第 X 页表 Y"**，也**不知道该文有无分类图**。
3. **Hardman 2019 的正文**——只取到逐字摘要。六类激励名称可引，**不知道有无分类图**。
4. **Hardman 等 2017 的期刊版页码**——本轮读的是机构报告版（UCD-ITS-RR-17-24 / EVS30），四类激励的原文在报告版 pp.3–4、补集那句在 p.6；**RSER 80:1100–1111 的对应页码未核**。
5. **史丹等 2017 的引句页码**——文章起止 93–110 已核，具体引句所在页需按 PDF 内页码换算，本轮未做。
6. **Santos 等 2010 两篇的一级分类**——三个入口全部 403，只知道 Part II 大致为 physical / soft / knowledge policies【转述】。若要用作第 3 支的上位来源，须换入口重取。
7. **刘名武等 2022 中文综述的三视角分类**——站点 403，【转述】。这是中文侧最贴题的一级用词候选，值得再试（换 IP 或走万方/维普）。
8. **Moghdani 等 2021、Demir 等 2014 的分类维度**——正文均未取到。
9. **"分类图是树状还是矩阵"这一项，七篇里核实了四篇**：Hardman 2017 是国家 × 激励类型的勾选矩阵表；Asghari 2021 是带框横向树（Fig.2）加打点矩阵（Fig.3）；Albadi 2007 是纵向缩进式大纲树（Fig.1）；陈婉茹 2023 是文献总结表（表 1）。Waltho 2019、Hardman 2019、李晓易 2021、史丹 2017 四篇的图形形式**未知或无分类图**。因此第六节的树状皮囊只能取自 Asghari 2021 或 Albadi 2007，**不能说"照某篇碳政策综述的分类图画"**。
10. **丁澍与邱玉琢学位论文（Zotero `GIXBUQQZ`）无 PDF 附件**——只有摘要（"深入探讨了碳限额、碳税、碳交易和碳补偿四种碳规制政策对油电混合车队的影响"）。它是 Qiu 等 2024 的中文前身，其第 1 章文献综述本可给出四个工具的中文定义，但本轮拿不到正文。若要用「碳补偿」这个中文名，须先补到原文。
11. **中文侧的"目标期刊综述"要求**：目标期刊里**确有**按碳政策分类的东西（陈婉茹等 2023 表 1，见 S0），但它出自**研究论文的文献总结表**，不是文献综述；目标期刊唯一的绿色车辆路径**综述**（周鲜成等 2021）已证实无政策分类。本轮拿到的另两篇中文来源里，中国工程科学 23(6) 是工程院战略研究（非严格综述），城市与环境研究 2017(4) 是学术综述但期刊层级低于目标期刊。**"至少一篇来自目标期刊或同级中文期刊的综述分类"这条要求，只能以 S0 的形式部分满足**，见第八节。

### 7.2 需新增的 bibitem（论文现有参考文献里全部没有；格式照 `paper_main.tex` 现行体例）

```latex
\bibitem{ref:waltho2019} Waltho C, Elhedhli S, Gzara F. Green supply chain network design: A review focused on policy adoption and emission quantification[J]. International Journal of Production Economics, 2019, 208: 305--318.

\bibitem{ref:hardman2017} Hardman S, Chandan A, Tal G, et al. The effectiveness of financial purchase incentives for battery electric vehicles -- A review of the evidence[J]. Renewable and Sustainable Energy Reviews, 2017, 80: 1100--1111.

\bibitem{ref:hardman2019} Hardman S. Understanding the impact of reoccurring and non-financial incentives on plug-in electric vehicle adoption -- A review[J]. Transportation Research Part A: Policy and Practice, 2019, 119: 1--14.

\bibitem{ref:albadi2007} Albadi M H, El-Saadany E F. Demand response in electricity markets: An overview[C]//2007 IEEE Power Engineering Society General Meeting. Tampa: IEEE, 2007: 1--5.
% 本报告核实的是这个会议版（Fig.1 分类树）。若期刊惯例不收会议论文，可改引同族期刊版：
% Albadi M H, El-Saadany E F. A summary of demand response in electricity markets[J]. Electric Power Systems Research, 2008, 78(11): 1989--1996.
% 但期刊版正文本轮未取到，引它就不能说"见其图 1"。

\bibitem{ref:asghari2021} Asghari M, Mirzapour Al-e-hashem S M J. Green vehicle routing problem: A state-of-the-art review[J]. International Journal of Production Economics, 2021, 231: 107899.

\bibitem{ref:zhouxc2021} 周鲜成, 周开军, 王莉, 等. 物流配送中的绿色车辆路径模型与求解算法研究综述[J]. 系统工程理论与实践, 2021, 41(1): [起止页待核].
% 注：卷期与 DOI(10.12011/SETP2020-2300) 已核；起止页码本轮未核（Crossref 不收录该刊），
% 成文前须从 PDF 首页或期刊目录补。不要填任何未核的数字。

\bibitem{ref:lixy2021} 李晓易, 谭晓雨, 吴睿, 等. 交通运输领域碳达峰、碳中和路径研究[J]. 中国工程科学, 2021, 23(6): 15--21.

\bibitem{ref:shidan2017} 史丹, 张成, 周波, 等. 碳排放权交易的实践效果及其影响因素：一个文献综述[J]. 城市与环境研究, 2017(4): 93--110.
```

---

## 八、任务要求的达成情况（如实报）

| 任务要求 | 达成 |
|---|---|
| 至少 3 篇综述的分类 | **达成**：Waltho 2019（四政策，摘要逐字）、Hardman 2017（四类财政购置激励，正文逐字）、Hardman 2019（六类复发性/非财政激励，摘要逐字）、Albadi 2007（需求响应完整分类树，**正文与图题逐字**）、Asghari 2021（建模特征框架，正文逐字）、李晓易 2021（五类举措，正文逐字）、史丹 2017（四维度，正文逐字）——**七篇有分类，其中五篇的分类名称已从正文逐字取到** |
| 至少 1 篇来自目标期刊或同级中文期刊 | **部分达成，且这是本任务唯一没能完全满足的条件**。目标期刊的绿色车辆路径综述（周鲜成等 2021, SETP 41(1)）**确无政策工具分类**（逐词计数 + 抽取器自检，复用 09-06 取证）。**替代物已找到**：目标期刊的陈婉茹等 2023（SETP 43(11)）表 1 p.3322 有一列「碳规制政策」，取值为碳限额 / 碳税 / 限额碳交易 / 无——**是目标期刊里现成的碳政策分类与中文用词，但载体是研究论文的文献总结表，不是综述**。建议把"这一族综述没有政策工具分类"写成 4.4.3 的一句话（见第五节示范段落），把它从缺口变成一句可辩护的表述 |
| 每个节点标注来源与页码 | **部分达成**：陈婉茹 2023、Hardman 2017、Albadi 2007、Asghari 2021、李晓易 2021、史丹 2017 有页码/图号/节号；Waltho 2019、Hardman 2019 只有整篇页码范围 |
| 记录分类图的图号与形式 | **部分达成**：陈婉茹 2023 表 1（文献总结表）、Hardman 2017 Table 1（勾选矩阵表）、Albadi 2007 Fig.1（缩进式大纲树）、Asghari 2021 Fig.2/Fig.3（带框横向树 / 打点矩阵）四篇已核；Waltho 2019、Hardman 2019 未知；李晓易 2021、史丹 2017 确认无分类图 |
| 未实测分支保留并说明原因 | **达成**（第四节树上逐条一句） |
| 图形皮囊与画法建议 | **达成**（第六节，含同类判定、版式逐项规格、TikZ 骨架、图注写法） |

---

## 附录：本轮检索式

**Zotero（本地库，子串匹配）**：`综述`（qmode=everything）、`review`、`政策`（qmode=everything）、`policy`。语义检索不可用。

**WebSearch**：
- `Waltho Elhedhli Gzara 2019 "Green supply chain network design" review "policy adoption" emission quantification classification carbon policies`
- `低碳供应链 碳减排政策 研究综述 碳税 碳交易 碳限额 碳补贴 分类 中国管理科学 系统工程理论与实践`
- `Hardman 2017 "review" purchase incentives battery electric vehicles ... classification financial non-financial incentives`
- `Hardman 2018 "Understanding the impact of reoccurring and non-financial incentives ..." escholarship pdf categories`
- `Santos Behrendt Teytelboym 2010 "Part II: Policy instruments for sustainable road transport" ... taxonomy physical soft knowledge fiscal regulation`
- `Demir Bektas Laporte 2014 "A review of recent research on green road freight transportation" ... classification measures pdf eprints`
- `新能源汽车 推广 政策工具 研究综述 分类 供给型 环境型 需求型 补贴 路权 限行`
- `交通运输 碳减排 政策 措施 综述 分类 "交通运输系统工程与信息" OR "中国公路学报" 结构调整 技术减排 管理减排 政策工具`
- `"低碳" 物流 配送 "综述" 政策工具 分类 "命令控制型" "市场激励型" ...`
- `"碳规制" OR "碳政策" 车辆路径 OR 物流 "综述" 分类 碳税 碳限额 碳交易 碳补偿 四种 研究进展 期刊`
- `Albadi El-Saadany "Demand response in electricity markets: An overview" classification figure incentive-based price-based TOU CPP RTP tree`
- `review "time-of-use" electricity pricing electric vehicle charging demand response classification taxonomy ...`

**WebFetch / curl 取回全文**：中国工程科学 23(6) PDF（经 hep.com.cn 302）、城市与环境研究 2017(4) PDF、UC Davis ITS 报告 PDF、多伦多都会大学需求响应综述 PDF、RePEc 两条摘要页。

**Crossref API 核实书目**：`10.1016/j.rser.2017.05.255`、`10.1016/j.tra.2018.11.002`、`10.1016/j.ijpe.2018.12.003`、`10.1016/j.ijpe.2020.107899`、`10.1016/j.epsr.2008.04.002`、`10.1109/PES.2007.385728`、`10.1016/j.ejor.2013.12.033`，以及 Moghdani 2021 的题名检索（更正 Omega → Journal of Cleaner Production）。**Crossref 不收录《系统工程理论与实践》**，该刊条目（周鲜成 2021 的 DOI 10.12011/SETP2020-2300）查无返回，页码须走 PDF 或期刊目录。

**本地 Zotero 全文读取（`zotero_get_attachment_path` + `pdftotext`）**：`2NPAEYEV`（Asghari 2021，另用 `pdftoppm` 渲染第 3、4 页 PNG 目视核对图 2、图 3 版式）、`NKRC4JZU`（陈婉茹等 2023）。`GIXBUQQZ`（丁澍与邱玉琢学位论文）**无附件**，只能读 Zotero 存的摘要。

**逐词计数自检**：Asghari 2021 全文（carbon tax 1、cap-and-trade 1、subsid 0、incentive 0、toll 0）、陈婉茹 2023 全文（碳交易 65、碳价 17、碳限额 12、限额碳交易 8、碳税 1、碳补偿 0、碳抵消 0）。两次均先用文件里已知高频的词试过抽取器，零命中不是坏工具造成的。

**403 / 反爬（本机不可达）**：`social.uestc.edu.cn`、`zghjgl.ijournal.cn`、`orca.cardiff.ac.uk`、`orca.cf.ac.uk`、`ora.ox.ac.uk`、`sciencedirect.com`、`researchgate.net`。
