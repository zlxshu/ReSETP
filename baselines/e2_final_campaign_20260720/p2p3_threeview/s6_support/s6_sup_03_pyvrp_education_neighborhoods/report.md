# S6-SUP-03 PyVRP 0.12.2 教育邻域源码审计

机器判定：`PASS_S6_SUP_03_PYVRP_NEIGHBORHOOD_AUDIT`。

审计只读取冻结 PyVRP 0.12.2 安装包、其 pyi/运行时文档和本项目 HGS 调用；没有修改环境或运行求解器。完整清单在 `pyvrp_education_neighborhoods.md`，逐算子证据在 `operator_audit.csv`。

结论：本代表题实际加入 Exchange10/20/11/21/22、SwapTails、SwapRoutes、SwapStar；RelocateWithDepot 在 supports(data) 中返回 False。项目没有自定义删掉默认算子，但使用默认 40-客户 granular neighbourhood，属于候选边裁剪。
