# Metaheuristic Baseline Comparison

One-line conclusion: at least one run is incomparable because it failed the zero-violation or full-evaluation gate; no dominance claim should be made from this report.

Commit: 7de2c847
Environment: /opt/anaconda3/bin/python3.13, numpy 2.3.5
Eval budget/runtime: 16000 / 900.0s

## Verdicts
- 100-01-24h ACO: ALNS碾压; mean=6331.298734, gap_vs_winner=30.682%, wins_alg_lower_than_winner=0/10, p=1, commit=7de2c847.
- 100-01-24h GA: ALNS碾压; mean=6331.298734, gap_vs_winner=30.682%, wins_alg_lower_than_winner=0/10, p=1, commit=7de2c847.
- 100-01-24h GA-VNS: ALNS碾压; mean=5708.831611, gap_vs_winner=17.834%, wins_alg_lower_than_winner=0/10, p=1, commit=7de2c847.
- 100-01-24h GWO: ALNS碾压; mean=6331.298734, gap_vs_winner=30.682%, wins_alg_lower_than_winner=0/10, p=1, commit=7de2c847.
- 100-01-24h IWD: ALNS碾压; mean=6331.298734, gap_vs_winner=30.682%, wins_alg_lower_than_winner=0/10, p=1, commit=7de2c847.
- 100-01-24h LNS: ALNS小幅领先; mean=4912.145216, gap_vs_winner=1.390%, wins_alg_lower_than_winner=3/10, p=0.958008, commit=7de2c847.
- 100-01-24h PSO: ALNS碾压; mean=6331.298734, gap_vs_winner=30.682%, wins_alg_lower_than_winner=0/10, p=1, commit=7de2c847.
- 100-01-24h VNS: ALNS碾压; mean=5713.885924, gap_vs_winner=17.939%, wins_alg_lower_than_winner=0/10, p=1, commit=7de2c847.
- L-main ACO: ALNS碾压; mean=9666.358832, gap_vs_winner=16.033%, wins_alg_lower_than_winner=0/10, p=1, commit=7de2c847.
- L-main GA: ALNS碾压; mean=9666.358832, gap_vs_winner=16.033%, wins_alg_lower_than_winner=0/10, p=1, commit=7de2c847.
- L-main GA-VNS: ALNS碾压; mean=9472.378091, gap_vs_winner=13.705%, wins_alg_lower_than_winner=0/10, p=1, commit=7de2c847.
- L-main GWO: ALNS碾压; mean=9666.358832, gap_vs_winner=16.033%, wins_alg_lower_than_winner=0/10, p=1, commit=7de2c847.
- L-main IWD: ALNS碾压; mean=9666.358832, gap_vs_winner=16.033%, wins_alg_lower_than_winner=0/10, p=1, commit=7de2c847.
- L-main LNS: ALNS失败; mean=7882.629772, gap_vs_winner=-5.378%, wins_alg_lower_than_winner=10/10, p=0.000976562, commit=7de2c847.
- L-main PSO: ALNS碾压; mean=9666.358832, gap_vs_winner=16.033%, wins_alg_lower_than_winner=0/10, p=1, commit=7de2c847.
- L-main VNS: ALNS碾压; mean=9621.649446, gap_vs_winner=15.496%, wins_alg_lower_than_winner=0/10, p=1, commit=7de2c847.

