SELFBUILT_DONE

# Problem-HGS 自造件清点与替换提案（2026-08-17）

## 结论先说

`FACT`：`solver/src/setp_solver/algorithms/problem_hgs/` 的 37 个真实 Python 模块合计 **25,369 行**；本轮继续追到 10 个直接或同职责的跨目录算法模块，合计 **9,960 行**。行数是当前工作树物理行数（含注释和空行），不含 macOS 的 `._*.py` 元数据文件。

`FACT`：这些代码不能一刀切成“全是自造”。当前包里同时存在三类东西：

1. **已经拿来的成熟实现**：PyVRP 0.12.2 HGS 内核、SREX、编译邻域、frvcpy；
2. **把成熟算法重新手写了一遍的代码**：自造种群/罚分、旧 HGS 外循环、通用邻域、Regret 修复、SISR、NSGA-II、停止器、DCREX 重写；
3. **项目语义适配层**：实体车多趟、双班次、跨趟 SOC、充电窗、两车场归属、动态锁、完整成本/可行性真值桥。这部分没有找到可直接替代的一体开源实现，但目前写得过厚，应压成薄适配层。

`CORRECTION`：任务书给出的种群起点对历史缺陷是正确的，但当前单目标私有主路径已经不是全量自造种群。`bi_objective_population.py:441-461` 在单目标模式返回内核 `ExternalPopulation`，`integrated_private.py:1095-1122` 又把它交给内核 `IntegratedGeneticAlgorithm`。仍需清掉的是 `population.py` 中自造罚分/参数/距离及 `runner.py:551-567` 明示的退役外循环，而不是把当前主路径误写成仍由 `DutyPopulation` 驱动。

`DECISION`（提案）：最值得先换的是“成熟 HGS 已有、项目又写了一份”的骨架；真正承载项目特殊语义的部分不应继续长成第二个求解器，只保留输入翻译、完整评价回调和结果翻译。

## 取证口径与路径缩写

- 本轮按**当前工作树**静态清点。开始检查时任务范围内已经有多处已修改源码，以及 2 个未跟踪源码（`c0_witness_adapter.py`、`hybrid_decoder.py`）；这些都不是本任务改的，本报告按读取时的当前内容取证。
- 只读了文本、行数、导入关系和现有来源快照；**没有 import 求解器、没有运行测试、没有启动求解、没有实验**。
- “自造”包括“照论文自行重写”；只有原样复制、直接调用或明确薄适配才记为“拿来”。依据见 `solver/src/setp_solver/algorithms/problem_hgs/PROVENANCE.md:7-22`。
- “未检索到”只表示：在当前仓库、已冻结开源快照、现有材料清单以及本轮官方源码定向核查中未找到同职责可直接使用的实现；不把有限检索伪装成世界范围不存在。
- 八行影响对照来自 `docs/handoff/algorithm_phase_prd_20260817.md:20-22`：①时变碳（图3/图5）②混合车队（图5/5.2）③多企业协同 ④实体车多趟 ⑤成本/参数/算例表 ⑥动态需求5.3 ⑦公平分配表 ⑧公开对比表。
- 表内路径缩写：
  - `K/` = `third_party/setp_hgs_kernel/setp_hgs_kernel/`
  - `F/` = `third_party/harvested_materials/04_ev_charging/frvcpy_2020_1035/upstream/src/frvcpy/`
  - `D/` = `third_party/harvested_materials/06_dynamic_demand/`
  - `S/` = `third_party/harvested_operators/open_source_sisr_routing_2026/`
  - `M/` = `third_party/harvested_materials/08_green_objectives/pymoo_nsga2/upstream/pymoo/algorithms/moo/`
  - `C/` = `third_party/harvested_materials/07_collaboration_profit/pycoopgame/upstream/pyCoopGame/`

## A. `problem_hgs/` 全模块清点

