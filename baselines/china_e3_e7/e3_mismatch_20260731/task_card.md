# E3-MISMATCH-RESTART-20260731 任务卡

目标：独立复核 China81 全部 81 个实例的行政责任车场与有向道路最近车场错配，在全部自然非零错配实例上预注册并运行 IND / ZONE / JOINT 三臂结构对照。

输入：

- `data/ChinaInstances/china81_stage2_static_inputs_corrected_v3_20260723/`
- `data/ChinaInstances/china81_local_directed_matrices_corrected_v10_20260723/`
- `data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723/`
- `data/ChinaInstances/china81_finite_fleet_authority_v1_20260723/`
- `baselines/china_e3_e7/e3_zone_joint_20260731/` 的已认证搜索入口与硬锁筛选修复

允许改：本交付目录内新建的审计、预注册、运行、检查、监控和报告文件；任务完成后的强制交接记录面。

禁止改：

- `solver/src/setp_solver/cost.py`
- `solver/src/setp_solver/check.py`
- `solver/src/setp_solver/search/evaluation.py`
- `baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py`
- `baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py` 的搜索语义
- `baselines/china_e3_e7/e3_zone_joint_20260731/` 及更早目录中的任何真实文件

运行纪律：搜索前先写 `pre_registration.json`；种子 1--10；完整候选评价预算为上限；合法不可行与 `FILTERED_HARD_HOME_DEPOT_LOCK` 正常计入消费；只有技术错误 HALT；最多 2 workers；一个实例完整落盘后再进入下一个；文件枚举排除 `._*`、缓存和监控运行态。

验收：81/81 输入审计闭合；非零错配实例集合可复现；三臂全部预定单元有逐解计划、完整 trace、独立复算和全分母汇总；四件套、`report.md`、干净哈希清单齐全；`done.json` 最后写入。

停止条件：任一受保护哈希漂移；`route_pool_sp.py` 或 `epochal_hgs.py` 搜索语义变化；预注册前启动搜索；真技术错误；输入或独立证书不闭合。

