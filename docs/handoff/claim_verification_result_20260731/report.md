# CLAIM-VERIFICATION-20260731 独立核查报告

核查日期：2026-07-31

FACT — 任务性质为只读复核。未启动实验、搜索或调参，未改动代码、论文或封存产物。

## 核查口径与总结

FACT — 本次从各组原始 JSON/CSV、任务结果、输入数据、源码、Git 对象与原始 PDF 重新读取。聚合数值由 `scripts/recompute_claims.py` 重算；该脚本只读并只向 stdout 输出 JSON（`scripts/recompute_claims.py:1-6,24-42,1066-1081`）。外置硬盘的 `._*` AppleDouble 侧车文件被明确排除（同文件 `:45-58`）。整数、字符串和布尔值按序列化值直接比较；除不尽小数外，数值不做显示舍入。不尽小数给出生成它的原始汇总量或计数口径与 `Decimal(prec=80)` 展开；运行器的 Python float 口径另行原样复现。

FACT — 64 个编号全部覆盖。判定计数为 `CONFIRMED=48`、`PARTIAL=12`、`REFUTED=1`、`NOT_CHECKABLE=3`。唯一直接反证项是 E7-5；台账写成 50c 有40个静态单元，真值是10个。

## 一、E2 算法比较

### E2-1 — CONFIRMED

FACT — 从 `baselines/algorithm_prototypes/china81_vs_opensource_20260727/raw_runs.json:1` 的2025个对象按 `(instance_id,seed)` 重组，得到405个配对单元，MV对O为354胜、46平、5负。按原始成本字符串重算的均值为 `1.9191180150258946598389658589611319611881610827997480087735944506479096704125813%`；按原运行器float顺序为 `1.919118015025895%`，与 `decision.json:1` 的差是 `0.0`。重算公式见 `scripts/recompute_claims.py:69-123`。

### E2-2 — CONFIRMED

FACT — 对405个单元检查 `O>=F>=E>=M>=MV`，成立数是299（`scripts/recompute_claims.py:80-94,124`），与 `baselines/algorithm_prototypes/china81_vs_opensource_20260727/decision.json:1` 一致。

### E2-3 — CONFIRMED

FACT — 逐层重算结果为 O→F `268/22/115`，F→E `290/29/86`，E→M `79/77/249`，M→MV `114/0/291`，顺序均为改善/回退/平（`raw_runs.json:1`；`scripts/recompute_claims.py:95-102,125`）。

### E2-4 — CONFIRMED

FACT — 原始行中O臂的405行均为 `NoImprovement(3000)`，数据源为 `NEW_DISTANCE_ONLY_O_20260727`；F/E/M/MV的1620行均为 `V7_FIXED_25000_ITERATIONS_PER_VIEW`，数据源为 `SEALED_V7_ARCHIVE_20260724`（`raw_runs.json:1`；`scripts/recompute_claims.py:104-107,126-130`）。`decision.json:1` 同时记录 `same_batch_or_same_machine_claim_allowed=false` 与 `archive_wallclock_available=false`。

### E2-5 — CONFIRMED

FACT — 未使用任何 handoff 二手总结。直接读取 `baselines/algorithm_prototypes/mvhgssp_bks_reproduction_full_20260727/decision.json:1`：18个目标中13个达标、5个未达标，未达标集合是 PR14A、PR15A、PR15B、PR16A、PR24A，终值为 `STOP_NOT_ALL_TARGETS_REPRODUCED`。

### E2-结论 — PARTIAL

FACT — 非同批同机、停止规则不同和阶梯仅299/405完整单调都成立。

INFERENCE — “不是实验失败”没有可执行的真假判定定义，不能被前述口径事实自动证明，因此整条不是 `CONFIRMED`。

### E2 附加问题

FACT — `sealed_rows_reused=1620` 与 `O_new_rows=405` 之和精确等于2025，也等于原始数组行数与 `actual_rows/expected_rows`（`decision.json:1`）。

INFERENCE — 现有数据不支持把 `1.919118015025895%` 分解为“停止规则部分”与“算法部分”。缺少的是同一批单元上、相同运行环境和共同停止规则下的O与MV对照或交叉停止规则记录。

## 二、E4 碳感知充电择时

### E4-1 — CONFIRMED

FACT — `baselines/china_e3_e7/e4_carbon_timing_20260729/decision.json:4-5` 为 `evidence_status=PASS_COMPLETE_ZERO_SEARCH_REPLAY`、`verdict=POSITIVE`。

### E4-2 — CONFIRMED

FACT — 对 `baselines/china_e3_e7/e4_carbon_timing_20260729/raw_runs.csv:2-11341` 的排放列分别求和：ASAP=`475317.3345401612233375` kg，CARBON=`214033.62756881424449620` kg。据此重算为 `54.970371998766269479158016226285610269243598705559989050207423850540349165485621%`；按运行器float累加顺序为 `54.97037199876627%`，与 `decision.json:7` 的差是 `0.0`。公式见 `scripts/recompute_claims.py:134-170`。

### E4-3 — CONFIRMED

FACT — CSV总行数为11341，扣除表头后数据行精确为11340；与 `decision.json:15-17` 的 `all_rows_retained=true`、`observed_pair_rows=11340`、`expected_pair_rows=11340` 一致。

