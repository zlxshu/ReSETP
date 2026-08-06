# Y2：多趟语义下的车队规模与电动化档位重算

状态：`Y2_FLEET_MULTITRIP_COMPLETE`。四部分均覆盖81个算例、144个车场和405个算例×档位单元；未启动路径搜索，`route_search_executed=false`、`search_evaluations=0`。

## 结论

`FACT`：X4 的1040个 `R_d` 现在只表示配送趟。固定这些趟的客户集合和访问顺序后，CV实体车合计从1040辆降为693辆。144个车场中，96个取得完整EV趟链与双桩证书；48个未认证，其中44个车场含至少一条既有CV趟无法直接改作EV趟（54条趟超过1700 kg载重，另有3条EV重放错过客户时窗，其中2条同时超载），4个车场即使把所有趟拆成一车一趟也排不进2×22 kW充电槽。

`FACT`：100%电动化从单趟口径的75/81降为多趟固定趟口径的41/81；NOT_CERTIFIED 从6增至40。逐算例方向为：变差34个、变好0个、两轮都通过41个、两轮都未认证6个。多趟没有改善100%档；实体车复用节省资产，但EV复用新增趟间充电，且原CV趟中存在EV载重/时窗不兼容。

## 第一部分：多趟下的最少实体车数

`FACT`：输入趟来自 `data/ChinaInstances/china81_finite_fleet_authority_v2_20260731/witnesses/*.json`，每条路线原样冻结，只把语义从车辆改为趟。未重新分组客户、未改访问顺序。CV按 `route_timing` 固定见证时钟做区间分割；每车场最大同时在外趟数与证书实体车数相等，故得到该固定时钟下的最少CV实体车数。

`FACT`：现行China81车场节点没有独立装货参数，`Node.service_time=0`，所以趟间最短返场装货时间为0秒。该字段逐行写入 `determinants.minimum_return_reload_seconds`，没有自造装货系数。

`FACT`：EV逐趟先检查1700 kg载重、时窗、77.28 kWh电池，再按按需补电传播趟间SOC。首趟从0 kWh在当日服务时域内充到所需出发电量；每笔趟间补电都有kWh、22 kW非线性时长、释放时刻、截止时刻和占用的30分钟槽。双桩排程用与检查器一致的“每个被触及槽计一辆车”规则作精确容量放置。逐车场证书、趟链和充电作业见 `fleet_sizing_multitrip.json`。

## 第二部分：五档重认证

- 0% EV：CERTIFIED 81/81，NOT_CERTIFIED 0/81。
- 25% EV：CERTIFIED 81/81，NOT_CERTIFIED 0/81。
- 50% EV：CERTIFIED 78/81，NOT_CERTIFIED 3/81。
- 75% EV：CERTIFIED 63/81，NOT_CERTIFIED 18/81。
- 100% EV：CERTIFIED 41/81，NOT_CERTIFIED 40/81。

100%档逐算例变化如下。机器可读原因与车场违反项见 `levels_design_multitrip.json.single_vs_multitrip_100_percent_by_instance`。

| 算例 | 单趟100% | 多趟100% | 方向 |
|---|---|---|---|
| cn-cy-100c-01-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-cy-100c-02-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-cy-100c-03-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-cy-10c-01-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-cy-10c-02-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-cy-10c-03-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-cy-150c-01-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-cy-150c-02-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-cy-150c-03-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-cy-15c-01-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-cy-15c-02-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-cy-15c-03-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-cy-200c-01-V2-LOCATIONS | NOT_CERTIFIED | NOT_CERTIFIED | UNCHANGED_NOT_CERTIFIED |
| cn-cy-200c-02-V2-LOCATIONS | NOT_CERTIFIED | NOT_CERTIFIED | UNCHANGED_NOT_CERTIFIED |
| cn-cy-200c-03-V2-LOCATIONS | NOT_CERTIFIED | NOT_CERTIFIED | UNCHANGED_NOT_CERTIFIED |
| cn-cy-20c-01-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-cy-20c-02-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-cy-20c-03-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-cy-25c-01-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-cy-25c-02-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-cy-25c-03-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-cy-50c-01-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-cy-50c-02-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-cy-50c-03-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-cy-75c-01-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-cy-75c-02-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-cy-75c-03-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-jjj-100c-01-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-jjj-100c-02-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-jjj-100c-03-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-jjj-10c-01-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-jjj-10c-02-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-jjj-10c-03-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-jjj-150c-01-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-jjj-150c-02-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-jjj-150c-03-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-jjj-15c-01-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-jjj-15c-02-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-jjj-15c-03-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-jjj-200c-01-V2-LOCATIONS | NOT_CERTIFIED | NOT_CERTIFIED | UNCHANGED_NOT_CERTIFIED |
| cn-jjj-200c-02-V2-LOCATIONS | NOT_CERTIFIED | NOT_CERTIFIED | UNCHANGED_NOT_CERTIFIED |
| cn-jjj-200c-03-V2-LOCATIONS | NOT_CERTIFIED | NOT_CERTIFIED | UNCHANGED_NOT_CERTIFIED |
| cn-jjj-20c-01-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-jjj-20c-02-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-jjj-20c-03-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-jjj-25c-01-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-jjj-25c-02-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-jjj-25c-03-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-jjj-50c-01-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-jjj-50c-02-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-jjj-50c-03-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-jjj-75c-01-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-jjj-75c-02-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-jjj-75c-03-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-prd-100c-01-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-prd-100c-02-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-prd-100c-03-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-prd-10c-01-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-prd-10c-02-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-prd-10c-03-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-prd-150c-01-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-prd-150c-02-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-prd-150c-03-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-prd-15c-01-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-prd-15c-02-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-prd-15c-03-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-prd-200c-01-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-prd-200c-02-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-prd-200c-03-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-prd-20c-01-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-prd-20c-02-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-prd-20c-03-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-prd-25c-01-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-prd-25c-02-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-prd-25c-03-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-prd-50c-01-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-prd-50c-02-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-prd-50c-03-V2-LOCATIONS | CERTIFIED | CERTIFIED | UNCHANGED_CERTIFIED |
| cn-prd-75c-01-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-prd-75c-02-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |
| cn-prd-75c-03-V2-LOCATIONS | CERTIFIED | NOT_CERTIFIED | WORSE |

