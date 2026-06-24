# 09m 运营结构混合带根因诊断执行计划

## Summary
09l 说明“真实来源电池容量单参数”不能让非 80kWh 候选跨规模稳定维持 20%-80% 实践混合带，但这不是故事线失败。下一步要按 Fable5/root-cause-first 口径调查：在 75-200 关键规模和稳定性实例中，是否存在由地理距离、车场/充电站布局、EV 数量/资本约束、充电容量、公共桩可用性或长路线 eligibility 造成的自然 CV/EV 分工。

本步只做诊断和证据，不正式改默认参数，不进入 E2/T3。当前最强线索来自 `baselines/e2_alns/structural_mixed_band_investigation.md`：算例 metadata 有 `num_cv/num_ev`，但当前 `infer_fleet_limits()` 是 unbounded fleet，`check.py` 明确 fleet count 不再是硬约束；09l/09h 的 EV-heavy 方案常用几十条 EV route，远超 metadata 中的 EV 数。这很可能是 280kWh 下“EV 太香”的主因之一，且现实上比继续微调电池更好解释。

## Key Changes
- 新增诊断 runner 与报告，建议为 `baselines/e2_alns/operational_structure_mixed_band_diagnostic.py` 和 `.md`，输出 `operational_structure_mixed_band_data/`。
- 冻结 `prices.py`、`cost.py`、`check.py`、`evaluation.py`、bundle 和算法语义。所有实验只能用 in-memory override、`SearchPolicy(max_ev/max_cv)`、只读实例结构分析或显式标注的 counterfactual；不把 counterfactual 冒充默认模型。
- Phase 0 做证据矩阵：本地 Zotero/论文与网上官方/行业来源必须分别记录。重点来源包括混合车队配置论文（如 Li2020、Chen2023、Qiu2024、Goeke/Schneider）、UK commercial EV fleet adoption/barriers、depot charging/grid capacity、public charging availability。当前可用外部起点：
  - GOV.UK 2024 commercial electric vans and fleets research: https://www.gov.uk/government/publications/commercial-electric-vans-and-fleets-adoption-smart-charging-and-barriers
  - SMMT 2025 van market / BEV share / barriers: https://www.smmt.co.uk/van-market-shrinks-in-2025-despite-ev-growth/
  - Fraunhofer/Oeko/T&E 2025 truck depot charging report: https://uploads.transportenvironment.org/production/files/TE_truck-depot-charging_final-report.pdf
- Phase 1 做全 69 实例结构审计，不只看 `-01`：距离跨度、客户密度、最近车场/最近公共站距离、车场数、站点数、站点/客户比、车场/公共站充电器容量、metadata `num_cv/num_ev`、时间窗宽度、需求密度。重点单列 75/100/150/200 和 `-01/-02/-03` 稳定性实例。
- Phase 2 复核现有 09l/09k/09h 结果：只把它们作为线索，不作最终结论。对每个 75-200 family × size × replicate，标出已有 EV share、是否超过 20%-80%、是否 EV route count 超过 metadata `num_ev`、是否 station/depot coverage 异常。
- Phase 3 只做轻量 in-memory 控制变量 gate，按“先少量代表点，过了才扩”的原则，避免过度探测：
  - A. EV 数量/资本约束：用真实来源或文献支持的 EV share/fleet-count 值，跑 `SearchPolicy(max_ev=...)` 或等价 wrapper。先测 75-200 `-01`，再测 75-200 全 `-01/-02/-03`。不得直接把 metadata `num_ev=10` 当真理，必须解释它来自生成器还是论文设定。
  - B. 充电容量：审计现有解的充电并发；若车场充电器数量过宽松，测试源支持的 depot charger cap / public charger cap。必须保留 `check.py` 当前容量语义，不静默改硬约束。
  - C. 公共站可用性/布局：只做标注 counterfactual，如 station-sparse、depot-only、public-station eligibility，不准改 bundle 落盘。
  - D. 长路线 EV eligibility：按路线距离/时长阈值标注，不得先拍阈值；阈值必须来自文献/行业证据或先作为 diagnostic-only。
  - E. 价格/占用费/固定费：复用 09f/09h 的固定碳价原则，只跑有来源支撑的 near-flip，不扩大成无来源网格。
- Phase 4 判定必须以 75-200 规模为主，并包含稳定性实例。至少报告 route/customer/demand/distance 四个 EV share；主判据仍是 route share，但若路线数平衡、客户/距离严重失衡，必须写明“假平衡”。

## Gate Rules
- `OPERATIONAL_MIXED_BAND_FOUND`：某个证据支持的运营结构设定，在 75/100/150/200 的 relevant families 与 `-01/-02/-03` 稳定性实例中，多数 seed winner 的 EV route share 落在 20%-80%，且 customer/demand/distance share 无严重假平衡。
- `FLEET_CAP_PRIMARY_DRIVER`：EV 数量/资本约束能解释 280kWh EV-dominant，并在 75-200 稳定性实例中产生真实混合；后续才可讨论是否把 EV fleet availability 作为论文主场景约束。
- `CHARGING_INFRA_PRIMARY_DRIVER`：充电容量或公共桩可用性是主要机制；后续才可讨论是否正式加入基础设施约束。
- `GEOGRAPHY_GENERATOR_MISMATCH`：问题主要来自当前 E2 车场/充电站选址或站点密度生成方式，不应通过参数硬调解决；需回到 instance generator 设计。
- `BATTERY_AND_OPERATIONS_INSUFFICIENT`：证据支持的电池与运营结构仍不能守住 75-200 混合带；论文叙事需转向 EV-dominant transition 或重新定义场景。
- `HALT_COLLECTION_COST` / `HALT_EVIDENCE_GAP` / `HALT_OVERRIDE_NOT_TRUSTWORTHY`：跑不满、证据不够或 override 不可信时停止，不下科学结论。

## Test Plan
- 预检：`git status --short`、`git rev-parse HEAD`，读取 `MASTER_codex_takeover_plan.md`、`HANDOFF.md`、`structural_mixed_band_investigation.md`。
- 静态：`py_compile` 新 runner。
- Phase 0/1 只读结构与证据矩阵必须先跑完，输出 evidence matrix、instance structure、09l join、hypothesis ranking。
- Phase 3 每个机制先跑小代表集，不得直接启动全量；只有代表集出现 pass/near-pass 才扩到 75-200 全 `-01/-02/-03`。
- 回归测试：若只新增诊断脚本和报告，至少跑 `pytest solver/tests/test_cost.py solver/tests/test_check.py solver/tests/test_search.py -q`；若触碰任何 search wrapper，还要跑对应 e2_alns smoke。
- 提交：先提交诊断脚本/数据/报告/HANDOFF/MASTER；再写回 artifact commit hash 做第二笔提交；不 push。

## Assumptions
- “75-200 维持混合带”是当前主目标；10-50 可作为解释材料，但不作为本 gate 的硬门槛。
- 不再把 80kWh 作为现代主候选；它只保留为历史/文献锚。
- 不为了混合自造参数。任何 EV 数量、充电器容量、站点可用性、长路线阈值，都必须有文献或行业来源；没有来源只能标 diagnostic-only。
- 若最终确定任何新默认参数或运营约束，必须同步 `prices.py` 注释、TeX 参数表/说明、bibliography、HANDOFF/MASTER，并保留旧参数及其来源痕迹。