| 模块 | 行数 | 职责 | 自造/拿来 | 现成替代（文件:行号或“未检索到”） | 替换代价 | 风险 | 建议优先级 |
|---|---:|---|---|---|---|---|---|
| `__init__.py` | 84 | 汇总并导出 Problem-HGS 公共接口。 | 自造胶水 | 未检索到；这不是算法职责。 | 不能直接删；随被替模块同步缩短导出表。 | 误删会破坏所有调用入口；影响①②③④⑥⑦⑧。 | 保留薄层 |
| `bi_objective_population.py` | 469 | 用完整成本与排放做 NSGA-II 排序、拥挤度、存活与档案。 | 文献重写，算自造（文件:1-9） | `M/nsga2.py:23-77,85-127` 已有二元锦标赛、rank/crowding 和 NSGA-II。 | 需把 `DutyIndividual`、完整可行性和两目标值包装成 pymoo `Problem/Population`；保留 HGS 交叉适配。 | 直接换会改变随机流、并列破平和档案顺序；只影响显式双目标臂，关联①②及图3/图5。 | 高：换掉 NSGA-II 骨架 |
| `c0_witness_adapter.py` | 166 | 把已保存见证解从 CSV→Route→Solution→Duty，并恢复实体车槽位。 | 自造项目适配（文件:1-6） | 未检索到同数据契约实现。 | 不可直接换；只能继续压薄为格式翻译。 | 删除会失去已验证的可行初始化；影响①②③④⑥。 | 必须保留薄层 |
| `charging.py` | 2,457 | 对改变后的实体车 Duty 重建充电，串起固定路线修复、多趟证书、时窗、SOC 与锁检查。 | 自造编排 + 已有充电器（文件:1-12） | `F/solver.py:33-96,150-167` 可替固定路线插站/充量；`F/algorithm.py:20-85,559-590` 为原算法。未找到同时含跨趟 SOC、双班次和项目充电窗的一体替代。 | 用 frvcpy 吞掉固定路线充电搜索；保留跨趟/锁/完整真值适配。 | frvcpy 目标是最短完成时间，不是电费+碳；直接全换会改①，且影响②④⑥。 | 高：大幅减薄，不全删 |
| `contracts.py` | 799 | 定义候选状态、运行记账、轨迹与来源数据结构。 | 自造胶水（文件:1-10） | `K/IntegratedGeneticAlgorithm.py:58-72,214-225` 已有运行记账/结果；领域原因码未检索到。 | 可把通用运行统计交内核，保留项目原因码和八行产物字段。 | 状态名迁移会影响报告读取；影响⑤及①②③④⑥⑦⑧的可追溯性。 | 中：去重后保留 |
| `crossover.py` | 647 | 在完整 Duty 层做整车/整趟交换，并承担 DCREX 适配、去重和缺失客户暴露。 | 自造（文件:1-12） | `K/crossover/selective_route_exchange.py:13-78` 已有 SREX；`K/crossover/ordered_crossover.py:10-80` 已有 OX，但仅 TSP 假设。 | 通用交叉交给内核；只保留“内核 route ↔ 实体车 Duty”的映射和锁保护。 | SREX 不携带跨趟 SOC/实体车身份；未经适配直接换会破坏①②③④⑥，公开端影响⑧。 | 高 |
| `crossover_control.py` | 111 | 在 fast/DCREX 两臂间按收益/时间分配选择。 | 文献启发的自造控制器（文件:1-12） | 同一控制器未检索到；若 DCREX 退出则无需替代。 | 随多交叉组合删除；只保留内核单一成熟交叉。 | 继续保留会维持无来源的策略层；删除只影响已废弃/默认关挂件和⑧。 | 立即清退（随 DCREX） |
| `dcrex.py` | 580 | 按论文重建多父代 DCREX、20 个范围、5 种插入和双控制器。 | 文献重写，明确无作者源码（文件:1-8；`PROVENANCE.md:19-22`） | **同名实现未检索到**；同职责成熟替代为 `K/crossover/selective_route_exchange.py:13-78`。 | 不是逐行替换，而是用 SREX 取代交叉职责并删除 DCREX 叙事。 | 会失去 DCREX 专属对比/归因；当前总表只直接影响⑧，三挂件已在 `algorithm_phase_prd_20260817.md:150` 记为废弃/默认关。 | 立即替换职责并清退 |
| `dynamic.py` | 565 | 把完成/执行中历史冻结在搜索外，未来 Duty 绑定继承实体车并完整验证。 | 自造项目语义（文件:1-5） | `D/dvrpsim/upstream/src/dvrpsim/model.py:18-56,147-169` 有事件、车辆、订单生命周期；未含本项目实体车 SOC/锁。 | 可用 dvrpsim 接管事件生命周期；保留未来 Duty、资产锁和完整评价翻译。 | 状态边界不一致会让已执行任务被重排；直接影响⑥，连带④。 | 必须保留薄适配；事件层可换 |
| `dynamic_insertion.py` | 884 | 在动态切点把新订单交给内核插入/局搜，再由完整 Duty 评价接受。 | 拿来内核 + 自造适配（文件:1-8） | 已在用 `K/search/LocalSearch.py:15-38,101-161` 和 `K/repair/__init__.py:1-5`；事件接口可用 `D/.../dvrpsim/model.py:165-169,250-265`。 | 不再另写插入算法；只保留动态切点、必须服务集合和 Duty 回译。 | 过度删除会丢动态锁与实体车继承；影响⑥。 | 保留并减薄 |
| `education.py` | 664 | 枚举 Duty 邻域、重建受影响充电并用完整真值选最佳改进。 | 自造搜索层（文件:1-10） | `K/search/LocalSearch.py:15-19,101-161`；算子清单 `K/search/__init__.py:5-37`。 | 内核生成/下降，项目层只做候选回译和完整接受；特有充电重定时另留一个动作。 | 内核代理成本不含全套电费/碳/公平，必须由完整评价回调兜底；影响①②③④⑥⑧。 | 立即替换通用部分 |
| `evaluation.py` | 1,502 | 把 Duty 转成项目 Solution，调用受保护 checker/cost/profit，并维护真值/增量缓存。 | 自造项目真值桥（文件:1-12） | 未检索到能覆盖本项目八项成本、实体车、多趟 SOC、动态锁、协同利润的开源实现。 | 不可直接换；只应压缩缓存和转换，受保护真值继续唯一。 | 删除或改义会让八行结果全部失真；影响①–⑧。 | 必须保留薄层 |
| `feedback.py` | 394 | 把完整违规映射成可寻址压力信号并做真值诊断。 | 自造诊断（文件:1-11） | 未检索到；本轮静态导入图未找到调用者。 | 从活跃算法包移出即可，无需找替代。 | 可能失去历史诊断脚本入口；对八行正式结果无当前影响。 | 立即移出活跃包 |
| `fleet_registry.py` | 109 | 为每个场站/车型建立可追踪的实体车槽位。 | 自造项目语义（文件:1） | `K/Model.py:347-435` 有 `num_available`、车型、场站与 reload，但不保存项目实体车 ID。 | 可让内核管数量；仍需一张“内核车辆索引→实体车 ID”薄映射。 | 完全删除会把多辆同型车混成匿名数量，破坏④⑥并影响②。 | 必须保留薄映射 |
| `frvcpy_adapter.py` | 508 | 原样调用冻结 frvcpy，把项目固定路线翻译进去并翻译充电站/充量结果。 | **拿来 + 薄适配**（文件:1-12） | 已在用 `F/solver.py:33-96,160-167`；来源 `.../frvcpy_2020_1035/ORIGIN.md:3-7`。 | 不替换上游；可合并重复翻译和删除自造后备充电搜索。 | 必须保留电价/碳/跨趟终审；影响①②④⑥。 | 保留；作为替换落点 |
| `hybrid_decoder.py` | 1,049 | 客户序交叉后做可行分段、实体车槽位选择并还原完整 Duty。 | 自造（文件:1-7） | OX 可用 `K/crossover/ordered_crossover.py:10-80`；内核已有多趟 Route/Trip `K/_setp_hgs_kernel.pyi:277-336`，但同语义的实体车分段解码器未检索到。 | 换 OX；分段优先用内核 route/trip/reload 表示；仅保留实体车与 SOC/锁回译。 | 当前路线层开关默认关闭；直接砍对当前默认路径无影响，若启用则影响①②③④⑥。 | 高：拆掉通用部分，暂留薄解码 |
| `independent.py` | 247 | 切出各车场独立服务子问题，生成公平分配的外部选项。 | 自造项目数据切片（文件:1-6） | 未检索到同一 China81 数据契约实现；`C/Shapley.py:30-50` 与 `C/Nucleolus.py:58-99` 只接联盟价值，不生成独立路线成本。 | 可移出主算法包，公平实验时由独立数据构造器调用成熟路由器。 | 本轮静态导入图未找到调用者；现在砍不影响已跑主线，未来影响⑦和③。 | 移出活跃包，不在 HGS 内自养 |
| `initialization.py` | 763 | 生成可复现初始 Duty 群体，补齐实体车、多趟、充电与完整可行性。 | 自造（文件:1-6） | 内核随机解 `K/_setp_hgs_kernel.pyi:327-336`；缺客户修复 `K/repair/__init__.py:1-5`；项目见证适配已有 `c0_witness_adapter.py`。 | 用“内核随机/修复 + C0 见证”替换通用扰动；保留 Duty 完成回调。 | 直接换可能让可行初始解再次稀缺；影响①②③④⑥。 | 高 |
| `integrated_private.py` | 1,145 | 把完整 Duty 的评价、交叉、教育、修复接到同一个内核 HGS 循环。 | **拿来内核 + 自造适配**（文件:1-7） | 已用 `K/IntegratedGeneticAlgorithm.py:22-55,75-106,114-225` 和 `K/ExternalPopulation.py:43-156`。 | 不应另换求解器；把回调压到最小，删除在适配层重复的搜索策略。 | 这是成熟内核与项目语义的边界；全删会中断①②③④⑥。 | 保留薄适配，优先减肥 |
| `kernel_proposals.py` | 1,163 | 让复制内核提出路线骨架，再无歧义映射回实体车 Duty。 | **拿来内核 + 自造映射**（文件:1-7） | 已用 `K/search/LocalSearch.py:15-38,101-161`；车型/多趟结构 `K/Model.py:347-435`。 | 删除代理搜索重复层，保留内核索引→实体车、充电/协同完整评价桥。 | 当前代理成本与真实时变电价不完全同义；贸然把代理当接受器会影响①②③④⑥。 | 高：减薄而不移除边界 |
| `mechanical_baseline.py` | 819 | 为动态订单做确定性最便宜可行插入基线。 | 自造基线（文件:1-12） | EURO 动态开源明确提供 greedy/lazy/random/oracle 和逐 epoch 静态 HGS：`D/euro_neurips_2022_code_only/upstream/README.md:56-65,75-87`；当前定向快照未保存其 `solver.py` 源码。 | 应重新取得带许可证的完整官方 baseline 源码后包装 Duty 评价；当前快照不足以直接施工。 | 不同 dispatch 定义会改实验对手；只影响⑥。 | 高，但先补全上游源码证据 |
| `model.py` | 762 | 表示实体车整日 Duty、趟次、锁和向旧 Solution 的封闭转换。 | 自造项目语义（文件:1-11） | `K/_setp_hgs_kernel.pyi:277-336` 有 Route/Trip/Solution；没有充电动作、动态锁和实体车 ID。 | 用内核对象承载普通路线/趟次；保留 sidecar 的实体车、SOC、锁。 | 全换为匿名内核 Solution 会丢④⑥语义并影响②。 | 必须保留最小 sidecar |
| `operators.py` | 1,219 | 实现 relocate/swap/2-opt/2-opt*/跨趟/跨场/换型/开趟/充电重定时等 Duty 动作。 | 大量自造，部分是标准算子（文件:1-12） | 标准算子 `K/search/__init__.py:5-37`；多趟插回库 `K/cpp/search/RelocateWithDepot.h:9-20,41-63`；跨场 `K/cpp/search/DepotSplit.cpp:33-64,112-139`。 | 标准路线动作全部交内核；只保留整 Duty 换型、动态锁和充电择时等项目特有动作。 | 不能把内核局部代理成本当完整接受；影响①②③④⑥⑧。 | 立即替换标准算子 |
| `population.py` | 603 | 自造可行/不可行池、偏置适应度、锦标赛、Duty 距离和完整违规罚分。 | **自造**（文件:1-20） | `K/ExternalPopulation.py:1-8,43-156`；原生分流 `K/Population.py:63-101`；自适应罚分 `K/PenaltyManager.py:124-166,234-286`。 | 当前单目标池已换；继续把罚分登记/参数/距离接口接到内核，并删除退役 `DutyPopulation`。 | Duty 的完整违规维度比内核 load/time/distance 多，需明确映射；影响所有搜索行①②③④⑥⑧。 | **第一优先** |
| `proposals.py` | 551 | 串行组织“内核路线提案→项目机制提案”，但不拥有接受权。 | 自造编排（文件:1-6） | 内核回调边界 `K/IntegratedGeneticAlgorithm.py:22-55,145-168`；同一 Duty 流未检索到。 | 把它压成一个 iterator/callback 适配；删掉重复身份/哈希算法则需迁移元数据。 | 完全删除会丢组件激活记录；影响①②③④⑥及⑤。 | 中：减薄 |
| `public.py` | 1,219 | 自管公开 MDVRPTW 的交叉组合、HGS 外循环、轨迹与问题连接。 | 自造外循环 + 内核部件（文件:1-6） | `K/GeneticAlgorithm.py:64-132,168-208` 与 `K/HGSControl.py:37-93` 已完整提供外循环；SREX 见上。 | 让公开入口直接调用复制内核；只保留输入/输出和必要的公开问题适配。 | 历史 DCREX 指标不再同定义；影响⑧，不应污染私有三实验。 | **第一优先** |
| `public_assignment.py` | 263 | 逐客户跨车场删除/重插，改善公开多车场分配。 | 文献思想的自造实现（文件:1-7） | `K/cpp/search/DepotSplit.cpp:33-64,64-139` 已有跨场段迁移；内核也暴露 `DepotSplit`：`K/search/_search.pyi:38-43`。 | 用编译 `DepotSplit` 取代 Python 全位置扫描；适配车型兼容组。 | 现有实现是逐客户，DepotSplit 是趟段前/后缀，邻域不完全相同；影响⑧。 | 高 |
| `public_search.py` | 531 | 构建公开 HGS，当前集成内核，同时保留历史分配 builder 和可选挂件。 | 拿来内核 + 自造 builder（文件:1-5） | `K/IntegratedGeneticAlgorithm.py:75-106`、`K/GeneticAlgorithm.py:93-132`。 | 删历史 builder 和自造挂件，只留内核参数/数据/结果翻译。 | 清理时要保留公开协议元数据；影响⑧。 | 第一优先：减薄 |
| `readiness.py` | 220 | 在动态披露事件之间给空闲 EV 安排观测需求下的待命充电。 | 自造项目机制（文件:1-6） | `D/dvrpsim/upstream/src/dvrpsim/model.py:18-56,165-169` 有事件/车辆生命周期；未检索到带非线性 SOC 的同策略。 | 事件推进可交 dvrpsim；只保留 SOC/充电动作决策。 | 隐藏信息边界和锁若适配错误会污染动态实验；影响⑥与①。 | 保留薄策略；事件层可换 |
| `repair.py` | 420 | 对交叉后缺失客户做 Regret-2 插入并用完整评价判定。 | 自造（文件:1-8） | `K/repair/__init__.py:1-5` 已有 greedy、nearest-route、SISR repair；精确同版 Regret-2 未检索到。 | 用内核 repair 生成完整路线，再由 Duty 适配/真值验收；若必须保留 Regret-2，应从有人类源码的实现引入。 | 修复顺序变化会改变搜索轨迹；影响①②③④⑥⑧。 | 高 |
| `runner.py` | 1,602 | 主入口、来源/轨迹/结果装配；后半仍保留退役自造 DCREX 外循环。 | 自造胶水 + 退役自造算法（文件:1-12；`:551-567`） | 活跃路径已经调用 `K/IntegratedGeneticAlgorithm.py:75-225`；通用结果 `:58-72`。 | 保留约 入口/元数据/结果翻译，删除 `:551` 后退役外循环及其只服务代码。 | 旧脚本若私下导入下划线函数会断；静态主入口不需要它。影响①②③④⑥⑧的运行包装，不改科学语义。 | **第一优先** |
| `schedule_capture.py` | 75 | 可选捕获原始候选，服务 DSS 诊断。 | 自造诊断（文件:1） | 未检索到；无需算法替代。 | 移出活跃包或随 DSS 归档。 | 删除只影响可选诊断，不影响当前八行正式结果。 | 立即移出活跃包 |
| `schedule_oracle.py` | 1,805 | 对固定结构 Duty 做精确事件标签排程，作为 DSS 默认关闭原型。 | 自造原型（文件:1-6） | 未检索到同时覆盖项目成本、跨趟 SOC、充电窗和实体车锁的开源实现。 | 当前不是主算法必需；移出活跃包。若以后确需同职责，再单独选开源调度器并做适配。 | 若误当正式接受器会形成第二套真值；当前默认关闭，移出不影响八行，启用时关联①④。 | 立即移出活跃包 |
| `sisr.py` | 392 | 在公开搜索中做相邻字符串破坏和贪婪重建，但不含原 SISR 接受规则。 | 文献重写，算自造（文件:1-8） | 人类开源完整实现 `S/cvrp/src/Sisrs.cpp:24-41,123-224,224-320`；VRPTW 版 `S/vrptw/src/Sisrs.cpp:26-41,92-192,192-360`；内核封装 `K/repair/__init__.py:3-5`。 | 直接绑定/调用开源 SISR 或内核 repair；适配多车场/有限车队输入。 | 当前自造版不等于完整 SISR；替换会改变公开轨迹，但只影响⑧且挂件默认关。 | **立即替换/删除** |
| `srex.py` | 26 | 给公开端调用复制内核的编译 SREX。 | **拿来 + 极薄包装**（文件:1-7） | 已直接用 `K/crossover/selective_route_exchange.py:13-78`。 | 可直接从调用点导入内核，连这 26 行也可删；或保留来源清晰的薄门面。 | 风险很低；影响⑧。 | 保留薄门面或直接内联 |
| `stopping.py` | 21 | 按迭代数停止。 | 自造重复件（文件:1-12） | `K/stop/MaxIterations.py:1-16` 同职责。 | 直接换导入；若调用需要 `ProblemHGSSearchState`，写极薄参数提取器。 | 很低；影响所有运行入口但不改算法语义。 | **立即替换** |
| `vidal_compound.py` | 535 | 联合尝试客户、车场、有限车辆槽、车型和路线旋转。 | 文献思想的自造扩展（文件:1-8） | 跨场 `K/cpp/search/DepotSplit.cpp:33-139`；普通邻域 `K/search/__init__.py:5-37`；最佳旋转 `K/_setp_hgs_kernel.pyi:321-325`。 | 拆成内核 DepotSplit/旋转/车型邻域；有限槽只留映射。 | 现行公开 clean-ruler 显式开它，直接删会改变⑧结果；需先用内核等职责替换而非空删。 | 高，排在公开外循环之后 |

