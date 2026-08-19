结论先说：**上游初始化路径找到了，所以现在不能以“找不到”为由退回 A。** 但当前私有路径并不是纯 B：它给每个初始解重新播种，还在入群前做了局部搜索。更大的问题是，上游随机顺序与 AM/PM 班次合同天然冲突；因此 B 必须先按 P105 做一次真实小探针，静态取证还不能宣布成功。

以下可直接作为蓝图增补节。

## A. 现状取证

1. **上游原生初始化**

   - 冻结身份是 PyVRP 0.12.2、tag commit `ea0c421…`：[ORIGIN.md:3](</Volumes/移动硬盘（512G）/ReSETP/third_party/harvested_operators/pyvrp_v0.12.2/ORIGIN.md:3>)。
   - `solve(data, stop, seed=0, ...)` 只创建一条随机数流，然后连续生成 `min_pop_size` 个 `Solution.make_random(data, rng)`；默认 `min_pop_size=25`：[solve.py:138](</Volumes/移动硬盘（512G）/ReSETP/build/python_envs/pyvrp-frozen-0.12.2-clean/lib/python3.13/site-packages/pyvrp/solve.py:138>)、`_pyvrp.pyi:360-378`。
   - 随机解会：
     1. 收入全部必服务客户；
     2. 打乱客户；
     3. 按可用车辆数均匀切成路线；
     4. 异构车队时再打乱车型槽位。  
     证据：[Solution.cpp:166](</Volumes/移动硬盘（512G）/ReSETP/build/python_envs/pyvrp-frozen-0.12.2-clean/lib/python3.13/site-packages/pyvrp/cpp/Solution.cpp:166>)。
   - 项目建模时没有覆盖 `required`，而 `Model.add_client()` 默认 `required=True`，所以这些企业客户天然全覆盖：[Model.py:207](</Volumes/移动硬盘（512G）/ReSETP/build/python_envs/pyvrp-frozen-0.12.2-clean/lib/python3.13/site-packages/pyvrp/Model.py:207>)、`kernel_proposals.py:895-903`。
   - 初始解不先修复、不先局部搜索，直接加入种群；可行解和不可行解分别进入两个子种群。概率修复只发生在后续子代：[GeneticAlgorithm.py:171](</Volumes/移动硬盘（512G）/ReSETP/build/python_envs/pyvrp-frozen-0.12.2-clean/lib/python3.13/site-packages/pyvrp/GeneticAlgorithm.py:171>)、[Population.py:75](</Volumes/移动硬盘（512G）/ReSETP/build/python_envs/pyvrp-frozen-0.12.2-clean/lib/python3.13/site-packages/pyvrp/Population.py:75>)。

2. **复制内核**

   复制内核的 `Solution.cpp` 与冻结版在这段初始化上的差异只有命名空间改名，随机构造正文一致；复制版 `solve.py:187-190` 也仍是同一条随机流生成整批初始解。

3. **当前私有初始化不是纯上游语义**

   当前 `kernel_proposals.py:584-619 random_skeleton_move()` 已调用复制内核的 `make_random`，但有两处偏差：

   - 每个成员重新创建 `RandomNumberGenerator(seed+n)`，不是上游共享的一条 RNG 流；
   - `truth_guided_route_boundary` 未开时，会在 `:602-606` 先跑完整局部搜索再解码。

   当前 `initialization.py:609-869 build_initial_population()` 还会：

   - 把输入 `initial` 本身作为第一个成员；
   - F1 下从封存见证出发并先做见证扰动；
   - 再以“随机骨架＋局部搜索”作后备。

