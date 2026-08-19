# CONVERGE-RERUN2 任务书：同步陪跑重跑（发给 Codex）

先读 `docs/handoff/codex_standing_charter_20260817.md`。
上一轮孤儿化启动失败（你判定正确并按停止条件停手）：nohup 子进程在你退出时被清，
两次均 2 秒死、stdout 零字节。**故本次回到第一跑验证过的同步流程：你保持会话等命令收尾**
（等待期间你不消耗推理）。第一跑死于系统内存压力（swap 2876M/4096M），不是同步流程的错。

## 执行

1. 核对哈希同 `converge_long_20260817/resume.md` 收口值；
2. **同步**执行 resume.md 配方（带 PYTHONPATH、不预建输出目录），
   输出目录 `solver/reports/converge_long_20260817_rerun2`；
3. 收尾后写 `solver/reports/converge_long_20260817_rerun2/report.md`：
   首行 `CONVERGE_RERUN2_DONE`／`_HALT`，末行 `CONVERGE_RERUN2_END`；
   内容同第一跑要求（完成圈数、终止原因、改进点表、形态大白话描述、
   最优成本、服务客户数/需求量红线、异常如实）；`done.json`＋`resume.md`。
   若再被 SIGKILL：如实 HALT，**引用哨兵的 RSS 采样文件**
   `solver/reports/converge_rerun_rss_20260817.csv` 帮助定凶。
4. 结尾按章程答"接下来该干什么"。

## 边界

零代码改动；不碰保护文件与 `charging.py`；期间不启动第二个求解进程；
不动前两跑现场；不拼接曲线。