### E4-4 — CONFIRMED

FACT — `decision.json:18-19` 为 `search_candidate_count=0`、`rescue_tuning=false`；11340个原始行的 `search_candidate_count` 唯一值也是 `0`（`scripts/recompute_claims.py:171-177`）。

### E4-结论 — NOT_CHECKABLE

INFERENCE — “无问题”与“六组里最完整”没有检查项或比较准则，因此不是可从文件中验真的命题。

FACT — 同一原始表还显示充电电费从 `528422.7924061140473160` 元增至 `1241158.274937080238615` 元，增幅为 `134.87977671924500770846579549446712206689298059785331205088354716868489299668737%`（`scripts/recompute_claims.py:140-163`）。

### E4 附加问题

FACT — 数据行数与11340一致。主终点可从CSV独立重算；Decimal重算值与序列化decision值 `54.97037199876627` 的差是 `-0.000000000000000520841983773714389730756401294440010949792576149459650834514379` 个百分点，而与运行器float值的差是 `0.0`。

## 三、E5 非线性充电

### E5-1 — CONFIRMED

FACT — `baselines/china_e3_e7/e5_nonlinear_final_20260730/decision.json:1` 的四个终点为 NL90完整可行20/20、L100假可行0/20，以及共同可行配对成本变化 min/mean/median/max 均为 `0.0%`。

### E5-2 — CONFIRMED

FACT — `baselines/china_e3_e7/e5_nonlinear_final_20260730/charging_sessions.csv:2-197` 共196个数据行，L100_control与NL90_mild各98行（`scripts/recompute_claims.py:181-189,220-223`）。

### E5-3 — CONFIRMED

FACT — 按 `(instance_id,seed,vehicle_id,session_index)` 配对，两臂键集相等；`start_soc_pct`、`end_soc_pct`、`energy_kwh` 的序列化字符串逐条相等（`scripts/recompute_claims.py:183-193,221-223`）。

### E5-4 — CONFIRMED

FACT — `start_soc_pct==0.0` 的行数是160/196（`scripts/recompute_claims.py:224`）。

### E5-5 — CONFIRMED

FACT — `charge_start_second==0.0` 的行数是140/196（`scripts/recompute_claims.py:225`）。

### E5-6 — PARTIAL

FACT — 中位数完整值是 `37.032809860860496`；按序列化字符串重算的均值是 `46.953234940037198438775510204081632653061224489795918367346938775510204081632653`。台账的37.03和46.95是舍入值，不符合本任务的完整精度规则（`charging_sessions.csv:2-197`；`scripts/recompute_claims.py:194-196,226-227`）。

### E5-7 — PARTIAL

FACT — `end_soc_pct>=99.9`有36行；字面 `nonlinear_minus_linear_seconds!=0`有68行，其中正值38行，`abs(delta)>1e-9`才是36行。高SOC的36行与 `abs(delta)>1e-9` 的36行完全同集，但与“字面非零”的68行不同集。多出的32行是 `-4.547473508864641E-13`、`-2.2737367544323206E-13` 或 `2.2737367544323206E-13` 的浮点尾差（`charging_sessions.csv:2-197`；`scripts/recompute_claims.py:197-215,228-234`）。

### E5-8 — CONFIRMED

FACT — 上述36行的 `nonlinear_minus_linear_seconds` 只有一个序列化值：`1264.5818181818177`，因此 min=median=max（`scripts/recompute_claims.py:217,235`）。

### E5-9 — PARTIAL

FACT — `baselines/china_e3_e7/e5_literature_curve_20260731/decision.json:4-12` 的曲线名为 `M17_22KW_NORMAL_PWL`，受影响36/196，序列化百分比是 `18.36734693877551%`，`new_units_run=0`，状态为 `SKIPPED_CURVE_ALSO_UNEXPOSED`。台账的18.37%只是舍入显示。

### E5-原因 — CONFIRMED

FACT — 投影代码固定路线、车辆、站点、开始时刻和充电量，只替换占用时长与物理标识（`baselines/china_e3_e7/check_e5_nonlinear_20260729.py:146-213`）。36行实际是18个物理充电会话在两臂中重复；这18个会话全部为 `start_soc=0.0`、`end_soc=100.0`、`charge_start=0.0`、`linear_duration=12645.818181818182`、`nonlinear_duration=13910.4`。首趟发车时刻是 `21600.0`，所以非线性充电结束到发车的余量在18/18会话中都是 `7689.6` 秒，大于增量 `1264.5818181818177` 秒。

FACT — 对20个L100计划做只读物理重放后，`departure_second`、`return_second`、`recharge_end_second` 的改变数为0（`scripts/recompute_claims.py:258-350`）。上述事实与当前20个计划的零成本效应解释一致。车场充电不计公共站占用费的成本代码见 `solver/src/setp_solver/cost.py:1194-1205`。

### E5 附加问题

FACT — (a) 36行的 `linear_duration_seconds` 均为 `12645.818181818182`。(b) 从非线性充电结束到运营首趟发车的余量均为 `7689.6` 秒，不是小于 `1264.5818181818177` 秒。(c) 未找到任何会话使后续出发、返回或补能结束时刻改变，改变数为0。

