AUDIT1_DONE

# AUDIT-1：底层实现缺陷定点审计

## 一句话结论

`INFERENCE`：本轮按任务书核完 11 个反常信号并做了七类定点坏味道普查，确认 **4 个（b）缺陷条目**：A1 是已经修掉的历史发车时钟断裂；C2 是当前主入口已兜底、但结果字段和旧 C8 入口仍残留“外包/崩溃”旧语义；D2 是当前路线层对同一区间随标签数重复解码；D3 是当前通用 `accepted` 口径混入种群留存。当前代码里，**D2 是唯一有直接代码证据、可能同时吃掉三大实验搜索预算的缺陷**；C2 只会在复用旧 C8 入口时压住动态实验，D3 会扭曲所有读数但不改变求解结果。

## 1. 缺陷表

判定口径：`(a)` 真实约束或符合现有算法合同；`(b)` 实现、接线或口径缺陷；`(c)` 仅靠读码不能定案。

| 编号 | 信号 | 判定 | 证据（文件:行号） | 可能压住的图/实验 | 最小修法 | 改动面 | 风险 | 触及受保护文件 |
|---|---|---|---|---|---|---|---|---|
| A1 | 63/63 `NO_FEASIBLE_WINDOW` | **(b)，历史缺陷已修；旧 63 条中有多少由它造成仍 UNKNOWN** | `FACT`：旧样本在原始、放宽窗口和 FRVCPY 三种重放下均为 63/63，见 `solver/reports/design_probe_death_survey2_20260815/report.md:45-56`。随后查明生成端与检查端发车时钟不同，见 `solver/reports/fix_s1s2_20260816/report.md:15-23`。当前生成端已直接调用检查端的 `route_departure_second`，见 `solver/src/setp_solver/search/multitrip_schedule.py:718-764`。修后 SC0 终解有 1 EV、2 次充电且 0 违规，见 `solver/reports/sc0_witness_adapter_20260816/report.md:53-69`。 | 历史上直接压混合车队和图 5；当前这条断裂链已不再成立 | 不再改时钟；保留当前单一发车时钟调用。若要量化旧 63 条责任，只做第 4 节 A1 探针 | `multitrip_schedule.py` 及调用它的非保护充电重建 | 再复制一套时钟会复发 S1；不应为旧样本继续改物理合同 | 否 |
| A2 | 初始化 3744 次仅 2 个新骨架通过，2542 次无充电窗 | **(a)，该分布属于旧随机初始化路径，不是当前 SC0 分布** | `FACT`：旧 run5 的 3744 次尝试为 2 通过、2542 充电窗、522 趟重叠、309 客户窗、368 无发车，见 `solver/reports/fix_s1s2_20260816/report.md:137-150`。当前初始化先走见证扰动、随后才走随机兜底，见 `solver/src/setp_solver/algorithms/problem_hgs/initialization.py:600-708`；SC0 实际为 witness 1/1、perturb 24/121、random 0 次，且无 depot 充电窗拒绝，见 `solver/reports/sc0_witness_adapter_20260816/report.md:38-51`。 | 旧路径曾压混合车队；当前 SC0 不受这组 2542 统计支配 | 不修；不能再拿旧 3744 分布描述当前 SC0 | 无 | 若据旧分布改窗，会把已修问题和当前候选生成混在一起 | 否 |
| A3 | 带罚项成本接受，真实成本可上升 | **(a)，是 HGS 的可行性恢复规则；未发现系统性把车型推向 CV 的代码证据** | `FACT`：教育按 `penalized_cost` 选候选，见 `solver/src/setp_solver/algorithms/problem_hgs/education.py:472-495`；接受后同时单独记录真实成本、排放和 EV 客户变化，见 `solver/src/setp_solver/algorithms/problem_hgs/contracts.py:169-215`。第 13 条 EV→CV 的真实成本增加 38.471266，但 15 条接受中 8 条 CV→EV、7 条 EV→CV，EV 客户净增 9，见 `solver/reports/diag_ev_absence_20260816/report.md:36-64`。可行池 best 按真实总成本选，见 `solver/src/setp_solver/algorithms/problem_hgs/population.py:353-370`；integrated adapter 也把真实总成本作为 objective、罚后成本另列，见 `solver/src/setp_solver/algorithms/problem_hgs/integrated_private.py:1066-1105`。 | 会影响混合车队的搜索路径，但现有证据不支持“系统性压 EV” | 不改接受目标；如需判方向，只做第 4 节 A3 离线分层统计 | 无 | 改成只接受真实成本下降会破坏现有不可行池修复语义 | 否 |
| B1 | 罚分自适应从未触发 | **(a)，窗口未攒满，不是参数键或注册接线错误** | `FACT`：入口默认窗口为 50，见 `solver/scripts/run_problem_hgs_private_technical.py:2788-2796`；管理器每次注册追加一次，只有长度等于窗口才更新，见 `solver/src/setp_solver/algorithms/problem_hgs/population.py:161-207`。同入口把 U 改为 4 后实际发生 2 次更新，U=50 只有 11 次注册、0 次更新，见 `solver/reports/penalty_window_probe_20260816/report.md:5-23`。 | 不构成时变碳或其他实验的底层压制 | 不修；U 是否调整是后续参数标定，不是本审计的代码修复 | 无 | 把“未攒满”误当断线会引入未经批准的新参数口径 | 否 |
| B2 | `frvcpy_enabled=false`、曲线转换计数 0 | **(a)，两个量都被误读：FRVCPY 不是非线性曲线总开关，转换计数只属于 schedule oracle** | `FACT`：CLI 明写 FRVCPY 只优化固定路线的充电站点和电量，默认保留现有修复，见 `solver/scripts/run_problem_hgs_private_technical.py:2857-2862`；该值传入 policy 并在两处分支读取，见 `solver/scripts/run_problem_hgs_private_technical.py:3105-3110`、`solver/src/setp_solver/algorithms/problem_hgs/charging.py:1029-1045,1353-1363`。默认修复仍调用 `_curve_aware_action`，见 `solver/src/setp_solver/algorithms/problem_hgs/charging.py:1883-1895`；曲线核按 SOC 分段算时长，见 `solver/src/setp_solver/charging_action.py:17-75`、`solver/src/setp_solver/charging_curve.py:86-106`。保存解在 FRVCPY=false 时仍带 `M17_FAST_SHAPE_SCALED_60KW_PWL`，见 `solver/reports/sc10_education_depth_20260816/n3/metadata.json:478-489`、`solver/reports/sc10_education_depth_20260816/n3/best_solution.json:225-247`。同一产物的 schedule oracle 样本数为 0，所以其 curve transitions 也为 0，见 `solver/reports/sc10_education_depth_20260816/n3/best_solution.json:995-1031`；该计数只在 oracle 内累加，见 `solver/src/setp_solver/algorithms/problem_hgs/schedule_oracle.py:745-764,1789-1801`。 | 不压时变碳；若充电 SOC 始终未过拐点，则只是当前动作没有暴露非线性差异 | 不修开关；报告中把该计数改称“schedule-oracle 曲线节点数”，不要叫全局曲线启用次数 | 报表字段/文字，不改物理核 | 若强开 FRVCPY，会同时改变站点和电量，不能当作“启用曲线”的最小修复 | 否 |
| B3 | 时变碳 5210 提案、0 接受 | **(a)，低碳价归因成立；实现还把后续通道限制为共享充电资源的二次机会，但没有写死必拒** | `FACT`：择时目标在 `cost_plus_carbon` 下明确为电费加碳价乘排放，见 `solver/src/setp_solver/charge_timing.py:426-460,462-520`。现有普通充电修复已经对每个固定动作的电价/碳价断点选过局部最优，后续只生成其他车辆释放充电资源的时刻，见 `solver/src/setp_solver/algorithms/problem_hgs/charging.py:1209-1225`；这些候选统一记作 `time_varying_carbon_charge`，见 `solver/src/setp_solver/algorithms/problem_hgs/proposals.py:180-229`。固定电量从夜谷移到 13:00 的局部临界值为 1.472 元/kg，现行 0.075 只有其约 1/19.6，见 `docs/handoff/algorithm_full_design_20260816.md:113-122`。 | 时变碳图 3/图 5 的当前碳价臂真实缺少成本驱动力，不是实现侧强制清零 | 不修；后续若做碳价扫描，必须每档重搜，不能把 5210 个后处理提案当成完整政策扫描 | 无 | 把后续二次通道扩成另一套全量择时会重复普通修复并改变搜索预算 | 否 |
| C1 | C8 第 5 批 `no feasible clock` | **(c)，读码无法区分真无解与动态续接时钟重复实现出错** | `FACT`：旧包只保存批次、客户和错误，未保存失败路线节点、`departure_floor`、`latest` 或资产释放时刻，见 `solver/reports/c8_stream_20260816/failure_diagnostic.json:1-77`。动态 `_route_profile` 自己重算 preferred/latest，并在 `latest < departure_floor` 时抛错，见 `solver/src/setp_solver/search/dynamic_multitrip_schedule.py:1427-1511`；静态 `route_timing` 有一套几乎相同的前后向时钟递推，见 `solver/src/setp_solver/search/multitrip_schedule.py:446-550`。动态分配随后才把资产释放时刻并入边界，见 `solver/src/setp_solver/search/dynamic_multitrip_schedule.py:810-860`。现有测试同时覆盖“唯一车辆回得太晚而拒绝”和“等待车辆回场后可服务”，见 `solver/tests/test_dynamic_multitrip_schedule.py:458-526`。 | 可能压动态需求实验 | 第 4 节 C1：重放该一条失败路线，对同一输入同时打印动态 profile 和权威 `route_timing` 的 floor/latest，不跑搜索 | 只读探针；若证实不一致，最小修法是让动态 profile 调用同一时钟核 | 失败输入未完整保存，重构错误会污染结论 | 未定；建议修法不需碰保护文件 |
| C2 | 动态插入无 reject/兜底，以崩溃代替兜底 | **(b)，生产主入口已修；结果合同和旧 C8 入口仍残留错误语义** | `FACT`：当前插入器会捕获候选的 `TypeError/ValueError`、记录拒绝并尝试直接插入兜底，全部失败才返回结构化失败，见 `solver/src/setp_solver/algorithms/problem_hgs/dynamic_insertion.py:316-410,443-488`。生产 MAIN3B 对异常和无可行候选都顺延，见 `solver/src/setp_solver/main3b_backend.py:280-361`；顺延字段进入最终读数，见 `solver/src/setp_solver/main3b_backend.py:1345-1360`。但 `DynamicInsertionResult` 仍把未插入客户叫 `outsourced_customer_ids`，见 `solver/src/setp_solver/algorithms/problem_hgs/dynamic_insertion.py:139-147,400-408`；生产 state 也残留一个未使用的同名字段，见 `solver/src/setp_solver/main3b_backend.py:170-212`。旧 C8 入口遇异常仍抛 `C8RunFailure`，失败结果仍按“外包”移出活动客户，见 `solver/scripts/run_problem_hgs_c8_stream.py:601-656`，与已定“顺延且不定价”冲突，见 `docs/paper_gci_dmm_vrp_20260804/pending_decisions.md:1075-1102`。 | 当前 MAIN3B 不被压；复用旧 C8 入口会压动态实验并误记服务量 | 若旧 C8 仍保留：把结果字段改为 `deferred_customer_ids`，旧入口按 defer 保留客户；若旧入口不再使用，直接标历史入口并删除死别名 | `dynamic_insertion.py`、`main3b_backend.py` 的死字段、旧 C8 脚本及相关报表测试 | 字段改名有历史产物兼容风险；不得把旧“外包”成本迁入新结果 | 否 |
| D1 | 历史 199 passed、当前可复算 197 passed | **(c)，是历史测试输入清单缺失，不是已证实少了两个测试** | `FACT`：SC0 报告只记 199 passed，没有保存命令和文件清单，见 `solver/reports/sc0_witness_adapter_20260816/report.md:82-88`。当前可复算清单逐项保存 29 个文件并得到 197 passed，见 `solver/reports/penalty_window_probe_20260816/regression_197.txt:1-37`；后续报告也明确无法找到旧 199 中缺失的两个文件或命令，见 `solver/reports/sc8_decoder_crossover_20260816/report.md:140-148`。 | 所有回归读数的证据完整性；尚无证据表明算法效果被压 | 第 4 节 D1：找旧任务日志或 `--collect-only` 节点清单，与当前节点逐项 diff；找不到就永久保留 UNKNOWN | 只读测试清单核对 | 不能随便加两个测试把数字补成 199 | 否 |
| D2 | 441 次路线层解码耗时 760.97 秒，而另一包约 7.7 ms/次 | **(b)，当前热循环存在确定的重复计算；它解释多少倍差距仍 UNKNOWN** | `FACT`：N=1 包记录 441 次解码、760.9707096652419 秒，见 `solver/reports/sc10_education_depth_20260816/n1/best_solution.json:979-986`；SC8 包记录 10 次、0.0774687509983778 秒，见 `solver/reports/sc8_decoder_crossover_20260816/route_layer_900/best_solution.json:1177-1184`。两者分别为 1.725557 秒/次和 0.007746875 秒/次，相差 222.742 倍。`_split_block` 把只依赖 `(position,end,车型,车场,班次)` 的 `_probe_segment` 放在每个存活 label 的内层，见 `solver/src/setp_solver/algorithms/problem_hgs/hybrid_decoder.py:398-449`；分块长度又由相邻客户的车场/车型/班次连续性决定，见 `:315-358`。 | 路线层开启时会吃掉混合车队、时变碳、动态需求三类实验的共同搜索预算 | 在 `_split_block` 内按 `(position,end)` 预计算/缓存 `_probe_segment`；不改标签支配、选中规则或完整评价 | `hybrid_decoder.py` 一处及其单测/函数级计时 | 缓存对象必须不可变；修后先核 candidate、gap、fingerprint 逐位相同。不得预先承诺速度倍数 | 否 |
| D3 | `evaluated` / `accepted` / `admitted` 是否混用 | **(b)，专用计数已分开，但通用 `accepted_actions` 和轨迹布尔值仍跨层混用** | `FACT`：`proposed_actions`、`evaluated_actions`、`accepted_actions` 与 `population_admission_attempts/admissions` 是独立字段，见 `solver/src/setp_solver/algorithms/problem_hgs/contracts.py:67-108`。但 `record_population_admission(inserted=True)` 又调用 `record_acceptance("hgs_population")`，把留存计入通用 accepted，见 `:243-249`；序列化同时输出两套数字，见 `:354-378,426-430`。轨迹中的同一个 `accepted` 在教育阶段表示罚后成本改善，见 `solver/src/setp_solver/algorithms/problem_hgs/education.py:490-525,576-600`；在 population 阶段则表示是否留在种群，见 `solver/src/setp_solver/algorithms/problem_hgs/runner.py:1113-1135`。 | 不压求解，但会让三大实验的“接受数”被误读，继而误判机制是否生效 | 保留专用计数；通用轨迹增加 `acceptance_level=move/population`，报表禁止把 `accepted_actions` 求和当搜索动作接受数。兼容期不删旧字段 | `contracts.py`、轨迹 schema、报表读取 | 历史 JSON 兼容；必须区分“字段改名”和“历史数字重算” | 否 |

