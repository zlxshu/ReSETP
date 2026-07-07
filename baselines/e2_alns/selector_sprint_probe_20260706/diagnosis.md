# Selector Sprint Diagnosis

Verdict: `SELECTOR_SPRINT_8000_SUPPORTED`.

This is diagnostic-only selector scheduling evidence, not formal T3.

Gate rows:
- budget=4000 profile=A4_BALANCED_SELECTOR_LOCAL_SEARCH pass=True gap=0.00048527397136235187 wins/losses=23/18
- budget=4000 profile=A5_EPS_DECAY_SELECTOR_LOCAL_SEARCH pass=True gap=0.0030773050937767557 wins/losses=22/16
- budget=4000 profile=A6_THOMPSON_SELECTOR_LOCAL_SEARCH pass=True gap=0.0011433358929469968 wins/losses=24/18
- budget=4000 profile=A7_SOFTMAX_SELECTOR_LOCAL_SEARCH pass=True gap=0.0038323386258464383 wins/losses=23/16
- budget=8000 profile=A4_BALANCED_SELECTOR_LOCAL_SEARCH pass=False gap=-0.005220086718924731 wins/losses=24/15
- budget=8000 profile=A5_EPS_DECAY_SELECTOR_LOCAL_SEARCH pass=False gap=-0.00271671140701799 wins/losses=27/12
- budget=8000 profile=A6_THOMPSON_SELECTOR_LOCAL_SEARCH pass=True gap=-0.001683652696976347 wins/losses=29/12
- budget=8000 profile=A7_SOFTMAX_SELECTOR_LOCAL_SEARCH pass=True gap=-0.0010006201218705217 wins/losses=26/13
- budget=16000 profile=A6_THOMPSON_SELECTOR_LOCAL_SEARCH pass=False gap=-0.006035769122260031 wins/losses=29/12
- budget=16000 profile=A7_SOFTMAX_SELECTOR_LOCAL_SEARCH pass=False gap=-0.0026802757975461834 wins/losses=28/12
