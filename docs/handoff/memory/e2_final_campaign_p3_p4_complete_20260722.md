---
name: e2-final-campaign-p3-p4-complete
description: E2-FINAL-CAMPAIGN-001（MV-HGS-SP终局战役）P1/P3/P4已收官,P2代表题正式批尚未执行,P5收官前必须先补P2
metadata:
  type: project
---

2026-07-22:E2-FINAL-CAMPAIGN-001（施工图=`docs/handoff/e2_final_algorithm_experiment_construction_20260720.md`）P0→P1→P3→P4 已完成,但施工图规定的 **P2（China81代表题正式批,产出表6/图4/表4）尚未执行**,commit `09ba2454` 把 P3/P4 并行启动时跳过了 P2。

**已完成阶段**：
- P1(公开V13-28正式批,种子1-10)：`p1_formal_gate/decision.json`,280单元264胜16平0负,平均误差0.905%低于ETGA2026的0.990%。
- P3(China81全量三臂,81题×5种子=405单元)：`p3_china81_gate/decision.json`,决策`P3_CHINA81_FORMAL_COMPLETE`;完整体vs母体144胜261平**0负**（零负底线守住）;完整体vs去SP消融81胜302平22负;15题刷新China81-BKS-v0(项目内部最优,非公开BKS)。
- P4(BKS冲刺,15道预注册目标题×新种子11-12)：`p4_bks_sprint/decision.json`,决策`P4_BKS_SPRINT_COMPLETE`;**新BKS候选=0**（没有严格突破当前已验证BKS）,但12/15题优于最强文献值,差距0.008%~1.31%;引擎与P1/P3完全同构,只放大预算+换种子,无夹带新机制（对应commit `1da62b62`的科学一致性修正——删除了原计划里"深度末段精修"这个实为多跑epoch且ETGA标签浮夸的段落）。

**尚未执行**：P2——施工图§3明确要求三臂(PyVRP-HGS母体/ReSETP-ALNS独立/MV-HGS-SP完整体)×代表题×等墙钟种子1-10,产出表6数据+图4曲线数据+表4最优路径明细。仓库里已有的`gate_china_rep`(G-CHINA-REP)是P1启动前的两臂(母体vs完整混合体)设计验证门,只用了3题×5种子,**不满足P2的三臂×10种子×产表格式要求**,不能替代P2。

**为什么重要**：P5收官阶段(施工图§3 P5)要求"表4/表5/表6/图4/China81汇总全部由单一脚本从封存CSV生成"——表6/图4/表4的数据源就是P2,P2不跑,P5没有源数据可用,不能直接进入P5。

**How to apply**：任何"下一步该干什么"的判断，必须先补齐P2（代表题定义见施工图§1.2零搜索预选规则：81题按客户数/车场数/需求离散度/时窗紧度/EV可达率五特征取离全体中位向量最近者，字典序并列，开跑前登记不得看结果换题），P2产出+独立复算通过后才进P5。不得跳过P2直接宣称"算法实验收官"或生成表6/图4/表4。参见[[mv_hgs_sp_stage1_closeout_20260720]]、[[paper-v2-china-pivot]]。

**2026-07-22确认的第二个缺口——论文表格列名与产出数据对不上（已核对`docs/paper_v2/paper_main.tex`+P0脚本裁定，非猜测）**：论文正文明写"用PyVRP-HGS、ReSETP-ALNS和MV-HGS-SP对China81代表算例求解"（tex行955-959，ReSETP-ALNS=本项目独立实现的自适应大邻域搜索\cite{ref:66}加同一完成器），表6(tab:algorithm-comparison)和附录A1列头都是`PyVRP-HGS | ReSETP-ALNS | MV-HGS-SP`三个真实不同算法。但G-CHINA-REP和P3实际跑的"三臂"是`mother(单视角HGS收敛)/ablation(去SP多视角轮转)/full(含SP完整体)`——全是MV-HGS-SP同源内部消融，**没有ReSETP-ALNS这一列**，P3封存CSV列名和论文表A1要求列名对不上，P3不能直接喂论文表。

**关键更正（不要把这当成"从没跑过独立ALNS"）**：独立ALNS其实在**P0等算力四臂门跑过**。P0的D臂`run_arm_d`调用`run_project_alns(bundle, common.solution, mechanism_mode=True)`（P0脚本行147-153，即"本项目独立机制ALNS"=论文的ReSETP-ALNS），在完整China81模型、等墙钟、H6三题(cn-jjj-25c-03/cn-prd-75c-03/cn-cy-150c-03)×5种子=15单元上跑满。结果`C(MV-HGS-SP) vs D(独立ALNS)=15胜0平0负`，且D明显弱（cy-150 seed4：D=8290.83 vs 母体A=7302.95 vs C=7319.15）。这个独立ALNS包正是2026-07-19被反复降级止损的那个（见[[resetp-alns-independence]]），在China81完整非线性模型上稳定垫底。**所以独立ALNS能跑、跑得稳、补跑技术风险低**；缺的只是论文表6(代表题10次)和表A1(全81题)所需的ReSETP-ALNS列数据——P0的15单元既不覆盖P2代表题(P2未跑)也不覆盖全81题。

**当时为什么这么做（推断）**：P0已用15:0证明独立ALNS稳定垫底且弱于母体，脚本作者到China81正式批(P2跳过、P3全量)时把三臂设成内部消融(测SP机制增量)，大概率判断"D已被P0证垫底，全量再跑它浪费算力"，但这与论文承诺的表头脱节，且此协议范围变更未见任何登记批准(`model_change_approval_register`未查到)。

**须用户拍板二选一**：①给P2代表题(便宜)和P3全量(需追加一个不含SP的独立ALNS臂，数小时机时)补跑ReSETP-ALNS列，匹配论文承诺——独立ALNS弱对MV-HGS-SP是好事，提供真实外部参照；②改论文正文+表6/表A1表头，承认China81对比改为MV-HGS-SP自身机制消融(mother/无SP/有SP)，删除ReSETP-ALNS列与ref:66叙事。Claude建议倾向①（China81是验证"MV-HGS-SP解复杂模型有效性"的唯一完整赛场，只跟自己阉割版比审稿人必问，且正文已写对比+P0已证可行），但属用户科学范围决策。
