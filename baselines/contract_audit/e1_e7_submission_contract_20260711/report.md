# E1-E7 submission contract audit

Verdict: `BLOCK_FORMAL_E4_E7_PENDING_SUBMISSION_CONTRACT_DECISION`.

The frozen E2 280 kWh table remains internally valid: 270/270 saved rows replayed under the current checker, with zero violations and matching free-cross-site costs: True.
However, nearest-depot annotation finds 278 cross-site customers for the hybrid and 758 for LNS across 45 runs. Those services were not charged in the frozen E2 objective.
For the five 200c hybrid rows, theta=1 feasibility after enabling the 95 GBP cross-site fee and using the seed-matched E3 independent baseline holds in 0/5 rows.

Therefore E2 can be reported as a same-contract algorithm comparison, but not yet as the final full-model result. E4-E7 formal search stays blocked until one paper submission contract is frozen.

The detailed rows and the E1-E7 switch matrix are stored beside this report. What-if costs are diagnostics only; they are not legal replacement scores because the algorithms did not optimize under the added fee.
