# E2 算法收敛图与消融表报告

- 任务日期：2026-07-30
- 数据边界：只读已封存数据
- 新实验运行数：0
- 终局依据：`docs/handoff/e2_final_closeout_20260727.md`
- E2 状态：`ALGORITHM_EXPERIMENTS_CLOSED_WITH_MIXED_EVIDENCE`

## 1. 结论

封存数据足以生成合规的收敛图，但只覆盖 HGS-F、HGS-E、HGS-M 和
MV-HGS-SP 四条曲线；O 臂没有逐点目标轨迹，因此没有把 O 的终值扩展成伪曲线。
本目录已输出矢量 PDF、300 dpi PNG、曲线数据 CSV、消融表 CSV 和 LaTeX 源码。

主图使用结果产生前冻结的中等规模展示算例
`cn-prd-100c-01-V2-LOCATIONS`，固定使用 seed 1。该算例的登记角色是
`iteration_display_case`，登记文件同时明确
`may_be_called_statistically_representative=false`，因此本文只能称其为“预登记展示
算例”，不能称其在统计意义上代表全部 China81。总体关系由完整的 81 个算例 × 5
个种子矩阵给出。

## 2. 封存数据调查

### 2.1 最终值与消融矩阵

权威文件为
`baselines/algorithm_prototypes/china81_vs_opensource_20260727/raw_runs.json`，
SHA-256 为
`4291ee24707bcf834c6cf6ff6b308a14eab4b4a6a3011681408935e8693e070c`。
该文件含 2025 行，即 O/F/E/M/MV 五臂各 405 行，覆盖 81 个算例和种子
1--5。可用字段包括 `arm`、`instance_id`、`seed`、`final_cost`、
`route_count`、`ev_route_count`、`cpu_seconds`、`wallclock_seconds`、
`stop_iterations`、`budget_rule`、`data_source`、`status` 和 witness 路径。

其中 `wallclock_seconds` 在 F/E/M/MV 的 1620 行中为空，五臂共同可用的时间字段只有
`cpu_seconds`，所以消融表报告平均 CPU 时间，并明确其只作描述。脚本逐一读取 2025
行指向的封存 witness，核对 `route_count` 等于路线数且所有路线的 `vehicle_id`
互异，因此表中的“车辆数”可由该字段直接报告。

### 2.2 逐点轨迹

最终 v7 正式目录
`baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/full_gate/tasks/`
含 405 个正式 `trajectory_observations.json`，与 81 × 5 个正式单元逐一对应。每份
轨迹均覆盖 HGS-F、HGS-E、HGS-M 和 MV-HGS-SP，逐点字段为
`elapsed_seconds`、`objective`、`phase`、`source` 和 `view`。正式 v7 汇总文件还记录
每任务 280 次完整候选评价尝试，但轨迹点没有对应的逐点评价序号，因此不能把 280
平均分配或推定到各检查点。

本图使用的精确轨迹文件为
`full_gate/tasks/D6-E2-STAGED__cn-prd-100c-01-V2-LOCATIONS__seed1/trajectory_observations.json`，
SHA-256 为
`fabeb5fcc0faf8288da3c1cdda1c3964472689998d4ca470e647bb3aeb974c66`。
该文件含 HGS-F/E/M 各 41 个实际检查点、MV-HGS-SP 122 个实际检查点，共 245 点；
各曲线末点与最终值账本在绝对容差 `1e-9` 内一致。

O 臂目录
`baselines/algorithm_prototypes/china81_vs_opensource_20260727/tasks/` 只有最终
`solution_witness.json`；总账只有 `final_cost`、`stop_iterations` 和时间字段，没有
中间 incumbent、逐迭代目标值或逐评价目标值。因此 O 臂不能进入收敛图。

`baselines/e2_alns/` 中虽有大量历史 trace，但它们属于已退役 ALNS 探针或其他算法
诊断，不是最终 MV-HGS-SP 五级身份的同一封存批，未被混入本图。
`p2p3_threeview/s6_support/s6_sup_02_figure_v7/` 也有一份较早的 29 行展示曲线；本次
没有使用它，而是直接读取 2026-07-24 最终 v7 的真实在线检查点。

## 3. 收敛图口径

横轴采用时间（min）。选择时间而不是评价次数的原因是：封存轨迹对每个实际检查点保存
了 `elapsed_seconds`，但没有保存逐点完整候选评价序号；只知道每任务总评价次数不足以
重建逐点评价横轴。该选择也与陈雨蝶等（2025）图 4 在算法迭代口径不同时采用时间横轴
的做法一致。

纵轴为“截至该时点已观察完整模型检查点的累计最低成本”。输出数据
`fig_e2_convergence_data.csv` 同时保留原始 `observed_cost_cny` 和派生的
`best_so_far_cost_cny`，可直接审计累计最低变换。图中没有平滑、插值、补点、断轴或
离线替换候选。

为避免结果后挑选曲线，算例沿用结果产生前冻结的展示算例，种子固定为最小正式种子
seed 1，四臂使用同一个种子。旧预登记原计划另跑种子 6--10 后按十种子均值选种子，
但该阶段被当时的上游强度门阻断；本任务禁止新实验，故没有补跑，也没有用五种子结果
重新挑选“好看”的种子。

