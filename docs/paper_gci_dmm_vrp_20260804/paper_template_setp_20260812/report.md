# 2026-08-12 旧稿退役、期刊模板与同刊惯例调查报告

## 结论

三项任务均已完成：两份旧正文已改名并加退役声明；`setp-new.cls` 空白模板已编译出 2 页 A4 PDF；同刊惯例合同已完成，首行为 `CONVENTION_DONE`。本轮未运行求解器或实验，未改算例、算法参数和三个受保护文件，也没有把任何旧实验数字迁入模板或新合同。

## 一、旧正文退役

### 1. 产物

- `docs/paper_submission_final/RETIRED_paper_main.tex`
- `docs/paper_v2/RETIRED_paper_main.tex`

两份文件开头各增加 10 行显著声明，分别写明旧稿所属时代、退役原因、现行正文路径 `docs/paper_gci_dmm_vrp_20260804/paper_main_foundation_v2_20260812.md`，以及任何人不得引用、迁移或改写其中实验数字作为当前论文证据。

### 2. 原正文未被改写

去掉新增的前 10 行后，两份退役稿均与 Git 中改名前的正文逐字节相同，`cmp` 返回 0：

```bash
cmp -s <(tail -n +11 docs/paper_submission_final/RETIRED_paper_main.tex) \
  <(git show HEAD:docs/paper_submission_final/paper_main.tex)

cmp -s <(tail -n +11 docs/paper_v2/RETIRED_paper_main.tex) \
  <(git show HEAD:docs/paper_v2/paper_main.tex)
```

原正文 SHA-256：

- 英国算例、英镑与 TVCI-ALNS 时代稿：`6936bcf31d37c65c5f1100416a5406443c506c060c5b8823df696ac311d0f735`
- 由旧稿迁移至 China81/MV-HGS-SP 的 V2 时代稿：`76425e69ee7e0c0ffe7697dcad72eaf9e6803b95a10ce6ccd383410ffa81096f`

### 3. 路径引用更新

只改了路径字符串，没有改引用文件原有的结论文字：

| 旧路径 | 修改前 | 修改后仍保留（排除本报告） | 已更新 |
|---|---:|---:|---:|
| `docs/paper_submission_final/paper_main.tex` | 289 文件、506 个匹配行 | 244 文件、454 个匹配行 | 45 文件、52 行 |
| `docs/paper_v2/paper_main.tex` | 357 文件、788 个匹配行 | 347 文件、778 个匹配行 | 10 文件、10 行 |

两条路径去重后更新 53 个可维护引用文件；另同步修正现行中国化台账中的相对路径和声明新增后的行号，合计 54 个文件。

更新范围包括仓库 README、仍会读取旧稿的审计/构建脚本、`docs/paper_v2` 的 README 与两个构建脚本，以及当前的中国化台账。完整清单如下。

<details>
<summary>展开 54 个已更新引用文件</summary>

