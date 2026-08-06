# W2 冻结基线重锚记录（2026-08-02）

## 授权与纪律

`DECISION`：用户 2026-08-02 批准“④更新”，并要求“以前的数据和设计几乎全部作废，以最新的为准”。本记录只更新冻结锚值；旧 commit、旧 manifest 和旧探针 metadata 均保留，未删除断言、未放宽比较、未跳过测试。当前锚全部是精确 SHA-256；以后任一字节再漂移仍会失败。

## 逐项重锚

### 1. E2 80 kWh 受保护语义合同

- 测试：`solver/tests/test_e2_80k_robustness_gate.py::test_protected_semantics_and_goeke80_parameters_match_frozen_commit`。
- 失败原因：测试把当前八个语义文件逐字节对比历史执行 commit `40bd28835dff1a4287486e720351e531fc7a38d0`；项目在该正式批以后已批准演化，所以八项全漂移，守卫长期只报历史差异而不能保护当前活动源码。
- 重锚前：`prices.py=09c534bb...5644a7`、`cost.py=ab9bfb9f...55d8a37`、`check.py=1e367354...8a4f81`、`evaluation.py=1fae4f76...e1545d`、`solution.py=ae17629a...e09378`、`bundle.py=077eea45...f693`、`feasible_repair.py=0d0a67b1...934f722`、`candidates.py=1a5e99e0...3d4061`，均来自 `40bd2883...`。
- 重锚后：`prices.py=36049112...dcb96`、`cost.py=e7ea406d...2b00d`、`check.py=86b81315...902b`、`evaluation.py=c7215263...6fc3`、`solution.py=636b08d9...1bbd`、`bundle.py=fa6d527d...24a7`、`feasible_repair.py=5a7e5d24...a4fb2`、`candidates.py=7ecfc9f8...17b59`。
- 保留方式：`FROZEN_COMMIT` 仍为 `40bd2883...`，返回结果同时记录每项 `frozen_sha256`；新增 `ACTIVE_PROTECTED_SHA256` 只负责当前守卫。

### 2. PyVRP 0.13.4 候选探针

- 测试：`solver/tests/test_external_baseline_freeze_builder_20260717.py::test_candidate_probe_is_bound_to_current_adapter`。
- 失败原因：旧探针 metadata 锁定探针源码 `a3b313c7...45e5d`，现行源码为 `378152c8...c3976`；旧包不得覆盖，原测试却要求两者相等。
- 重锚前：探针 artifact 源码 `a3b313c73e96938b02d17e81f6bbaf4c679b35675b5edf8d1456ee2d8fd45e5d`；adapter `08a541b77a222fb1cfba7121a850b0d3ac7216c8cb001302bea39d04c4f19a67`。
- 重锚后：历史探针锚仍精确检查旧值；另加活动探针源码锚 `378152c847fe9d6d4b16c53cc0ec1f28e7b8c8995b7c45d86048de8ebfdc3976`。adapter 未变化，活动锚仍为 `08a541b7...19a67`。
- 保留方式：不改 `pyvrp_0134_tool_probe_20260717_v3/`；测试现在同时验证旧 metadata 与活动源码两个锚。

### 3. E4 全局证据 manifest 的活动源码段

- 测试：`solver/tests/test_paper_evidence_boundaries.py::test_current_e2b_e3_e4_and_e6_identity_matrices_are_exact`。
- 失败原因：262 项历史 manifest 中有五个活动源码文件已在后续获批工程中演化；旧 manifest 仍应证明旧 E4 身份，但不能继续充当当前源码冻结值。
- 重锚前→后：`multitrip_schedule.py a1033870...eb9ab→1274da79...94d13`；`cost.py d8bfee18...dee4→e7ea406d...2b00d`；`check.py 53f5cc27...e142→86b81315...902b`；`e3_multitrip_runtime.py ecbe2155...62ad6a→8a221add...60e3`；`formal_runner.py 9cde2b62...09ad22→4d80f576...92aa8a`。
- 保留方式：旧 262 项 manifest 原文件不变；审计仅对这五条应用 `E4_ACTIVE_SOURCE_REANCHOR_SHA256`，其余 257 条仍逐项使用旧 manifest，文件数、必需证据面与身份矩阵断言均不变。

### 4. strong-bridge 工作树保护锚

- 测试：`solver/tests/test_strong_bridge_backend_alignment.py::StrongBridgeBackendAlignmentTests::test_decision_gate_reports_backend_only_and_main_local_search_separately`。
- 失败原因：守卫以 Git `HEAD=850cea5f3d3e11a21e073a7c1a45477a65a7a66f` 为唯一基线；W1 经用户批准修改 `cost.py` 后仍被列为 `protected_diff`，使纯决策单测与实验前门长期红。
- 重锚前：HEAD 中 `cost.py=7f59a47a3aab9b582b17e29d7e9dc13f16f892fc7b5ae7b54eec84412aa77333`。
- 重锚后：批准的活动工作树 `cost.py=e7ea406da87a3172cd1ff7dc87fe7def536e74f197f6c67b29da2394fe42b00d`。
- 保留方式：Git 基线不改；只在工作树恰好等于批准哈希时视为已重锚。若 `cost.py` 再改一个字节，`protected_diff` 立即恢复非空。

## 验收口径

上述四项必须逐项转绿。若其后同一测试暴露非锚值失败，则保留红灯并另行分类，禁止继续改断言救绿。

## W2 v3 绑定触发的补充车队数锚

权威全量测试第一次运行时，`solver/tests/test_china81_bundle_20260720.py::test_real_china81_bundle_joins_region_vehicle_and_road_contracts` 的三个参数化单元仍把默认 China81 车队数锚在 v1/v2：京津冀 `num_cv/num_ev=2/1`、珠三角 `3/1`、成渝 `2/1`。默认绑定切到 v3 后，三个 10c 算例均为 `1/1`，故只把上述三组数值锚更新为 `1/1`；地区、油价、车型、矩阵、充电并发、断言结构和测试输入均未改变。批准依据同为用户 2026-08-02 的“④更新”及本 W2 对 v3 默认绑定的明确授权。

同轮出现的 `test_china81_shared_completion_20260720.py` 两个失败未被伪装成锚漂移：旧 completion 仍按“每条路线占一辆车”执行 `route_count <= num_cv + num_ev`，而 v3 的上限是可跨趟复用的实体车数。一个单元因此把不满足 v3 车型上限的全燃油方案作为单调参照，另一个单元把 3 条可多趟排班的路线直接判为超过 2 辆。它们不能仅更新锚值转绿，断言原样保留并列为 W2 发现的真实接口回归。
