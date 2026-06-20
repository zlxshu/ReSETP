---
name: baseline-algorithm-catalog
description: "ReSETP 算法对比基线清单(Zotero整理): 各论文主流算法+item key+复刻来源+推荐基线集; ALNS/DR-ALNS要复刻并赢过这些"
metadata: 
  node_type: memory
  type: reference
  originSessionId: c9cbe929-a2d3-4aa0-8abb-ddd9fdf75852
---

2026-06-19 Claude 从 Zotero 整理(user要求: 拿ALNS/DR-ALNS对标**文献主流算法**并赢过; Codex不自创算法只复刻/适配, 见 [[project-plan-overview]] 铁律)。库=My Library 422 items。核心集合: 双碳多能源混合车队(B6VJ6JYG) / VRP.etl(ZMMFYZ2R) / 本方向(69ZJICJM) / 优选(65UIRL2U)。

**🔑 keystone**: 周鲜成2021《绿色VRP模型与求解算法综述》[DTPTHXZV] 发在**系统工程理论与实践(本文目标期刊!)** Vol41(1):213-230。算法3层分类=精确/启发式/元启发式, 定义了目标期刊对算法对比的预期。另两综述: 张玉玺2025 带TW-VRP元启发综述[NL7GPYZ3]; 刘云忠2005 VRP综述[S9P89LEV]。

**经典元启发基线源(tag高置信)**: GA=姜大立1999[EEMNDCZ3]; PSO=李宁2004带TW[BQA7K9U8]; SA=杨宇栋2006改进SA[UQ5R5JHF](仓库**已有fair-SA**); TS=符卓2017[WWLNPHMF]; ACO=何美玲2023改进蚁群+VNS[DJWRJRWX](+郑荣2023[EIU6WYTZ]/潘茜茜2016[UU68BV7G]); VNS=Woller2025 EVRP-VNS[VSUPJ3V7]; ALNS=吴廷映2023[4MNLGZZF](仓库**已有winner kernel**); LNS=高娇娇2024[TAQUPN3F]/张婧文2025[NC2MAHE4]。
**混合**: GA-SA=Wei&Zhou2014[S8IADZGI](就在本主题集合); 混合GWO=马祥丽2025[J9SJK8C4]; 智能水滴IWD+LNS=张婧文2025[NC2MAHE4]; GA-VNS=无单篇, 用GA+VNS原材料照文献拼。
**问题最接近(最该赢)**: 邱莹莹2024低碳混合车队EV+CV[4U7I5H4P=46ZIIKQS, **同组干宏程, 最像**, 算法待深读]; 李英2020 EV/CV混合车队配置+路径[2P2MP7GH, 算法待深读]; 郑荣2023多中心低碳冷链ACO[EIU6WYTZ]; Araghi2025 FSM-CVRPTW+移动快充[6HMZYRBZ, 待深读]。
**DRL/RL同类(DR-ALNS定位,引/比)**: Wan2025 DRL-FSM[6VNYWJ7Q]; Daysalilar2026 课程DRL-EVRP[GKWV7NHV]; Narayanan2022 RL-EVRP-V2G[BCBMVPMB]; Herdianto2025 ML引导启发式[X7N42RUB]。

**Claude推荐基线集**: Tier A(经典元启发+user旗舰混合)=GA/PSO/SA/TS/ACO/VNS/GA-VNS; Tier C(DR定位)=Wan/Daysalilar/Narayanan。诚实: 忠实复刻7+元启发是大工程, 建议先做SA(有)+GA+VNS+GA-VNS+ACO, 再加TS/PSO。
**⚠️2026-06-19 user调整**: (1)**邱莹莹2024踢出benchmark**(太老/不作对手, 仅留related work引用); (2)**尽量用2020年以后的算法**——GA/PSO/SA/TS/GA-SA库内源(姜大立1999/李宁2004/杨宇栋2006/符卓2017/Wei&Zhou2014)偏旧,仅作机制参考, **竞争性设计改从post-2020来源(GitHub/近年论文)取**; 库内post-2020设计源=ACO何美玲2023/VNS Woller2025/ALNS吴廷映2023/LNS高娇娇2024·张婧文2025/IWD张婧文2025/GWO马祥丽2025/混合车队李英2020/DRL Wan2025·Daysalilar2026·Narayanan2022。(3)user要求**一次性读全post-2020算法论文抽设计**(本会话进行中)。
**待深读(写Codex复刻提示词前)**: 优先 邱莹莹2024(最近问题+同组benchmark规范)+张玉玺2025(元启发分类+标准参数); 各单算法源论文(姜大立/李宁/符卓/杨宇栋/何美玲)在实现对应算法时逐篇读取设计。fulltext经MCP取回常>25k token超限, 用python从落盘JSON切片读(本会话已验证)。
**获取规则**: 仓库有→适配结合; 无→GitHub找现成再适配; 组合型→原材料+照Zotero论文拼。Codex第0步先audit仓库现有元启发实现/原材料。

