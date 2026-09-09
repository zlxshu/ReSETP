# 四条不完整参考文献的溯源与补全（2026-09-09）

只读追溯，未改动任何文件。行号以 `docs/paper_v2/paper_main.tex`（md5 `8943afbb2a11888e50d7841872e50ac9`，1677 行）为准。
追溯期间该文件被另一处会话改动过一次（同一批行号先后为 878/879 与 876/877），引用行号前请先核 md5。

核实日期统一记为 2026-09-09。凡未能自己打开原文页面核到的字段，一律标 **【未核实】**，不猜。

---

## 一、ref:ndrc-tou —— 国家发改委 分时电价机制通知（缺 URL）

### a. 现状与引用处

`:1671`
```
\bibitem{ref:ndrc-tou} 国家发展改革委. 关于进一步完善分时电价机制的通知[EB/OL]. 发改价格〔2021〕1093号. (2021-07-26).
```

唯一引用处 `:1211`：
> 1）分时电价与电网碳强度在时段上错开。北京现行分时电价依据《关于进一步完善分时电价机制的通知》\cite{ref:ndrc-tou}由北京市发展和改革委员会按电网负荷划定\cite{ref:bj-tou}，

它支撑的是**制度来源**（北京时段划分的上位依据），不承担任何数值。

### b. 数据如何进入项目

不承担数值，仓库内无对应数值落点。`grep "1093号"` 在 `solver/`、`data/`、`docs/paper_v2/` 内零命中；该文号只出现在 tex 参考文献里。

### c. 线上核实

已打开 <https://www.ndrc.gov.cn/xxgk/zcfb/tz/202107/t20210729_1292067.html> 并逐项核对：

| 字段 | 页面实际值 | 与现有 bibitem 是否一致 |
|---|---|---|
| 标题 | 关于进一步完善分时电价机制的通知 | 一致 |
| 文号 | 发改价格〔2021〕1093号 | 一致 |
| 发文机关 | 国家发展改革委 | 一致 |
| 成文日期 | 2021年7月26日 | 一致（现有 bibitem 的 2021-07-26 是成文日期） |
| 网页发布日期 | 2021/07/29 | bibitem 未写 |

结论：只缺 URL，其余字段全对。

### d. 补全后的 \bibitem

```latex
\bibitem{ref:ndrc-tou} 国家发展改革委. 关于进一步完善分时电价机制的通知[EB/OL]. 发改价格〔2021〕1093号. (2021-07-26)[2026-09-09].
\url{https://www.ndrc.gov.cn/xxgk/zcfb/tz/202107/t20210729_1292067.html}.
```

---

## 二、ref:hebei-tou —— 河北南网工商业分时电价通知（缺 URL）

### a. 现状与引用处

`:1673`
```
\bibitem{ref:hebei-tou} 河北省发展和改革委员会. 关于进一步完善河北南网工商业及其他用户分时电价政策的通知[EB/OL]. 冀发改能价〔2022〕1364号. (2022-12-01).
```

两处引用：

- `:1213`：「山东、河北等省份已将谷段调整至午间\cite{ref:hebei-tou}。」——支撑「午间谷段在中国已有先例」这个事实性判断。
- `:1246`：「谷段设在午间参照河北的做法\cite{ref:hebei-tou}，电价数值不变，低谷时段为1:00--6:00与12:00--15:00；」——支撑本文反事实情景的**时段取值**。

### b. 数据如何进入项目

反事实日历（把谷段搬到午间）由脚本生成，不是从河北文件抄电价：

- `solver/scripts/build_counterfactual_tariff_calendar.py:724`：「**这是构造情景，不是任何一份现行电价文件。** 北京现行分时电价的时段结构……」
- `solver/scripts/build_policy_class_table.py:298`：表里那一行的标签直接写成 `r"河北南网分时电价\cite{ref:hebei-tou}"`，配 `set_midday`。
- 产物：`data/ChinaInstances/china81_cf_calendar_midday_valley_v1_20260904/`（含 `README.md` 与 `tariff_carbon_hourly_calendar.csv`）。

