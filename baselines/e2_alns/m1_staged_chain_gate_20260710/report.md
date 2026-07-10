# M1 staged-chain 4000-evaluation gate

This is a diagnostic seed-1 gate, not the formal 10-seed/16000-evaluation benchmark. Both algorithms use the same generated L-main v3 instance, CV start, 280 kWh price configuration, evaluator, checker, and 4000 complete-candidate evaluations.

The staged independent ALNS uses 400 regular evaluations, 3200 strong-repair evaluations, then 400 regular evaluations. Aggregate cost is 34328.746819 versus LNS 36379.445968, a 5.636972% reduction. Aggregate runtime is 517.203761s versus 1869.268814s, a 72.331226% reduction. ALNS wins cost on 7 of 9 instances, ties one, and wins runtime on all 9.

The result does not support a universal 5% per-instance claim. The unweighted mean of instance percentage gains is 3.035910%, and L-main-threeshift-150c-01 loses by 10.185173%. Formal promotion is blocked until a bounded multi-seed gate confirms the aggregate result and the 150c failure is understood.
