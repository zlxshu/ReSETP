# 中国九城物流设施来源登记（V2 候选层）

本登记把九城算例的车场从“工业用地候选”提升到“有名称、有政府来源的物流设施候选”。它仍不是正式车场清单：本轮只锁定官方身份线索，没有把规划范围偷换成单一坐标，也没有把政府页面偷换成运营主体或车场充电容量。

机器可读入口是 `docs/handoff/china_facility_manifest_v2_20260718.json`。最新批次位于 `data/ChinaInstances/china_facility_sources_v2_20260718_clean_v2/`：9 条主 URL 中 8 条已保存 HTTP 200 原始响应并完成哈希，东莞替代政府页面已补齐。深圳政府新闻页仍因本机 OpenSSL 与站点 TLS 握手出现 `BAD_ECPOINT` 而无法保存本地字节；浏览器绕路后，从深圳市规划和自然资源局现行页面取得了 2025 年设计文件核查表与变更后规划许可证，两份官方 PDF 均已本地保存并哈希。因此九城都已有本地官方设施来源，但主 URL 抓取统计仍如实记为 8/9。坐标为空、`operating_status=COORDINATE_AND_OPERATIONAL_STATUS_PENDING` 和地图编号为空仍是有意保留的阻断状态。正式算例前仍必须补齐具体入口坐标、地图/运营商编号、实际运营状态、客户到车场道路距离和车场充电合同。

| 城市 | 候选设施 | 官方来源 | 当前证据边界 |
|---|---|---|---|
| 北京 | 京平综合物流枢纽（马坊物流基地） | [北京市政府页面](https://www.beijing.gov.cn/ywdt/gzdt/202408/t20240822_3779844.html) | 支持枢纽和基地身份；入口、运营主体、车场桩待核 |
| 天津 | 东疆综保区港口型国家物流枢纽 | [天津市发展改革委文件](https://fzgg.tj.gov.cn/zwgk_47325/zcfg_47338/zcwjx/fgwj/202210/t20221024_6016462.html) | 支持港口型枢纽区域身份；单一车场和桩待核 |
| 石家庄 | 石家庄国际陆港 | [石家庄市政府页面](https://www.sjz.gov.cn/columns/ba3cae66-c5bf-45c6-a0cc-9ade69246aa9/202503/01/d5c08f53-1d89-4fc4-ad7c-f077b5b79e52.html) | 支持综合货运枢纽建设对象；具体入口待核 |
| 广州 | 广州空港物流枢纽 | [广州市政府规划](https://www.gz.gov.cn/zwgk/ghjh/fzgh/ssw/content/mpost_8661346.html) | 支持空港物流枢纽规划身份；具体车场待核 |
| 深圳 | 深圳国际综合物流枢纽中心（平湖南） | [深圳市政府在线页面](https://www.sz.gov.cn/cn/xxgk/zfxxgj/gqdt/content/post_12582907.html)、[规划资源局现行通告](https://pnr.sz.gov.cn/xxgk/gggs/content/post_12485164.html)、[设计文件核查表](https://pnr.sz.gov.cn/attachment/1/1645/1645187/12485163.pdf)、[规划许可证](https://pnr.sz.gov.cn/attachment/1/1645/1645190/12485164.pdf) | 现行核查表载明用地单位、平湖南铁路货场、1068个货车停车位和642个充电桩位；桩位不是枪数、投运数量或功率，入口和实际可用充电设施仍待核 |
| 东莞 | 东莞枢纽沙田片区（虎门港综合保税区核心） | [东莞市政府页面](https://www.dg.gov.cn/shatian/jjst/styw/content/post_4280217.html) | 支持国家物流枢纽片区身份；仍不能直接当单一站址 |
| 佛山 | 佛山国际陆港 | [广东省政府页面](https://www.gd.gov.cn/gdywdt/dsdt/content/post_4148215.html) | 支持已命名陆港线索；具体入口待核 |
| 成都 | 成都国际铁路港 | [四川省政府页面](https://www.sc.gov.cn/10462/10464/10797/2020/8/27/07e4d4877886412285920f85d123473a.shtml) | 支持正式设施/开发区身份；具体车场待核 |
| 重庆 | 重庆公路物流基地（南彭） | [重庆市政府页面](https://www.cq.gov.cn/zt/yhyshj/zsyz/zqcyyq/bnq/202512/t20251226_15274244.html) | 支持基地身份；入口、运营主体、车场桩待核 |

## 当前裁决

这份登记可以作为后续坐标匹配和现场设施核验的入口，不能作为正式算例的车场证据。尤其是东莞的“建设范围”、广州的“规划枢纽”、成都的“开发区/港区”都不能直接生成一个虚构的经纬度；必须在下一步从地图或运营方资料中选定具体可进入的物流场址。

## 当前裁决

`OFFICIAL_FACILITY_SOURCE_AVAILABLE_9_OF_9_PRIMARY_URL_CAPTURE_8_OF_9`。九城均已有本地官方设施来源；深圳通过现行规划附件绕过失效旧附件和命令行 TLS 问题，但主新闻 URL 的失败记录没有被删除。设施层仍未闭合，`formal_search_allowed` 继续为 `false`。
