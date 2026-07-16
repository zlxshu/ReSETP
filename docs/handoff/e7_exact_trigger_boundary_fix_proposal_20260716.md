# E7 充电恰逢触发时刻的边界修复提案

日期：2026-07-16  
状态：`AUTHORIZED_APPLIED__PARENT_CHILD_RECOVERY_FIRST_TASK_RUNNING`  
适用异常：`N322__historical_mixed__stream1__no_participation`

## 1. 已证实的根因

正式批在 `e7_full_mechanism_probe_20260714.py::_charging_window_witness()` 抛出：

```text
unstarted charging action was marked locked: EV_D1_5#T2
```

动态切分合同 `cut_certificate_at_trigger()` 与
`cut_dynamic_certificate_at_trigger()` 均把
`absolute_charge_start <= trigger_second` 的充电动作列入锁定集合。见证函数却只把
`absolute_charge_start < trigger_second - TOL` 识别为触发时正在进行。动作恰好在触发时刻
开始时，前者锁定、后者判为尚未开始，两个同一时刻的边界定义不一致。

新增回归测试：

```text
solver/tests/test_e7_full_mechanism_gate.py::
test_charging_window_witness_treats_exact_trigger_start_as_locked
```

当前保护源下结果为 `1 failed, 1 passed`；失败位置和正式异常相同，证明无需用历史动作漂移、
动作键变化或无效断点解释本次错误。

## 2. 最小修复

受保护文件：

```text
baselines/e7_dynamic/e7_full_mechanism_probe_20260714.py
```

只修改见证函数的一个边界判断：

```diff
-        elif absolute_original < float(trigger_second) - TOL:
+        elif absolute_original <= float(trigger_second) + TOL:
```

含义：充电在触发时刻已经开始，或者仅存在浮点容差内的时刻差时，固定其原开始时刻，
记录为 `in_progress_at_trigger_fixed`。该修改不移动充电、不改变充电量、不改变路径、车辆、
预算、事件流、评价器或任何封存结果。

## 3. 为什么不能简单改为“跳过异常”

跳过该动作会使完整全日充电窗口账本少于最终充电动作集合，破坏
`set(charging_windows) == full_day_action_keys`；删除锁定动作又会改变触发时车辆电量和可用时刻。
最小修复必须保留动作并给出固定窗口，而不是吞掉异常、删除动作或放宽最终账本闭合门。

## 4. 批准后验证顺序

1. 记录修改前保护哈希和本提案；
2. 应用上述单行修改；
3. 运行全部 `test_e7_full_mechanism_gate.py`；
4. 运行动态多趟调度器相关测试，确认完成、进行中、恰逢触发和未来动作四种边界；
5. 建立并审计父—子恢复合同：旧102个断点继续绑定父合同且只读保留，修复后的18个缺口绑定子合同并写入独立断点区；
6. 先只复跑原失败任务，使用原网络、责任、事件流、机制、50评价和原评价器；原失败点通过后再补齐其余缺口，不删除或改写旧断点；
7. 依照 `resetp_goal_completion_matrix_20260716.md` 十步顺序完成四件套、重放、不变量、独立审计和论文填数。

## 5. 权限边界

用户已于2026-07-16明确授权E7边界修复与父—子恢复。授权只覆盖本提案的单行边界修复、原失败任务的先行复跑及其通过后同合同补齐其余17个缺口；不授权改动50次评价、6 workers、实例、种子、事件流、四种机制、评价器、父断点或任何既有不利结果。

## 6. 影子验证结果（2026-07-16）

受保护源哈希仍为 `0212c344024f95c9d13f7226f7b9ac7cfaab11f9e4244577d8191d37b5a629ed`，`git diff`为空。当前源上定向边界测试为`1 failed, 1 passed`，失败仅发生在“充电开始时刻恰等于触发时刻”的新增回归用例。

将单行修复只应用于`/private/tmp`影子副本后，`test_e7_full_mechanism_gate.py`全部10项通过。另行验证四种边界：触发前已完成动作保持`completed_before_trigger`；触发时正在进行、恰逢触发和容差内开始均固定为`in_progress_at_trigger_fixed`；晚于触发且超过容差的未来动作仍抛出原异常，没有被错误吞掉。动态多趟、正式价值、充电动作持久化及碳感知充电等相关测试共93项通过。

因此，单行修改的局部语义和相邻回归风险已经在影子环境中得到支持，但这不等于获准修改保护源或恢复正式E7。正式应用和断点续跑仍等待用户明确授权。

## 7. 恢复前合同谱系审计（2026-07-16）

只读闸门`baselines/e7_dynamic/e7_pre_recovery_gate_20260716/`逐个调用正式runner自身的断点加载与载荷验证函数，确认102/120个断点全部有效、18个缺口、0个无效断点；7个保护面、合同列出的全部源码与输入均无漂移，50评价、6 workers和原输出目录的监控合同保持不变。

该审计同时发现，调度器源码哈希是正式`contract_sha256`的组成部分。父合同为`bffdc512b8b39fe5c11bb80b63204a39f2a529d7810741354c401644cc3be16f`；正式应用单行修复后，调度器哈希变为`8b2de29659a1460020f3be4ad50cf34baa0b4badc340fbe31ceb98b6c288959f`，经正式合同构造器重新计算的子合同为`b703492d88d5a4db69f4302c709767871a8743ddef853e7be1d8b4ca956c0721`。先前影子推导的`199b...`并非正式子合同，现予更正。因此，直接修改保护源后调用原runner会正确拒绝旧断点；绕过合同校验把新旧语义混在同一合同内也不可接受。

正式恢复采用显式父—子谱系：父断点原地只读保留，子断点单独写入，最终汇总逐任务登记来源合同。该恢复设计和保护源修改已经获得用户明确授权。

## 8. 正式应用与首任务恢复（2026-07-16）

单行修复已经应用。`test_e7_full_mechanism_gate.py`共10项通过；动态多趟调度、正式价值、充电动作持久化、精细碳核算、可恢复runner及多趟排程等扩大回归共96项通过。父—子恢复只读闸门判决为`PASS_PARENT_CHILD_RECOVERY_AUTHORIZED`，确认102个父断点有效、18个缺口与授权白名单逐项一致、父断点哈希未变。

恢复runner为`baselines/e7_dynamic/e7_parent_child_recovery_runner_20260716.py`，子输出目录为`baselines/e7_dynamic/e7_multinetwork_formal_recovery_child_20260716/`。当前只运行原失败任务`N322__historical_mixed__stream1__no_participation`，仍使用50次评价和6 workers；监控由事件钩子接管，不进行人工轮询。只有该任务形成`PASS_ORIGINAL_FAILURE_TASK_RECOVERED`且父102项哈希保持不变，才允许继续补齐其余17项。