## 2. 七类坏味道普查

`DECISION`（审计筛选口径）：命中很多的类别只列与 A1–D3 靶子直接相交、且位于当前问题 HGS/动态/充电热路径的最可疑项；以下不是对整个 `solver/src/setp_solver/` 的总体质量外推。

### 2.1 同一物理量有两个计算来源

- **发车时刻**：历史生成端与检查端不同源，已按 A1 修成 `route_departure_second` 单源调用（`FACT`：`solver/src/setp_solver/search/multitrip_schedule.py:738-764`）。判定：历史 (b)，当前该点已修。
- **动态路线时钟**：动态 `_route_profile` 和静态 `route_timing` 各自做一次同形前后向递推（`FACT`：`solver/src/setp_solver/search/dynamic_multitrip_schedule.py:1473-1511`；`solver/src/setp_solver/search/multitrip_schedule.py:446-550`）。判定：(c)，对应 C1。
- **充电曲线**：动作构造从同一个 `charging_curve` 核取得时长和 curve id（`FACT`：`solver/src/setp_solver/charging_action.py:17-75`；`solver/src/setp_solver/charging_curve.py:1-6`）。判定：(a)，未发现第二套线性 `energy/power` 偷换主路径。

### 2.2 名实不符

- `outsourced_customer_ids` 实际装的是“本触发点未插入、应顺延”的客户（`FACT`：`solver/src/setp_solver/algorithms/problem_hgs/dynamic_insertion.py:139-147,368-408`）。判定：(b)，对应 C2。
- 轨迹 `accepted` 同时表示局部动作改善和种群留存（`FACT`：`solver/src/setp_solver/algorithms/problem_hgs/education.py:490-525`；`solver/src/setp_solver/algorithms/problem_hgs/runner.py:1126-1135`）。判定：(b)，对应 D3。
- `rebuilt_shift_neighbours_only` 实际只收窄 neighbours，名字没有承诺候选物化后的全局班次可行性；候选物化另有硬检查（`FACT`：`solver/src/setp_solver/algorithms/problem_hgs/kernel_proposals.py:131-140,185-203`；`solver/src/setp_solver/algorithms/problem_hgs/initialization.py:588-591,690-708`）。判定：(a)，旧 S2 问题不能再归因于这个名字。

