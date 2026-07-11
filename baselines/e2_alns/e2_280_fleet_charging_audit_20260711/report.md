# Frozen E2 280 kWh fleet and charging audit

Verdict: `E2_280_EV_HEAVY_CHARGING_ACTIVITY_AUDITED`. No new search was run.

All 45 official aware/naive pairs retain the same route structure, electricity demand and charging-action multiset, and both sides remain feasible: True.
After excluding the structural 15c no-EV instance, aggregate EV shares by customers/demand/distance are 86.082%/87.031%/81.544%.
The corresponding CV shares are 13.918%/12.969%/18.456%; EVs account for 64.615% of summed physical-vehicle use.
The eligible rows contain 29 mixed runs, 11 all-EV runs and 0 all-CV runs.
They contain 929 charging actions and 88711.268 kWh of charging. Carbon-aware timing actually shifts 911 actions and 86737.553 kWh (97.775% of charging energy).
Against the same-route naive timing rows, charging-weighted carbon intensity falls from 137.979 to 123.605 gCO2/kWh and total EV indirect carbon falls by 1275.090 kg; positive/negative pairs are 40/0.
All formal charging is depot charging: public-station actions/energy are 0/0.000 kWh. Therefore the frozen result proves depot charging-time shifting, not public-station selection.

This audit supports or limits the 280 kWh paper story using frozen evidence only. It does not decide the cross-depot fee, fairness contract, a new battery capacity, or the formal refined-carbon gate.
