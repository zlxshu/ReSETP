# P115 大删除只读侦察清单（2026-08-18）

## 结论与口径

`USER DECISION`：P115 已明确授权把不必要源码真删；本清单只做侦察，不执行删除。唯一写入物就是本文件。

`FACT`：本清单以 **2026-08-18 侦察启动快照**为计数基线，不是干净 `HEAD`，而且工作树仍在并行变化。初始化施工会话正在改 `kernel_proposals.py`、`initialization.py`、`runner.py` 及其接线；这些文件不列为本轮删除目标。对侦察过程中已被另一写手删除的文件，行数取删除前的 tracked 版本，条目表达的是“删后必须不存在”的目标状态。下一写手必须先吸收并行会话的最终状态，再按**函数名和外部入边**重放本清单，不能照旧行号盲删。

`FACT`：可执行结论是三类：

1. 第一档共有 **19 个整文件目标、3,831 物理行**；
2. 第二档清掉公开退役岛、两套 SISR、旧 ALNS 公平入口、旧 LNS policy 接口及兼容 shim；
3. 第三档只削混合文件中的死函数，`population.py` 当前没有可安全删除的函数。

`INFERENCE`：按侦察启动快照的文件物理行数、函数跨度和必要的两次“旧 helper 原样搬家”计算，**整份清单的毛删除量**约 **13,300 行**。其中可直接按整文件计数的是 **10,393 行**；其余约 **2,900 行**来自函数、开关、旧测试片段和 import 清理。这个数字包括侦察期间被并行写手先行删除的部分，不等于下一写手尚需删除的行数，也不得重复记功。格式化和并行改动会让最终 `git diff --numstat` 浮动，最终精确账必须以合并后的单一 diff 为准。

`FACT`：侦察启动时的完整回归基数由下列命令取得：

```bash
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=solver/src:models/src:third_party/setp_hgs_kernel \
/opt/anaconda3/bin/python3.13 -m pytest --collect-only -q -p no:cacheprovider solver/tests
```

启动快照结果：`1197 tests collected in 3.99s`。本清单计划净删 34 个 `solver/tests` 用例，闭合后应收集 **1163** 个；另删 1 个 `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/test_fairness_deficit_decoder.py` 用例，它本来就不在 1197 口径内。

`CORRECTION`：交付前重跑同一收集命令时，工作树已被另一写手先删 `search/fairness.py`，结果变成 `1090 tests collected, 13 errors`，错误栈指向仍从该文件 import helper 的 baseline 链。因此 **1090 不是新基数**；它证明当前外部改动尚未闭合。1163 仍是从完整启动基数按本清单逐项扣除得到的目标数，须在 helper 搬家和全部 import 清理完成后实测确认。

## 证据命令约定

下表里的命令代号不是结论替代品；每一行仍给出实际结果摘要。

- `R-CODE(TOKEN)`：`rg -n 'TOKEN' solver/src solver/scripts solver/tests baselines tools models --glob '*.py' --glob '*.sh'`
- `R-NOW(TOKEN)`：`rg -n 'TOKEN' docs/handoff/READ_ME_FIRST_FOR_AGENTS.md docs/handoff/CURRENT_PROJECT_CONTEXT.md docs/paper_gci_dmm_vrp_20260804/pending_decisions.md docs/handoff/algorithm_pipeline_map_20260817.md docs/handoff/reform_council_20260818 --glob '*.md'`
- `R-DOC(TOKEN)`：`rg -l 'TOKEN' docs --glob '*.md'`
- `VULTURE`：`nl -ba tools/quality/vulture_whitelist.py | sed -n '224,335p'`
- `LINES(PATH...)`：`wc -l PATH...`
- `COLLECT(PATH...)`：上面的 Python 3.13 `pytest --collect-only` 命令，把末尾路径换成相应测试文件。
- “零外部入边”按**删除岛折叠后**计算：岛内文件互相 import 不算外部入边；动态 import、包再导出、CLI 字符串、shell 调用和 baseline import 均另做 `rg` 复核。

## 第一档：整文件删除

这些文件满足：删除岛外零运行入边、canonical 不可达、非冻结、不是当前证据文件。历史文档里的文字提及不算现役步骤；其风险在最后一列明说。

