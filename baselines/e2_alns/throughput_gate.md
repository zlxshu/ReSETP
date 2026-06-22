# E2 ALNS Throughput Gate

Gate: `HALT_TRUE_GLNS_BETTER_AFTER_THROUGHPUT`

Commit: `c769600e1e746ae20c0e6136ddcf9876ba62f641`; elapsed seconds: `12932.727`.

Group gaps: `{"e2-threeshift-100c-01": 1.3287474923988718, "e2-threeshift-150c-01": 1.3856577139973836, "e2-threeshift-200c-01": 3.448226570085188, "e2-threeshift-50c-01": 0.37217257522090186, "e2-threeshift-75c-01": -1.4134214911164933}`
Throughput ratios: `{"e2-threeshift-100c-01": 3.7837146367173125, "e2-threeshift-150c-01": 3.4982931195692175, "e2-threeshift-200c-01": 3.8881741660619613, "e2-threeshift-50c-01": 4.027963138192951, "e2-threeshift-75c-01": 3.6645266612348926}`

| instance | algorithm | n | finite | mean | best | std | mean eval/s | zero violations | statuses |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| e2-multidepot-100c-01 | LNS | 5 | 5 | 4986.411408 | 4958.980084 | 20.917103 | 31.971 | 5 | `{"HALT_RUNTIME_UNDER_EVAL": 5}` |
| e2-multidepot-100c-01 | alns_e2_throughput | 5 | 5 | 4942.986628 | 4830.887108 | 85.574831 | 116.085 | 5 | `{"OK": 5}` |
| e2-multidepot-200c-01 | LNS | 5 | 5 | 9460.707293 | 9388.241204 | 56.192029 | 7.595 | 5 | `{"HALT_HARD_TIMEOUT_WITH_INCUMBENT": 5}` |
| e2-multidepot-200c-01 | alns_e2_throughput | 5 | 5 | 9551.356152 | 9404.998766 | 99.157069 | 39.579 | 5 | `{"OK": 5}` |
| e2-threeshift-100c-01 | LNS | 5 | 5 | 4944.487761 | 4918.752360 | 16.379543 | 30.973 | 5 | `{"HALT_RUNTIME_UNDER_EVAL": 5}` |
| e2-threeshift-100c-01 | alns_e2_throughput | 5 | 5 | 5010.187518 | 4874.971895 | 125.189441 | 117.192 | 5 | `{"OK": 5}` |
| e2-threeshift-150c-01 | LNS | 5 | 5 | 7451.731179 | 7439.741687 | 10.088957 | 17.009 | 5 | `{"HALT_RUNTIME_UNDER_EVAL": 5}` |
| e2-threeshift-150c-01 | alns_e2_throughput | 5 | 5 | 7554.986667 | 7256.330133 | 174.786703 | 59.504 | 5 | `{"OK": 5}` |
| e2-threeshift-200c-01 | LNS | 5 | 5 | 8991.802112 | 8979.132838 | 18.190394 | 10.609 | 5 | `{"HALT_RUNTIME_UNDER_EVAL": 5}` |
| e2-threeshift-200c-01 | alns_e2_throughput | 5 | 5 | 9301.859822 | 9093.841324 | 170.938286 | 41.248 | 5 | `{"OK": 5}` |
| e2-threeshift-50c-01 | LNS | 5 | 5 | 2358.247888 | 2351.347164 | 5.146171 | 75.892 | 5 | `{"OK": 5}` |
| e2-threeshift-50c-01 | alns_e2_throughput | 5 | 5 | 2367.024640 | 2356.597950 | 12.621629 | 305.689 | 5 | `{"OK": 5}` |
| e2-threeshift-75c-01 | LNS | 5 | 5 | 3605.423331 | 3571.071970 | 27.277848 | 46.909 | 5 | `{"HALT_RUNTIME_UNDER_EVAL": 5}` |
| e2-threeshift-75c-01 | alns_e2_throughput | 5 | 5 | 3554.463503 | 3456.739668 | 64.784187 | 171.900 | 5 | `{"OK": 5}` |
| e2-vanilla-100c-01 | LNS | 5 | 5 | 5683.149631 | 5657.585256 | 16.581737 | 30.792 | 5 | `{"HALT_RUNTIME_UNDER_EVAL": 5}` |
| e2-vanilla-100c-01 | alns_e2_throughput | 5 | 5 | 5748.468157 | 5686.448715 | 55.795037 | 90.123 | 5 | `{"OK": 5}` |
| e2-vanilla-200c-01 | LNS | 5 | 5 | 10868.595095 | 10839.920852 | 23.832426 | 7.107 | 5 | `{"HALT_HARD_TIMEOUT_WITH_INCUMBENT": 5}` |
| e2-vanilla-200c-01 | alns_e2_throughput | 5 | 5 | 10869.078795 | 10665.258483 | 138.415484 | 27.454 | 5 | `{"OK": 5}` |
