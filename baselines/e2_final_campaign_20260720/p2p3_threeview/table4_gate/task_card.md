# S4 表4路径明细任务卡

仅接受 S3 `PASS_S3_REPRESENTATIVE` 后的代表题 MV-HGS-SP 十次运行。按 exact cost 选最优 seed（成本相同时按 seed 字典序），从 S3 witness 复原 `Solution`，再独立调用 `check.py`、`cost.py` 的路线/调度/评价入口以及 `exact_china81_score` 复算；不手填任何列。

输出逐路线 `路径 | 距离(km) | 成本(元) | 时间(h) | 油耗(L) | 电耗(kWh) | 碳排放(kg) | num(满足时窗客户数) | 装载率(%)`，另保留 EV 行驶电耗和检查状态审计列，并生成均值行、合计行及最优 witness 副本。任一独立复算不一致、检查违规或字段缺失，写 `HALT_S4_*` 停止。