| 路径 | 行数 | 档位 | 证据（命令＋结果摘要） | 连带删除（测试／开关／文档步骤） | 风险／删了谁会坏 |
|---|---:|---|---|---|---|
| `solver/src/setp_solver/search/e2_alns_sa_acceptance.py` | 607 | 第一档 | `R-CODE(e2_alns_sa_acceptance)`：该模块零 import 入边；命中 `winner.py`/`test_alns_crush_v2.py` 的是同名核心函数，不是本 CLI 模块。`R-NOW` 为 0。 | 无测试删除；不删 `winner.py` 中仍被测试的函数。 | 旧 `python -m setp_solver.search.e2_alns_sa_acceptance` 不能在当前树复跑；git 历史可恢复。 |
| `solver/src/setp_solver/search/e2_alns_scan_bridge.py` | 415 | 第一档 | `R-CODE(e2_alns_scan_bridge)`：模块零 import 入边；同名核心函数仍在 `winner.py`。`R-NOW` 为 0。 | 无测试删除；不碰现存 scan-bridge 核心测试。 | 旧 gate CLI 和其直接改写旧 baseline Markdown 的能力消失。 |
| `solver/src/setp_solver/search/fleet_charge_corepair.py` | 143 | 第一档 | `R-CODE(search.fleet_charge_corepair)`：0 命中；现用实现是 `algorithms/resetp_alns/support/fleet_charge_corepair.py`。 | 无。 | 只失去一份无人调用的旧重复实现。 |
| `solver/scripts/merge_r2_manifests.py` | 72 | 第一档 | `R-CODE(merge_r2_manifests)`：只命中本文件和同岛 export shell；`R-NOW` 为 0。 | 与下列 8 个 R2 shell 一起删。 | `docs/claudecode_handoff.md` 的旧 R2 恢复命令失效；保存结果不受影响。 |
| `solver/scripts/run_parallel_r2.sh` | 137 | 第一档 | `R-CODE(run_parallel_r2)`：只有本 R2 shell 岛内部自述/调用；当前入口和当前事实源均 0。 | 同岛整组删除。 | 旧 R2 并行编排不能直接复跑。 |
| `solver/scripts/run_parallel_r2_e34.sh` | 129 | 第一档 | `R-CODE(run_parallel_r2_e34\.sh)`：0 内容引用，岛外 0 入边；`R-NOW` 为 0。 | 同岛整组删除。 | 只影响旧 E3/E4 批次启动。 |
| `solver/scripts/run_parallel_r2_e4stress.sh` | 125 | 第一档 | `R-CODE(run_parallel_r2_e4stress\.sh)`：0 内容引用，岛外 0 入边；`R-NOW` 为 0。 | 同岛整组删除。 | 只影响旧 E4 stress 启动。 |
| `solver/scripts/run_parallel_r2_e4stress_bplus.sh` | 125 | 第一档 | `R-CODE(run_parallel_r2_e4stress_bplus\.sh)`：0 内容引用，岛外 0 入边；`R-NOW` 为 0。 | 同岛整组删除。 | 只影响旧 B+ stress 启动。 |
| `solver/scripts/run_parallel_winner_formal.sh` | 134 | 第一档 | `R-CODE(run_parallel_winner_formal)`：只命中自身 usage；当前文档/流程 0。 | 同岛整组删除。 | 旧 winner formal shell 不能复跑。 |
| `solver/scripts/run_r2_export.sh` | 61 | 第一档 | `R-CODE(run_r2_export)`：只命中自身及 merge 提示；当前文档/流程 0。 | 同岛整组删除。 | 旧导出包装消失，已有导出物不动。 |
| `solver/scripts/run_r2_recovery_chain.sh` | 146 | 第一档 | `R-CODE(run_r2_recovery_chain)`：只命中自身 usage；当前文档/流程 0。 | 同岛整组删除。 | 旧恢复链需从 git 取回。 |
| `solver/scripts/run_winner_formal_export.sh` | 93 | 第一档 | `R-CODE(run_winner_formal_export)`：只命中自身；`R-DOC` 仅旧 `legacy_sweep` 报告。 | 同岛整组删除。 | 旧报告中的复跑命令失效。 |
| `solver/scripts/run_integrated_private_carbon_models_scout.py` | 323 | 第一档 | `R-CODE(run_integrated_private_carbon_models_scout)`：0 外部入边；它只向仍保留的 component scout 取 helper。`R-NOW` 为 0。 | 无。 | 失去一次性三种碳建模 scout；无当前文档步骤。 |
| `solver/scripts/run_integrated_private_carbon_scout.py` | 290 | 第一档 | `R-CODE(run_integrated_private_carbon_scout)`：0 外部入边；只依赖同表 fleet-supply scout 和保留的 component scout。 | 与下一行一起删。 | 失去一次性日均／时变碳 scout。 |
| `solver/scripts/run_integrated_private_fleet_supply_scout.py` | 372 | 第一档 | `R-CODE(run_integrated_private_fleet_supply_scout)`：唯一外部入边来自上一行，折叠两文件后为 0；`R-NOW` 为 0。 | 与上一行一起删。 | 失去旧车队供给 scout。 |
| `solver/scripts/run_pyvrp_hgs_convergence_technical.py` | 257 | 第一档 | `R-CODE(run_pyvrp_hgs_convergence_technical)` 和 `R-NOW` 均 0。 | 无。 | 失去旧 PyVRP 收敛技术入口；现役 public ruler 不调用它。 |
| `solver/scripts/finalize_mechanism_validation_v3.py` | 216 | 第一档 | `R-CODE(finalize_mechanism_validation_v3)`、`R-NOW` 均 0。 | 无。 | 旧 v3 包不能用该一次性 finalizer 重装；保存的证据包不动。 |
| `solver/scripts/verify_mechanism_validation_v3_preflight.py` | 104 | 第一档 | `R-CODE(verify_mechanism_validation_v3_preflight)`、`R-NOW` 均 0。 | 无。 | 旧 preflight 不能直接复跑。 |
| `baselines/e2_alns/repair_sisr_v1_artifact_hashes_20260718.py` | 82 | 第一档 | `R-CODE(repair_sisr_v1_artifact_hashes)`：0 入边；只读取待退役 SISR runner。 | 随 SISR 删除。 | 失去一次性历史 hash 修补脚本；既有 artifact 不删。 |

### 第一档明确排除的“看起来像孤儿”