视觉编码严格采用用户指定规范：

| 算法 | 颜色 | 线型 |
|---|---|---|
| HGS-F | 蓝色 | 虚线 |
| HGS-E | 绿色 | 虚线 |
| HGS-M | 紫色 | 虚线 |
| MV-HGS-SP | 红色 | 实线 |

图例置于图内右上方空白区。PDF 使用嵌入的 macOS Heiti 中文字体，中文标签无方框；
PNG 为 1882 × 1191 像素，按 300 dpi 输出。建议图注保持中性名词短语：
“不同算法迭代图”。横轴和累计最低口径放在正文说明，不把结论写进图注。

## 4. 消融表口径与结果

表中每行一个算法臂。`Best` 是先在每个算例的五个种子中取最低成本，再对 81 个算例
等权平均；`Avg` 是对全部 405 个实例--种子单元等权平均。`Gap%` 定义为

\[
100\times\operatorname{mean}\left[
\frac{C_{\mathrm{arm}}-C_{\mathrm{MV}}}{C_{\mathrm{arm}}}
\right],
\]

正值表示 MV-HGS-SP 的配对成本较低。标准差未列入主表，以对齐目标期刊多数算法表的
报告方式；原始 405 单元仍保留在权威封存账本中。

| 算法臂 | Best（元） | Avg（元） | Gap% | 平均车辆数 | 平均 CPU（min） | MV 胜/平/负 |
|---|---:|---:|---:|---:|---:|---:|
| O（纯距离开源） | 3609.597 | 3615.557 | 1.919 | 12.111 | 0.759 | 354/46/5 |
| HGS-F | 3587.524 | 3592.472 | 1.059 | 12.165 | 1.852 | 307/98/0 |
| HGS-E | 3558.578 | 3563.655 | 0.069 | 12.207 | 2.081 | 125/280/0 |
| HGS-M | 3558.450 | 3566.005 | 0.085 | 12.230 | 2.104 | 114/291/0 |
| MV-HGS-SP | 3556.687 | 3559.608 | 0.000 | 12.178 | 6.209 | 0/405/0 |

MV 对 O 的 354 胜、46 平、5 负及配对平均成本改进
`1.919118015025895%` 与终局裁决一致。相邻层转移计数也逐项复核为：
O→F 268/115/22，F→E 290/86/29，E→M 79/249/77，M→MV
114/291/0；完整非增阶梯只在 299/405 单元成立。由此可以单独报告
M→MV 在该矩阵中不回退，但不能把完整五级写成逐层普遍单调贡献。

## 5. 计算口径披露与主张边界

O 臂来自新的 `NoImprovement(3000)` 收敛式批次；F/E/M/MV 来自
2026-07-24 v7 固定每视角 25000 次迭代的封存批。两组数据不是同批、同机、同停止
规则或等算力。表中 CPU 时间用于满足描述性报告需要，不能据此构造等算力效率结论。
同样，图只比较同一 v7 批内 F/E/M/MV 的实际运行轨迹，不包含 O。

本报告和正文段落不声称 China81 逐单元全面支配，不声称
O→F→E→M→MV 每层机制全面单调贡献，不声称公开 18 个新 BKS 均由本文算法复现，也
不声称 MV-HGS-SP 在公开算例上普遍或等算力优于纯 HGS。公开固定协议的真实边界仍为
13/18 复现；本地独立认证候选不等同于社区已接受 BKS。

## 6. 可直接用于正文的段落

图 X 给出了结果产生前冻结的中等规模展示算例
`cn-prd-100c-01-V2-LOCATIONS`（seed 1）在封存运行中的完整模型检查点累计最低成本，
横轴为实际运行时间；表 X 汇总了 China81 的 81 个算例和 5 个种子结果。MV-HGS-SP
相对纯距离开源 O 臂取得 354 胜、46 平和 5 负，配对平均成本降低 1.919%；相对
HGS-F、HGS-E 和 HGS-M 分别为 307/98/0、125/280/0 和 114/291/0，其中 M→MV
未出现回退。需要说明的是，O 臂来自 `NoImprovement(3000)` 新批次，F/E/M/MV
沿用 2026-07-24 固定迭代封存，二者并非同批、同机、同停止规则或等算力，因此上述
结果只作统一完整模型评分下的总体比较，不作等算力优越性解释。

建议图注：**不同算法迭代图**

建议表注：**E2算法消融结果**

## 7. 交付文件

| 文件 | 内容 |
|---|---|
| `fig_e2_convergence.pdf` | 收敛图矢量 PDF |
| `fig_e2_convergence.png` | 收敛图 300 dpi PNG |
| `fig_e2_convergence_data.csv` | 245 个原始检查点及累计最低成本 |
| `table_e2_ablation.csv` | 五臂消融汇总及相邻层计数 |
| `table_e2_ablation.tex` | LaTeX 三线表源码 |
| `generate_e2_outputs.py` | 只读封存数据的可复现生成脚本 |
| `artifact_hashes.json` | 交付产物及两项权威输入的 SHA-256 |
