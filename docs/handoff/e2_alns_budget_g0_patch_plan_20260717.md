# ALNS 完整方案评价预算 G0 闭合合同

状态：2026-07-17 方案冻结；E7 十步收口完成前只允许只读审计、合同和测试准备，禁止修改共享 `winner.py`、评价器、成本函数、物理约束或 E7 保护源。

## 1. 为什么必须先做 G0

零搜索静态审计在 ALNS 包中识别出 31 个相关完整方案评分调用点，其中 5 个已明确计入 `EvalBudget`，24 个仍会阻断预算闭合；历史探针另确认 9 次运行存在 11,547 次未计入正式预算的完整解评分，实际评分数与报告评价数之比均值为 13.830。由此，旧稿中“统一 4,000 次完整方案评价”的算法横向比较、显著性检验和收敛解释暂时不能作为投稿证据。

G0 的目标不是让算法跑得更好，而是把“什么叫一次完整方案评价”变成可执行、可复算、绝不超限的合同。G0 通过前，不得启动 Homberger 开发搜索、Solomon 正式测试或基于旧口径重写算法优越性结论。

## 2. 统一评分边界

E7 释放共享源后，新增：

`solver/src/setp_solver/algorithms/resetp_alns/runtime/budgeted_scoring.py`

该模块只暴露下列概念接口：

```python
class SearchBudgetExhausted(RuntimeError):
    pass

def remaining_search_evaluations(context) -> int: ...
def can_score_search_candidate(context) -> bool: ...

def score_search_candidate(solution, context, *, channel: str): ...
def score_reference_solution(solution, context, *, phase: str): ...
def reference_model_cost(solution, context, *, phase: str): ...
def cached_or_reference_model_cost(solution, context, *, phase: str): ...
```

统一语义如下。

1. 搜索期间，任何会参与候选选择、接受、拒绝或更新最好解的完整方案，只能通过 `score_search_candidate` 评分；一次底层完整方案评分严格对应一次候选预算。
2. 初始解、最终解、历史记录、断点、确定性充电后处理等不参与搜索选择的复算，必须走 reference 通道；它们不占搜索预算，但按阶段独立计数，不能消失在日志之外。
3. 路线级成本增量继续走 repair-delta 通道；路线增量不得被用来掩盖一个未经计费的完整候选。
4. 候选接口必须在调用底层 scorer 以前检查 `count >= target_count`。旧 `EvalBudget.record()` 的“先加一、后抛错”不能作为唯一防线；计数永远不得出现 `target+1`。
5. 正式评价预算下，`_budget_limit()` 收紧为合同目标值；前置检查与下层上限形成双门。
6. 现有静态 HALT 五记录面原样保留；修复后另建 G0 五记录面，不得覆盖或改写历史不利证据。

## 3. 24 个阻断点的处置原则

### 3.1 核心状态与主循环

- `AlnsState.objective` 删除隐式 reference 评分回退。若 `objective_value` 缺失，直接判内部状态错误，避免一次属性读取触发重复评分。
- 初始方案使用 `score_reference_solution(..., phase="initial")`；搜索候选重排后的完整方案使用候选通道。
- 删除没有调用者的 `_repair_solution_delta_score` 及其内部完整评分。
- 已经带有 `best_cost` 或 `best_obj` 的阶段结果直接复用缓存，不得为阶段选择再次调用 `model_cost`。
- 搜索预算耗尽时，在动作边界停止产生下一候选并保留当前 incumbent；`SearchBudgetExhausted` 只作为遗漏保护，不能逃逸到正式 runner 造成整项失败。

### 3.2 报告、历史、断点与确定性后处理

- final reporting、initial/final reference、充电后排班等走明确 phase 的 reference 通道。
- 历史和 checkpoint 优先复用 `score_breakdowns[id(solution)]["raw_cost"]`；缓存确实缺失时才触发 reference 复算。
- broad `except Exception` 不得吞掉预算终止或合同错误。

### 3.3 局部搜索与跨场候选

- 跨场注入后的完整方案是新搜索候选，必须计费。
- 局部搜索复用调用者传入的 incumbent objective；每个完整邻居逐一通过候选通道评分，并返回已评分的 `(solution, objective)`，外层不得重复收费。
- RVND、scan restart、strong bridge 和 relaxed retry 在剩余预算不足时停止下一个完整候选，不能先评分再报超限。

### 3.4 碳算子与可行修复

- 碳算子的方案总碳特征改为各路线碳量求和，不再调用完整方案 evaluator；需在燃油车、电动车和混合车代表解上验证其与原 `E_total` 数值等价。
- 可行修复中，若路线级增量不可得，返回预先定义的大惩罚值，不以尚未完成或缺客户的完整方案成本参与修复排序。

### 3.5 全局重装和车队—充电联合修复

