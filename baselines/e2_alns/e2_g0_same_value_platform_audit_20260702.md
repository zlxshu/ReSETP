# E2-G0 5174 同值平台审计

日期：2026-07-02
输入：`baselines/e2_alns/ev_heavy_findability_gate_long_same_instance_v2_data/`
审计脚本：`baselines/e2_alns/plateau_5174_audit.py`
输出目录：`baselines/e2_alns/e2_g0_same_value_platform_audit_data/`

## Verdict

`ARTIFICIAL_HOMOGENIZATION`

这不是 `evaluate/check` 回放错误，也不是 GA 旧的 `HALT_RUNTIME_UNDER_EVAL`。四个 baseline 确实都跑满 `16000/16000 OK`，checkpoint 解也能用冻结 `evaluate()` / `check_solution()` 回放到同一成本、零违约。

问题在于：GA/LNS/PSO/VNS 两个 seed 的所有 best 更新都在前 42 次 eval 内完成，并且全部由共享车型翻转通道主导；之后至少 15958 次 eval 没有任何算法用自身搜索结构继续改善 best。当前 `5174.345121253789` 平台更像“共同 deterministic repair/mutation 把所有 baseline 推到同一个局部平台”，不能直接作为健康 baseline 证明 ALNS 30% 领先。

附加标签：

- `HASH_CONTAMINATED_APPLEDOUBLE`
- `EV_MAXIMAL_REFERENCE_NOT_BOUND`

## 产物

- `summary.json`：总 verdict 与门槛字段。
- `seed_invariance.csv`：四 baseline 跨 seed 同 cost / 同 signature / 同 EV share。
- `checkpoint_replay.csv`：checkpoint 用当前代码回放的 cost、violation、signature。
- `baseline_history_summary.csv`：best-update operator、最终改进 eval、后续无改进 eval 数。
- `baseline_history.csv`：逐条 best-update history。
- `hash_hygiene.json`：AppleDouble 污染清单。
- `baseline_plateau_signature.json`：项目 `solution_signature()` 输出的规范化平台签名。

## 证据链

1. raw 数据层：GA/LNS/PSO/VNS 共 8 行全部 `OK` 且跑满 `16000` eval；best cost 全为 `5174.345121253789`，best signature 全为 `7cc6d853424cabb63602f8e9157561513fd038792153be3eb53eab56e86f09d2`，best EV share 全为 `0.6818181818181818`。见 `seed_invariance.csv`。

2. checkpoint 回放层：8 个 baseline checkpoint 用 `B_battery_kwh=280.0`、`carbon_price=0.05034` 回放，全部 `replay_total_cost=5174.345121253789`、`replay_violation_count=0`、`signature_matches_raw=True`。所以这不是 CSV 旧值或 checkpoint 损坏。见 `checkpoint_replay.csv`。

3. history 层：所有 baseline 的最终 best 更新都发生在 eval 30-42 之间，之后至少 15958 次 eval 没有 best 更新。GA 的 best 更新全是 `ga_vehicle_type_initialization`；LNS 全是 `lns_vehicle_type_mutation`；VNS 全是 `vns_vehicle_type_construction` / `vns_local_vehicle_type`；PSO 的 history 标成 `pso_initial_particle`，但其 best 更新 eval 为 2/5/8/.../41，对应 `_pso_initial_particles()` 中 `idx % 3 == 1` 的车型翻转分支。见 `baseline_history_summary.csv`。

4. 代码层：baseline 共享同一个 warm start 与 session 评分器（`metaheuristic_baselines.py:112-159`、`191-225`）；GA 初始化显式每三步调用 `_vehicle_type_mutation()`（`1037-1069`）；PSO 初始化同样每三步调用 `_vehicle_type_mutation()`（`1145-1160`，脚本按 eval 序列识别）；LNS 主循环 35% 概率走 `_vehicle_type_mutation()`（`601-619`）；VNS 构造与 local search 都包含车型翻转通道（`496-520`、`1181-1205`）；共享 `_vehicle_type_mutation()` 本体在 `845-877`。

5. serialized JSON hash 不完全相同，但项目规范化 signature、成本、能耗、碳成本和可行性完全相同。这说明表层 payload 可能有车牌号/序列化差异；论文判据应以项目 signature + evaluate/check 为准。

6. `findability_decision.json` 的 `max_closed_gap_fraction≈5.6976` 不是错误，而是 `ev_maximal_reference_cost=5411.442347477969` 不是下界。ALNS 找到的 `3569-3653` 低于该诊断参照，所以闭合比例超过 1。这个字段不能写成最优性或下界闭合证据。

7. 输入目录存在 51 个 AppleDouble `._*` 文件，且 `artifact_hashes.json` 已包含 `._raw_runs.csv` 等污染项。旧 hash 清单只能标为 `HASH_CONTAMINATED_APPLEDOUBLE`，不得作为正式证据。

## 结论含义

当前 C1 不支持“ALNS 已经对健康 GA/LNS/PSO/VNS 稳定领先 30%”这句话。更准确的说法是：在 280kWh 诊断同实例上，所有 baseline 先被共享车型翻转通道推到同一平台，ALNS 通过更强的 route segment / repair 结构继续下降。但这还没有证明四个 baseline 的算法身份和搜索能力是健康、独立、充分表达的。

这也不等于 ALNS 结果是假的。ALNS checkpoint 回放干净，成本优势是真实数值；问题是比较对象被同质化，审稿人会质疑“你是不是把对手都变成了同一个弱壳”。

## PDCA 关闭

Plan：审计 `5174.345121253789` 是共同局部最优还是人为同质化。

Do：新增只读审计脚本，解析 raw/task/checkpoint/history，做冻结 evaluate/check replay。

Check：回放通过；种子不变性、history 主导通道、AppleDouble 污染均已落表。

Act：E2-G0 判 `ARTIFICIAL_HOMOGENIZATION`。在整改前不得启动 E2-G4/G5，不得把该单实例 30% 写入论文主张。

## 下一步施工令

1. C1-R1：把共享车型翻转从“baseline 算法成绩”中剥离出来，作为 common preprocessing 或单独 common repair layer 记账。公平对比应从同一 `5174` 平台继续，或至少分别报告“common vehicle-type lift”和“native algorithm lift”。

2. C1-R2：给 baseline 加 operator provenance gate。验收标准不是低预算分胜负，而是每个 baseline 的 best 更新必须能区分 common channel 与 native channel；如果最终仍同值，必须证明 native channel 已被充分调用且不是被共同 decoder/repair 吞掉。

3. C1-R3：整改后再补 ACO/GA-VNS/GWO/IWD/SA/NSGA-II 等承诺基线。不要在当前同质化平台上扩跑。

4. C1-R4：清理 AppleDouble 后重生 `artifact_hashes.json`；旧 hash 文件保留为污染证据，不进入正式表。

5. C1-R5：G0 重新审计过门后再进入 G1 独立 ALNS 剥离与 G3 基线补全。G4/G5 继续冻结。
