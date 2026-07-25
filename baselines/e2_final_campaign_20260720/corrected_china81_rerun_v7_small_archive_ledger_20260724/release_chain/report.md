# E2 staged-v7 release chain

Decision: `HALT_E2_STAGED_V7_RELEASE_CHAIN`.

The original nested witness monitor stalled after the sealed replay PASS. Recovery v2 verified and reused that evidence, then continued the frozen downstream stages.

Reason: result_strength verdict mismatch: expected PASS_E2_STAGED_PORTFOLIO_PAPER_STRENGTH, got HOLD_E2_STAGED_PORTFOLIO_NOT_PAPER_STRONG
