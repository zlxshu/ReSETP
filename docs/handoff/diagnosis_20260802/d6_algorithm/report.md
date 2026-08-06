# D6：MV-HGS-SP 算法竞争力对抗性评审

任务编号：`D6`  
状态：`D6_ALGORITHM_REVIEW_COMPLETE`

## 一、论断 A 裁决

**裁决：部分成立，且只在“比较协议不足以归因算法优势”这一支成立。** “没有逐实例 BKS gap”不成立：正文表 `tab:v13-results` 已逐题列出 BKS、Best gap 和 avg gap（`docs/paper_v2/paper_main.tex:1111-1116, 1130-1165`）；封存结果包还保留了精确未舍入 gap。“gap 本身不具竞争力”也不成立：以表中 2013 年参考解为分母，MV-HGS-SP 的 28 题 Best 平均 gap 为 **0.9048706161%**，低于 VCGP 的 1.6040966227%、MDFIHA 的 1.3749011122% 和 MDFIHA-ETGA 的 0.9903830847%；逐题有 19/28 低于 MDFIHA-ETGA（`baselines/e2_final_campaign_20260720/mv_hgs_sp_final/p1_formal_gate/decision.json`：`avg_row_error_pct`、`table5`；正文 `paper_main.tex:1114-1117`）。因此，现有目标值足以说明“处于所列强算法的竞争区间”。

成立的是第三支。正文把各自收敛的母体与在同一母体轨迹后继续搜索的 MV-HGS-SP 并排，后者每题平均处理器时间实际为母体的 **1.450051--2.003249 倍**；280 次运行的母体/融合体平均 CPU 分别为 **231.943327 s / 433.776769 s**。正文只给 1.47--2.00 的比例，不给逐题或平均秒数，也没有 CPU 型号（`paper_main.tex:1106-1108, 1165`；`p1_formal_gate/raw_runs.csv`：`mother_cpu_seconds, hybrid_cpu_seconds, cpu_ratio`；`p1_formal_gate/metadata.json` 仅有 `workers=6`、`seeds=1..10` 和停止常数，没有硬件字段）。更关键的是，6 题×5 种子的 6200 代配对中仅得到 18 胜/12负、合计改善 0.1003%，95% 区间跨 0、Wilcoxon `p=0.2894`，结论为与纯 PyVRP-HGS 无统计可区分差异（`baselines/algorithm_prototypes/boundary_probe_20260726/d4_summary.json`；同目录 `report.md` 第 11 节；正文 `paper_main.tex:1118-1120`）。所以公开表证明了解质量竞争力，没有证明所称融合结构在公平预算下优于母体。

另有一个基准口径错误：正文称“当前逐题 BKS”（`paper_main.tex:1111`），但结果包使用的是字段 **`bks_2013`**。仓库后来用未经修改的 PyVRP-HGS 从这些解热启动，在 18/28 题上取得更低且独立认证的解（`baselines/algorithm_prototypes/boundary_probe_20260726/NEW_BKS_TABLE.csv`：18 行，列 `bks_2013,new_best,certificate=PASS`）。这些是仓库内认证候选，不等于已获外部共同体承认的新 BKS；因此当前仓库既不能把 2013 列称为“当前 BKS”，也没有一份外部社区当前 BKS 注册表可供核验。

## 二、公开标准算例的真实表现

### 2.1 算例身份与规模

使用的是 **Vidal 等 2013 年提出的 V13 大规模 MDVRPTW 算例**，不是 Solomon、Goeke 或 Schneider 电动车算例。集合为 `PR11A--PR24B` 共 **28 个实例**，客户规模 **360--960**（`paper_main.tex:1101-1103`；Vidal 等作者公开稿 PDF p.23，Table 8 的 V13 行）。封存决策文件给出 `instances_complete=28`、`instances_total=28`、`seed_units_total=280`（`p1_formal_gate/decision.json`）。

### 2.2 冷启动正式表：逐实例最终 Best 与 BKS gap

下表的 BKS 是结果包沿用的 2013 参考值；MV 最终值是 10 次运行中的最小 `hybrid_best`；gap 定义为 `100×(MV Best−BKS)/BKS`。全部原始值来自 `p1_formal_gate/decision.json.table5`，正文只显示两位小数 gap（`paper_main.tex:1130-1162`）。

