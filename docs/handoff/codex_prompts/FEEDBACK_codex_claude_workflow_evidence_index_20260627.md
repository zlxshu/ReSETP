# 复盘证据索引 - 2026-06-27

用途: 给 `FEEDBACK_codex_claude_workflow_retrospective_20260627.md` 绑定证据。此文件不是新结论,只说明主要判断来自哪些本地文件或本线程可见内容。

## A. 用户反馈口径

| 判断 | 证据来源 | 用法 |
|---|---|---|
| 用户要求按"预期/问题/影响/解决办法"四个桶写反馈 | 当前主线程用户消息; Codex memory `2026-06-24T15-05-31-KdeS-resep_09e_feedback_summary_bilingual.md` | 决定报告四大反馈维度 |
| 用户补充英文 walkthrough 六个问题 | 当前主线程用户消息 | 决定报告必须覆盖 goal, challenge, workflow, Codex struggled, what next, outcome/improvement |
| 用户补充 examples/broader goal | 当前主线程用户消息 | 决定报告必须写 Codex 丢目标、局部合理整体失败、反复犯错、跨工具协调差、切换模型工具 |
| 用户要求中文白话、少黑话、Fable5 风格 | `CLAUDE-FABLE-5.md`; Codex memory `2026-06-23T18-48-44-W3B5-resep_memory_personalization_fable5_probing.md`; 当前主线程多次用户纠偏 | 决定报告不用技术流水账作为主结构 |

## B. 协作和事实源

| 判断 | 证据来源 | 用法 |
|---|---|---|
| Claude 负责战略判断和提示词,Codex 负责仓库执行,用户保留最终决策 | 当前主线程; `docs/handoff/codex_prompts/MASTER_codex_takeover_plan.md`; 子代理只读审计结果 | 写三者分工和偏差 |
| 主仓 HANDOFF/MASTER 是单一事实源,但曾出现 root/worktree handoff divergence | `HANDOFF.md`; `docs/handoff/codex_prompts/MASTER_codex_takeover_plan.md`; Codex memory HANDOFF divergence entries | 写跨文件协调问题 |
| AppleDouble `.git/objects/pack/._*.idx` 会造成 git 噪声 | 多次 `git status` / `git log` 输出; memory `m1_to_x86_09s_handoff_safe_branch_cleanup` | 解释 git 读取噪声不是实验结论 |

## C. 算法比较线

| 阶段 | 证据来源 | 关键事实 |
|---|---|---|
| 09c SA acceptance | `baselines/e2_alns/sa_acceptance_halt_report.md` | `HALT_HARD_TIMEOUT_NOT_PROMOTED`; 35/135 hard timeout; 完成行零违约但不能晋级 |
| 09d throughput | `baselines/e2_alns/throughput_halt_report.md` | 吞吐提升,但 ALNS paired 9/25 赢、16/25 输; `HALT_TRUE_GLNS_BETTER_AFTER_THROUGHPUT` |
| 09t Goeke80 T3 preflight | `baselines/e2_alns/goeke80_multitrip_t3_preflight.md` | Stage A 138/138 跑满,ALNS 7/LNS 2/tie 60; Stage B 130/414 后 `HALT_COLLECTION_COST` |
| 09u wall-clock / 100kWh preflight | `baselines/e2_alns/wallclock_battery_preflight_wallclock_retry.md` | 92/92 收齐; wc80/wc100 都是 ALNS 2/LNS 1/tie 20; EV route share 约 0.057 |
| 8 文献基线仍不能直接当正式比较 | `baselines/report.md`; 子代理 Gibbs 审计 | 正式比较仍需后续闭合,旧根目录 baseline CSV 不能直接引用 |

## D. 参数和混合车队故事线

