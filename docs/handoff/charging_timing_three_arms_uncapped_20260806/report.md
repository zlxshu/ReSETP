# T31 固定 3 并发续跑报告

终态为 `HALT_T31_WORKERS3_MEMORY_SWAP_INSTABILITY`，材料化 73/90，成功 73，失败 0，剩余 17，`paper_claim_allowed=false`。本轮新增 3 个完成单元，未产生 90 单元全量分析。

逐单元数值、服务量红线、MIP 状态、中止资源依据、未材料化键与开收工哈希见 [t31_partial_report.md](t31_partial_report.md)。因 90 单元未闭合，本报告不伪造全量代理捕获率、三臂完整目标差异、MIP 全量状态分布、48 槽分布或路线签名配对结论。

## FACT

命令行固定 `--workers 3 --batch-size 5`；没有将 workers 降低到 3 以下。新增三行全部为客户 100/100、需求 24443.0/24443.0、违反 0、闭合误差 0.0。

## INFERENCE

停机依据为单 worker RSS 1078.7 MB、`U` 状态、交换区已用 5308.94→6723.06 MB 并继续扩容；1 分钟负载仅 4.73，故不是 CPU 瓶颈。

## DECISION

仅执行用户指定的资源停机边界。

## HALT_*

`HALT_T31_WORKERS3_MEMORY_SWAP_INSTABILITY`
