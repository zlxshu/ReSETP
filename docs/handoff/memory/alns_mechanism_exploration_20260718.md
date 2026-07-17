# ALNS分机制算法探索记忆（2026-07-18）

## 硬边界

EA-001只批准研究、取证、候选设计和隔离微探针，不批准合入正式ALNS、修改`winner.py`、干预E7、改变模型/单位/物理语义、启动正式实验或形成论文创新结论。任何新方法必须由用户逐项批准，实施后还须同步机器合同、代码、测试、HANDOFF、memory和证据包。

## 主题1：混合车队、车型选择、SOC与非线性补能

两轮研究证据包为`docs/handoff/algorithm_exploration_20260718/fleet_charging/`，机器判决固定为`EXPLORATION_ONLY_AWAITING_USER_APPROVAL`，正式搜索评价次数为0。

候选`FC-C01`至`FC-C05`分别是：Hiermann联合路线—车型算子；Froger/frvcpy固定路线非线性补能精确oracle；PyVRP异构车队高性能局部搜索工程参照；Wang HEVRP-NL逐车型评价、补能评估、ReplacePath/VND/路线池架构；自研车型—模式后悔修复与分层非线性补能oracle（VMR-NL）。EA-001下可继续的隔离探索顺序是`FC-C02 → FC-C05 → FC-C01 → FC-C04`，`FC-C03`主要作为实现和基线参照；这一顺序不构成正式实施批准。

frvcpy与PyVRP微实例只通过功能/接口门，不证明相对当前ALNS的性能。VMR-NL的新颖性尚未证明；在独立文献审查和消融前不得写作论文创新。

## 主题1独立原型进展

EA-001授权下已在`baselines/algorithm_prototypes/fleet_charging_20260718/`完成FC-C02与FC-C05隔离原型。FC-C02只通过懒加载适配层调用`frvcpy 0.1.1`，并由独立逐弧SOC/非线性时间回放复算；FC-C05只实现可注入评分、SOC实例和oracle的VMR-NL接口桩与人工微例。预算0/1/2/5、活性、完整评价/oracle/cache/reference分账和最终5项单测均通过，五件记录齐全。首轮测试的两项开发错误已保留在metadata/report。

原型判决为`PASS_ISOLATED_FUNCTION_PROTOTYPE_ONLY`。正式CNY目标、批准的非线性SOC曲线、初始/跨趟SOC、桩容量排队、接受规则和正式完整评价适配均未裁决；不得把抽象微例参数写入中国实例，不得形成性能、显著性或新颖性主张。正式合入、模型变化、正式实验和论文主张仍需用户批准。

## 预算与审批纪律

G0闭合前仅允许预登记的预算0/1/2/5功能探针。所有候选必须分别记录完整评价、cheap filter、精确非线性oracle、缓存命中、路线池/集合划分求解和外部基线调用；不得用缓存命中或启发式筛选掩盖正式评价预算。车型语义、SOC安全边界、非线性充电曲线、充电站可达性、目标函数、接受规则或单位发生变化时，必须停止并另建审批单。