## B. 跨目录直接/同职责算法模块

以下不是被动数据加载器或受保护真值文件，而是 Problem-HGS 直接调用、间接共享，或与其形成重复实现的算法模块。受保护的 `cost.py`、`check.py`、`search/evaluation.py` 是真值边界，不列为“待替换自造算法”。

| 模块 | 行数 | 职责 | 自造/拿来 | 现成替代（文件:行号或“未检索到”） | 替换代价 | 风险 | 建议优先级 |
|---|---:|---|---|---|---|---|---|
| `charge_timing.py` | 738 | 在允许窗口内按 earliest/价格/碳/混合目标选择充电开始时刻。 | 自造项目策略 | 通用碳择时参考 `third_party/harvested_materials/05_time_varying/carbon_aware_computing/upstream/README.md:7-15,34-45`；frvcpy 只优化时长 `F/solver.py:86-96`。同一 EV 电价+碳职责未检索到。 | 可复用通用时间窗择时算法，但仍需项目电价、碳价和站点窗口薄适配。 | 全换成 frvcpy 会丢时变碳目标；直接影响①（图3/图5），连带②④⑥。 | 必须保留最小策略；算法核可外包 |
| `search/multitrip_schedule.py` | 2,592 | 给实体车分配多趟、排双班次、串跨趟 SOC/充电并出可验证证书。 | 自造项目调度器 | 内核支持 reload/multi-trip：`K/Model.py:347-435`、`K/cpp/search/RelocateWithDepot.h:9-20,41-63`、`K/_setp_hgs_kernel.pyi:277-303`；同一“实体车+双班次+跨趟 SOC+充电窗”实现未检索到。 | 把路线/趟次和回库邻域交内核；保留物理车排程、SOC 和证书薄层。 | 这是④的核心语义；全删会让多趟退化为匿名路线，影响①②④⑥。 | 必须保留薄证书层，大幅减薄 |
| `search/dynamic_multitrip_schedule.py` | 1,721 | 在动态触发点切证书、继承实体车状态、重排未来充电并验证锁。 | 自造项目调度器 | dvrpsim 事件/车辆/订单 `D/dvrpsim/upstream/src/dvrpsim/model.py:18-56,147-169`；EURO epoch 环境 `D/euro_neurips_2022_code_only/upstream/environment.py:62-75,96-149`。跨趟 SOC/锁未检索到。 | 外包事件推进和 epoch 协议；保留切点资产状态、SOC/锁适配。 | 时间基准或锁语义错一处就泄露未来/重排已执行任务；影响⑥和④。 | 必须保留薄适配 |
| `search/charging.py` | 999 | 旧共享 EV 固定路线插站、充电量和择时修复。 | 自造 | `F/solver.py:33-96,150-167`；非线性曲线 `F/core.py:362-400,543-590`。 | 用 frvcpy 替充电搜索；项目策略统一转到一个适配器。 | 与 ALNS 版重复但细节可能漂移；贸然删要先确认全部调用点。影响①②④⑥。 | 立即合并/替换 |
| `algorithms/resetp_alns/support/charging.py` | 1,846 | 当前共享的 EV 充电候选、缓存、插站、充量、择时与重放。 | 自造大实现 | `F/solver.py:33-96,150-167` 和 `F/algorithm.py:20-85,559-590`；当前 `frvcpy_adapter.py` 已能原样调用。 | frvcpy 负责固定路线插站/充量；只留缓存、项目时变目标与完整终审。 | 现有模块还承载项目候选枚举和缓存；一次性全删风险高。影响①②④⑥。 | 高：作为充电去重主战场 |
| `charging_action.py` | 81 | 构造带曲线元数据的项目 ChargingAction。 | 自造胶水 | frvcpy 输出 `(node_id, charge_amt)`：`F/solver.py:90-96`；没有项目动作 schema。 | 保留一个很薄的结果翻译器即可。 | 删除会丢曲线/来源元数据，影响①④⑥和⑤。 | 保留薄层 |
| `charging_curve.py` | 750 | 实现分段非线性充电曲线、正反变换、链式能量和择时计算。 | 自造数学核 | frvcpy 已实现 PWL 曲线结构/斜率/充电时长：`F/core.py:362-400,543-590`。 | 让 frvcpy 作为唯一曲线数学核；适配单位、曲线 ID、哈希和项目动作元数据。 | 数值舍入、单位和边界点可能改变既有真值；影响①②④⑥。 | 高，但需数值等价核对 |
| `solution.py` | 87 | 定义项目 Route、ChargingAction、CrossSiteService、Solution 数据对象。 | 自造数据契约 | 内核 Route/Trip/Solution：`K/_setp_hgs_kernel.pyi:277-336`，但没有项目充电动作和跨场服务账。 | 普通路线/趟次可换内核对象；充电/跨场保留 sidecar。 | 全换会丢成本与协同所需字段；影响①②③④⑤⑥⑦。 | 保留最小 sidecar |
| `china81_completion.py` | 858 | 把路线骨架补成 China81 完整实体车/多趟/充电方案并做精确评分。 | 自造项目适配 | 内核 Route/Trip/reload `K/_setp_hgs_kernel.pyi:277-336`、`K/Model.py:347-435`；同一 China81 完成器未检索到。 | 用内核承载普通路线；保留 China81 场站/车队/充电/成本的翻译和终审。 | 这是统一私有算例桥，误删会影响①②③④⑤⑥。 | 必须保留薄层 |
| `profit.py` | 288 | 从完整路线成本/跨场服务计算各车场利润分项。 | 自造项目核算 | `C/Shapley.py:30-50` 与 `C/Nucleolus.py:58-99` 可替分配算法；它们不生成路线利润或联盟成本，来源边界见 `.../pycoopgame/ORIGIN.md:3-8`。 | 利润事实表仍由项目生成；Shapley/核仁数值交 pyCoopGame。 | 把核算和分配混换会失去个体理性基线；影响③⑦及⑤。 | 保留核算薄层；立即外包分配算法 |

