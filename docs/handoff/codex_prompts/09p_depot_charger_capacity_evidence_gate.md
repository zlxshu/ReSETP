# 09p 车场充电容量/充电资本证据 Gate 执行计划

## Summary
09o 小试探没有跑满完整 mini-batch，结论仍是 `HALT_COLLECTION_COST`，不能作为论文结论。但 3 个成功的 280kWh/200c `free_mixed` 行共同显示：EV 解完全靠车场充电，公共充电为 0，且当前生成实例把车场桩数设为 `customer_count_route_upper_bound`。09p 的目标是把这个线索做成证据约束诊断：现实/文献中的 depot charger count 或 charging-capital budget 是否能自然阻止 280kWh 下 EV-heavy/all-EV 退化，并让 75-200 梯度与稳定性实例维持 20%-80% 实践混合带。

本步仍然不改默认参数、不进 E2/T3、不改 `prices.py`、`cost.py`、`check.py`、`evaluation.py`、bundle 或算法语义。任何约束只允许通过内存中的 instance/node `station_chargers` 覆盖或 runner 层资本预算审计来诊断，不能冒充正式数学模型。

## Key Changes
- 新增诊断 runner，例如 `baselines/e2_alns/depot_charger_capacity_gate.py`，输出报告与数据目录；复用 09o 的完整解保存、station capacity audit、resume、timeout/HALT 机制。
- Phase 0 先做证据矩阵，不允许拍脑袋设桩数。来源至少包括：UK/Europe commercial depot charging guidance，物流/货运车队电动化报告，2020 年后混合车队/MDVRP/EVRP 文献中对 depot charger count、charger-to-vehicle ratio、charging infrastructure budget、fleet electrification capital limits 的设定。没有来源的 cap 只能标 `diagnostic_only`，不得作为主场景候选。
- Phase 1 做当前实例结构审计：75/100/150/200 的三类 family、`-01/-02/-03`，记录当前 depot 数、public station 数、metadata `num_ev/num_cv`、当前 depot_chargers、public_chargers，以及 09l/09m/09o winners 的实际 depot/public charging kWh、公共充电路线数、峰值并发车场充电。
- Phase 2 做 in-memory fixed replay：用 09o 或新跑出的 full solution，把 depot `station_chargers` 替换为证据候选值，独立 `check_solution(..., override_instance)`。这一步只回答“已有 EV-heavy 解需要多少车场桩才不违反容量”，不重优化，不下最终结论。
- Phase 3 只有当 Phase 2 显示证据候选可能改变可行域时，才跑小预算 reopt gate。范围先从 75-200 的 `-01`、seed1 开始；幸存后再扩到 `-01/-02/-03`、seeds 1-3；最终确认才 seeds 1-5。每个候选必须同时报告 EV route/customer/demand/distance share，防路线数假平衡。

## Candidate Rules
- 主候选必须来自真实来源，例如“每 depot 固定桩数”“charger-to-EV ratio”“depot charging capital budget”“每日可服务 EV 充电窗口/功率预算”等。
- 不允许为了混合直接试 `5/10/20` 这类无来源数字。可以记录 09o 观测到的 required peak concurrency（例如 15/24/62）作为诊断阈值，但不能把它变成现实参数。
- 公共快充稀缺不是第一优先，因为 09o 成功行公共充电为 0；除非新证据显示大规模正式解高度依赖公共站，否则不要先做 public-station removal。

## Verdict Rules
- `DEPOT_CHARGER_CAPACITY_PRIMARY_DRIVER`：来源可信的 depot charging cap/budget 让 75-200 全稳定性实例多数 seed winner 落在 20%-80%，且 customer/demand/distance 不显示假平衡。
- `DEPOT_CAP_TOO_RESTRICTIVE`：来源可信 cap 导致大量不可行或退成全 CV，不能直接采用。
- `DEPOT_CAP_STILL_EV_DOMINANT`：来源可信 cap 下仍系统性 EV-heavy/all-EV，说明车场桩容量不足以支撑混合故事。
- `DIAGNOSTIC_ONLY_NO_SOURCE`：只有无来源诊断值有效，不能改默认参数或写论文主场景。
- `HALT_COLLECTION_COST`：timeout、缺行或关键 solution/replay 数据不完整。
- `HALT_EVIDENCE_MISMATCH`：找不到可支撑 depot charger/capital 设定的来源，停止，不硬造参数。

## Test Plan
- 预检：`git status --short`、`git rev-parse HEAD`，确认 09l=`BATTERY_ONLY_INSUFFICIENT`、09n=`HALT_COLLECTION_COST`、09o=`HALT_COLLECTION_COST` 且 E2/T3 仍暂停。
- 静态检查：`py_compile` 新 runner。
- Phase 0 evidence-only 先跑，报告必须列来源、数值、适用车队规模、是否可用于主场景。
- Smoke：用 200c 三个 `-01` 实例和 09o saved solutions 验证 replay、station capacity violation、CSV/JSON/Markdown 输出。
- 正式 gate：先 Stage A，再按幸存规则扩 Stage B/C；任何缺行/timeout 保留并 HALT，不补造结论。
- 回归：因为不改 solver 语义，至少跑 `solver/tests/test_cost.py solver/tests/test_check.py solver/tests/test_search.py -q`。

## Assumptions
- 09p 仍是诊断，不是模型正式化。若通过，必须另开 09q，把 hard constraint/soft capital budget 写进数学模型、checker、论文参数表和来源注释，并保留旧语义可复现开关。
- 20%-80% 是实践混合带，不追求 1:1；但必须覆盖 75-200 梯度和稳定性实例。
- 若 depot charging cap 无法解释，下一步再查 EV 资本预算、路线 eligibility 或组合约束，不回到无来源电池微调。