- `solver/src/setp_solver/algorithms/resetp_alns/support/mechanism_prescription.py`（767 行）：**不删**。AST import 图找到 4 个 baseline 代码消费者：`contextual_expert_solver.py`、`mechanism_segment_generator.py`、`run_contextual_expert_behavior_gate.py`、`test_contextual_expert_solver.py`；它还参与 hash 封存的旧机制证据岛。Vulture 的“unused class”只说明现役 solver 不调用，不能推翻证据入边。
- `solver/scripts/run_integrated_private_component_scout.py`：**不删**。`run_dss_step1_oracle.py` 真 import `_run_arm`，`run_endogenous_fleet_trial.py` 还以脚本路径调用；两者又被 `CURRENT_PROJECT_CONTEXT.md` 引作当前诊断证据。
- `solver/scripts/run_dss_step1_oracle.py`、`run_endogenous_fleet_trial.py`、`run_problem_hgs_static_effect_scout.py`：**不删**，三者均被当前事实源直接引用。
- `solver/scripts/feasibility_report_text.py`：**不删**，`finalize_metro_rebuild_20260812.py` 和 static-effect scout 真实 import。
- `run_problem_hgs_private_rebuild_assignment_probe_pyvrp.py`、`run_problem_hgs_copied_foundation_technical.py`、`run_mechanism_validation_v3_step_c.py`、`run_problem_hgs_public_technical.py`：分别仍是现行审计证据、待复核步骤、d* 数值来源或公开技术入口；不满足“非证据”。

## 第二档：退役件连专属测试一起删

### A. 公开 Vidal／customer-assignment／SISR 退役岛

`FACT`：`algorithm_pipeline_map_20260817.md:95-100,117-128` 把这四个公开模块标为 `RETIRED_COMPAT`，canonical 强制关闭，已观测调用数为 0。AST import 图显示它们的入边只来自 `public_search.py` 的关闭支路、岛内文件和专属测试。

| 路径 | 行数（现有／预计删） | 档位 | 证据（命令＋结果摘要） | 连带删除（测试／开关／文档步骤） | 风险／删了谁会坏 |
|---|---:|---|---|---|---|
| `solver/src/setp_solver/algorithms/problem_hgs/public.py` | 1219／1219 | 第二档 | `R-CODE(problem_hgs.public)`：生产入边只有同岛 `public_assignment.py`、`vidal_compound.py`；canonical 不 import。 | 同岛其余模块和测试一起删。 | 旧自建 public 外循环及 DCREX public builder 消失；现役 copied-kernel public 不受影响。 |
| `solver/src/setp_solver/algorithms/problem_hgs/public_assignment.py` | 263／263 | 第二档 | `R-CODE(public_assignment)`＋AST import 图：入边仅 `public_search.py` 的关闭分支、退役岛及专属测试。 | 删 `test_problem_hgs_public_assignment.py`。 | 旧客户跨车场精修不能复跑。 |
| `solver/src/setp_solver/algorithms/problem_hgs/vidal_compound.py` | 535／535 | 第二档 | `R-CODE(vidal_compound)`＋AST import 图：入边仅 `public_search.py` 的关闭分支、退役岛及专属测试；canonical calls=0。 | 删 `test_problem_hgs_vidal_compound.py`。 | 旧 Vidal rotation/customer refinement 不能复跑。 |
| `solver/src/setp_solver/algorithms/problem_hgs/sisr.py` | 383／383 | 第二档 | `R-CODE(problem_hgs\.sisr)`＋`R-CODE(enable_sisr)`＋AST import 图：入边仅 `public_search.py` 的 opt-in 分支及专属测试；正式 runner 默认/正式批次均 false。 | 删 `test_problem_hgs_sisr.py`；清 runner SISR flags。 | 旧 public SISR probe 不能复跑。 |
| `solver/src/setp_solver/algorithms/problem_hgs/crossover_control.py` | 111／111 | 第二档 | `R-CODE(crossover_control)`＋AST import 图：入边仅退役 `public.py` 及专属 controller 测试。 | 两个 controller 测试删；教育器浮点噪声测试迁走后删原测试文件。 | 不影响 `education._meaningfully_better`。 |
| `solver/src/setp_solver/algorithms/problem_hgs/public_search.py` | 529／约 367 | 第二档接线 | `R-CODE(enable_vidal_compound)`＋`R-CODE(enable_sisr)`：所有退役分支集中于此；现役只需 reader、native evaluator、copied HGS builder、fingerprint。 | 删 `VidalCompoundAccounting`、`_VidalCompoundRefiner`、`AssignmentSearchAccounting`、`CustomerAssignmentHGS`、`build_customer_assignment_hgs`；`IntegratedPublicHGSBundle` 只留 `algorithm`；`refine=lambda candidate: (candidate,)`；删 5 个退役参数和相关 import。 | 这是现役文件，必须按函数名削，不能整文件删。 |
| `solver/scripts/run_public_v2_28_clean_ruler.py` | 1644／约 66 | 第二档接线 | `R-CODE(sisr-enabled)`＋`R-CODE(disable-vidal-compound)`：命中 `_solve_independent`、metadata、worker command、probe/batch、parser；正式 batch 明传 SISR false。 | 删除两个 CLI flag、两个 `_worker_command` 参数、P42 reopen 拒绝分支、旧 metadata component、两套 accounting 序列化；builder 只传 `data/seed`。 | `execution_blueprint_20260818.md:2789,2817` 中“仍传 disable flag”的句子会陈旧，后续事实文档更新时标旧；本轮不改该文档。 |
| `solver/tests/test_problem_hgs_public_assignment.py` | 62／62 | 第二档测试 | `COLLECT`：1 个测试。 | 整文件删。 | 回归数 −1。 |
| `solver/tests/test_problem_hgs_vidal_compound.py` | 324／324 | 第二档测试 | `COLLECT`：10 个测试。 | 整文件删。 | 回归数 −10。 |
| `solver/tests/test_problem_hgs_sisr.py` | 382／382 | 第二档测试 | `COLLECT`：8 个测试。 | 整文件删。 | 回归数 −8。 |
| `solver/tests/test_problem_hgs_crossover_control.py` | 44／净约 39 | 第二档测试 | `COLLECT`：3 个测试；前 2 个只测退役 controller，第 3 个只测现役 education。 | 把 `test_education_rejects_float_noise_as_an_improvement` 原样迁入 `test_problem_hgs_education_depth.py`，再删本文件。 | 回归数净 −2，不丢现役 education 断言。 |
| `solver/tests/test_public_clean_ruler_worker_env.py` | 137／27 个函数行 | 第二档测试 | `COLLECT`：8 个；`:47-75` 两个测试只证明退役 Vidal flag 关闭/不可重开。 | 删这 2 个测试；保留环境隔离和 verdict 的 6 个。 | 回归数 −2。 |

