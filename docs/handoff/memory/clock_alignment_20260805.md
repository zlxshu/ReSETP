# T15 时钟对齐与车场窗口模式（2026-08-05）

`FACT`：排班证书 `route_timing/build_multitrip_certificate` 是本任务唯一权威时钟。生成侧路线时钟、最终车场返场锚点和 China81 首趟窗口已接入该口径；公共站占用被计入最终返场锚点。

`FACT`：显式车场窗口参数为 `prev_night`、`same_day_predeparture`、`full_gap`。China81 补全默认 `same_day_predeparture`；profile 由已有日历按实际日期键读取，不插补新数据。三模式不在本任务中择优。

`FACT`：T15 回归结果为定向 7/7、阳性 3/3、T10 合法 witness 18/18；全量 `906 passed / 1 skipped / 6 failed`，相对 T10 `898/1/14` 无新失败。受保护三文件 SHA-256 前后相同。

`INFERENCE`：`prev_night` 在 `cn-jjj-10c-01-V2-LOCATIONS` 有限车队 smoke fixture 上未找到满足车队上限的组合；这不是模型硬不可行证明。

权威证据：`docs/handoff/clock_alignment_20260805/report.md`、`regression_results.json`、`artifact_hashes.json`。
