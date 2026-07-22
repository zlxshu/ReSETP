# S5-REV-V3 版式与完整性修订任务卡

本任务只从已封存的 S5 v2 产物和 P1/S4 证据确定性生成 v3 文件，不运行求解器，不修改 raw ledger、witness、评价器、统计检验输入或主 TeX；v2 文件与 v2 artifact_hashes.json 必须保留。

修订内容为：表5补入 PyVRP-HGS 母体 Best/avg 误差列，所有算法指标统一为相对 BKS 的误差百分比，按 P1 decision.json 的 avg_row_error_pct 生成 Best 平均行并补入封存 P1 raw 的十种子平均误差列，逐行最小误差加粗；表6每行（含 Min/Avg/Max）只加粗最低成本，CPU 不加粗；China81汇总表的 Best 与 avg 分别逐行加粗最低值；表4合计装载率改为路线最大实际装载量之和除以车辆容量之和。

表4其余字段、表6/China81/配对检验/图4数值必须与 v2 一致。AppleDouble 侧车文件不进入 hash 清单；若发现则标记 HASH_CONTAMINATED_APPLEDOUBLE，清理后重算 hash。
