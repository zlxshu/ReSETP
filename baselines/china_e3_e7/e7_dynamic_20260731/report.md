# E7 动态需求压力测试

当前状态：`HALT_PROBE_STARTUP_KEYERROR_INSTANCE_PATH`。15 条事件流调查和预注册已经完成，但收敛探针在进入候选搜索前因 China81 `source_paths` 键名接线错误崩溃；E7 完整候选评价为 0，50c/100c/150c 正式实验均未运行，没有任何动态效果数字。

## 1. 现有资产调查

冻结事件流位于 `baselines/china_e3_e7/mechanism_foundation_20260730/inputs/e7_events/<instance_id>/`。实例对应关系为 50c=`cn-prd-50c-01-V2-LOCATIONS`、100c=`cn-prd-100c-02-V2-LOCATIONS`、150c=`cn-prd-150c-01-V2-LOCATIONS`。每个实例有 `stream_seed1` 至 `stream_seed5`，每条流同时保存 canonical JSON 与 typed TSV，因此共 15 条逻辑事件流、30 个镜像文件。

JSON 外层字段为 `schema`、`instance_id`、`stream_seed`、`rolling_parameters`、`absolute_operating_clock` 和 `events`。单事件包含 `event_id`、`event_type`、`t_appear`、`customer_id`、旧/新需求、需求差、坐标、旧/新时间窗、需求/时间窗/服务时间来源、donor 客户、服务时间、来源和生成种子。事件类型只有新增、取消和需求变化。50c 每流 12 个事件（5 新增、2 取消、5 需求变化），100c 每流 25 个（10、5、10），150c 每流 38 个（15、8、15），合计 375 个事件。

独立逐字段回读结果为 15/15 JSON–TSV 完全一致；排序均为 `(t_appear,event_id)`；foundation 的 15 个 canonical payload SHA-256 全部复算一致。所有新增事件均精确复制同一实例内 donor 客户的坐标、需求和服务时间：50c 25/25、100c 50/50、150c 75/75。这个事实允许新增节点精确克隆 donor 在冻结有向道路矩阵和 CV/EV road-profile 中的入弧、出弧；不得使用 `dynamic.py` 对无 road profile 新节点的欧氏距离回退。

## 2. 原始四臂与可实现性

`e3_e7_experiment_product_design_20260712.md` 的原始四臂为：B1 终局全知全部事件后一次静态求解，用于信息成本；B2 协同、碳感知充电、逐阶段参与保障全部开启的完整滚动；B3 与 B2 相同但硬锁客户责任车场；B4 与 B2 相同但充电使用最早可行时刻。四臂共享事件流、种子和阶段预算，公平在全部臂启用。

现有可复用组件分三层。`solver/src/setp_solver/search/dynamic.py` 有事件数据类、事件生成/回读、触发批处理和早期滚动入口，但历史认证已明确该入口不足以承载正式的物理状态冻结。`solver/src/setp_solver/search/dynamic_multitrip_schedule.py` 有严格整趟承诺、车辆可用时刻、剩余电量、已开始充电锁、动态多趟排程、碳感知重排与证书验证。`baselines/e7_dynamic/e7_formal_dynamic_value_20260714.py`、`e7_full_mechanism_probe_20260714.py` 和 `e7_formal_resumable_runner_20260715.py` 已把严格状态、同状态无协同基准、成员收益闭合与充电择时连成旧 L-main 正式框架。

缺口有两项。第一，旧正式框架绑定旧 L-main `SearchBundle` 和 ALNS，没有当前 China81 `China81Bundle`、冻结道路 profile、E3 JOINT 保存解的现成桥接层。第二，原始 B1 虽然技术上能做后见静态求解，却不经历因果事件和不可撤回执行，所以不能回答本任务要求的“静态最优方案遇到扰动后的实际表现”。若原样只跑 B1–B4，核心问题仍缺一个静态实际臂。

## 3. 显式替代设计

本批建议并预注册四臂：`STATIC_FIXED_RECOURSE`、`FULL_ROLLING`、`NO_COOPERATION`、`CARBON_BLIND`。只替换原 B1；B2–B4 的结构语义保持。静态臂冻结扰动前路线，事件后只允许因果补救：删除未出发的取消订单、更新未出发需求、新增或失配订单由其责任车场开独立补救趟；其他未来路线的客户顺序、服务车场和组合都不能变，且不运行路线搜索。这样得到的是静态路线政策在真实扰动下的可执行成本，不是假装不服务新增订单，也不是后见全知下界。

