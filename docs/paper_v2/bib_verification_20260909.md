# 参考文献逐条核验台账（2026-09-09）

核验对象：`docs/paper_v2/paper_main.tex` 的 `thebibliography`（50 条）。
产物：本文件 + `docs/paper_v2/bib_verified_block.tex`（改正后的完整文献表，键序不变）。
本轮**未改动** `paper_main.tex`（正文另有代理在改）。

## 0. 格式依据与体裁缺口

著录体例的权威来源是期刊骨架
`docs/paper_gci_dmm_vrp_20260804/paper_template_setp_20260812/paper_template.tex`，它只给了四类模板：

- 中文期刊：`中文作者. 题名[J]. 刊名, 年, 卷(期): 起页--止页.` + 紧随一行英文对照；
- 外文期刊：`Author. Title[J]. Journal, year, volume(issue): start--end.`；
- 专著：`作者. 书名[M]. 出版地: 出版者, 年.`；
- 网络资源：`责任者. 题名[EB/OL]. 发布日期[引用日期]. 网址.`

**模板不含 DOI 字段**，因此本表一律不写 DOI（DOI 只作为本文件的核验证据）。
标点按模板（逗号后留空格、页码用 `--`），不采用陈雨蝶那篇里“逗号不空格”的排印习惯——
该样板自身前后不一致（“等”前有无逗号两种写法并存、[17] 与 [23] 同一篇重复著录），
只作超三作者用「等 / et al.」这一条规则的旁证。

模板未覆盖的六条，按 GB/T 7714 补齐（**这是本轮的格式来源声明，不是期刊明文规则**）：
`ref:osrm`（[C]）、`ref:changjiang2024` 与 `ref:mee2025`（[R]）、`ref:71`（[D]）、
`ref:14`（[M]// 析出文献）、`ref:75`（arXiv 预印本按 [EB/OL]）。

超三作者截断规则（前三 + 等 / et al.）已逐条复核，50 条全部符合，无一条错截或漏截。

## 1. 逐条结论

证据方式记号：**Z**=Zotero 条目；**CR**=CrossRef API 实取；**PUB**=出版方/期刊官网页面实取；
**GOV**=政府门户原页实取；**arXiv**=arXiv abs 页实取。
上一轮 `reference_audit_20260831.md` 的结论**不作为本轮证据**，本表每条都重新取证。

