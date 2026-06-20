---
name: alns-crush-root-cause
description: "Why ReSETP ALNS only ties SA, and the ALNS-internal route-minimization thesis to CRUSH it (no SP escape hatch)"
metadata: 
  node_type: memory
  type: project
  originSessionId: c7e19b75-f4af-454a-9cdd-0285773bf61c
---

**目标**: ALNS系列(尤其dr-alns与wouda)不止打赢SA, 要**碾压**。SA在论文里是垫底基线, ALNS输它=根因没找到。**只能用ALNS范式内部办法(destroy-repair-learn), 严禁SP/集合划分/精确求解逃生口**(user明确否定了那个方向, 说牛头不对马嘴)。

**真根因思路(Claude读码后的判断, 待Codex实验证实)**: 主成本是**路线数固定成本**。cost.py:evaluate 里 cost_fix = len(routes)×£80。L-main约65路线×80=£5200, 占总成本£8284的~63%。即**60%+的成本由路线数决定, 距离(cost_km £0.35/km)只是小头**。所以碾压SA = **把路线数压到比任何现有解更低 + 最优车型混合**。ALNS的大破坏-修复能一步清空整条路线再重分配(路线消除), SA的单客户relocate/swap做不到(清空一条路线的中间步会临时溢出被拒, 过不去山脊)——**这正是ALNS本该碾压SA的维度**。

**4个ALNS内部缺陷(代码证据)挡住了它**:
1. 修复评分用**纯距离**不是真成本(candidates.py:1415 _path_repair_delta_score 用 _route_sequence_distance; alns_wouda.py fast模式 _route_distance)。对£80/路线的cost_fix跳变完全盲视, 不会主动减路线。
2. 移除量 q 太小(DR-ALNS~2, Wouda cap 12), **不足以清空一整条路线**。
3. **没有"路线消除"算子**(移除最弱整路客户、强制重分配到其他路线、仅当路线数下降才接受)。
4. 接受准则**逐行就是SA**(alns_wouda.py:276 metropolis exp(-Δ/T) + :296 几何降温)。"ALNS"动力学=SA动力学, 难怪只追平。还**缺嵌入式局部搜索(2-opt/Or-opt/relocate)精修**——SA本质就是局部搜索, ALNS无LS则解粗糙磨不细。

**修法(全在ALNS内部)**: ①修复评分换真成本regret(看见£80/路线); ②加路线消除大邻域+自适应大q; ③接受换真ALNS(RRT/LAHC)+真自适应权重去SA同构; ④destroy-repair后嵌入LS精修。预期: 100-01有明确减路线空间(DR 31路线£5247已优于SA 33路线£5331), 修好后可能压到<31路线碾压; L-main headroom较薄(DR减2路线反更贵因全CV), 但"减路线+保留最优车型混合"的联合优化可能突破£8284。

**已验证赢家内核**(candidates.py:148 require_charging_signal=False + 1370 _regret_reinsert_removed + 1390全枚举 + 1410新CV路线兜底 + 能全CV)是修复底座。见 [[algorithm-pivot-ca-alns]]。教训: 不要拿跑一半/未验证的agent结论当数。

**2026-06-15 V2 验证结论(公平SA基线, 推翻了我上面的"4刀"思路)**: 我设计的4项加料(真成本修复/路线消除/真接受RRT/嵌入LS)经消融**大多有害**, 全部默认关闭。真正取胜的是**winner kernel本身(简单的解锁regret ALNS)**, 已抽成干净模块 setp_solver/search/winner_operators.py(manifest: winner_operator_module/public_api/operator_base_id)。
- **100-01: 真碾压成立**——winner_kernel_only 均值 £4878.33 vs 公平SA £5346.99(8.8%差距), 10/10配对胜, Wilcoxon p=0.00098, 且是新best-known(旧best-known £5247, 降~7%, **重跑时需复核这个大跳**), 40/40零违约。
- **L-main: 不能碾压(诚实)**——winner_kernel 均值£8351 ≈ 公平SA £8319(略差), Task2 headroom证实薄, 三信号(公平SA持平+headroom薄+加料有害)都说L-main对所有算法近最优, 物理上压不动。
- **关键认知**: V1的"11%碾压"是拿弱化SA(4000eval vs公平16000eval)比的注水。winner kernel是**正确实现的标准ALNS, 靠实现取胜非靠新颖性**→算法创新点必须来自碳感知算子(用碳消融衡量,非cost)或PPO, 不能靠cost碾压当创新。PPO现实天花板=匹配kernel(从而碾压SA), 不太可能超过kernel。

