# T7 评价链碳一致性修复（2026-08-04）

## 事实

T5 budget 1000/seed1 的 O/C 旧 witness 路线与充电量逐位相同，但充电排放为
43.064987→57.304565 kg。回放显示，同一 witness 在 search bundle 与 reporting bundle
的充电排放、电费逐臂相等；48 槽内部为 0-based、输入展示为 1-based，profile 按充电节点
城市筛选，北京/天津没有交叉取数。T5 route-pool 的 exact physicalize/recheck 不重新选择
既有充电 start。

## 根因与修复

`solver/src/setp_solver/china81_completion.py` 原先无条件生成 `ev_low_carbon/legacy`。
`solver/src/setp_solver/algorithms/resetp_alns/support/charging.py` 的 legacy 分支直接按
最低碳槽排程，不服从 O/P 零碳价的运营成本-only 目标；因此 O/P 控制臂被隐藏碳择时污染，
C 臂按电费与小额货币碳项权衡时可更便宜但更脏。修复后仅当 bundle 碳价为正时加入 legacy
变体，未改保护文件、成本公式、碳价、碳数据、算例、约束或车队合同。

## 验证边界

同 T5 配置 18/18 完整合法；search/final 充电排放与电费最大差 0；6 个 C-O 配对路线改变
4/6、系统排放下降 6/6，所有服务量 50/50 与 13264/13264。预算1000/seed1 路线已不同，
所以原同路线同电量矛盾不再成立；C 充电排放仍高 19.886912 kg，但系统排放低 16.817447 kg，
这是换路换电量后的目标权衡，不是论文证据。

权威产物：`docs/handoff/eval_chain_carbon_consistency_20260804/`。