| key | 结论 | 证据 | 改动字段 |
|---|---|---|---|
| ref:tdf1555 | VERIFIED | GOV gov.cn/zhengce/content/202607/content_7074826.htm（题名、国发〔2026〕22号、2026年07月09日 逐字符合） | — |
| ref:wlw2026 | VERIFIED | GOV zfxxgk.ndrc.gov.cn id=20659（题名、发改经贸〔2026〕1241号、2026年8月18日 符合） | — |
| ref:6 | VERIFIED | Z `R4MW8E32`；PUB sysengi.cjoe.ac.cn/EN/10.12011/SETP2019-1371（41(4):995-1009，英文题名逐字一致） | — |
| ref:23 | VERIFIED | Z `NKRC4JZU`；PUB /EN/10.12011/SETP2022-2971（43(11):3320-3335，英文题名逐字一致，4 作者→等） | — |
| ref:qiu2024 | VERIFIED | CR 10.1080/00207543.2023.2296017（IJPR 62(16):5720-5736；3 作者全列） | — |
| ref:bruglieri2025 | VERIFIED | CR 10.1016/j.tre.2025.104230（TR-E 201:104230，5 作者→et al.） | — |
| ref:gao2025 | **CORRECTED** | Z `M53I5HBR`；PUB zgglkx.com/CN/10.16381/j.cnki.issn1003-207x.2022.1252 | 英文题名：原“Policy effects of urban delivery fleet renewal considering electric vehicle configuration and routing optimization”→官方“Effects analyses of delivery fleet renewal policies considering electric vehicle deployment and routing optimization”。中文题名/卷期页/作者无误 |
| ref:dantzig | VERIFIED | CR 10.1287/mnsc.6.1.80（Management Science 6(1):80-91, 1959） | — |
| ref:27 | VERIFIED | CR 10.1016/j.ejor.2015.01.049（EJOR 245(1):81-99） | — |
| ref:45 | VERIFIED | CR 10.1016/j.trc.2016.01.013（TR-C 65:111-127） | — |
| ref:montoya | VERIFIED | CR 10.1016/j.trb.2017.02.004（TR-B 103:87-110；4 作者→et al.） | — |
| ref:12 | VERIFIED | CR 10.1287/trsc.2021.1111（Transportation Science 56(2):460-482；4 作者→et al.） | — |
| ref:zhou2026 | **CORRECTED** | Z `KTUD9BPC`；PUB zgglkx.com/CN/10.16381/j.cnki.issn1003-207x.2023.1103 | 英文题名：原“Time-dependent electric vehicle routing model considering …”→官方“Research on time dependent electric vehicle routing model with nonlinear energy consumption and an improved whale optimization algorithm”。34(3):214-225 与 5 作者→等 均无误 |
| ref:deng | VERIFIED | CR 10.1016/j.trd.2022.103333（TR-D 109:103333；4 作者→et al.） | — |
| ref:shi2025 | VERIFIED | CR 10.1016/j.eswa.2025.126875（ESWA 273:126875） | — |
| ref:52 | VERIFIED | CR 10.1016/j.trd.2024.104383（TR-D 135:104383, 2024） | — |
| ref:du2025 | VERIFIED | CR 10.1016/j.apenergy.2025.126196（Applied Energy 397:126196, 2025） | — |
| ref:martin2025 | VERIFIED | CR 10.1038/s41467-025-64979-7（Nature Communications 16, 文章号 10150, 2025） | — |
| ref:44 | VERIFIED | CR 10.1016/j.tre.2020.101866（TR-E 135:101866；5 作者→et al.） | — |
| ref:sahin | VERIFIED | CR 10.1287/trsc.2022.1146（Transportation Science 56(6):1636-1657） | — |
| ref:zhao2024 | VERIFIED | CR 10.1016/j.ejor.2024.04.011（EJOR 317(3):921-935；4 作者→et al.） | — |
| ref:49 | VERIFIED | CR 10.1016/j.ejor.2017.08.051（EJOR 265(3):1078-1093） | — |
| ref:7 | VERIFIED | CR 10.1016/j.eswa.2023.119654（ESWA 219:119654；6 作者→et al.） | — |
| ref:wang2024 | VERIFIED | CR 10.1016/j.tre.2024.103798（TR-E 192:103798） | — |
| ref:8 | VERIFIED | CR 10.1016/j.ijpe.2022.108669（IJPE 255:108669, 2023） | — |
| ref:91 | VERIFIED | Z `UIVEWQC2`；PUB /EN/10.12011/SETP2021-3282（42(10):2721-2739，英文题名逐字一致，4 作者→等） | — |
| ref:14 | VERIFIED | TRID 记录 309530（Golden & Assad 编 *Vehicle Routing: Methods and Studies*, Studies in Management Science and Systems 16, North-Holland/Elsevier, Amsterdam, 1988: 223-248） | — |
| ref:18 | VERIFIED | Z `R7NZFUZC`；PUB zgglkx.com/CN/10.16381/j.cnki.issn1003-207x.2019.1495（30(8):254-266，英文题名一致） | — |
| ref:51 | VERIFIED | Z `GKCQ5LXR`；PUB /EN/10.12011/SETP2023-0524（44(7):2362-2380，英文题名逐字一致） | — |
| ref:71 | **UNVERIFIABLE** | 见 §2 | 不动 |
| ref:mardesic2024 | VERIFIED | CR 10.3390/math12010028（Mathematics 12(1):28；4 作者→et al.） | — |
| ref:shahbazian2025 | VERIFIED | CR 10.1016/j.cor.2025.107217（C&OR 184:107217, 2025；4 作者→et al.） | — |
| ref:94 | VERIFIED | CR 10.1016/j.cor.2025.107374（C&OR 189:107374，**期次年份 2026-05**；DOI 里的 2025 是收录年，年份未漂移） | — |
| ref:95 | **CORRECTED** | Z `HADEF6XR`；PUB kzyjc.alljournals.cn/html/2026/5/2025-0435.htm（41(5):1338-1347, 2026） | 英文题名：原“Distribution routing optimization for oil-electric hybrid fleets from a low-carbon perspective”→官方“Optimization of distribution paths for hybrid fuel-electric fleet under low-carbon perspective” |
| ref:76 | VERIFIED | CR 10.1287/opre.1120.1048（Operations Research 60(3):611-624；5 作者→et al.） | — |
| ref:77 | VERIFIED | CR 10.1016/j.ejor.2013.09.045（EJOR 234(3):658-673；4 作者→et al.） | — |
| ref:hgs-cvrp-2022 | VERIFIED | CR 10.1016/j.cor.2021.105643（C&OR 140:105643, 2022，单作者） | — |
| ref:64 | VERIFIED | CR 10.1287/ijoc.2023.0055（IJOC 36(4):943-955, 2024） | — |
| ref:changjiang2024 | **UNVERIFIABLE** | 见 §2 | 不动 |
| ref:bj-tou | **CORRECTED** | GOV fgw.beijing.gov.cn/…/t20230821_3718725.htm（页面加载正常） | 补文号「京发改规〔2023〕11号」（原缺）；补引用日期 [2026-09-09]。发布日期 2023-08-21 属实（成文 2023-08-18，施行 2023-09-01） |
| ref:bj-fee | **CORRECTED** | GOV beijing.gov.cn/…/t20190522_58449.html（页面加载正常，京发改〔2015〕848号） | 文号从题名括号内移出为独立字段（对齐模板）；日期 2015-04-24（成文）→2015-05-08（发布日期，页面标注）；补引用日期。**另见 §2 的时效性提示** |
| ref:mee2025 | VERIFIED | GOV mee.gov.cn/ywgz/ydqhbh/wsqtkz/202509/t20250927_1128352.shtml（2025-09-24 于中国碳市场大会发布，报告封面署“中华人民共和国生态环境部 二○二五年九月”） | — |
| ref:zhang2025 | VERIFIED | CR 10.1371/journal.pone.0318432（PLoS ONE 20(2):e0318432, 2025） | — |
| ref:osrm | VERIFIED | CR 10.1145/2093973.2094062（ACM SIGSPATIAL GIS '11: 513-516） | — |
| ref:82 | VERIFIED | CR 10.1038/s41597-026-07272-6（Scientific Data 13, 文章号 926, 2026；8 作者→et al.） | — |
| ref:75 | **CORRECTED** | arXiv abs/2605.05208（题名与两位作者逐字一致，Submitted on 24 Feb 2026） | 补 URL 与 (发布日期)[引用日期]，对齐 [EB/OL] 模板 |
| ref:74 | VERIFIED | CR 10.1016/j.cor.2012.07.018（C&OR 40(1):475-489, 2013；4 作者→et al.） | — |
| ref:woody2021 | VERIFIED | CR 10.1021/acs.est.1c03483（ES&T 55(14):10108-10120；5 作者→et al.） | — |
| ref:ndrc-tou | **CORRECTED** | GOV ndrc.gov.cn/xxgk/zcfb/tz/202107/t20210729_1292067.html（页面加载正常） | 补 URL（原条目完全没有网址，不满足 [EB/OL] 模板）；日期 2021-07-26（成文）→2021-07-29（发布），与 bj-tou、tdf1555 统一用发布日期；补引用日期 |
| ref:hebei-tou | **CORRECTED（附保留意见）** | 石家庄市府转发页 sjz.gov.cn（题名+冀发改能价〔2022〕1364号）与临漳县转发页 linzhang.gov.cn（成文 2022年10月28日、2022年12月1日起执行）双源互证 | 日期 2022-12-01（执行日）→2022-10-28（成文日）；补省厅原页 URL 与引用日期。**保留意见见 §2** |