- `GlobalRepackOutcome` 与 `FleetChargeOutcome` 增加 `objective` 和 `evaluations_used`。
- 当前解成本从调用者缓存获得；内部每个新完整候选各收费一次，最优候选携带已评分 objective 返回；外层不得再次评分。
- 剩余预算不能覆盖下一候选时，返回当前最好已评分结果，不生成半评分候选。

## 4. 实施顺序

1. E7 完成十步收口后，冻结全部修改前传递源哈希。
2. 新增统一评分模块和纯 API 单元测试；此时仍不改变算法策略。
3. 收紧预算上限，删除隐式 objective 评分和死函数。
4. 先迁移不改变搜索轨迹的初始、终局、历史、断点和后处理 reference 复算。
5. 重构局部搜索的 objective 传递与逐候选收费。
6. 重构碳特征和可行修复 fallback，并完成等价性测试。
7. 重构 global repack 和 fleet-charge co-repair 的内部计费及返回结构。
8. 最后接入 `winner.py` 的候选入口、预算耗尽控制和 staged 汇总。
9. 运行新 G0 静态与行为审计，生成新的五记录面。
10. 所有 G0 门通过后才冻结新算法哈希；随后才能进入 Homberger G1 开发。

G0 阶段不顺手调整 UCB、模拟退火温度、算子权重或接受准则。完整评分数闭合后，外层 move 数必然下降、各算子的预算份额也可能变化；这些只记录为版本语义变化，留到 G1 再判断，避免把正确性修复和性能调参混成一次不可解释改动。

## 5. 必须覆盖的行为测试

新增 `solver/tests/test_alns_budget_accounting_g0_20260717.py`，至少覆盖：

- `target=0` 时初始与终局 reference 可以运行，但候选数和搜索预算均为 0；
- `target=1/2/3/7` 时，`evaluations == candidate_scores == target`，且底层完整 scorer 从不执行第 `target+1` 次；
- initial、final、history、checkpoint 等 reference 分相计数，但不改变候选预算；
- local search 邻居全部逐候选计费，incumbent 不重复评分；
- relaxed retry、strong bridge、scan restart、RVND、global repack 和 fleet-charge 在极小剩余预算下均干净停止；
- 结构算子内部完整候选一对一计费，外层不重复收费；
- 碳特征路线求和与旧 `E_total` 在 CV、EV、混合代表解上等价；
- repair route-delta 失败时不调用完整 evaluator；
- E3 strict multi-trip 下返回的 prepared solution 被保留，计数仍一对一；
- 同实例、种子、预算重放时，最终解签名、计数和停止位置一致；
- 最终保存解由独立 evaluator/checker 复算，目标值一致且硬违约为 0；
- staged run 只复用阶段缓存，不产生隐藏评分；
- 静态审计对 ALNS 包内任何新增直接 `evaluate`、`model_cost`、`score_reference` 或 `prepare_and_score_*` 调用硬失败。

既有测试调整边界：保留历史 HALT 测试；把“存在隐藏局部评分”的断言改为隐藏评分为 0；把 `actual_moves == evaluations` 改为 `0 < actual_moves <= evaluations`，因为一个外层 move 可以合法消费多个完整候选评价。

## 6. G0 通过标准

以下条件必须同时成立：

1. 新静态审计为 `BLOCK=0`、`unclassified=0`；除统一评分模块和明确的路线级函数外，ALNS 包内没有直接完整 scorer。
2. 零预算和极小预算覆盖默认路径、局部搜索、碳算子、scan、strong bridge、RVND、global repack、fleet-charge 和 E3 strict 路径。
3. 搜索期完整方案评分与预算严格一对一：`evaluations == candidate_scores == requested_target`，任何时刻不超过 target。
4. candidate、reference 和 repair-delta 三类计数分别可见，其总量与底层探针闭合。
5. 保存的最终解独立复算一致、硬违约为 0、同种子可重放。
6. 旧 HALT 证据原样保留，新 G0 五记录面、源码哈希、依赖和测试结果齐全。
7. 任一条件失败，继续判 `HALT_ALNS_BUDGET_CLOSURE_REQUIRED`，不得启动 Homberger 或 Solomon 胜负搜索。

## 7. 对旧实验和论文的影响

G0 会改变一次固定评价预算中能够完成的外层动作数，因此旧 E2 算法比较、消融、收敛曲线及其显著性不能直接沿用。若最终算法版本改变，还必须依照总完成矩阵统一识别并重跑受影响的 E2--E7；旧结果保留作版本历史，禁止与新版本结果拼成一套论文证据。

公开 Benchmark 与自有模型实验继续分工：Solomon/PyVRP 等只回答通用 VRPTW 求解能力，自有复杂网络上的连续 ALNS、LNS、结构消融只回答本文算法嫁接是否适配多车场、多趟、充电和参与约束。两个问题、两套公平轴、两张表，不混为“算法全面领先”。
