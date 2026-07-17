# 中国公开 EV 配送/VRP 算例检索审计（2026-07-17）

## 结论

`HALT_NO_COMPLETE_OPEN_INSTANCE`

截至 2026-07-17，本轮没有找到一个能够实际下载或通过开放 API 取得、许可可复用、并在**同一中国实例**中同时给出以下四类输入的来源：至少两个明确车场、EV/电池参数、充电站、带需求量和承诺时间窗的客户订单。不能把中国路网、充电桩 POI、EV 统计或一篇声称使用重庆案例但未释出原始表格的论文包装成完整算例。

这不是对“自建 C31”可行性的否定，只是否定“已有完整公开中国四要素算例可直接复用”这一前提。C31 的当前定义为京津冀/珠三角/成渝三种区域原型，各含 50/100/200 客户；因此，任何单城、无客户需求或无时间窗的来源都不通过完整实例门。

## 核验标准与方法

完整来源必须同时满足：

1. 中国地理或真实中国配送运营；
2. 稳定网页下载或开放 API 实际可取；
3. 明示可复用许可，或至少没有与仓储许可证矛盾的使用限制；
4. 可机读字段覆盖客户坐标、需求、硬时间窗、多车场、充电站、EV/电池；
5. 来源不是由国际基准或随机抽样后才“变成”中国案例。

检索分两轮进行：先以中英文覆盖“中国/China + EV/电动配送 + VRP + multi-depot + charging + time window + dataset/Zenodo/GitHub”，再针对找到的论文、Zenodo、Figshare、Hugging Face 逐项读取数据可得性声明、仓储/API 元数据、许可和实际文件头/Parquet schema。下载文件均保留为原文件；SHA-256 位于 `data/ChinaInstances/open_sources_20260717/SHA256SUMS`。本轮没有运行优化，也没有读取或修改 E7 文件与 solver 核心。

## 逐源判定

