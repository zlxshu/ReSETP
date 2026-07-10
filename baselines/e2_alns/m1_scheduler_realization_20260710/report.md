# M1 scheduler realization diagnostic

Verdict: `DEFAULT_SELECTOR_STARVATION_CONFIRMED`.
Minimum-coverage gate: `MINIMUM_COVERAGE_400_SUPPORTED`.

The one-step probe already showed that ALNS can make useful route and vehicle-type changes. This experiment asks whether the unchanged full loop actually gives those moves a chance. It is diagnostic only and makes no ALNS-versus-SA win claim.

Instance: `L-main-threeshift-25c-01`; actual customers: `55`; battery: `280.0` kWh; budget: `400` evaluations; seeds: `[1, 2, 3, 4, 5]`.

## Matched runs

- CV_ONLY / seed 1 / DEFAULT_ALPHA_UCB: best 1190.297444, routes 8, EV routes 8, selected pairs 16, dominant share 0.900, vehicle-type attempts 25.
- CV_ONLY / seed 1 / BALANCED_COVERAGE: best 1318.804366, routes 8, EV routes 6, selected pairs 18, dominant share 0.249, vehicle-type attempts 51.
- CV_ONLY / seed 1 / MINIMUM_COVERAGE: best 1262.192698, routes 8, EV routes 7, selected pairs 16, dominant share 0.355, vehicle-type attempts 138.
- CV_ONLY / seed 2 / DEFAULT_ALPHA_UCB: best 1334.822454, routes 8, EV routes 1, selected pairs 4, dominant share 0.990, vehicle-type attempts 0.
- CV_ONLY / seed 2 / BALANCED_COVERAGE: best 1124.847095, routes 7, EV routes 7, selected pairs 18, dominant share 0.193, vehicle-type attempts 86.
- CV_ONLY / seed 2 / MINIMUM_COVERAGE: best 1291.403478, routes 8, EV routes 8, selected pairs 16, dominant share 0.550, vehicle-type attempts 213.
- CV_ONLY / seed 3 / DEFAULT_ALPHA_UCB: best 1272.161463, routes 7, EV routes 1, selected pairs 3, dominant share 0.995, vehicle-type attempts 0.
- CV_ONLY / seed 3 / BALANCED_COVERAGE: best 1245.292004, routes 7, EV routes 5, selected pairs 18, dominant share 0.194, vehicle-type attempts 58.
- CV_ONLY / seed 3 / MINIMUM_COVERAGE: best 1305.068397, routes 8, EV routes 7, selected pairs 16, dominant share 0.419, vehicle-type attempts 163.
- CV_ONLY / seed 4 / DEFAULT_ALPHA_UCB: best 1115.831769, routes 7, EV routes 7, selected pairs 16, dominant share 0.843, vehicle-type attempts 33.
- CV_ONLY / seed 4 / BALANCED_COVERAGE: best 1274.232757, routes 8, EV routes 6, selected pairs 18, dominant share 0.168, vehicle-type attempts 81.
- CV_ONLY / seed 4 / MINIMUM_COVERAGE: best 1264.650630, routes 8, EV routes 8, selected pairs 16, dominant share 0.544, vehicle-type attempts 210.
- CV_ONLY / seed 5 / DEFAULT_ALPHA_UCB: best 1377.771678, routes 8, EV routes 1, selected pairs 3, dominant share 0.992, vehicle-type attempts 0.
- CV_ONLY / seed 5 / BALANCED_COVERAGE: best 1173.253500, routes 7, EV routes 6, selected pairs 18, dominant share 0.148, vehicle-type attempts 77.
- CV_ONLY / seed 5 / MINIMUM_COVERAGE: best 1172.722881, routes 8, EV routes 8, selected pairs 16, dominant share 0.341, vehicle-type attempts 132.
- SHARED_ONE_EV / seed 1 / DEFAULT_ALPHA_UCB: best 1373.464858, routes 8, EV routes 1, selected pairs 1, dominant share 1.000, vehicle-type attempts 0.
- SHARED_ONE_EV / seed 1 / BALANCED_COVERAGE: best 1187.242559, routes 8, EV routes 8, selected pairs 18, dominant share 0.246, vehicle-type attempts 74.
- SHARED_ONE_EV / seed 1 / MINIMUM_COVERAGE: best 1316.444113, routes 8, EV routes 7, selected pairs 16, dominant share 0.313, vehicle-type attempts 121.
- SHARED_ONE_EV / seed 2 / DEFAULT_ALPHA_UCB: best 1358.241961, routes 8, EV routes 1, selected pairs 1, dominant share 1.000, vehicle-type attempts 0.
- SHARED_ONE_EV / seed 2 / BALANCED_COVERAGE: best 1133.711352, routes 7, EV routes 7, selected pairs 18, dominant share 0.170, vehicle-type attempts 74.
- SHARED_ONE_EV / seed 2 / MINIMUM_COVERAGE: best 1216.414238, routes 8, EV routes 8, selected pairs 16, dominant share 0.292, vehicle-type attempts 110.
- SHARED_ONE_EV / seed 3 / DEFAULT_ALPHA_UCB: best 1345.216091, routes 8, EV routes 1, selected pairs 1, dominant share 1.000, vehicle-type attempts 0.
- SHARED_ONE_EV / seed 3 / BALANCED_COVERAGE: best 1148.997206, routes 7, EV routes 6, selected pairs 18, dominant share 0.190, vehicle-type attempts 61.
- SHARED_ONE_EV / seed 3 / MINIMUM_COVERAGE: best 1259.743983, routes 8, EV routes 8, selected pairs 16, dominant share 0.612, vehicle-type attempts 237.
- SHARED_ONE_EV / seed 4 / DEFAULT_ALPHA_UCB: best 1343.039542, routes 8, EV routes 1, selected pairs 2, dominant share 0.997, vehicle-type attempts 0.
- SHARED_ONE_EV / seed 4 / BALANCED_COVERAGE: best 1189.970729, routes 7, EV routes 6, selected pairs 18, dominant share 0.206, vehicle-type attempts 71.
- SHARED_ONE_EV / seed 4 / MINIMUM_COVERAGE: best 1241.538697, routes 8, EV routes 7, selected pairs 16, dominant share 0.409, vehicle-type attempts 158.
- SHARED_ONE_EV / seed 5 / DEFAULT_ALPHA_UCB: best 1347.249652, routes 7, EV routes 1, selected pairs 7, dominant share 0.985, vehicle-type attempts 0.
- SHARED_ONE_EV / seed 5 / BALANCED_COVERAGE: best 1212.922893, routes 8, EV routes 8, selected pairs 18, dominant share 0.160, vehicle-type attempts 80.
- SHARED_ONE_EV / seed 5 / MINIMUM_COVERAGE: best 1534.363480, routes 8, EV routes 5, selected pairs 16, dominant share 0.775, vehicle-type attempts 300.

## Boundary

A coverage improvement at this short budget proves that early pair starvation can cause a missed result. The minimum-coverage branch passes only if it covers vehicle-type moves in every matched run, wins at least 60% of pairs, and lowers mean cost. Even a 400-evaluation pass does not prove long-budget or cross-instance superiority.