小计：**41 条 VERIFIED、7 条 CORRECTED、2 条 UNVERIFIABLE、0 条 SUSPECT**。
未发现任何幻觉条目（题名—作者—刊名—卷期页错配为零）。

## 2. UNVERIFIABLE / 需用户裁决的条目

### (1) ref:71 邱莹莹 学位论文 —— UNVERIFIABLE，**建议优先处理**

- 条目声称：邱莹莹.《低碳背景下考虑动态需求的混合车队物流配送路径问题研究》[D]. 上海: 上海理工大学, 2024.
- 已做的检索：Zotero 全库（只查到该作者两篇期刊论文，**没有学位论文条目**）、
  按论文全名做全网检索（零命中）、按“作者+导师+学校+年份”检索（零命中）。
- Zotero 里同作者可确证的是：邱莹莹, 干宏程. 低碳背景下混合车队车辆路径优化研究[J].
  重庆工商大学学报（自然科学版）, 2024, 41(6): 114-120（item key `4U7I5H4P`，
  DOI 10.16055/j.issn.1672-058X.2024.0006.015）。该文用粒子群求静态混合车队路径，
  **不含动态需求**。
- 为什么要紧：这条不是装饰性引用，它承载了正文四处方法出处
  （表里的“邱莹莹”一行、动态阶段“保留既有成本并重新规划”的结构、
  “定时与定量联合批处理策略”、动态事件类型设定）。
- 三个处理选项：
  1. **查证后保留**（推荐）：在 CNKI/万方按作者名调出该学位论文，把题名、年份、
     学校逐字回填；若题名与现稿不同，以库里的为准。
  2. **换源**：若学位论文不存在，则“定时/定量联合触发”“保留既有成本重规划”
     需另找有页码支持的出处（现有 `ref:18`、`ref:51` 都是动态 VRP 的可用替代，
     但它们支持的是重规划时刻设定与多车型动态，**不覆盖批处理触发**），
     不能直接把重庆工商大学那篇顶上去（它没有动态需求）。
  3. **删引**：若两条都办不到，则表格该行与四处引用一并删除，方法描述改为本文自设。

### (2) ref:changjiang2024 长江证券研报 —— UNVERIFIABLE