## 必须自造的短名单

这里的“必须自造”不是允许继续堆算法，而是指**必须存在一层本项目自己的语义翻译**。本轮未检索到可直接替代的一体开源实现。

1. **完整真值桥**：`evaluation.py` 的“Duty→受保护 checker/cost/profit→完整结果”最小适配。开源 HGS 不知道本项目八项成本、服务量红线、协同利润和动态锁。
2. **实体车身份与动态锁 sidecar**：`model.py`、`fleet_registry.py`、`dynamic.py` 的最小映射。PyVRP 有车型数量、shift、reload 和 Trip，但没有本项目跨 epoch 的实体车 ID、已执行锁和完整充电历史。
3. **跨趟 SOC/双班次/充电窗证书层**：`search/multitrip_schedule.py` 与 `search/dynamic_multitrip_schedule.py` 的最小证书和验证适配。PyVRP reload 解决路线中的回库/补货，不直接解决本项目跨趟电池连续性和动态锁。
4. **时变电价+碳强度的充电目标适配**：`charge_timing.py` 应缩成薄目标函数与时间窗翻译。frvcpy 能做固定路线最短时间充电，不能直接代替本文电费+碳目标。
5. **China81 输入/输出完成器**：`c0_witness_adapter.py`、`china81_completion.py` 只保留数据格式、场站/实体车映射和终审，不再自行拥有种群、局搜或充电算法。

