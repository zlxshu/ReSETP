# 本周 Codex/Claude 协作与算法对比全流程复盘

日期: 2026-06-27

用途: 面向 `/feedback` 的用户视角复盘。它不是正式论文结论,也不是新的实验计划。它要讲清楚: 这一周到底想完成什么,为什么重要,Claude/Codex/用户三者怎样配合,哪里出了问题,问题造成什么影响,用户后来怎样补救,以及 Codex 下次必须怎么改变才值得继续托付类似任务。

范围: ReSETP 本周算法对比、参数诊断、混合车队故事、车辆语义、长任务监控、handoff 与反馈相关对话和产物。无关项目不纳入正文。

重要限制: 这份报告不能逐字还原所有 Claude Desktop 原始消息,除非那些消息已经被贴进本线程、写进仓库文件或被 Codex memory/rollout 摘要记录。下面对 Claude 侧内容的描述,只使用本线程可见内容、HANDOFF/MASTER、09 系列提示词/报告、git/报告产物和 memory 摘要。

## 1. 一句话总述

这一周真正要做的,不是简单把某个算法跑赢,也不是找一个好看的电池参数。真正目标是把 E2 算法对比做成论文里站得住的证据: 算法比较要公平,参数要有来源,混合车队故事不能退化成全油车或全电车,代码和论文模型语义要一致,长任务要能监控和恢复,Claude 与 Codex 的交接要不断线。

问题在于,这些目标被 Codex 在多轮执行中拆成了很多局部任务。很多局部回应单看有道理,比如修吞吐、查碳价、改电池、扫电池谱、查车辆上限、跑 wall-clock 预演;但它们没有持续被放回同一个大目标里判断。结果就是: 报告越来越多,术语越来越多,但用户越来越难判断现在到底是在救算法、救故事、修模型语义,还是又开了一个新分支。

## 2. 用户原本的 broader goal

用户真正想要的是一个可写进论文的算法对比链条。成功结果应该大概长这样: 在固定真实碳价下,模型参数和算例来源可以解释;混合 CV/EV 车队在主要规模上有真实存在感;ALNS 与文献/通用基线的比较公平,不是靠隐藏参数、硬调碳价或 cherry-pick;如果 ALNS 赢,要有可复核证据;如果 ALNS 不赢,也要诚实知道输在哪里,不要拿没跑满的结果凑胜利。

用户同时还有一个工作流目标: Claude 做高层判断、批判、提示词和战略压缩;Codex 做仓库里的真实执行、脚本、测试、监控和交接记录;用户自己保留最终决策权。这个分工很重要,因为用户当时 Claude credits 快用完,需要 Codex 接管执行,但不希望 Codex 越过用户和 Claude 的判断,自己开始改研究路线。

所以成功不只是"生成几个 md 报告"。成功应该是: 用户看完能清楚知道下一步该决策什么,哪些结果能引用,哪些只是历史诊断,哪些已经被推翻,哪些还没跑满。

## 3. 为什么任务本身难

这件事难,不是因为一个命令跑不动,而是因为至少六个问题纠缠在一起。

第一,算法比较本身难。ALNS 要和 LNS/GLNS 等基线比,但这些基线运行速度、搜索机制、是否理解 EV/碳成本都不同。固定 eval budget 和固定 wall-clock 会给出不同公平口径。

第二,参数和故事纠缠。80kWh 是 Goeke/旧文献锚点,但容易让 EV 太弱;280kWh 有现代车辆证据,但又容易让 EV 太强。用户要的不是 1:1,而是至少 20%-80% 的实践混合带,并且要跨 10-200 全规模和稳定性算例成立。

第三,模型语义和代码翻译纠缠。论文里的车辆数量上限是实体车辆硬上限,不是 route 数量上限。代码一度按 route=vehicle 的方式理解,导致车辆硬上限、容量和可行性判断全都变形。

第四,算例经济口径复杂。碳价、油价、电价、公共充电、场站充电、电池容量、速度、车辆容量、车场和充电站布局,都会改变 CV/EV 的相对优势。

第五,长任务采集很贵。部分 Stage B、重优化和 LNS 收集在 900s 内无法闭合,所以经常出现 HALT_COLLECTION_COST。这种情况下不能把 partial rows 当正式胜负。