- 条目声称：邬博华, 曹海花, 叶之楠.《经济性驱动，新能源轻重卡兑现爆发式增长》[R]. 武汉: 长江证券研究所, 2024: 5.
- 可证的部分：邬博华、曹海花、叶之楠确为长江证券研究所新能源与电力设备团队研究员
  （新浪财经分析师榜单、百度百科词条均可查）。
- 不可证的部分：**该篇研报的题名、年份、页码 5 均未找到任何公开落点**；
  券商研报通常只在付费终端（Wind/choice/慧博）分发，没有稳定公开页。
- 为什么要紧：它是电动车购置价差与电池价格两个成本参数的唯一出处（正文两处）。
- 两个处理选项：
  1. **补公开落点**：把手上的 PDF 首页信息（完整报告名、发布日期、页码）逐字回填，
     并在条目末尾给一个能打开的公开链接（慧博/研报网的该篇页面）。
  2. **换源**：改引可公开核对的价格来源（如中汽协/中国汽车流通协会年度报告、
     电池价格用 BNEF 或真锂研究的公开年度均价），同一句话照样成立。

### (3) ref:hebei-tou 的保留意见

题名与文号已被两个市级政府转发页双源确证，成文日期 2022-10-28 亦然。
但**省厅原页 `info.hebei.gov.cn/...` 在本机始终连不上（curl 与抓取工具均超时）**，
无法亲自确认该链接可打开。请在定稿前手动点一次；若打不开，改用石家庄市府转发页
`https://www.sjz.gov.cn/zfxxgk/columns/e227fca7-4fc2-4423-91cd-6f8b0162ec3d/202401/12/8337de24-ce4a-402b-97ca-7f432dc7f5f7.html`。
另：该文件已于 2025-10-01 被河北南网新的分时电价优化调整政策取代——正文写的是
“山东、河北等省份已将谷段调整至午间”，属历史事实陈述，可以不改；但若要写“现行”，需换新文件。

### (4) ref:bj-fee 的时效性提示（不影响著录正确性）

北京市政府页面在“有效性”一栏标注**否**（京发改〔2015〕848号已失效）。
条目本身字段全部属实，属 VERIFIED/CORRECTED；但正文第 877 行用它作
“**本市规定的上限**”的依据（现在时），与失效状态不符。
建议二选一：把句子改成“低于该文件当年规定的上限”，或改引现行的北京充电服务费文件。

## 3. 引用—文献闭环检查（2026-09-09 快照）

- `paper_main.tex` 全文只用 `\cite{}` 一种形式（`\citep`/`\citet`/`\cite[...]{}` 零命中）。
- `\cite` 键去重后 **50 个**，`\bibitem` 键 **50 个**，**双向零差集**：无孤儿文献、无悬空引用。
- ⚠️ 这是快照。核验期间 `paper_main.tex` 行数从 1679 变为 1646（正文另有代理在改），
  文献表本身未动。**合稿后必须重跑一次这个比对。**

### 同一来源既进文献表又在正文裸给网址（用户要求一源一形）

| 位置 | 情况 | 判断 |
|---|---|---|
| 第 882 行 `\cite{ref:zhang2025}（figshare 28113608）` | 引的是 PLoS ONE 论文，裸网址指向该文配套的 figshare **数据集** | **不算重复**：论文与数据集是两个不同对象，学界惯例就是这样并给。若仍想统一，把数据集网址移到脚注 |
| 第 884 行 `\cite{ref:82}（figshare 28953545）` | 同上，Scientific Data 论文 + 其数据集 | 同上 |
| 第 875/878/879/883 行的裸网址（江淮 K7、福田智蓝、国家能源局充电桩、北京 0 号柴油价、OpenStreetMap） | 只在正文出现，未进文献表 | 合规，且与陈雨蝶那篇“数据源/算例库用括号内网址就地给出、不进文献表”的做法一致 |

结论：**没有真正的一源两形违规**。

## 4. 其他已核但未改的格式细节

- 中英对照行之间用 `\newline`（模板写的是 `\\`）。两者排版输出相同，而 `\\` 在
  `\bibitem` 里更容易出问题，故保留 `\newline`。
- `ref:martin2025`、`ref:82` 用“卷: 文章号”而不写期号，与 CrossRef 记录一致
  （Nature Communications 16(1)、Scientific Data 13(1) 的期号无检索价值），
  与样板里“Heliyon, 2021, 7(9)”这类无卷号条目属同一类容差。
- `ref:qiu2024` 的 CrossRef 上线日期是 2023-12-20，但正式期次为 2024 年 62(16)，
  条目写 2024 正确。
- `ref:mardesic2024` 上线 2023-12-21，MDPI 期次为 Mathematics 12(1)（2024 年 1 月），
  条目写 2024 正确。