4. **三件自写初始化的真实使用位置**

   | 用途 | 当前真实血统 |
   |---|---|
   | F1 | 每次运行读取 `health_witness_routes.csv`；见证离线由 `build_edf_route_plans → plans_to_solution → minimum_edf_order_chains` 生成。运行时不是现场调用，但血统仍在。 |
   | F2 单干 | 旧蓝图 `W1.3a C.8` 原计划现场调用 EDF、链覆盖和 `complete_china81_route_skeleton`；P105 后该段整体作废。 |
   | F5 | 对三件精确调用为零，不受 K7 影响。 |

   `plans_to_solution()` 内部会调用 `minimum_edf_order_chains()`，所以不能以“没直接写函数名”为由继续使用。证据：`build_china81_suite_rebuild_20260812.py:1369-1413`、蓝图 `:1100-1106,1171-1176`。

## B. 可直接复用的积木

| 积木 | 用法 | 状态 |
|---|---|---|
| `Solution.make_random(data, rng)` | 上游原生路线级随机解 | 直接复用 |
| `_build_unique_asset_problem()` | 每个实体车槽位建一个 `num_available=1` 的内核车型 | 零改动，`kernel_proposals.py:773-1051` |
| `decode_replacements()` / `_decode_changes()` | 按内核 `vehicle_type` 精确映回实体车辆 | 零改动，`:441-450,739-770` |
| `_split_replacement_trips_by_shift()` | 保留客户顺序，只在班次边界切趟 | 零改动，`:679-710` |
| `DutySkeletonMove.apply()` | 把空参考中的 `unserved_customers` 转为已服务客户 | 零改动，[operators.py:356](</Volumes/移动硬盘（512G）/ReSETP/solver/src/setp_solver/algorithms/problem_hgs/operators.py:356>) |
| `register_all_vehicle_slots()` | 给空参考登记完整 CV/EV 实体槽位 | 零改动，[fleet_registry.py:12](</Volumes/移动硬盘（512G）/ReSETP/solver/src/setp_solver/algorithms/problem_hgs/fleet_registry.py:12>) |
| `repair_changed_duties_outcome()` | 现役排程与充电补全 | 零改动，[charging.py:744](</Volumes/移动硬盘（512G）/ReSETP/solver/src/setp_solver/algorithms/problem_hgs/charging.py:744>) |
| `DutyFullEvaluator.evaluate()` | 完整成本、完整可行性、服务量评价 | 零改动，[evaluation.py:510](</Volumes/移动硬盘（512G）/ReSETP/solver/src/setp_solver/algorithms/problem_hgs/evaluation.py:510>) |
| `IntegratedGeneticAlgorithm`＋`ExternalPopulation` | 完整评价后分可行/不可行池入群 | 零改动，`IntegratedGeneticAlgorithm.py:114-135`、`ExternalPopulation.py:76-107` |

B 路不应调用 `hybrid_decoder` 重新切路线；那会丢掉上游生成的路线边界。更不能调用已停用的 EDF、链覆盖或 China81 completion。

## C. B 路拼装步骤

1. **替换 W1.3a C.8**

   删除旧蓝图 `:1171-1176` 的 EDF/chain/completion 调用。`EnterpriseSeedInput` 若只为三件自写件服务，也不再需要。

2. **建立空的单企业参考个体**

   在企业切片完成后构造：

   ```python
   DutyIndividual(
       duties=(),
       unserved_customers=enterprise_slice.customer_ids,
       source=f"native-init-reference/{enterprise_slice.source_id}",
   )
   ```

   然后调用：

   ```python
   register_all_vehicle_slots(reference, enterprise_slice.bundle)
   ```

   它只登记该企业冻结的 3+3 或 7+7 车辆槽位，不生成路线。

3. **使用一条共享随机流**

   `IndependentKernelDutyRouteProposalEngine(..., random_seed=args.seed)` 已在 `kernel_proposals.py:156-163` 拥有 `self._rng`。应把 `random_skeleton_move()` 改为：

   - 使用 `self._rng`；
   - 每次只调用一次 `make_random(self._data, self._rng)`；
   - 直接解码，不调用 `_local_search`；
   - 参数用 `draw_index` 仅记录第几个初始成员，不再以它重新播种。

