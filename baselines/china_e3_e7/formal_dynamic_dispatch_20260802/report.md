# XC2 动态发车时机正式实验（论文 5.3）

终态：`XC_DYNAMIC_FORMAL_COMPLETE`。30 个策略—种子配对场景全部进入冻结执行清单；所有硬不可行、搜索未找到和不利差值均保留。

## 预注册与口径

实例为 `cn-prd-100c-02-V2-LOCATIONS`，每个 H0/G2 种子含 20 张独立新订单，服务日为 06:00--22:00。三策略为逐单立即、固定 30 分钟、累计 500 kg 或最多 30 分钟；实际调整次数是结果，不强制为 3。预优化和每次重优化均使用 HGS 种群 120、最大 2000 代，且没有第二套停止规则。

碳感知与碳盲两臂在每个触发点共享事件、种子、冻结状态和预算；碳盲臂仅把决策时点之后的城市碳强度按最后已知值延续，其他输入不变。为使下一个触发点仍能共享状态，预注册以碳盲臂作为共同状态承载轨迹；碳感知臂每次仍保存完整搜索与完整续行解，配对差是同状态反事实差，不是零搜索重打分。

固定成本按实体车辆编号计 170 元，多趟开启，车场充电并发不设上限，公共站并发仍按实例，车队上限来自 authority v3。未引入信息等待的货币成本。

预注册反证条件：The Section 5.3 claim is not supported if the registered 30 paired scenarios show neither a change in post-event remaining charging windows / available-versus-used CV-EV capacity nor a corresponding route, vehicle-type, or charging response; it is also not supported if hard infeasibility or search-not-found outcomes prevent the three registered strategies from being compared. Zero, adverse, mixed, or unstable aware-minus-blind differences are retained and do not permit seed replacement or parameter rescue.

## 事件／状态表（预注册代表事件）

| 事件 | 到达 | 类型/需求 | 触发 | 待服务 | 可用CV/EV | 实际CV/EV | 最晚服务余量(min) | 剩余充电窗总计(min) | 新增车辆 | 状态 |
|---|---|---|---|---:|---:|---:|---:|---:|---|---|
| ADD_016_C076 | 06:00:05 | add/347.0 kg | 06:08:19 (demand_threshold) | 82 | 13/4 | 6/4 | 350.58 | 0.00 | True | PASS_COMPLETE_OPTIMIZATION |

判断：同一种子下三种策略面对完全相同的 20 个外生事件，但因触发时刻不同，其内生车辆状态不强制相同；每一策略—种子内的碳感知／碳盲两臂则共享同一冻结状态。`HARD_INFEASIBLE` 只用于已证明违反硬容量或硬时间窗必要条件的行，`SEARCH_NOT_FOUND` 只表示冻结的完整搜索未找到可执行续行，两者未混写。

全量逐事件状态（车辆位置、下一趟剩余容量、待服务集合、窗口、运力和改变计数）在 `event_state_table.csv`；逐触发搜索状态在 `stage_runs.csv`。

## 代表路线调整图

代表事件在搜索前固定为 `ADD_016_C076`（策略 `hybrid_500kg_or_30_minutes`、seed 1、第 1 批、碳感知臂）。图为同坐标双面板：`representative_route_adjustment.png`；虚线为 CV 路线，实线为 EV 路线，红星为预注册事件。图状态：`PASS_PREREGISTERED_ROUTE_FIGURE`。

## 策略比较表

下表只并列描述，不按平均成本给策略排名，也不挑正文赢家。

| 策略 | 臂 | 完整指标场景 | 车辆数 | 实际调整次数 | 距离(km) | 总成本(元) | 排放(kg) | 响应率(%) / 服务量 | 路线/车型/充电改变 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| continuous_per_order | carbon_aware | 10/10 | 15.600 | 15.500 | 1981.739 | 5585.307 | 548.433 | 77.500 / 15.500 | 35.900/16.600/9.000 |
| continuous_per_order | carbon_blind | 10/10 | 15.600 | 15.500 | 1981.739 | 5585.307 | 548.433 | 77.500 / 15.500 | 35.900/16.600/8.600 |
| periodic_30_minutes | carbon_aware | 10/10 | 15.500 | 9.000 | 1953.556 | 5526.605 | 541.454 | 75.000 / 15.000 | 32.300/15.400/7.900 |
| periodic_30_minutes | carbon_blind | 10/10 | 15.500 | 9.000 | 1953.556 | 5526.605 | 541.454 | 75.000 / 15.000 | 32.300/15.400/7.900 |
| proposed_500kg_or_30_minutes | carbon_aware | 10/10 | 15.600 | 10.100 | 1938.735 | 5526.440 | 538.879 | 76.000 / 15.200 | 38.100/17.200/8.600 |
| proposed_500kg_or_30_minutes | carbon_blind | 10/10 | 15.600 | 10.100 | 1938.735 | 5526.440 | 538.879 | 76.000 / 15.200 | 38.100/17.200/8.600 |

碳感知减碳是否伴随成本、距离、车型或充电改变，逐触发配对差保存在 `paired_differences.csv`。策略表不把信息等待分钟货币化。

## 主张检验

按预注册反证条件的机械判定为 `SUPPORTED_AS_REGISTERED_MECHANISM_OBSERVATION_NO_WINNER_CLAIM`。该标签只回答本节登记主张是否被这些场景支持，不把构造实例升级为普遍规律，也不从平均成本选赢家。

## 新歧义的保守取舍与边界

三策略必须在不同触发时刻演化，因此不能同时要求‘三策略的内生车辆状态也相同’；本实验保留相同外生事件流，并只在同一策略—种子内严格匹配两碳臂的冻结状态。为满足这一点，碳盲臂承载共同历史，碳感知臂是每个决策点的完整反事实续行。故配对差识别的是同状态下未来碳信息的决策价值，不应写成两条各自滚动执行的全日政策差。

PyVRP 的种群参数将 120 解释为每次生存者选择后的最小种群；内部每 40 个后代执行一次生存者选择。40 是引擎的代内批量参数，不是额外停止规则；唯一停止条件仍为 2000 次 HGS 迭代。终端种群最多取 120 个完整候选进入 ReSETP 物理机制重排。

## 记录完整性

`preregistration.json` 在开跑前原子写入且跑后未改；`metadata.json` 锁定源码与输入 SHA-256、git 提交、模型开关、authority、实例和代表事件。每个场景的两臂均保存预优化及逐触发完整解；各文件含 `solution_sha256`。`artifact_hashes.json` 排除 AppleDouble、`__pycache__`、自身与终态哨兵。