### 2.3 控制流断裂

- S0 当前停止分支会补一次完整评价并返回当前候选，runner 随后执行 `population.add` 和 admission 记账（`FACT`：`solver/src/setp_solver/algorithms/problem_hgs/education.py:369-393`；`solver/src/setp_solver/algorithms/problem_hgs/runner.py:1113-1115`）。判定：历史 (b) 已修，当前未见同点断裂。
- 当前生产动态入口异常/无候选均进入 defer；旧 C8 脚本仍抛错或移出“外包”客户（`FACT`：`solver/src/setp_solver/main3b_backend.py:300-361`；`solver/scripts/run_problem_hgs_c8_stream.py:601-656`）。判定：(b)，只剩旧入口风险。
- 种群提交后才计算当前 best，并优先 `best_feasible()`（`FACT`：`solver/src/setp_solver/algorithms/problem_hgs/runner.py:1137-1153`）。判定：(a)，未发现新的 best 更新跳过分支。

### 2.4 开关请求了但没生效

- FRVCPY：CLI → policy → 两个充电分支 → provenance 全部有读写（`FACT`：`solver/scripts/run_problem_hgs_private_technical.py:2857-2862,3105-3110,3648-3657`；`solver/src/setp_solver/algorithms/problem_hgs/charging.py:1029-1045,1353-1363`）。判定：(a)。
- 班次邻域：构造函数保存布尔值，邻域生成处实际读取，identity 也保存（`FACT`：`solver/src/setp_solver/algorithms/problem_hgs/kernel_proposals.py:50-80,131-140,240-253`）。判定：(a)。
- 路线层 crossover：只有开启时才构造 decoder spec 并进入路线层分支（`FACT`：`solver/src/setp_solver/algorithms/problem_hgs/integrated_private.py:280-292,459-469`）。判定：(a)。
- 本轮定点开关中没有发现“值传入但下游从不读”的新缺陷。

