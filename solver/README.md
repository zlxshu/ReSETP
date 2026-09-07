# setp_solver

Standalone scoring utilities for generated SETP/EVRPTW-MF instances.

This package is intentionally independent from `models/`: it does not import
`setp_instance_lab`, and it only reads generated files such as
`instance_evrptwmf.txt` and `carbon_profile.csv`.

Current scope:

- load generated instance nodes and distance matrices;
- represent a given solution as routes, charging actions, and cross-site service records;
- evaluate cost and CO2e emissions for that given solution.

Out of scope for this first block:

- route feasibility checks;
- solver algorithms;
- charging time selection;
- charging amount decisions;
- automatic cross-site service detection.

Run tests:

```bash
cd solver
PYTHONPATH=src python3 -m unittest discover -s tests
```

## First-trip depot charging window (2026-09-06)

`--first-trip-window` on `solver/scripts/run_problem_hgs_private_technical.py`
decides how far back a first trip's pre-departure depot charge may reach:

- `prev_return` — it may start when the vehicle came back to the depot the
  preceding evening. **This is the default and the paper's formal setting from
  2026-09-06 on**; a real depot charger is not available to a vehicle before
  that vehicle is back. It also flips the depot charge window mode to
  `full_gap`, without which the preceding-day placement cannot survive the
  ledger replay.
- `same_day` — it may start at the simulation day's own 00:00. This is what
  every batch run before 2026-09-06 used, and it is kept so those batches can
  be reproduced. Runs under the two settings are not comparable.

Two consequences of the default flip worth knowing:

- Under `prev_return` the vehicles of one plan may legitimately charge on
  different days, so `MultiTripCertificate` records a first-trip charge day per
  duty (`first_trip_charge_day_offset_by_route`); the plan-wide scalar is the
  earliest day the plan reaches.
- `solver/scripts/build_charge_timing_comparison.py` keeps its own
  `--first-trip-window` default at `same_day` on purpose: it is a replay tool
  for already-finished batches, and those batches are `same_day`.

Evidence for the switch: `solver/reports/first_trip_window_probe_v2_20260906`.
