---
name: e2-final-campaign-p3-p4-complete
description: E2终局战役最终决定——公开表证"优于已知算法"(P1已完成),China81私有表证"三视角融合1+1+1>3"(需补跑三视角子算法),两个ALNS都不进表
metadata:
  type: project
---

2026-07-22 用户拍板定案。E2-FINAL-CAMPAIGN-001（施工图=`docs/handoff/e2_final_algorithm_experiment_construction_20260720.md`）两张表的**目的**和**对手**由用户明确：

**两张表的目的（用户原话精神）**：
- **公开 benchmark 算例（V13-MDVRPTW-28）= 证明我的混合算法优于目前已知算法**。对手 = 能在别人论文查到同款算例成绩的公开算法：VCGP/MDFIHA/MDFIHA-ETGA（文献值）+ 开源母体 PyVRP-HGS（同机复跑）。**不加入任何自产陪跑算法**（主推 MV-HGS-SP 除外，它是被评价对象）。
- **China81 私有算例 = 证明我的主打算法 = 它的开源子算法们的 1+1>2 融合**。因为是自建算例无外人成绩可查，对手 = 它自己的开源子算法（拆开单独跑，证融合体 > 各组件）。

**关键澄清（纠正之前的错误）**：
1. **"ReSETP-ALNS"这个算法名是论文 tex 里编出来的，用户从没取过**。tex 行958的 `\cite{ref:66}` 其实指 Ropke-Pisinger 2006（ALNS 开山论文）。用户手里真实有两个 ALNS：一个第三方**开源 ALNS**、一个自己造的**加强版 ALNS**。
2. **两个 ALNS 都不进任何对比表**。MV-HGS-SP 内部用的是 HGS 不是 ALNS，ALNS 是项目早期被淘汰的另一条路线，不是 MV-HGS-SP 的子算法。P0 等算力四臂的 D 臂 `run_project_alns(mechanism_mode=True)`（自产加强版 ALNS，15:0 输给 MV-HGS-SP）就留在 P0 保险丝里当历史，**不进主表**。
3. **China81 主表 = 三视角子算法 + 完整体**。MV-HGS-SP 的 "MV"=多视角，内部是**三个视角各跑一个 HGS**：`cv_only`(纯燃油视角)/`naive_ev`(简化电动视角)/`mechanism_ev`(完整机制电动视角)，再用 **SP(HiGHS 集合划分)把三视角路线精确融合**。所以私有表 = 三视角子算法各自单独跑 vs MV-HGS-SP 融合体，证"单看任一视角都不如三视角融合"= 1+1+1>3。

**已完成（可复用/不重跑）**：
- **P1 公开表已完成**：`p1_formal_gate/decision.json`，`P1_FORMAL_PUBLIC_COMPLETE`，28题×10种子=280单元。MV-HGS-SP 平均误差 **0.905% 全场第一**（ETGA 0.990%/MDFIHA 1.375%/母体HGS 1.472%/VCGP 1.604%）；逐题压母体28/28、压MDFIHA 27/28、压VCGP 26/28、压最强ETGA 19/28（对ETGA平均更低但逐题只19/28，须诚实注）；对母体264胜16平0负。新BKS候选0。**表5格式(Best./avg.误差%)已对齐陈2025，不重跑。**
- **P3 全量三臂已跑**：`p3_china81_gate/decision.json`，`P3_CHINA81_FORMAL_COMPLETE`，81题×5种子=405单元。但跑的三臂是 mother(mechanism_ev单视角)/ablation(去SP多视角)/full(完整)。**其中 mother=mechanism_ev 视角、full=MV-HGS-SP 完整，两臂数据可复用**；ablation(去SP)不进主表，降为附录组件消融证据。full vs mother=144胜261平0负（融合>最强单视角，零负，1+1>2成立）。
- **P4 BKS冲刺已跑完**：新BKS候选0，12/15题优于文献值(gap 0.008%~1.31%)，与P1/P3同引擎只放大预算+换种子。

**尚未做（本轮 Codex 开跑，见任务 S1–S7）**：
- **S1 preflight**：cv_only/naive_ev 两个新视角在3题(含1个200c大EV题)先验可行+区分度。cv_only 是纯燃油代理但用完整EV/充电/碳模型评分，大题可能 complete 失败或三视角塌成同值——20分钟先探，失败即 HALT。
- **S2 全量补跑**：81题×5种子×{cv_only,naive_ev} 单视角收敛（mechanism_ev/full 复用P3）。附录A1数据。
- **S3 代表题四臂**：先零搜索预选代表题(五特征)登记，再×10种子×四视角臂，记值/CPU/逐时间轨迹。表6+图4数据。
- **S4 表4**：代表题MV-HGS-SP十次最优解逐路径明细，独立检查器复算。
- **S5**：单一脚本生成全部表图。
- **S6 [Claude]改tex**：表头三视角化、删 ReSETP-ALNS 与 in-text ref:66、正文改1+1+1>3叙事、去SP消融进附录、公开表诚实注。preflight通过后再动手。
- **S7 P5收官**：引用补全+终局标记 `ALGORITHM_EXPERIMENTS_CLOSED_20260720`。"E2搞定"以此标记为准。

**方法变更登记（须写审批登记）**：私有表用**收敛式**(NoImprovement停,各臂跑到自身收敛,报各自CPU)，偏离施工图§P2的"等墙钟T"。理由：表6要报CPU对比，等墙钟下CPU都≈T无意义；收敛式与P3/G-CHINA-REP一致，也对齐陈2025表6(各算法收敛CPU)。诚实边界：收敛式下完整体用的算力多于任一单视角，故私有表是"质量结果+CPU披露"(陈的框法)，不得暗示等算力优越。

参见 [[mv_hgs_sp_stage1_closeout_20260720]]、[[paper-v2-china-pivot]]、[[resetp-alns-independence]]。

2026-07-22 Codex execution status (durable, not final closure):
- S1 preflight passed as PASS_S1_THREEVIEW_PREFLIGHT: 9/9 exact-feasible rows, violation count 0; on the 200-customer instance the three exact costs were distinct (cv_only=9390.71355197382, naive_ev=9390.193755425857, mechanism_ev=9389.14724976716).
- S2 is running under the bundled PyVRP 0.12.2 environment with six workers. Only cv_only and naive_ev are newly computed; P3 mechanism_ev and MV-HGS-SP are read-only reuse. At record time 139/810 new rows were complete, with feasible rate 1, zero violations, zero duplicates, and no monitor findings.
- A PASS-only local chain controller waits for complete S2/S3/S4/S5 evidence, cleans AppleDouble sidecars and refreshes listed hashes, then launches the next stage. It does not edit TeX, protected evaluator files, or raw inputs. This status is not ALGORITHM_EXPERIMENTS_CLOSED_20260720; S6/S7 remain open.