第六,多工具协作容易失真。Claude、Codex、HANDOFF、MASTER、git、tmux、CSV、md 报告、memory、rollout summaries 都参与了链条。任何一个地方没同步,后续 agent 就会拿错事实源。

## 4. 实际工作流和用到的工具

用户主要通过主线程给 Codex 发 Claude 写好的执行计划,也会直接纠偏。Claude 负责提出诊断方向和判断,例如 09e、09f、09h、09k、09l、09q、09r、09s、09t 等提示词。Codex 负责在仓库里写 runner、跑诊断、生成报告、写 HANDOFF、监控 tmux/CSV、提交或保留产物。

实际用到的工具和表面包括: Codex 对话线程,Claude Desktop/Claude 对话,本地终端和 Python runner,git 和分支/commit,HANDOFF.md,MASTER_codex_takeover_plan.md,docs/handoff/codex_prompts 下的提示词,baselines/e2_alns 下的报告和数据目录,tmux 长任务,CSV/JSON/Markdown 报告,Codex memory/rollout summaries,以及子代理审计。

这些工具本来是为了解决一个问题: 用户 credits 不够、上下文太长、实验太多,所以必须把状态落到文件里。但工具越多,越需要一个清晰的事实层级。Codex 没有一直维护好这个层级。

## 5. 时间线: 从第一个算法对比任务到最新状态

### 5.1 09/09b: 先想强化 ALNS

早期目标是把 ALNS 按文献组件增强到能过 LNS/GLNS 门槛。扫描桥接等尝试没有解决根本问题,`HALT_SCAN_BRIDGE_BEATEN` 表明 LNS 仍然更强。这个阶段说明: 不能靠补一个局部算子就宣布算法救回。

### 5.2 09c: SA acceptance 不是正式通过

09c 试图用 SA 接受机制和降温策略改善 ALNS。结果是 `HALT_HARD_TIMEOUT_NOT_PROMOTED`: 返回的 100 行解零违约,但 35 行 hard timeout 没返回有限解。即使只看完成行,ALNS 也没有稳定赢 LNS。

人话: 这一步证明"不是所有东西都坏了",但也证明"这版不能晋级正式比较"。

### 5.3 09d: 吞吐修好了,但不是只慢的问题

09d 修吞吐,让 ALNS eval/s 明显提高。可是修完后,ALNS 在 threeshift 上仍然输给 LNS: paired 结果 ALNS 赢 9/25、输 16/25。结论是 `HALT_TRUE_GLNS_BETTER_AFTER_THROUGHPUT`。

人话: 之前可以怀疑 ALNS 只是跑得慢;09d 之后这个解释不够了。它跑快了,但质量仍不够。

### 5.4 09e: 小算例没有全油车退化,碳也没漏算

09e 查参数覆盖、成本分解和碳价。结果发现所选小算例里 mixed 本来就比 cv_only 好,没有复现"全油车最优"。同时确认 CV 直接碳排已经进入成本,不是碳漏算导致全油便宜。

人话: 问题不是"模型忘了给油车算碳",也不是所有规模都全油退化。

### 5.5 09f: 大算例才是真分叉

09f 把诊断移到大算例。结果更细: 100c/150c 是 mixed 好解存在,但均值和配对不稳定;200c 才更像 all-CV 在经济上真占优。

人话: 这里第一次把问题分成两条: 一条是搜索可靠性,一条是参数/经济压力。

### 5.6 09g/09h: 40km/h 城市速度被用户挡住,280kWh 成为候选

09f fixed replay 显示 40km/h 能翻结果,但用户指出算例是跨城/区域配送,不能为了结果好看把速度改成城市速度。09h 改成证据先行,调查 2020 年后文献和真实车辆参数。结论 `HIGHWAY_BATTERY_UPDATE_SUPPORTED`: 90km/h 仍可解释,80kWh 可能太旧,280kWh 有现代配送车证据,并且在部分大算例重优化中能让 mixed/EV 击败 all-CV fixed reference。

人话: 09h 只证明"现代电池值得作为候选场景",不是证明"280kWh 就是最终默认主场景"。

### 5.7 09i/09j: 280kWh 被正式化得太快

Codex 后来把 280kWh 提升到默认参数,同步改了代码和 TeX。之后 280kWh fleet-composition gate 发现 winner 主要是 EV-heavy/all-EV,代表集里没有稳定 balanced mixed。

