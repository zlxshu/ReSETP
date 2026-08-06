# SEEDPROBE 诊断记录

## 运行内容

固定算例 `cn-cy-100c-01-V2-LOCATIONS`、电动车占比档位 25，分别使用 100、1000、25000 次迭代和种子 1、2，共运行 6 个单元。每个单元沿 `_configure_fleet()` 与 `fleet_worker()` 的现有调用路径执行；下列目标值、路线、充电、车辆和完整候选评价次数均取 `COST_PLUS_CARBON` 搜索侧。

## 单元记录

### 100 次，seed 1

status=`PASS`；objective_float_hex=`0x1.1d2064a7ab27dp+12`；total_cost_cny=`4562.024573963715`；route_structure_sha256=`16259adedecdf47b932ddb581e3437b14d8d8941426623e56ce1c88026755bb5`；charging_structure_sha256=`4486a90585abede9353f08a410ffa5b2187e623205ee280ff158ed695d44e4bc`。

dispatched_cv=8；dispatched_ev=4；used_physical_vehicles=12；route_count=18；complete_candidate_evaluation_attempts=80；hgs_iterations_by_view=`{"cv_only":100,"mechanism_ev":100,"naive_ev":100}`；stop_reasons_by_view=`{"cv_only":"MAX_ITERATIONS","mechanism_ev":"MAX_ITERATIONS","naive_ev":"MAX_ITERATIONS"}`；elapsed_seconds=35.79464095807634。

failure_reason：空

### 100 次，seed 2

status=`PASS`；objective_float_hex=`0x1.1d2064a7ab27dp+12`；total_cost_cny=`4562.024573963715`；route_structure_sha256=`16259adedecdf47b932ddb581e3437b14d8d8941426623e56ce1c88026755bb5`；charging_structure_sha256=`4486a90585abede9353f08a410ffa5b2187e623205ee280ff158ed695d44e4bc`。

dispatched_cv=8；dispatched_ev=4；used_physical_vehicles=12；route_count=18；complete_candidate_evaluation_attempts=80；hgs_iterations_by_view=`{"cv_only":100,"mechanism_ev":100,"naive_ev":100}`；stop_reasons_by_view=`{"cv_only":"MAX_ITERATIONS","mechanism_ev":"MAX_ITERATIONS","naive_ev":"MAX_ITERATIONS"}`；elapsed_seconds=35.78896058292594。

failure_reason：空

### 1000 次，seed 1

status=`PASS`；objective_float_hex=`0x1.1d2064a7ab27dp+12`；total_cost_cny=`4562.024573963715`；route_structure_sha256=`16259adedecdf47b932ddb581e3437b14d8d8941426623e56ce1c88026755bb5`；charging_structure_sha256=`4486a90585abede9353f08a410ffa5b2187e623205ee280ff158ed695d44e4bc`。

dispatched_cv=8；dispatched_ev=4；used_physical_vehicles=12；route_count=18；complete_candidate_evaluation_attempts=80；hgs_iterations_by_view=`{"cv_only":1000,"mechanism_ev":1000,"naive_ev":1000}`；stop_reasons_by_view=`{"cv_only":"MAX_ITERATIONS","mechanism_ev":"MAX_ITERATIONS","naive_ev":"MAX_ITERATIONS"}`；elapsed_seconds=68.85467154101934。

failure_reason：空

### 1000 次，seed 2

status=`PASS`；objective_float_hex=`0x1.1d2064a7ab27dp+12`；total_cost_cny=`4562.024573963715`；route_structure_sha256=`16259adedecdf47b932ddb581e3437b14d8d8941426623e56ce1c88026755bb5`；charging_structure_sha256=`4486a90585abede9353f08a410ffa5b2187e623205ee280ff158ed695d44e4bc`。

dispatched_cv=8；dispatched_ev=4；used_physical_vehicles=12；route_count=18；complete_candidate_evaluation_attempts=80；hgs_iterations_by_view=`{"cv_only":1000,"mechanism_ev":1000,"naive_ev":1000}`；stop_reasons_by_view=`{"cv_only":"MAX_ITERATIONS","mechanism_ev":"MAX_ITERATIONS","naive_ev":"MAX_ITERATIONS"}`；elapsed_seconds=69.1789058339782。

failure_reason：空

### 25000 次，seed 1

status=`PASS`；objective_float_hex=`0x1.1d2064a7ab27dp+12`；total_cost_cny=`4562.024573963715`；route_structure_sha256=`16259adedecdf47b932ddb581e3437b14d8d8941426623e56ce1c88026755bb5`；charging_structure_sha256=`4486a90585abede9353f08a410ffa5b2187e623205ee280ff158ed695d44e4bc`。

dispatched_cv=8；dispatched_ev=4；used_physical_vehicles=12；route_count=18；complete_candidate_evaluation_attempts=80；hgs_iterations_by_view=`{"cv_only":25000,"mechanism_ev":25000,"naive_ev":25000}`；stop_reasons_by_view=`{"cv_only":"MAX_ITERATIONS","mechanism_ev":"MAX_ITERATIONS","naive_ev":"MAX_ITERATIONS"}`；elapsed_seconds=857.6363692920422。

failure_reason：空

### 25000 次，seed 2

status=`PASS`；objective_float_hex=`0x1.1d2064a7ab27dp+12`；total_cost_cny=`4562.024573963715`；route_structure_sha256=`16259adedecdf47b932ddb581e3437b14d8d8941426623e56ce1c88026755bb5`；charging_structure_sha256=`4486a90585abede9353f08a410ffa5b2187e623205ee280ff158ed695d44e4bc`。

