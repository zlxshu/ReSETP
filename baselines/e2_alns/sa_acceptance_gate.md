# E2 ALNS SA Acceptance Gate

Gate: `HALT_INFEASIBLE`

Reason: At least one gate row is infeasible or missing a finite solution.

Commit: `8ae7727ee6fd2b6d68b75a631e0476107e60cb32`; Python: `/opt/anaconda3/bin/python3.13`; NumPy: `2.3.5`.

Seeds: [1, 2, 3, 4, 5]; eval budget is a diagnostic backstop `16000`.

| instance | algorithm | n | mean | best | std | mean seconds | mean evals | routes | CV | EV | zero violations |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| e2-multidepot-100c-01 | LNS | 5 | 4985.382229 | 4958.980084 | 20.326324 | 300.015 | 10279.6 | 32.00 | 32.00 | 0.00 | 5 |
| e2-multidepot-100c-01 | alns_sa_autofit | 5 | 5357.841254 | 5287.057473 | 44.049395 | 301.818 | 1136.4 | 35.20 | 24.40 | 10.80 | 5 |
| e2-multidepot-100c-01 | alns_sa_lns_cooling | 5 | 4943.685833 | 4833.051015 | 84.906545 | 301.549 | 3568.6 | 34.00 | 10.40 | 23.60 | 5 |
| e2-multidepot-200c-01 | LNS | 5 | inf | inf | inf | 915.006 | 0.0 | 0.00 | 0.00 | 0.00 | 0 |
| e2-multidepot-200c-01 | alns_sa_autofit | 5 | inf | inf | inf | 915.018 | 0.0 | 0.00 | 0.00 | 0.00 | 0 |
| e2-multidepot-200c-01 | alns_sa_lns_cooling | 5 | inf | inf | inf | 915.012 | 0.0 | 0.00 | 0.00 | 0.00 | 0 |
| e2-threeshift-100c-01 | LNS | 5 | 4944.487761 | 4918.752360 | 16.379543 | 300.015 | 10014.2 | 29.40 | 29.40 | 0.00 | 5 |
| e2-threeshift-100c-01 | alns_sa_autofit | 5 | 5250.266550 | 5170.838666 | 70.527112 | 301.849 | 1157.2 | 32.60 | 25.60 | 7.00 | 5 |
| e2-threeshift-100c-01 | alns_sa_lns_cooling | 5 | 5017.082864 | 4874.971895 | 125.615763 | 301.503 | 3283.8 | 32.80 | 10.60 | 22.20 | 5 |
| e2-threeshift-150c-01 | LNS | 5 | 7451.731179 | 7439.741687 | 10.088957 | 887.858 | 15984.0 | 48.00 | 48.00 | 0.00 | 5 |
| e2-threeshift-150c-01 | alns_sa_autofit | 5 | 8176.700150 | 8127.154904 | 40.393670 | 902.306 | 1338.8 | 54.40 | 43.00 | 11.40 | 5 |
| e2-threeshift-150c-01 | alns_sa_lns_cooling | 5 | 7556.930429 | 7266.048944 | 170.639941 | 829.915 | 9382.0 | 52.60 | 14.20 | 38.40 | 5 |
| e2-threeshift-200c-01 | LNS | 5 | 8989.413172 | 8967.188137 | 20.858834 | 900.056 | 10018.8 | 62.20 | 62.20 | 0.00 | 5 |
| e2-threeshift-200c-01 | alns_sa_autofit | 5 | inf | 10073.969917 | inf | 912.607 | 106.8 | 14.60 | 11.00 | 3.60 | 1 |
| e2-threeshift-200c-01 | alns_sa_lns_cooling | 5 | inf | 9263.728516 | inf | 890.889 | 4422.2 | 57.60 | 9.80 | 47.80 | 4 |
| e2-threeshift-50c-01 | LNS | 5 | 2358.247888 | 2351.347164 | 5.146171 | 183.587 | 16000.0 | 15.00 | 15.00 | 0.00 | 5 |
| e2-threeshift-50c-01 | alns_sa_autofit | 5 | 2378.095811 | 2354.062507 | 25.674950 | 301.615 | 6368.6 | 17.00 | 5.40 | 11.60 | 5 |
| e2-threeshift-50c-01 | alns_sa_lns_cooling | 5 | 2367.024640 | 2356.597950 | 12.621629 | 152.963 | 16000.0 | 17.00 | 4.60 | 12.40 | 5 |
| e2-threeshift-75c-01 | LNS | 5 | 3605.423331 | 3571.071970 | 27.277848 | 300.008 | 15589.2 | 23.60 | 23.60 | 0.00 | 5 |
| e2-threeshift-75c-01 | alns_sa_autofit | 5 | 3686.590654 | 3605.152707 | 57.862554 | 301.660 | 2398.2 | 25.60 | 13.40 | 12.20 | 5 |
| e2-threeshift-75c-01 | alns_sa_lns_cooling | 5 | 3554.463503 | 3456.739668 | 64.784187 | 263.303 | 13659.4 | 25.60 | 5.40 | 20.20 | 5 |
| e2-vanilla-100c-01 | LNS | 5 | 5683.149631 | 5657.585256 | 16.581737 | 300.023 | 9779.4 | 31.00 | 31.00 | 0.00 | 5 |
| e2-vanilla-100c-01 | alns_sa_autofit | 5 | 6174.289976 | 6061.282700 | 99.706361 | 301.973 | 1200.6 | 34.40 | 28.00 | 6.40 | 5 |
| e2-vanilla-100c-01 | alns_sa_lns_cooling | 5 | 5777.111002 | 5708.176712 | 65.145084 | 301.848 | 1618.8 | 33.20 | 19.40 | 13.80 | 5 |
| e2-vanilla-200c-01 | LNS | 5 | inf | inf | inf | 915.005 | 0.0 | 0.00 | 0.00 | 0.00 | 0 |
| e2-vanilla-200c-01 | alns_sa_autofit | 5 | inf | inf | inf | 915.017 | 0.0 | 0.00 | 0.00 | 0.00 | 0 |
| e2-vanilla-200c-01 | alns_sa_lns_cooling | 5 | inf | inf | inf | 915.014 | 0.0 | 0.00 | 0.00 | 0.00 | 0 |

## Candidate Metrics