| 实例 | 客户 | BKS（2013） | MV-HGS-SP Best | 精确 gap (%) | 达到/改进该 BKS |
|---|---:|---:|---:|---:|---|
| PR11A | 360 | 6655.548 | 6672.748 | 0.2584310112 | 否 |
| PR11B | 360 | 4814.803 | 4816.902 | 0.0435947224 | 否 |
| PR12A | 480 | 8148.107 | 8194.636 | 0.5710406110 | 否 |
| PR12B | 480 | 6004.834 | 6011.056 | 0.1036165196 | 否 |
| PR13A | 600 | 9501.934 | 9580.149 | 0.8231482138 | 否 |
| PR13B | 600 | 7201.765 | 7230.335 | 0.3967083069 | 否 |
| PR14A | 720 | 10925.670 | 11055.153 | 1.1851264041 | 否 |
| PR14B | 720 | 8656.335 | 8722.913 | 0.7691245775 | 否 |
| PR15A | 840 | 12714.063 | 12897.333 | 1.4414746883 | 否 |
| PR15B | 840 | 10223.105 | 10369.112 | 1.4282060098 | 否 |
| PR16A | 960 | 13992.681 | 14299.112 | 2.1899377253 | 否 |
| PR16B | 960 | 11225.795 | 11479.315 | **2.2583701199** | 否；最差 gap |
| PR17A | 360 | 6292.594 | 6304.696 | 0.1923213225 | 否 |
| PR17B | 360 | 4771.155 | 4771.155 | **0.0000000000** | **达到** |
| PR18A | 520 | 8183.231 | 8215.182 | 0.3904448011 | 否 |
| PR18B | 520 | 6443.442 | 6462.527 | 0.2961926250 | 否 |
| PR19A | 700 | 10521.112 | 10650.927 | 1.2338524673 | 否 |
| PR19B | 700 | 8061.518 | 8131.012 | 0.8620460811 | 否 |
| PR20A | 880 | 11686.369 | 11924.648 | 2.0389481113 | 否 |
| PR20B | 880 | 10013.395 | 10141.893 | 1.2832610718 | 否 |
| PR21A | 420 | 6230.046 | 6234.394 | 0.0697908170 | 否 |
| PR21B | 420 | 4822.337 | 4822.912 | 0.0119236793 | 否 |
| PR22A | 600 | 7868.943 | 7936.795 | 0.8622759118 | 否 |
| PR22B | 600 | 6403.374 | 6417.919 | 0.2271458765 | 否 |
| PR23A | 780 | 9726.158 | 9892.624 | 1.7115288483 | 否 |
| PR23B | 780 | 8317.649 | 8405.473 | 1.0558752840 | 否 |
| PR24A | 960 | 11638.608 | 11889.491 | 2.1556100180 | 否 |
| PR24B | 960 | 10486.450 | 10641.270 | 1.4763814256 | 否 |
| **均值/计数** | **28题** | — | — | **0.9048706161** | **达到 1，改进 0** |

冷启动正式表的“达到或改进 BKS”是 **1/28 达到、0/28 改进**，不是 18/28。后一个数字来自另一项以 2013 解为起点的热启动边界探查：纯 PyVRP-HGS 先在 18/28 题取得更低解（`paper_main.tex:1174-1177`；`boundary_probe_20260726/NEW_BKS_TABLE.csv`），而 MV-HGS-SP 固定复现协议对这 18 个目标只复现 **13/18**、失败 **5/18**（`baselines/algorithm_prototypes/mvhgssp_bks_reproduction_full_20260727/decision.json`：`evaluated=18, passed=13, failed=5, verdict=STOP_NOT_ALL_TARGETS_REPRODUCED`）。正文表 `tab:v13-improved` 的 18 行均低于 2013 值（`paper_main.tex:1192-1216`），但这不能倒填为冷启动正式表的 18 个 BKS 命中。

### 2.3 重复、停止、统计量与时间

