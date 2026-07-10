# E2 临时执行备忘录（长对话压缩版）

用途：本文件只服务2026-07-11十二小时E2收口。每次准备改代码、改参数或启动新批次前先读，避免跑偏、串线或沉浸在局部补丁。正式事实最终仍回写 `HANDOFF.md` 和实验四件套。

## 用户真正要什么

7月31日前完成论文。眼下十二小时内至少达到“可以放心启动全量”，最好完成全量；如果计算超过十二小时，允许后台继续，改为按小时监控。汇报必须说人话。

论文正面故事偏电车：现实配送车电动化带来多EV、多用电、多充电；普通充电可能落在高碳时段；碳感知调度把相同电量移到低碳时段，从而降低电网间接排放。油车多、成本高、排放高可作为传统或反面场景，但不能成为正面主故事。

研究步骤按逻辑串行；获准的一批实验内部按任务并行，尽量利用CPU。长跑不高频人工探测，本地脚本每5分钟记状态，人工正常每小时看一次，异常立即救火。

## 已经成立的证据

1. 当前新算法不是旧ALNS，而是 `staged ALNS-LNS hybrid`。30次280kWh诊断稳定性门为30/30 OK、4000评价、零违规；100/150/200c平均相对LNS改善6.45%/0.69%/14.08%，11/15胜。
2. L-main v3正式集合是9个三班次 `-01` 算例：10/15/20/25/50/75/100/150/200c。
3. 旧通用formal runner仍有旧ALNS身份；本轮新增独立submission runner，不覆盖历史入口。
4. Tier1旧23实例校验已修为当前9实例；62项相关测试通过。旧全油车扫描构造仍有超过油车数量上限的历史失败，不进入正式基线。
5. 历史粗糙碳算子 `worst_carbon_removal/carbon_related_removal/low_carbon_charging_repair` 不真正平移充电时刻，历史结论为弱，不进入正式算法。
6. 固定路线充电调度小门复用15个保存解：15/15成功、路线/车型/总电量不变、双方零违规，625次充电移动，15/15降低EV充电间接排放，平均约9.87%。
7. 因此正式候选为 `staged ALNS-LNS hybrid + carbon-aware charging schedule`；消融为 `+ immediate charging ablation`。

## 参数与实验合同

正面主场景选280kWh任务内覆盖，理由是有现代中型配送车来源，并且当前新算法能形成真实多EV、多充电和择时降碳。后续E1--E7正式正面主结果应沿用同一场景合同。源码 `prices.py` 默认80kWh不改；80kWh保留为Goeke原始基准和稳健性对照，不与280混表排名。

主矩阵计划：9实例 × seeds1--5 × 6算法 × 4000评价 = 270项。六算法为完整碳感知混合算法、立即充电消融、LNS、GA、PSO、VNS。旧ALNS不参加正式对比。默认6 workers。

16000评价不直接覆盖全矩阵。先完成4000全矩阵；再按论文同行公平惯例和实际墙钟，只对100/150/200c代表规模做确认。

## 当前进行到哪里

最终更新：全量已完成并通过。225个真实搜索任务展开270行，270/270 `OK`、满4000、零违规；正式方案完整benchmark总成本第一，相对LNS总量领先6.845690%，配对25胜5平15负，配对平均优势2.829832%。碳消融45/45同路线同电量，40组移动充电并降碳。E2算法冻结，不再继续rescue；正式收口见 `docs/handoff/e2_full_closeout_20260711.md`。

- 代码/协议提交：`72a48b90`；基线健康门补丁：`d571a036`。
- 18项400评价接线门：18/18跑满、零违规，3/3碳完整/消融保持同路线同电量且产生充电差异。
- 该门在100c发现GA/PSO/VNS停在同一个共同起点；150/200c已开始分离。判定400预算不足以证明基线活性，不是直接启动全量的许可。
- 100c、GA/LNS/PSO/VNS、4000评价补门已通过：四条结果互不相同、零违规、跑满预算，算法专属搜索均活跃。
- 全量dry-run：225个搜索任务、225个唯一RunKey，展开270行；9实例×5种子×5搜索入口正确。
- resume真实小门：第二次运行不改raw hash和mtime；pair一次搜索可展开aware/naive两行，同路线同电量。
- 实测排程：约24.8 CPU小时；6 workers按65%效率约6.4小时。当前工程判决为 `GO_FULL_E2`。

## 全量启动前门槛（已全部完成，历史记录）

1. 当前4000基线健康门通过。
2. 生成270项任务manifest但不运行，核对9实例、5种子、6算法、280覆盖、4000预算和无重复RunKey。
3. 根据短门真实耗时估算总CPU小时与完成时间；若明显超出投稿节奏，先裁剪非核心基线或采用论文可接受的等墙钟合同，不能启动后才改。
4. 验证resume：人为只完成少量任务后再次运行，已完成任务不重复、失败任务可单独重试。
5. 启动前工作树干净，数字绑定提交；受保护文件无diff。
6. 启动本地watchdog，正常每小时查看，异常立即介入。

## 止损与禁止事项

- 不再改路线搜索算子，不做rescue调参。
- 不恢复旧粗糙碳算子。
- 不改cost/check/evaluation/prices语义。
- 不为凑胜利换种子、删失败行、挑算例或临时换电池。
- 不重开19档电池扫描；只有280短门出现真实退化才考虑123.9/150/180/200等来源档。
- 不串到dr-x86、DQN、PPO或动态入口迁移。
- 不提前跑E1/E3/E6/E7，不用未冻结算法污染其他实验。
- 一个问题若没有新证据，不反复做同类探针；先查历史手册和已有保存解。
- 全量一旦启动，除硬错误外不边跑边改协议。

## 决策口令

- `GO_FULL_E2`：工程小门全部通过、排程可接受，允许启动270项。
- `HALT_BASELINE_HEALTH`：基线无原生更新或同解，修入口/预算后再判。
- `HALT_RUNTIME_PLAN`：预计时间不可接受，先冻结公平替代合同。
- `HALT_CARBON_CONTRACT`：完整/消融没有同路线同电量或没有时间移动。
- `HALT_INTEGRITY`：违规、未跑满、复算不一致、manifest或hash异常。

任何HALT都不是失败羞耻，而是避免把一天算力烧在错误协议上。
## OpenAI product bug feedback after E2 closeout

After the E2 run is fully closed out, prepare an English bug report for OpenAI about the Codex Goal-mode continuation loop observed in this task. The report must explain that automatic goal continuations repeatedly created assistant turns even after the user explicitly requested hourly-only monitoring; invisible or zero-width replies still counted as messages; the assistant-facing goal API exposed only `complete` and `blocked`, not `pause`; and the local Computer Use runtime failed to start when the assistant attempted to pause Goal mode through the UI. Include reproduction steps, expected behavior, actual behavior, user impact (message spam and unnecessary credit/token consumption), and suggested fixes (assistant-callable pause/resume, configurable continuation interval, and no-op continuations that do not create visible turns).

Do not submit the report silently. Create the English draft and obtain the user's confirmation at the final submission step if an external feedback channel is available.
## Goal-mode long-run monitoring hard rule

For long-running experiments under Goal mode, manual/agent-side probing must never occur more frequently than once every 30 minutes. The default interval is 60 minutes. Earlier intervention is allowed only when the local watchdog has already emitted a concrete failure, stale-progress, or resource-health alert. Automatic goal continuations are not valid reasons to read progress or emit status messages; they must remain silent.
