# Track A Fair Baselines Report

Verdict: HALT_BASELINE_NOT_RUNNING
Reason: PSO failed baseline health on E-UK25_02__curric_d2_s3_seed2_24h/seed901: UNHEALTHY_WARM_HASH 
Strong vs plain mean gain: -3.693022031020216
Strong vs weakest weak-baseline mean gain: 5.1408850728145286
Rows: 4

Baseline repair audit: GA now passes the health gate after reseeding/diversification. PSO still fails after three repair attempts: particle ALNS polish, local-search bootstrap, and pbest/gbest path relinking. The final PSO probe reached 16000/16000 but returned the warm-start hash and cost, so the comparison stops at HALT_BASELINE_NOT_RUNNING.
