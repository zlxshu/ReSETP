# T31 固定 3 并发续跑中止记录

## FACT

终态为 `HALT_T31_WORKERS3_MEMORY_SWAP_INSTABILITY`，`paper_claim_allowed=false`。T31 从 70/90 个唯一 `(instance_id, arm, seed)` 开始，固定 `workers=3`、`batch-size=5`；本轮新增成功 3 个、新增失败 0 个，逐单元持久化后为 73/90，仍剩 17 个。

| 单元 | 总迭代数 | 最后一次 >=1% 改善全局迭代 | 总墙钟秒 | 停机触发原因 | 最终完整评价目标 | MIP 状态 | MIP 实耗秒 |
|---|---:|---:|---:|---|---:|---|---:|
| `T26__PRD__COST__S2026080201` | 47329 | 36449 | 738.724176 | `NO_IMPROVEMENT_WALLCLOCK_ALL_VIEWS` | 3509.465997667 | `REJECTED_COMPLETE_MODEL_VIOLATIONS` | 10.023565 |
| `T26__PRD__COST__S2026080202` | 45293 | 34501 | 714.325636 | `NO_IMPROVEMENT_WALLCLOCK_ALL_VIEWS` | 3469.166597014 | `REJECTED_COMPLETE_MODEL_VIOLATIONS` | 10.023085 |
| `T26__PRD__COST__S2026080203` | 41700 | 30918 | 657.925062 | `NO_IMPROVEMENT_WALLCLOCK_ALL_VIEWS` | 3496.382877484 | `REJECTED_COMPLETE_MODEL_VIOLATIONS` | 10.023511 |

本轮已完成单元墙钟中位数为 714.325636 秒。三次服务量均为 100/100 客户、24443.0/24443.0 需求；违反数均为 0，闭合误差均为 0.0。失败单元清单为空。

中止依据是同一时间窗内的实测资源变化：单个 worker RSS 达 1078.7 MB 且状态为 `U`；交换区从开工时 6144 MB 中已用 5308.94 MB，增长到 7168 MB 中已用 6723.06 MB，暂停后系统继续扩到 8192 MB 且已用 6939.44 MB；内存压力空闲比例降至 32%，`swapouts` 由 91862707 增至 93446190。1 分钟负载仅由 2.58 增至 4.73，因此本次停机依据是内存/交换区失稳，不是 CPU 不足。

`T26__PRD__COST__S2026080204` 和 `T26__PRD__COST__S2026080205` 只留有 `SEARCH_STARTING` 检查点，没有结果行，不计为失败或完成。已按用户命令停止整个进程组，未以低于 3 的 workers 继续。

## INFERENCE

没有产生三臂完整的 90 单元集合，因此本记录不计算或解释用户要求的全量代理捕获率、三臂最终完整目标差异、MIP 全量状态分布、48 槽全量分布或路线签名配对结论。

## DECISION

仅执行用户预先规定的资源停机边界；未新设阈值，未修改算法搜索语义，未降低并发继续。

## HALT_*

`HALT_T31_WORKERS3_MEMORY_SWAP_INSTABILITY`

三个受保护文件开工/收工 SHA-256 一致。