### B. 两套 SISR 全清

| 路径 | 行数（现有／预计删） | 档位 | 证据（命令＋结果摘要） | 连带删除（测试／开关／文档步骤） | 风险／删了谁会坏 |
|---|---:|---|---|---|---|
| `solver/src/setp_solver/algorithms/resetp_alns/operators/sisr_string_removal.py` | 175／175 | 第二档 | `R-CODE(sisr_string_removal)`：生产入边只有 `winner.py` 的默认 false 开关；另有 1 个专属测试文件和历史 baseline runner。 | 删专属测试；清 `winner.py` 的 import/config/action wiring。 | 历史 SISR gate 不能复跑；其负结果报告保留。 |
| `solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py` | 3557／约 8（本节） | 第二档接线 | `R-CODE(include_sisr_string_removal)`：命中仅 `:75,238,271,284,317-318,361,1806`；赋值 `True` 只在专属测试和旧 SISR baseline。 | 删除字段、参数、operator 插入和传递；另见第三档 7 行死方法。 | 不能误删 Winner 其余 ALNS baseline 能力。 |
| `solver/tests/test_sisr_string_removal_20260718.py` | 189／189 | 第二档测试 | `COLLECT`：5 个测试，全是 SISR。 | 整文件删。 | 回归数 −5。 |
| `baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/hybrid.py` | 568／1 | 第二档接线 | `R-CODE(include_sisr_string_removal)`：现行 prototype 只传一次 `False`。 | 删该实参；`frozen_baseline/.../hybrid.py` 是冻结证据副本，不改。 | 冻结副本在当前 checkout 将不能直接配新 API 运行，但其历史字节不能改。 |

### C. 旧 ALNS 公平入口

`FACT`：用户已明确公平不得调用退役 ALNS。`search/fairness.py:29-314` 的三个入口会调用 `run_alns_wouda`；`formal_runner.py` 的旧 E3/E6 正是其生产消费者。该文件另有 47 行子算例写入 helper，被历史 E3/E6 证据代码引用，不能把消费者假装成 0。

| 路径 | 行数（现有／预计删） | 档位 | 证据（命令＋结果摘要） | 连带删除（测试／开关／文档步骤） | 风险／删了谁会坏 |
|---|---:|---|---|---|---|
| `solver/src/setp_solver/search/fairness.py` | 533／净约 473 | 第二档＋最小搬移 | AST/`R-CODE(setp_solver.search.fairness)`：12 个非报告消费者；其中生产只有 `formal_runner`/package export，7 个 baseline 文件只取 `_subinstance_for_depot/_write_subbundle/_node_payload`，2 个旧 prototype 取 ALNS 入口。交付前状态已是 `D`，但 7 个 helper import 仍在，且触发 13 个收集错误。 | 把三 helper（原文件 `:317-363`）从 `HEAD` 逐字恢复到 `baselines/e3_ablation/_legacy_subbundle.py`，只配最小 import；更新 7 个 baseline import。不要恢复旧 ALNS 入口。 | 当前是“提供者已删、消费者未迁”的断裂状态；`solver/reports/formal/run_w2_parallel_chain.py` 又位于明确排除的 reports 内，需复跑时 checkout 旧 commit。 |
| `solver/src/setp_solver/search/__init__.py` | 84／5 | 第二档接线 | `R-CODE(run_independent_profit_baselines)`：`:29,71-74` 只有旧 lazy export。 | 删除 export/`__getattr__` 分支。 | 无现役调用者。 |
| `solver/src/setp_solver/search/formal_runner.py` | 2257／约 555 | 第二档接线 | 分别执行 `R-CODE(run_e3_ablation)`、`R-CODE(run_e6_fairness_scan)`、`R-CODE(_e3_)`、`R-CODE(_e6_)`，结果与 `execution_blueprint_20260818.md:1535-1539` 的逐函数清单一致，消费者只剩 parser/旧测试。 | 删除 `run_e3_ablation`、`run_e6_fairness_scan`、全部 `_e3_*` runner/table helper、`_e6_*`、`_prices_with_theta`、`_min_ratio`、`_ratio_text`，共 547 个函数行；删 parser 的 E3/E6 choices、`--variants/--thetas` 和 dispatch。仍需的 `infer_customer_home_depots` 直接从 `profit.py` import。 | 保留 E4 的纯碳函数与测试；不能按连续大行段误删 E4/E5/E7。 |
| `solver/tests/test_profit.py` | 471／58 | 第二档测试 | `COLLECT`：9 个；`:410-467` 唯一旧 concatenated seed 测试。 | 删除该测试。 | 回归数 −1；其余 8 个利润/公平精算测试保留。 |
| `solver/tests/test_formal_runner.py` | 986／59 | 第二档测试 | `COLLECT`：39 个；`:631-693` 3 个测试只覆盖旧 E3 runner，`:545-606` 3 个纯碳测试不调用 ALNS。 | 删 3 个旧 E3 测试和 2 条 helper import。 | 回归数 −3；保留 36 个。 |
| `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/run_stage1_algorithm_closeout.py` | 1319／1319 | 第二档旧 prototype | `R-CODE(run_stage1_algorithm_closeout)`：无代码消费者；只被同目录 README 当历史命令；内部调用旧 `run_independent_profit_baselines`。 | 与下一行一起删。 | README 命令陈旧；旧 prototype 结果仍在 git/证据包。 |
| `baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/test_fairness_deficit_decoder.py` | 129／129 | 第二档旧测试 | `COLLECT`（baseline 路径）：1 个测试，只测上一行旧公平入口。 | 整文件删。 | 不计入 1197 的 `solver/tests` 基数。 |

