# T23 充电时刻三条线探索批：跑前合同 HALT

`HALT_T23_RUNNER_STOP_AND_FAILURE_CONTRACT_UNAVAILABLE_NO_SEARCH`

## FACT

本轮计划清单为 3 个算例 × 3 个充电择时策略 × 10 个种子，共 90 个单元；实际启动搜索 `0/90`，`raw_runs.csv` 数据行 0，`improvement_trace.csv` 数据行 0，`slot_distribution.csv` 数据行 0，solution witness 0。没有运行 solver、没有生成实验数字、没有补跑或挑选种子，`paper_claim_allowed=false`。

开工前读取了 T21 预注册、T22 仪表报告、准备清单 §二、T21 runner 和 HGS 停机实现。当前 runner 把 `REFERENCE_ITERATIONS={cv_only:600, naive_ev:600, mechanism_ev:800}` 直接作为 full 模式的 `iterations` 传入每个单元；HGS 随后用 `MaxIterations(max_hgs_iterations)` 构造停止器，并把达到该值的停因记为 `MAX_ITERATIONS`。因此 600/600/800 在当前实现中是硬停止值，不是参考起点。

当前实现没有“到参考起点后若仍改善则继续”的运行分支，也没有已登记的“长期平缓”窗口可供程序决定何时最终停止。若直接执行 full 模式，90 个单元即使在参考边界仍有改善，也会按 `MAX_ITERATIONS` 截断；这与 T23 明示合同冲突。

当前 runner 还在 `as_completed()` 循环中直接调用 `future.result()`。任一单元抛异常会终止整批；各项 CSV、witness 与正式 metadata 又是在所有 future 返回后才统一物化。因此它不能满足“单元失败时记录原始原因与已跑状态、继续其余单元”的合同。

三个受保护文件开工 SHA-256：

- `solver/src/setp_solver/cost.py`: `e7ea406da87a3172cd1ff7dc87fe7def536e74f197f6c67b29da2394fe42b00d`
- `solver/src/setp_solver/check.py`: `1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072`
- `solver/src/setp_solver/search/evaluation.py`: `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3`

收工复核见 `metadata.json`；本轮未修改 runner、算法、策略实现、审计器、三个受保护文件或论文目录。

## 本任务要求的五项读数

1. 每个算例每个策略的最后改善迭代与改善幅度衰减：无观察值，因搜索 0/90。
2. 很大迭代数仍在改善的单元：无观察值，因搜索 0/90。
3. 三策略的 48 槽分布与每 kWh 实际碳强度差异：无观察值，因搜索 0/90。
4. 服务量红线：无运行行，不能报告完成客户数或完成需求量；没有把缺失写成通过。
5. 违反数与目标闭合误差：无运行行，不能报告为 0；没有把未运行写成通过。

## INFERENCE

直接启动当前 full 模式只能得到“每视角固定迭代上限的批次”，不能得到 T23 登记的“参考起点后继续观察改善、单元失败仍继续”的批次。0/90 不构成任何三策略效果、服务量、违反数、闭合误差或长期平缓证据。

## DECISION

按用户铁律“若必须改才能跑完，停下来写明要改什么、为什么，不要自行改”，本轮不执行 full 模式，不改代码，不自定长期平缓阈值。`paper_claim_allowed=false`。

## HALT_*

`HALT_T23_RUNNER_STOP_AND_FAILURE_CONTRACT_UNAVAILABLE_NO_SEARCH`

为使冻结合同可执行，必须修改但本轮没有修改的内容只有：把参考迭代边界与硬停止器解耦，在边界处能够依据已记录的改善状态继续运行；为最终停止提供经用户登记的窗口或等价的明确外部停止授权，不能由执行者自定；逐 future 隔离异常并原样保存失败原因和已跑状态，使其余登记单元继续；把已完成单元原子物化，避免一个 future 异常使先前完成项只存在于内存。否则运行结果无法满足 T23 的停止合同与失败保全合同。
