# 当前源码保存解重放兼容性诊断

状态：`HALT_DIAGNOSTIC_CURRENT_SOURCE_REPLAY_NON_EQUIVALENT`。

- `formal_result=false`；未启动搜索、未改变正式参数、未修改任何正式结果。
- 重放保存解：3015；E3 不可检查：1（没有完整保存 solution）。
- 逐解失败或 HALT：6；绝对容差：1e-06。
- 六份 E2 HALT 源于锁定 140.41 kWh 与当前 77.28 kWh 电池契约不同；其保存 action 在锁定曲线下时长误差为 0，不归因于 E5。
- 判断范围仅为当前 `cost.py`/`check.py` 对保存解的合法性和记分兼容性。