| 阶段 | 证据来源 | 关键事实 |
|---|---|---|
| 09e 小算例参数诊断 | `baselines/e2_alns/instance_param_diagnostic.md` | 小算例 mixed 已赢 cv_only; CV 碳排已计入; 全油问题不是普遍现象 |
| 09f 大算例诊断 | `baselines/e2_alns/largescale_allcv_diagnostic.md`; `MASTER_codex_takeover_plan.md` | 100/150c mixed 好解存在但不稳; 200c all-CV best/mean 更强 |
| 09h evidence-bound parameter review | `baselines/e2_alns/parameter_evidence_review.md` | 280kWh 有现代配送车证据; highway/regional 速度证据支持; 但只是候选场景支持 |
| 280kWh fleet composition gate | `baselines/e2_alns/280kwh_fleet_composition_gate.md` | `HALT_EV_DOMINANT`; 280kWh 过度 EV 主导,不能当稳定 mixed 默认 |
| 09k battery spectrum | `baselines/e2_alns/battery_spectrum_transition.md` | strict balanced 主要是 80kWh; 100kWh 近边界偏 EV-heavy; 113kWh+ EV-dominant |
| 09l source-bound mixed band | `baselines/e2_alns/source_bound_mixed_band_gate.md` | `BATTERY_ONLY_INSUFFICIENT`; 非 80kWh 来源候选无一跨全梯度过关 |
| 09q battery x operations map | `baselines/e2_alns/source_bound_operational_mix_map.md` | `BATTERY_OPERATION_COMBINATION_INSUFFICIENT`; 真实电池+诊断运营约束 Stage A 未找到可推广组合 |

## E. 车辆语义和 Goeke 回正线

| 阶段 | 证据来源 | 关键事实 |
|---|---|---|
| 09r hard-cap feasibility audit | `baselines/e2_alns/hard_cap_feasibility_audit.md` | `Q=1600 + hard cap + route=vehicle` 下 69/69 容量下界不可行 |
| 用户纠偏: 一台车可以多趟 | 当前主线程用户消息 | 论文车辆上限是实体车辆硬上限,代码翻译错了,不是新增建模 |
| 09s Goeke80 multi-trip rescue | `baselines/e2_alns/goeke80_multitrip_rescue_gate.md`; `MASTER_codex_takeover_plan.md` | 当前主线回到 `Q=3650,B=80,v=25,carbon=0.05034`; 69/69 warm start OK; smoke 34/34 OK |
| 09s 不是正式胜利 | `goeke80_multitrip_rescue_gate.md`; `goeke80_multitrip_t3_preflight.md` | 语义卡点解除,但正式算法胜负仍未闭合 |

## F. 用户体验和 Codex 失败模式

| 失败模式 | 证据来源 | 说明 |
|---|---|---|
| Codex 逐渐丢目标 | 当前主线程用户多次追问"目标是什么/大问题是什么/完全跑偏"; 09e-09u 报告链 | 局部任务很多,但缺少持续总图 |
| 诊断线索被推进成结论 | 09h -> 09i/09j -> 280 gate 链条 | 280kWh 从候选支持被推进为默认,后又被 EV-dominant gate 降级 |
| 术语太多,用户看不懂 | 当前主线程用户明确说"说人话","我看不懂","不要黑话"; memory personalization entry | 报告需要先写人话含义 |
| 监控方式误解 | 当前主线程用户关于"开着对话来监控"和"不要过度探测"的纠偏 | 用户要低频陪跑,不是机械 heartbeat 状态 |
| 模型语义讲乱 | 当前主线程关于车辆硬上限、TeX 是否被改、运营约束是不是原模型的连续纠偏 | Codex 没把"代码翻译错误"和"新增模型"分清 |
| 跨文件协调不足 | MASTER 与 09q 报告状态差异; HANDOFF/worktree divergence 记忆 | 单一事实源维护不稳定 |
| 用户被迫切回 Claude/其他工具 | 当前主线程用户表达"请回 Claude 做智力劳动"; memory feedback entries | Codex 未能让用户信任其全局判断 |

## G. 仍有效 / 已降级 / 待决策

| 类别 | 内容 | 证据 |
|---|---|---|
| 仍有效 | CV 碳排已计入; 90km/h 不能随便改成城市速度; 当前 baseline 为 Goeke `Q=3650,B=80`; 实体车可多趟 | 09e,09h,09s reports |
| 已降级 | 280kWh 不能直接写成稳定 mixed 默认; 09s smoke/09t Stage A/09u preflight 不能写成正式 T3 | 280 gate,09s,09t,09u reports |
| 待决策 | 是否继续 Goeke baseline 算法 T3; 是否另开现代 mixed 场景; 是否恢复 Claude 战略把关 | 当前主线程和 MASTER 后续计划 |