### 2.5 默认值/常量与文档或注册值不符

- 罚分窗口 CLI 默认 50，管理器使用同一个 `solutions_between_updates` 控制 deque 和触发条件（`FACT`：`solver/scripts/run_problem_hgs_private_technical.py:2788-2796`；`solver/src/setp_solver/algorithms/problem_hgs/population.py:177-207`）。判定：(a)。
- FRVCPY policy 默认 false，与 CLI `store_true` 和保存的 provenance 一致（`FACT`：`solver/src/setp_solver/algorithms/problem_hgs/charging.py:401-415`；`solver/scripts/run_problem_hgs_private_technical.py:2857-2862,3651-3657`）。判定：(a)。
- 当前路线修复先生成 same-day 局部动作，再由 duty 证书锚定上一夜/趟间窗口；这不是遗漏 `full_gap` 默认（`FACT`：`solver/src/setp_solver/algorithms/problem_hgs/charging.py:1380-1407,1883-1945`）。判定：(a)。

### 2.6 零值语义未区分

- `schedule_oracle_curve_transitions=0` 在样本数也为 0 时表示 oracle 没被调用，不表示非线性充电没启用（`FACT`：`solver/reports/sc10_education_depth_20260816/n3/best_solution.json:995-1031`；`solver/reports/sc10_education_depth_20260816/n3/best_solution.json:225-247`）。判定：(b) 报表解释风险，对应 B2；算法核不修。
- `population_admissions=0` 必须与 `population_admission_attempts` 一起读；合同已经分开两个字段（`FACT`：`solver/src/setp_solver/algorithms/problem_hgs/contracts.py:106-108,243-249`）。判定：(a) 底层字段足够，D3 的问题在通用 accepted 又混入 admission。
- `time_varying_carbon_charge accepted=0` 不能单独区分“没有更优时刻”和“候选被上游预先优化”；普通修复已先选局部最优（`FACT`：`solver/src/setp_solver/algorithms/problem_hgs/charging.py:1209-1225`）。判定：(a) 真实机会为零，不能据此改开关。

