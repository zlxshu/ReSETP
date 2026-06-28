# Pilot20 Learned-Destroy Phase A

Verdict: `HALT_LEARNED_DESTROY`

Held-out avg vs operator-select: -22.429%
Min scale avg vs operator-select: -30.612770606223147
Held-out avg vs random: -23.103790514567475
Zero violation learned: True
Worker integrity: True (C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe, NumPy 2.3.5)

PASS if held-out avg >= 2%, every scale >= 0%, learned beats random on average, learned has zero violations, and all rows use the py313/NumPy 2.3.5 worker; WEAK if 0-2%; otherwise HALT.

Artifacts: `pilot20_phaseA_rows.csv`, `pilot20_update_log.csv`, `learned_destroy_phaseA_model.pt`.