即：**电价数值仍是北京的，只借河北的时段形状**，与正文 `:1246`「电价数值不变」一致，口径自洽。

### c. 线上核实

- 已打开并核到文号与发文机关：<https://fgw.cangzhou.gov.cn/fgw/c101713/202403/f236865498a447aabe5b3f38f66e85db.shtml>（沧州市发改委转载页，标题即《关于进一步完善河北南网工商业及其它用户分时电价政策的通知》（冀发改能价〔2022〕1364号）；正文以图片形式呈现，时段文字不可抽取）。
- 已打开并核到「省文文号 + 转发」：<https://www.sjz.gov.cn/zfxxgk/columns/e227fca7-4fc2-4423-91cd-6f8b0162ec3d/202401/12/8337de24-ce4a-402b-97ca-7f432dc7f5f7.html>（石家庄市发改委转发件）。
- 河北省政府信息公开原文页 `http://info.hebei.gov.cn/hbszfxxgk/329975/329988/330035/6852718/7041023/index.html` 在搜索结果中存在，但本机 WebFetch 报 Socket closed、curl 无 DNS（本机对该域名根本解析不了）。**工具打不开不等于页面不存在**，故该 URL 标【未核实】，不作推荐首选。

时段核对（与正文 `:1246` 完全吻合）：低谷 1—6 时、12—15 时；平段 0—1 时、6—12 时、15—16 时；高峰 16—24 时（冬季 16—17、19—24，尖峰 17—19）；平段基础上峰谷各上下浮 70%，尖峰在高峰上浮 20%；自 2022 年 12 月 1 日起执行。
（该时段表来自检索结果转述与多处地市转发页，**未从省级原文 PDF 逐字核到**，标【部分未核实】。）

日期存在冲突，不擅自选一个：

| 来源 | 日期 |
|---|---|
| 沧州市发改委转载页 | 2022-11-03 |
| 石家庄转发件 | 2022-11-07 |
| 现有 bibitem | 2022-12-01（这是**执行日期**，不是发布日期） |

### d. 补全后的 \bibitem

```latex
\bibitem{ref:hebei-tou} 河北省发展和改革委员会. 关于进一步完善河北南网工商业及其他用户分时电价政策的通知[EB/OL]. 冀发改能价〔2022〕1364号. (2022)【发布日期未核实，2022-12-01为执行日期】[2026-09-09].
\url{https://fgw.cangzhou.gov.cn/fgw/c101713/202403/f236865498a447aabe5b3f38f66e85db.shtml}.
```

省级原文 URL【未核实】；若能在河北省发改委域名下核到原文页，应换成该 URL 并把发布日期一并补实。

---

## 三、ref:bj-tou / ref:bj-fee —— 北京两份（均缺访问日期）

两条都缺访问日期，故一并处理。

### a. 现状与引用处

`:1651`
```
\bibitem{ref:bj-tou} 北京市发展和改革委员会. 关于进一步完善本市分时电价机制等有关事项的通知[EB/OL]. (2023-08-21).
\url{https://fgw.beijing.gov.cn/fgwzwgk/2024zcwj/bwgfxwj/202308/t20230821_3718725.htm}.
```
`:1654`
```
\bibitem{ref:bj-fee} 北京市发展和改革委员会. 关于本市电动汽车充电服务收费有关问题的通知（京发改〔2015〕848号）[EB/OL]. (2015-04-24).
\url{https://www.beijing.gov.cn/zhengce/zhengcefagui/201905/t20190522_58449.html}.
```

引用处：

