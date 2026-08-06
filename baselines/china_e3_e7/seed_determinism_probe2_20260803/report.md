# SEEDPROBE2 诊断记录

## 运行内容

固定算例 `cn-cy-100c-01-V2-LOCATIONS`、电动车占比档位 25，迭代预算为 100、1000、25000，种子为 1、2，共执行 6 个单元。每个单元沿第一轮同一 `fleet_worker → run_unit → _run_arm → MV-HGS-SP` 路径运行；下表每行是一个单元与一个视角的组合，共 18 行。完整模型字段读取 `COST_PLUS_CARBON` arm。

## 取得方式

`proxy_best_cost` 与 `proxy_best_is_feasible` 在 PyVRP `GeneticAlgorithm.run()` 返回后，从 `Result.cost()` 和 `result.best.is_feasible()` 打补丁取得。

`proxy_initial_best_cost` 在 `GeneticAlgorithm` 构造时、迭代开始前，对实际 `initial_solutions` 中可行解用零罚 `CostEvaluator` 取最小值；`proxy_improvement` 是该值减最终代理值。

`min_pop_size` 从实际 `Population._params` 打补丁读取；`warm_native_count` 直接读 `HgsExactEpoch.stats.warm_elite_count`；`random_count` 用构造器实际收到的初始解数减热启动数。

`archive_candidate_count` 直接取该视角实际送入 `_route_pool_records` 的 `archive_completions` 数；该集合含归档完成解和共同初始完成解。`exact_elite_count` 直接取 `elite_completions` 数。

`sp_route_pool_size`、`sp_improved_over_parent`、`selected_source` 直接读 `HgsRoutePoolRun.stats`。集合划分由三个视角共同生成，所以同一单元的三行重复记录同一组集合划分字段。

完整模型目标值、成本、结构哈希、派车数、路线数、完整候选评价次数、迭代数、停止原因和用时均直接读第一轮相同返回对象。所有补丁在 worker 上下文退出时还原。

## 代理值与种群构成