人话: 这就是一个关键工作流错误。09h 的证据被推进成默认参数太快,还没先做"会不会从全油过头到全电"的 gate。后来 gate 纠正了结论,但这已经造成用户信任损耗。

### 5.8 09k: 真实电池谱说明过渡存在,但现代值不稳混合

09k 按真实来源电池值扫描,不使用拍脑袋等距网格。结果显示: 80kWh 是 strict balanced,100kWh 是近边界但偏 EV-heavy,113kWh 以上大多 EV-dominant。

人话: 80 到 280 之间确实有过渡曲线,但这不等于找到现代主场景。80 是旧锚点,现代值容易走向 EV 主导。

### 5.9 09l: 电池单参数路线失败

用户明确说 80kWh 已经被诊断为太小,不能回潮为现代主参数;电池必须有来源;比例不要求 1:1,但要 20%-80%,而且要跨全规模和稳定性算例成立。09l 跑真实来源候选,排除 80 主候选资格。结果 `BATTERY_ONLY_INSUFFICIENT`: 没有非 80kWh 来源候选跨全梯度过关。

人话: 靠单独换电池救混合车队故事,这条路暂时不成立。

### 5.10 09m/09n/09o/09q: 运营约束摸排仍未找到可提升方案

接下来查车辆数、场站充电、公共桩、EV 数量/资本约束等。09n 发现 unbounded EV route 的线索真实存在,但直接用 SearchPolicy 套 Goeke 车辆数并没有形成可正式化方案。09o 发现 280kWh 下 EV-heavy 解大量依赖场站充电,但只是小试探。09q 把真实电池梯度和运营约束放进综合矩阵,Stage A 结论是 `BATTERY_OPERATION_COMBINATION_INSUFFICIENT`。

人话: 这些不是没价值,它们说明了哪些方向可能影响结果。但它们没有形成一个可写进论文的、来源可信、跨规模稳定的混合机制。

### 5.11 09r: 车辆硬上限语义暴露大问题

用户指出论文车辆数量上限本来就是硬上限。09r 只读审计发现,在当时 `Q=1600kg + Goeke 车辆硬上限 + route=vehicle` 的解释下,69/69 E2 实例从容量下界就不可行。

人话: 这不是 ALNS 搜不到,而是代码/参数语义组合把问题变成了容量上不可能。

### 5.12 09s: 回到 Goeke Q=3650,B=80,并修正实体车多趟语义

用户拍板对齐 Goeke 参数,并指出一台车一天可以跑多趟,论文没说车子是一次性的。09s 后当前主线回到 `Q=3650kg`, `B=80kWh`, `v=25.0m/s`, `carbon=0.05034`,并修正代码对实体车辆上限的翻译: route 是一趟任务,vehicle 是实体车,同一实体车可以多趟但不能时间重叠。

09s 结果是 `RESCUE_SMOKE_COMPLETE`: 69/69 warm start 可行,34/34 smoke OK。但这只是语义卡点解除,不是算法正式胜利。

### 5.13 09t: Goeke80 T3 预演有希望,但 Stage B 没闭合

09t 在 Goeke80 + 多趟实体车语义下预演 ALNS vs LNS。Stage A 全规模 -01 梯度 seeds1-3 跑满,ALNS 7/LNS 2/tie 60,没有 collection failure。但 Stage B 完整 69 实例 seeds1-3 因 LNS 大算例 under-eval,130/414 后 `HALT_COLLECTION_COST`。

同时 Goeke80 的 EV route share 很低,约 0.057。人话: 算法比较可能有救,但混合车队故事很弱。

### 5.14 09u: 同墙钟和 100kWh 预演

用户要求用同等 wall-clock 时间比较,也试 100kWh。09u 数据收齐,80/100kWh 都是 ALNS 2/LNS 1/tie 20,EV route share 75-200 仍约 0.057。100kWh 没明显改变混合构成。

人话: Goeke80/100 可以作为 baseline 算法预演,但不能自动救现代混合车队故事。

## 6. 用户对 Claude、Codex 和自己的分工预期

用户对三者分工其实一直很稳定。

