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
- **P3 全量三臂已跑**：`p3_china81_gate/decision.json`，`P3_CHINA81_FORMAL_COMPLETE`，81题×5种子=405单元。但跑的三臂是 mother(mechanism_ev单视角)/ablation(去SP多视角)/full(完整)。**其中 mother=mechanism_ev 视角(HGS-M)、full=MV-HGS-SP 完整，两臂数据可复用**；ablation(去SP)不进论文(本刊几乎不设附录,附录已删),仅留仓库 CSV 作证据。full vs mother=144胜261平0负（融合>最强单视角，零负，1+1>2成立）。
- **P4 BKS冲刺已跑完**：新BKS候选0，12/15题优于文献值(gap 0.008%~1.31%)，与P1/P3同引擎只放大预算+换种子。

**尚未做（本轮 Codex 开跑，见任务 S1–S7）**：
- **S1 preflight**：cv_only/naive_ev 两个新视角在3题(含1个200c大EV题)先验可行+区分度。cv_only 是纯燃油代理但用完整EV/充电/碳模型评分，大题可能 complete 失败或三视角塌成同值——20分钟先探，失败即 HALT。
- **S2 全量补跑**：81题×5种子×{cv_only,naive_ev} 单视角收敛（mechanism_ev/full 复用P3）。数据填正文分层汇总表 tab:china81-summary(本刊不设附录,不做逐题A1表)。
- **S3 代表题四臂**：先零搜索预选代表题(五特征)登记，再×10种子×四视角臂，记值/CPU/逐时间轨迹。表6+图4数据。
- **S4 表4**：代表题MV-HGS-SP十次最优解逐路径明细，独立检查器复算。
- **S5**：单一脚本生成全部表图。
- **S6 [Claude]改tex**：已完成结构改动——表头三视角化(HGS-F/E/M)、删 ReSETP-ALNS 与 ref:66(正文+bibitem)、正文改1+1+1>3叙事、删附录A(本刊不设,全量结果入正文 tab:china81-summary)、命名映射见 [[algorithm-naming-map]]。**剩余**:公开表诚实注(对ETGA平均更低但逐题19/28,等P1数据填入时加)。**去SP消融不进论文**(附录已删+简洁),留仓库证据。表4(逐路径明细)用户2026-07-22令保留。
- **S7 P5收官**：引用补全+终局标记 `ALGORITHM_EXPERIMENTS_CLOSED_20260720`。"E2搞定"以此标记为准。

**方法变更登记（须写审批登记）**：私有表用**收敛式**(NoImprovement停,各臂跑到自身收敛,报各自CPU)，偏离施工图§P2的"等墙钟T"。理由：表6要报CPU对比，等墙钟下CPU都≈T无意义；收敛式与P3/G-CHINA-REP一致，也对齐陈2025表6(各算法收敛CPU)。诚实边界：收敛式下完整体用的算力多于任一单视角，故私有表是"质量结果+CPU披露"(陈的框法)，不得暗示等算力优越。

参见 [[mv_hgs_sp_stage1_closeout_20260720]]、[[paper-v2-china-pivot]]、[[resetp-alns-independence]]。

2026-07-22 Codex execution status (durable, not final closure):
- S1 preflight passed as PASS_S1_THREEVIEW_PREFLIGHT: 9/9 exact-feasible rows, violation count 0; on the 200-customer instance the three exact costs were distinct (cv_only=9390.71355197382, naive_ev=9390.193755425857, mechanism_ev=9389.14724976716).
- S2 is running under the bundled PyVRP 0.12.2 environment with six workers. Only cv_only and naive_ev are newly computed; P3 mechanism_ev and MV-HGS-SP are read-only reuse. At record time 139/810 new rows were complete, with feasible rate 1, zero violations, zero duplicates, and no monitor findings.
- A PASS-only local chain controller waits for complete S2/S3/S4/S5 evidence, cleans AppleDouble sidecars and refreshes listed hashes, then launches the next stage. It does not edit TeX, protected evaluator files, or raw inputs. This status is not ALGORITHM_EXPERIMENTS_CLOSED_20260720; S6/S7 remain open.