- `:876`：「车场与公共站充电功率按现行直流快充枪的常见功率取60 kW（\url{...nea.gov.cn...}）；**分时电价采用北京现行时段与电价**\cite{ref:bj-tou}，」
- `:877`：「……公共充电站按车场同一价目计费并加收服务费，**服务费0.40元/kWh低于本市规定的上限**\cite{ref:bj-fee}；」
- `:1211`：「……由北京市发展和改革委员会按电网负荷划定\cite{ref:bj-tou}，低谷时段为23:00--07:00；」
- 表 5（`:904`、`:906`）：车场/公共站充电功率各 60.0；**车场电价（谷/平/峰，元/kWh）0.5633/0.8364/1.1486**；**公共站服务费 0.4**。

### b. 数据如何进入项目（这一节是本次追溯的主要发现）

**三档电价的真实出处不是 ref:bj-tou，而是一份 2025 年 2 月的北京电网销售电价表镜像。**

链条按顺序：

1. `data/ChinaPrices/china_2025_02_tariff_register_v2.json`
   - `/one_to_ten_kv_candidate_rows/beijing/single_part` = `peak 1.14862175 / flat 0.83644275 / valley 0.56328575`（另有两部制 `0.88707675/0.65294275/0.41880875`，未采用）
   - `/sources/beijing/archive_page` = `https://energydc.cn/policy/beijing/2025-02/6b885a88-d1dd-11f0-9e8e-46a1f660a16d`（**第三方数字档案镜像**）
   - `/sources/beijing/api_file` = `data/ChinaPrices/official_snapshots/china_2025_02_nine_city/beijing_2025_02_api.json`（sha256 `cc8d3fbe…`）
   - `/sources/beijing/scan_file` = 同目录 `beijing_2025_02.webp`（sha256 `a77e05e7…`）
   - `/source_strength` = `third_party_digital_archive_of_grid_original_scans`
   - `/source_boundary` 原文：档案图片可见国网/南网出版方标识，**原始供电公司 URL 仍然欠缺**（"Original utility URLs remain desirable"）
   - `/formal_row_rule`：主情景假定为 1–10 kV、100 kVA 以上 315 kVA 以下**单一制**用户，按 发改价格〔2023〕526号 行使选择权，**必须标为情景而非已核实的车场合同**
2. `docs/handoff/china_nine_city_electricity_price_closure_v2_20260718.md:13` 登记北京三档 `1.14862175/0.83644275/0.56328575`；`:31` 给北京的判定是 **`PASS_CURRENT_SCAN_MIRROR_OFFICIAL_URL_PENDING`** ——「国网原表扫描件已封存，但当前只找到第三方数字档案镜像，尚缺国网原始发布 URL」。同文件 `:43` 把 fgw.beijing.gov.cn 的 2023 分时政策页只列为「**分时政策**」，与价表并列而非合一。
3. `baselines/china_instances/build_china_stage2_static_inputs_20260718.py:185-186` 生成 48 槽日历：
   ```python
   "depot_energy_cny_per_kwh": prices[label],
   "public_energy_cny_per_kwh": prices[label],
   "public_service_fee_cny_per_kwh": 0.4,
   "public_total_cny_per_kwh": round(float(prices[label]) + 0.4, 9),
   ...
   "service_fee_class": "UNIFORM_SCENARIO_PROXY_NOT_MARKET_OBSERVATION",
   ```
   同文件 `:280`：`"public": {"power_kw": 60.0, "gun_count": 1, "service_fee_cny_per_kwh": 0.4}`，整块标 `UNIFORM_PREDECLARED_SCENARIO_PROXY`。
4. `data/ChinaInstances/china81_stage2_static_inputs_corrected_v3_20260723/metadata.json` 记 `repair_builder` 与 `input_hashes.tariff_register`；产物 `tariff_carbon_hourly_calendar.csv` 首行即 `beijing,jjj,2025-02-01,1,0,valley,0.56328575,0.56328575,0.4,0.96328575,...`。
5. `solver/src/setp_solver/china81.py:1099`、`:1168-1176` 读入 `public_service_fee_cny_per_kwh` 与 `service_fee_class`；`:1274` `depot_charge_power_kw=60.0`。
6. `solver/src/setp_solver/cost.py:1382-1409` 取价：车场取 `depot_energy_cny_per_kwh`，站取 `public_total_cny_per_kwh`（＝电能价＋0.4）。