| 项目 | 仓库事实 | 正文披露 |
|---|---|---|
| 重复次数 | 每题种子 1--10，共 280 单元；`p1_formal_gate/metadata.json.seeds=[1..10]`，`decision.json.seed_units_total=280` | 已写：`paper_main.tex:1106,1165` |
| 母体停止 | `K_MOTHER=4000` 或 `CAP_MOTHER=240.0 s` | 只写“运行至其收敛条件”：`paper_main.tex:1106`；数值未写 |
| 融合后续停止 | 每轮 `K_EPOCH=2000` 或 `CAP_EPOCH=60.0 s`；`MAX_EPOCHS=4`、`STALL_EPOCHS=2`；SP 每轮 `SP_TIME=10.0 s`；`p1_formal_gate/metadata.json.frozen_constants` | 只写路线池重组与后续搜索：`paper_main.tex:1107`；上述数值未写 |
| 报告统计量 | 每题 Best 为 10 次最小值；avg 为 10 次最终 gap 的均值；`decision.json.table5` 与 `raw_runs.csv` | 已写 Best/avg gap：`paper_main.tex:1130-1162`；没有写 Best 原始目标值 |
| 计算时间 | 280 行均有 `mother_cpu_seconds,hybrid_cpu_seconds,cpu_ratio`；总体均值 231.943327/433.776769 s；单次范围 77.132099--240.520478/115.820906--482.222701 s；逐题均值比 1.450051--2.003249 | 只写比值 1.47--2.00：`paper_main.tex:1108,1165`；无秒数 |
| 硬件 | `decision.json.claim_boundary` 仅称 same-machine `(M1)`；`metadata.json` 没有 CPU 型号、内存、操作系统字段 | 正文仅称“同机”：`paper_main.tex:1104-1108,1165` |
| 文献对手 | `decision.json.claim_boundary` 明定 VCGP/MDFIHA/ETGA 是 literature best，不作同机时间比较 | 已写：`paper_main.tex:1104-1109,1165` |

### 2.4 已进论文、只在仓库、以及不存在的内容

**已进论文。** 算例身份、28 题、360--960 客户、10 个种子、逐题 BKS、逐题 Best/avg gap、四个算法的平均 gap、19/28 胜 ETGA、264/16/0 母体比较、处理器时间比例、6题×5种子等迭代检验和热启动 18 行结果均已写入 `paper_main.tex:1101-1216`。

**只在仓库。** 28 个 MV-HGS-SP Best 原始目标值、未舍入 gap、280 行逐次目标与 CPU 秒数、母体及融合阶段全部停止常数、具体失败的 5 个热启动复现目标、以及“只有 PR14B 可严格归因 SP”的边界只存在于 `p1_formal_gate/{decision.json,metadata.json,raw_runs.csv}`、`mvhgssp_bks_reproduction_full_20260727/{decision.json,report.md,NEW_BKS_UPDATES.csv}`。其中 PR14B 的同轮 HGS/SP 为 8654.168/8653.985，SP 独立降低 **0.183**；其余四个新候选是 HGS 结果或 SP 平局（该复现包 `report.md`）。

**不存在。** 仓库不存在“截至 2026-08-02 获外部共同体承认的当前逐实例 BKS 清单”；可找到的是 2013 列和本仓库独立认证候选。冷启动 P1 包也不存在 CPU 型号字段。论文的 `tab:v13-results` 由 `p1_formal_gate/decision.json.table5` 和 `baselines/e2_final_campaign_20260720/p2p3_threeview/artifacts/table5_public_v4.csv` 生成：后者只有 `bks` 及各算法 gap，没有 MV 原始目标和时间。

## 三、同类算法论文的报告惯例

### 3.1 六篇逐篇对照

