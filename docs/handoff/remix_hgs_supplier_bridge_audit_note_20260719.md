# ReMIX HGS 供料桥失败与更正

- v1：
  `baselines/algorithm_foundation/remix_hgs_supplier_bridge_20260719`
- v2：
  `baselines/algorithm_foundation/remix_hgs_supplier_bridge_v2_20260719`

v1 的两版本路线和整数距离完全一致，但 PyVRP 0.12.2 在固定两次迭代后尚未找到
第一份可行解，40 条路线存在时间窗或最长路线时长违约。因此 v1 正确判失败，不能
作为供料授权。

开发合同只要求一次零性能的可行路线桥，没有预注册“两次迭代”。v2 不改变算法
参数、题目、种子、取整或验收标准，只把错误的固定两次停止改为
“找到第一份可行解即停，最多五秒”。v1 永久保留作失败现场；只有 v2 通过，HGS
才可进入六题开发候选。
