# T7：搜索侧碳项与最终充电排程/评价一致性

## 结论

**[DECISION] FIX_VALIDATED**。根因不是 48 槽索引、城市选择或最终评价再次重排，而是公共 China81 补全器在 O/P 的零碳价控制臂中仍无条件生成 `ev_low_carbon`/`legacy` 分支。该分支直接按最低碳时段排程，绕过了 O/P 的“运营成本-only”目标；因此 T5 的 O 与 C 不是同一目标下的充电控制，才产生了“同路线、同电量而 C 更脏”的跨臂假矛盾。

修复仅改动 `solver/src/setp_solver/china81_completion.py:312-327`：只有 `bundle.prices.carbon_price > 0` 时才加入 `ev_low_carbon`；零碳价 O/P 只生成 `ev_integrated` 和 `ev_immediate` 两个目标一致的变体。未修改三个受保护文件、碳价、碳数据、算例、车队合同、约束或目标函数经济含义。

## 1. 症状与最小复现

**[FACT]** T5 归档的预算 1000、seed 1 witness 重放得到：O/C 路线 hash 都是 `f064404eb2f7...`，充电量都为 `87.548679 kWh`；O 充电排放 `43.064987 kg`、电费 `62.833212 CNY`，C 充电排放 `57.304565 kg`、电费 `46.785051 CNY`。

**[FACT]** 最小复现脚本为 [reproduce_minimal.py](reproduce_minimal.py)。重放旧 witness（不跑 18 次）命令：

```text
PYTHONHASHSEED=0 PYTHONPATH=solver/src:models/src:baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720:docs/handoff/eval_chain_carbon_consistency_20260804 /opt/anaconda3/bin/python3.13 docs/handoff/eval_chain_carbon_consistency_20260804/reproduce_minimal.py --mode pre-fix-replay
```

该脚本逐臂打印搜索 bundle 与最终 reporting bundle 的充电排放和电费；旧 witness 中两套评价的充电排放已经相等，分别为 O `43.064987`、C `57.304565 kg`。这证明异常不是“搜索侧记了一个数、最终评价又算了另一个数”。修复后只跑 O/C 的同一预算和 seed：

```text
PYTHONHASHSEED=0 PYTHONPATH=solver/src:models/src:baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720:docs/handoff/eval_chain_carbon_consistency_20260804 /opt/anaconda3/bin/python3.13 docs/handoff/eval_chain_carbon_consistency_20260804/reproduce_minimal.py --mode fixed-run
```

**[FACT]** 最小复现的修复后输出是：O route hash `24fb8fb9457d...`、`53.572182 kWh`、`37.417653 kg`；C route hash `f064404eb2f7...`、`87.548679 kWh`、`57.304565 kg`。两臂每一侧的搜索侧与最终评价充电排放均逐位相等，服务量均为 `50/50`、`13264/13264`。

## 2. 诊断

### 2.1 槽索引口径

**[FACT]** 输入日历是每城市 48 行、`hourly_calendar_row=1..48`；内部 `charging_slot_breakdown`/`charging_action_slot_breakdown` 使用 0-based `slot_index=0..47`。`cost.py:73-107` 的 `carbon_slot_index` 与 `carbon_profile_row_for_slot` 将时间按 1800 秒映射，并按实际 profile 长度 48 循环；没有 24 槽替换、1-based 直接索引、UTC 另加偏移或整体时移。

**[FACT]** 搜索代理的时变电费/碳值在 `baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/pyvrp_adapter.py:969-992` 通过同一 `time_profile_rows_for_node` 取候选城市行；完整充电排放在 `cost.py:723-753` 通过同一节点 profile、同一 slot breakdown 和 `carbon_profile_row_for_slot` 结算。T5 的槽输出只是把内部 0-based 槽加 1 展示。

**[INFERENCE]** C 的槽 9—14 与 O 的槽 25—28 不是固定的索引偏移：它们来自不同的 `charge_start_second` 和不同的变体选择。索引口径本身不能解释异常。

### 2.2 城市口径

**[FACT]** `cost.py:110-144` 按充电动作的 station/depot 节点城市筛选 profile。相关动作的 `D_beijing` 与 `D_tianjin` 两侧均使用各自城市行；T5 也在 `probe_driver.py:573-574` 检查 O/C profile 相同。未发现北京/天津互取或跨城市碳曲线。

### 2.3 是否存在最终重排

**[FACT]** T5 route-pool 路径调用 `complete_china81_route_skeleton` 生成 route variant 和充电动作；`china81_completion.py:329-350` 生成动作并以完整 evaluator 评分，`china81_completion.py:533-537` 只做 physicalize 后再次 exact score。route-pool 的 `_accepted_mip_completion`（`route_pool_sp.py:591-600`）和 set-partitioning recheck（`route_pool_sp.py:812-820`）同样只检查，不重新选择充电 start。

**[FACT]** 通用 winner 路径另有 `reschedule_between_trip_charging`，但本 T5 runner 调用的是 prototype route-pool 入口；T5 的 `probe_local_hook_origins` 和 witness action ledger 没有显示该通用 winner 重排被调用。

**[DECISION]** “最终完整解被另一个只看电费的模块重排”被排除；既有动作在搜索侧完整评分与最终 reporting 评分之间没有被移动。

### 2.4 权重、符号与单位