新增变差算例及首要违反项：

- `cn-cy-100c-01-V2-LOCATIONS`：2×22 kW双桩无法容纳全部固定趟充电作业。
- `cn-cy-100c-02-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-cy-100c-03-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-cy-150c-01-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-cy-150c-02-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-cy-150c-03-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-cy-15c-01-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-cy-15c-03-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-cy-50c-02-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-cy-75c-02-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-cy-75c-03-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-jjj-100c-01-V2-LOCATIONS`：2×22 kW双桩无法容纳全部固定趟充电作业。
- `cn-jjj-100c-02-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-jjj-100c-03-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-jjj-150c-01-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗；2×22 kW双桩无法容纳全部固定趟充电作业。
- `cn-jjj-150c-02-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-jjj-150c-03-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-jjj-25c-01-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-jjj-75c-01-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-jjj-75c-03-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-prd-100c-01-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-prd-100c-03-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-prd-150c-01-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-prd-150c-03-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-prd-15c-01-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-prd-15c-03-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-prd-200c-01-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-prd-200c-02-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-prd-200c-03-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-prd-20c-03-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-prd-25c-02-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-prd-75c-01-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-prd-75c-02-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。
- `cn-prd-75c-03-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗。

原6个200客户未认证算例仍未认证：

- `cn-cy-200c-01-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗；未放宽任何约束。
- `cn-cy-200c-02-V2-LOCATIONS`：2×22 kW双桩无法容纳全部固定趟充电作业；未放宽任何约束。
- `cn-cy-200c-03-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗；未放宽任何约束。
- `cn-jjj-200c-01-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗；未放宽任何约束。
- `cn-jjj-200c-02-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗；未放宽任何约束。
- `cn-jjj-200c-03-V2-LOCATIONS`：至少一条原CV固定趟违反EV载重或时窗；未放宽任何约束。

## 第三部分：与X4单趟表的关系

`DECISION`：两套表可以同时存在，但不能作为同一实验的两次车队规模报告。Y2表是正文正式的实体车多趟表；X4表只能作“每条路线独占一辆车”的受限诊断或附录，用来解释路线数与实体资产数为何不同。表号、标题、分母和主张必须分开；正文不得把X4的 `R_d/candidate_total` 与Y2实体车数直接横比。细则见 `single_vs_multitrip_relation.json`。

## 第四部分：对E4/E6已完成实验的影响

`DECISION`：E4的90份解和E6的900份解不全部作废；可作为“每辆实体车只执行一趟”的受限子模型结果引用。MT1已逐份确认E4 90/90、E6 900/900完整多趟接口可执行，E4的270笔返场补电共5869.852618210776 kWh全部入账。

`FACT`：它们不是打开多趟后的最优结果。旧求解空间禁止车辆复用，后验把固定路线装入更少实体车只能证明可执行，不能证明扩大可行域后的最优值。若把旧结果映射到Y2档位，必须逐车场验证旧CV/EV向量与Hamilton向量完全相等；若主张完整多趟优化效应，E4需重新优化，E6需重新估计全部联盟价值和分配结果。严格条件见 `legacy_experiment_impact.json`。

## 核算边界与复算入口

`FACT`：Y2的“最少”针对冻结的authority-v2趟集合与注册见证时钟。路线级最优重组不在本任务内；所有 NOT_CERTIFIED 行保留原违反项。输入、每趟载重/时钟/能量、实体车链、补电kWh、充电时隙、双桩并发、Hamilton向量和405个证书均已写入两个JSON。

`FACT`：本轮没有引用母体论文车队数字，没有改载重、时间窗、电池、桩数、功率或服务时域，没有修改任何源码或既有产物。
