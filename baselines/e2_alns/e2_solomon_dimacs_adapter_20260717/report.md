# Solomon/DIMACS 零搜索适配审计

判定：`PASS_SOLOMON_DIMACS_ZERO_SEARCH_ADAPTER_GATE`。

核对 56/56 个 Solomon 100 客户算例；本轮路径搜索评价次数为 0。
六类数量：{'C1': 9, 'C2': 8, 'R1': 12, 'R2': 11, 'RC1': 8, 'RC2': 8}。
距离口径为 `floor(10 * Euclidean) / 10`，车辆数为上限，目标仅为总距离。
BKS/最优标志来自冻结的 DIMACS 控制器 `genScript1.sh`；56项均标记为已证明最优。
本地压缩包内算例逐项与冻结控制器版本作字节比较。

该门只证明数据、BKS、目标和解析口径一致，不证明本文算法性能，也不授权在E7运行期间修改共享内核。