正文表 5 的四位小数正是登记表八位值的四舍五入：`0.56328575→0.5633`、`0.83644275→0.8364`、`1.14862175→1.1486`。链条闭合。

**关于 0.40 服务费的仓库内唯一出处**：`docs/handoff/china_policy_scenario_contract_20260717.md:50`
> 自有/公共充电服务费 | 0/0.42元/kWh | 0.42为2024年上海公共场站中位数；1.30元/kWh只作政府指导上限情景

即 **0.4 是把上海 2024 年中位数 0.42 取整后套到北京**，与北京任何文件无关。`docs/handoff/public_station_modeling_audit_20260908.md:115-116` 已把这一条写死：
> `public_service_fee_cny_per_kwh = 0.4` … 仓库内可追到的唯一来源：`china_policy_scenario_contract_20260717.md:50`……即 **0.4 是把上海 2024 中位数取整后套到北京**
> 北京公共充电服务费**政府指导上限**的官方文号 | **未核**。仓库里只有上海口径（0.42 中位 / 1.30 指导上限），**没有找到北京市发改委关于充电服务费上限的原文或快照**

同审计 `:113` 另把「公共站电能价 ≡ 车场电能价」列为本次审计判定的最核心无出处项（C 级）。

（60 kW 不在本次四条之列，一句带过：车场 60 kW 有出处（`docs/handoff/depot_charging_power_evidence_20260811.md`，咸宁市发改委专项规划等 37 台设备台数中位），公共站 60 kW 被同一份审计判为无出处；正文 `:876` 引的 nea.gov.cn 链接与仓库取证不是同一条线。）

### c. 线上核实

**ref:bj-tou**（已打开 <https://fgw.beijing.gov.cn/fgwzwgk/2024zcwj/bwgfxwj/202308/t20230821_3718725.htm>）：

| 字段 | 页面实际值 |
|---|---|
| 标题 | 北京市发展和改革委员会关于进一步完善本市分时电价机制等有关事项的通知 |
| 文号 | **京发改规〔2023〕11号**（现有 bibitem 未写） |
| 成文日期 | **2023年8月18日**（现有 bibitem 写的 2023-08-21 是网页发布日期） |
| 施行日期 | 2023年9月1日 |
| 时段 | 高峰 10:00–13:00、17:00–22:00；平段 7:00–10:00、13:00–17:00、22:00–23:00；低谷 23:00–次日 7:00；尖峰 夏季 11:00–13:00、16:00–17:00，冬季 18:00–21:00 |
| 是否含元/kWh 绝对价 | **否。只有比例（如高峰在平段基础上上浮 71%），全文不含 0.5633 / 0.8364 / 1.1486** |

低谷 23:00–07:00 与正文 `:1211` 一致；时段这一半，ref:bj-tou 是对的。

**电价那一半对不上，且可以算死**：本文三档的实际比值为 峰/平 = 1.3732、谷/平 = 0.6734，与该通知的 ±71% 对不上（因为浮动只作用于**电度电价分量**，而登记表里的 8 位数是含输配、政府性基金等在内的到户价）。所以正文 `:876`「分时电价采用北京现行时段与**电价**\cite{ref:bj-tou}」中的「电价」二字**没有被 ref:bj-tou 支撑**；真正含这三个数的文件是 2025 年 2 月北京电网（1–10 kV 单一制工商业）销售电价表，仓库只持有第三方镜像与扫描件哈希，**国网原始发布 URL 至今【未核实】**。

**ref:bj-fee**（已打开 <https://www.beijing.gov.cn/zhengce/zhengcefagui/201905/t20190522_58449.html>）：

