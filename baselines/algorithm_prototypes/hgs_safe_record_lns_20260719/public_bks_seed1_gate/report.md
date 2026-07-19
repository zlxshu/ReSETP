# HGS-SAFE-RECORD-LNS-04 原始 Solomon+BKS seed1门

- 判决：`STOP_SAFE_RECORD_LNS_INTEGRITY`
- 两臂均单线程、共同seed1、共同确定性初解、每臂五秒。
- BKS在12个求解任务结束后才关联。

|实例|BKS|纯HGS|安全记录LNS|当题最好|
|---|---:|---:|---:|---|
|C105|10/828.94|10/828.94|10/828.94|hgs_safe_record_lns_04, pyvrp_0_12_2_hgs|
|C204|3/590.60|3/590.60|3/593.93|pyvrp_0_12_2_hgs|
|R108|9/960.88|9/1012.16|9/1012.16|pyvrp_0_12_2_hgs, hgs_safe_record_lns_04|
|R207|2/890.61|2/911.74|2/909.50|hgs_safe_record_lns_04|
|RC104|10/1135.48|10/1172.32|10/1177.84|pyvrp_0_12_2_hgs|
|RC204|3/798.46|3/845.25|3/845.25|hgs_safe_record_lns_04, pyvrp_0_12_2_hgs|

逐题胜平负：1胜/3平/2负。

只有零负且至少两胜才允许冻结代码追加seed2/3；否则候选立即停止。
