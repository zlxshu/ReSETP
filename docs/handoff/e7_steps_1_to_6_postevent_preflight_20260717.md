# E7 步骤1--6事件后收口预检

状态：2026-07-17静态预检通过；未读取E7正式目录、任务方向或中间结果，未执行重放、独立审计、论文展品生成或证明发布。本文只固定hooks发出`COMPLETED`后的命令顺序和停止条件。

## 1. 入口与源码指纹

| 步骤 | 入口 | SHA-256 |
|---|---|---|
| 外部暂停时效审计 | `baselines/e7_dynamic/audit_e7_external_pause_timing_20260716.py` | `81d26f7244f3976f4122c61450d620234e5d16f76b4fc23588a00a24147d200c` |
| 28日电网日零搜索重放 | `baselines/e7_dynamic/e7_multiday_zero_search_replay_20260715.py` | `33b92d4c160c51f87bbd188a81b1c8086167faac0e4eb60ef506c083c2413dac` |
| 重放不变量审计 | `baselines/e7_dynamic/audit_e7_replay_invariants_20260715.py` | `73585f37aa1df0a01345fb1037cd1c0022806be3b1c6c6ae800498811bc35c27` |
| 多网络独立总审计 | `baselines/e7_dynamic/audit_e7_multinetwork_formal_20260715.py` | `6a551d83fcdc90128a6b4c73746ad5ee27ac6a07995a2d4017a58f28c5d07329` |
| E7论文展品生成 | `baselines/paper_story/build_20260715_formal_evidence.py` | `9b56919bde5d687f7759df9c89d040f766f6101432151a6ff51246c8d65ff02f` |
| 步骤1--6证明 | `baselines/e7_dynamic/build_e7_steps_1_to_6_attestation_20260717.py` | `955ad93979b9c131eac165b31823c432d0574caeaefdec1206802374834ba608` |

六个入口均通过`py_compile`。暂停时效、重放不变量、独立总审计、论文展品和证明构建器的21项定向测试全部通过。该结果只说明收口程序结构可执行，不说明E7已经完成。

## 2. 事件后的唯一命令顺序

所有命令均从仓库根目录执行，使用`PYTHONPATH=solver/src:models/src:.`。任何一步非零退出、判决字段不符、输入清单/哈希漂移或输出目录已有内容时立即停止，不继续运行后续命令。

1. 只读hooks事件包；只有`COMPLETED`才读取正式`decision.json`、`artifact_hashes.json`及五记录面。`ANOMALY`保留现场并停止。
2. 运行`python3 baselines/e7_dynamic/audit_e7_external_pause_timing_20260716.py`。正式判决必须为允许的完成状态，且任何阶段耗时不得达到已记录的13934秒外部暂停时长。
3. 在运行重放前，人工确认`baselines/e7_dynamic/e7_multiday_zero_search_replay_20260715/`不存在或为空。随后运行`python3 baselines/e7_dynamic/e7_multiday_zero_search_replay_20260715.py`，要求`PASS_E7_28DAY_ZERO_SEARCH_CHARGING_REPLAY`。
4. 人工确认`baselines/e7_dynamic/e7_replay_invariants_audit_20260715/`不存在或为空；运行`python3 baselines/e7_dynamic/audit_e7_replay_invariants_20260715.py`，要求`PASS_E7_REPLAY_INVARIANTS_AUDIT`。
5. 人工确认`baselines/e7_dynamic/e7_multinetwork_independent_audit_20260715/`不存在或为空；运行`python3 baselines/e7_dynamic/audit_e7_multinetwork_formal_20260715.py`，要求`PASS_E7_MULTINETWORK_FORMAL_AND_REPLAY_INDEPENDENT_AUDIT`。
6. 运行`python3 baselines/paper_story/build_20260715_formal_evidence.py`，核对七件论文展品与`e7_dynamic_paper_evidence_manifest.json`共同形成；最后运行`python3 baselines/e7_dynamic/build_e7_steps_1_to_6_attestation_20260717.py --publish`，要求`PASS_E7_STEPS_1_TO_6_ATTESTATION_READY`且证明文件为首次发布。

## 3. 特别风险

零搜索重放入口自身使用`mkdir(exist_ok=True)`，因此“输出目录不存在或为空”目前仍是运行前的外部门禁，不能省略。其余两套独立审计会拒绝覆盖非空目录，证明构建器也拒绝覆盖既有证明。为避免E7运行期修改下游冻结面，本轮不改重放脚本；完成事件后仍按总矩阵先检查目录，再执行入口。

步骤1--6证明只授权ALNS预算G0和外部强基线最终冻结，不代表E7十步或总目标完成。若后续算法换代，当前版本E7证据只能作为版本历史，必须用最终单一算法/物理版本重跑受影响证据。
