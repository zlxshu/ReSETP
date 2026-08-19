# MEM-DIAG 任务书：求解器内存爆胀根因诊断（发给 Codex）

先读 `docs/handoff/codex_standing_charter_20260817.md`。**诊断优先，不猜测**（P76 教训：
Claude 三假设全错过一次）。

## 已钉死的事实

- `FACT`（内核日志，`converge_long_20260817_rerun2/kernel_memory_kill_evidence.log`）：
  05:34:29 `memorystatus: killing largest compressed process python3.13 [61727] 39524 MB`——
  求解器压缩内存足迹 **39.5 GB**。
- `FACT`：两跑（`converge_long_20260817/` 与 `_rerun2/`）死法相同：曲线逐位复现 16 个改进点
  至第 863 圈 2868.433369292473，此后无改进，在 47 分钟前后被杀。
- `FACT`（`converge_rerun_rss_20260817.csv`）：交换区 2.7GB→6.3GB（CPU 9:15）→11.5GB（15:43）
  →14.4GB（20:18），随后爆至内核记录的 39.5GB。
- `FACT`：**同配置 800 迭代（745.5 秒）正常收尾**（`fix_decoder_dag_20260817/iter_800_post/`），
  故致命增长发生在更深区域（863 圈之后的无改进期，含 stagnation_patience=500 的重启带）。

## 嫌疑清单（只作检索起点，结论必须靠测量）

①SC-V2 充电修复缓存（作用域＝整次搜索、无逐出）②种群重启后的旧对象滞留
③education/提案候选列表滞留 ④DAG 重写新引入的持有 ⑤记账/轨迹结构累积 ⑥其他。

## 你要做的

1. **外置仪器，不改 solver 源码**：写一个探针脚本（放
   `solver/reports/mem_diag_20260817/probe_*.py`），用 tracemalloc（或你判断更便宜的方式）
   包裹既有入口跑同命令（同 seed、同参数），每 60–90 秒把 top-25 分配点
   （按累计大小、带 traceback 文件行号）与 RSS/交换区写入仓库 CSV/日志。
2. **保护机器**：探针自带安全阀——总足迹（RSS＋swap 增量）超过约 10GB 即对求解器发
   SIGTERM 优雅停，**不许再让系统杀第三次**。目标观察窗＝越过 863 圈后至少 10–15 分钟。
3. **裁断**：给出增长主因的文件:行号级证据（哪个结构在涨、涨速多少 MB/分钟、
   与圈数/重启事件的相关）；逐条裁嫌疑清单。
4. **最小修法提案（先不施工）**：写清改哪里、是否语义无关
   （精确键缓存的逐出不改变任何返回值→应当逐位无关，须论证）、验收怎么做
   （800 迭代指纹逐位＋深区段内存曲线平稳）。**若你判断证据已足且修法语义无关，
   按 P85 可直接施工＋验收；语义有关则停下写清。**

## 产物

`solver/reports/mem_diag_20260817/`：`report.md` 首行 `MEM_DIAG_DONE`／`_HALT`、
末行 `MEM_DIAG_END`；探针脚本、采样 CSV、四件套、done.json、续跑说明。
边界：不碰三保护文件与 `charging.py`（P78 冻结——**注意：若主因真在 SC-V2 缓存，
它在 `resetp_alns/support/charging.py` 还是 `problem_hgs/charging.py`？后者冻结中；
若修法必须动冻结文件，停下报告，不得越界**）；不动前两跑现场；结尾答"接下来该干什么"。