| 论文 | BKS gap 与重复统计 | 时间、停止与硬件 | 表格形态与页码 |
|---|---|---|---|
| Vidal et al. (2013), HGSADC, DOI `10.1016/j.cor.2012.07.018` | 作者公开稿 PDF p.20 Table 3 对经典 MDVRPTW 列 `Avg 10, Best 10, T(min), prev BKS, All exp.`，底部给相对 BKS 的 gap；V13 大题在 p.23 Table 8 列 `Avg 5, T(min), Best 5`。 | PDF p.16：C++ `g++ -O3`、Intel Xeon 2.93 GHz；p.17：正式比较 `ItNI=5000`；p.21 对超大题另列 2 h 上限，p.23 对部分大题列 `ItNI=2500` 与 5 h 上限。 | 逐实例一行，原始目标、重复均值、重复最好、时间并列；处理器在表底单列。该表正是 ReSETP 的 V13 来源。 |
| Lei & Hao (2026), MDFIHA/MDFIHA-ETGA, arXiv `2605.05208` | PDF p.21 给 `Gap=(f−BKS)/BKS×100%`、胜/平/负和 Wilcoxon；附录 PDF p.39 Table A8 对 28 个 V13 逐题列 `fBest,fAvg,γt,Gap`。正文/附录说明自有算法以独立重复的 best、average 和 average time 报告。 | PDF p.20：AMD EPYC 7282 2.8 GHz；GPU 为 NVIDIA V100 32 GB；V13 时限 7200 s。PDF p.21 与 p.36 Table A3 用 PassMark 比率 `γ` 归一化异机 CPU 时间。 | Table 3 是集合级平均 best、平均/归一化时间、平均 gap、W/T/L、p 值；Table A8 是逐实例 best/avg/归一化时间/gap。 |
| Schneider, Stenger & Goeke (2014), DOI `10.1287/trsc.2013.0490` | PDF p.12 参数检验明确每设置 10 次取最好；p.13 Table 5 小例给 10 次最好及对 CPLEX 的 gap；p.14--16 Tables 6--7 给 best-of-10、average gap 与 BKS gap。 | PDF p.11：Intel Core i5-750 2.67 GHz、4 GB、Windows 7；可行性/距离阶段分别观察 50,000/20,000 无改善迭代；p.13 CPLEX 上限 7200 s，并列总时间。 | 逐实例列车辆数、距离、best gap、average gap、时间；表底列平均 gap 与平均时间。 |
| Goeke & Schneider (2015), DOI `10.1016/j.ejor.2015.01.049` | PDF p.10 Table 2 用 10 次最好调参；p.11--12 Table 5 同时列 10 次最好、10 次平均、average runtime 与两种 gap；p.15 Table 10 对公开 E-VRPTW 逐题列 previous BKS、best-of-10 gap 和时间。 | PDF p.10：Intel Core i7 2.8 GHz、8 GB、Windows 7、Java 单线程；停止为 `βfeas=2000` 与 `βobj=750`（大题按规模缩放）。PDF p.16 明说只有同平台算法的时间能精确比较。 | 逐实例 BKS/车辆数/best gap/time，表底列累计车辆、平均 gap、平均时间；异机比较边界直接写在正文。 |
| Zhao et al. (2024), HGS+DP split, DOI `10.1016/j.ejor.2024.04.011` | PDF p.10 Table 3：每题 10 个随机种子，报告 `Best, Avg, Time(s)`；p.10--11 Table 4 再列 best/avg/time/gap。 | PDF p.9：终止为 `max(50n,2000)` 迭代，500 代无改善触发 diversification；Ubuntu 18.04.3、Intel Xeon Silver 4216 2.10 GHz、512 GB RAM。 | 逐实例 best、平均值、平均秒数与已知最好值并列，集合表再汇总 gap。 |
| 陈婉茹等 (2023), 《系统工程理论与实践》43(11):3320--3335 | p.3328 给最大迭代与按规模变化的最大无改善迭代；公开算例与仿真实例采用 10 次运行并报告算法结果。 | pp.3328--3331 的结果表列计算时间；p.3329 给收敛曲线；p.3331 Table 8 做算法部件消融。 | 目标期刊样式同时出现参数/停止条件、重复结果、计算时间、收敛过程和一因素部件表。 |

### 3.2 本文相对惯例的缺项与多出项

**必要缺项**的判据是：至少四篇直接同类算法文献共同报告，或目标期刊同类文献明确使用，且缺失会阻断性能或归因判断。

