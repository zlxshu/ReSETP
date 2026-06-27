---
name: project-plan-overview
description: "ReSETP global project plan — paper for 系统工程理论与实践, what's done / in-progress / left / ETA"
metadata: 
  node_type: memory
  type: project
  originSessionId: c7e19b75-f4af-454a-9cdd-0285773bf61c
---

**ReSETP = 学术论文** 投《系统工程理论与实践》: "兼顾收益公平与时变碳强度的动态协同多车场混合车队路径优化"。多车场混合车队(CV+EV)绿色VRP, 含EV非线性充电(时变碳强度)、时间窗、跨车场、收益公平、动态需求滚动重规划。贡献是**模型+机制**(碳两层排放/协同/公平/动态), 算法是手段但**也必须有创新**。

**算法目标(2026-06-19 user纠正了我之前的口径)**: 主线=**DR-ALNS真训练出来且有创新**; 退路=**创新的普通ALNS**(DR实在跑不通才退到这); 真正竞争门槛=**干过GA-VNS/GA/PSO及其混合**(常见强启发式)。**SA是地板**——它是最烂算法之一, 赢SA只算"合格", 从来不是卖点。故旧"碾压SA=主线"口径作废。

**角色铁律**: Claude=只思考/判断/写Codex提示词, 禁止运行或修改代码、禁止开workflow/ultracode(user限额宝贵)。Codex=执行。关键核验才允许Claude亲自读仓库, 其余交Codex。不要被跑一半就停的结果误导。

**Codex不自创算法铁律(2026-06-19, user实证多次失败=Codex缺算法设计能力)**: 对比基线一律复刻/适配现成实现或论文设计——仓库有→适配结合, 无→GitHub找现成再适配, 组合型(如GA-VNS)用仓库GA/VNS原材料+照Zotero论文设计拼。基线集由**文献定义**不受仓库局限。**Claude负责整理Zotero各论文用的主流对比算法清单**(每篇: 主算法/对比基线/问题类型像不像我们rich VRP), 作为ALNS与DR-ALNS要复刻并赢过的对手。对比目标=拿ALNS/DR-ALNS赢过这些文献主流算法(非只赢SA)。

**已完成**: 模型(论文§2)✓; 碳价bug修复✓; E7动态bug修复✓; 词汇规范化✓; §4.6碳段+§4.9管理启示(数字临时占位)✓; F5b碳压力图✓; T6/F3 CV基线标签修正✓; 图片美观重制(编译干净20页)✓; 诊断C1/C2/D✓; 预算公平修复P2a/P2a-Iter✓。

**ALNS碾压SA — 真相已查明(2026-06-16晚, 提示词③, 纠正"基线丢失"误判)**: winner kernel算法健康、碾压成立(干净子进程环境跑原生run_winner_kernel, 100-01逐seed复现金标准£4878/seed2£4779/零违约/配方审计PASS)、代码没丢(只是从未提交, 现已commit固化024579d, winner首次进git)。上一轮"退化/永久丢失"是误判(被PPO污染进程的£5745误导), 已纠正。**真问题=winner kernel非自包含确定性bug**: 同函数同seed, 干净子进程£4779 vs PPO的evaluate_policy同进程£4909; 根因待提示词④实验定位(静态grep未见全局随机源; 候选=子进程PYTHONHASHSEED继承/dict-set顺序/winner_operators.py:195无seed默认rng分支)。影响范围: 论文主线(碾压/150-200/大重跑)在隔离环境跑基本可靠; 非确定性主要害PPO lane。提示词②gate失败是其症状(正确拦下); 提示词①150输/200平很可能真实(待确认隔离性), 若确认则印证"碾压取决约束松紧"。下一步提示词④=修winner kernel非确定性使其任意进程复现£4878, 修前不训PPO。详见 [[alns-crush-root-cause]] "🔑真相修正"段。