| 迭代 | 种子 | 视角 | 状态 | 初始代理值 | 最终代理值 | 可行 | 改进值 | min_pop | warm | random |
|---:|---:|---|---|---|---|---|---|---:|---:|---:|
| 100 | 1 | cv_only | PASS | 0x1.98ef7a0000000p+25 | 0x1.9499700000000p+21 | true | 0x1.7fa5e30000000p+25 | 25 | 0 | 25 |
| 100 | 1 | naive_ev | PASS | 0x1.2cb9750000000p+25 | 0x1.32a8e00000000p+20 | true | 0x1.23242e0000000p+25 | 25 | 0 | 25 |
| 100 | 1 | mechanism_ev | PASS | 0x1.1873f18000000p+25 | 0x1.11be700000000p+20 | true | 0x1.0fe5fe0000000p+25 | 25 | 0 | 25 |
| 100 | 2 | cv_only | PASS | 0x1.7afc880000000p+25 | 0x1.92d2680000000p+21 | true | 0x1.61cf618000000p+25 | 25 | 0 | 25 |
| 100 | 2 | naive_ev | PASS | 0x1.3005a28000000p+25 | 0x1.ad94d00000000p+20 | true | 0x1.2298fc0000000p+25 | 25 | 0 | 25 |
| 100 | 2 | mechanism_ev | PASS | 0x1.1ed3398000000p+25 | 0x1.50ff100000000p+20 | true | 0x1.144b410000000p+25 | 25 | 0 | 25 |
| 1000 | 1 | cv_only | PASS | 0x1.98ef7a0000000p+25 | 0x1.202d300000000p+21 | true | 0x1.86eca70000000p+25 | 25 | 0 | 25 |
| 1000 | 1 | naive_ev | PASS | 0x1.2cb9750000000p+25 | 0x1.2c04200000000p+20 | true | 0x1.2359540000000p+25 | 25 | 0 | 25 |
| 1000 | 1 | mechanism_ev | PASS | 0x1.1873f18000000p+25 | 0x1.0181100000000p+20 | true | 0x1.1067e90000000p+25 | 25 | 0 | 25 |
| 1000 | 2 | cv_only | PASS | 0x1.7afc880000000p+25 | 0x1.1fd0480000000p+21 | true | 0x1.68ff838000000p+25 | 25 | 0 | 25 |
| 1000 | 2 | naive_ev | PASS | 0x1.3005a28000000p+25 | 0x1.2ab1000000000p+20 | true | 0x1.26b01a8000000p+25 | 25 | 0 | 25 |
| 1000 | 2 | mechanism_ev | PASS | 0x1.1ed3398000000p+25 | 0x1.00af500000000p+20 | true | 0x1.16cdbf0000000p+25 | 25 | 0 | 25 |
| 25000 | 1 | cv_only | PASS | 0x1.98ef7a0000000p+25 | 0x1.1eaa200000000p+21 | true | 0x1.8704d80000000p+25 | 25 | 0 | 25 |
| 25000 | 1 | naive_ev | PASS | 0x1.2cb9750000000p+25 | 0x1.2929900000000p+20 | true | 0x1.2370288000000p+25 | 25 | 0 | 25 |
| 25000 | 1 | mechanism_ev | PASS | 0x1.1873f18000000p+25 | 0x1.0030100000000p+20 | true | 0x1.1072710000000p+25 | 25 | 0 | 25 |
| 25000 | 2 | cv_only | PASS | 0x1.7afc880000000p+25 | 0x1.1eaa200000000p+21 | true | 0x1.6911e60000000p+25 | 25 | 0 | 25 |
| 25000 | 2 | naive_ev | PASS | 0x1.3005a28000000p+25 | 0x1.2929900000000p+20 | true | 0x1.26bc560000000p+25 | 25 | 0 | 25 |
| 25000 | 2 | mechanism_ev | PASS | 0x1.1ed3398000000p+25 | 0x1.0030100000000p+20 | true | 0x1.16d1b90000000p+25 | 25 | 0 | 25 |

## 路线池与集合划分

| 迭代 | 种子 | 视角 | 归档候选数 | 精英数 | SP 路线数 | 严格优于父解 | 入选来源 |
|---:|---:|---|---:|---:|---:|---|---|
| 100 | 1 | cv_only | 1 | 1 | 18 | false | best_exact_hgs_parent |
| 100 | 1 | naive_ev | 1 | 1 | 18 | false | best_exact_hgs_parent |
| 100 | 1 | mechanism_ev | 1 | 1 | 18 | false | best_exact_hgs_parent |
| 100 | 2 | cv_only | 1 | 1 | 18 | false | best_exact_hgs_parent |
| 100 | 2 | naive_ev | 1 | 1 | 18 | false | best_exact_hgs_parent |
| 100 | 2 | mechanism_ev | 1 | 1 | 18 | false | best_exact_hgs_parent |
| 1000 | 1 | cv_only | 1 | 1 | 18 | false | best_exact_hgs_parent |
| 1000 | 1 | naive_ev | 1 | 1 | 18 | false | best_exact_hgs_parent |
| 1000 | 1 | mechanism_ev | 1 | 1 | 18 | false | best_exact_hgs_parent |
| 1000 | 2 | cv_only | 1 | 1 | 18 | false | best_exact_hgs_parent |
| 1000 | 2 | naive_ev | 1 | 1 | 18 | false | best_exact_hgs_parent |
| 1000 | 2 | mechanism_ev | 1 | 1 | 18 | false | best_exact_hgs_parent |
| 25000 | 1 | cv_only | 1 | 1 | 18 | false | best_exact_hgs_parent |
| 25000 | 1 | naive_ev | 1 | 1 | 18 | false | best_exact_hgs_parent |
| 25000 | 1 | mechanism_ev | 1 | 1 | 18 | false | best_exact_hgs_parent |
| 25000 | 2 | cv_only | 1 | 1 | 18 | false | best_exact_hgs_parent |
| 25000 | 2 | naive_ev | 1 | 1 | 18 | false | best_exact_hgs_parent |
| 25000 | 2 | mechanism_ev | 1 | 1 | 18 | false | best_exact_hgs_parent |