**🔌 公平对比harness接口(2026-06-20 Claude读码核实, 给Codex②用)**: 主仓 /Volumes/移动硬盘（512G）/ReSETP, branch codex/reporting-pipeline。
- harness=solver/src/setp_solver/search/alns_crush_v2.py: FAIR_SA_EVAL_BUDGET=16000/FAIR_SA_MAX_RUNTIME_SECONDS=900; run_task1=公平SA(写fair_sa_reference_costs.json), run_task3=winner kernel vs公平SA+scipy Wilcoxon(_wilcoxon_vs_fair_sa)+判级_task3_verdicts(碾压=mean_delta<0&p<0.05&wins>=8&std_ok / 小幅领先 / 持平 / 失败)。
- 算法入口: candidates.run_candidate(label, bundle_dir, seed, eval_budget, max_runtime_seconds, initial_solution=warm) 统一派发("scikit-opt-SA"是其一); winner=winner_operators.run_winner_kernel(bundle_dir, WinnerKernelConfig(algorithm,seed,eval_budget,max_runtime_seconds,include_route_elimination))。
- 解结构 solution.py: Solution{routes[Route(vehicle_id,vehicle_type,home_depot_id,node_sequence)], charging_actions[ChargingAction(vehicle_id,station_id,energy_kwh,occupancy_minutes,charge_start_second)], cross_site_services[CrossSiteService(customer_id,served_by_depot_id)]}。
- 评分=cost.evaluate + check.check_solution(单一真值源, 禁改语义); evaluation.py有EvalBudget(record/target_count/reached_target)计评估次数+penalized_obj/score_candidate/model_cost。暖启动=candidates.make_shared_initial_solution(bundle)。bundle=bundle.load_search_bundle(root/rel_dir)。
- 算例 INSTANCE_DIRS(alns_crush.py:45): "100-01-24h"=models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113; "L-main"=…/E-UK24h-三班-01。150/200未生成。
- 金标准锚: 100-01 winner mean£4878.33/seed2£4779.05(32路线)/公平SA£5346.99(winner碾8.76pp); L-main winner£8351≈SA£8319(持平)。**公平命门**: 每个基线目标计算必须走同一evaluate()/penalized_obj+过EvalBudget计数+封顶16000+暖启动make_shared_initial_solution(V1不公平就是预算错配)。基线必须解码成ReSETP可行解(复用candidates现成构造/修复处理EV充电/时窗/多车场/cross-site, 别重造可行性)。
- 环境: 全用系统Python /opt/anaconda3/bin/python3.13 + numpy2.3.5跑(RL venv numpy不同→winner漂到£5696输SA, 故基线/solver必系统Python)。
**两条详细Codex提示词(含共同背景+读论文清单+中文论文设计转录)已于2026-06-20本会话输出在transcript**, 待user审后发Codex。

**✅结果(2026-06-20, Codex两条都回, 均诚实)**:
- **轨①离线探针=PROMISING**: Probe A 上下文模型显著优于动作均值基线, r2_delta mean=1.052764, 95%CI=[0.956931,1.157185](不跨0)。Probe B=INCONCLUSIVE_SUPPORT(random_block仅125行/目标动作精确命中0次, 不当OPE性能证据)。文件: solver/rl/dr_alns_ppo/offline_probe.py(+test) + …/offline_bandit/probe/{offline_probe_report,audit,curriculum_training_plan}.md; 21测试过; commit d137b9b/70b1df0。**含义: DR有可学上下文信号→"拉垮"根因是训练不稳非无信号(印证我们的判断)→绿灯上GPU课程训练(curriculum_training_plan.md已ready)**。TODO sanity: r2_delta=1.05偏大, 核是否泄漏假象(但episode分组CV+合成数据单测verdict翻转正确→可信度高)。
- **轨②8基线=HALT_BASELINE_THROUGHPUT(诚实, 未出正式对比)**: 8基线已接统一接口/小预算零违约/保护文件无diff/3测试过; 但eval/s仅3.96–11.04 < 16000÷900s=17.78硬门槛, 没产出"ALNS赢8基线"结论。文件: solver/src/setp_solver/search/{metaheuristic_baselines,metaheuristic_baseline_runner}.py + solver/tests/test_metaheuristic_baselines.py + baselines/{audit.md,report.md,comparison_table.csv}; commit d088664。**Claude诊断**: 每eval太重, 疑每步全量re-decode+全量check_solution超出被计数的单次evaluate(winner kernel靠delta/精简达17.78+)。**下一步待定(公平口径=user方法学决定)**: 先profile+削每eval冗余(每个计数eval≈一次evaluate, full check延到接受/末尾, 缓存decode)使≈winner eval/s保16000/900s; 仍不够则(A)等墙钟公平重跑全部锚 或 (B)保16000 eval放宽900s上限+附报运行时。注意16000 eval对种群法(GA/PSO/GWO/IWD)可能偏少不收敛→可能反而低估基线, 不利于"诚实赢"。