### 2.7 算例级不变量在热路径内重建

- 最可疑命中包括 `solver/src/setp_solver/algorithms/problem_hgs/charging.py:1047,1366,1476,1730` 的 `node_lookup` 重建，以及动态 `_route_profile` 的 `nodes` 重建（`FACT`：`solver/src/setp_solver/algorithms/problem_hgs/charging.py:1047,1366,1476,1730`；`solver/src/setp_solver/search/dynamic_multitrip_schedule.py:1441`）。
- 已有同实例微基准测得 651 次 `node_lookup` 投影仅 0.001913410 秒；即使把整个所在函数 self time 都算给它，也只占 113.226 秒的 0.0167%（`FACT`：`solver/reports/speed_diag_20260816/report.md:46-54`）。判定：代码质量命中，但不是当前性能病灶，不建议修。
- D2 的 `_probe_segment` 重复不是“算例级字典重建”，而是更严重的**标签层重复区间求值**，已单列为当前 (b) 缺陷。

## 3. 不建议修的

1. **不改罚分窗口来“修 B1”**：U=4 已证明接线能更新，但终解与 U=50 的成本和指纹相同（`FACT`：`solver/reports/penalty_window_probe_20260816/report.md:7-23,50-67`）。窗口属于后续标定，不是低级接线修复。
2. **不为 B2 强开 FRVCPY**：它会改变固定路线充电站点和电量，不是非线性曲线开关（`FACT`：`solver/scripts/run_problem_hgs_private_technical.py:2857-2862`；`solver/tests/test_problem_hgs_frvcpy_integration.py:186-223`）。
3. **不把 A3 改成“真实成本不上升才接受”**：现有可行池 best 已按真实成本保底，教育罚项承担的是修复不可行候选（`FACT`：`solver/src/setp_solver/algorithms/problem_hgs/population.py:274-288,353-370`；`solver/src/setp_solver/algorithms/problem_hgs/education.py:472-495`）。
4. **不随便加两个测试补成 199**：旧 199 没有命令/节点清单，当前能复算的输入得到 197（`FACT`：`solver/reports/penalty_window_probe_20260816/report.md:109-116`）。补数字不能补证据。
5. **不优化 `node_lookup`**：已有实测只占 0.0167%，不是 760.97 秒路线层慢点（`FACT`：`solver/reports/speed_diag_20260816/report.md:46-54`）。
6. **不再改 A1 发车时钟**：当前生成端已调用权威 `route_departure_second`，再次复制公式只会重开双源（`FACT`：`solver/src/setp_solver/search/multitrip_schedule.py:738-764`）。
7. **不先修旧 C8 的所有报表**：只有确认该脚本仍是正式动态入口才值得做；当前生产 MAIN3B 已按 defer 运行（`FACT`：`solver/src/setp_solver/main3b_backend.py:280-361`）。若旧入口退役，标历史比继续维护更小。

