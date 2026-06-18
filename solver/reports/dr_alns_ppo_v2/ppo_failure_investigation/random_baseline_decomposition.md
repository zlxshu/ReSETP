# Random Baseline Decomposition

`random_full` is not a weak random solution generator. It samples actions inside the restored winner-kernel operator space.

## Cost Summary

| family | split | rows | mean | median | best | top action share |
|---|---|---:|---:|---:|---:|---:|
| random_full | eval_10001 | 10 | 4781.121851 | 4788.890407 | 4739.860025 | 0.017319 |
| random_full | eval_held_out | 10 | 3538.481527 | 3543.015348 | 3454.642943 | 0.017319 |
| random_full | eval_train | 9 | 5365.972939 | 5412.281684 | 3528.765009 | 0.057417 |
| alpha_ucb_env | eval_10001 | 10 | 4878.331796 | 4848.619848 | 4779.053444 | 0.315800 |
| alpha_ucb_env | eval_held_out | 10 | 3902.509680 | 3951.963415 | 3471.164732 | 0.298431 |
| alpha_ucb_env | eval_train | 9 | 5680.789650 | 5758.276002 | 3573.719578 | 0.445437 |

## Operator Distribution Delta

```json
{
  "random_destroy_top": [
    [
      "shaw_related_removal",
      77686
    ],
    [
      "random_customer_removal",
      77674
    ],
    [
      "vehicle_type_swap",
      77458
    ],
    [
      "whole_route_removal",
      77401
    ],
    [
      "worst_customer_removal",
      76924
    ],
    [
      "route_segment_removal",
      76857
    ]
  ],
  "alpha_destroy_top": [
    [
      "route_segment_removal",
      345520
    ],
    [
      "vehicle_type_swap",
      64600
    ],
    [
      "whole_route_removal",
      21107
    ],
    [
      "random_customer_removal",
      20578
    ],
    [
      "shaw_related_removal",
      9611
    ],
    [
      "worst_customer_removal",
      2584
    ]
  ],
  "random_repair_top": [
    [
      "regret3_insert_repair",
      155386
    ],
    [
      "regret2_insert_repair",
      154631
    ],
    [
      "greedy_insert_repair",
      153983
    ]
  ],
  "alpha_repair_top": [
    [
      "greedy_insert_repair",
      244247
    ],
    [
      "regret3_insert_repair",
      110076
    ],
    [
      "regret2_insert_repair",
      109677
    ]
  ]
}
```
