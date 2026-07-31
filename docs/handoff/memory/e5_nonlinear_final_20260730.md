# E5-NONLINEAR-CHARGING-FINAL-20260730：已认证 v4 单元无搜索终局聚合

日期：2026-07-30

权威目录：`baselines/china_e3_e7/e5_nonlinear_final_20260730/`

终态：`COMPLETE`

科学标签：`MECHANISM_BUT_TIE`

## 授权与数据边界

用户明确将 v4 的 `HALT_E5_V2_CERTIFICATE_DENOMINATOR:80!=40` 裁定为外置盘
AppleDouble 导致的文件枚举误报，并授权新建 final 轮次修复工具层枚举后，只从
v4 已落盘的 40 个 plan、40 个独立 certificate、
`independent_verification.json` 和 `raw_runs.csv` 聚合。旧 v1/v2/v3/v4
真实文件不得覆盖，任何搜索不得重跑。

本轮实际 `search_reruns=0`、`search_processes_started=0`、
`independent_checker_reruns=0`。聚合脚本只使用 Python 标准库，不导入 solver、
checker、route pool 或搜索 runner。

## 枚举修复与清理

`run_e5_nonlinear_v2_20260730.py` 的旧封存树、certificate loader 和 manifest
递归枚举，v3/v4 的 task-status loader，以及 v2 checker 的 plan loader，均改为
排除文件名以 `._` 开头的旁文件和路径中的 `__pycache__`、`.pytest_cache`。

清理前 v4 目录有 262 个真实文件和 68 个 `._*`；真实 plan/certificate 各 40，
certificate 旁文件 40，plan 旁文件 0。只删除 68 个精确旁文件后，真实文件仍为
262、plan/certificate 仍各 40、旁文件为 0。清理前后排序后的真实路径列表和逐文件
SHA-256 列表逐字节一致。

## 一致性门

聚合前全量复核 40 个 plan 内容 ID、40 个 certificate 内容 ID、证书声明的 plan
文件 SHA-256、solution ID、40 个 task status、v4 `raw_runs.csv` 的 40 个键与
数值、每个 seed 的共同初始解，以及 `independent_verification.json` 的
`PASS certificates=40/40`。不一致项为 0。

`cost.py`、`check.py`、`search/evaluation.py`、`route_pool_sp.py` 的当前
SHA-256 与 v4 `source_lock.json` 一致。修改只涉及枚举代码和新聚合器。

## 四个科学端点

NL90 完整可行率为：50c 10/10，100c 10/10，总体 20/20（100%）。

在 L100 下完整可行、固定路线/车辆/站点/开始时刻/充电量后回放 NL90 物理即不可行
的假可行解为：50c 0/10，100c 0/10，总体 0/20。因假可行分母中的事件数为 0，
充电时长/功率、SOC/电量、时间窗、容量及其他原因计数均为 0，也没有重叠原因组合。

两臂在共同 NL90 物理下均可行的配对为 20/20。每个 seed 用
`100*(NL90 plan common-NL90 cost - L100 plan replay common-NL90 cost) /
L100 plan replay common-NL90 cost` 计算，两个算例及总体的均值、中位、最小和最大
均为 0.000%。

证书共持久化 196 个会话。50c 的 NL90−L100 时长差均值/中位/最大为
316.145/0/1264.582 s，正差 20/80；100c 为 174.425/0/1264.582 s，正差
16/116；总体为 232.270/0/1264.582 s，正差 36/196。总体起始 SOC
均值/中位/最大为 4.878/0/29.247%，结束 SOC 为 46.953/37.033/100%。
会话只作嵌套描述性观测，不冒充 196 个独立实验样本。

## 正式表与结论边界

期刊式主表按一行一算例、两臂并列，报告 10 次运行的 Best、Avg、Gap%、最佳/平均
物理车辆数、平均时间、实际评价数均值与范围、可行率。50c 两臂均为
Best=2288.011935、Avg=2288.231338、Gap=0.009589%、8/8.00 辆、10/10 可行；
100c 两臂均为 Best=4692.922895、Avg=4706.839925、Gap=0.296554%、
17/17.20 辆、10/10 可行。

非线性充电确实延长部分会话，但没有在本批次中改变完整可行性或成本。允许写：
“在所选 50/100 客户算例和当前 SOC 暴露范围内，线性近似没有高估可行性，非线性
机制效应很小。”不得外推到高 SOC 暴露或更紧时窗场景，也不得为放大机制而挑种子、
挑单元或改判据。

## 终局完整性

final 目录含四件套、`report.md`、正式表、逐配对成本、原因与重叠表、196 行
会话表、会话分布和 v4 source inventory。`artifact_hashes.json` 排除自身、
`done.json`、AppleDouble、缓存和监控运行态；13 个 manifest 产物与五个必需文件
哈希独立复核一致。`done.json` 为目录最后写入的真实文件，核心字段为
`status=COMPLETE`、`source_units=40`、`endpoints_answered=4`、
`nl90_feasibility_rate=1.0`、`cost_effect_pct=0.0`、
`false_feasible_count=0`、`search_reruns=0`。
