# C1-R1a/R3 Decoder Fix Validation

本步目标：让基线的两条死通道恢复生命体征：(a) 修复解码器“绝对距离比较”bug，让排列→解码路径能产出多客户路线；(b) 查清 `_apply_strong_alns_destroy_repair` 桥在 5174 平台解上失效的微观死因。

Evidence level: **PROBE / 非正式 T3**. 这是 baseline 健康整改探针，不是正式 T3，不得写成算法胜负。

拍板边界：不改建模，只修 baseline decoder 实现偏差；固定费仍按现有 `£/班次 / 每趟派遣` 口径使用，不改成每实体车固定费，不引入 fleet-size-and-mix。

Verdict: `DECODER_FIXED_AND_BRIDGE_CAUSE_LOCATED`

## Plain Reading

解码器已恢复多客户路线候选；桥尸检已完成。本结论只说明 baseline health probe，不是算法胜负。

## Gates

- Model intent audit: `True`
- Phase0 env: `True` (`/opt/anaconda3/bin/python3.13` / `2.3.5`)
- Decoder micro check: `True`
- Decoder decision: `DECODER_FIXED`
- Bridge decision: `BRIDGE_CAUSE_LOCATED`
- Collection failures: `0`
- HEAD: `ee1f7bfb1ac8466322f671d453e20359335e2e63`
- Battery override only in memory: `dataclasses.replace(DEFAULT_PRICES, B_battery_kwh=280.0, carbon_price=0.05034)`.

## Model Intent Audit

| check | pass |
|---|---:|
| cost_has_route_fixed_cost | True |
| cost_has_km_cost | True |
| prices_fixed_cost_per_shift | True |
| prices_has_c_km | True |
| tex_objective_fixed_and_km | True |
| tex_fixed_cost_dispatch_text | True |

## Decoder Summary

| algorithm | status | evals | decode rows | route count min/p50/max | decoded cost min/p50 | decode <5174 | best cost |
|---|---|---:|---:|---|---|---:|---:|
| GA | OK | 2000 | 1095 | 21/26/32 | 5202.303/5713.807 | 0 | 4949.657813072418 |
| PSO | OK | 2000 | 1401 | 21/24/33 | 5158.943/8077.316 | 1 | 4652.871567923312 |

修复前 C1-R2 基线摘要：

```json
{
  "available": true,
  "by_algorithm": {
    "GA": {
      "cost_min": 20997.633223472087,
      "cost_p50": 21009.041568215667,
      "route_count_max": 150,
      "route_count_min": 150,
      "route_count_p50": 150.0,
      "rows": 1094,
      "unique_route_counts": [
        150
      ]
    },
    "PSO": {
      "cost_min": 20993.53221428402,
      "cost_p50": 21022.442187034758,
      "route_count_max": 150,
      "route_count_min": 150,
      "route_count_p50": 150.0,
      "rows": 1432,
      "unique_route_counts": [
        150
      ]
    }
  },
  "path": "baselines/e2_alns/native_channel_autopsy_data/decode_events.csv",
  "rows": 5214
}
```

## Bridge Autopsy

| destroy | repair | trials | feasible | changed | dominant bucket | rate |
|---|---|---:|---:|---:|---|---:|
| random_customer_removal | greedy_insert_repair | 14 | 0 | 0 | REPAIR_NONE | 1.0000 |
| random_customer_removal | regret2_insert_repair | 14 | 0 | 0 | REPAIR_NONE | 1.0000 |
| random_customer_removal | regret3_insert_repair | 14 | 0 | 0 | REPAIR_NONE | 1.0000 |
| route_segment_removal | greedy_insert_repair | 13 | 0 | 0 | REPAIR_NONE | 1.0000 |
| route_segment_removal | regret2_insert_repair | 13 | 0 | 0 | REPAIR_NONE | 1.0000 |
| route_segment_removal | regret3_insert_repair | 13 | 0 | 0 | REPAIR_NONE | 1.0000 |
| shaw_related_removal | greedy_insert_repair | 14 | 0 | 0 | REPAIR_NONE | 1.0000 |
| shaw_related_removal | regret2_insert_repair | 14 | 0 | 0 | REPAIR_NONE | 1.0000 |
| shaw_related_removal | regret3_insert_repair | 13 | 0 | 0 | REPAIR_NONE | 1.0000 |
| whole_route_removal | greedy_insert_repair | 13 | 0 | 0 | REPAIR_NONE | 1.0000 |
| whole_route_removal | regret2_insert_repair | 13 | 0 | 0 | REPAIR_NONE | 1.0000 |
| whole_route_removal | regret3_insert_repair | 13 | 0 | 0 | REPAIR_NONE | 1.0000 |
| worst_customer_removal | greedy_insert_repair | 13 | 0 | 0 | REPAIR_NONE | 1.0000 |
| worst_customer_removal | regret2_insert_repair | 13 | 0 | 0 | REPAIR_NONE | 1.0000 |
| worst_customer_removal | regret3_insert_repair | 13 | 0 | 0 | REPAIR_NONE | 1.0000 |

## Artifacts

- Data dir: `baselines/e2_alns/decoder_fix_validation_data`
- Candidate rows: `baselines/e2_alns/decoder_fix_validation_data/raw_runs.csv`
- Decode rows: `baselines/e2_alns/decoder_fix_validation_data/decode_events.csv`
- Bridge rows: `baselines/e2_alns/decoder_fix_validation_data/bridge_autopsy.csv`
- Bridge summary: `baselines/e2_alns/decoder_fix_validation_data/bridge_summary.csv`
- Decision: `baselines/e2_alns/decoder_fix_validation_data/decision.json`
