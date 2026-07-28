# Track24 E2-E7 Headroom Matrix

## E2

- Current status: `DR parity stands, old operator/meta is not a breakthrough route.`
- Oracle gate: No direct training gate; E2 alone cannot justify new PPO.
- Hard stop: Do not continue old operator/meta PPO.

## E3

- Current status: `HEADROOM_UNKNOWN`
- Oracle gate: Only train if switch changes cost/fairness/carbon action payoff.
- Hard stop: No measurable mechanism action payoff delta.

## E4/E5

- Current status: `Default weak; scenario knobs may create signal.`
- Oracle gate: carbon share >=8% and timing delta >=2% for REAL.
- Hard stop: All knobs flat or infeasible.

## E6

- Current status: `SIGNAL_AUDIT_REQUIRED`
- Oracle gate: reduced penalty/violations with controlled cost increase.
- Hard stop: BLOCKED_FAIRNESS_BASELINE_NOT_EXPOSED or flat oracle.

## E7

- Current status: `Highest-priority action-space audit.`
- Oracle gate: >=5 pp strong; 2-5 pp weak; <2 pp halt.
- Hard stop: Illegal row, underbudget row, violation, or oracle reduction <2 pp.
