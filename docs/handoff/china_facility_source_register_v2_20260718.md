# 中国九城物流设施与运营场址来源登记（V2 候选层）

本登记把九城车场证据拆成两层：原有政府来源证明城市中确有该物流枢纽或设施；新增运营来源和地图实体用于选择一个可以继续核验的具体场址或入口。两层都闭合后仍不等于正式车场，因为百度原始坐标是 `BD09MC` 投影米制坐标，货车准入、开放时间、停车容量和场内充电能力也没有自动获得证明。

机器可读入口是 `docs/handoff/china_facility_manifest_v2_20260718.json`。设施身份来源包位于 `data/ChinaInstances/china_facility_sources_v2_20260718_clean_v2/`；运营来源首轮失败包和首个绕路通过包分别位于 `data/ChinaInstances/china_operational_site_sources_v2_20260718_run1/` 与 `data/ChinaInstances/china_operational_site_sources_v2_20260718_run2/`。补入运营主体、准入、停车和充电硬参数来源后的当前包为 `data/ChinaInstances/china_operational_site_sources_v2_20260718_run3_hard_parameters/`：尝试38条URL，保存35条，九城全覆盖。深圳 HTTPS 因命令行 TLS `BAD_ECPOINT` 失败后，使用同一政府主机的 HTTP 端点保存原文，并在 `raw_runs.csv` 明记降级边界；没有把它伪装成正常 HTTPS 抓取。

| 城市 | 原身份候选 | 优选运营场址/入口候选 | 运营证据与当前边界 |
|---|---|---|---|
| 北京 | 京平综合物流枢纽（马坊物流基地） | 北京平谷国际陆港（马坊铁路场站）货车入口候选 | [北京市政府 2025](https://www.beijing.gov.cn/ywdt/gqrd/202509/t20250909_4194699.html)、[北京市政府 2024](https://www.beijing.gov.cn/ywdt/gqrd/202405/t20240517_3686953.html)证明班列从马坊铁路站发出并在场站集结；百度 UID `07dc236824a0e3ba49fc8d2b`、OSM way `1104072601`。道路吸附点尚未核成货车门。 |
| 天津 | 东疆综保区港口型国家物流枢纽 | 万纬天津港物流园停车场出入口候选 | [天津市生态环境局名录](https://sthj.tj.gov.cn/ZWXX808/TZGG6419/202410/W020241018613257591606.pdf)证明物流企业在北港西路 902 号运营；园区 UID `0aa45c3b9adf9a5e6e20b930`，出入口 UID `46024ec9e95c210921f017a5`。尚未证明该口允许重型货车。 |
| 石家庄 | 石家庄国际陆港 | 石家庄国际陆港北门候选 | [运营方设施页](https://www.cnlandport.com/product/12.html)和[联系页](https://www.cnlandport.com/Contact.html)证明依托高邑货运站运营；园区 UID `f13a67f3eea2123a82a12e5e`，北门 UID `2869d26d7f472ed617c8f609`。北门的货车主入口身份待核。 |
| 广州 | 广州空港物流枢纽 | 广州国际港（广州铁路集装箱中心站）东门 | [广州市政府投运报道](https://www.gz.gov.cn/xw/zwlb/gqdt/byq/content/post_8014572.html)和[运营报道](https://www.gz.gov.cn/zt/zzyyzq/bmdt/content/post_10634822.html)支持班列及集装箱卡车作业；东门 UID `f5141d94db59caa1c356ac61`。社会货车预约规则待核。 |
| 深圳 | 平湖南综合物流枢纽 | 平湖南既有/一期铁路货场地面作业层 | [深圳市政府一期运营资料](https://www.sz.gov.cn/szzt2010/wgkzl/glgk/jgxxgk/gyqyyy/content/post_10699280.html)和[铁路地面层资料](https://www.sz.gov.cn/cn/xxgk/zfxxgj/gqdt/content/post_12582907.html)支持既有/一期作业；UID `6421a1c69b1aeab68a36eef1`。规划文件中的 1068 个货车停车位、642 个充电桩位属于建设许可口径，不能写成已投运容量、枪数或功率。 |
| 东莞 | 东莞枢纽沙田片区 | 东莞清溪保税物流中心（B型） | [清溪镇政府货车卡口资料](https://www.dg.gov.cn/dgqxz/gkmlpt/content/4/4334/post_4334630.html)和[运营资料](https://www.dg.gov.cn/dgqxz/gkmlpt/content/4/4494/post_4494741.html)支持仓库装卸、车辆卡口、2025 年运营和 7×24 小时通关；UID `ee7fc367b5165e7f22f017f0`。通关时段不等于普通配送车全天自由准入。 |
| 佛山 | 佛山国际陆港 | 佛山国际陆港 | [广东省政府投运资料](https://www.gd.gov.cn/gdywdt/dsdt/content/post_4148215.html)支持已投运；百度 UID `b3de3ceec4a5b371b31e3674`、OSM way `1072462242`。OSM 质心只表示场区面，不是入口。 |
| 成都 | 成都国际铁路港 | 中铁联集成都中心站北门 | [中铁联集中心站页](https://www.crct.com/index.php?a=lists&c=index&catid=66&m=content)和[四川交通运输厅资料](https://jtt.sc.gov.cn/jtt/c111874/2025/9/12/17f7d101dc094701bba68b75bce4156a.shtml)支持中心站和公路集疏运；北门 UID `85880009b61de98646572689`、OSM way `633016112`。车型准入和开放时段待核。 |
| 重庆 | 重庆公路物流基地（南彭） | 重庆南彭公路保税物流中心西北门 | [重庆市政府 2025](https://www.cq.gov.cn/ywdt/jrcq/202508/t20250819_14911996_app.html)和[重庆市政府 2023](https://www.cq.gov.cn/ywdt/jrcq/202307/t20230722_12174804.html)直接记录跨境车辆从南彭 B 保驶出并在中心集拼；西北门 UID `6e699d1ad3a23e9b260bd089`。地图“开放大门”标签不等于全天普通配送准入。 |

## 当前裁决

设施身份来源层为 `OFFICIAL_FACILITY_SOURCE_AVAILABLE_9_OF_9_PRIMARY_URL_CAPTURE_8_OF_9`；具体运营场址与硬参数来源层为 `PASS_OPERATION_SOURCE_CAPTURE_9_OF_9_CITIES`；九城均已形成地图标识明确的优选场址或入口候选，运营/开发主体字段已不再为空。第一轮缺深圳的 HALT 包和第二轮20条URL包均保留，38条URL的第三轮通过包不覆盖历史。

硬参数审计没有得到“九城均有可直接使用的场内桩”这种理想结果。九城普通运营时段、配送货车停车位、投运车辆充电桩数/枪数/功率仍大多为`UNKNOWN`；天津港北疆有16台320kW公共重卡桩，但到万纬园区的精确道路距离未闭合；深圳1068个货车停车位和642个充电车位是上盖项目规划值；佛山6+10台60kW只是待查备案线索。以上均已结构化写入manifest，且`formal_depot_parameter_lock=false`。

正式算例仍为 `HALT`。下一门是将每个入口候选转换或重新匹配为 WGS84 道路节点，并记录坐标转换方法、第二地图交叉核验、道路吸附误差和货车可达性。`coordinates.latitude/longitude` 继续保持空值，任何人都不得把 BD09MC 的百万量级 x/y 写进去。停车容量、门禁时间和场内充电参数仍须单独取证；缺证据时只能采用明确标注的中国情景参数，不能冒充现场实测值。