## 四、E3 跨场协同

### E3-1 — CONFIRMED

FACT — `baselines/china_e3_e7/e3_zone_joint_20260731/input_assignments.csv:2-301` 有300个数据行。50c算例在ZONE/JOINT两臂各50行，100c算例在两臂各100行（`scripts/recompute_claims.py:353-363,402-406`）。

### E3-2 — CONFIRMED

FACT — 300行的 `registered_differs_from_nearest` 全为False；去除臂重复后是150个唯一客户、0个错配（`input_assignments.csv:2-301`；`scripts/recompute_claims.py:357-358,404-405`）。

### E3-3 — CONFIRMED

FACT — `solver/src/setp_solver/china81.py:355-375` 先检查每个城市恰有一个车场，然后用 `depots_by_city[customer.city]` 派生 `customer_home_depot`。`baselines/china_e3_e7/e3_zone_joint_20260731/decision.json:37,41` 记录 `literal_registered_depot_column_found=false`但派生字段存在。

### E3-4 — CONFIRMED

FACT — 输入表中两个形式算例的车场集均为 `D_guangzhou` 与 `D_shenzhen`。50c按臂均为23/27，100c按臂均为46/54（`input_assignments.csv:2-301`；`scripts/recompute_claims.py:359-362,406`）。

### E3-5 — CONFIRMED

FACT — `baselines/china_e3_e7/e3_zone_joint_20260731/decision.json:30-34` 记录 `formal_units_run=40`、`ind_arm_run=false`、`ind_arm_reason=IND_AND_ZONE_INPUTS_IDENTICAL_BY_PRE_SEARCH_FACT`。`raw_runs.csv:2-41` 的40行只有ZONE和JOINT。

### E3-6 — CONFIRMED

FACT — `decision.json:8-28,39-40` 的序列化值为50c成本效应 `2.2727594138817997%`、100c `0.693114675203723%`、等权总体 `1.4829370445427614%`；两算例的距离和碳“reduction”均为负，车辆数变化为 `-1.0` 与 `-0.8000000000000007`。按CSV字符串使用Decimal重算的成本效应分别为 `2.2727594138817957636089175187680598212277416336320532994401885299134497558943598%`、`0.69311467520372048272319951125643579458140095454689338220263273923774058672492961%`，两算例等权为 `1.4829370445427581231660585150122478079045712940894733408214106345755951713096447%`（`scripts/recompute_claims.py:364-384,407-414`）。

### E3-7 — PARTIAL

FACT — 直接读取 `baselines/china_e3_e7/e3_pooling_probe_20260731/raw_units/*.json` 并按种子重组，ZONE在三个种子中均为 `2341.446789956353`。seed1的JOINT/POOLED为 `2289.318598837748`/`2290.1857525902215`，POOLED对JOINT的 reduction 为 `-0.037878246955829594133777123656432411602271472065776787447318692454698548704779797%`；seed2两者均为 `2288.011934963608`，reduction=`0%`；seed3为 `2288.011934963608`/`2288.840466684108`，reduction=`-0.036211861828123646599618404414946075433591965759208016901323155969932889485586445%`（`scripts/recompute_claims.py:386-399`）。台账的数值方向正确，但全部是舍入值。

### E3-原因 — PARTIAL

FACT — 对正式两个算例，错配确为0。对China81全部81个算例重算，总客户数为5805，错配客户数为24，分布在6个算例（`scripts/recompute_claims.py:419-469`）。

INFERENCE — “错配按构造恒为零”只对正式两个输入成立，对81算例总体不成立。另外，ZONE/JOINT两臂结果没有隔离“路径合并”之外的中介变量，所以“`1.4829370445427614%` 全部来自路径合并”不是被该两臂数据唯一识别的因果归属。

### E3 附加问题

FACT — (a) `china81.py:355-369` 显式要求车场城市集与算例城市集相等，且每城市只有一个车场。如果存在客户所在城市没有车场，加载器在366-369行直接抛出 `ValueError`，不会把该客户派给其他车场。

FACT — (b) 81算例中6个非零算例为：`cn-prd-150c-01-V2-LOCATIONS` 3/150，`cn-prd-150c-02-V2-LOCATIONS` 2/150，`cn-prd-150c-03-V2-LOCATIONS` 4/150，`cn-prd-200c-01-V2-LOCATIONS` 7/200，`cn-prd-200c-02-V2-LOCATIONS` 6/200，`cn-prd-200c-03-V2-LOCATIONS` 2/200。

FACT — (c) 上述6个预构建输入的错配率分别为 `2%`、`1.3333333333333333333333333333333333333333333333333333333333333333333333333333333%`、`2.6666666666666666666666666666666666666666666666666666666666666666666666666666667%`、`3.5%`、`3%`、`1%`。这些值是从China81原始算例加载后对每个客户的行政车场与最近车场重算，不是引用预注册或报告数字（`scripts/recompute_claims.py:419-469`）。

## 五、E6 参与与结算

### E6-1 — CONFIRMED