**最新蓝图(2026-06-16晚定稿, 按依赖分阶段)**:
- **阶段0｜地基(最高优先, 进行中)**: 提示词④修winner kernel非确定性→任意进程确定复现£4878→固化确定性锚。出口: official_winner_kernel在污染进程也复现; PPO self-check gate过。**地基不牢不推主线(user铁律)**。详见 [[alns-crush-root-cause]] 真相修正段。
- **阶段1｜算法强化(0完成后)**: 1a训PPO(self-check过→100k smoke→1-2M pilot→论文级; 目标PPO≥AlphaUCB-in-env>random, 证DR真实学习增益; winner kernel内部=AlphaUCB[20,8,2,0.05]α0.08选算子+HillClimbing接受+q/温度默认, 即DR要超越的对手; PPO看11维obs动态调全4维(destroy,repair,q,阈值接受)); 1b加强对比基线(审稿硬需求, 与1a并行: 标准ALNS+贪心构造+小算例Gurobi/OR-Tools最优或下界); 1c算法叙事=贴近最优下界+远快+DR可学习自适应+碳感知算子(碳消融)。
- **阶段2｜主线重跑(1稳定后)**: 设PRIMARY=winner kernel(确定性版)→重跑E1-E7→重生成T3/T4/T5/T7/T9+F1/F2/F5→碳数字占位→终值。R2那批表图是坏ALNS-Wouda次优结果, 必须全废重跑。
- **阶段3｜撰写与稳健性**: 写§3算法章(DR训练到起作用+强基线对比+下界gap)+§4.4算法对比重写+确认/重跑150/200+算例鲁棒性。

**关键决策(2026-06-16晚)**:
- **"碾压SA 50-100%"目标被否(数学不可能, Claude实事求是拦下)**: 100-01 winner£4779中固定成本£2560占53.6%, 路线数有容量下界, winner与SA都逼近同一物理下界, 8.8%已是接近下界的显著优势; 强追只能注水/弱化基线反招审稿质疑。**代差跨越正确实现=对手更强(加标准ALNS/Gurobi下界)+DR真实学习增益+贴近最优, 非碾弱对手更狠**。审稿真实风险是"对手单薄/创新点不清", 非"赢得不够多"。
- **算法贡献定位=数据驱动(user选)**: 先修④+训PPO, 拿PPO vs AlphaUCB vs SA真实差距再定包装; "加更强基线"无论如何要做。
- **提示词①150输/200平很可能真实**(原生kernel隔离跑), 待④后确定性环境复核; 印证"碾压取决约束松紧非规模"。三个施工决策(最终客户数口径/阈值接受/不加dynamic_events)已落提示词①②。

历史: 旧Track C的PPO(2026-06-15)建在错误算子底座(大q+限宽+纯距离), 实测E-UK100_03三seed全输random, 已HALT_RANDOM收口, smoke_100k仅作管线凭证。基建(env/worker/脚本)复用。

**还差(以上方蓝图阶段0-3为准)**: 当前焦点=阶段0提示词④(修winner非确定性)。①winner kernel碾压SA 8.8%(100-01)健康但非自包含确定性待修; ②PPO底座已换winner(6+3算子/阈值接受), gate待④后过再训; ③150/200已跑(150输/200平待确定性环境复核); ④设PRIMARY重跑E1-E7+重生成表图; ⑤碳数字占位→终值; ⑥§3算法章+§4.4重写+加更强基线(标准ALNS/Gurobi下界)。

**ETA**: ALNS优化+重跑+重写是关键路径, 受多轮迭代影响, 量级为数周。论文最终文字打磨由user手工完成。