## 完整模型交叉记录

| 迭代 | 种子 | 视角 | 目标值 hex | 总成本 | 路线 SHA-256 | 充电 SHA-256 | CV | EV | 路线数 | 完整评价次数 | 三视角迭代数 | 三视角停止原因 | 用时秒 |
|---:|---:|---|---|---:|---|---|---:|---:|---:|---:|---|---|---:|
| 100 | 1 | cv_only | 0x1.1d2064a7ab27dp+12 | 4562.024573963715 | 16259adedecdf47b932ddb581e3437b14d8d8941426623e56ce1c88026755bb5 | 4486a90585abede9353f08a410ffa5b2187e623205ee280ff158ed695d44e4bc | 8 | 4 | 18 | 80 | {"cv_only":100,"mechanism_ev":100,"naive_ev":100} | {"cv_only":"MAX_ITERATIONS","mechanism_ev":"MAX_ITERATIONS","naive_ev":"MAX_ITERATIONS"} | 26.486992916907184 |
| 100 | 1 | naive_ev | 0x1.1d2064a7ab27dp+12 | 4562.024573963715 | 16259adedecdf47b932ddb581e3437b14d8d8941426623e56ce1c88026755bb5 | 4486a90585abede9353f08a410ffa5b2187e623205ee280ff158ed695d44e4bc | 8 | 4 | 18 | 80 | {"cv_only":100,"mechanism_ev":100,"naive_ev":100} | {"cv_only":"MAX_ITERATIONS","mechanism_ev":"MAX_ITERATIONS","naive_ev":"MAX_ITERATIONS"} | 26.486992916907184 |
| 100 | 1 | mechanism_ev | 0x1.1d2064a7ab27dp+12 | 4562.024573963715 | 16259adedecdf47b932ddb581e3437b14d8d8941426623e56ce1c88026755bb5 | 4486a90585abede9353f08a410ffa5b2187e623205ee280ff158ed695d44e4bc | 8 | 4 | 18 | 80 | {"cv_only":100,"mechanism_ev":100,"naive_ev":100} | {"cv_only":"MAX_ITERATIONS","mechanism_ev":"MAX_ITERATIONS","naive_ev":"MAX_ITERATIONS"} | 26.486992916907184 |
| 100 | 2 | cv_only | 0x1.1d2064a7ab27dp+12 | 4562.024573963715 | 16259adedecdf47b932ddb581e3437b14d8d8941426623e56ce1c88026755bb5 | 4486a90585abede9353f08a410ffa5b2187e623205ee280ff158ed695d44e4bc | 8 | 4 | 18 | 80 | {"cv_only":100,"mechanism_ev":100,"naive_ev":100} | {"cv_only":"MAX_ITERATIONS","mechanism_ev":"MAX_ITERATIONS","naive_ev":"MAX_ITERATIONS"} | 26.487608541036025 |
| 100 | 2 | naive_ev | 0x1.1d2064a7ab27dp+12 | 4562.024573963715 | 16259adedecdf47b932ddb581e3437b14d8d8941426623e56ce1c88026755bb5 | 4486a90585abede9353f08a410ffa5b2187e623205ee280ff158ed695d44e4bc | 8 | 4 | 18 | 80 | {"cv_only":100,"mechanism_ev":100,"naive_ev":100} | {"cv_only":"MAX_ITERATIONS","mechanism_ev":"MAX_ITERATIONS","naive_ev":"MAX_ITERATIONS"} | 26.487608541036025 |
| 100 | 2 | mechanism_ev | 0x1.1d2064a7ab27dp+12 | 4562.024573963715 | 16259adedecdf47b932ddb581e3437b14d8d8941426623e56ce1c88026755bb5 | 4486a90585abede9353f08a410ffa5b2187e623205ee280ff158ed695d44e4bc | 8 | 4 | 18 | 80 | {"cv_only":100,"mechanism_ev":100,"naive_ev":100} | {"cv_only":"MAX_ITERATIONS","mechanism_ev":"MAX_ITERATIONS","naive_ev":"MAX_ITERATIONS"} | 26.487608541036025 |
| 1000 | 1 | cv_only | 0x1.1d2064a7ab27dp+12 | 4562.024573963715 | 16259adedecdf47b932ddb581e3437b14d8d8941426623e56ce1c88026755bb5 | 4486a90585abede9353f08a410ffa5b2187e623205ee280ff158ed695d44e4bc | 8 | 4 | 18 | 80 | {"cv_only":1000,"mechanism_ev":1000,"naive_ev":1000} | {"cv_only":"MAX_ITERATIONS","mechanism_ev":"MAX_ITERATIONS","naive_ev":"MAX_ITERATIONS"} | 53.173186791012995 |
| 1000 | 1 | naive_ev | 0x1.1d2064a7ab27dp+12 | 4562.024573963715 | 16259adedecdf47b932ddb581e3437b14d8d8941426623e56ce1c88026755bb5 | 4486a90585abede9353f08a410ffa5b2187e623205ee280ff158ed695d44e4bc | 8 | 4 | 18 | 80 | {"cv_only":1000,"mechanism_ev":1000,"naive_ev":1000} | {"cv_only":"MAX_ITERATIONS","mechanism_ev":"MAX_ITERATIONS","naive_ev":"MAX_ITERATIONS"} | 53.173186791012995 |
| 1000 | 1 | mechanism_ev | 0x1.1d2064a7ab27dp+12 | 4562.024573963715 | 16259adedecdf47b932ddb581e3437b14d8d8941426623e56ce1c88026755bb5 | 4486a90585abede9353f08a410ffa5b2187e623205ee280ff158ed695d44e4bc | 8 | 4 | 18 | 80 | {"cv_only":1000,"mechanism_ev":1000,"naive_ev":1000} | {"cv_only":"MAX_ITERATIONS","mechanism_ev":"MAX_ITERATIONS","naive_ev":"MAX_ITERATIONS"} | 53.173186791012995 |
| 1000 | 2 | cv_only | 0x1.1d2064a7ab27dp+12 | 4562.024573963715 | 16259adedecdf47b932ddb581e3437b14d8d8941426623e56ce1c88026755bb5 | 4486a90585abede9353f08a410ffa5b2187e623205ee280ff158ed695d44e4bc | 8 | 4 | 18 | 80 | {"cv_only":1000,"mechanism_ev":1000,"naive_ev":1000} | {"cv_only":"MAX_ITERATIONS","mechanism_ev":"MAX_ITERATIONS","naive_ev":"MAX_ITERATIONS"} | 53.9728840830503 |
| 1000 | 2 | naive_ev | 0x1.1d2064a7ab27dp+12 | 4562.024573963715 | 16259adedecdf47b932ddb581e3437b14d8d8941426623e56ce1c88026755bb5 | 4486a90585abede9353f08a410ffa5b2187e623205ee280ff158ed695d44e4bc | 8 | 4 | 18 | 80 | {"cv_only":1000,"mechanism_ev":1000,"naive_ev":1000} | {"cv_only":"MAX_ITERATIONS","mechanism_ev":"MAX_ITERATIONS","naive_ev":"MAX_ITERATIONS"} | 53.9728840830503 |
| 1000 | 2 | mechanism_ev | 0x1.1d2064a7ab27dp+12 | 4562.024573963715 | 16259adedecdf47b932ddb581e3437b14d8d8941426623e56ce1c88026755bb5 | 4486a90585abede9353f08a410ffa5b2187e623205ee280ff158ed695d44e4bc | 8 | 4 | 18 | 80 | {"cv_only":1000,"mechanism_ev":1000,"naive_ev":1000} | {"cv_only":"MAX_ITERATIONS","mechanism_ev":"MAX_ITERATIONS","naive_ev":"MAX_ITERATIONS"} | 53.9728840830503 |
| 25000 | 1 | cv_only | 0x1.1d2064a7ab27dp+12 | 4562.024573963715 | 16259adedecdf47b932ddb581e3437b14d8d8941426623e56ce1c88026755bb5 | 4486a90585abede9353f08a410ffa5b2187e623205ee280ff158ed695d44e4bc | 8 | 4 | 18 | 80 | {"cv_only":25000,"mechanism_ev":25000,"naive_ev":25000} | {"cv_only":"MAX_ITERATIONS","mechanism_ev":"MAX_ITERATIONS","naive_ev":"MAX_ITERATIONS"} | 682.7375780419679 |
| 25000 | 1 | naive_ev | 0x1.1d2064a7ab27dp+12 | 4562.024573963715 | 16259adedecdf47b932ddb581e3437b14d8d8941426623e56ce1c88026755bb5 | 4486a90585abede9353f08a410ffa5b2187e623205ee280ff158ed695d44e4bc | 8 | 4 | 18 | 80 | {"cv_only":25000,"mechanism_ev":25000,"naive_ev":25000} | {"cv_only":"MAX_ITERATIONS","mechanism_ev":"MAX_ITERATIONS","naive_ev":"MAX_ITERATIONS"} | 682.7375780419679 |
| 25000 | 1 | mechanism_ev | 0x1.1d2064a7ab27dp+12 | 4562.024573963715 | 16259adedecdf47b932ddb581e3437b14d8d8941426623e56ce1c88026755bb5 | 4486a90585abede9353f08a410ffa5b2187e623205ee280ff158ed695d44e4bc | 8 | 4 | 18 | 80 | {"cv_only":25000,"mechanism_ev":25000,"naive_ev":25000} | {"cv_only":"MAX_ITERATIONS","mechanism_ev":"MAX_ITERATIONS","naive_ev":"MAX_ITERATIONS"} | 682.7375780419679 |
| 25000 | 2 | cv_only | 0x1.1d2064a7ab27dp+12 | 4562.024573963715 | 16259adedecdf47b932ddb581e3437b14d8d8941426623e56ce1c88026755bb5 | 4486a90585abede9353f08a410ffa5b2187e623205ee280ff158ed695d44e4bc | 8 | 4 | 18 | 80 | {"cv_only":25000,"mechanism_ev":25000,"naive_ev":25000} | {"cv_only":"MAX_ITERATIONS","mechanism_ev":"MAX_ITERATIONS","naive_ev":"MAX_ITERATIONS"} | 686.911216624896 |
| 25000 | 2 | naive_ev | 0x1.1d2064a7ab27dp+12 | 4562.024573963715 | 16259adedecdf47b932ddb581e3437b14d8d8941426623e56ce1c88026755bb5 | 4486a90585abede9353f08a410ffa5b2187e623205ee280ff158ed695d44e4bc | 8 | 4 | 18 | 80 | {"cv_only":25000,"mechanism_ev":25000,"naive_ev":25000} | {"cv_only":"MAX_ITERATIONS","mechanism_ev":"MAX_ITERATIONS","naive_ev":"MAX_ITERATIONS"} | 686.911216624896 |
| 25000 | 2 | mechanism_ev | 0x1.1d2064a7ab27dp+12 | 4562.024573963715 | 16259adedecdf47b932ddb581e3437b14d8d8941426623e56ce1c88026755bb5 | 4486a90585abede9353f08a410ffa5b2187e623205ee280ff158ed695d44e4bc | 8 | 4 | 18 | 80 | {"cv_only":25000,"mechanism_ev":25000,"naive_ev":25000} | {"cv_only":"MAX_ITERATIONS","mechanism_ev":"MAX_ITERATIONS","naive_ev":"MAX_ITERATIONS"} | 686.911216624896 |

## 取不到的量

无。

## 异常文本

无。