FACT — 从 `baselines/china_e3_e7/e6_fairness_v3_20260731/candidate_pool_summary.csv:2-21` 逐行求和，`participation_satisfying_candidate_count` 总和为0，20个单元中自然Pareto单元为0，`f_equals_i=true`为20（`scripts/recompute_claims.py:472-517`）。与 `baselines/china_e3_e7/e6_fairness_v3_20260731/decision.json:21,28-30` 一致。

### E6-2 — CONFIRMED

FACT — `instance_summary.csv:2-3` 的两个实例行为 `2.3256150488348655%` 和 `0.6979522849163983%`，等权Decimal均值为 `1.5117836668756319%`；原运行器float与 `decision.json:12-14` 的主值为 `1.511783666875632%`。以20个单元为池的另一口径是 `1.5124654575275557206%`（`scripts/recompute_claims.py:496-522`）。

### E6-3 — CONFIRMED

FACT — `baselines/china_e3_e7/e6_allocation_20260731/decision.json:7-10` 为 `search_reruns=0`、`route_search_executed=false`、`data_source=e6_fairness_v3_20260731 certified I/U rows`。Shapley转移在已有I/U结果上计算，未进入路线搜索。

### E6-4 — PARTIAL

FACT — `baselines/china_e3_e7/e6_allocation_20260731/raw_runs.csv:2-21` 有19个可行转移单元与1个不可行单元。19个可行行的平均Shapley转移为 `817.374756596798`元，平均系统节省为 `45.358150991979578947368421052631578947368421052631578947368421052631578947368421`元，两均值之比为 `18.020460241894112454059203056845544273000131774231069099252819558967864994682451`，38个成员-单元净增益的池均值为 `22.679075495989210526315789473684210526315789473684210526315789473684210526315789`元（`scripts/recompute_claims.py:477-495,523-533`）。台账除平均转移外的三个小数均为舍入值。

### E6-5 — CONFIRMED

FACT — 唯一不可行单元是 `cn-prd-100c-02-V2-LOCATIONS` seed4，系统节省 `-1.135377416539`元，core下界 `1.135377416540`、上界 `0.000000000000`（`raw_runs.csv:2-21`；`decision.json:14-21`；`scripts/recompute_claims.py:534-543`）。

### E6-结论 — PARTIAL

FACT — 公平机制事后核算、未参与路线搜索的性质成立。

INFERENCE — “E6不是失败”没有与文件字段对应的真假定义，不能与“事后核算”这一事实合并为 `CONFIRMED`。

### E6 附加问题

FACT — 候选池是20个单元摘要行。逐行求和得 `candidate_pool_unique_total=2764`、`candidate_full_evaluation_events=2869`、`participation_satisfying_candidates_total=0`（`candidate_pool_summary.csv:2-21`；`scripts/recompute_claims.py:511-517`）。

INFERENCE — 该0的精确含义是“已落盘的2764个唯一候选中没有”。现有产物没有候选空间完备性证书，所以不能在“池中确实没有”与“池未覆盖其他可能解”之间做更强的完备性判定。

## 六、E7 动态需求

FACT — E7聚合重算直接遍历 `baselines/china_e3_e7/e7_dynamic_v3_20260731/formal/{50c,100c,150c}/tasks/*.json`，方法见 `scripts/recompute_claims.py:588-838`。本节没有使用诊断报告的数字。

### E7-1 — CONFIRMED

FACT — 清除 `._*` 后共120个任务JSON，状态为114个 `LEGAL_INFEASIBLE`、6个 `PASS`。分尺度为50c `34/6`、100c `40/0`、150c `40/0`（`scripts/recompute_claims.py:588-602,755-758`）。

### E7-2 — CONFIRMED

FACT — 6个PASS产物均没有 `feasible` 键，但有数值型 `final_total_cost`；114个失败产物均为 `feasible=false`、`final_total_cost=null`（`scripts/recompute_claims.py:759-774`）。一个PASS样例见 `formal/50c/tasks/cn-prd-50c-01-V2-LOCATIONS__seed04__FULL_ROLLING.json:2-20,1662-1669`；一个失败样例见 `formal/100c/tasks/cn-prd-100c-02-V2-LOCATIONS__seed01__FULL_ROLLING.json:2-21,63-83`。

### E7-3 — CONFIRMED

FACT — 120/120个任务满足 `stream_seed=((algorithm_seed-1) mod 5)+1`（`scripts/recompute_claims.py:775`）；10个算法种子因此只对应5条事件流。

### E7-4 — CONFIRMED

FACT — 6个PASS全部属于50c，algorithm_seed只有4和9，两者的stream_seed都是4；每个种子各有CARBON_BLIND、FULL_ROLLING、NO_COOPERATION三个滚动臂（`scripts/recompute_claims.py:759-772`）。

### E7-5 — REFUTED

FACT — 50c的40个单元是10种子×4臂，所以 `STATIC_FIXED_RECOURSE` 只有10个，不是40个。这10个确实全部为 `LEGAL_INFEASIBLE`。三个尺度合计才是30个静态单元，30/30均为 `LEGAL_INFEASIBLE`（`scripts/recompute_claims.py:603-605,776-782`）。原始50c静态样例的臂、状态见 `formal/50c/tasks/cn-prd-50c-01-V2-LOCATIONS__seed01__STATIC_FIXED_RECOURSE.json:2-16,74-82`。