**2026-06-19 离线体检①(offline bandit lane)=HALT_COLLECTION_COST(判不出PROMISING/WEAK)**: ⑥pilot前插的便宜离线闸——用已有traces验DR能否超random_block/AlphaUCB。Codex实现 solver/rl/dr_alns_ppo/offline_bandit.py(audit-existing/collect/summarize-partial/train/evaluate/report)+RL测试(路径/覆盖/.pt可载/verdict不注水门禁), 提交a5ed83b。核心: (1)旧报告不能当训练集(钉死); (2)本地补采CPU-bound太慢, 2.85h仅1625行/13ep(~13min/ep), 未过4000行最低门禁(覆盖872unique>150过/零违约/完整性过); (3)Codex诚实halt未训未跑100-01不注水。solver164/RL99过, 未碰cost/check/evaluation。报告在 solver/reports/dr_alns_ppo_v3_block_dr_alns/offline_bandit/。

**破局设计(Claude, 待user确认, 仍思考阶段)**: 把估计量从"训策略+重跑rollout"(贵)改成跑现有1625行——(A)监督式上下文可学性探针: 比"上下文感知"vs"仅block边际均值"对block收益的held-out预测力, 提升=DR对AlphaUCB有headroom=PROMISING, 打平=WEAK(学函数跨872动作泛化故每臂1.9样本不致命; 前提特征维度别太高); (B)若采集记了propensity则OPE/doubly-robust估greedy策略价值。零新采样可能直接出verdict, 不够再聪明补(并行CPU采集/一次性可复用数据集/因子化动作; 采集CPU活GPU无用; 4000门禁是为per-arm制表定的, 监督探针须据估计量重导最小N)。3待audit: 采集策略+有无propensity / 一行是什么决策+状态特征维度 / collect能否并行。

**关键(给真bar定位)**: 探针只判"DR值不值得上GPU训", ≠"赢GA-VNS/GA/PSO"(user真bar)。且若旧判断"PPO天花板≈winner kernel"成立, DR能否过真bar主要取决于winner-kernel级ALNS本身是否已干过GA/PSO/GA-VNS——故**最便宜最高值、且不受collection halt影响的未知=直接测winner kernel vs GA/PSO/GA-VNS的gap(无需学习/无需采集)**, 应并行做。阶段1的1b基线集据此扩为: 标准ALNS+贪心+Gurobi/OR-Tools下界 **+ GA-VNS/GA/PSO及混合(user定的真竞争门槛, 必须实现且被干过)**。

**🎯 2026-06-20 大重跑 E1-E7 完成(M1 canonical, commit 9da7f8b, codex/reporting-pipeline)= 论文正式数字锁死**: 471/471/零失败/零违约/无<16000eval(E1=30/E2=141/E3=60/E4=160/E6=70/E7=10)。Stage0 gate: ALNS£4878.3318/seed2£4779.0534/公平SA£5346.99零违约(**£4878锚精确复现,M1确定**)。T3-T9+F1-F6/F5b重生成→docs/paper_submission_final; **F4修好非空**(96行/var16860); **碳3298.8→2330.7 kgCO2e**(清单 formal_winner_20260619/placeholder_replacements.md); latexmk过; solver166过/RL102过; cost/check/evaluation未进提交。复现锚=/opt/anaconda3/bin/python3.13(3.13.9)+numpy2.3.5+winner全关+PYTHONHASHSEED=0。报告 solver/reports/formal_winner_20260619/。上方"还差"里 **④重跑E1-E7、⑤碳数字终值 已完成**。小尾巴:E2有1条stale DR-ALNS provenance行(T3已排除,无害)。注:这是"正式数字+现有风格表图"完成, 图表顶刊级重设计(壳/范本)是否并入待确认见[[figure-redesign-task]]。**下一步: M1空闲→发轨②提示词③做基线正式对比→移盘Windows训DR(单盘串行)。** handoff文档+记忆快照已入仓库(docs/handoff/), GitHub私有备份 zlxshu/ReSETP。