**⚠️ 2026-06-16晚: 下方V3一度被误判为"退化丢失作废", 但提示词③已证 winner kernel健康、碾压成立(干净环境逐seed复现£4878/£4779)。V3碾压结论实际有效, 真问题是winner kernel非自包含确定性bug(同seed不同进程结果不同)。以文末"🔑真相修正"为准。**

**2026-06-16 V3 决定性验证(⚠️已作废-代码丢失且退化, 见文末事故)**:
- **100-01 碾压坐实且复核通过**: £4878.33是10-seed mean(非单解), 10个落盘解全部check_solution零违约、evaluate重算一致; best具体解=seed2 £4779.05, 32条路线(CV11/EV21)。
- **L-main 判定=甲(碾压物理不可能, 下界证明)**: 路线数容量下界60, 当前winner best 64, FFD诊断61; 现有解**已有55/64条跨班路线**(max span 19.6h)——我猜的"跨班复用大杠杆"不存在, 已经在用了。理论余量≤3-4条路线≈固定成本£240-320(且减路线会推高里程部分抵消)。**这是减路线杠杆上的"彻底失败"=数学下界, 不是搜索没找到。** L-main上winner kernel均值£8351 略逊公平SA £8319(£32, 高方差, 实为统计持平)。
- **算法最终定性**: ALNS在有空间处(100-01小算例)真碾压SA 8.8%, 在近最优处(L-main主算例)与SA统计持平。这是诚实天花板。step-level winner API已暴露(apply_winner_action等), PPO解锁可训。

**2026-06-16 DR/PPO定性升级(读码后钉死, user定调)**: 第3点纠正——**不改名承认DR没用, 而是把DR训练到真正起作用让DR-ALNS名副其实**。读码确认的关键事实:
- **winner kernel内部就有算子选择器=DR要超越的对手**: `_run_winner_kernel_loop`(winner_operators.py:383) 用经典 **AlphaUCB([20,8,2,0.05], alpha=0.08)**(alns_wouda.py:253 `_make_operator_selector`)选destroy/repair + **HillClimbing接受**(默认, SETP_ALNS_CRUSH_TRUE_ACCEPTANCE=0; 注: V1说的"接受=SA"已被V2推翻, winner kernel实际是HillClimbing纯爬山) + **q/温度固定默认不调**(raw_action传-1,-1, 让destroy算子自决remove_count_q=None)。
- **现有PPO底座仍是错的(未换)**: worker.py:24 `DESTROY_IDS=[D1..D5]`(5个) + `from .operator_manual import apply_destroy,apply_repair`(非winner算子), env.py:31 action_space=[5,3,10,100]。这正是上轮smoke输random的根因(HALT_RANDOM.txt: "old operator base, superseded")。winner step API造好了但worker没接上。
- **winner算子集**(WinnerOperatorSet.create): 6 destroy(random/worst/shaw/whole_route/route_segment/vehicle_type_swap)+3 repair(greedy/regret2/regret3), action_space_nvec=(6,3,10,100); q_idx→fraction 0.10-0.40, t_idx→temp base×(0.10-2.0)。
- **DR起作用的精确判据**: 换底座到winner算子后, PPO看11维obs(env.py:113 gap/停滞/进度/温度/ev_cv比/碳份额/配额松弛/违约…)**动态联合调(destroy,repair,q,temperature)全4维**, 在同底座同16000预算下**统计显著超越AlphaUCB(=winner kernel)且远超random**。AlphaUCB只在算子上自适应、不调q/温度、不看状态——这是PPO的价值空间(DR-ALNS@Reijnen的卖点)。因winner kernel已碾压SA, PPO≥kernel自动碾压SA。
- **公平性风险点**: AlphaUCB-in-env对手须对齐winner kernel(HillClimbing+算子自决q)才能复现£4878锚; 若用worker的sa_accept(SA Metropolis)接受逻辑会偏离→对照不可信。self-check: L1 AlphaUCB-in-env应落£4878量级, 偏向SA £5347则说明没对齐。
- 参考实现在 `Reference Algorithm/DR-ALNS@RobbertReijnen/`(原始DR-ALNS, RL选算子+接受参数, 已含TSP/CVRP/mTSP训练模型)。两个Codex提示词(①150/200算例 ②PPO换底座训练)已发, 见 [[project-plan-overview]] 路径2/3。