2026-07-22 Codex S2-REV-V2 corrective closeout:
- The v1 S2 HALT record remains unchanged. Under approval-register entry `S2-INFEASIBLE-UNIT-001`, v2 records 810/810 rows, 809 OK and one deterministic `naive_ev`/HGS-E infeasible raw ERROR (`cn-jjj-200c-01-V2-LOCATIONS`, seed 2, C099 late by 0.388 s). HGS-E uses four feasible seeds for that instance's Best/avg, with the table note and the complete-model-referee motivation disclosed; no rerun, reseed, completioner, evaluator, or raw-data change was made.
- v2 files are `full_gate/decision_v2.json`, `report_v2.md`, `metadata_v2.json`, `done_v2.json`, and the refreshed `artifact_hashes.json`; the original manifest is `artifact_hashes_v1.json`. The S3/S5 runners and chain controller now consume v2. The fresh chain is `.e2-s2-to-s5-chain-v3.monitor`; the previous v2 chain HALT was caused by its PASS-only controller not recognizing the approved v2 decision.
- The v3 chain is now running: it recognized the v2 S2 PASS and launched `representative_gate/.e2-s3-representative.monitor`. No final closure marker has been written.
- The run later completed S3 and halted at S4. S3 passed 40/40 exact-feasible rows on registered representative `cn-prd-50c-01-V2-LOCATIONS`; S4 seed 4 had identical recorded/direct/exact cost `2357.11786239211` and zero full-solution violations. The S4 runner incorrectly applied global customer-coverage checking to each one-route fragment, creating 400 expected `CUSTOMER_COVERAGE` pseudo-violations, so the decision is `HALT_S4_INDEPENDENT_RECHECK`. S5 and final closure remain unopened; no algorithm data or protected evaluator was changed.

2026-07-22 Codex S4-REV-V2 and S5-REV-V2 closeout:
- The original S4 v1 HALT files remain unchanged. The v2 runner checks the complete witness with global `check_solution`, exact scoring, and one-time customer coverage only at the whole-solution level; each route fragment is checked arithmetically and all additive columns close to the complete-solution totals. `table4_gate/decision_v2.json` is `PASS_S4_ROUTE_DETAIL`: recorded/direct/exact cost `2357.11786239211`, full-solution violation count 0, 50 customers covered exactly once, and all route closure checks pass. No solution, witness, evaluator, cost, price, search, or main TeX file was changed.
- The earlier S5 v1 PASS is retained as historical provenance but is superseded for the current paper contract because it copied A1 and exposed engineering labels. S5 v2 is `PASS_S5_ARTIFACTS` and writes only suffixed v2 outputs: renamed Table 4/5/6, Figure 4, `china81_summary_v2.csv/.tex` (10 rows: three city groups x S/M/L contiguous tier bands plus Overall), and `china81_pairwise_tests_v2.csv`. It generates no v2 A1 appendix. The nine sealed tiers are grouped for reporting as S=(10,15,20), M=(25,50,75), L=(100,150,200); this is an aggregation rule only and does not alter raw data.
- S5 v2 uses HGS-F/HGS-E/HGS-M/MV-HGS-SP in table/figure outputs. The S2 registered exception remains visible: HGS-E is 404/405 feasible, and the affected instance uses four feasible seeds for Best/avg; HGS-F/HGS-M/MV-HGS-SP are 405/405. Global paired results are MV vs HGS-F `297/85/23` over 405 pairs, MV vs HGS-E `143/215/46` over 404 pairs, and MV vs HGS-M `144/261/0` over 405 pairs. Wilcoxon signed-rank p-values use a tie-corrected large-sample normal approximation with three-comparison Holm adjustment; this is auxiliary descriptive evidence, not an equal-compute claim.
- v2 `artifact_hashes.json` was independently recomputed with zero mismatches and carries `HASH_CONTAMINATED_APPLEDOUBLE`; root output sidecars were cleaned. The v6 chain supervisor wrote `chain_done_v2.json` = `PASS_S2_TO_S5_CHAIN_V2` with S2/S3/S4/S5 all PASS and no chain findings. Standalone S5 monitor startup races left diagnostic scenes preserved, but the completed v2 files, chain completion marker, hashes, and protected-file hashes were independently verified. S6 TeX edits and S7 final closure remain open; no `ALGORITHM_EXPERIMENTS_CLOSED_20260720` marker is authorized.