## 4. 需要探针才能判的

以下只给设计，本轮未执行。

### A1：旧 63 条中多少由时钟断裂造成

`UNKNOWN`：旧 CSV 只保留候选 fingerprint、changed duties 和原因码，没有序列化候选本体（证据：`solver/reports/design_probe_death_survey2_20260815/run2_reason_codes/charging_diagnosis/relaxation_probe.csv:1-3`），不能在当前 checkout 原样重放。

`DECISION`（最便宜探针）：同 seed 只捕获前 63 个 duty-crossover 充电拒绝候选并立即停；每个候选在同一进程内分别调用“当前权威时钟”和只读复刻的“旧 earliest-departure 时钟”，保存 reason code、失败 duty、窗口上下界。只比较同一候选的原因变化，不看终解、不延长预算。

### A3：换型是否在更大样本中方向性偏 CV

`DECISION`（最便宜探针）：不求解，离线读取已保存的完整 trajectory；只取 `phase=education`、`channel=whole_duty_type_exchange`、`accepted=true`，按“接受前是否可行、接受后是否可行、EV 客户变化、真实成本变化、罚后成本变化”五列分层。若可行→可行层仍显著偏 EV→CV，才有方向性证据；不可行→更少违规层不能当车型偏置。

### C1：第 5 批到底是真无解还是时钟算错

