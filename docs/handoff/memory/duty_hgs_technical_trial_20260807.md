# Duty-HGS 真实输入技术试跑记忆

日期：2026-08-07

## 用户授权

用户明确允许开始试跑。授权范围是小规模真实输入技术试跑和直接暴露缺陷的修复，不含正式算法对比、统一算例、三大实验、五因素消融或论文回填。

## 已完成事实

1. 首次 `cn-jjj-10c-01-V2-LOCATIONS` 一轮试跑走通完整循环，但事后核查发现 15 个普通动作作用范围不一致：修改 CV 路线时，公共班表压缩函数同时擦除了未参与 EV 的未锁定充电。原始包保留，最终判定更正为 `TECHNICAL_TRIAL_INVALIDATED_BY_POSTRUN_SCOPE_DEFECT`。
2. 修复普通动作后，7854 个多车场多 EV 动作的实际改动范围与声明范围全部一致。随后顾问发现交叉的重复客户清理仍有同类缺陷：没有发生重复清理的 EV 也会被压缩。该处修复后增加了专门回归测试，中间试跑包标为被最终版取代。
3. 最终一轮试跑完成 10/10 客户和 3196/3196 需求量，完整检查可行、0 违规，70 次真值哨兵、73 次实际完整评价、368 行轨迹。单轮成本变化不作为性能证据。
4. 真实输入 regret-2 修复把漏服务客户从 1 降到 0，接受 1 次插入，最终 10/10 客户、完整检查可行、0 违规。
5. 原型完整测试 31/31 通过，`git diff --check` 通过，Ruff 对本轮新增和修改的 Python 文件复验通过。复验过程中先后出现过命令名和导入路径写错，均按正确项目解释器和完整导入路径重跑后通过；Ruff 首次发现的一个无用导入已经删除。
6. 三个受保护文件未修改：cost.py=`e7ea406da87a3172cd1ff7dc87fe7def536e74f197f6c67b29da2394fe42b00d`；check.py=`1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072`；search/evaluation.py=`c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3`。

## 顾问与监督

Claude Opus 5 最终意见：可以进入正式对比协议准备，当前没有代码级阻塞。Codex Luna Max 意见：可以准备协议，但技术试跑不能自动升级为正式运行。顾问意见均已回到源码、测试和保存产物核对，不具有用户决策效力。

## 仍未证明及待决边界

没有证明 Duty-HGS 优于充分收敛的 PyVRP 0.12.2 HGS，没有证明公开算例胜过文献强对手，没有证明私有算例会稳定产生三大实验和五因素效应。真实输入重启分支尚未单独触发，完整动态状态仍未接入。

正式对比前仍由用户决定：P20 正式收敛口径、正式算例、正式独立经营利润基准 Pi0、真值哨兵在正式对比中全程开启还是抽查。不得把本次技术 fixture 或临时 Pi0 复用为正式值。

## 产物位置

- 首次作废包：`baselines/algorithm_prototypes/duty_hgs_20260807/technical_trials/real_input_one_cycle_20260807/`
- 中间取代包：`baselines/algorithm_prototypes/duty_hgs_20260807/technical_trials/real_input_one_cycle_20260807_after_scope_fix/`
- 最终一轮包：`baselines/algorithm_prototypes/duty_hgs_20260807/technical_trials/real_input_one_cycle_20260807_final/`
- 多车场多 EV 动作核查：`baselines/algorithm_prototypes/duty_hgs_20260807/technical_trials/multidepot_multiev_action_scope_20260807/`
- 真实修复核查：`baselines/algorithm_prototypes/duty_hgs_20260807/technical_trials/real_input_regret2_repair_20260807/`

## 正式对比前的追加闭合

用户随后批准按 Opus 验货意见补做干净提交重放和真实重启点火，并要求修完后再由 Opus 做正式开跑前的最后技术论证。这个批准没有授权直接跑正式算法对比。

最终一轮、动作作用范围和漏服务修复三条链在干净提交 `79e8d67e` 上重放，关键轨迹或明细与此前有效包逐字节一致。重放汇总在 `technical_trials/preformal_provenance_reverify_20260807/`。同一提交上把重启阈值暂时缩短到 1 轮，只为点亮分支，3 轮中实际触发 1 次重启，结果仍为 10/10 客户、3196/3196 需求、完整检查可行、0 违规；证据在 `technical_trials/preformal_restart_ignition_20260807/`。

Opus 进一步审查后，撤回了“技术脚本干净门会阻塞正式运行”“当前必须立即接正式对手”等不属于核心缺陷的担忧；确认唯一仍成立的代码级阻塞是每个动作的完整轨迹一直留在内存。运行器现支持分批写出和关闭内存保留，无写出接口时会拒绝关闭保留。干净提交 `c410d24b` 上的 3 轮真实输入试跑实际写出 876 行、内存不保留，并触发 1 次重启；证据在 `technical_trials/preformal_streaming_restart_20260807/`。

完整真值复核现为默认开启的显式开关。关闭后的真实输入一轮试跑记录 0 次真值哨兵、3 次必要完整模型评价，结果仍为 10/10 客户、3196/3196 需求、完整检查可行、0 违规；证据在 `technical_trials/preformal_sentinel_off_20260807/`。该试跑只证明开关真实接通，不决定正式比较中是全开还是抽查。

测试增至 34/34 通过，Ruff 和 `git diff --check` 通过。三项受保护文件仍未修改。工程核心已具备进入正式对比协议设计的条件，但正式停止口径、算例、Pi0、真值复核用法、算法主张大小仍须用户批准；同预算 PyVRP 0.12.2 HGS 需在正式协议中经现有适配器接入。小试里的时变碳充电动作仍全部 `NO_CHANGE`，算法对这部分问题是否真正有效尚无证据，必须由后续正式算例和消融回答。