2026-07-22 Codex S5-REV-V3 presentation closeout:
- S5 v2 and `artifact_hashes_v2.json` were preserved. The v3 runner is deterministic materialization only: no solver, raw ledger, witness, evaluator, statistical input, or main TeX was changed. The v3 decision is `PASS_S5_ARTIFACTS` with revision `S5-REV-V3`.
- Table 5 now contains VCGP/MDFIHA/MDFIHA-ETGA Best error, PyVRP-HGS Best/avg error, and MV-HGS-SP Best/avg error, all relative to BKS; its Avg row uses P1 `decision.json` for Best averages and sealed P1 raw runs for ten-seed average columns. Minimum error is bolded row-wise. Table 6 bolds only row-wise minimum cost, including Min/Avg/Max, never CPU; the China81 summary independently bolds Best and avg minima.
- Table 4 changes only the total-row load-rate cell. The route-level definition is maximum actual load divided by vehicle capacity, so the aggregate is the sum of nine route maxima divided by the sum of nine capacities: 12223/12675=96.433925%. The v2 total value `100.0` was not reused.
- The v3 monitor `.e2-s5-artifacts-v4.monitor` completed with no findings. The v3 manifest has 19 files and zero independent SHA-256 mismatches; root AppleDouble sidecars were removed and the integrity flag is retained. S6 must still embed v3 table bodies and recompile; S7 references and the final closure marker remain open.

2026-07-22 Codex S3-TRAJ-V4 observation-only rerun:
- The registered representative `cn-prd-50c-01-V2-LOCATIONS` was rerun for four arms and seeds 1--10. All 40 final costs matched the sealed S3 raw ledger exactly; all 40 complete solutions were feasible with zero violations. The sealed S3 raw SHA-256 remained `da7ebb85f29b166c0f386f30c354d3d844b2c9026e9fd9d69a3e05fc67891afa`.
- The first HALT was a runner artifact bug: `snapshot_file` was left blank because a temporary row copy was passed to the snapshot writer. Its v1 decision/report/metadata/hash/offline evidence was preserved as `*_halt_v1`; the repair then resumed offline without another solver run.
- The repaired offline materialization hit the registered hard gate on `mechanism_ev`/seed10: a historical proxy-best skeleton scored `2364.589958517462` under the complete model, below the sealed and rerun final cost `2365.8780971446868`. An independent read-only replay confirmed the point. Final decision is `HALT_S3_TRAJ_OFFLINE_CURVE_GATE`; v2 evidence is preserved as `*_halt_v2`.
- This is a real boundary between historical offline-completed incumbents and the sealed runner's final candidate, not an evaluator or algorithm change. Do not discard the lower historical point or raise it by hand. Figure 4 v4 and S5-REV-V4 PASS remain blocked pending a user decision on the trajectory acceptance contract; no closure marker is authorized.

2026-07-22 Codex S3-TRAJ-CURVE-DEF-001 与 S5-REV-V4 收口：
- 用户批准将图4定义为历史快照骨架经完整模型离线评分后的单调 best-so-far；原 S3-TRAJ v1/v2 HALT 证据不改写。离线物化完成 40/40，最终成本逐位匹配封存 S3，完整解违约 0；HGS-M/seed10 的 `2364.589958517462` 低于封存最终 `2365.8780971446868`，仅保留为轨迹观测，不进入表格。
- S5-REV-V4 判定 `PASS_S5_ARTIFACTS_V4`。输出表4/表5/表6/China81 汇总、图3碳强度曲线、图4收敛曲线的 v4 CSV/TeX/PDF/PNG；47项哈希独立复核无缺失/不匹配，图3为144点，图4为29点，表4客户1--50恰好覆盖一次。v3产物和manifest保留，主TeX及保护文件未改。