## HALT Rows
- 100-01-24h GA seed1: HALT_RUNTIME_UNDER_EVAL evals=9229/16000 violations=0.
- 100-01-24h GA seed2: HALT_RUNTIME_UNDER_EVAL evals=9229/16000 violations=0.
- 100-01-24h GA seed3: HALT_RUNTIME_UNDER_EVAL evals=9229/16000 violations=0.
- 100-01-24h GA seed4: HALT_RUNTIME_UNDER_EVAL evals=9229/16000 violations=0.
- 100-01-24h GA seed5: HALT_RUNTIME_UNDER_EVAL evals=9229/16000 violations=0.
- 100-01-24h GA seed6: HALT_RUNTIME_UNDER_EVAL evals=9229/16000 violations=0.
- 100-01-24h GA seed7: HALT_RUNTIME_UNDER_EVAL evals=9229/16000 violations=0.
- 100-01-24h GA seed8: HALT_RUNTIME_UNDER_EVAL evals=9229/16000 violations=0.
- 100-01-24h GA seed9: HALT_RUNTIME_UNDER_EVAL evals=9229/16000 violations=0.
- 100-01-24h GA seed10: HALT_RUNTIME_UNDER_EVAL evals=9229/16000 violations=0.
- 100-01-24h GWO seed1: HALT_RUNTIME_UNDER_EVAL evals=11086/16000 violations=0.
- 100-01-24h GWO seed2: HALT_RUNTIME_UNDER_EVAL evals=11792/16000 violations=0.
- 100-01-24h GWO seed3: HALT_RUNTIME_UNDER_EVAL evals=11729/16000 violations=0.
- 100-01-24h GWO seed4: HALT_RUNTIME_UNDER_EVAL evals=11671/16000 violations=0.
- 100-01-24h GWO seed5: HALT_RUNTIME_UNDER_EVAL evals=11179/16000 violations=0.
- 100-01-24h GWO seed6: HALT_RUNTIME_UNDER_EVAL evals=11431/16000 violations=0.
- 100-01-24h GWO seed7: HALT_RUNTIME_UNDER_EVAL evals=11850/16000 violations=0.
- 100-01-24h GWO seed8: HALT_RUNTIME_UNDER_EVAL evals=11859/16000 violations=0.
- 100-01-24h GWO seed9: HALT_RUNTIME_UNDER_EVAL evals=11841/16000 violations=0.
- 100-01-24h GWO seed10: HALT_RUNTIME_UNDER_EVAL evals=11811/16000 violations=0.
- L-main GA seed1: HALT_RUNTIME_UNDER_EVAL evals=9229/16000 violations=0.
- L-main GA seed2: HALT_RUNTIME_UNDER_EVAL evals=9229/16000 violations=0.
- L-main GA seed3: HALT_RUNTIME_UNDER_EVAL evals=9229/16000 violations=0.
- L-main GA seed4: HALT_RUNTIME_UNDER_EVAL evals=9229/16000 violations=0.
- L-main GA seed5: HALT_RUNTIME_UNDER_EVAL evals=9229/16000 violations=0.
- L-main GA seed6: HALT_RUNTIME_UNDER_EVAL evals=9229/16000 violations=0.
- L-main GA seed7: HALT_RUNTIME_UNDER_EVAL evals=9229/16000 violations=0.
- L-main GA seed8: HALT_RUNTIME_UNDER_EVAL evals=9229/16000 violations=0.
- L-main GA seed9: HALT_RUNTIME_UNDER_EVAL evals=9229/16000 violations=0.
- L-main GA seed10: HALT_RUNTIME_UNDER_EVAL evals=9229/16000 violations=0.
- L-main GA-VNS seed1: HALT_RUNTIME_UNDER_EVAL evals=7804/16000 violations=0.
- L-main GA-VNS seed2: HALT_RUNTIME_UNDER_EVAL evals=7788/16000 violations=0.
- L-main GA-VNS seed3: HALT_RUNTIME_UNDER_EVAL evals=8007/16000 violations=0.
- L-main GA-VNS seed4: HALT_RUNTIME_UNDER_EVAL evals=7913/16000 violations=0.
- L-main GA-VNS seed5: HALT_RUNTIME_UNDER_EVAL evals=7777/16000 violations=0.
- L-main GA-VNS seed6: HALT_RUNTIME_UNDER_EVAL evals=7815/16000 violations=0.
- L-main GA-VNS seed7: HALT_RUNTIME_UNDER_EVAL evals=7726/16000 violations=0.
- L-main GA-VNS seed8: HALT_RUNTIME_UNDER_EVAL evals=7977/16000 violations=0.
- L-main GA-VNS seed9: HALT_RUNTIME_UNDER_EVAL evals=7900/16000 violations=0.
- L-main GA-VNS seed10: HALT_RUNTIME_UNDER_EVAL evals=7778/16000 violations=0.

## Method
All complete candidates are scored by evaluate/check through EvalBudget; model_cost is used only for final unpenalized reporting. Runs with violations or under-target evaluations are marked HALT and are not evidence for wins.
