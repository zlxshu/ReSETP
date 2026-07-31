# E7 China81 动态实验探针启动 HALT（2026-07-30）

权威目录：`baselines/china_e3_e7/e7_dynamic_20260731/`。

三规模各五条冻结事件流已核实：50c 每流 12 个事件（5 新增、2 取消、5 需求变化），100c 每流 25 个（10、5、10），150c 每流 38 个（15、8、15）；15/15 JSON/TSV 可逐字段精确回读，共 375 个事件。所有新增订单均为同一实例既有 donor 的精确位置、需求和服务时间克隆，因此可通过克隆 donor 的有向距离行/列及 CV/EV road profile 接入，禁止欧氏回退。

原设计四臂为终局全知静态、完整滚动、关协同、碳盲。终局全知静态不经历不可撤回执行，不能回答当前用户要求的“静态方案受扰后实际表现”；本批在任何搜索前显式预注册替代为 `STATIC_FIXED_RECOURSE`，其余三臂语义保持。50c/100c 计划复用同 seed 的 E3 JOINT 封存解，150c 只用 foundation common initial，后者不能冒充 E3 扩展。

零搜索预检通过：15 条流、375 事件、15 份派生 owner、冻结 Python/线程环境、系统内存压力 57% 可用、六个保护文件哈希均闭合。随后 50c seed1 stream1 FULL_ROLLING 长探针在进入 `probe.run_probe_arm()` 前崩溃：适配器读取 `China81Bundle.source_paths["instance_json"]`，而当前 bundle 无此键，抛 `KeyError: 'instance_json'`。完整候选评价为 0，预算未选，三个规模正式单元均为 0。

按用户“崩溃立即停、不自行修复后继续”规则，未修键名、未重启。监控配置另有相对路径按配置目录重复解析的问题，但运行器自身的保护哈希复核已通过。终态 `HALT_PROBE_STARTUP_KEYERROR_INSTANCE_PATH`；静态恶化、动态挽回与三机制参与均未观测，不得把 done 中的 false 写成机制无效。继续必须由用户另行授权，在新 attempt 目录先修并做零搜索接口测试，不能覆盖本 HALT 包。

# 2026-07-30 E7 v3 150c 并行执行终态

用户随后明确授权正式 E7 运行。`e7_dynamic_v3_20260731` 的 150c 规模已完成
40/40 单元，全部为合同允许的 `LEGAL_INFEASIBLE`；完成标志
`formal/150c/scale_complete.json` 状态为 `COMPLETE_150c`，marker SHA-256 为
`3c5b1314f5e8e30410529f1652356f96f2bc850fd0c77bd45c7f8a5456691c68`。
预算仍为每 search pass 上限 600、每阶段上限 1200，四臂、种子 1--10、事件流、
算例和 null objective 口径均未改。

运行先以 4 workers 启动；外部现场同时把 100c 扩至 6 workers，10 路并发造成
负载超过 20、单 worker CPU 约 60%，故只将 150c 降为 2 workers，总并发恢复为
8。监控的 1200 秒 stale 门曾误停仍高 CPU 的长单元，按既有 3200 秒以上单元证据
改为 7200 秒后，对同一 PGID SIGCONT 并继续，没有重启实验或改变在途状态。

100c 在 150c 启动前现场实际已有 16 个非 AppleDouble 任务文件，终验 SHA-256
16/16 不变；终验时为 34/40 且六个计算 worker 仍为 `RN`。详细运行治理和 PID
75334 处置边界见 `parallel_150c_report.md`。