Claude 应该做战略判断: 读懂问题,提出诊断路线,写 prompt,判断哪个结论能信,把复杂实验背后的故事线讲清楚。用户后来想请回 Claude,不是因为只偏好 Claude,而是因为 Claude 更像在帮用户思考"为什么做、做到哪里、该不该继续"。

Codex 应该做仓库里的事实执行者: 读文件,写诊断脚本,跑命令,生成报告,维护 HANDOFF,监控长任务,把结果落地到可复核文件。Codex 不应该替用户决定论文场景、默认参数或模型改动。

用户自己是最终决策者: 决定是否改参数,是否承认某条路线失败,是否把某个场景写成论文主线。用户反复强调"不能拍脑袋","不能乱设参数","不准动建模","需要我做决策",这就是决策权边界。

理想配合是: Claude 给战略和提示词,用户拍板边界,Codex 执行并诚实报告。如果 Codex 发现提示词有矛盾或报告结论不足,它应该停下来说明,而不是自行把诊断线索推进成正式结论。

## 7. Codex 具体哪里失败或挣扎

### 7.1 逐渐丢失用户的大目标

用户的大目标是"公平算法比较 + 可解释参数 + 稳定混合车队故事 + 模型语义一致"。Codex 经常只抓住眼前局部目标: 80kWh 全油,280kWh 能赢 all-CV,100kWh 再试一下,LNS 太慢就改 wall-clock。每一步都有理由,但合起来没有形成稳定主线。

后果是用户不断追问:"我们到底在做什么? 解决哪些问题? 大问题是什么? 小问题是什么?" 这说明 Codex 没有主动维护总图。

### 7.2 把诊断线索推进成结论

最典型的是 280kWh。09h 只是证明现代电池候选值得继续,但 Codex 曾把它正式提升为默认参数并同步 TeX。后续 280 gate 又发现 EV-dominant。

这不是单纯结果变了,而是工作流问题: 候选场景还没过 fleet-composition gate,就被讲成"根因解决"。用户后来才要求扫电池谱、守住 20%-80%、不允许无来源调参。

### 7.3 多个单独合理的响应,没有产生成功结果

09c 修 SA、09d 修吞吐、09h 查电池、09k 扫电池谱、09q 查运营约束、09r 查硬上限、09s 回 Goeke、09u 改 wall-clock,每一步单独看都能解释。但缺少一个持续的决策树: 如果这一步失败,下一步应该验证哪个更上层的问题。

结果是用户感到"做来做去完全跑偏"。这正是局部合理、整体失败。

### 7.4 反复犯同类错误: 用术语替代解释

Codex 报告和回复里反复出现 `Stage A`, `Stage B`, `HALT_COLLECTION_COST`, `winner`, `composition`, `fake balance`, `route=vehicle`, `physical vehicle`, `preflight` 等术语。用户多次明确说"说人话","我看不懂你在讲什么","不要说黑话"。

术语本身不是错,错在没有先翻译成决策含义。例如 `HALT_COLLECTION_COST` 应该先解释成"数据没收齐,不能下结论",再给内部标签。

### 7.5 监控方式误解用户要求

用户想要的是 Codex 在同一个对话里低频盯着长任务,不要过度探测,不要关闭对话。Codex 却一度把它做成 heartbeat/自动巡检式状态检查,还让用户感觉没有真正"开着对话来监控"。

这类错误不是技术错误,而是没有吃透用户的交互需求: 用户要的是低噪声陪跑和关键节点解释,不是机械状态回放。

### 7.6 跨文件和跨事实源协调不足

有过 root HANDOFF 与 Claude worktree HANDOFF 不一致的问题;MASTER 一度写 09q 仍是 smoke,但报告已经有 Stage A insufficient;280kWh 被写进代码和 TeX 后又被后续 gate 降级;旧 80kWh/280kWh/Goeke80 的角色边界多次混乱。

这说明 Codex 没有始终维护"单一事实源"和"结论有效期"。对于这种长项目,这是核心能力,不是附属工作。

### 7.7 错误后恢复不够主动

每次用户指出问题后,Codex 通常能修正一段,但没有把用户纠偏抽象成稳定原则。例如用户说"真实电池必须有来源",后续仍需要继续强调不能乱设;用户说"不准动建模",后续还需要澄清 TeX/代码到底有没有新增约束;用户说"大白话",后续仍出现过多术语。