### D. 兼容 shim 与旧 LNS policy 岛

| 路径 | 行数 | 档位 | 证据（命令＋结果摘要） | 连带删除（测试／开关／文档步骤） | 风险／删了谁会坏 |
|---|---:|---|---|---|---|
| `solver/src/setp_solver/search/resetp_alns/__init__.py` | 15 | 第二档 | AST import 图：仅 3 个 solver 测试引用；canonical 在 `algorithms/resetp_alns/runtime`。 | 三个测试改为直接 import canonical runtime。 | 旧包路径消失。 |
| `solver/src/setp_solver/search/resetp_alns/accept.py` | 2 | 第二档 | 文件内容是 deprecated star-import；`R-CODE(search\.resetp_alns\.accept)` 和 `R-CODE(search/resetp_alns/accept\.py)` 均为 0。 | 与 shim 一起删。 | 旧包路径消失。 |
| `solver/src/setp_solver/search/resetp_alns/outcome.py` | 2 | 第二档 | 文件内容是 deprecated star-import；`R-CODE(search\.resetp_alns\.outcome)` 和 `R-CODE(search/resetp_alns/outcome\.py)` 均为 0。 | 与 shim 一起删。 | 旧包路径消失。 |
| `solver/src/setp_solver/search/resetp_alns/select.py` | 2 | 第二档 | 文件内容是 deprecated star-import；代码 import 检索为 0；`R-CODE(search/resetp_alns/select\.py)` 只命中 2 个旧审计字符串，不是运行入边。 | 与 shim 一起删。 | 旧包路径消失；两份历史审计仍会记录旧路径。 |
| `solver/src/setp_solver/search/lns_policy_kernel.py` | 143 | 第二档 | `R-CODE(lns_policy_kernel)`：仅 2 个旧测试和一个 2026-07-08 probe；`R-NOW` 为 0。 | 与下两行一起删。 | 历史 A13 probe 不能复跑。 |
| `baselines/e2_alns/lns_policy_kernel_probe.py` | 697 | 第二档 | 唯一生产消费者，当前文档无步骤；旧 docs 仅历史记账。 | 整文件删。 | 保存的 probe 结果不动。 |
| `solver/tests/test_lns_policy_kernel.py` | 33 | 第二档测试 | `COLLECT`：2 个测试，只覆盖上述退役接口。 | 整文件删。 | 回归数 −2。 |

## 第三档：混合文件按函数削

