# V13-MDVRPTW-28 比较基础零搜索报告

## 结论

判定：`PASS_MDVRPTW_V13_COMPARISON_FOUNDATION_ZERO_SEARCH`。

- 作者原始 28 题与 PyVRP 规范化 28 题逐字段语义核对全部通过；
- 当前 28 个 BKS 路线由 PyVRP 官方解析器与项目独立解析器双重验真；
- 2026 MDFIHA 论文 Table A8 的 VCGP、MDFIHA、MDFIHA-ETGA 逐题值
  28/28 抽取；
- 开发 6 题、确认 6 题、封存 16 题及代表题 `PR17A`
  均由结果盲结构规则生成；
- 搜索评价 0、求解器调用 0、China81 未读未跑、阶段二未启动。

## 诚实边界

这个 PASS 只说明题、对手、最好解和划分方式已经闭合。它不说明本文算法已经赢，
也不放行性能搜索。下一步最多允许做关闭增强时逐位退回母体的接线检查。

## 冻结版本

- PyVRP/Instances：`1cf23a5969fabf23c80f8002e42ed501a47aca61`
- PyVRP：`v0.13.4` / `18815548d04a90a0e5eea2a0bed53a81ea9d2d49`
- 本次校验环境 PyVRP：`0.12.2`
- 作者原始压缩包 SHA-256：`478f6db04f9814284e24cf266a1126c536f4d79b50676e257a9348900aff8aa7`