| 缺项 | 分档 | 证据与当前状态 |
|---|---|---|
| 公开表逐实例 MV 原始 Best 目标值 | **必要** | Vidal PDF pp.20,23、Lei PDF p.39、Schneider PDF pp.13--16、Goeke PDF p.15、Zhao PDF p.10 均把原始目标与 gap/BKS 并列；本文 `paper_main.tex:1130-1162` 只列 gap，原值只在 `decision.json.table5`。 |
| 公开表逐实例或至少集合级实际 CPU 秒数/分钟 | **必要** | 上述五篇全部报时间；目标期刊陈婉茹等 pp.3328--3331 也报时间。本文公开表只给 1.47--2.00 比例（`paper_main.tex:1108,1165`），秒数只在 `raw_runs.csv`。 |
| 机器 CPU 型号、内存、系统/线程口径 | **必要** | Vidal PDF p.16、Schneider PDF p.11、Goeke PDF p.10、Zhao PDF p.9、Lei PDF p.20 均给硬件；本文 P1 `metadata.json` 无硬件字段，正文只称“同机”。 |
| 全部停止条件的数值 | **必要** | Vidal PDF pp.17,21,23、Schneider PDF p.11、Goeke PDF p.10、Zhao PDF p.9、Lei PDF p.20 均给迭代/无改善/时限；本文只在 `metadata.json.frozen_constants` 保存 `4000/240s, 2000/60s, 4轮, 2轮停滞, SP 10s`，正文 `paper_main.tex:1106-1108` 未给。 |
| 异机文献对手的时间可比边界或归一化口径 | **必要** | Goeke PDF p.16 明定只有同平台能精确比较；Lei PDF pp.21,36 用 PassMark `γ`；本文对文献列只比较目标值是正确边界（`paper_main.tex:1109`），但没有把各方法时限/硬件并列，读者无法判断 0.90% 与 0.99% 的成本差对应何种计算投入。 |
| 一因素算法部件归因 | **必要** | 陈婉茹 p.3331 Table 8 与 Lei §5/PDF pp.23--27 分别隔离算法部件；当前 `paper_main.tex:1221-1228` 同时改变三视角、路线池、MIP、后续搜索和接受规则。`docs/handoff/model_scope_reduction_review_20260802/gaps.json` 亦将该项分档为“必要”。 |
| BKS 版本/来源口径 | **必要** | Lei PDF p.39 将 BKS/参考算法与 gap 定义绑定，Vidal PDF pp.20,23 分开 `prev BKS` 与本次 `All exp.`；本文 `paper_main.tex:1111` 称“当前 BKS”，而仓库字段是 `bks_2013`。 |
| 重复结果离散度（标准差/箱线） | **可选** | Vidal、Schneider、Goeke、Zhao 的主表通常只给 best/avg/time，并非共同硬项；本文已有 Best 与 avg gap（`paper_main.tex:1130-1162`）。 |
| 全 28 题统计检验 | **可选** | Lei PDF p.21 使用 Wilcoxon，但 Vidal、Schneider、Goeke 的对应主表不统一要求；本文已有 30 个等迭代配对的区间与 Wilcoxon（`paper_main.tex:1119-1120`）。 |

本文多出的内容是：同机母体 280 单元的胜平负、6题×5种子的配对区间/Wilcoxon、独立路线证书、热启动边界探查和性能剖面（`paper_main.tex:1118-1121, 1174-1216, 1332-1360`）。这些量有审计价值，但不替代实际时间、硬件、停止数值和部件归因。

## 四、三个自称创新点的可辩护性

### 4.1 机制视角分解：HGS-F / HGS-E / HGS-M

**最接近工作及差异。** Zhao et al. (2024) §6、PDF pp.9--10（期刊 pp.928--930）使用单一 HGS 种群、交叉、局部搜索、survivor、diversification 和 DP split；Wang et al. (2025), DOI `10.1016/j.trc.2024.104932`, PDF pp.13--18 使用问题感知路线评价、ILS 路线生成和路线池/SP。二者都没有“燃油/简化电动/机制感知三个独立代理种群”这一同形构造；这与 `docs/handoff/model_scope_reduction_review_20260802/components.json` 中条目 `HGS-F/HGS-E/HGS-M三机制视角分解` 的证据一致。差异存在于代理目标拆分与三种群共同写回，不存在于 HGS 主体。

