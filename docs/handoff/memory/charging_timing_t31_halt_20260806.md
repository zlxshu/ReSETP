# T31 固定 3 并发续跑资源停机（2026-08-06）

权威现场记录为 `docs/handoff/charging_timing_three_arms_uncapped_20260806/t31_partial_report.md`。T31 从 70/90 启动，固定 `workers=3`、每批最多 5 个；新增 3 个成功行后停在 73/90，失败行 0，剩余 17。停机时单 worker RSS 1078.7 MB 且处于 `U`，交换区由已用 5308.94 MB 增至 6723.06 MB，暂停后系统扩容到 8192 MB 且已用 6939.44 MB。按用户命令停止，没有将 workers 降到 3 以下继续，没有形成 90 单元全量科学结论。三个受保护文件开收工哈希一致，`paper_claim_allowed=false`。
