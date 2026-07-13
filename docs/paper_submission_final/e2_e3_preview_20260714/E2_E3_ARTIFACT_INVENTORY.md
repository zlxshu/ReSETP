# E2—E3 论文产物清单

## 正文产物

E2 正文包含两张三线表和一张图：九种算法综合表现、所提算法与八种对比算法的配对检验、代表网络上的收敛过程。E3 正文包含三张三线表和两张图：客户责任范围地理聚集的直接影响、客户责任范围空间结构、九张网络上的协同成本节省、协同成本节省的来源，以及车辆和充电空档的结果边界说明。

## 附录产物

附录保留 E2 的 16,000 次评价探针、80 kWh 电池边界检验和固定路线充电能力审计；E3 保留九张网络逐一列出的协同节省表。它们用于解释正文结论的适用范围，不与正文主图重复讲故事。

## 证据来源

E2 主结果来自 `baselines/e2_alns/e2_final_10seed_20260711/formal/`，收敛数据来自 `baselines/e2_alns/e2_final_10seed_20260711/figures/f2_convergence_curves.csv`。E3 主结果来自 `baselines/e3_ablation/e3_paired_cost_formal_v2_20260713/`，客户责任图来自 `baselines/e3_ablation/e3_ownership_class_design_v4_20260713/`。本次只做论文组织、制表和绘图，没有重新搜索路线，也没有改变封存数据。

## 可交付文件

论文预览为 `paper_e2_e3_preview.pdf`，正文源文件为 `paper_e2_e3_preview.tex`，图表生成脚本为 `baselines/paper_story/build_e2_e3_setp_preview_20260714.py`，视觉依据和禁止事项见 `SETP_VISUAL_CONTRACT.md`。