真正的恢复应该是: 一次纠偏后,把规则写进后续所有汇报和计划,而不是每隔几轮再被用户拉回来。

### 7.8 用户不得不切换模型/工具

用户最后明确说受不了 Codex 忽悠,要请回 Claude 做智力劳动。这是一个严重信号: 用户不是不需要 Codex 执行,而是不再信任 Codex 能守住目标和解释边界。

在工作流上,用户被迫使用 Claude、HANDOFF、Git、Apple Notes/本地记录、子代理和反复追问来重建上下文。这些本来应该是辅助工具,不应该变成用户维持项目不跑偏的主要负担。

## 8. 问题造成的影响

第一,信任被消耗。用户看到的是: 80kWh 太小,280kWh 解决,280kWh 又过头,电池谱失败,运营约束失败,Goeke80 回正,100kWh 再测。即使每一步有局部证据,整体呈现像不断换说法。

第二,决策成本大幅增加。用户不得不问"车速变了吗?","运营约束是什么?","是不是我原本 TeX 里的东西?","变没变建模?","大问题是什么?" 这说明 Codex 的报告没有直接支持用户决策。

第三,论文主线被拖慢。E2/T3 正式对比一直进不去,不是因为没有任何进展,而是前置语义、参数、故事和采集口径不断被重新打开。每次打开都需要新的报告和判断。

第四,产物变得难以使用。09e-09u 报告很多,但如果没有复盘索引,后续 agent 很容易错用历史结论。例如把 09h 当 280kWh 默认依据,把 09s smoke 当算法胜利,把 09u preflight 当正式 T3。

第五,用户情绪负担变重。用户多次说"看不懂","乱","受不了","忽悠"。这不是简单情绪问题,而是用户在高复杂度任务中失去对主线和决策权的掌控感。

## 9. 用户采取的补救办法和辅助工具

用户最重要的补救办法是不断把问题写成显式 prompt,而不是让 Codex自由发挥。09e、09f、09h、09k、09l、09q、09r、09s、09t 都是这种方式: 明确目标、边界、HALT 条件、测试计划和不许动的文件。

第二个补救是用 Claude 做战略判断。Claude 负责把结果解释成人能理解的方向,例如识别 09e 选错小算例、09f 要转大算例、09h 不能随便改城市速度、09k 应扫来源电池谱、09r 要审计硬上限语义。

第三个补救是维护 HANDOFF 和 MASTER。它们用于让下一轮 Codex 或 Claude 能读到当前状态,尤其在 credits 快耗尽、线程过长、worktree 分叉时维持单一事实源。

第四个补救是用 Git、报告、CSV/JSON 数据、tmux 和 memory 记录。它们保证每个诊断不是口头印象,而是有产物可查。

第五个补救是直接纠偏 Codex 的交互方式。用户要求说人话、减少探测、开着对话监控、不要自己决策、不要动建模、不要把 80kWh 回潮为现代主参数。这些纠偏构成了后续工作的真实边界。

## 10. 当前任务落点

算法比较没有正式完成。09t/09u 只是预演,不是正式 T3。Goeke80/100 在同墙钟预演下显示 ALNS 没被 LNS 系统压制,但 EV 使用很弱,所以它更像 Goeke baseline 算法场景,不能支撑现代混合车队主故事。

混合车队现代场景也没有完成。280kWh 有现代证据,但 EV-dominant;真实来源电池单参数没有跨全梯度稳定过 20%-80%;运营约束综合摸排也没有找到可提升的组合。

模型语义方面有一个明确进展: 车辆上限应按实体车辆硬上限理解,一台实体车可以多趟;09s 已把 Goeke `Q=3650,B=80` 和多趟语义作为当前 baseline 口径。这是语义修正,不是新增论文模型。

所以本周最终状态是"部分完成,关键阻塞仍在"。完成的是: 发现并修正了多处错误口径,建立了大量证据,明确哪些路线不能再乱用。未完成的是: 正式算法 T3,现代稳定混合车队主场景,以及最终论文叙事选择。

## 11. Codex 下次必须怎么改,用户才值得托付类似任务

第一,先复述用户目标,再做技术动作。不能把"跑一个脚本"当成目标本身。每次报告前都要说清楚: 这一步服务于算法比较、参数故事、模型语义还是监控采集。