| 来源 | 实际下载/API 核验 | 可用字段（本轮实际检查） | 关键缺失项 | 许可 / 引用 | 是否适合 C31 |
|---|---|---|---|---|---|
| [Wang et al., 2025, *Sustainability*：重庆多车场 EV 动态配送案例](https://doi.org/10.3390/su17062700) | 论文页可打开；数据可得性仅称“Data is contained within the article”，未提供 CSV/代码仓储/补充数据下载。 | 正文明确写有重庆 4 个车场、151 客户（101 静态、50 动态）及 13 个充电站；模型含 EV 与时间窗。 | 无可下载的客户坐标、逐客户需求、逐客户时间窗、车场/站点原始坐标或机器可读车辆表；不能复现实例。其 30 个算法比较实例来自国际 NEO MDVRPTW，并把站点/动态客户从客户中随机选取，非中国原始实例。 | 论文为开放获取（CC BY 4.0）；**不等于**未释出案例数据自动可复用。引用见论文 DOI。 | 否。只可作为“真实重庆场景存在四类实体”的文献背景，不能作为数据源。 |
| [Cainiao-AI/LaDe](https://huggingface.co/datasets/Cainiao-AI/LaDe)（本轮取 `delivery_cq.csv`） | Hugging Face 数据集 API 返回公开仓储和城市文件清单；`delivery_cq.csv` 实际下载成功，138 MiB、931,351 行，城市字段均为 `Chongqing`。 | `order_id, city, courier_id, lng/lat, accept_time, delivery_time`，以及接受/送达时的 GPS 坐标；README 描述包裹位置和时空事件。 | 实际下载的配送表没有客户需求、承诺时间窗字段、车场、充电站、车型、容量或电池字段；不是多车场 EVRP。README 中“可用于研究”与仓储卡的许可证声明存在不一致。 | API `cardData` 写 `Apache-2.0`，但 README 写“can be used for research purposes”；在获得发布方澄清前，按**许可待澄清**处理。引用：Wu et al., *LaDe* (2023), arXiv:2306.10675。 | 否（可作为成渝的订单位置/实际完成时间候选层，但不能单独作 C31，且先解决许可冲突）。 |
| [北京公共充电交易与基础设施数据](https://doi.org/10.6084/m9.figshare.31952289.v2) | Figshare API 可取；`stations_public.parquet` 实际下载成功，MD5 与 API `supplied_md5` 相同。 | `station_id`、网格化 `geocoding`、场地类型、站点总功率、桩/枪数量及 AC/DC 拆分。 | 仅北京；站点位置是匿名网格，不是精确坐标；没有配送客户、需求、时间窗、车场或配送 EV 车辆表。 | CC BY 4.0；应引用 Figshare DOI 和关联论文。 | 否（北京充电设施参数层；可用于未来经批准的 C31 北京站点能力标定，不能直接当充电站坐标实例）。 |
| [中国七城 EV 使用与充电分析数据](https://doi.org/10.5281/zenodo.13852045) | Zenodo API 可取并列出 MD5；三个 CSV 实际下载且本地 MD5 均与 API 一致。 | 覆盖北京、广州、成都、重庆等城市的 EV 类型、名义电池能量分位数、日内驾驶/充电/停放占比等统计。 | 无客户、订单需求、订单时间窗、车场、逐站坐标或可用于路径的车辆记录；是论文图表的处理后统计，非配送实例。 | CC BY 4.0；引用 Zenodo DOI 与 Zhan et al. (2025)。 | 否（可作为 EV/电池或充电时段参数的候选证据，不能生成完整 C31）。 |
| [PLOS ONE 众包货运补充数据](https://doi.org/10.6084/m9.figshare.28113608.v1) | Figshare API 和 `Data Description.xlsx`、`Day 1.xlsx` 均实际下载，文件 MD5 与 API 一致。 | 10 日订单给出客户/商户平面坐标、取送硬时间窗、货物体积、服务时间；另有车辆初始平面坐标。 | 文件以无地理参照的平面坐标给出，包内未证明中国城市；无 EV、电池、充电站或明确多车场。 | CC BY 4.0；引用 Zhang (2025), *PLOS ONE* 与 Figshare DOI。 | 否。可作非中国、非 EV 的动态取送时间窗格式参考，不得移植后称“中国公开 EV 算例”。 |

## 关键反证：看似最接近的重庆论文不是公开算例

该论文确实是本轮最接近四要素叙述的中国来源：其第 6.2 节写明 4 车场、151 客户和 13 充电站。但同页的数据声明只有“数据包含在论文中”；图、汇总表和参数表不能还原客户需求与时间窗。更关键的是，论文第 6.1 节明确说明用于算法对比的 30 个实例由 NEO 的国际 MDVRPTW 基准扩展而来，充电站与动态客户是从客户位置随机选出的。因此它既不满足“开放机器可读原始中国案例”，也不满足“真实站点/动态需求已公开”的要求。

## 已保存的原始文件与完整性

下载根目录：`data/ChinaInstances/open_sources_20260717/`。`SOURCE_METADATA.json` 是各仓储 API 原样响应；`README.md` 为 LaDe 仓储原样说明。没有改写任何来源原始数据。外置盘会产生 `._*` AppleDouble 旁车文件；它们不是来源文件，未写入 `SHA256SUMS`，也没有作为证据或数据使用。

| 原始文件 | SHA-256 | 上游完整性核验 |
|---|---|---|
| `huggingface_Cainiao-AI_LaDe/delivery_cq.csv` | `114a35e9a31f817a3c9efb8513924688706bcedfa85ccd69df696eb5e8eddea2` | Hugging Face 可直接下载；仓储 API 未提供文件 MD5。 |
| `figshare_31952289/stations_public.parquet` | `3db96289c1f906de8b481372772b72164211868026ceedfc7a2858f56c336b85` | 本地 MD5 `449a2adaa391895d4c29944a6e400794` = Figshare `supplied_md5`。 |
| `zenodo_13852045/Fig1b...csv` | `6fac65f51c2c7b5c4569bb174e1ddf66a62357c3f544401685f3a6eeb17043de` | 本地 MD5 `15aa741321fb36eb0eb78e6f4e35afbc` = Zenodo API。 |
| `zenodo_13852045/Fig2a...csv` | `034d4647fef7d429e9b001fae585d408c97e82b14541e39e33dac492fa0ba5b1` | 本地 MD5 `badb7f20660efcb04fb87b02b05a5d88` = Zenodo API。 |
| `zenodo_13852045/FigSI6...csv` | `ee9a03c921d7b38c70835991dd602f3c38968a2f5e85ddf06f4b87be5152cd08` | 本地 MD5 `517033b7c981436e17b5153cc92e3163` = Zenodo API。 |
| `figshare_28113608/Data Description.xlsx` | `7c9be7fac9b993d50bd0cfd1070082c52d0080deda5972a5cefd782e8f3a0659` | 本地 MD5 `d1b03be930ec05eeadf87c3b75f60fe6` = Figshare `supplied_md5`。 |
| `figshare_28113608/Day 1.xlsx` | `45fbe317209d58ed3d9116c8691638882a8db8c35b5c125954881b1b6fda37aa` | 本地 MD5 `d37f2fc15c24c0df80fd99cf3dd6f196` = Figshare `supplied_md5`。 |

完整 SHA-256 清单还包括保存的仓储元数据、README 和笔记本，见 `SHA256SUMS`。

## C31 的停机线与可用事实

因此当前决策应维持为：**停止寻找“可直接拿来跑的完整中国四要素公开实例”这一支线，不授权把任何上表部分数据直接灌入 C31。** 若以后转入自建，必须先单独冻结“订单/需求与时间窗如何由文献分布生成、车场如何预注册、充电点是否使用精确可许可坐标、跨源许可如何满足”的实例合同；那是新建算例工作，不是本报告声称已经找到的公开算例。

本报告只完成资料检索、原始文件保存和字段/许可审计；未对 solver、E7 或任何优化运行作出改动。
