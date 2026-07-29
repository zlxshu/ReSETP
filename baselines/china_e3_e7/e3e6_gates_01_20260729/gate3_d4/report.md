# 门三 D4：结果盲吞吐 pilot

**结论：NOT RUN。** 门二已经 HALT，按“任一门失败立即停下”要求，没有启动任何 pilot，没有读取或报告任何臂间成本。

只读源码预检确认当前 E3/E6 路径使用 `MaxIterations` 加墙钟安全上限，并由 24 个 archive candidates/视图闭合为固定 80 次完整候选评价；该路径没有使用 `NoImprovement` 收敛停机。因此用户给定的 `L/S` 判据在机制上适用于原计划 pilot，但因上游 HALT 未实际计算 `L`、`S` 或选择档位。
