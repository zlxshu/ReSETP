# ALGORITHM_EXPERIMENTS_CLOSED_20260720

- 战役编号：E2-FINAL-CAMPAIGN-001
- 关闭日期：2026-07-22
- 状态：**算法实验正式关闭。此后算法只许被引用，不许被改动。**
- 算法冻结身份：`MV-HGS-SP`（多视角混合遗传搜索—精确路线池重组算法）；
  三视角子算法学名 `HGS-F`/`HGS-E`/`HGS-M`（映射见
  `docs/handoff/algorithm_naming_map_20260722.md`）。

## 关闭依据（全链 PASS，证据均含四件套+哈希）

| 阶段 | 判定 | 证据目录 |
|---|---|---|
| P0 等算力保险丝 | TierB（含重平衡验证 FAIL 留档） | `p0_fuse/` |
| G-DEV / G-CONFIRM / G-CHINA-REP | 三门 PASS | `mv_hgs_sp_final/gate_*` |
| P1 公开 V13-28 正式批 | `P1_FORMAL_PUBLIC_COMPLETE`（280 单元 264胜16平0负，平均误差 0.905% 全场第一） | `mv_hgs_sp_final/p1_formal_gate/` |
| P3 China81 全量三臂 | `P3_CHINA81_FORMAL_COMPLETE`（405 单元，full vs mother 零负） | `mv_hgs_sp_final/p3_china81_gate/` |
| P4 BKS 冲刺 | `P4_BKS_SPRINT_COMPLETE`（新 BKS 候选 0，12/15 优于文献值） | `mv_hgs_sp_final/p4_bks_sprint/` |
| S1 三视角 preflight | `PASS_S1_THREEVIEW_PREFLIGHT` | `p2p3_threeview/preflight_gate/` |
| S2 全量三视角补跑 | `PASS_S2_FULL_THREEVIEW_WITH_REGISTERED_INFEASIBLE_UNIT`（v1 HALT 留档；809 OK + 1 登记不可行单元，口径=审批登记 `S2-INFEASIBLE-UNIT-001`） | `p2p3_threeview/full_gate/` |
| S3 代表题四臂 | `PASS_S3_REPRESENTATIVE`（40/40，代表题 cn-prd-50c-01 预登记） | `p2p3_threeview/representative_gate/` |
| S4 表4 独立复算 | `PASS_S4_ROUTE_DETAIL`（v1 HALT=验收脚本片段误用全局检查器，留档；v2 修复后 PASS） | `p2p3_threeview/table4_gate/` |
| S5 表图生成 | `PASS_S5_ARTIFACTS`（v3：表5 含母体列+Avg 行、逐行最优加粗、表4 合计装载率 96.43=12223/12675） | `p2p3_threeview/artifacts/` |
| 链监督 | `PASS_S2_TO_S5_CHAIN_V2` | `p2p3_threeview/chain_done_v2.json` |

## 正式结论口径（写入论文的措辞边界）

- 公开 V13-28：MV-HGS-SP 平均 Best 误差 0.905%，为 VCGP/MDFIHA/MDFIHA-ETGA/
  PyVRP-HGS 母体/本文五算法最低；压母体 28/28、MDFIHA 27/28、VCGP 26/28、
  ETGA 19/28——**对 ETGA 为平均占优而非逐题全胜（已在论文正文如实注明）**；
  追平 PR17B 当前 BKS，新 BKS 为 0。
- China81：全部 9 层+总体 Best/avg 均由 MV-HGS-SP 占优；配对 Wilcoxon+Holm
  对 HGS-F/E/M 三组均 p<0.001（平均改善 0.985%/0.192%/0.199%）；对最强单视角
  HGS-M 144胜261平0负（零负由单调保护结构保证）；对 HGS-F/E 存在 23/46 个
  种子级负单元，已在论文如实披露。HGS-E 可行率 404/405（1 个确定性代理不可行
  单元，已升格为完整模型裁判必要性的实证写入算法章）。
- 私有表为收敛式（各臂报各自 CPU），判读为"质量结果+CPU 全披露"，
  不作等算力优越主张（登记 `E2-CHINA81-VIEW-ABLATION-001`）。

## 关闭后的边界

1. `MV-HGS-SP` 与三视角子算法的实现、参数、种子协议全部冻结；任何修改都构成
   新算法，须另立战役，不得沿用本战役成绩。
2. 去 SP 消融（P3 ablation 臂）不进论文，仅留仓库证据。
3. 算法版本冻结触发 PRD §10 影响矩阵；E3–E7 依赖复核属论文阶段工作，
   不属于本战役。
4. 论文 V2（`docs/paper_v2/paper_main.tex`）已完成表5/表6/表4/汇总表/图4 的
   脚本产物嵌入与全部分析段，20 页编译零错误零悬空文献。