`DECISION`：`contracts.py`、`runner.py`、`proposals.py` 不属于“科研上必须自造”；它们只是工程胶水，应以开源内核的回调/结果类型为中心压到够用。

## 应当立即替换或清退的短名单

按“已有成熟同职责实现、收益大、项目语义风险相对可控”排序：

1. **`population.py` 的剩余自造罚分/池/参数与 `runner.py` 的退役外循环** → `ExternalPopulation`、`PenaltyManager`、`IntegratedGeneticAlgorithm`。这是已发生真实缺陷、且当前主路径已经半换成功的一组，继续统一风险最低。
2. **`public.py` / `public_search.py` 的自造 HGS 外循环** → 复制内核 `GeneticAlgorithm`/`HGSControl`；保留公开输入输出。能一次砍掉大段重复控制流。
3. **`stopping.py`** → 内核 `MaxIterations`；**`srex.py`** 可直接导入内核；这是最直接的零语义替换。
4. **`sisr.py`** → 人类开源 SISR 或内核 `sisr_repair`；当前自造版还缺原 SISR 接受规则，不应继续以 SISR 名义自养。
5. **`operators.py`、`education.py`、`repair.py` 的标准路线动作** → 内核 LocalSearch/Exchange/Swap/RelocateWithDepot/repair；仅保留换型、锁、充电择时等项目特有回调。
6. **`dcrex.py`、`crossover_control.py`** → 用已有 SREX 承担交叉职责；作者未公开 DCREX 源码，继续维护本地重建不符合“要别人造的”。
7. **`bi_objective_population.py` 的 NSGA-II 骨架** → pymoo；保留完整 Duty 评价接口，不再手写非支配排序和拥挤度。
8. **两份自造充电搜索与 `charging_curve.py` 数学核** → frvcpy；只保留项目时变目标、跨趟 SOC、锁、缓存和完整终审。这里收益很大，但数值/单位风险高于前七项，不能无适配硬替。
9. **`feedback.py`、`schedule_capture.py`、默认关闭的 `schedule_oracle.py`、主路径未调用的 `independent.py`** → 移出活跃算法包；它们不是当前八行正式结果的运行必需，不需要为了“替换”再造新代码。

