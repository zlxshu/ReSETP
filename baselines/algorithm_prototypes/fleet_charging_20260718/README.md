# Fleet charging prototypes under EA-001

This directory contains isolated functional prototypes for `FC-C02` and
`FC-C05`. It must not import the formal ReSETP solver, modify `winner.py`, read
E7 live state, or select any formal model, unit, parameter, or objective.

`frvcpy_adapter.py` lazily imports the Apache-2.0 `frvcpy 0.1.1` package. The
package is intentionally not added to the formal project dependency set.
`vmr_nl.py` keeps the score function, charging oracle, nonlinear curve,
initial energy, and cross-trip semantics injectable.

The committed micro instance uses abstract time and energy values solely to
exercise nonlinear charging and mode selection. Its values are not China
scenario parameters and may not be copied into a formal experiment.

Run the tests and record builder in an isolated environment containing
`frvcpy`:

```text
PYTHONPATH=baselines/algorithm_prototypes/fleet_charging_20260718 \
python -m unittest discover \
  -s baselines/algorithm_prototypes/fleet_charging_20260718 \
  -p 'test_*.py' -v

PYTHONPATH=baselines/algorithm_prototypes/fleet_charging_20260718 \
python baselines/algorithm_prototypes/fleet_charging_20260718/run_probe.py
```

The five required records are `metadata.json`, `raw_runs.csv`,
`decision.json`, `artifact_hashes.json`, and `report.md`.