| 路径 | 行数（现有／预计删） | 档位 | 留什么／删什么 | 证据（命令＋结果摘要） | 风险／连带动作 |
|---|---:|---|---|---|---|
| `solver/src/setp_solver/algorithms/problem_hgs/dcrex.py` | 580／约 578 | 第三档 | **留** `DISCOUNT_FACTOR = 0.99` 两行桥；**删**其余全部类和函数。 | 分别执行 `R-CODE(DCREXController)`、`R-CODE(InsertionOperator)`、`R-CODE(DiscountedUCB1)`：只被待删 public/crossover/repair 岛引用；唯一现役残边是排除中的 `runner.py:40,64` 引 `DISCOUNT_FACTOR`。 | 本轮不能碰 runner，故不能整文件删；初始化施工落地后的下一批可再消掉这两行桥。 |
| `solver/src/setp_solver/algorithms/problem_hgs/crossover.py` | 647／约 192 | 第三档 | **留** `FleetRegistryEntry`、`DutyCrossoverResult`、`canonical_fleet_registry`、`trip_assignment_exchange`、`trip_assignment_exchange_candidates` 及其后续 helper；**删** DCREX import、`DutyDCREXResult`、`dcrex_duty_exchange`、`_route_genes`、`selective_duty_exchange`。 | `VULTURE` 列出 DCREX/`selective_duty_exchange`；全仓符号检索只有本文件/待删岛，现役 `integrated_private.py` 只 import `DutyCrossoverResult` 和 `trip_assignment_exchange_candidates`。 | 不得误删现役第二父代的**客户顺序/任务交换**；P114 删的是车型继承需求。 |
| `solver/src/setp_solver/algorithms/problem_hgs/repair.py` | 420／约 200 | 第三档 | **留** `regret2_repair`、`insertion_moves`、`_insertion_moves`、`_repair_key`；**删** `dcrex_repair`、`_choose_dcrex_insertion` 和 `InsertionOperator`/`random` import。 | `VULTURE`＋`R-CODE(dcrex_repair)`：无外部调用；`initialization.py` 真 import `regret2_repair/insertion_moves`。 | 这是初始化在途邻接文件；下一写手须等其落地后重核 import，不能本会话动。 |
| `solver/src/setp_solver/algorithms/problem_hgs/__init__.py` | 90／3 | 第三档接线 | 删除 `DCREXController`、`InsertionOperator` import/export；其余全留。 | `R-CODE`：两名称无外部消费者。 | 当前文件已被并行施工修改；只在 rebase 后做三行机械删除。 |
| `solver/src/setp_solver/algorithms/resetp_alns/kernel/alns_core.py` | 1218／83 | 第三档 | 删 `_EvalOrRuntimeStop`(21)、`_count_table`(2)、`multi_customer_removal`(12)、`identity_repair`(5)、`_try_cv_to_ev`(3)、`_try_ev_to_cv`(3)、`_ranked_repair_routes`(8)、`_ranked_insert_positions`(16)、`_repair_route_delta_score`(10)、`_worst_customer_by_distance_contribution`(3)。 | `VULTURE` 与 `R-CODE(上述符号)`：除定义外 0 调用；`test_search.py` 只断言 `identity_repair` 不在活动计数。 | 删除 unused import `feasible_route_customers/feasible_route_distance` 时先让 ruff 复核；不删候选版 `_try_*_candidates`。 |
| `solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py` | 3557／7（另有第二档 8） | 第三档 | 删 `WinnerOperatorSet.destroy_index`(2)、`repair_index`(2)、`_scan_route_distance`(3)。 | `VULTURE`＋全仓精确符号检索均只命中定义。 | `decode_winner_action`、`run_e2_alns_final` 虽被 Vulture 标红，但仍被 API manifest／静态审计字符串消费，本批不删。 |
| `solver/src/setp_solver/algorithms/resetp_alns/support/construction.py` | 628／6 | 第三档 | 删 `_seed_route_limit`。 | `VULTURE`＋全仓精确符号检索仅定义。 | 无。 |
| `solver/src/setp_solver/algorithms/resetp_alns/support/fleet.py` | 320／10 | 第三档 | 删 `_first_number`。 | `VULTURE`＋`R-CODE(_first_number)`：本文件中的定义无调用。 | 无。 |
| `solver/src/setp_solver/algorithms/resetp_alns/support/order_decoder.py` | 287／23 | 第三档 | 删 `exploratory_type_hints`(4)、`mutated_type_hints`(19)。 | `VULTURE`＋分别执行 `R-CODE(exploratory_type_hints)`、`R-CODE(mutated_type_hints)`：本文件中的两定义无调用；同名 `search/order_decoder.py` 是另一份定义，不能误算成消费者。 | 无。 |
| `solver/src/setp_solver/algorithms/resetp_alns/support/timing.py` | 55／4 | 第三档 | 删 `record_timing`。 | `VULTURE`＋`R-CODE(record_timing)`：本文件中的定义无调用。 | 受保护的同目录 `charging.py` 零修改。 |
| `solver/src/setp_solver/search/construction.py` | 645／6 | 第三档 | 删另一份 `_seed_route_limit`。 | `VULTURE`＋精确符号检索仅定义。 | 无。 |
| `solver/src/setp_solver/search/fleet.py` | 320／10 | 第三档 | 删另一份 `_first_number`。 | `VULTURE`＋`R-CODE(_first_number)`：该文件中的定义无调用。 | 无。 |
| `solver/src/setp_solver/search/order_decoder.py` | 287／23 | 第三档 | 删 `exploratory_type_hints`、`mutated_type_hints`。 | `metaheuristic_baselines.py` import 的是带 `_shared_` 别名的其他现用函数；这两个精确符号无调用。 | 依函数名复核，不按相邻行整段删。 |
| `solver/src/setp_solver/search/timing.py` | 55／4 | 第三档 | 删 `record_timing`。 | `VULTURE`＋精确符号检索仅定义。 | 无。 |
| `solver/src/setp_solver/search/candidates.py` | 2022／9 | 第三档 | 删 `_apply_path_operator`(7)、`_route_set_distance`(2)。 | `VULTURE`＋全仓精确符号检索仅定义。 | 其余候选和 `run_candidate` 仍被 formal/baseline 调用，全留。 |
| `solver/src/setp_solver/search/instance_registry.py` | 104／2 | 第三档 | 只删 `formal_instance_names`。 | `VULTURE`＋精确符号检索仅定义。 | `iter_formal_bundles` **不删**：`baselines/contract_audit/submission_contract_candidate.py` 真调用。 |
| `solver/src/setp_solver/search/alns_crush.py` | 1143／42 | 第三档 | 删 `_phase0_solutions`。 | `VULTURE`＋全仓精确符号检索仅定义。 | 其余 old-baseline 分析仍有测试，不能扩大。 |
| `baselines/e2_alns/run_homberger_g1_sisr_20260718.py` | 965／净约 626 | 第三档 | **留并搬** 13 个通用 helper：`DevelopmentGateError`、hash/atomic 写入、bundle/price/initial/recompute 等；**删** `run_arm`、`paired_rows`、`decide`、`report_text`、`write_evidence`、`execute`、CLI 和 SISR 常量/import。 | AST 外部 import 表显示 8 个 TrueSwapStar/repair 脚本取通用 helper；SISR 实验逻辑从 `run_arm:392` 起，无现役入口。 | 把通用 helper 原样搬到 `baselines/e2_alns/homberger_g1_helpers_20260718.py` 并改 8 个 import；这是本清单最易因漏 consumer 出错的一项。 |