4. **调整初始种群编排，不新增算法**

   `build_initial_population()` 建议把“参考个体”和“候选成员”分开。B 调用参数应为：

   ```text
   include_reference_candidate=False
   witness_seed=None
   max_random_attempts=requested_size
   require_complete_feasible=False
   mechanism_enabled=None
   fleet_activation_enabled=True
   ```

   含义是：严格生成上游规定数量的原生随机解，不因结果不好继续抽更多随机解；空参考不得进入种群；初始不可行解只要能完成 Duty 物化和完整评价，就按上游语义进入不可行池。

5. **每个原生路线解依次经过现役链**

   ```text
   make_random
   → decode_replacements
   → DutySkeletonMove.apply
   → 班次边界切趟
   → repair_changed_duties_outcome
   → DutyFullEvaluator.evaluate
   → ExternalPopulation.add
   ```

   其中只有最前面的上游调用和编排需要改动；Duty 补全、充电、完整评价、罚分种群均零改动。

6. **修正探针验收器**

   当前 runner `:3732-3779` 强制要求“第一个 initial_evaluation 可行”。这与上游允许初始不可行解直接入池冲突。B 下应检查最终探针解是否可行、满服务；不得因为列表第一个随机解不可行就误报 B 失败。

## D. 缺口与最大风险

**FACT：上游路径存在，不触发 `HALT_NO_UPSTREAM_PATH`。**

真正风险是随机客户顺序不能被现役同日 AM/PM Duty 时钟物化：

- ENT_A：10 个 AM、15 个 PM，6 台车使原生初始化切成 5 条、每条 5 客户。
- ENT_B：7 个 AM、18 个 PM，14 台车切成 12 条 2 客户＋1 条 1 客户。
- F1 联合：17 个 AM、33 个 PM，20 台车切成 16 条 3 客户＋1 条 2 客户。

现役补全只按连续班次切趟，不重排客户。如果某台车出现“PM 后又回 AM”，同日物理顺序无法闭合。

只计算这一项必要条件，不算容量、时间窗、能量和充电，25 个原生随机解中至少有一个班次顺序可物化的概率上界约为：

| 对象 | 25 个原生解至少一个通过班次顺序必要条件 |
|---|---:|
| ENT_A | 0.50% |
| ENT_B | 72.7% |
| F1 联合见证 | 0.062% |

这是根据 `orders.csv:5807-5856`、企业映射、`fleet_caps.csv:174-175` 和上游切路公式复算的数学上界，不是求解器实验。其余约束只会继续降低成功率。

因此：

- `HALT_B_NATIVE_MATERIALIZATION`：25 个原生解均无法走完现役 Duty 补全与完整评价；
- `HALT_B_SERVICE_LOSS`：任一客户或需求量丢失；
- `HALT_B_NO_FEASIBLE_RESULT`：规定的一种子探针最终仍有违规。

这三种都有资格作为 P105 的实际退回证据。不能通过排序班次、增加抽样、调用 hybrid decoder 或恢复预局部搜索来“救 B”，因为那会变成另一套初始化算法。

“明显劣化”当前仍是 `UNKNOWN`：一种子接线探针不能给它下性能结论，也没有用户批准的数值阈值。

## E. 最小探针

W0 收工后只跑两次探索：

```bash
for enterprise in ENT_A ENT_B; do
  OUT="solver/reports/enterprise_native_init_probe/${enterprise}"
  PYTHONPATH=solver/src:models/src:third_party/setp_hgs_kernel \
    build/python_envs/setp-independent-hgs/bin/python \
    solver/scripts/run_problem_hgs_private_technical.py "$OUT" \
    --instance-id cn-jjj-50c-01-DEPOTSEARCH-d996f755bd \
    --enterprise-id "$enterprise" \
    --seed 1 \
    --iterations 1 \
    --stagnation-patience 1 \
    --max-runtime-seconds 60
done
```

