# 算法探索主题3记忆：碳、分时电价与非线性充电

2026-07-18依据EA-001完成两轮研究，证据包为`docs/handoff/algorithm_exploration_20260718/carbon_nonlinear_charging/`，机器判定`EXPLORATION_ONLY_AWAITING_USER_APPROVAL`。本轮只检索、核原文和许可证、设计候选，没有修改正式solver、`winner.py`、E7、单位、模型或正式实验合同。

最高匹配候选是Montoya--Froger--Liang方法链的固定路线非线性充电标签优化器；没有找到许可证明确的作者代码，只能clean-room重实现。MIT的`cspy`适合低摩擦Python隔离原型；PathWyse支持高性能双向标签和自定义非线性资源，但为GPL-3.0-or-later，须先裁决许可证。Cheng第一作者碳感知充电仓库可核，但没有LICENSE，禁止复制。SAP共享容量充电排程为Apache-2.0，但仓库已于2026-07-16归档，只作参考或交叉检查。

自研候选为`DUAL_ORACLE_CARBON_PRICE_CONFLICT_CHARGING`：在相同路线、车辆、曲线、桩容量和时间窗口下分别求价格-only与碳-only充电oracle，用两者分歧构造冲突破坏信号，再以正式联合目标repair。它必须通过非零活性、相对随机选择的同预算优势、碳盲配对和wall-time四类证伪门。

碳贡献必须双层识别。机制层保持算法和物理相同，比较`JOINT_COST_CARBON`与`COST_ONLY_BLIND`；算法层保持正式评价器相同，只开关碳算子。E7碳盲臂保留同一滚动机制、状态继承、合作、公平、非线性物理、价格信号、oracle和预算，只隐藏未来碳信息，最终用同一实现碳曲线结算。

任何原型、单位或状态转换、时间/SOC离散、目标权重、GPL使用和正式接入都需要用户另行批准。建议的待批编号为`EA-001-C3-P1/P2/L1/R1`。

## 2026-07-18 EA-001隔离原型完成

用户随后明确授权本主题隔离原型，因此上一段“任何原型需要另行批准”的表述由本节纠正：EA-001允许独立目录内的人工微例、预算0/1/2/5功能/活性/计数探针；正式算法接入、模型/单位/参数变化、目标语义、离散精度、正式实验和论文主张仍须逐项批准。

原型目录为`baselines/algorithm_prototypes/carbon_nonlinear_charging_20260718/`。人工穷举oracle和clean-room前向时间—SOC标签原型在预算0/1/2/5下逐位一致；无限预算带支配的标签结果与完整穷举最优一致，支配、跨非线性曲线分段和跨时变价格/碳槽积分均实际激活。判决=`PASS_ISOLATED_FUNCTION_ACTIVITY_ACCOUNTING_ONLY`，只支持功能、活性和计数闭合，不支持算法性能或正式NL→NL结论。

MIT `cspy==0.1.2`仅对由clean-room回放编译出的16个可行微计划有限图做最短路交叉检查并通过；它没有被写成原生非线性资源扩展。分发版本0.1.2与模块`__version__=0.1.0`的不一致已保留。一次性仓库内虚拟环境在探针后完整删除，最终目录不含环境、AppleDouble、`__pycache__`或pytest缓存。

五件记录、源码和测试全部在上述原型目录；9项pytest与Ruff通过。未导入或修改正式solver、`winner.py`、E7、模型、单位、参数或正式合同。任何正式接入仍需用户批准。