---
**📐 算法设计提取(2026-06-19, Claude读7篇正文+7篇摘要, 给Codex复刻用)**:
- **ACO(何美玲2023 IACO [DJWRJRWX], 计算机集成制造系统/EI)**: 改进蚁群+VND嵌入局部搜索。状态转移概率融入节约值sij+时间窗偏差devij+宽度widthj(式12-13); 信息素自适应挥发ρ(t)=0.95ρ(t-1)→ρmin(式16),Δτ=(zmax-z)/z·Q; VND邻域=插入算子+交换算子。参数: m=20/iter=100/r0=0.1/ρ=0.8/ρmin=0.01/α=1/β=2。benchmark=Solomon C/R/RC 25/50/100; 对手=传统ACO+超启发GA+其他改进ACO。
- **VNS(Woller2025 [VSUPJ3V7], arXiv2511.09570, CEC-12竞赛冠军CGVRP/EVRP)**: Algorithm1=construction→perturbation→local_search循环, ITERS_MAX=r×n(无改进重启), 新鲁棒repair(改自Zhang2018), 从GRASP演化。**最强VNS源, EV相关, arXiv大概率有码+公开benchmark**。
- **ALNS(吴廷映2023 [4MNLGZZF], EI)**: 经典Ropke-Pisinger。destroy=Shaw相似(R=α·dist+β·time+γ·|li-lj|)+random; repair=greedy+regret; 自适应权重w=(1-δ)w+δπ/θ轮盘赌; SA接受; 15000迭代/段2000/评分σ=33,9,13/降温0.99975。**仓库已有winner kernel同族**。
- **LNS(高娇娇2024 GLNS [TAQUPN3F], CSCD扩展)**: 扫描sweep构造+LNS(random/相似removal, 最远/后悔值repair)+SA接受。参数: max_iter1000/移除ε=0.3/SA Φ=0.05/降温μ=0.95。对手=CPLEX。
- **IWD(张婧文2025 IIWD [NC2MAHE4], 物流科技, 问题=MDHFVRPTW最接近)**: 智能水滴+LNS+SA, 单串编码(仓库/车/客户)。**直接给对手对比表: TS/VNS/GA/MA/PSO 在Cordeau MDVRPTW pr01-10(48-288客户/4-6仓库), 源=BEN&ENNIGROU2018**。
- **GWO混合(马祥丽2025 HGWO [J9SJK8C4], EI扩展, 张惠珍组)**: GWO+GA交叉+LNS破坏修复; 自然数编码; 罚函数。NIND=50/MAXGEN=350或1000。引言谱系=GA/ACO/PSO/狼群/Memetic/蝙蝠/SA/花朵授粉。
- **SS+ACO(李英2020 SS-MACO [2P2MP7GH], 系统管理学报, 问题=EV/CV混合车队配置+路径最接近)**: Scatter Search分簇定车队配置(扫描多样性+交换/分离/合并算子+参考集50%质量50%多样)+改进蚁群定路径。对手=CPLEX。成本比FCV:FEV:CCV:CEV=0.3Dr:0.9Dr:1:0.4。
- **DR-ALNS同类(神经RL,不复刻,定位/差异化)**: Daysalilar2026课程PPO-EVRPTW[GKWV7NHV](3阶段课程+改进PPO+异构图注意力,N=10训练泛化5-100); Wan2025 DRL-FSMVRP[6VNYWJ7Q](FRIPN+MDP秒级近优); Narayanan2022 RL-EVRP-V2G[BCBMVPMB](**RL vs MILP vs GA, RL快24×距最优<20%**)。**关键差异化: 它们是end-to-end神经构造(learning-to-construct), 我们DR-ALNS=RL导ALNS算子(learning-to-search)→论文卖点**。
- **充电/模型类(引用非对手)**: Araghi2025 FSMCVRPTW移动快充Gurobi[6HMZYRBZ]; Duc EVRPTW无线充电扩展Schneider[PVSQESUX]; Herdianto2025 ML引导启发式特征[X7N42RUB]。
- **综述**: 周鲜成2021[DTPTHXZV]目标期刊3层分类; 张玉玺2025[NL7GPYZ3]VRPTW元启发综述。
**Claude精化推荐复刻集**: 核心(post-2020设计齐全)=GA+PSO+VNS(Woller)+ACO(何美玲)+GA-VNS; 强/可选=TS/LNS(高娇娇)/GWO(马祥丽)/IWD(张婧文); DR peers引用对比=Daysalilar/Wan/Narayanan。GA/PSO/TS仓库源旧→GitHub取post-2020设计+综述标准参数。

