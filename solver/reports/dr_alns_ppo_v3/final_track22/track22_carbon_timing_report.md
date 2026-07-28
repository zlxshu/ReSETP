# Track22 Carbon Timing Leverage Probe

Verdict: `NO_CARBON_TIMING_LEVERAGE`
Reason: Default scenario carbon timing leverage <0.5%: -0.003%.

## Evidence

- Gate rows: 3
- Average improvement: -0.003%
- Zero violations: True
- Rule: >=2% passes, 0.5-2% weak, <0.5% no leverage; EV-heavy row is diagnostic only.

## EV-heavy diagnostic

{"bundle": "models/data_bundle/generated_instances/E-UK25_11__curric_d2_s3_seed2211_24h", "scale": "25c", "seed": 2999, "diagnostic_role": "ev_heavy_diagnostic_only", "source": "ev_heavy_initial_solution", "error": "ValueError: HALT_M0: unable to satisfy EV-heavy fleet limits (cv=5/0, ev=0/999)", "improvement_pct": NaN}
