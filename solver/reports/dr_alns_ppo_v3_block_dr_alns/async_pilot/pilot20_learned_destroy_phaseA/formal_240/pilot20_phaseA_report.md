# Pilot20 Learned-Destroy Phase A

Verdict: `HALT_LEARNED_DESTROY`

Held-out avg vs operator-select: -12.259%
Min scale avg vs operator-select: -19.480967171422062
Held-out avg vs random: -12.886861444071204
Zero violation learned: True
Worker integrity: True (C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe, NumPy 2.3.5)

PASS if held-out avg >= 2%, every scale >= 0%, learned beats random on average, learned has zero violations, and all rows use the py313/NumPy 2.3.5 worker; WEAK if 0-2%; otherwise HALT.

Artifacts: `pilot20_phaseA_rows.csv`, `pilot20_update_log.csv`, `learned_destroy_phaseA_model.pt`.