50c 和 100c 的扰动前方案逐种子直接复用 E3 已封存 JOINT 保存解，不重跑 E3。150c 没有当前 E3 的封存 JOINT 结果，因此只复用 foundation 冻结的 mismatch00 common initial solution；150c 只能作压力稳健性证据，不能冒充 E3 的 150c 协同延伸。

种子固定为 1–10。每规模只有五条冻结事件流，故采用结果盲映射 `stream_seed=1+((algorithm_seed-1) mod 5)`，使每条流恰好使用两次。冻结单位是已出发整趟路线；已完成/进行中路线、其客户、已开始充电、物理车辆归属/类型/可用时刻/剩余电量全部不可撤回。事件只能看到当前触发前已出现的信息。

预算先运行 50c、seed 1、stream 1、`FULL_ROLLING` 第一阶段的长收敛探针。探针每个搜索 pass 上限 800，完整记录严格候选 best-so-far；取同状态 reference 与主搜索最后改进评价数的较晚者向上取整到整百。若最后改进超过 720，按预注册只扩一次到 1600；超过 1440 则停止请求预算决定。正式每阶段总 cap 为 reference 与主搜索各占一半后的合计，静态臂无路线搜索，实际消费自然低于同一 cap。预算是上限而不是必须用满的配额。

## 4. 预注册指标与停止线

主量定义为：静态恶化 `100×(C_static−C_nominal)/C_nominal`；动态相对静态节省 `100×(C_static−C_full)/C_static`；动态挽回率 `100×(C_static−C_full)/(C_static−C_nominal)`，分母为零时记空值。表格一行一算例、各臂并列，报告 Best、Avg、Gap%、车辆数、墙钟和实际评价数。

三机制参与证据分别为：事件后出现相对于冻结 owner 的新跨场责任重分配；至少一个成员的累计利润随事件或相对同状态基准发生变化；至少一个未锁充电动作离开最早可行时刻，且 FULL_ROLLING 的充电加权碳强度低于 CARBON_BLIND。没有发生就报告 false，不以候选“技术上可构造”替代实测参与。

任一受保护哈希漂移、冻结事件/输入漂移、客户守恒失败、独立成本或利润闭合失败、实际评价超 cap、冻结执行状态被改写、China81 新增节点落入欧氏距离回退、崩溃或非有限账本，立即停止并形成 HALT 交付，不在正式搜索后修补继续。

## 5. 探针启动故障与终态

零搜索预检先通过：解释器为仓库冻结的 PyVRP 0.12.2 环境，四个线程变量均为 1，系统内存压力显示 57% 可用，1 分钟负载约 2.26；15 条流、375 个事件和 15 份派生 owner 映射全部闭合。六个受保护文件哈希与任务起点完全一致。

随后启动预注册的 50c、seed 1、stream 1、FULL_ROLLING 第一阶段长探针。入口在 `current_sources()` 组装审计来源时读取 `bundle.source_paths["instance_json"]`，但当前 China81 bundle 的真实键为 `catalog`、`nodes`、`orders`、`road_matrices`、`tariff_carbon_calendar`、`vehicle_parameter_lock`、`finite_fleet_authority` 和 `facilities`，不存在 `instance_json`，因此抛出 `KeyError: 'instance_json'`。调用栈发生在 `probe.run_probe_arm()` 之前；`probe/` 无任务结果、`budget_lock.json` 不存在，完整候选评价数精确为 0。

这是启动器真技术故障，不是判据过严，也不是合法 null objective。按本任务“崩溃立即停、不自行修复后继续”的规则，未把键名改为别的来源，也未重启探针。监控合同本身还存在一个次要路径配置问题：其相对保护路径按配置文件目录解析，形成重复目录；不过运行器在崩溃前独立执行的 `verify_protected()` 已验证六个受保护哈希，故不影响“哈希未漂移”这一事实。该监控配置问题同样未在本批修后重启。

## 6. 本批能答与不能答

能确认的只有资产和接口事实：三规模各五条流确实冻结且可精确回读；新增/取消/需求变化事件构成和数量如第 1 节；严格旧动态框架、China81 E3 保存解和 donor 道路克隆存在可设计的桥接路线；原始 B1 不能回答静态方案受扰后的因果实际表现。

不能回答的包括：静态成本恶化比例、动态挽回比例、Best/Avg/Gap%、车辆数、时间和实际评价表，以及事件后跨场责任、成员收益、碳感知充电是否真实参与。`done.json` 中三个机制布尔量写为 false 仅表示 `NOT_OBSERVED_BECAUSE_NO_FORMAL_RUN`，不能解释为实验证明机制没有参与。E3、E4、E5、E6 封存结果均未改写或重跑。
