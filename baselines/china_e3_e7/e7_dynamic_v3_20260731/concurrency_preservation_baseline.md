# E7 并发切换保护基线

- 冻结时点：2026-07-30T07:15:45Z
- 旧运行：PID/PGID 67744，2 workers
- 安全边界：用户下令时在途的 100c seed4 `FULL_ROLLING` 与 `NO_COOPERATION` 均已原子落盘后，由实验监控器暂停整个进程组；`lsof` 未发现任务目录写文件句柄。
- 50c：40 个真实任务 JSON；按路径排序后对每行 `SHA-256  路径` 再取 SHA-256，集合摘要为 `64ffc8fd3b86d230747beef76dfbf158e98ccb9a5e15004bd08ad2d03c43da37`。
- 100c：暂停时共有 16 个真实任务 JSON；包括 seeds 1--3 的全部四臂、seed4 的 `STATIC_FIXED_RECOURSE`/`FULL_ROLLING`/`NO_COOPERATION`、seed5 的 `STATIC_FIXED_RECOURSE`。同法计算的集合摘要为 `fe9f276128fce6b0dea00f9e668ab9a0764e2b709089c8d9103035dea60911fc`。
- 文件枚举排除 `._*`。

切换后必须按同一文件集合与同一算法复算；任一摘要不同即停止收口并写 `HALT_PRESERVED_TASK_HASH_MISMATCH`。