硬判据只用用户已定的四项：

- 最终完整评价 `feasible=true`；
- 违规数为 0；
- ENT_A 为 `25/25` 客户、`6597/6597 kg`；
- ENT_B 为 `25/25` 客户、`6667/6667 kg`。

另保存四项血统诊断，但不把它们另造为科学门槛：

- 只创建一条初始化 RNG 流；
- 原生 `make_random` 调用数；
- 入群前局部搜索调用数必须为 0；
- 三件自写初始化函数调用数必须为 0。

失败后保留全部原始拒绝原因，按具体用途退回 A；不加种子、不加抽样次数、不改班次、不调参数救结果。

## F. F1 见证、机时与退回披露

1. **B 若通过**

   不再运行 `build_china81_suite_rebuild_20260812.py`；它的 `build_witness()` 在 `:1416-1430` 仍直接进入 EDF 链，而且 `main()` 会重建 81 例。

   应继续使用 `run_problem_hgs_private_technical.py`，在初始种群完成后：

   - 从上游抽取顺序中取**第一个**完整可行、0 违规、50/50、13264/13264 kg 的初始成员，不按成本挑最好；
   - 用其 `FullEvaluation.prepared_solution` 和 `certificate` 导出新的 `health_witness_routes.csv`；
   - 先写新报告目录，验证后再切 loader，不覆盖旧见证；
   - 反向导出可放进 W0 已出现的 `c0_witness_adapter.py`，它只是格式适配，不拥有路线算法。

2. **机时代价**

   - 已知工作量：1 个 M1、1 个 joint seed、只生成一次原生初始种群。
   - 建议沿用 60 秒探索上限，因此本次见证探针的计划上限是 **0.0167 M1 机时**。
   - 实际代价按 runner 已有 `initialization_wall_seconds / 3600` 记。
   - 旧路径曾有 420 秒＝0.117 机时的初始化记录，但那一轮包含“每个随机骨架先跑局部搜索”，不能冒充 B 的机时估计。
   - 如果 60 秒内没有第一个合格的原生初始成员，应报实际拒绝结构；是否属于“代价失衡”不能由代理另造比例阈值。S5 冻结后可同时报告“重建机时／正式单跑机时”，再按 P105 处理。

3. **退回 A 时的披露句**

   > 私有算例的初始可行解采用项目内的 EDF 路线构造、最小链覆盖和有限车队充电补全。我们曾优先接入 PyVRP 0.12.2 的原生随机初始化，但预注册的 seed-1 探针在【具体对象】出现【完整违规／服务缺口／实测机时】；因此按事前约定仅在初始化环节退回项目实现。三件项目初始化不作为算法贡献；种群、罚分、重启和后续局部搜索仍采用复制的 PyVRP 0.12.2 HGS 语义。

   方括号必须填实际结果；不能预写“代价失衡”。

4. **施工量估计**

   生产代码约 `+80～110/−35～55`：主要是共享 RNG 原生抽取、空参考不入群、F1 见证反向导出和删除旧 EDF 接线；测试约 `+90～120`。W0 正在并行改这些文件，落地前应按其最终 diff 重算，不按本轮行号机械套补丁。

直接说我的判断：**B“能接上”有九成以上把握；B 按现有完整 Duty 链同时通过 ENT_A、ENT_B 和 F1 见证，我只给低个位数成算。** 最大风险不是服务量，也不是找不到 API，而是上游允许不可行随机解进罚分池，而我们的 Duty 层必须先把固定实体车、趟序和充电时钟物化；ENT_A 与联合见证的随机班次顺序几乎总会先撞墙。

所以正确动作仍是：先按 P105 原样试 B；我预计最可能由 ENT_A 或 F1 给出一份真实、可复核的退回 A 证据。本轮只读，未写文件、未跑求解器。


