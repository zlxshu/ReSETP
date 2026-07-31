# E5-NONLINEAR-CHARGING-V4-20260730：null 二义性闭合、正式搜索完成、终端聚合 HALT

日期：2026-07-30  
权威交付：`baselines/china_e3_e7/e5_nonlinear_v4_20260730/`  
根状态：`HALT_APPLEDOUBLE_CERTIFICATE_DENOMINATOR`

## 已闭合的二义性

`epochal_hgs.py` 只在既有三个异常捕获分支增加
`exception_type` 与 `exception_message`，没有改变 try 范围、候选翻译、
完整化、候选顺序、接受规则、评价计数或返回方案。50c-01、seed 1、
L100、cap 1500 的改前/改后指纹逐位一致：最终方案 SHA256
`74bd2c416a88e003167854cb7f2ff30ed05b8734e3974d120d42a09d9f3c1c67`，
完整目标 `2289.318598837748`，331 次去诊断字段评价轨迹 SHA256
`ab12cb197c579c3d282da6531a3b5bd0e81440f3a781f597af9434dbed823063`。
权威证明为
`diagnostics/search_semantics_unchanged_proof.json`。

双臂探针均实际消费 331 次：各 147 个可行候选、184 个合法不可行候选、
0 个技术错误。合计 368 个空目标全部为完整模型抛出的 `ValueError`；
368/368 均以
`China81 route skeleton has no feasible all-CV completion:` 开头，具体为容量和
时间窗违约。候选级原因允许重叠：每臂 112 行含容量、178 行含时间窗、
106 行两者同时出现。`IndexError`、`KeyError`、`TypeError`、未知
`ValueError`、缺失异常诊断均为 0。因此 v3 的“任何 null objective 即 HALT”
判据由证据确认过严；v4 保留 null 行为实际消费数据，只在非空目标上更新 incumbent，
并仅在 `error_candidates>0` 时停止。

## 正式搜索与预算

两臂探针都在 331 次因有限候选耗尽；按向上整百留余量规则，共同正式 cap 锁为
400。全程 1 worker，先完成 50c 后启动 100c。两实例、10 个共同种子、两臂共
40/40 正式搜索单元 PASS；实际消费范围 298--396，全部不超过 cap，所有单元
`error_candidates=0`。每个 seed 的两臂共同初始解哈希一致。50c 与 100c 的
manifest 均已落盘。

独立 checker 随后输出 `INDEPENDENT_CHECK_PASS certificates=40/40`，
`independent_verification.json.status=PASS`。40 个真实 plan、40 个真实
certificate 与逐单元 checker 摘要均保留。

## 终端真故障与证据边界

checker 写入 40 个真实 certificate JSON 时，外置盘同时生成 40 个 AppleDouble
`._*.json`。v2 复用聚合器的 `load_certificates()` 使用未排除旁文件的
`glob("*.json")`，把分母读成 80，并崩溃：
`HALT_E5_V2_CERTIFICATE_DENOMINATOR:80!=40`。

用户已明确规定“崩溃即真故障，立即停，不自行修复后继续”。因此没有修复 glob、
没有清除证书旁文件后重跑聚合，也没有从现有 certificate 补算四端点。四个科学
端点统一为 `NOT_AGGREGATED`，`endpoints_answered=0`；不得把搜索/证书已经完成
推成 NL90 可行率、假可行数量、成本方向或会话时长结论。

HALT 四件套、`report.md` 与最后完成信号 `done.json` 已写齐。
`raw_runs.csv` 含 40 行正式搜索及 checker 摘要，但
`scientific_endpoint_inclusion=NOT_AGGREGATED_DUE_TO_TERMINAL_CRASH`。
哈希清单排除 `._*`、缓存和监控运行态。受保护 `cost.py`、`check.py`、
`search/evaluation.py`、`route_pool_sp.py` 哈希未漂移；旧 v1/v2/v3 目录未覆盖。

## 后续授权边界

若用户希望继续，必须明确批准一个新轮次：修正证书枚举以排除 AppleDouble 后，
从已有 40 个真实证书重新执行终端聚合，或重新跑独立 checker/聚合。当前 v4
`done.json` 是 HALT 终态，不得直接覆盖。
