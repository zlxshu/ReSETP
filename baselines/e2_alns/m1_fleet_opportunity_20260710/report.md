# M1 fixed-route fleet opportunity map

Target verdict: `FIXED_ROUTES_ROUTING_DEPENDENT` at `280.0` kWh.

Every CV/EV assignment was enumerated while keeping each saved depot/customer order fixed. EV routes used the existing charging repair; every complete solution used the unchanged checker and evaluator.

- 80.0 kWh / BALANCED_COVERAGE / CV_ONLY / seed 2: best 1297.229570554624, EV routes 2/7, MIXED, best mixed gap 0.0%.
- 280.0 kWh / BALANCED_COVERAGE / CV_ONLY / seed 2: best 1124.8470945585916, EV routes 7/7, ALL_EV, best mixed gap 1.6265646497617605%.
- 80.0 kWh / BALANCED_COVERAGE / SHARED_ONE_EV / seed 2: best 1330.0282331609194, EV routes 1/7, MIXED, best mixed gap 0.0%.
- 280.0 kWh / BALANCED_COVERAGE / SHARED_ONE_EV / seed 2: best 1133.7113523331486, EV routes 7/7, ALL_EV, best mixed gap 1.6379195437892218%.
- 80.0 kWh / DEFAULT_ALPHA_UCB / CV_ONLY / seed 4: best 1274.15636901853, EV routes 3/7, MIXED, best mixed gap 0.0%.
- 280.0 kWh / DEFAULT_ALPHA_UCB / CV_ONLY / seed 4: best 1115.8317691417785, EV routes 7/7, ALL_EV, best mixed gap 1.3431660313039933%.
- 80.0 kWh / DEFAULT_ALPHA_UCB / SHARED_ONE_EV / seed 4: best 1326.1448415205703, EV routes 3/8, MIXED, best mixed gap 0.0%.
- 280.0 kWh / DEFAULT_ALPHA_UCB / SHARED_ONE_EV / seed 4: best 1200.2864839270112, EV routes 7/8, MIXED, best mixed gap 0.0%.
- 80.0 kWh / MINIMUM_COVERAGE / CV_ONLY / seed 5: best 1334.0513914242906, EV routes 3/8, MIXED, best mixed gap 0.0%.
- 280.0 kWh / MINIMUM_COVERAGE / CV_ONLY / seed 5: best 1172.7228812008877, EV routes 8/8, ALL_EV, best mixed gap 0.6804825880766768%.
- 80.0 kWh / MINIMUM_COVERAGE / SHARED_ONE_EV / seed 2: best 1366.253760315196, EV routes 4/8, MIXED, best mixed gap 0.0%.
- 280.0 kWh / MINIMUM_COVERAGE / SHARED_ONE_EV / seed 2: best 1216.414238229307, EV routes 8/8, ALL_EV, best mixed gap 1.1050502882003062%.

Boundary: a fixed-route all-EV or all-CV result means a mixed target is absent on that route order. It does not prove that every possible routing has the same composition. Routing-dependent results mean search and fleet composition must be diagnosed together.
