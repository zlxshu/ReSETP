# 文档层级校正：强制入口里有三份已不管事

日期：2026-07-29

## 事实

`READ_ME_FIRST_FOR_AGENTS.md` 强制读取清单第 3、4、7 项已**不是当前执行入口**，
但清单本身没标注这一点：

| 文档 | 状态 |
|---|---|
| `codex_prompts/MASTER_codex_takeover_plan.md` | 第 5 行**自陈**被 2026-07-11 用户决定覆盖；正文为英国轨 |
| `project_planning_map_20260701.md` | 总目标/不要做清单有效；具体路线为英国轨历史 |
| `project_prd_execution_map_v2_20260702.md` | 顶部两条声明被 07-11 覆盖；E2-G0~G5 门链已被 07-25 `FINAL_STOP` + 07-27 `e2_final_closeout` 作废 |

三者正文主体讲的是 **Goeke80 主场景 / 280 kWh 诊断场景 / 09x-09y 排查 / DR-ALNS 训练线 /
E2 门链**——全部属于**已退役的英国轨**。照单全读的冷启动 agent 会据此形成过时理解。

## 仍然有效的部分（不因降级而失效）

1. 记录纪律：四件套 + `report.md`；hash 清单排除 `._*`/`__pycache__`/`.pytest_cache`
2. 结论标签制：`FACT`/`INFERENCE`/`DECISION`/`HALT_*`/`VALID_BUT_WEAK`/`MECHANISM_BUT_TIE`
3. 禁改语义：`cost.py`/`check.py`/`search/evaluation.py`
4. 四同步链（参数正式化）
5. **已关闭路线台账**（PRD v2 §Phase2 七条）——重提前须书面说明"与当时失败条件有何不同"并经用户明示同意
6. 不要做清单（planning map §9）

## 当前权威链

```
07-11 e1_e7_submission_contract_decision   唯一拍板单
07-12 e3_e7_experiment_product_design      E3–E7 设计权威
07-13 paper_north_star                     迷路时先读
07-17/20 China pivot
07-25 e2_post_v7_algorithm_paper_action_contract
07-27 e2_final_closeout                    E2 终局
07-28 contract_e5e7_blind_01               E5/E6/E7 结果盲合同
07-29 advisor_instance_selection_01        算例选型裁决
```

后两份同时是 E5 monitor 的 `protected_files`，是机器层面的佐证。

## 怎么用

冷启动先读
`docs/handoff/session_handoff_20260729_document_hierarchy_and_e5_e3e6_state.md`，
再读其余强制入口。相关：[[e2-prd-gates]]、[[feedback-check-closed-paths-first]]、
[[paper-north-star]]、[[watchdog-must-be-per-task-and-in-session]]。
