# 09q 来源约束电池梯度 × 运营约束综合摸排执行计划

## Summary
执行综合摸排，不再只测试 `280kWh`，也不回潮 `80kWh`。目标是在真实来源电池容量谱上，叠加有证据或明确标注为 diagnostic 的运营约束，判断是否存在能跨 E2 可用 `10-200` 全规模梯度稳定维持 `20%-80%` EV/CV 实践混合带的组合。

本步仍是诊断，不改默认参数，不进入 E2/T3，不改 `prices.py`、bundle、`cost.py`、`check.py`、`evaluation.py` 或算法语义。当前已实现 runner 并完成 smoke；正式 Stage A 还没有跑满，不能引用 smoke 作为科学结论。

## Key Changes
- 使用 `baselines/e2_alns/source_bound_operational_mix_map.py` 与报告 `baselines/e2_alns/source_bound_operational_mix_map.md`；输出目录为 `baselines/e2_alns/source_bound_operational_mix_map_data/`。
- 电池候选固定来自 09l/09k 真实来源矩阵：`60, 81, 82.6, 89, 100, 113, 123.9, 140, 141, 150, 176, 180, 194, 200, 210, 240, 280, 282, 291 kWh`。`80kWh` 只作历史 reference，不参与主候选通过判定。
- 运营约束场景固定为：`unbounded_reference`、`goeke_ev_cap_only`、`goeke_total_cap`、`depot_chargers_manifest_ev_diagnostic`、`depot_chargers_manifest_total_diagnostic`、`public_charging_disabled_diagnostic`、`depot_manifest_ev_no_public_diagnostic`。其中 Goeke/ReSETP 车辆数是 source-backed diagnostic；车场桩数/禁公共桩是 diagnostic proxy，不得直接提升为论文模型。
- 实例范围升级为可用 `10-200` 全梯度：vanilla/multidepot 的 `10/15/20/25/50/75/100/150/200c`，threeshift 的 `50/75/100/150/200c`，每个 size 使用 `-01/-02/-03` 稳定性实例。Stage A 用 `-01` 共 23 个实例；Stage B/C 用全 69 个实例。
- 每个 winner 同时报告 EV route/customer/demand/distance share、CV/EV route count、公共/场站充电 kWh、场站峰值并发、容量违规、EV 路线距离与能耗。若 route share 平衡但 customer/demand/distance 越界，必须标成 fake balance。

## Current State
- `--phase0-only` 已通过：电池 override 可穿透，临时 bundle 的 depot charger override 可被 `load_search_bundle/evaluate/check/run_alns_wouda` 看到。
- smoke 已跑：`81/280kWh × unbounded_reference × 2 个代表实例 × seed1 × 3 variants`，12 rows，10 OK + 2 `INIT_INFEASIBLE`，verdict=`SMOKE_ONLY`。这只证明 runner 可用，不是 Stage A 结论。
- 完整 Stage A 默认任务量是 `19 × 7 × 23 × 3 = 9177` 个子任务，不能在普通交互里伪装成已跑满。必须按可恢复任务队列分段跑，保留 partial/timeout/error。

## Run Commands
预检：
```bash
cd '/Volumes/移动硬盘（512G）/ReSETP' && \
git status --short && git rev-parse HEAD && \
PYTHONPATH=solver/src:models/src:baselines/e2_alns PYTHONHASHSEED=0 \
/opt/anaconda3/bin/python3.13 -m py_compile baselines/e2_alns/source_bound_operational_mix_map.py
```

Phase 0/1：
```bash
cd '/Volumes/移动硬盘（512G）/ReSETP' && \
PYTHONPATH=solver/src:models/src:baselines/e2_alns PYTHONHASHSEED=0 \
/opt/anaconda3/bin/python3.13 baselines/e2_alns/source_bound_operational_mix_map.py --phase0-only
```