**[FACT]** T5 C search bundle 在 `probe_driver.py:509-519, 538-549` 使用 `carbon_price=0.07502`，并将 `diesel_ef=0` 限定为充电侧碳项；完整 reporting bundle 恢复基准 `diesel_ef`。C 的搜索闭合式是运营成本加 `0.07502 × E_ev_indirect`，最终 unchanged evaluator 仍对 `E_cv_direct + E_ev_indirect` 计碳成本。

**[FACT]** T7 wrapper 对 18 次逐行同时做 search-bundle exact score 和 reporting-bundle exact score。搜索侧与最终评价的充电排放最大绝对差为 `0.0 kg`，充电电费最大绝对差为 `0.0 CNY`。因此没有 kg/t、符号或充电项被吸收/抵消造成的记账分裂。

## 3. 根因

**[FACT]** 修复前 `china81_completion.py:316-320` 无条件遍历：

```text
ev_integrated -> integrated, carbon_weight=1
ev_low_carbon -> legacy, carbon_weight=1
ev_immediate -> integrated, carbon_weight=0
```

**[FACT]** `support/charging.py:634-652` 中，`integrated` 分支调用可注入的 timing scorer；`legacy` 分支直接调用 `_lowest_gamma_slot_start`，即按最低碳 profile 选槽，不按 O/P 的电费-only 目标选槽。

**[INFERENCE]** T5 的本地 hook 使 C 的 integrated timing 使用“电费 + 碳价×充电排放”，但 O/P 的 legacy 分支仍绕过该 hook。于是 O 虽然声明 search objective 为 operating cost，却可能接纳一个按碳最小化时刻生成的 EV route；C 则按小额货币碳项与电费的真实权衡选择更便宜的时段。原异常是 O 控制臂被隐藏碳择时污染后的跨臂比较，不是同一个解在 search/final 两个评价器中出现两个排放值。

## 4. 修复

**[DECISION]** 在非受保护文件 `solver/src/setp_solver/china81_completion.py:312-327` 增加 `variant_specs`：当 `carbon_price <= TOL` 时不生成 `ev_low_carbon`；当碳价为正时保留该既有分支。该改动只修正变体接线与臂目标的一致性，未改变任何目标项公式或物理约束。

**[FACT]** 修复后 `solver/tests/test_refined_carbon_charging.py` 为 `7 passed`，T5 driver self-test 为 `SELF_TEST_PASS`。完整 T7 runner 使用 `pyvrp 0.12.2`、Python `3.13.9`、`numpy 2.3.5`、`scipy 1.16.3`，单次最长 `19.143627 s`，未触发 30 分钟停止条件。

## 5. 修复后 18 次验收

**[FACT]** 18/18 为 `PASS_FULL_LEGAL_SOLUTION`，0 violation，0 wallclock safety stop；所有运行均满足服务量红线 `completed_customer_count=50/50`、`completed_demand=13264/13264`。

| budget | seed | 路线是否相同 | C−O 充电排放 kg | C−O 系统排放 kg |
|---:|---:|:---:|---:|---:|
| 100 | 1 | 否 | +5.851692 | −28.918787 |
| 100 | 2 | 是 | −1.988733 | −1.988733 |
| 100 | 3 | 是 | −1.987186 | −1.987186 |
| 1000 | 1 | 否 | +19.886912 | −16.817447 |
| 1000 | 2 | 否 | +10.844354 | −35.570672 |
| 1000 | 3 | 否 | +4.372370 | −37.423859 |

**[FACT]** 因此六个 C−O 配对中，路线改变 `4/6`，系统排放下降 `6/6`；18 次服务量全部为 `50/50` 与 `13264/13264`。

**[FACT]** 对用户指定的 budget 1000/seed 1：原“同路线同电量”条件不再成立；O/C 路线 hash 已不同，充电量为 `53.572182` 与 `87.548679 kWh`。C 充电排放高于 O `19.886912 kg`，但系统排放低 `16.817447 kg`，原因是换路后燃油直接排放下降；这不是原 T5 的同路线、同电量矛盾。该差异也不构成论文结论。

## 6. 未闭合问题与边界

**[FACT]** 修复后 C 在 6 对中有 4 对充电排放高于 O，但这 4 对均发生路线变化或电量变化；在路线保持不变的两对中，C 充电排放均下降。C 不被声明为对 O 的逐对 Pareto 支配者。

**[DECISION]** 本任务验证闭合，`decision.json.paper_claim_allowed=false`。T7 结果只是修复验证，不进入论文正文或正式实验统计。

**[HALT_*]** 无。三个受保护文件开工前/收工后 SHA-256 均未变化：

```text
solver/src/setp_solver/cost.py              e7ea406da87a3172cd1ff7dc87fe7def536e74f197f6c67b29da2394fe42b00d
solver/src/setp_solver/check.py             86b813152b2fc7f89500468cc3d73178cb1bdafe9dc659852b437c5fdb07702b
solver/src/setp_solver/search/evaluation.py c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3
```

## 7. 产物

逐次结果见 [raw_runs.csv](raw_runs.csv)，槽级闭合见 [slot_distribution.csv](slot_distribution.csv)，运行 witness 见 [solution_witnesses.json](solution_witnesses.json)，最小复现见 [reproduce_minimal.py](reproduce_minimal.py)，完整批次配置与执行信息见 [metadata.json](metadata.json) 和 [runner_state.json](runner_state.json)。哈希清单见 [artifact_hashes.json](artifact_hashes.json)；清单排除了 `._*`、`__pycache__`、`.pytest_cache`、`.t7-eval-chain-carbon-consistency.monitor` 与临时文件。