## 砍掉后的八行影响总览

上面每一件已在“风险”栏逐件写明影响；这里再按总表收口，避免只见模块不见论文：

- **①时变碳（图3/图5）**：真正不能硬删的是完整评价、充电时机目标、跨趟 SOC；种群、HGS 循环、通用邻域、NSGA-II 都可换成熟实现。
- **②混合车队（图5/5.2）**：必须保留车型/实体车 sidecar 与整 Duty 换型语义；标准路线搜索、种群、罚分应外包。
- **③多企业协同**：保留跨场成本/服务事实桥；跨场路线邻域用内核 DepotSplit，分配数值用 pyCoopGame。
- **④实体车多趟**：PyVRP 的 Trip/reload/RelocateWithDepot 可替大量路线级自造代码；跨趟 SOC、双班次和实体车身份仍需薄证书层。
- **⑤成本/参数/算例表**：算法可换，受保护成本真值和最小结果/来源 schema 不能丢；诊断流水不必留在活跃算法包。
- **⑥动态需求5.3**：事件生命周期和 dispatch baseline 可用 dvrpsim/EURO 开源；未来 Duty、资产继承、SOC 和执行锁必须保留适配。
- **⑦公平分配表**：联盟路线成本/独立外部选项仍要由项目路由结果生成；Shapley/核仁计算直接交 pyCoopGame。
- **⑧公开对比表**：应最彻底回到复制 HGS 内核；自造 DCREX/SISR/外循环/跨场 Python 扫描不再承担“公开强度”叙事。