**仓库能否反驳“常规做法改名”。不能。** 单算例 10 次中，MV 对 F/E/M 为 10/0/0、9/1/0、10/0/0，但 CPU 为 1.84 min，对三个单视角仅 0.50/0.63/0.64 min（`paper_main.tex:1252-1257`）。China81 虽有 F/E/M/MV 的 405 单元，却按“每视角 25000 次迭代”运行，融合体没有共享总预算（`paper_main.tex:1225-1228,1296,1327-1329`）；公开 V13 又在机制字段缺失时自然退化（`paper_main.tex:1110`）。因此现有数据没有一个只改变“三视角”且保持总算力、路线池和 SP 不变的一因素对照。更早的三题等算力开发门也只得到对 homogeneous-CV 1/0/2、对两个 EV 对照各 1/2/0，结论为 `HOLD_MVHGS_ALNS_EQUAL_COMPUTE_GATE`（`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/g4_equal_compute_gate/decision.json`）；它不是当前 405 单元正式证明。

**判定。** 形式上有可辨认差异，但实证没有隔离该差异；可辩护为工程构造，不能由当前公开基准或 China81 结果单独支撑“算法创新”。

### 4.2 跨轮累积路线池 + 限时 MIP 集合划分

**最接近工作及差异。** Rochat & Taillard (1995), DOI `10.1007/BF02430370`, 作者稿 PDF pp.3--5 已把历次优质解的路线加入集合 `T`、反复从池中重组并回填；pp.4--5 写出由池路线构成的 set-partitioning，p.7 用 CPLEX 精确求解并在 Table 4 单列 post-optimization 值与时间。Wang et al. (2025) PDF pp.13--18 更直接采用“问题专用路线评价/ILS 生成高质量路线池 + set-partitioning 重组”。本文差异是三个机制视角、跨外层轮次永久累积、完整 ReSETP 复算与限时求解；“路线池 + SP”核心本身已有同类先例（`components.json` 条目 `跨轮累积...路线池` 与 `限时MIP路线池集合划分`）。

**仓库能否反驳“常规做法改名”。不能，且有反向证据。** 公开热启动复现的 18 个目标只过 13 个，只有 PR14B 的 **0.183** 可严格归因 SP（`mvhgssp_bks_reproduction_full_20260727/{decision.json,report.md}`）。公开诊断中，单次运行池扩到原来的 6--8 倍后仅 3 胜3负、合计改善 0.0882%；12 次初始诊断的最终解 12/12 都来自 HGS epoch 而非 SP（`baselines/algorithm_prototypes/boundary_probe_20260726/report.md` 第 4、7 节）。这些数据证明 SP 能偶尔重组出更好解，不证明跨轮池化是稳定竞争力来源。

**判定。** 核心做法是成熟路线池 matheuristic；当前可辨差异没有被一因素数据支撑，不能独立承担算法创新。

### 4.3 严格改善才接受的单调规则

**最接近工作及差异。** Lei & Hao (2026) Algorithm 1（PDF pp.8--9）只在 `f(S')<f(S*)` 时更新全局最好解；Zhao et al. (2024) PDF pp.9--10 使用 survivor/diversification 并保留最优；它们都是常规 incumbent/elitist preservation。本文额外把每轮 `min(current,SP)` 的结果写回三个视角共同起点并跨轮累积（`paper_main.tex:1225-1228`）；所查原文没有这整个同形链，`components.json` 的 `严格改善才接受、写回共同起点与外层收敛` 条目也只判“查不到同形原文出处”，同时注明其可退化为普通精英保存。

**仓库能否反驳“常规做法改名”。不能。** China81 的 `M_to_MV={improve:114, regress:0, tie:291}`（`baselines/algorithm_prototypes/china81_vs_opensource_20260727/decision.json.transition_counts`）与正文 114/291/0（`paper_main.tex:1324`）中的“0 回退”由 `min` 规则机械保证；没有关闭该规则或采用另一接受准则的对照。114 次改善同时含三视角、额外搜索、路线池和 SP，不能归给接受规则。

**判定。** 完整写回链在形式上未见同形出处，但“只更新更好 incumbent”是常规安全网；零回退是定义后果，不是独立性能证据，不能独立承担算法创新。

### 4.4 0.069%--0.085% 融合增量的来源与公平性