`DECISION`（最便宜探针）：从第 4 批保存状态和第 5 批事件重建**这一条** `open-CV_D_OSM_WAY_1003511503_1-1`；不跑 HGS。记录 route nodes、origin ready/service、minimum departure、资产 available、动态 preferred/latest；再对同一路线调用 `route_timing`，比较两套 floor/latest 和首个过窗客户。若两套时钟不同，判 (b)；若相同且 asset boundary 晚于 latest，判 (a)。

### D1：199 与 197 的两个差额

`DECISION`（最便宜探针）：先查 SC0 原任务日志/终端历史里的完整 pytest 命令或 node id；找到后对当前 `pytest --collect-only -q` 节点做集合差。若找不到旧节点清单，不再复猜，永久保留 `UNKNOWN`。

### D2：222.742 倍差距中重复区间探测占多少

`DECISION`（最便宜探针）：不跑求解器，直接把两个已保存 customer order 送进 `decode_customer_order`；用 monkeypatch 只计 `_probe_segment` 的 `(position,end)` 总调用数和唯一键数，再用函数内临时 memo wrapper 复跑。验收只看输出 candidate、gap、changed ids 完全相同，并报告调用数/墙钟；不先设提速门槛。

## 5. UNKNOWN 清单

1. A1：旧 63 条中由 S1 发车时钟断裂直接造成的条数。
2. A3：超出已保存 15 条换型接受记录后，罚项接受是否在可行→可行层存在稳定车型方向偏置。
3. C1：旧 C8 第 5 批是资产确实回得太晚、候选客户顺序无解，还是动态 `_route_profile` 与权威时钟不一致。
4. D1：历史 199 相比当前可复算 197 多出的两个具体 pytest node id。
5. D2：222.742 倍单次耗时差中，重复 `_probe_segment` 的实际占比和缓存后的真实提速。
6. C2：旧 `run_problem_hgs_c8_stream.py` 是否仍会被正式动态实验调用；当前事实入口只证明 MAIN3B 是生产兜底已接通的路径（`FACT`：`solver/src/setp_solver/main3b_backend.py:280-361`）。

AUDIT1_END
