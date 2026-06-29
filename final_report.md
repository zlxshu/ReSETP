# Final Track15 Report

Final status: HALT_BASELINE_NOT_RUNNING
Final reason: GA failed baseline health on E-UK25_02__curric_d2_s3_seed2_24h/seed901: UNHEALTHY_UNDER_EVAL Stopped at 9229/16000 complete evaluations.

## Track A
Verdict: HALT_BASELINE_NOT_RUNNING
Reason: GA failed baseline health on E-UK25_02__curric_d2_s3_seed2_24h/seed901: UNHEALTHY_UNDER_EVAL Stopped at 9229/16000 complete evaluations.
Strong beats plain mean gain: -3.693022031020216
Strong beats weak baselines min mean gain: 23.803196355187666

Baseline health audit: the apparent +23.8% against GA is not claimable. GA consumed only 9229/16000 required evaluations in the formal 900s run and returned the exact warm-start hash. A self-repair probe reran the same GA case with 1800s, but it still stopped at 9229/16000 and still returned the warm-start hash. This confirms the weak-field comparison is blocked by an unhealthy baseline, not by a publishable strong-method margin.

## Track B
Verdict: NOT_RUN
Reason: 

## Decision
DR-static remains excluded from claims. Track A is not publishable yet because the first weak baseline failed the health gate; do not cite the GA margin. Track B was not run after the Track A hard stop, and no dynamic DR win is claimed.
