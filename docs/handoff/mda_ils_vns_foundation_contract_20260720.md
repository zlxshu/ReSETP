# MDA-ILS-VNS 强母体基础合同

- 编号：`MDA-ILS-VNS-F0-001`
- 日期：2026-07-20
- 状态：`USER_AUTHORIZED_AUTONOMOUS_EXECUTION__PREREGISTERED_BEFORE_CODE`
- 目的：先把公开 `V13-MDVRPTW-28` 的路由母体做强，再建设机制化自适应控制；
  不抢跑完整 28 题、China81 或阶段二。

## 1. 用户目标与本合同职责

用户最终要的是一套有清楚混合故事、公开题成绩强、China81 明显胜母体，并能支撑
E1--E7 后续实验的算法。算法名称、母体数量和参数均不预设；以结果为根本，但不得
改计分、改题、删负例或把弱证据写成胜利。

本合同只承担第一块基础：保留 PyVRP 0.13.4 ILS 的高速局部搜索，在刷新最好解时
选择性调用其原生 `SwapStar` / `SwapRoutes` 路线级精修，并在开发块上做一次受控
题族配置竞赛。它不复活已经 STOP 的 C2 固定停滞替换，不接 HGS 外挂，不维护每轮
Python 精英档案，不做无条件末尾路线会审。

## 2. 依据

1. PyVRP 0.13.4 源码默认只装节点级算子，路线级 `SwapStar` 与 `SwapRoutes`
   已存在但默认列表为空；ILS 只在新最好解上另做一次 exhaustive search。
2. Vidal 等（2013、2014）的粒度邻域、路线级移动和多属性统一局部搜索直接面向
   多车场与时间窗问题。
3. Lei 与 Hao（2026）的 MDFIHA 消融表明，多车场专用车场移动、动态罚分和
   可行/不可行联合搜索是有效部件；其论文值并不是当前 BKS，因此只借设计思想。
4. ReMIX、MPILS-MVNS-C1/C2 的共同死因是外置层或高频 Python 记账偷走强母体时间；
   本包把昂贵路线精修限制到“新最好解”事件，不增加并行工种。

## 3. 保护边界

允许新增：

- `baselines/algorithm_prototypes/mda_ils_vns_20260720/`
- `baselines/algorithm_foundation/mda_ils_vns_foundation_20260720/`
- 本合同、来源登记、审批登记和任务完成后的 HANDOFF / memory 记录。

禁止修改：

- `solver/src/setp_solver/cost.py`
- `solver/src/setp_solver/check.py`
- `solver/src/setp_solver/search/evaluation.py`
- `solver/src/setp_solver/prices.py`
- `docs/paper_submission_final/paper_main.tex`
- PyVRP 隔离环境和其安装文件
- 既有失败证据目录

本包不跑 China81、不跑完整 28 题、不进入阶段二、不形成论文优胜结论。

## 4. 候选与参数边界

第一轮只在开发题 `PR17A`、seed 1、每臂 20 秒比较下列预登记配置：

1. `default`：原装 PyVRP 0.13.4 ILS。
2. `swapstar_best`：只在 exhaustive / 新最好解精修时启用 `SwapStar`。
3. `swaproutes_best`：同上，只启用 `SwapRoutes`。
4. `route_vns_best`：同上，依次启用两种路线算子。
5. `route_vns_k80`：配置 4 + 80 个粒度邻居。
6. `route_vns_tw_k80`：配置 5 + 等待权重 0.5、时间窗违约权重 2.0、对称邻居。
7. `route_vns_restart75k`：配置 4 + 75,000 次无改进重启、历史长度 600。
8. `route_vns_perturb5_40`：配置 4 + 每次 5--40 个原生扰动。

这些常数是结果前冻结的有限候选，不是文献原参数主张。第一轮按目标值选前三名；
第二轮只在 `PR11A/PR17A/PR21A`、seed 1、每臂 30 秒比较前三名与 default，
按三题平均 BKS gap 选唯一候选。相同均值时依次按最坏 gap、总目标和配置名裁决。

## 5. 未见验收块

唯一候选与 default 在 `PR11B/PR17B/PR21B`、seeds 1--2、每臂 60 秒、单线程、
同批运行。验收要求同时满足：

- 12 个解全部完整、可行、独立复算通过；
- 候选六对合计目标严格低于 default；
- 至少 4 胜，最多 1 负；
- 任一负例退步不超过 0.25%；
- 平均 BKS gap 至少比 default 低 0.10 个百分点；
- 端到端墙钟合规，全部第三方代码来源与许可闭合。

未过即 `STOP_MDA_ILS_VNS_FOUNDATION_NO_VALIDATED_GAIN`，不在 B 组调参数、不换题
救援。通过才允许另立自适应控制合同；是否追加 300 秒长门由本包结果决定，但不得
自动扩大到完整 28 题或 China81。

## 6. 证据与停止

输出必须包含 `metadata.json`、`raw_runs.csv`、`decision.json`、
`artifact_hashes.json`、`report.md`，保存每次完整路线。哈希排除 `._*`、
`__pycache__`、`.pytest_cache`。任何验解失败、保护文件漂移、结果目录预先存在、
运行前 Git 非预登记状态或许可证缺口均立即 HALT。

本合同的“通过”只证明强母体配置在小型开发/验收块有稳定向好，不等于新 BKS、
公开一骑绝尘、China81 碾压或最终算法完成。