### `population.py`：审过，本批删 0 行

`FACT`：`solver/src/setp_solver/algorithms/problem_hgs/population.py` 当前 603 行。必须保留：

- `PopulationParameters`、`PenaltyParameters`：runner、integrated private、execution identity 和多组现役测试使用；
- `EvaluatedDutyCandidate`、`PopulationAdmission`、`AdaptivePenaltyManager`、`DutyPopulation`：private technical runner 仍在 `:2842-2843,3566-3567` 真调用；
- `broken_pairs_distance` 及 `_neighbour_distance`、`_duty_neighbours`、`_average_close_distance`、`_candidate_distance`、`_clip`：前者由 integrated private 使用，后者是其内部闭包。

`FACT`：Vulture 对 `bi_objective_population.best_penalised` 的告警是泛型接口假阳性；`IntegratedGeneticAlgorithm` 通过 population 协议动态调用，不能删。

`DECISION`：本轮不要借“population 混合身份”提前改初始化/runner。等并行初始化施工落地后，若 `DutyPopulation` 的两处 runner 调用真的消失，再另批重新画入边图；本清单不预判。

## P114 三件“删需求”残码核查

| 已删需求 | 检索命令与事实 | 本清单处置 |
|---|---|---|
| 第二父代车型继承 | `rg -n -i 'second[-_ ]parent|parent[_ ]?2|donor.*vehicle|vehicle.*inherit' solver/src solver/scripts solver/tests --glob '*.py'`：命中的是现役动态阶段车辆状态继承、runner 的第二父代形成记录、DCREX donor 同型检查和客户/任务交换；未找到“从第二父代继承车型”的独立实现。 | 没有专门残码可删。DCREX 因自身退役按第三档删；现役 crossover 的客户顺序/任务交换保留。 |
| 共享充电桩联合调度 | `rg -n -i 'joint.*charg|charg.*joint|shared.*charg|charger.*capacity|station.*capacity' ...`：命中 `check.py`、模型语义、`schedule_oracle.py`、动态容量检查和两份受保护 charging；没有独立的“必须新增联合调度组件”。 | 不删模型语义，不删 `schedule_oracle.py`，五冻结文件不动。P114 删的是欠账，不是既有约束。 |
| 估价假阴性救回 | `rg -n -i 'false.?negative|proxy.*rescue|truth.*shortlist|proxy_improv' ...`：命中现役 truth shortlist 计数与测试；该机制只对已进入 proxy shortlist 的候选精算，没有扫描 proxy 非改善候选，故不是假阴性救回半成品。 | 无残码可删；`kernel_proposals.py`/`education.py` 又属现役及在途范围，明确排除。 |

## 明确不入清单

### 五冻结文件

本会话只读哈希如下，零修改：

| 路径 | 当前 SHA-256 |
|---|---|
| `solver/src/setp_solver/cost.py` | `13ae664bae0e9c8b5033780fbbc43cedcd43c626ac1eb23023a4a667bd2d1bbd` |
| `solver/src/setp_solver/check.py` | `1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072` |
| `solver/src/setp_solver/search/evaluation.py` | `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3` |
| `solver/src/setp_solver/algorithms/problem_hgs/charging.py` | `3a7da9df0241bed566240d9e9359be4b7dc6e0edd8a385d085ddce48482fc2a5` |
| `solver/src/setp_solver/algorithms/resetp_alns/support/charging.py` | `7c2d8df0427626ef7c1ab487dbb44360ea82e07d6e9ce3b0e889502f27cfc171` |

下一写手开工前须重新取一次哈希，因为当前并行会话已在工作树修改其中部分文件；本表只是侦察时点身份，不是要求回滚别人的改动。

### 现役与证据

- 初始化施工范围：`kernel_proposals.py`、`initialization.py`、`runner.py` 及其当前接线，不列删；`repair.py`/`__init__.py` 的第三档动作只能在该会话落地后重基。
- 现役 public/private/dynamic 入口、`solver/reports/`、算例数据、builders/generators/finalizers 中仍承担当前算例溯源者均不删。
- `baselines/china_e3_e7/e7_o1_replanning_20260801/policy.py` 不是孤儿：`run_mechanical_dynamic_baseline.py:53` 和 `run_problem_hgs_dynamic_disclosure_scout.py:87` 真 import；动态 stream/trigger 文件也由现役脚本取 hash，全部保留。
- `run_problem_hgs_dynamic_disclosure_scout.py`、`run_mechanical_dynamic_baseline.py`、`run_problem_hgs_c8_stream.py`、`generate_c8_dynamic_stream.py` 保留。
- `schedule_oracle.py`、`dcrex.py` 中唯一在用的 `DISCOUNT_FACTOR`、`population.py` 全部当前消费者保留。
- Vulture 假阳性明确保留：decorator 注册的 reporting runners；子进程代码字符串调用的 `winner_nondeterminism._winner_kernel_payload`；baseline 真调用的 `iter_formal_bundles`；动态/哈希/协议字段；所有五冻结文件内标红项。