**三个施工决策已拍板(user认可, 2026-06-16, 写进精确施工版提示词)**:
1. **150/200算例口径=最终合并后客户总数正好150/200**(非每班)。依据: L-main的"219"就是三班合并删超时后的客户节点总数(100+100+19, 删81超时), instance.json=219。生成法: 改 models/scripts/build_three_shift_instance.py 的每班n_customers(参数化副本勿改原文件), 迭代生成→读three_shift_manifest.json的kept_customer_count→微调直到==150/200; 删超时使最终数不精确, 无法精确命中则报实际值勿事后删客户凑整。起点: 150试每班[66,66,66], 200试[88,88,88]。
2. **PPO第4维=阈值接受(RecordToRecordTravel语义), 非SA**: t_idx∈[0,99]→threshold=(t_idx/99)*0.02*current_obj(0.02对齐alns_wouda.py:241 winner kernel start_threshold=0.02*initial_obj), accepted=(delta<=threshold)。t_idx=0→threshold=0=纯爬山=对手AlphaUCB/HillClimbing, 故PPO接受能力嵌套包含纯爬山(最干净的"DR起作用"证明结构)。在worker层做映射(忽略decode_winner_action的temperature), 不改winner_operators(铁律)。
3. **150/200不生成dynamic_events**: L-main/100-01均export_dynamic=False(build脚本:338), 是静态算例; "三班动态"靠时间窗错时分布体现, 真正动态滚动是E7运行时另施加的协议非bundle自带。提示词①做静态碾压对比, 不碰dynamic_events。

**现成对照框架(提示词①复用勿重造)**: solver/src/setp_solver/search/alns_crush_v2.py: FAIR_SA_EVAL_BUDGET=16000/FAIR_SA_MAX_RUNTIME_SECONDS=900(:36-37); run_task1=公平SA(scikit-opt-SA), run_task3=winner_kernel_only + _wilcoxon_vs_fair_sa + verdict; 算例注册在 alns_crush.py 的 INSTANCE_DIRS。
**换底座接口差异(提示词②避坑)**: 旧worker.py用operator_manual.apply_destroy/apply_repair + random.Random + sa_accept(:88); 新要apply_winner_action(rng须np.random.Generator, 内部含improve_solution_locally局部搜索+评分+flag上下文, 返回actual_evals_added须据实累加)。env.py:31 action_space[5,3,10,100]→[6,3,10,100]。

---

