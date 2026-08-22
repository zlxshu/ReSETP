# pymoo 约束处理取件说明

- 上游项目：`anyoptimization/pymoo`
- 上游版本：`0.6.2`
- 上游地址：<https://github.com/anyoptimization/pymoo/tree/0.6.2>
- 许可证：Apache-2.0，原文见 `upstream/LICENSE`
- 保留文件：个体约束违规计算、正规化工具、把约束违规并入目标的官方实现和许可证。
- 对应问题：根因 2，约束向量、违规汇总和正规化的候选开源原料。
- 接入边界：代码依赖 pymoo 的 `Individual`、`Population` 和 `Problem` 数据合同；它没有读取本项目 `FullEvaluation` 或 Duty 的接口，不能原样替换当前逐候选罚分回调。

