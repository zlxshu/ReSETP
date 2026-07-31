# E7-CODE-01 / E7-SLIM-02 report

Status: `IMPLEMENTATION_FOUNDATION_READY__SCIENTIFIC_STREAM_NOT_SELECTED`.

Implemented: three approved trigger methods; original China81 order fields; 08:00–10:00 reception; 500 kg or 30-minute hybrid triggering; 10:00 tail processing; all legal vehicles up to depot/type caps; per-order rejection with lost revenue exactly `rho * demand_kg`.

The tests call the shared `prepare_dynamic_multitrip_solution()` and prove that an unused legal vehicle can be mobilized and that one unserviceable order does not invalidate the unit.

Verification:

```text
PYTHONPATH=solver/src /opt/anaconda3/bin/python3.13 -m pytest -q baselines/china_e3_e7/e7_trigger_policies_20260801/test_e7_trigger_policies.py solver/tests/test_dynamic_multitrip_schedule.py
13 passed in 1.64s
```

E7-SLIM-02 reduced the two production modules from 566 to 363 lines (`-203`, `-35.9%`) and the whole directory from 797 to 541 lines (`-256`, `-32.1%`) while retaining all tests. Custom threshold/window arguments, repeated type checks, repeated wrappers and duplicated prose were removed. Assertions remain only where silent drift could change the event stream, fleet authority, order set, or revenue accounting.

No scientific smoke run was started: dynamic-customer share/selection, appearance-time distribution, search budget, and unused-EV initial energy remain explicit inputs because no approved source uniquely fixes them. No shared solver or retired E7 result was changed.
