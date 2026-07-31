# E3-ZONE-JOINT-COMPARISON-20260731 正式收口

状态：`COMPLETE`。权威目录：
`baselines/china_e3_e7/e3_zone_joint_20260731/`。

## 输入与科学口径

- China81 没有字面 `registered_depot` 列；loader 已把客户 `city` 确定性映射到
  同城唯一车场，形成 `customer_home_depot`。该行政归属与有向道路最近车场在
  两题完全相同：50c 为 0/50 错配，100c 为 0/100 错配。
- 因 IND 与 ZONE 是同一输入，本轮依用户裁决只跑 ZONE 分区配送与 JOINT 联合
  配送；IND 未运行。若以后要测空间组织价值，距离次近车场、更细行政区划或容量
  均分都属于新的科学定义，必须另行批准。
- 四份输入均以冻结 C++ First-Fit 构造，并由 Python `_pack_depot` 逐组复算；
  两臂使用共同种子和共同初始路线骨架。旧故障前 18 个 PASS 目标值没有进入本轮
  任何效应、方向或显著性判断。

## 跨场候选技术错误及修复

- 硬锁在
  `baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/pyvrp_adapter.py`
  第 146 行开始通过客户车场归属容量维施加，并在第 261 行开始由各车场车辆的匹配
  容量承接。
- 旧 14/14 个技术错误都来自 `epochal_hgs.py::_run_exact_epoch` 的
  `terminal_population_archive`：原生 HGS 终端种群候选经完整 China81 补全后仍
  跨场，旧路径把正常硬锁拒绝抛成 `ValueError`。trace 没有保存单算子祖先，故
  不能唯一归因于 Exchange11 或其他算子。
- 修复只在完整补全后把硬锁跨场候选写成
  `FILTERED_HARD_HOME_DEPOT_LOCK`，计入实际候选消费并在进入精英/路线池前排除；
  没有修改搜索算子、随机流、JOINT 分支或 `route_pool_sp.py` 搜索语义。50c seed 3
  定向回归过滤 2 个候选，最终跨场服务 0、违规 0。
- JOINT 50c seed 1、cap 400 的改前/改后实跑均消费 331 个完整候选，解哈希均为
  `159dc8289888437ac1e1e3e7264d06641d933941b307ca488ee526e0dacf3985`，完整目标
  浮点位均为 `0x1.1e2a31f630958p+11`，完整目标规范哈希均为
  `d27d9e0ec657701f5a2aa87b4c01878778c058264156cee026505dd802e6be9b`。

## 正式矩阵与结果

- 先完成 50c，再完成 100c；两题 × 两臂 × seeds 1--10，共 40/40 PASS。
  共同完整候选上限为 400，2 workers；实际消费均不超过上限，技术错误候选 0。
  独立 checker 逐解复算 40/40 通过，完整目标/解哈希不一致、ZONE 跨场违规、预算
  超限和保护哈希漂移均为 0。
- 50c：ZONE/JOINT 平均成本 2341.446790/2288.231338，JOINT 节省
  2.272759%；车辆 9.0→8.0，距离增加 28.035662%，碳排增加 4.044894%，满足硬
  时间窗客户均为 50。
- 100c：ZONE/JOINT 平均成本 4739.691422/4706.839925，JOINT 节省
  0.693115%；车辆 18.0→17.2，距离增加 12.176611%，碳排增加 1.182531%，满足硬
  时间窗客户均为 100。
- 两条算例行等权总体降本 1.482937%，低于目标期刊同类 3%--6% 参照量级。结果支持
  “行政分区已与地理最优重合后只剩有限降本协同”，同时必须保留距离与碳排上升的
  权衡，不能写成全面改善。

## 终端与保护边界

- `done.json.status=COMPLETE`，`formal_units_run=40`，
  `cross_site_bug_fixed=true`，`joint_semantics_unchanged_proof=true`。
- 哈希清单 167/167 独立复核通过；交付目录 `._*` 为 0，缓存与监控运行态不入清单。
  `cost.py`、`check.py`、`search/evaluation.py`、`route_pool_sp.py` 哈希未变；旧
  `e3e6_formal_20260729`、`e3e6_inputs_20260730`、`e3_structural_20260731`
  真实文件没有删除或覆盖。