### 已由并行会话删除、不得重复计数

侦察启动时，`git status` 已显示另一会话删除了旧 `solver/src/setp_solver/algorithms/duty_hgs/` 整包、其 3 个 runner、6 个专项测试，另删了旧 public/SISR launcher 以及 `problem_hgs/{feedback,independent}.py`。这些不进入本清单的 13,300 行总账；下一写手不得恢复后再删来虚增数字。

交付前又观察到本清单范围内的公平项已被外部写手先行施工：`fairness.py` 删除 533 行，`formal_runner.py` 当前 diff 为 `+3/-605`，`search/__init__.py` 为 `+0/-5`，`test_formal_runner.py` 为 `+2/-108`，`test_profit.py` 为 `+0/-141`。这批 diff 尚未闭合，因为 baseline helper import 仍指向已删文件。它们计入上面的 **13,300 行毛目标**，但下一写手只应核对和补齐，不得再次计为新增删除量；也不能把这些实际删行机械地从 13,300 相减，因为外部 diff 的函数边界与本清单估算并不完全相同。

## 回归基数账

| 测试位置 | 启动快照收集数 | 计划删除数 | 目标删后数 |
|---|---:|---:|---:|
| `test_problem_hgs_public_assignment.py` | 1 | 1 | 0 |
| `test_problem_hgs_vidal_compound.py` | 10 | 10 | 0 |
| `test_problem_hgs_sisr.py` | 8 | 8 | 0 |
| `test_problem_hgs_crossover_control.py` | 3 | 2（1 个迁走） | 1 |
| `test_public_clean_ruler_worker_env.py` | 8 | 2 | 6 |
| `test_sisr_string_removal_20260718.py` | 5 | 5 | 0 |
| `test_profit.py` | 9 | 1 | 8 |
| `test_formal_runner.py` | 39 | 3 | 36 |
| `test_lns_policy_kernel.py` | 2 | 2 | 0 |
| **`solver/tests` 总计** | **1197** | **34** | **1163** |

另：`baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/test_fairness_deficit_decoder.py` 删除 1 个 baseline 局部测试，不在上表 1197 内。

`FACT`：这里只做了两次 `--collect-only`，没有运行 solver、实验或测试正文，也没有生成 pytest cache/pyc。第一次建立 1197 基数；第二次暴露并行删除造成的 13 个收集错误。

## 执行顺序建议

`DECISION`：建议分两批，不建议把约 13,300 行塞进一个不可定位的巨型 patch。两批不是新增科学门槛，只是让故障能定位。

1. **第一批：先闭合已经断开的公平 helper，再清其余删除岛。** 等初始化会话落地并重基后，先从 `HEAD` 把三个纯 helper 搬到 baseline 局部模块并改完 7 个 import，使收集不再因 `fairness.py` 缺失而中断；不恢复旧 ALNS 入口。然后在同一原子 patch 中完成第一档、公开退役岛、两套 SISR、shim、LNS policy 及专属测试。其余项目仍遵守“先改保留的消费者/import/CLI/test，再删 provider”。随后只做 import/collect/full regression。
2. **第二批：混合文件削骨。** 按第三档函数名删除 DCREX、repair/crossover、两份 ALNS support 死函数和 baseline SISR tail；先把通用 helper 原样搬完并核完 8 个消费者，再删旧实现。随后跑全量 1163 回归，再按 P115 跑私有/公开最小冒烟，核完整服务客户数和需求量。

每批最后都执行：

```bash
rg -n 'enable_sisr|sisr-enabled|disable-vidal-compound|enable_vidal_compound|enable_customer_relocation|include_sisr_string_removal' \
  solver/src solver/scripts solver/tests baselines --glob '*.py' --glob '*.sh'

rg -n 'setp_solver\.search\.fairness|setp_solver\.search\.resetp_alns|lns_policy_kernel' \
  solver/src solver/scripts solver/tests baselines --glob '*.py' --glob '*.sh'

git diff --numstat
```

第一条允许冻结历史副本中保留旧字串，但现役 `solver/src`/`solver/scripts` 应为 0；第二条只允许明确登记且不能修改的 `solver/reports` 历史脚本（该命令本身未扫 reports）。

## 我最没把握的三条

1. **`run_homberger_g1_sisr_20260718.py` 的通用 helper 与 SISR 主体切割。** 八个 TrueSwapStar/repair 消费者使它不能整文件删；函数边界清楚，但搬家后的 import 漏一处就会让历史 baseline 崩。
2. **R2 shell 整岛。** 当前事实源和现役流程均零引用，删它们最符合 P115；但它们仍是旧正式结果的便利复跑入口。git 能恢复源码，保存产物不受影响，是否还要求“当前 checkout 一键复跑旧 R2”是唯一剩余取舍。
3. **`problem_hgs/dcrex.py` 的两行常量桥。** DCREX 主体已无现役消费者，但并行范围内的 `runner.py` 仍 import `DISCOUNT_FACTOR`；初始化施工落地后，这条边可能保留、迁走或消失。当前只能确定删主体，不能预先承诺整文件删。