### E7-6 — CONFIRMED

FACT — seed9的CARBON_BLIND、FULL_ROLLING、NO_COOPERATION均为 `5462.484679661239`。seed4的CARBON_BLIND/FULL_ROLLING均为 `5975.267331229614`，NO_COOPERATION为 `7217.318971600578`（`scripts/recompute_claims.py:719-722,783`）。seed4 FULL_ROLLING的原始值见 `formal/50c/tasks/cn-prd-50c-01-V2-LOCATIONS__seed04__FULL_ROLLING.json:13-21`。

### E7-7 — CONFIRMED

FACT — 6个PASS中 `carbon_aware_charging_shift_after_event=false`、`moved_charge_actions_after_event=0`、`cross_depot_reassignment_after_event=false` 全部成立（`scripts/recompute_claims.py:759-770`）。样例字段见上述seed4 FULL_ROLLING文件 `:5,10,30`。

### E7-8 — CONFIRMED

FACT — 排除30个静态臂后，有84个失败滚动臂。逐条检查 `actual_evaluations == completed_stage_count*1200+600`，不符数为0（`scripts/recompute_claims.py:603,607-611,784-785`）。100c seed1 FULL_ROLLING为600=`0*1200+600`（原始文件 `:2-7`）。

### E7-9 — CONFIRMED

FACT — 84个失败滚动臂按 `(scale,algorithm_seed)` 组成28组，每组恰有3臂。28/28组的 `legal_infeasibility_reason` 字符串逐字节相同，因此嵌入的 `top_rejections` 路线名和计数也相同（`scripts/recompute_claims.py:612-618,786-788`）。

### E7-10 — PARTIAL

FACT — 从原始事件JSON重建触发批次的代码见 `scripts/recompute_claims.py:548-577,664-694`。50c中stream1/2/3/5的“首个含过期新增订单阶段”分别为4/3/4/3，对应失败滚动行共24个，且四条有定义值的事件流4/4与失败阶段相等。stream4无过期新增订单、也无失败滚动行；如把“双缺席”也记为模式匹配，则是5/5（`scripts/recompute_claims.py:696-713,816-826`）。

FACT — 最极端值不是 `-5415.4`秒，而是 `-10753.5458680683`秒，位于50c stream3 stage4的customer N5（`scripts/recompute_claims.py:667-687,827-833`）。原始事件的 `new_due_time=54046.4541319317` 见 `baselines/china_e3_e7/mechanism_foundation_20260730/inputs/e7_events/cn-prd-50c-01-V2-LOCATIONS/stream_seed3.json:197-218`，滚动参数见同文件 `:294-300`；stage4触发时刻为64800.0，两者之差即 `-10753.5458680683`。

### E7-11 — CONFIRMED

FACT — `solver/src/setp_solver/search/dynamic_multitrip_schedule.py:1237-1251` 从路线时间窗反推最晚发车；`:702-747` 在候选资产上检查车型/归属车场、EV可达电量和最晚发车；`:458-470` 在候选为空时返回 `no inherited asset can serve open route ...`。台账给出的代码链语义与现行源码一致。

### E7-12 — CONFIRMED

FACT — `baselines/china_e3_e7/e7_dynamic_v3_20260731/run_e7_dynamic.py:504-510` 中 `arm` 只参与合法性检查；`:513-531` 无条件构造immediate与aware，`:539-543` 无条件把ware交给 `prepare_multitrip_solution`，`:563-570` 固定返回 `strategy=aware`。

### E7-13 — PARTIAL

FACT — `ARM_CONFIGS` 的四个语义键定义于 `baselines/china_e3_e7/e7_dynamic_v3_20260731/run_e7_dynamic.py:252-280`。仓库中没有以 `ARM_CONFIGS[arm]["route_policy"]` 等逐键查询来驱动执行，但“全仓库无读取点”的字面表述过强：该字典在v3的`:1345-1362` 被 `**ARM_CONFIGS[arm]` 整体展开到自检行，在`:1488-1513` 被整体序列化。

FACT — 真实的臂行为由旧主运行器 `baselines/china_e3_e7/e7_dynamic_20260731/run_e7_dynamic.py:815-896` 按 `arm` 字符硬编码分支实现。

INFERENCE — 准确说法是：四个声明键本身没有成为执行接线；它们会被读出用于展示/序列化，臂语义由另一套分支实现。

### E7-14 — CONFIRMED

FACT — 从120个任务的 `nominal_plan_sha256` 去重，50c有10个唯一值，100c有10个，150c只有1个（`scripts/recompute_claims.py:715-718,834-835`）。因此150c的40个单元共用一个名义方案SHA-256。

### E7-15 — CONFIRMED

FACT — v3在首次切割时从名义方案certificate ledger的 `ledger.assets` 构造 `base_states`，没有把合法上限中未被名义解使用的车辆补入（`baselines/china_e3_e7/e7_dynamic_v3_20260731/run_e7_dynamic.py:600-621`）。从 `data/ChinaInstances/china81_finite_fleet_authority_v2_20260731/fleet_caps.csv:2-145` 与名义方案重算，合法车队上限/名义已用实体车为50c `12/8`、100c `23/17`、150c `35/27`（`scripts/recompute_claims.py:723-750,836`）。