Smoke：
```bash
cd '/Volumes/移动硬盘（512G）/ReSETP' && \
PYTHONPATH=solver/src:models/src:baselines/e2_alns PYTHONHASHSEED=0 \
/opt/anaconda3/bin/python3.13 baselines/e2_alns/source_bound_operational_mix_map.py \
  --stage-a --smoke \
  --battery-values 81 280 \
  --constraint-scenarios unbounded_reference \
  --stage-a-eval-budget 300 \
  --runtime-small 60 --runtime-medium 90 --runtime-large 120 \
  --task-timeout-buffer 30 --workers 3 --no-resume
```

正式 Stage A 全矩阵：
```bash
cd '/Volumes/移动硬盘（512G）/ReSETP' && \
PYTHONPATH=solver/src:models/src:baselines/e2_alns PYTHONHASHSEED=0 \
/opt/anaconda3/bin/python3.13 baselines/e2_alns/source_bound_operational_mix_map.py \
  --stage-a --resume --workers 3
```

若 Stage A 有 pass/near-pass 组合，再跑 Stage B：
```bash
cd '/Volumes/移动硬盘（512G）/ReSETP' && \
PYTHONPATH=solver/src:models/src:baselines/e2_alns PYTHONHASHSEED=0 \
/opt/anaconda3/bin/python3.13 baselines/e2_alns/source_bound_operational_mix_map.py \
  --stage-b --resume --workers 3
```

若 Stage B 仍有 pass/near-pass 组合，再跑 Stage C：
```bash
cd '/Volumes/移动硬盘（512G）/ReSETP' && \
PYTHONPATH=solver/src:models/src:baselines/e2_alns PYTHONHASHSEED=0 \
/opt/anaconda3/bin/python3.13 baselines/e2_alns/source_bound_operational_mix_map.py \
  --stage-c --resume --workers 3
```

## Verdict Rules
- `SOURCE_BOUND_OPERATIONAL_MIX_FOUND`：来源真实电池 + 可正式化运营约束在 Stage C 全 69 实例、seeds1-5 中通过，且 route/customer/demand/distance 都不显示假平衡。
- `ONLY_DIAGNOSTIC_NO_SOURCE`：只有 diagnostic proxy 通过，不能直接改论文模型，只能作为下一步找证据/建模方向。
- `SOURCE_BOUND_OPERATIONAL_NEAR_NEEDS_CONFIRMATION`：Stage A/B 有 pass 或 near-pass，但不是 Stage C 终判。
- `BATTERY_OPERATION_COMBINATION_INSUFFICIENT`：真实电池和已测试运营约束组合都无法跨 10-200 全梯度稳住实践混合带。
- `SMOKE_ONLY`、`HALT_COLLECTION_COST`、`HALT_OVERRIDE_NOT_TRUSTWORTHY`：分别表示只验证链路、数据没跑满/超时、覆盖不可信；都不能下科学结论。

## Test Plan
- 静态：`py_compile` 必须通过。
- smoke：必须产出 `metadata.json`、`phase0_audit.json`、`stage_a_raw_runs.csv`、`stage_a_winners.csv`、`stage_a_scenario_summary.csv`、`conclusion.json` 和 markdown 报告。
- 正式 Stage A/B/C：所有 timeout/error 必须保留，缺行即 HALT；不得补造 winner。
- 回归：完成当前脚本与文档后，至少跑 `solver/tests/test_cost.py solver/tests/test_check.py solver/tests/test_search.py -q`。
- 提交：先提交 runner、报告、数据、HANDOFF/MASTER/prompt；再把 artifact commit hash 写回 metadata/report 做第二次提交。不 push。

## Assumptions
- “全规模梯度”按当前 E2 bundle 实际存在的 69 实例执行；threeshift 不存在 10/15/20/25c，因此从 50c 起。
- 本步不正式引入车辆数上限、场站容量或公共桩约束到数学模型；通过诊断后仍需另起正式建模计划，同步 TeX、代码注释和来源。
- 不因为想要混合而选择无来源电池或无来源约束；跑不满或只得到 diagnostic pass 就诚实停。
