# Independent ReSETP ALNS

Paper main algorithm package. Fully isolated from open-source ALNS trees.

```text
resetp_alns/
  api.py           # public entry
  runtime/         # SA/RRT/AlphaUCB (vendored N-Wouda subset)
  kernel/          # main loop + winner facade
  operators/       # destroy/repair/LS/carbon/strong-bridge (private)
  support/         # charging/construction/fleet/... (private)
  PROVENANCE.md
```

```python
from setp_solver.algorithms.resetp_alns import run_resetp_alns, WinnerKernelConfig
```

See `PROVENANCE.md` for ancestry and independence rules.
