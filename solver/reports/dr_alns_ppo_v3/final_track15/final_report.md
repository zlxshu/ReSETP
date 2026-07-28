# Final Track15 Report

Final status: HALT_BASELINE_NOT_RUNNING
Final reason: PSO failed baseline health on E-UK25_02__curric_d2_s3_seed2_24h/seed901: UNHEALTHY_WARM_HASH 

## Track A
Verdict: HALT_BASELINE_NOT_RUNNING
Reason: PSO failed baseline health on E-UK25_02__curric_d2_s3_seed2_24h/seed901: UNHEALTHY_WARM_HASH 
Strong beats plain mean gain: -3.693022031020216
Strong beats weak baselines min mean gain: 5.1408850728145286

Baseline repair audit: GA was initially unhealthy, then fixed. Before repair it stopped at 9229/16000 and returned the warm-start hash even with an 1800s probe; after adding GA reseeding/diversification it reached 16000/16000 in 44.8s, improved cost from 749.6212 to 602.1428, changed hash, and had zero violations.

PSO remains unhealthy after three self-repair attempts. Attempt 1 added particle-level ALNS polish; attempt 2 added local-search bootstrap; attempt 3 added pbest/gbest path relinking. The final probe still reached 16000/16000 but returned the exact warm-start hash and cost 749.6212. Therefore PSO is not a valid weak baseline for a win claim, and Track A must halt at HALT_BASELINE_NOT_RUNNING.

## Track B
Verdict: NOT_RUN
Reason: 

## Decision
DR-static remains excluded from claims. Track A is not publishable yet because PSO fails the baseline health gate after three repair attempts. Also, the current strong method does not beat plain ALNS on the first checked seed: 571.1874 vs 550.8446, about -3.69%. Track B was not run after the Track A hard stop, and no dynamic DR win is claimed.