### E7-U1 — NOT_CHECKABLE

FACT — 在不重跑实验的前提下，现有的60个100c/150c失败滚动产物还能查到以下程度：60/60都是 `failure_stage=1`、`payload=null`、`physical_vehicle_ids=[]`、`vehicle_count=null`；60/60的 `legal_infeasibility_reason` 都保留了 `top_rejections`（`scripts/recompute_claims.py:634-658,792-808`）。一个原始样例见 `formal/100c/tasks/cn-prd-100c-02-V2-LOCATIONS__seed01__FULL_ROLLING.json:2-16,29-30,59-83`。

FACT — `top_rejections` 不是JSON子对象，而是嵌在原因字符串中的Python字面量列表，结构恰为长度3的 `[(full_reason_string, integer_count), ...]`。这个 `integer_count` 是搜索中的拒绝事件数，不是任务单元数。60行共20个不同的完整原因字符串。把top-3文本归类并按其嵌入计数求和，得 `NO_INHERITED_ASSET=10797`、`BACKTRACKING_LIMIT=297`、`ROUTE_CAPACITY=246`。模式分布为：100c中24行是三项全no-asset，6行是no-asset/no-asset/backtracking；150c中24行是三项全no-asset，6行是no-asset/capacity/no-asset。解析代码见 `scripts/recompute_claims.py:580-585,620-658`。

INFERENCE — 现有字段可以定位到“无继承资产”、“回溯上限”和“路线超载”三类顶层原因，但 `no inherited asset` 是 `_dynamic_assignment_candidates` 给出空集后的统一文本（`solver/src/setp_solver/search/dynamic_multitrip_schedule.py:458-470`）。该文本没有记录每辆候选车究竟在车型、归属车场、最晚发车还是EV电量条件被拒绝。四条件的代码在同文件`:702-747`，但中间布尔结果没有落盘。

INFERENCE — 要彻底分解四个条件，还缺每个失败profile的候选asset状态（车型、home depot、available_second、battery_kwh）、profile的latest/preferred departure与drive energy，以及每个条件的分项拒绝计数或逐车追踪。现有JSON无法恢复这些中间状态，所以中心问题判为 `NOT_CHECKABLE`。

### E7-U2 — NOT_CHECKABLE

FACT — `baselines/china_e3_e7/e7_dynamic_v3_20260731/run_e7_dynamic.py:1596-1607` 的探针硬编码为50c、algorithm seed1、FULL_ROLLING、`max_stages=1`，尝试cap序列是800、1600，但因首次已触发plateau而只执行了1次。`baselines/china_e3_e7/e7_dynamic_v3_20260731/budget_lock.json:2-22,6451-6462` 记录cap=800、两pass均未提前耗尽候选、最晚改善评价号=505、plateau=true；`:6475-6479` 选定 `per_search_pass_cap=600`、`selected_total_stage_cap=1200`。代码自述的探针范围也是50c seed1 stream1 FULL_ROLLING第一阶段（`run_e7_dynamic.py:2442-2446`）。

INFERENCE — 现有产物确认100c/150c没有专用预算探针，也没有候选空间耗尽证书，所以“预算不足”与“结构性无解”在现有证据中不可区分。要彻底查清还缺100c和150c的候选空间完全耗尽证书，或覆盖更大cap的完整收敛与拒绝追踪。这些不在现有封存产物中，因此判 `NOT_CHECKABLE`。

### E7-U3 — PARTIAL

FACT — 形式任务集中30/30个 `STATIC_FIXED_RECOURSE` 确实是 `LEGAL_INFEASIBLE`。但自检代码 `baselines/china_e3_e7/e7_dynamic_v3_20260731/run_e7_dynamic.py:1364-1377` 只调用了1个50c、seed1、STATIC_FIXED_RECOURSE、`per_pass_cap=1`、`max_stages=1` 的样例，只断言该样例是第1阶段合法不可行。自检结果文本在`:1463-1469` 也只写了50c该样例。

INFERENCE — “30个静态臂都在跑前写进自检通过条件”不成立；成立的部分是30个正式单元都失败，且其中1个50c seed1样例在跑前自检中被明示验证。

### E7 6.3 问题的答案摘要

FACT — U1在不重跑时可恢复到任务字段、失败阶段、完整原因字符串、top-3路线/计数及三类顶层原因；恢复不到四个候选过滤条件的单独命中。U2可确认探针范围和选定过程，不可确认100c/150c失败性质。U3可确认自检只覆盖1个静态单元，不是30个。

## 七、基础设施类断言

### INF-1 — CONFIRMED

FACT — `baselines/china_instances/build_china81_finite_fleet_authority_v1_20260723.py:97-122` 的 `_route_feasible` 只构造 `vehicle_type="cv"` 路线，使用CV载重、时间窗和路网。主储备系数在`:57-60` 为 `1.25`，`num_ev=max(1,ceil((1.25-1)*R_d))` 见`:195-211`。EV载重与电池都未进入 `R_d` 的定容计算。现行车型参数中CV载重是 `1735.0` kg，EV载重是 `1700.0` kg、电池是 `77.28` kWh（`solver/src/setp_solver/china81.py:634-672`）。