## 我认为接下来该干什么

`DECISION`：下一件应当是一个边界很窄的“**HGS 骨架归一**”施工任务：先把 `population.py` 的剩余自造池/罚分接口、`runner.py` 的退役外循环、`public.py/public_search.py` 的重复 HGS 控制流和 `stopping.py` 统一到 `setp_hgs_kernel`；保留 `IntegratedProblemAdapter`、完整评价桥和实体车 sidecar，不碰受保护三文件。

理由：这一步使用的是仓库里已经复制、已经被当前私有主路径调用的成熟 HGS，不需要先发明新模型；它同时清掉已知罚分缺陷来源和两套外循环，收益最大，而且不要求先改实体车多趟、SOC、充电窗这些高风险特殊语义。完成这一个替换后，再单独处理“通用邻域/修复”和“frvcpy 统一充电核”，不要把三件事揉成一次大改。

本报告是提案，不是施工授权；具体砍哪些模块、是否保留历史兼容入口，仍由用户拍板。

## 本轮边界核对

- 源码改动：0。
- 求解器/实验/测试：0。
- 本任务新增文件：仅本报告。
- 受保护文件未修改；当前哈希：`cost.py` = `13ae664bae0e9c8b5033780fbbc43cedcd43c626ac1eb23023a4a667bd2d1bbd`，`check.py` = `1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072`，`search/evaluation.py` = `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3`。

SELFBUILT_END