| 字段 | 页面实际值 |
|---|---|
| 标题 | 北京市发展和改革委员会关于本市电动汽车充电服务收费有关问题的通知 |
| 文号 | 京发改〔2015〕848号 |
| 成文日期 | 2015-04-24（与现有 bibitem 一致） |
| 网页发布日期 | 2015-05-08 |
| 上限条款 | 「每千瓦时收费上限标准为当日本市92号汽油每升最高零售价的15%」 |
| 失效条款 | 「自2020年1月1日起，充电服务收费按照国家规定实行**市场调节价**」 |

即：**该文件自己写明其限价自 2020-01-01 起终止**。正文 `:877` 用它支撑「0.40 元/kWh 低于本市规定的上限」，说的是一个 2020 年起已不存在的现行上限；仓库审计（`public_station_modeling_audit_20260908.md:116`）也已记「北京服务费上限官方文号 未核」。这是**正文措辞问题，不是 bibitem 字段问题**。

供选（二选一，不需要写简答题）：
- **甲**：改写 `:877`，把上限句改成历史口径，例如「服务费0.40元/kWh，为情景取值（按2024年公共场站中位水平取整）；北京自2020年起充电服务费实行市场调节价\cite{ref:bj-fee}」——同时消除「已失效上限」和「0.4 无北京出处」两处硬伤。
- **乙**：删掉 `:877` 中「低于本市规定的上限」整个从句与 `\cite{ref:bj-fee}`，只留服务费取值与情景标注；ref:bj-fee 随之从参考文献中删除（其余各处不引它）。

### d. 补全后的 \bibitem

```latex
\bibitem{ref:bj-tou} 北京市发展和改革委员会. 关于进一步完善本市分时电价机制等有关事项的通知[EB/OL]. 京发改规〔2023〕11号. (2023-08-18)[2026-09-09].
\url{https://fgw.beijing.gov.cn/fgwzwgk/2024zcwj/bwgfxwj/202308/t20230821_3718725.htm}.
```

```latex
\bibitem{ref:bj-fee} 北京市发展和改革委员会. 关于本市电动汽车充电服务收费有关问题的通知[EB/OL]. 京发改〔2015〕848号. (2015-04-24)[2026-09-09].
\url{https://www.beijing.gov.cn/zhengce/zhengcefagui/201905/t20190522_58449.html}.
```
（文号从标题括号里提出来放到文号位，与 ref:ndrc-tou、ref:hebei-tou 的体例统一。若采纳上面的「乙」方案，此条整条删除。）

**另建议新增一条价表文献**，承接表 5 那三个数（现在正文把它们挂在 ref:bj-tou 名下，属于张冠李戴）：

```latex
\bibitem{ref:bj-price-table} 国家电网北京市电力公司. 北京市电网销售电价表（2025年2月）[EB/OL]. 【原始发布URL未核实】[2026-09-09].
```
仓库现有证据仅为第三方镜像 <https://energydc.cn/policy/beijing/2025-02/6b885a88-d1dd-11f0-9e8e-46a1f660a16d> 与本地扫描件 `data/ChinaPrices/official_snapshots/china_2025_02_nine_city/beijing_2025_02.webp`（sha256 `a77e05e7…`）。发布机构名称亦为按扫描件标识推断，**【未核实】**。

---

## 四、ref:75 —— Lei 与 Hao 的 arXiv 预印本（缺 URL）

### a. 现状与引用处

`:1665`
```
\bibitem{ref:75} Lei Z, Hao J K. A GPU-accelerated hybrid method for a class of multi-depot vehicle routing problems[EB/OL]. arXiv:2605.05208, 2026.
```

三处引用：

- `:965`：「表中VCGP沿用Lei和Hao\cite{ref:75}的算法标签，指Vidal等提出的HGSADC\cite{ref:74}；」
- `:977`、`:989`（表头，两张表同构）：`VCGP\cite{ref:74}`、`MDFIHA\cite{ref:75}`、`MDFIHA-ETGA\cite{ref:75}`、本文算法
- `:966`：「VCGP、MDFIHA和MDFIHA-ETGA在V13算例上的Best与Avg均来自5次独立运行。」