**🧪 2026-06-21 [x86/DR] DR reduced-budget pilot07 = WEAK → DR 维持 future-work**: x86(`D:\ReSETP`/`dr-x86`)同降预算趋势 pilot(只训 100_02、`eval_budget=1500/block64/6 actors`、136 ep、route→energy→carbon、零违约、device=cuda)。同机同降预算口径 ppo_block 相对 alpha_ucb_block：100-01 **+1.63%** 但 100_02 **-4.77%**、100_03 **-6.06%**，且未稳过 random_block → **WEAK**(只报 x86 内相对%，绝不与 M1 绝对值横比；全对手成本经 py313 worker)。**论文算法主线维持 ALNS winner kernel + 机制贡献(碳/协同/公平/动态)；DR-ALNS 归 future-work/learnable lane。** 全预算训练在 x86/M1 本机均不可行(单局 85min~4.2h 已实测)，真要全量需云端。详见 HANDOFF 变更日志 2026-06-21 与 [[alns-crush-root-cause]]；产物在 x86 本地 `solver/reports/.../pilot07/`(最小集已 `git add -f` 回 dr-x86，tip `101a4819`)。

**🔬 2026-06-22 [x86/DR] pilot08 WEAK + pilot09 诊断 → DR headroom 在搜索参数、非算子选择**: pilot08（课程小→大、稳定性齐全、8422ep、无塌缩、选最优 checkpoint0240）900s 等墙钟评测 = **WEAK**（vs AlphaUCB train +0.69% / held +0.24% ≈平手，wins 3/5、2/5）→ **印证"PPO 天花板≈AlphaUCB"**（learned 算子选择对好 bandit 无 headroom；比 pilot07 更干净有结论：这次训练全做对了仍只持平）。pilot09 文献优先诊断（Zotero+Daysalilar/Reijnen/Narayanan/Wan）：stochastic/deterministic PPO 都救不回，**但固定算子=AlphaUCB、只扫搜索参数 q/threshold/exploration，最优静态 q0.40/thr0.0/exp0.05 比默认 AlphaUCB +3-4.6%** → headroom 在搜索参数。**Claude caveat**：该优势来自更优**静态**参数（默认欠调），动态/学习是否超"最优静态"待验；block_meta 成功 bar=打过最优静态（非默认 AlphaUCB，那是 strawman），需 900s 复核。**论文主线仍押 ALNS winner+机制+轨②基线（M1）；DR=future-work，但 pilot09 给了更精确救法方向=小动作空间 block_meta**。详见 [[alns-crush-root-cause]] 与 HANDOFF 2026-06-22。

**✅ 2026-06-27 [x86/DR] Pilot16/Pilot17 全规模 DR-ALNS 结果**: 新结构（候选生成器 + continue/stop/restart search-control）在全规模三班倒 `50/75/100/150/200c × 3` 上可稳定长训：11280 episodes、375 updates、37 checkpoints、每规模 2256 episodes、零违约、py313/NumPy2.3.5、CUDA、entropy 未塌缩、candidate/search-control 都持续使用。Pilot17 修正评测口径（按模型 7 头 action space 恢复环境，不能用旧 evaluate_policy 剪掉新头），同预算 `eval_budget=20/block4` 比 default AlphaUCB / tuned AlphaUCB-meta / random / SA / official winner。结论 **ACCEPTABLE_PASS but NOT TARGET_PASS**：相对最强外部基线为 50c +0.12%、75c +0.38%、100c +1.01%、150c +0.99%、200c +0.36%，全规模均非负但平均仅 +0.57%，离 user 目标“领先第二名至少 10%”很远；PPO 120 行提前 stop（常只用 8-9.3/20 eval），说明 search-control 学到早停捷径，不能包装成强算法。**当前项目判断**：x86 DR lane 证明了“可训练、可全规模、可小幅非劣”，但没有达成“强大的 DR-ALNS”。若继续救，优先修 reward/stop/acceptance 与独立 held-out 全规模算例；论文主线仍应同步 M1 普通 ALNS/强基线对比。
