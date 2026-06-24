# 09l 来源约束实践混合带 Gate 执行计划

## Summary
执行 09k 的纠偏版后续：不再把 `80kWh` 当现代主场景候选，也不使用等距网格或插值电池值。目标是在真实文献/车型明确给出的电池容量中，判断是否存在一个跨所有梯度规模和稳定性校验实例都能维持 EV/CV 实际占比在 `20%-80%` 内的“实践混合带”。本步只做诊断、报告和候选建议，不正式改默认参数，不进入 E2/T3。

## Key Principles
- `80kWh` 只作为 Goeke/Chen 历史/文献锚和 lower reference，不得作为现代主场景候选。先前大算例诊断已说明 80kWh 续航偏小，会导致 EV 在跨城/大规模下失去经济性。
- 电池候选必须来自真实来源：2020 年后文献、Zotero PDF、官方车型资料或明确车型规格。不得使用 `90/95/105` 这类无来源插值，也不得为了凑 mixed 自造参数。
- 不要求 1:1 混合；允许研究趋势偏 EV。判定区间为 winner 的 EV share 在 `20%-80%` 内。主指标为 `EV route share`，同时尽量补 `customer_share`、`distance_share`、`demand_share`，避免路线数假平衡。
- 不能只看全局均值或某一个 `-01` 代表实例。候选必须按 family × size 梯度和稳定性实例逐项报告；只有跨所有规模梯度、稳定性校验实例、seeds 多数都在 `20%-80%` 内，才可称为“故事立得住”。
- 若没有真实来源候选通过，结论必须写成“电池单参数不足”，不能继续微调无来源电池。下一步才考虑运营约束退路。

## Key Changes
- 新增或扩展 runner，建议为 `baselines/e2_alns/source_bound_mixed_band_gate.py` 与报告 `baselines/e2_alns/source_bound_mixed_band_gate.md`；可复用 `battery_spectrum_transition.py` 的证据矩阵、override audit、任务队列、composition 判定和 timeout/HALT 机制。
- 冻结 `prices.py`、`cost.py`、`check.py`、`evaluation.py`、bundle 和算法语义；所有电池只通过 `dataclasses.replace(DEFAULT_PRICES, B_battery_kwh=x, carbon_price=0.05034)` 内存覆盖。
- Phase 0 复核 override 穿透；必须继续使用显式 override warm start，因为 09k 已发现 `run_alns_wouda` 默认初始构造不会把 override prices 传进 `build_initial_solution`。
- Phase 1 从 09k `evidence_matrix.csv` 自动筛选候选：排除 diagnostic-only 和 future-heavy；排除 `80kWh` 作为现代主候选但保留为 reference；只保留真实来源明确的候选。优先 full-run 09k screen/transition 中处于 `20%-80%` 附近的来源值，例如 `81/89/100/113/123.9/140/141` 等，具体由数据和来源自动决定，不手填等距网格。
- Phase 2 对候选做全梯度实践混合 gate：覆盖 E2 benchmark 的所有 family × size 梯度，并包含稳定性校验实例。若 69 全实例成本过高，允许两段式执行：先全 `-01` 梯度 + 稳定性子集筛掉明显失败候选，再对幸存候选跑完整 69 实例；但报告不得把 Stage A 冒充最终结论。
- Phase 3 对通过或 near-pass 候选加 seeds 1-5、较高预算复核，并输出逐 family/size 的 EV/CV 占比表、失败实例清单、成本分解和充电行为摘要。

## Interfaces
- CLI 至少支持：`--phase0-only`、`--screen-only`、`--full-gate`、`--resume`、`--retry-timeouts`、`--candidate-policy source_transition`、`--exclude-80-main`。
- 输出目录建议：`baselines/e2_alns/source_bound_mixed_band_gate_data/`。
- 输出文件至少包括：`metadata.json`、`candidate_sources.csv`、`override_audit.json`、`screen_raw_runs.csv`、`screen_by_scale.csv`、`full_raw_runs.csv`、`full_winners.csv`、`mixed_band_by_scale.csv`、`failure_instances.csv`、`conclusion.json`。

## Verdict Rules
- `SOURCE_BOUND_MIXED_BAND_FOUND`：至少一个非 80kWh、来源合格候选在完整梯度与稳定性实例上，多数 winner 的 EV route share 落在 `20%-80%`，且 all-CV/all-EV/EV-heavy 极端不主导；报告需列出该候选的来源和每个规模梯度表现。
- `SOURCE_BOUND_NEAR_BAND_NEEDS_CONFIRMATION`：候选总体接近 `20%-80%`，但某些规模或稳定性实例失败；只能作为后续确认候选，不得改默认。
- `BATTERY_ONLY_INSUFFICIENT`：真实来源候选要么低端退回 all-CV，要么高端 EV-dominant，无法跨规模稳定维持 `20%-80%`；下一步转运营约束退路。
- `HALT_COLLECTION_COST`：timeout、缺行或 runner 未跑满；不得下科学结论。
- `HALT_OVERRIDE_NOT_TRUSTWORTHY`：电池 override 穿透不可信；停止。

## Test Plan
- 预检：`git status --short`、`git rev-parse HEAD`，确认当前 09k artifact commit 已记录，且 `MASTER_codex_takeover_plan.md` 中 80kWh 不再是主场景候选。
- 静态检查：`PYTHONPATH=solver/src:models/src PYTHONHASHSEED=0 /opt/anaconda3/bin/python3.13 -m py_compile baselines/e2_alns/source_bound_mixed_band_gate.py`。
- Smoke：用 `80(reference)`、`100(candidate)`、`280(reference)` 三点和少量实例验证 resume、timeout row、CSV/JSON/Markdown 输出。
- 正式跑：先 screen，后 full gate；如果 full 69 实例成本过高，按 Stage A/Stage B 分段，但任何未跑满阶段都必须写 `HALT_COLLECTION_COST` 或 `NEAR_BAND_NEEDS_CONFIRMATION`，不能冒充通过。
- 回归：`PYTHONPATH=solver/src:models/src PYTHONHASHSEED=0 /opt/anaconda3/bin/python3.13 -m pytest solver/tests/test_cost.py solver/tests/test_check.py solver/tests/test_search.py -q`。
- 提交：runner、数据、报告、HANDOFF/MASTER 更新先提交；再把 artifact commit hash 写回 metadata/report 做第二次提交；不 push。

## Assumptions
- “混合”按 20%-80% 实践带定义，不按 50%-50% 定义；EV 偏高是允许的，但超过 80% 不能再讲成稳定混合车队。
- 80kWh 的 full-gate balanced 只说明它是历史转折参考，不推翻“80kWh 太小”这一先前大算例诊断结论。
- 若无候选通过，本步不自动设计运营约束，只给出下一步运营约束退路提示词建议。
