# 09r 车辆硬上限可行性只读审计

Verdict: `HARD_CAP_CAPACITY_INFEASIBLE_CURRENT_Q`

## 一句话结论

在当前 `Q=1600kg` 且 `num_cv/num_ev` 是硬上限的口径下，E2 69 个正式实例全部从容量下界就不可行。

这不是 warm start 笨，也不是 ALNS 没搜到；只要“一条 route 占用一辆车”成立，`总车辆数 × 1600kg < 总需求` 就已经把可行性否掉了。

## 当前事实

- Repo HEAD: `316c0eb5`
- Artifact commit hash: `316c0eb5`
- 当前代码/论文容量 `Q`: `1600.0` kg
- Goeke 反事实容量: `3650.0` kg
- 论文 hard-cap 公式存在: `True`
- 车辆硬约束说明存在: `True`
- 审计实例: `69/69`
- 来源一致性: `69/69`

## 容量下界结果

| 口径 | 容量下界不可行 | 容量下界可行 | 解释 |
|---|---:|---:|---|
| 当前 Q=1600kg | 69 | 0 | 当前正式参数；若车辆数为硬上限，则这些实例不能进入正式 E2/T3。 |
| Goeke Q=3650kg 反事实 | 1 | 68 | 只用于说明冲突是否来自容量口径；本报告不自动改参数。 |

## 最严重的当前 Q 缺口

| category | instance | cap | demand kg | Q=1600 capacity kg | surplus kg | current lower bound |
|---|---|---:|---:|---:|---:|---:|
| threeshift | e2-threeshift-200c-02 | 24 | 93401.0 | 38400.0 | -55001.0 | 59 |
| threeshift | e2-threeshift-200c-03 | 27 | 96754.0 | 43200.0 | -53554.0 | 61 |
| vanilla | e2-vanilla-200c-03 | 27 | 95957.0 | 43200.0 | -52757.0 | 60 |
| multidepot | e2-multidepot-200c-03 | 27 | 95957.0 | 43200.0 | -52757.0 | 60 |
| vanilla | e2-vanilla-200c-01 | 28 | 97152.0 | 44800.0 | -52352.0 | 61 |
| multidepot | e2-multidepot-200c-01 | 28 | 97152.0 | 44800.0 | -52352.0 | 61 |
| vanilla | e2-vanilla-200c-02 | 24 | 85390.0 | 38400.0 | -46990.0 | 54 |
| multidepot | e2-multidepot-200c-02 | 24 | 85390.0 | 38400.0 | -46990.0 | 54 |

## Goeke Q=3650 反事实边界

| category | instance | cap | demand kg | Q=3650 capacity kg | surplus kg | Goeke lower bound |
|---|---|---:|---:|---:|---:|---:|
| threeshift | e2-threeshift-200c-02 | 24 | 93401.0 | 87600.0 | -5801.0 | 26 |
| vanilla | e2-vanilla-15c-01 | 2 | 7219.0 | 7300.0 | 81.0 | 2 |
| multidepot | e2-multidepot-15c-01 | 2 | 7219.0 | 7300.0 | 81.0 | 2 |
| vanilla | e2-vanilla-25c-03 | 3 | 10520.0 | 10950.0 | 430.0 | 3 |
| multidepot | e2-multidepot-25c-03 | 3 | 10520.0 | 10950.0 | 430.0 | 3 |
| vanilla | e2-vanilla-25c-01 | 3 | 10504.0 | 10950.0 | 446.0 | 3 |
| multidepot | e2-multidepot-25c-01 | 3 | 10504.0 | 10950.0 | 446.0 | 3 |
| threeshift | e2-threeshift-100c-03 | 13 | 46903.0 | 47450.0 | 547.0 | 13 |

## 构造器 smoke 只作旁证

构造器 smoke 是可选旁证，默认不跑，避免让慢构造器拖住容量下界审计。若显式启用，它也不能推翻上面的容量下界结论。

| category | instance | status | route_count | error |
|---|---|---|---:|---|
|  |  | SKIPPED |  | constructor smoke disabled by default; capacity lower-bound audit does not need ALNS or warm-start search |

## 输出文件

- `baselines/e2_alns/hard_cap_feasibility_audit_data/metadata.json`
- `baselines/e2_alns/hard_cap_feasibility_audit_data/capacity_bound_audit.csv`
- `baselines/e2_alns/hard_cap_feasibility_audit_data/source_consistency.csv`
- `baselines/e2_alns/hard_cap_feasibility_audit_data/capacity_summary.csv`
- `baselines/e2_alns/hard_cap_feasibility_audit_data/constructor_smoke.csv`
- `baselines/e2_alns/hard_cap_feasibility_audit_data/decision_options.md`
- `baselines/e2_alns/hard_cap_feasibility_audit_data/conclusion.json`

## 决策边界

本报告不决定改 `Q`、不决定重标车辆数、不决定引入多车次。它只说明：当前 `Q=1600kg + Goeke车辆硬上限 + route=vehicle` 这组三件事不能同时支撑 E2 正式实验。
