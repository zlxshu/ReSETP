# PyVRP 官方空路线搜索取件说明

- 上游项目：`PyVRP/PyVRP`
- 上游地址：<https://github.com/PyVRP/PyVRP>
- 许可证：MIT；两个版本的许可证原文分别保存在各自 `upstream/LICENSE.md`
- 取件版本：`v0.12.2` 与 `v0.14.0`
- 保留文件：两个版本的 `LocalSearch`、`SwapTails` 及对应官方测试。
- 对应问题：根因 7，局部搜索缺少进入空闲车辆的方向。
- `v0.12.2` 原料：`Exchange`/节点算子可向空路线搬移节点；`SwapTails` 可把最后一趟的后缀移向另一条路线；首轮为了少用车辆而跳过空路线搜索。
- `v0.14.0` 原料：官方 `LocalSearch.cpp` 已取消首轮跳过，逐轮调用 `applyEmptyRouteMoves()`；官方测试给出行为依据。
- 接入边界：这些原料能恢复节点、短段和最后一趟后缀进入空车辆，不能声称覆盖任意较早趟的前缀/后缀搬移。项目 `DepotSplit` 不在这两个上游版本中，不能冒充官方原件。