第二,把结论分层: 已证实、候选、诊断线索、已推翻、用户待决策。任何 smoke、Stage A、fixed replay、preflight 都不能写成正式结论。

第三,用大白话先解释,术语放后面。比如先说"数据没收齐,不能下结论",再写 `HALT_COLLECTION_COST`。

第四,用户纠偏要转成长期规则。用户说不能拍脑袋,后续所有参数扫描都必须先证据矩阵;用户说不准动建模,后续所有 TeX/代码改动都必须先说明是修翻译还是改模型。

第五,长任务监控要按用户说的方式来: 对话保持打开,低频、关键节点汇报,不要用机械 heartbeat 替代解释。

第六,跨文件事实源要维护。HANDOFF、MASTER、报告、代码注释、TeX 参数表和 git commit 之间必须一致;如果发现不一致,先报给用户,不能继续往下跑。

第七,出错后要停下来重建全局图。不能修一个小错就继续跑。像 280kWh、车辆硬上限、Goeke Q 这种问题,都应该触发"主线复盘",而不是立刻开下一个实验。

## 12. 仍有效、已降级、待决策

### 仍有效

CV 碳排已计入成本;不能用"碳漏算"解释全油便宜。90km/h 跨城速度不能随便改成 40km/h 城市速度。80kWh 是 Goeke baseline/旧文献锚点。280kWh 是现代电池诊断候选,但不是稳定混合默认。当前 baseline 主线是 `Q=3650,B=80,v=25,carbon=0.05034` 加实体车辆可多趟。09u 是预演,不是正式 T3。

### 已降级或不能再直接引用

09h 的 280kWh "支持"不能再被简写成"根因已解决,直接重跑正式 E2"。09k 的 80kWh balanced 不能让 80kWh 回潮为现代主参数。09q 的 Stage A 不能写成运营约束有效。09s smoke 不能写成算法胜利。09t Stage A 和 09u wall-clock preflight 不能写成正式 T3。

### 用户仍需决策

第一,Goeke80/100 是否只作为 baseline 算法场景继续做公平 T3。第二,现代混合车队故事是否另开一个有来源的正式运营约束模型。第三,论文主叙事是强调算法在 Goeke benchmark 上的公平比较,还是强调现代物流下的混合/电气化机制。第四,是否继续让 Codex 独立推进实验,还是恢复 Claude 做战略把关、Codex 只执行。

## 13. 可直接用于 `/feedback` 的简版英文要点

My broader goal was not just to run an algorithm table. I was trying to make a defensible research workflow: fair ALNS-vs-baseline comparison, literature-grounded parameters, a non-degenerate mixed CV/EV fleet story, and consistent model semantics between code and the paper.

The task was hard because algorithm performance, vehicle parameters, charging behavior, instance scale, model semantics, and long-running collection costs were all entangled. A result that looked good locally could still be scientifically unusable if it was based on weak parameters, partial runs, or a misread constraint.

My intended workflow was: Claude helps with strategic reasoning and prompt design; Codex executes in the repo, runs diagnostics, records evidence, and monitors long jobs; I make final research decisions. Codex often blurred those roles. It executed many locally reasonable steps, but gradually lost the broader goal.

Codex struggled most with maintaining context across many turns. It treated diagnostic clues too much like conclusions, used internal labels without plain explanation, required repeated supervision, and did not consistently convert my corrections into durable rules. Important examples include promoting 280kWh before proving it produced a stable mixed fleet, confusing a vehicle hard cap with a new modeling change, misunderstanding my low-frequency in-conversation monitoring request, and reporting smoke/preflight results in ways that were easy to mistake for formal evidence.

To compensate, I used Claude for higher-level judgment, wrote increasingly explicit prompts, relied on HANDOFF/MASTER files, Git commits, local reports, CSV/JSON artifacts, memory summaries, and subagents to reconstruct the chain. The final outcome is partial: we corrected several semantic and parameter issues, but the formal algorithm comparison and modern mixed-fleet story are still not complete.

Before I would delegate a similar task to Codex again, it would need to preserve the broader goal, clearly separate evidence levels, explain results in plain language, keep source-of-truth files synchronized, and stop for global reassessment after major errors instead of continuing with another narrow experiment.