```text
README.md
baselines/algorithm_prototypes/mda_ils_vns_20260720/run_adaptive_gate.py
baselines/algorithm_prototypes/mda_ils_vns_20260720/run_dual_regime_gate.py
baselines/algorithm_prototypes/mda_ils_vns_20260720/run_foundation_gate.py
baselines/algorithm_prototypes/mda_ils_vns_20260720/run_late_stage_gate.py
baselines/algorithm_prototypes/mda_ils_vns_20260720/run_parameter_race_gate.py
baselines/algorithm_prototypes/mpils_mvns_c2_20260720/run_g1_b_first_fire.py
baselines/algorithm_prototypes/resource_slot_pricing_20260725/build_registration.py
baselines/algorithm_prototypes/unified_mechanism_alns_20260719/run_mechanism_priced_pair_resplit_behavior_gate.py
baselines/china_e3_e7/adapter.py
baselines/china_e3_e7/contract.py
baselines/china_e3_e7/formal_ablation_200c_20260803/run_xa2_formal.py
baselines/china_e3_e7/run_carbon_timing_rescore_20260802.py
baselines/china_e3_e7/run_e5_nonlinear_20260729.py
baselines/china_e3_e7/run_formal_fleet_levels_xb_20260802.py
baselines/china_e3_e7/scout_depot_ownership_20260803/run_scout_d.py
baselines/china_e3_e7/scout_three_mechanisms_20260803_runner.py
baselines/contract_audit/e1_e7_submission_contract_audit.py
baselines/e2_alns/alns_independence_migration.py
baselines/e2_alns/balanced_selector_probe.py
baselines/e2_alns/bridge_fix_validation.py
baselines/e2_alns/decoder_fix_validation.py
baselines/e2_alns/e2_final_closure.py
baselines/e2_alns/e2_g0_closure_hygiene.py
baselines/e2_alns/e2_g0_reaudit.py
baselines/e2_alns/fleet_cap_operational_gate.py
baselines/e2_alns/goeke80_multitrip_rescue_gate.py
baselines/e2_alns/goeke80_multitrip_t3_preflight.py
baselines/e2_alns/hard_cap_feasibility_audit.py
baselines/e2_alns/lns_acceptance_scheduler_audit.py
baselines/e2_alns/route_compression_probe.py
baselines/e2_alns/route_compression_trace_audit.py
baselines/e2_alns/selector_pathology_audit.py
baselines/e2_alns/selector_sprint_failure_analysis.py
baselines/e2_alns/selector_sprint_probe.py
baselines/e2_final_campaign_20260720/p2p3_threeview/full_gate/run_s2_full_threeview.py
baselines/e2_final_campaign_20260720/p2p3_threeview/full_gate/run_s2_revision_v2.py
baselines/e2_final_campaign_20260720/p2p3_threeview/preflight_gate/run_s1_threeview_preflight.py
baselines/e2_final_campaign_20260720/p2p3_threeview/representative_gate/run_s3_representative.py
baselines/e2_final_campaign_20260720/p2p3_threeview/representative_gate/s3_traj_v4/run_s3_trajectory_v4.py
baselines/e2_final_campaign_20260720/p2p3_threeview/table4_gate/run_s4_route_detail_v2.py
baselines/e3_ablation/e3_story_forensic_audit_20260713.py
baselines/model_verification/china_order_attribute_formula_validation_20260718.py
baselines/model_verification/paper_math_audit_20260716.py
baselines/model_verification/verify_charging_curve_nl0_20260720.py
baselines/model_verification/verify_china81_nonlinear_cost_check_nl2_20260720.py
baselines/model_verification/verify_china81_nonlinear_schedule_nl1_20260720.py
baselines/paper_story/audit_20260715_paper_evidence_boundaries.py
baselines/paper_story/audit_setp_visual_contract_20260716.py
docs/paper_gci_dmm_vrp_20260804/china_standard_residue_ledger_20260812.md
docs/paper_submission_final/design_templates/你的论文vs陈雨蝶模板_差距对照表.md
docs/paper_v2/README.md
docs/paper_v2/_rebuild_constraints.py
docs/paper_v2/candidates/build_v7_integrated_paper.py
```

</details>

### 4. 有意未改的旧路径引用

剩余两条旧路径合并去重后涉及 579 个文件（排除必须引用旧串进行交付说明的本报告）：

| 类别 | 文件数 | 未改原因 |
|---|---:|---|
| 封存 JSON/CSV 实验或监控产物 | 494 | 改写会改变历史产物哈希、证据身份或当时记录；保留原路径是历史事实的一部分 |
| 历史 Markdown、交接、报告、备份时间线 | 78 | 这些文件记录当时真实路径；机械改写会把历史叙述伪装成当时已经采用新路径 |
| LaTeX 生成痕迹（`.fls`、`.fdb_latexmk`、`.log` 等） | 7 | 属构建产物，不应手工改写；后续重新构建时自然生成 |

在现行可维护源码和普通说明文档中，没有留下“无法判断是否应改”的活跃引用；未改项都是上述有明确证据保护理由的历史记录。可用以下命令枚举每个确切文件：

```bash
{
  rg -l -F --hidden --no-ignore --glob '!.git/**' \
    --glob '!docs/paper_gci_dmm_vrp_20260804/paper_template_setp_20260812/report.md' \
    'docs/paper_submission_final/paper_main.tex' .
  rg -l -F --hidden --no-ignore --glob '!.git/**' \
    --glob '!docs/paper_gci_dmm_vrp_20260804/paper_template_setp_20260812/report.md' \
    'docs/paper_v2/paper_main.tex' .
} | sort -u
```

## 二、出版社 LaTeX 模板底稿

### 1. 产物

目录：`docs/paper_gci_dmm_vrp_20260804/paper_template_setp_20260812/`

- `setp-new.cls`：从仓库现有类文件复制，未修改。
- `paper_template.tex`：只含期刊格式骨架、双语题录、五章结构、公式、三线表、图片和参考文献模板；所有正文均为占位，不含实验结论或旧实验数字。
- `paper_template.pdf`：模板实际编译所得的 2 页 A4 空骨架。
- `report.md`：本报告。

类文件源件、`docs/paper_v2/setp-new.cls` 与目标副本的 SHA-256 均为：

```text
66d2f99056efe522ab91afa2fd05c105ba7bc8d42e3a9c5cdc29c6cc0ec2efa5
```