### INF-2 — CONFIRMED

FACT — 直接比较Git对象 `54d78421^:solver/src/setp_solver/china81.py` 与 `54d78421:solver/src/setp_solver/china81.py`，该commit的相关diff只修改EV车型号、载重1000→1700、整备质量3300→2600、迎风面积和电池140.41→77.28；CV段没有字段diff。当前CV/EV值见 `solver/src/setp_solver/china81.py:637-672`。

### INF-3 — CONFIRMED

FACT — 未使用已生成的comparison报告值。直接重读 `data/ChinaInstances/china81_finite_fleet_authority_v1_20260723/fleet_caps.csv:2-145` 与 `data/ChinaInstances/china81_finite_fleet_authority_v2_20260731/fleet_caps.csv:2-145`，144个 `(instance_id,depot_id)` 键完全相同，逐行差异数为0；两者总 `R_d=1040`、`num_cv=1040`、`num_ev=309`。直接比较两个 `witnesses/*.json` 目录的81对JSON，排除 `schema` 键后81/81目标值、路线和其他字段全等（`scripts/recompute_claims.py:841-878,913-941`）。

### INF-4 — CONFIRMED

INFERENCE — INF-1的定容公式没有EV参数入口，INF-3的全等重算与此相符。所以“旧EV载重推出的 `R_d` 不再有效”问错了对象；`R_d` 是由CV口径构造的。

### INF-5 — CONFIRMED

FACT — 0.25直接来自构造参数 `MAIN_RESERVE_FACTOR=1.25` 的增量（生成器`:57-60,202-211`）。生成过程中没有读取EV电池、EV弧能耗或EV载重来验证witness路线。

FACT — 针对附加问题，本次在不跑搜索的情况下，对v2的81个witness、144个车场、1040条已有CV路线逐条重算“如改用EV”的弧能耗与最大载重（`scripts/recompute_claims.py:967-1063`）。电池容量唯一值是 `77.28` kWh，EV载重唯一值是 `1700.0` kg，路线能耗范围是 `9.094221001679287` 至 `66.29088100604332` kWh。144/144个车场都有至少 `num_ev` 条同时满足电量与载重的已有witness路线；“该车场的EV任一路线都跑不完”的车场数为0，且“可行路线数少于num_ev”的车场数也为0。

### INF-6 — CONFIRMED

FACT — `data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723/tariff_carbon_hourly_calendar.csv:2-12097` 共12096个数据行。数值碳因子列只有 `carbon_factor_kgco2e_per_kwh`；另有非数值来源标识列 `carbon_source_column`。`solver/src/setp_solver/china81.py:803-817` 读取同一个 `gamma_kg`，并同时赋给 `actual_gco2_per_kwh` 和 `forecast_gco2_per_kwh`。

### INF-7 — CONFIRMED

FACT — 调度侧的动态充电重排默认使用 `forecast_gco2_per_kwh`（`solver/src/setp_solver/search/dynamic_multitrip_schedule.py:548-558`）。排放核算使用 `actual_gco2_per_kwh`（`solver/src/setp_solver/cost.py:713-743`）。静态多趟充电重排的默认字段为actual（`solver/src/setp_solver/search/multitrip_schedule.py:1393-1409,1521-1537`）。E4对每个候选同时按forecast和actual计算（`baselines/china_e3_e7/e4_carbon_timing_20260729/run_e4_carbon_timing.py:553-580`）。

FACT — 仓库内的其他forecast读取点包括 `solver/src/setp_solver/instance_loader.py:538-552`、`solver/src/setp_solver/search/formal_runner.py:1049-1062`、`solver/src/setp_solver/search/carbon_operators.py:208-209`、`solver/src/setp_solver/algorithms/resetp_alns/support/mechanism_prescription.py:754-759`、`solver/src/setp_solver/algorithms/resetp_alns/operators/carbon_operators.py:372`，以及E7 v3的 `run_e7_dynamic.py:504-531,1319-1327`。

FACT — E2正式原始行是成本/路线比较，没有forecast字段。E3的formal runner可构造两字段，但形式ZONE/JOINT效果表没有forecast调度入口；E5是已定路线/充电决策的充电曲线重放；E6使用E3已封存I/U行做候选与事后分配。这四组正式结果链都未显式用 `forecast_gco2_per_kwh` 作为调度决策字段；排放核算走actual字段。

### INF-8 — CONFIRMED

FACT — `data/Carbon/中国情景/cef_dataset_full_20260731/figshare_article_28953545.json:1` 列出7个文件及出版方MD5。对 `cef_dataset_full_20260731/` 中Annotation PDF、S1–S5五个Excel和Input parameters Excel逐个重算MD5，7/7与公布字符串相等（`scripts/recompute_claims.py:899-912,958-963`）。

### INF-9 — CONFIRMED

FACT — `data/Carbon/中国情景/cef_dataset_full_20260731/Annotation_of_the_dataset.pdf` 第1页将数据集称为2025–2060年planning scenarios下的projected electricity carbon emission factors；第4页明言小时数据是由power system operation simulation计算的每小时平均排放强度，不是瞬时值。

### 基础设施附加问题结果