**✅2026-06-19 user锁定复刻集**: 必做8个=GA+PSO+VNS(Woller)+ACO(何美玲)+GA-VNS+LNS(高娇娇)+GWO(马祥丽)+IWD(张婧文); **TS=仅当仓库已有现成才做**(Codex audit定); **DR同类(Daysalilar/Wan/Narayanan)升级为"深读偷设计"加强我们的DR-ALNS/ALNS**(user判断: 他们思路大概率显著优于现状, 是修复DR拉垮的捷径, 非仅引用对比)。两条Codex提示词(轨②基线复刻+轨①离线探针)已获授权起草, 待Claude读完DR同类设计后动笔(peer思路喂进DR那条)。

**🔧 DR-ALNS/ALNS改进设计(2026-06-20, 从DR同类偷; user: 他们思路优于现状=修复拉垮捷径)**:
- **①课程学习/约束分解(Daysalilar CB-DRL[GKWV7NHV], 最关键)**: 其诊断=我们病(端到端PPO密约束EVRPTW随机初始化训练失败: 稀疏奖励+违约梯度崩溃+退化策略躲难客户=我们HALT_RANDOM/算子塌缩)。解=3阶段约束课程(A拓扑+容量 k<10 → B+电池能量 10≤k<20 → C+时窗 k≥20), 逐步激活罚项+phase-specific PPO超参+value/advantage clipping+自适应LR; N=10训练零样本泛化到N=100。**搬DR-ALNS**: 按目标复杂度分阶段训算子策略(A路线数/距离→B+EV充电→C+碳+公平→D+动态), 别一上来全ReSETP目标=修拉垮捷径。
- **②动作掩码(Narayanan QuikRouteFinder[BCBMVPMB])**: mask不可行(u→node)对(容量/SoC/时窗)。搬DR-ALNS: mask当前态无效算子(无可清空路线时route-elimination、同质车队vehicle_type_swap)→直击算子塌缩(vehicle_type_swap独大)。
- **③稳定baseline(Wan FRIPN[6VNYWJ7Q])**: REINFORCE用同实例N条轨迹均值作shared baseline(比greedy/critic稳, 抗实例间高方差)。我们DR-ALNS实例方差大→可稳PPO优势估计。
- **④奖励整形**: reward=-total_cost+显式分量权重(Narayanan A1-5; Daysalilar λ=100 fleet罚), 课程内分阶段奖励。
- **⑤更富状态(Daysalilar异构图注意力: 客户/站/场分projection+global-local attention+FiLM; Wan node+fleet+remaining-graph嵌入)** vs我们11维平obs。重(改架构), 课程/掩码后再议。
- **⑥定位验证(战略)**: Daysalilar未来工作明说"把神经策略集成进元启发算子"=我们learning-to-search的DR-ALNS; Narayanan示端到端RL比GA差~20%质量(GA胜)。故端到端神经=快但质量低; DR-ALNS=保ALNS质量+学习自适应=论文novelty+回应"为何不用神经构造器"。
- **⑦track②红利**: Narayanan §2.3=完整EVRPTW GA(染色体=路线, NN初始+插入改进, 二元锦标赛, common-nodes/arcs交叉, 10%变异[随机/最近node·route删除], 精英top10%+随机)→直接做我们GA基线; 给RL-vs-GA-vs-MILP对比表式。
**战略含义**: user直觉对——DR"拉垮"根因大概率是**训练不稳(课程可修)**非"无信号"。离线探针①仍是便宜信号闸; 真修复=课程+掩码+shared baseline重训。fork(待user): 探针优先(便宜闸→有信号再GPU课程训) vs 探针∥课程重设计并行。
