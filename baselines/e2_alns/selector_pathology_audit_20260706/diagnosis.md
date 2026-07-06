# Selector Pathology Audit Diagnosis

Verdict: `SELECTOR_PATHOLOGY_SUPPORTED`.

This is diagnostic only, not formal T3 and not an algorithm win/loss claim.

Entropy summary:
- A0_MAIN_LOCAL_SEARCH: normalized_entropy=0.5479450509066646, top1=0.5102399430998055, top2=0.7646329728259733, best_top3=0.8607011070110702
- A3_BACKEND_LOCAL_SEARCH: normalized_entropy=0.6103431771914223, top1=0.4624746980767923, top2=0.6931550125267403, best_top3=0.8432472876917322
- LNS_STRONG_BRIDGE: normalized_entropy=0.9812637638712004, top1=0.14778803564757992, top2=0.289631250333529, best_top3=0.5487256371814093

Support gates:
- entropy_lower_than_lns: True
- top_pair_share_higher_than_lns: True
- a3_best_improved_concentrated: True
- value_bound_exploration_too_small: True

Selector value bound:
- iter 100: untried value=1.6076262349070363, reward8 dominates=True
- iter 1000: untried value=1.7434382168984977, reward8 dominates=True
- iter 4000: untried value=1.8145820822413041, reward8 dominates=True
- iter 16000: untried value=1.8800184770455164, reward8 dominates=True

If supported, the next action is a single-variable balanced-selector diagnostic. If not supported, stop scheduler changes and audit q-size or acceptance.