FACT — INF-5的只读witness检查结果是：81算例中不存在“该车场的EV无论如何都跑不完分给它的任一条已有witness路线”的车场，计数为0/144。

FACT — INF-7的额外forecast读取点已在INF-7列全。E2/E3/E5/E6正式链未把forecast字段作为明示调度决策输入；E3的通用profile变换会同时写两字段，这与“正式效果链使用forecast做决策”不是同一件事。

## 八、两处自我更正

### COR-1 — CONFIRMED

FACT — 代码侧的forecast/actual机制按INF-7所列路径确实存在，E4也同时用两个字段计算。`data/Carbon/时变碳强度/Carbon_Intensity_Data.csv:2-1394` 共1393个数据行，1337行 `Actual Carbon Intensity` 与 `Forecast Carbon Intensity` 不同，56行相同，actual-forecast范围是 `-48` 至 `52`。`data/Carbon/时变碳强度/neso-ci-national-methodology_v2.pdf` 第1页说明API提供最多48小时的forecast，并在每个半小时结束提供estimated carbon intensity。因此“本项目没有预测机制”的原前提不成立。

FACT — Git `HEAD:docs/paper_v2/paper_main.tex:373,459-466` 保留了 `\widehat\gamma_t`/预测与 `\gamma_t`/实际的模型区分；当前工作树 `docs/paper_v2/paper_main.tex:360,449-457` 已改成单一 `\gamma_t` 并声明两端同值。当前实验章 `docs/paper_v2/paper_main.tex:1033-1041` 另外正确说明中国数据是情景投影，调度与核算两端使用同一预先给定序列。

INFERENCE — “建模章保留通用forecast/actual机制，实验章说明中国算例两端同值”同时与代码分工、NESO原始方法文档和中国数据的投影属性一致。因此该自我更正的事实前提成立。

### COR-2 — PARTIAL

FACT — 车队v1/v2重算全等成立，但其直接原因是EV参数未进入 `R_d`定容，不是EV续航或车队构成已被验证。原生成器确实没有EV续航检查。

INFERENCE — “25%无依据”的表述过于绝对。代码中有明示构造依据：`MAIN_RESERVE_FACTOR=1.25`，并取其增量0.25生成EV数。本次在原始来源与生成代码中未找到该0.25的外部文献或经验车队依据。因此“全等不等于构成已验证”成立，但“25%完全无依据”不成立。

## 台账没列到但发现的问题

### NF-1 — E4的电费反向变化未进入台账结论

FACT — E4的充电排放降低 `54.970371998766269479158016226285610269243598705559989050207423850540349165485621%`，同时充电电费增加 `134.87977671924500770846579549446712206689298059785331205088354716868489299668737%`。台账的E4总结没有列出后一个同表原始结果。证据：`baselines/china_e3_e7/e4_carbon_timing_20260729/raw_runs.csv:2-11341`；`scripts/recompute_claims.py:134-163`。

### NF-2 — E5的36行不是36个独立物理会话

FACT — `charging_sessions.csv` 在两臂中逐键完全配对，因此高SOC的36行对应18个物理充电决策的两臂重复，不是36个独立会话（`scripts/recompute_claims.py:258-263,340-349`）。

### NF-3 — E6同时存在两个不同的公平代价聚合值

FACT — 两个实例行等权均值是 `1.5117836668756319%`（decision float为 `1.511783666875632%`）；20个单元的池聚合值是 `1.5124654575275557206%`（decision float为 `1.5124654575275558%`）。两者是不同权重定义，不是数值误差（`baselines/china_e3_e7/e6_fairness_v3_20260731/decision.json:12-14`；`scripts/recompute_claims.py:496-522`）。

### NF-4 — E7的top_rejections比“路线名与计数”更丰富，但仍不到四条件级

FACT — 100c/150c的60个失败滚动行中，top-3文本可区分 `NO_INHERITED_ASSET`、`BACKTRACKING_LIMIT`、`ROUTE_CAPACITY` 三类，而不只是无语义的路线名。但 `NO_INHERITED_ASSET` 仍合并了候选函数的四个过滤条件。证据：`baselines/china_e3_e7/e7_dynamic_v3_20260731/formal/100c/tasks/cn-prd-100c-02-V2-LOCATIONS__seed01__FULL_ROLLING.json:30`；`scripts/recompute_claims.py:580-585,634-658`。

### NF-5 — E7静态臂自检范围仅一个单元

FACT — 自检只验证50c seed1的第1阶段、per-pass cap1，而形式任务有30个静态臂。“30个都是跑前自检条件”与代码不符（`baselines/china_e3_e7/e7_dynamic_v3_20260731/run_e7_dynamic.py:1364-1377,1463-1469`）。

### NF-6 — China81的actual字段名不代表观测实际值

FACT — China81日历有 `carbon_source_column` 来源标识，但唯一数值碳因子被同时复制给forecast和actual（`tariff_carbon_hourly_calendar.csv:1-12097`；`solver/src/setp_solver/china81.py:803-817`）。原始中国数据文档将它定义为规划情景投影与运行模拟小时均值，所以字段名 `actual_gco2_per_kwh` 在China81上的数据语义是“用于事后核算的同一预给序列”，不是电网实测值。证据：`Annotation_of_the_dataset.pdf` 第1、4页。
