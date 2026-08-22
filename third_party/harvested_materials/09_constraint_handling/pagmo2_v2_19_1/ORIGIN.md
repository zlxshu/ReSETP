# pagmo2 约束自适应罚项取件说明

- 上游项目：`esa/pagmo2`
- 上游版本：`v2.19.1`
- 上游地址：<https://github.com/esa/pagmo2/tree/v2.19.1>
- 许可证：GPL-3.0 与 LGPL-3.0，原文保存在 `upstream/`
- 保留文件：`cstrs_self_adaptive` 的实现、声明、依赖声明、官方测试和许可证。
- 对应问题：根因 2，不同约束量纲不能直接共用一个 `100/unit`。
- 可直接采用的行为：在整个人口上逐约束取得违规最大值，先把各约束正规化，再计算个体不可行程度并自适应施加罚项。
- 接入边界：该实现接收 pagmo 的完整 `population` 和固定约束向量；当前项目只把单个 `FullEvaluation` 交给 `penalised_cost`。本取件不包含两者之间的项目接口，因此当前不能直接施工。