**⚠️⚠️ WINNER KERNEL基线丢失事故 (2026-06-16晚, Claude读码+查git实锤)**:
- **根因**: winner kernel全部代码从未提交git。winner_operators.py/alns_crush*.py/local_search.py/repair_scoring.py/feasible_repair.py/root_cause.py 是untracked(??); winner核心算子在alns_wouda.py(+654行脏diff)/candidates.py(+505行)/evaluation.py(+52行)是M(未提交修改)。HEAD(520e8a2)根本不含winner算子(grep whole_route_removal/regret3_insert_repair/shaw_related_removal/route_elimination_removal 全=0)。
- **V3 £4779/£4878 是在未保存工作区跑的, 之后candidates.py(06-15 22:25)/alns_wouda.py(06-16 08:29)被继续改动→winner kernel严重退化**。当前100-01 winner kernel 5种子(£5954/£4909/£5773/£6024/£6062) mean≈£5745 > 公平SA£5347约7.4%——**连最易碾压的100-01都输SA, 碾压完全消失**。
- **恢复途径全断**: reflog仅2条(从未commit过winner)、无stash、另一worktree(codex/reporting-pipeline)也在520e8a2不含winner、无.bak/.orig。**产生£4878的代码永久丢失**。
- **结论**: V3"碾压坐实/已钉死"作废; 目前无任何可复现的能碾压SA的winner kernel; 论文ALNS主算法暂无可信基线。提示词①Scale-150输SA(£5814 vs SA£5754)+提示词②gate失败(£4909≠£4779)是同一退化的两个症状, 非算例问题。
- **alpha_ucb_env每seed与official kernel完全一致→PPO环境接线正确, 问题纯在winner本体**。Codex两次都诚实HALT未硬撑(提示词①Scale判失败/持平; 提示词②HALT_BASELINE_WIRING), 判断正确。
- **教训(写进 [[feedback-communication-style]] 同级铁律)**: 核心算法代码改动必须立即commit; 碾压基线数字必须绑定commit hash; 否则反复发生。
- **用户已选 A 诊断式还原(2026-06-16晚)**, 提示词③已发(止血固化+诊断+还原, 分阶段可跨会话续作)。用户提示: 此任务可能Codex跨对话长跑, 需放开Codex权限。本任务明确授权git commit + 改alns_wouda/candidates搜索逻辑。
- **诊断关键已查(Claude读码)**: ①评分语义大概率未变——evaluation.py +52行脏diff仅加预算计数/score_reference基础设施, 目标公式 objective=cost+BIG_M×violations 未改; cost.py仅加排序缓存。故退化几乎确定在**搜索过程**(alns_wouda+654/candidates+505的算子/修复/选择/接受), 阶段1须实证确认。②金标准靶子: V3的10解全落盘 solver/reports/alns_crush_v2/task3/solutions/100-01-24h_winner_kernel_only_ALNS-Wouda_seed{1..10}.json + 分解在 taskB_10001_best_verify.json(seed2=£4779/32路线cv11ev21/cost_fix2560/cost_km1377); 用解结构逐seed对比定位退化维度(路线数/车型混合/里程/充电)。③不能简单git回退(HEAD无winner算子, 回退会删winner; diff混合"winner从无到有"+"退化"无中间快照)。④诊断顺序: 阶段0固化commit→阶段1重算金标准排除评分语义→阶段2解结构对比定位退化维度→自适应门(单一明确点则还原, 复杂则停下报告)→阶段3-4还原验证(mean<<SA£5347, best近£4779)→阶段5固化碾压版+重建绑commit hash的新锚。

**🔑 2026-06-16晚 真相修正(提示词③诊断结果, 推翻上方"退化丢失"误判)**:
- **winner kernel健康、碾压成立、代码没丢**: 提示词③用新模块 winner_restoration 在干净(ProcessPoolExecutor子进程)环境跑原生 run_winner_kernel, 100-01逐seed完全复现金标准(seed2£4779/32路线cv11ev21, 10seed mean£4878, max_abs_delta=0, 零违约), 静态配方审计PASS_STATIC_RECIPE_AUDIT(mismatches=[])。Phase1评分语义=金标准。**上一轮"严重退化/永久丢失"判断作废**——那是被提示词②在污染进程跑出的£5745误导。代码"从未提交"属实但已commit固化(安全网2aeb65e→验证024579d→报告04fab62), winner首次进git。诚实: Claude上一轮基于提示词②gate报告误判为退化丢失, 提示词③的"直接跑原生kernel"实验纠正了它。
- **真问题=winner kernel非自包含确定性(bug)**: baselines.run_official_winner_kernel(baselines.py:135) 与 winner_restoration._run_winner_task(:409) 调 run_winner_kernel 的 config 完全相同(seed/eval_budget/max_runtime), 但干净子进程£4779 vs PPO的 dr_alns_ppo.evaluate_policy 同进程£4909(seed2, 均PYTHONHASHSEED=0)。同函数同参同seed结果不同→非确定性。**根因待提示词④实验定位**: 静态grep alns_wouda/candidates/winner_operators 未见明显全局随机源(随机均np.random.default_rng(seed)); 候选=ProcessPoolExecutor(macOS spawn)子进程是否继承PYTHONHASHSEED / dict-set迭代顺序 / 并行vs串行 / winner_operators.py:195 `rng = rng or np.random.default_rng()` 无seed默认分支(PPO env/worker若走此则非确定)。
- **影响范围(降级严重性)**: 论文主线(碾压结论/提示词①150-200/将来大重跑)都在隔离子进程环境跑, 基本可靠; 非确定性主要害PPO lane(self-check多算法同进程跑暴露£5745, 及训练时env内算子稳定性)。提示词②gate失败是此症状(gate正确拦下, 值得肯定); 提示词①150输/200平很可能真实(待确认alns_scale_crush运行隔离性), 若确认则印证"碾压取决约束松紧"诚实预期。
- **下一步=提示词④**: Codex实验定位winner kernel非确定性根因(同进程先跑alpha_ucb_env再跑official_kernel复现£4909 vs 单跑复现£4779的对照, 二分前序污染源; 查PYTHONHASHSEED子进程继承; 查:195默认rng分支)→修(随机源统一接入传入的seeded np.random.Generator, 只接线不改算法逻辑防数值漂移)→验证official_winner_kernel在污染进程也复现£4878→PPO self-check/训练方可信。修前不训PPO。

