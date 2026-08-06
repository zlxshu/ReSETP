# Duty-HGS 来源和独立性说明

版本：v2，2026-08-07。

本目录是静态技术试跑候选，不是正式算法性能结果。

## 上游来源

upstream/PyVRP-0.12.2/GeneticAlgorithm.py 原样复制自本机 PyVRP 0.12.2 安装环境，SHA-256 为 c7c8c068a1fbd42d341e3dddda66b703a8d99ea9236a19ad5fd300d8963470fe。

upstream/PyVRP-0.12.2/LICENSE.md 保留原 MIT 许可证，SHA-256 为 d9484b4905b1479240a99cdbe96b4f34d9a2c17347000d961819f8b177f3365b。METADATA 保留版本、项目地址和许可证信息。

这些文件只用于核对成熟 HGS 的控制思想和建立母体基线，不是主算法的运行依赖。

## 主算法独立实现

主运行链不导入 PyVRP 的 GeneticAlgorithm、Population、PenaltyManager、Crossover、LocalSearch 或编译扩展。原型独立实现：

- model.py：实体车整日班表、趟次、充电会话和锁定承诺；
- evaluation.py：项目完整模型评价、增量缓存和真值哨兵；
- population.py：可行与不可行子种群、多样性、选择和自适应罚值；
- crossover.py：整日班表交叉；
- repair.py：重复、遗漏和未服务客户修复；
- operators.py 与 charging.py：客户、趟次和充电候选动作；
- education.py：完整评价驱动的局部教育；
- runner.py：选择、交叉、修复、教育、入群、轨迹和有类型终止；
- contracts.py：候选状态、动作账目和运行结果合同。

旧 control.py 只覆盖第一段控制骨架，已经由 runner.py 的完整运行链取代并删除。

## 项目积淀的复用边界

原型复用 setp_solver 中已经存在的 Solution、prepare_multitrip_solution、check_solution、evaluate、calculate_depot_profits 和 China81 车队限制。复用的是用户现有模型与评价事实，不是第三方算法实现。受保护的正式 solver 文件没有修改。

feedback.py 和 technical_feedback_probe.json 只保留为离线病灶诊断。它们当前不被 runner.py 导入，也不承担算法创新主张。

## 当前主张边界

当前可以核验：独立运行链已经接通；搜索对象是实体车整日班表；每个候选通过项目完整模型评价；动态锁定承诺受到保护；轨迹、来源、评价次数、真实入群和异常终止可以追溯。

当前不能主张：优于充分收敛的 PyVRP 0.12.2 HGS；达到公开算例强对手水平；反馈机制有效；私有三大实验和五因素已经产生论文效应。以上必须由用户批准后的公平算法对比和后续实验回答。