两个数来自 China81 的 **405 个实例--种子单元**。对每个单元分别计算

`100 × (C_arm − C_MV) / C_arm`

再对 405 个百分比取算术平均；实现位于 `docs/paper_v2/figures_e2_v2_20260730/generate_e2_v2_outputs.py:718-731`。对 HGS-E 得 `125/280/0` 和 **0.069133%**，对 HGS-M 得 `114/291/0` 和 **0.084730%**（`docs/paper_v2/figures_e2_v2_20260730/report.md` 第 5 节；正文舍入为 0.069%/0.085%，`paper_main.tex:1319-1329,1363-1369`）。

这个对照对“固定协议下 MV 终值不差于 E/M”是公平的：同一 405 单元、同一完整评分器、同一 F/E/M/MV 封存批（`china81_vs_opensource_20260727/decision.json.protocol_disclosure.F_E_M_MV="sealed v7 fixed-iteration archive reuse"`）。它对“融合算法带来净增益”不公平：E/M 是单视角 25000 次迭代，MV 同时承担三个视角、路线池和 SP，正文明确“不切分一个总预算”（`paper_main.tex:1225-1228,1296`），封存账本又有 `archive_wallclock_available=false`。所以 0.069%/0.085% 是**不等总算力的完整组合终值差**，不是三视角、SP 或单调接受任一部件的因果增量。

## 五、终局判定

| 问题 | 判定 |
|---|---|
| 公开标准算例有没有逐实例 BKS gap | **有**；正文已给舍入值，仓库有精确值 |
| 冷启动结果是否具竞争力 | **具竞争力**；平均 Best gap 0.904871%，为表内最低，19/28 优于 ETGA；但仅 1/28 达到、0/28 改进 2013 BKS |
| “当前 BKS”表述是否有证据 | **没有**；实际字段为 `bks_2013`，仓库无外部当前 BKS 注册表 |
| 比较协议能否判断净算法优势 | **不能**；不同停止/不等 CPU，公开表缺秒数与硬件；等迭代检验 `p=0.2894` |
| 三视角是否由现有数据独立支撑 | **否**；无等总算力一因素对照 |
| 路线池 + SP 是否为新的核心做法 | **否**；Rochat--Taillard 1995 与 Wang 2025 已有直接先例，仓库仅一题有严格 SP 归因 |
| 单调接受是否为独立算法创新 | **否**；属于 incumbent 安全网，零回退由定义保证 |
| 论断 A | **部分成立：目标值竞争力分支被推翻，协议与归因不足分支成立** |

## 六、取证来源

仓库原始证据：

- `docs/paper_v2/paper_main.tex:1097-1233,1251-1266,1296-1369,1631-1661`
- `baselines/e2_final_campaign_20260720/mv_hgs_sp_final/p1_formal_gate/{decision.json,metadata.json,raw_runs.csv}`
- `baselines/e2_final_campaign_20260720/p2p3_threeview/artifacts/table5_public_v4.csv`
- `baselines/algorithm_prototypes/boundary_probe_20260726/{NEW_BKS_TABLE.csv,d4_summary.json,report.md}`
- `baselines/algorithm_prototypes/mvhgssp_bks_reproduction_full_20260727/{decision.json,metadata.json,README.md,report.md,NEW_BKS_UPDATES.csv}`
- `baselines/algorithm_prototypes/china81_vs_opensource_20260727/{decision.json,raw_runs.json}`
- `docs/paper_v2/figures_e2_v2_20260730/{generate_e2_v2_outputs.py,report.md}`
- `docs/handoff/model_scope_reduction_review_20260802/{components.json,gaps.json,report.md}`

文献页级证据：Vidal et al. (2013) 作者公开稿 PDF pp.16--17,20--23；Lei & Hao (2026) PDF pp.20--21,36,39；Schneider et al. (2014) PDF pp.11--16；Goeke & Schneider (2015) PDF pp.10--12,15--16；Zhao et al. (2024) PDF pp.9--11；Rochat & Taillard (1995) 作者稿 PDF pp.3--5,7--8；Wang et al. (2025) PDF pp.13--18；陈婉茹等 (2023) pp.3328--3331。