**🔧 venv差异分叉决策(2026-06-16晚, Claude拍板)**: winner_restoration用系统Python(£4779) vs PPO self-check用 solver/rl/.venv(£4909)是两个不同解释器+依赖环境。若提示词④二分证明根因是venv差异(numpy版本/BLAS后端浮点差异)而非代码读未播种随机源, **默认不动依赖**, 走"环境内自洽": (1)论文正式实验(E1-E7/表图/碾压)全用系统Python金标准£4878不受影响; (2)PPO贡献是"同venv内 PPO vs AlphaUCB vs SA 相对提升%", 环境差异自动抵消, 不需复现系统Python绝对£; (3)PPO lane全部对照(random/AlphaUCB/SA/winner/PPO)统一在RL venv内跑一套; (4)self-check gate改判据=RL venv内确定+venv内winner碾压venv内SA+零违约; (5)报告/方法章明确披露"PPO lane与正式实验用不同数值环境, DR贡献以同环境相对提升衡量"。理由: 动RL venv的numpy去对齐系统Python有破坏torch/SB3风险且不必要。代码兼容层(选项3)对venv数值差异无效, 排除。仅当"PPO绝对数字必须并入正式主表/跨环境一致"才考虑钉依赖→停下等批准(不擅改)。若某环境内部非自确定则是真代码bug, 回查未播种随机源。决策树已下达Codex。

**🔬 提示词④结果(2026-06-16晚): 确诊 environment_numeric_drift(跨环境漂移, 非代码bug)**:
- 系统Python: seed2=£4779, 多次完全一致(环境内确定)。RL venv(solver/rl/.venv): seed2=£4909, 多次一致(环境内确定)。两环境各自确定但值不同。未改代码未动依赖(符合决策树3b)。
- **但Phase4/5暴露更严重事实**: RL venv内 winner 10seed mean=£5696 **反输** venv内fair-SA £5408(输5.3%); winner绝对值£4878→£5696恶化£818(16.8%)。**RL venv这个数值环境让winner kernel退化到不能用**, "环境内自洽"方案在RL venv失效(venv内winner不碾压SA)。£818太大不像浮点噪声, 疑numpy大版本default_rng随机流不同。gate=HALT_VENV_SELF_CHECK, PPO仍禁训。
- **两层问题+解法(提示词⑤)**:
  - 层1(PPO): 根因=worker_client.py:23 用sys.executable启动worker→PPO在RL venv时worker也在RL venv跑算子→退化。解法=worker子进程改用**系统Python**启动(SETP_WORKER_PYTHON环境变量), 算子跑碾压环境, PPO主进程仍RL venv跑torch。已核实可行: dr_alns_ppo/__init__.py为空、worker.py仅依赖numpy+setp_solver+winner_operators(无torch/gymnasium)。注意baselines.run_official_winner_kernel(:135)在RL venv主进程直跑run_winner_kernel得退化£4909, 锚要改走系统Python子进程或用winner_restoration的£4878。
  - 层2(可复现性, 更重要): **winner碾压绑定系统Python的numpy版本, 换环境翻盘**。非bug(元启发式RNG流敏感)但论文**必须钉死并声明numpy版本**, 否则审稿人换numpy复现得"winner输SA"质疑核心结论。phase3未查具体numpy版本差异, 提示词⑤补查+写reproducibility_note+钉版本。
- **论文主线地基仍牢**: 正式实验全系统Python, winner£4878碾压SA£5347/10seed统计显著/环境内确定, 钉死numpy版本即可复现可过审。venv漂移只卡PPO lane。
- 提交链(④): a55b5d6/1ba776d/d07533d/e7e1736/cc7b048(均报告+诊断runner, 未改算法/依赖)。

