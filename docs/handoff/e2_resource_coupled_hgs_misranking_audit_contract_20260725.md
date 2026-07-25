# E2 资源耦合 HGS：代理误判零搜索审计合同

- 编号：`E2-RCE-HGS-MISRANK-001`
- 日期：2026-07-25
- 状态：`USER_APPROVED__ZERO_SEARCH_CAUSAL_GATE_ONLY`
- 保护备份：现有三视角 HGS 及其全部封存证据保持只读。

## 1. 决策问题

本门只回答一个问题：现有 HGS 的半载重、最低时段能源成本代理，是否会把完整
China81 模型下更好的客户次序排到后面，从而在进入完整评价前错杀。

本门不是新算法性能实验，不运行 HGS，不接受或迭代任何候选，不改变任何封存成绩，
不授权论文、E3、公开 BKS/SOTA 或“视角互补”主张。

## 2. 与已停止路径的边界

以下候选保持最终停止，不得复活、调参或改名重试：

- `HGS-ILS-XD` 及顺序交接；
- `TAILORED-DP-VNS`、`FEASIBILITY-GUIDED-EJECTION-VNS`；
- 通用 ALNS/ILS/VNS、HGS+RR 和 ReMIX；
- 固定次序 Split/重切、路线池/路线列 MIP；
- 对偶引导有限位移次序重构；
- 资源—时隙定价路线生成；
- JRC 客户块精确排列。

本门不得执行上述算法。它只从封存强 HGS-M 解生成一组固定、非迭代、非接受的
一至两路线顺序扰动，分别记录旧代理排序与完整模型排序，以验证新机制的必要前提。

## 3. 冻结输入

使用 v7 封存的三题、两个种子 HGS-M witness，共六个独立任务：

- `cn-jjj-50c-02-V2-LOCATIONS`，seed 1、2；
- `cn-cy-100c-01-V2-LOCATIONS`，seed 1、2；
- `cn-prd-200c-02-V2-LOCATIONS`，seed 1、2。

每任务必须先独立重放 witness：完整检查零违约，精确成本与 v7 `raw_runs.csv`
中的 `HGS-M_cost` 在 `1e-9` 相对容差内闭合。

## 4. 固定候选集

每任务最多 96 个不同结构，按候选签名去重：

- 24 个单客户跨路线 relocate；
- 24 个跨路线 customer swap；
- 24 个路线内 segment reversal；
- 24 个跨路线 tail exchange。

候选按实例 ID、seed、动作类型、路线索引和位置索引的固定 SHA-256 顺序选取。
不得读取候选成本后补候选、换候选或改变动作配额。不得连续接受候选；每个候选都
相对原封存 witness 独立生成。

## 5. 两种排序与完整复算

旧排序严格复用 `build_pyvrp_problem(..., route_proxy_mode="mechanism_ev")` 的代理
弧成本口径，不修改 PyVRP 或保护文件。

完整排序对每个候选只调用现有共同
`complete_china81_route_skeleton()` 和 `exact_china81_score()`，并保存可行性、
完整目标、旧代理值、动作类型及候选签名。完整评价用于审计，不反馈任何搜索。

## 6. 通过与停止

六任务全部完成且无保护漂移后，只有同时满足下列条件才判因果前提成立：

1. 至少 5/6 任务中，旧代理与完整目标存在严格排序逆转；
2. 至少 4/6 任务存在完整模型严格改善候选；
3. 至少 4/6 任务中，完整模型最优的改善候选不在旧代理前八名；
4. 50/100/200 三个规模中至少两个规模满足第 2、3 条；
5. 所有记为可行的候选均经独立完整检查零违约；
6. 候选生成、评分计数和六任务账本闭合。

通过判：
`PASS_RCE_HGS_PROXY_MISRANK_CAUSAL_GATE`。

任一条件失败判：
`STOP_RCE_HGS_NO_VERIFIED_PROXY_MISRANK_HEADROOM`。

停止后不得在这六个任务上增加候选数、改变动作、换种子、换 witness、放宽阈值或
转入性能搜索。通过也只授权另立资源耦合评价器的 6 客户等价性工程门，不自动授权
性能实验。

## 7. 执行与保护

- 六任务资源安全时使用 6 workers；
- 不修改 `cost.py`、`check.py`、`search/evaluation.py`、`prices.py`、PyVRP、
  China81 完成器、主 TeX、v7 结果或历史失败目录；
- 运行前冻结 runner、合同、六份 witness、对应 v7 行、实例输入和保护文件哈希；
- 输出 `metadata.json`、`raw_runs.csv`、`decision.json`、
  `artifact_hashes.json`、`report.md`；
- 任一哈希漂移、路径身份错误、任务重复/缺失、资源危险或异常退出均立即 HALT，
  不自动修复或重启。