逐字节比较均返回 0，证明类文件没有改动。

### 2. 编译结果

`FACT`：编译通过，退出码 0，生成 2 页 A4 PDF；最终日志未检出 Warning、Overfull、Underfull 或 Error。两页均已渲染检查，中文、英文、公式、三线表、图片框和参考文献无乱码、黑块或越界。

编译命令在 `/Users/zhouleixishu/.codex/plugins/cache/openai-bundled/latex/0.2.4` 目录运行：

```bash
python3 scripts/compile_latex.py \
  '/Volumes/移动硬盘（512G）/ReSETP/docs/paper_gci_dmm_vrp_20260804/paper_template_setp_20260812/paper_template.tex' \
  --compiler texlive --engine xelatex
```

最终文件 SHA-256：

- `paper_template.tex`：`30ac382a3fbfed9386efd1f50b7977b8489545ac0355b9744ac1215a09443691`
- `paper_template.pdf`：`a45cda687fbea84d07fe9350cce2b926b15886bb8b40023c0ee169d06a1c3b81`

编译中修正了两个纯模板问题：类文件的月份参数必须是 1--12 的整数，不能用中文占位；字体回退改为按字体名称探测，不再把本机绝对字体路径写进模板。这两处只影响模板可编译性和可移植性，不涉及论文内容。

## 三、同刊惯例调查与新合同

### 1. 产物

- `docs/paper_gci_dmm_vrp_20260804/journal_convention_contract_20260812.md`

该文件首行为 `CONVENTION_DONE`，SHA-256 为：

```text
2ca8f8bc4587887fd39fc6625c22b5fae3f3e385d05b5172a220ca13a9fe8658
```

旧合同 `SETP_VISUAL_CONTRACT.md` 保持不动，当前 SHA-256 为：

```text
1f6cfa2b4866e221990773e3c8237ef50bbdd3928cbc042168933ad1b7b2b7d1
```

新合同明确完成了以下更新：

- 陈雨蝶 2025 改为全文与数值实验章总母版；陈婉茹 2023 下调为单表单图工艺标准；Soriano 2023 只在同刊母版缺少公平性同型图时作为整图第二母版。
- 原样继承主母版制、缺同型图才启用第二母版、整张图只模仿一个完整系统、禁止拼装、启用新母版必须登记五项证据的规则。
- 全部保留旧合同已有实测视觉参数，并逐项标明“本轮复测”或“沿用已有记录”；没有重新猜线宽或字号。
- 清除旧算法、旧英国算例和英镑作为现行对象的身份，改写为当前四个比较对象与正式名待定的一条串行改进链。
- 为时变碳强度、混合车队、动态需求、多车场协同、公平分配、实体车多趟、非线性充电分别建立了无数字表结构。
- 写死两条执行推论：主力产物是表；广度上逐机制铺开、单元内一节一因素一主表一结论。

### 2. 同刊样本真数

本地确认同刊去重发现池 18 篇；逐项精读核心样本 7 篇。指定五篇同刊论文全部找到，Soriano 为 IJPE，未计入同刊 N。

主要共性：表题上置 7/7、图题下置 6/6 有图论文、三线表 7/7、单位集中写在列头/行名/坐标轴 7/7、参考文献顺序编号 7/7。图例位置、网格、颜色、第二编码、子图字母、章节名均有反例，因此合同把这些写成一次性母版选择，没有冒充期刊硬规则。

`CORRECTION`：陈雨蝶 PDF 的 4.3--4.8 确实都有“动机/控制条件—展品—编号解释—判断”的稳定节奏，但严格符合“一张表、四条编号、字面综上”的只有 4.3、4.4，即 2/6。新合同把 PDF 事实与本文更严格的“一节一因素一主表一结论”执行规约分开记录。

### 3. 同刊 PDF 未找到情况

- 指定的陈雨蝶、陈婉茹、李得成、姜广田、周鲜成：全部找到。
- Soriano（IJPE）：找到。
- 陈雨蝶 2025 与王勇 2025 的本地文件是网络首发版，文件内没有最终卷期页码；报告明确写“查不到”，没有补猜。
- 除上述最终出版信息外，本任务没有指定 PDF 未找到项。

## 四、铁律核对

- 未运行求解器或实验。
- 未改算例、模型、算法参数或实验结果。
- 未把旧正文数字迁入模板或新合同。
- 三个受保护文件任务前后 SHA-256 一致：

```text
cost.py              ad5b360dd255c7c4c975074a6eb3ad5e31354c2eaf7399af288670396140ccd1
check.py             1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072
search/evaluation.py c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3
```

本任务不产生实验四件套；交付物是历史正文退役、格式模板、期刊惯例合同与本报告。