**🟢 提示词⑤结果(2026-06-16晚): 地基修好, 碾压在PPO环境恢复**:
- worker_client.py:23 sys.executable→系统Python(SETP_WORKER_PYTHON); worker不依赖torch/gymnasium(已核实__init__.py空、worker.py仅numpy+setp_solver+winner_operators), 系统Python可跑。
- 修后 env内 official winner+alpha_ucb_env 10-seed复现系统锚 mean£4878/seed2£4779、碾压fair-SA£5346.99(8.76pp)、零违约。**碾压在PPO环境恢复**。
- venv漂移根因=floating_or_blas_numeric_drift(两环境numpy RNG probe一致, 漂移来自BLAS/浮点)。金标准环境=/opt/anaconda3/bin/python3.13 + numpy2.3.5。**论文须钉死此环境+声明(可复现性硬需求)**, reproducibility_note已记。提交 b777079/75488a9/0dc9b1a。

**🟡 100k smoke结果(提示词⑤衔接): 管线通过但PPO失败=预期, 暴露两真问题**:
- held-out E-UK100_03: PPO median£4223 输 random£3543、alpha_ucb_env£3952; gate_vs_random=HALT_RANDOM。全可行、budget16000满。
- **失败=预期**: 1 episode=16000 eval步=一整轮ALNS, 100k步仅~6 episodes=没练。100k本就是管线冒烟。
- **真问题(a)训练集误混玩具题**: env_eval_counts显示训练用 verify_20251113/verify_20251113_evheavy/demo_carbon(best_obj仅£850, 非真实100c)。**(b)样本效率极低**: 真训练要几千局=几千万步=可能几天算力(1-2M仅60-125 episodes很可能不够)。
- **增益薄信号(再现)**: held-out上连经典AlphaUCB都输random(£3952 vs £3543), 说明"算子选择学习"在松算例增益薄/为负, PPO天花板可能仅匹配AlphaUCB。算子使用极度倾斜(vehicle_type_swap 206390/route_segment 160034 vs其余~27000), 疑训练塌缩。

**决策(2026-06-16晚, user选): 先换正经训练集+中等pilot探PPO能否学(选项1, 非全力训非止损)**。提示词⑥已发: 去玩具题(三套不重叠: 训练=E-UK100_02/150/200/25等真实算例, held-out=E-UK100_03, 正式=100-01+L-main)+worker系统Python+1-3M pilot+在100-01(算子选择有价值处)评估PPO vs AlphaUCB vs random。结论分类PROMISING(reward升+近AlphaUCB→全力训)/WEAK(平或远逊→止损讨论, DR定位可学习替代)。止损退路: 算法主贡献=winner kernel正确实现碾压SA8.8%+机制创新(碳/协同/公平/动态), DR-ALNS作已打通管线的可学习替代(诚实标注未达碾压)。

**2026-06-19 离线体检①=HALT_COLLECTION_COST**: ⑥pilot前插的便宜离线闸(solver/rl/dr_alns_ppo/offline_bandit.py, 验DR>random/AlphaUCB)。旧报告不可用作训练集(钉死); 本地补采2.85h仅1625行/13ep<4000行门禁(覆盖872unique>150过/零违约/完整性过), 未训未跑100-01诚实halt不注水, 提交a5ed83b。verdict未render(非PROMISING非WEAK)。**破局设计(Claude, 待确认)**: 改估计量为(A)监督式上下文可学性探针(现有1625行比'上下文'vs'仅block边际均值'对block收益的held-out预测力, 有提升=PROMISING打平=WEAK; 学函数跨872动作泛化故每臂1.9样本不致命, 前提特征维度别太高)+(B)若采集记了propensity则OPE/doubly-robust估greedy策略价值; 零新采样可能直接出verdict, 不够再并行CPU补采/一次性可复用数据集/因子化动作先测(采集是CPU活GPU无用; 4000门禁是为per-arm制表定的,监督探针须据估计量重导最小N)。探针只判'值不值GPU训'≠赢真bar。详见 [[project-plan-overview]] 2026-06-19段。

**⚠️ user纠正主线(2026-06-19)**: 论文算法主线**不是碾压SA**(SA是地板, 赢它只"合格")。真目标=**DR-ALNS真训练出来且有创新**, 退路=创新普通ALNS, 必须**干过GA-VNS/GA/PSO及其混合**。本文件名"crush SA"及上文多处"碾压SA"按此重读: 碾SA是必要地板非卖点; 且旧逻辑"DR≥AlphaUCB⇒碾SA⇒达标"**不足**——达标要对标GA/PSO/GA-VNS。
