# Next Action

problem_symptom -> A3 best-improved rate increased but corrected main-profile gap worsened
evidence -> see selector_entropy_by_profile.csv, selector_value_bound.md, and decision.json
minimal_remedy -> implement SETP_ALNS_CRUSH_BALANCED_SELECTOR=1 as a diagnostic-only scheduler probe
pass_gate -> A4 improves mean gap vs LNS, wins_vs_A0>=losses_vs_A0, entropy improves, top shares fall, and no HALT rows appear
fail_gate -> A4 fails any direction gate; stop scheduler tuning and audit q-size or acceptance

Boundary: no Tier1/Tier2/Tier3, no LNS weakening, no STRONG_BRIDGE_BACKEND tuning, no RELAXED_ROUTE_COMPRESSION tuning.