即 ref:75 同时承担三件事：算法标签来源、两列对照算法的出处、以及对照数据的运行次数口径。

### b. 数据如何进入项目

`grep "arXiv"`、`grep "2605.05208"` 在 `solver/`、`data/` 内零命中——这是纯文献引用，不注入任何算例参数。对照数值来自该论文表格的转录（本次未逐格复核）。

### c. 线上核实

- arXiv 摘要页 <https://arxiv.org/abs/2605.05208> 与官方 API（`http://export.arxiv.org/api/query?id_list=2605.05208`）均返回：
  - id `http://arxiv.org/abs/2605.05208v1`
  - 标题 `A GPU-Accelerated Hybrid Method for a Class of Multi-Depot Vehicle Routing Problems`
  - 作者 `Zhenyu Lei` 与 `Jin-Kao Hao`
  - published / updated 均为 `2026-02-24T14:15:28Z`
  - **journal_ref 无、DOI 无**（除 arXiv 自身的 10.48550/arXiv.2605.05208）
  - 分类 cs.RO; cs.DC; math.OC
  - 注：编号 2605 与 2026-02 的提交日期不自洽，此处照录 arXiv 自身返回值，不代为改写。
- CrossRef 按完整标题检索（`api.crossref.org/works?query.bibliographic=…`）前 5 条**无同题条目**，Lei 与 Hao 无期刊版命中。故**没有可替代的已发表版本，应按 arXiv 预印本著录**。
- 已打开全文 <https://arxiv.org/html/2605.05208> 核三处正文用法（与 `:965`、`:977`、`:966` 一一对应）：
  - **VCGP** 确为该文用来指代 Vidal 等混合遗传搜索（HGSADC 系）的对照标签 → `:965` 的说法成立。
  - **MDFIHA** 是该文自己提出的 CPU 版算法，**MDFIHA-ETGA** 是其 GPU 加速增强版 → `:977`/`:989` 两列挂 ref:75 正确。
  - 该文确在 28 个 MDVRPTW V13 大规模算例上报结果，并写明「除 MDVRPTW V13 算例按文献惯例跑 5 次外，其余每算例独立求解 10 次」 → `:966` 的「5 次独立运行」成立。
  （以上三条基于 arXiv HTML 全文抽取，未逐页核对 PDF 版式。）

### d. 补全后的 \bibitem

```latex
\bibitem{ref:75} Lei Z, Hao J K. A GPU-accelerated hybrid method for a class of multi-depot vehicle routing problems[EB/OL]. (2026)[2026-09-09].
\url{https://arxiv.org/abs/2605.05208}.
```
或保留 arXiv 编号的写法：
```latex
\bibitem{ref:75} Lei Z, Hao J K. A GPU-accelerated hybrid method for a class of multi-depot vehicle routing problems[EB/OL]. arXiv:2605.05208. (2026)[2026-09-09].
\url{https://arxiv.org/abs/2605.05208}.
```
截至 2026-09-09 无期刊版，无需改引已发表版本；若日后出刊，应换成期刊格式。

---

## 五、遗留缺口清单（都标了未核实，不猜）

1. 北京 2025-02 电网销售电价表的**官方原始 URL**——仓库自 2026-07-18 起即标 `OFFICIAL_URL_PENDING`，本次仍未取得。
2. 河北 1364号的**省级原文页**与**准确发布日期**（2022-10-28 / 11-03 / 11-07 三说并存）。
3. 北京公共充电服务费**现行**政府指导上限的官方依据——848号的限价 2020-01-01 已改为市场调节价，仓库审计亦记「未核」；正文 `:877` 的上限句需按上面甲/乙二选一处理。
4. 表 5 与 `:876` 把三档到户电价挂在 2023 年分时机制通知名下，属出处错配，建议另立价表文献。