dispatched_cv=8；dispatched_ev=4；used_physical_vehicles=12；route_count=18；complete_candidate_evaluation_attempts=80；hgs_iterations_by_view=`{"cv_only":25000,"mechanism_ev":25000,"naive_ev":25000}`；stop_reasons_by_view=`{"cv_only":"MAX_ITERATIONS","mechanism_ev":"MAX_ITERATIONS","naive_ev":"MAX_ITERATIONS"}`；elapsed_seconds=861.1145812500035。

failure_reason：空

## 逐预算目标值比对

100 次：seed 1=`0x1.1d2064a7ab27dp+12`；seed 2=`0x1.1d2064a7ab27dp+12`；identical=`true`。

1000 次：seed 1=`0x1.1d2064a7ab27dp+12`；seed 2=`0x1.1d2064a7ab27dp+12`；identical=`true`。

25000 次：seed 1=`0x1.1d2064a7ab27dp+12`；seed 2=`0x1.1d2064a7ab27dp+12`；identical=`true`。

25000 次两个单元逐位复现 4562.024573963715：`true`。

## 静态取证

### Q1

事实：rng 先进入 LocalSearch，同时用于生成随机初始解；随后作为 GeneticAlgorithm 的构造参数保存，并由 algorithm.run 进入 PyVRP HGS。

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/pyvrp_adapter.py:553`

```python
    rng = RandomNumberGenerator(seed=int(seed))
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/pyvrp_adapter.py:555`

```python
    local_search = LocalSearch(data, rng, neighbours)
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/pyvrp_adapter.py:565`

```python
        NativeSolution.make_random(data, rng)
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/pyvrp_adapter.py:573`

```python
    algorithm = GeneticAlgorithm(
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/pyvrp_adapter.py:576`

```python
        rng,
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/pyvrp_adapter.py:583`

```python
    result = algorithm.run(
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/pyvrp_adapter.py:584`

```python
        MaxRuntime(float(runtime_seconds)),
```

### Q2

事实：run_unit 对两个搜索侧分别把 seed 传给 _run_arm；_run_arm 再传给 run_hgs_route_pool_recombination，该函数对三个视角逐一传给 _run_exact_epoch。

`baselines/china_e3_e7/run_formal_fleet_levels_xb_20260802.py:801`

```python
        for arm in ARM_ORDER:
```

`baselines/china_e3_e7/run_formal_fleet_levels_xb_20260802.py:803`

```python
                arms[arm] = _run_arm(
```

`baselines/china_e3_e7/run_formal_fleet_levels_xb_20260802.py:805`

```python
                    int(seed),
```

`baselines/china_e3_e7/run_formal_fleet_levels_xb_20260802.py:530`

```python
        run = route_pool_sp.run_hgs_route_pool_recombination(
```

`baselines/china_e3_e7/run_formal_fleet_levels_xb_20260802.py:533`

```python
            seed=int(seed),
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py:190`

```python
    for mode in modes:
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py:196`

```python
        view_epochs[mode] = _run_exact_epoch(
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py:200`

```python
            seed=int(seed),
```

### Q3

事实：流程先取得 HGS 完整候选中的最低目标值父解，再运行集合划分生成重组候选；返回项由 HGS 父解与可用重组候选按完整目标值取最小。集合划分调用和最终 min 选择均未接收随机数或 seed。

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py:225`

```python
    parent_completion = min(
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py:227`

```python
        key=lambda item: item.objective,
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py:255`

```python
    recombined, sp_stats = _solve_set_partitioning(
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py:279`

```python
    else:
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py:282`

```python
        ] = [("best_exact_hgs_parent", parent_completion)]
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py:290`

```python
        if recombined is not None:
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py:305`

```python
        selected_source, completion = min(
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py:307`

```python
            key=lambda item: item[1].objective,
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py:690`

```python
    result = milp(
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py:698`

```python
        options={"time_limit": float(time_limit_seconds)},
```

### Q4

事实：本次 scout 车队路径没有调用 hybrid.py 的 homogeneous ensemble；它调用 run_unit 后进入 route_pool_sp，并在三个视角上使用同一个外部 seed。hybrid.py 该独立函数若被调用，会先选多个群体中完整目标值最低者，以它启动 ALNS，再在该群体解和 ALNS 解之间取完整目标值最低者。

`baselines/china_e3_e7/scout_three_mechanisms_20260803_runner.py:491`

```python
    return old.run_unit(
```

`baselines/china_e3_e7/scout_three_mechanisms_20260803_runner.py:492`

```python
        level,
```

`baselines/china_e3_e7/scout_three_mechanisms_20260803_runner.py:493`

```python
        seed,
```

`baselines/china_e3_e7/run_formal_fleet_levels_xb_20260802.py:530`

```python
        run = route_pool_sp.run_hgs_route_pool_recombination(
```

`baselines/china_e3_e7/run_formal_fleet_levels_xb_20260802.py:533`

```python
            seed=int(seed),
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py:190`

```python
    for mode in modes:
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py:196`

```python
        view_epochs[mode] = _run_exact_epoch(
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py:200`

```python
            seed=int(seed),
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/hybrid.py:346`

```python
    seeds = tuple(
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/hybrid.py:347`

```python
        int(base_seed) + 1_009 * index
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/hybrid.py:363`

```python
        population_runs = tuple(executor.map(run_population, seeds))
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/hybrid.py:364`

```python
    best_population = min(
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/hybrid.py:368`

```python
    alns = run_project_alns(
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/hybrid.py:375`

```python
    completion = min(
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/hybrid.py:376`

```python
        (best_population.completion, alns.completion),
```
