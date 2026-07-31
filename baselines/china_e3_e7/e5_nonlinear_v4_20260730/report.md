# E5 非线性充电实验 v4：HALT 封口

## 结论

本轮不能签发四个科学端点，终态为 `HALT_APPLEDOUBLE_CERTIFICATE_DENOMINATOR`。正式搜索 40/40 单元均完成，技术错误候选为 0，独立 checker 也明确输出 `PASS certificates=40/40`；但独立证书写盘后，外置盘为 40 个真实 JSON 同步生成 40 个 AppleDouble `._*.json`。旧聚合器使用未排除旁文件的 `glob("*.json")`，把证书数读成 80，并以 `HALT_E5_V2_CERTIFICATE_DENOMINATOR:80!=40` 崩溃。按本轮硬规则“崩溃即真故障，不自行修复后继续”，这里停止，不修改过滤器、不删除证书旁文件后重跑聚合、不从现有证书补算端点。

## 二义性诊断

同 seed、同 cap 的搜索语义指纹在增加纯诊断字段前后逐位一致：最终方案哈希、完整目标、331 行评价轨迹投影均相同。双臂探针共 662 次完整评价，368 行目标为空；368/368 均为完整模型明确报告容量或时间窗违约的 `ValueError`，技术错误 0。L100 与 NL90 各为 147 个可行候选、184 个合法不可行候选、0 个技术错误。因此 v3 的“任一空目标即 HALT”确属判据过严；v4 已把合法不可行保留为实际消费数据，并仅在 `error_candidates>0` 时停。

候选级原因允许重叠：每臂 184 个空目标中，112 行含容量违约，178 行含时间窗违约，106 行同时含两类；具体异常类型、完整消息和实例见 `probe/null_objective_diagnosis.json`、`probe/null_objective_root_cause_summary.json` 和两份完整 search trace。

## 正式搜索与独立复算状态

共同正式预算锁为 400 次上限，来自两臂探针在 331 次候选耗尽后向上取整留余量。50c 完成后才启动 100c；全程 1 worker。

| Instance | Search units | Actual evaluations | Error candidates | Independent check |
|---|---:|---:|---:|---|
| cn-prd-100c-02-V2-LOCATIONS | 20/20 | 313–396 | 0 | 40/40 checker batch total across both instances |
| cn-prd-50c-01-V2-LOCATIONS | 20/20 | 298–376 | 0 | 40/40 checker batch total across both instances |

40 个真实 plan、40 个真实 certificate 和 `independent_verification.json` 均保留。`raw_runs.csv` 记录所有正式单元的 feasible/infeasible/error 构成和 checker 摘要，但 `scientific_endpoint_inclusion` 明确标为未聚合，不能把这些行冒充已签发端点。

## 未回答的科学端点

端点 1 至 4 均标记为 `NOT_AGGREGATED`：没有签发 NL90 完整可行率、L100 假可行数量/成因、共同可行成本变化或逐会话 SOC/时长汇总。这里的“未回答”来自终端聚合崩溃和明确停机规则，不代表效应为零，也不代表已有独立证书无效。

## 冻结边界

`cost.py`、`check.py`、`search/evaluation.py` 和 `route_pool_sp.py` 哈希未漂移。`epochal_hgs.py` 只增加异常类名/消息诊断字段，逐位语义证明为 PASS。旧 v1/v2/v3 目录未覆盖或删除。`artifact_hashes.json` 排除 AppleDouble、缓存、监控运行态及 `done.json`；`done.json` 作为本次 HALT 完成信号最后写入。
