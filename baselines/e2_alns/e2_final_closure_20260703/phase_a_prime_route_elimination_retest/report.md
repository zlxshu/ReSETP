# Phase A Prime Route Elimination Retest

Verdict: `ROUTE_RETEST_INCONCLUSIVE`

本报告是 evidence material，不自动写入 TeX，不构成论文胜负表述。

```json
{
  "algorithm_win_loss_claim": false,
  "comparison_rows": [
    {
      "best_seed_gap_fraction": 0.07498145078524265,
      "gap_fraction": -0.011243409124018998,
      "instance": "POOLED_100C_150C",
      "mean_candidate": 3328.0969594389135,
      "mean_lns": 3291.093844875438,
      "pair_count": 6,
      "variant": "LOCAL_SEARCH_ONLY",
      "worst_seed_gap_fraction": -0.0708194957991079
    },
    {
      "best_seed_gap_fraction": 0.040841439176828156,
      "gap_fraction": -0.009939488164084928,
      "instance": "POOLED_100C_150C",
      "mean_candidate": 3323.8056331934704,
      "mean_lns": 3291.093844875438,
      "pair_count": 6,
      "variant": "ROUTE_ELIMINATION_ONLY",
      "worst_seed_gap_fraction": -0.04677516675475149
    },
    {
      "best_seed_gap_fraction": 0.07013697668462368,
      "gap_fraction": -0.01303748173798278,
      "instance": "POOLED_100C_150C",
      "mean_candidate": 3945.955164820597,
      "mean_lns": 3895.1719318922487,
      "pair_count": 3,
      "variant": "LOCAL_SEARCH_ROUTE_ELIMINATION_STACK",
      "worst_seed_gap_fraction": -0.06425981128603864
    },
    {
      "best_seed_gap_fraction": 0.010902180120816047,
      "gap_fraction": -0.021702123576003575,
      "instance": "e2-threeshift-100c-01",
      "mean_candidate": 2745.3297058863445,
      "mean_lns": 2687.0157578586277,
      "pair_count": 3,
      "variant": "LOCAL_SEARCH_ONLY",
      "worst_seed_gap_fraction": -0.05775255161645537
    },
    {
      "best_seed_gap_fraction": 0.0007983662841237529,
      "gap_fraction": -0.014898334975758385,
      "instance": "e2-threeshift-100c-01",
      "mean_candidate": 2727.047818704347,
      "mean_lns": 2687.0157578586277,
      "pair_count": 3,
      "variant": "ROUTE_ELIMINATION_ONLY",
      "worst_seed_gap_fraction": -0.026152979011749535
    },
    {
      "best_seed_gap_fraction": 0.07498145078524265,
      "gap_fraction": -0.004028649151723193,
      "instance": "e2-threeshift-150c-01",
      "mean_candidate": 3910.8642129914824,
      "mean_lns": 3895.1719318922487,
      "pair_count": 3,
      "variant": "LOCAL_SEARCH_ONLY",
      "worst_seed_gap_fraction": -0.0708194957991079
    },
    {
      "best_seed_gap_fraction": 0.040841439176828156,
      "gap_fraction": -0.006518715023192764,
      "instance": "e2-threeshift-150c-01",
      "mean_candidate": 3920.5634476825935,
      "mean_lns": 3895.1719318922487,
      "pair_count": 3,
      "variant": "ROUTE_ELIMINATION_ONLY",
      "worst_seed_gap_fraction": -0.04677516675475149
    },
    {
      "best_seed_gap_fraction": 0.07013697668462368,
      "gap_fraction": -0.01303748173798278,
      "instance": "e2-threeshift-150c-01",
      "mean_candidate": 3945.955164820597,
      "mean_lns": 3895.1719318922487,
      "pair_count": 3,
      "variant": "LOCAL_SEARCH_ROUTE_ELIMINATION_STACK",
      "worst_seed_gap_fraction": -0.06425981128603864
    }
  ],
  "halt_lifted_for_100c01": false,
  "local_search_100c01_gap_fraction": -0.021702123576003575,
  "local_search_pooled_gap_fraction": -0.011243409124018998,
  "route_elimination_100c01_gap_fraction": -0.014898334975758385,
  "route_elimination_100c01_passes_g4_two_percent_limit": true,
  "route_elimination_both_instances_not_worse_than_lns": false,
  "route_elimination_no_seed_worse_than_one_percent_on_100c01": false,
  "route_elimination_pooled_gap_better_than_local_search": true,
  "route_elimination_pooled_gap_fraction": -0.009939488164084928,
  "schema": "setp-e2-final-phase-a-prime-decision.v1",
  "selected_t3_main_profile": null,
  "verdict": "ROUTE_RETEST_INCONCLUSIVE"
}
```
