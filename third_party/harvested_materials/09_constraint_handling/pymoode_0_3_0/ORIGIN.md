# pymoode 约束排序取件说明

- 上游项目：`mooscaliaproject/pymoode`
- 上游版本：`0.3.0`
- 上游地址：<https://github.com/mooscaliaproject/pymoode/tree/0.3.0>
- 许可证：BSD-3-Clause，原文见 `upstream/LICENSE`
- 保留文件：约束排序与拥挤度生存选择的实现、配套度量和许可证。
- 对应问题：根因 2；它把各个约束作为向量比较，而不是先把 kg、m³、秒、kWh、车辆数和 CNY 相加。
- 接入边界：该实现属于 pymoo/pymoode 的人口生存选择，不是当前 HGS 的单值 `penalised_cost` 回调；原样采用会替换种群选择结构，不能当作一行罚分公式直接嵌入。

