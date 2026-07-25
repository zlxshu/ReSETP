# Resource-slot pricing v3 G0

Verdict: `HALT_G0_WORKER_RESOLVED_ARCHIVED_RUNNER`.

The v3 zero-objective engineering gate passed: the spawn smoke used six
distinct processes, all six real-bundle engineering tasks passed, and no
candidate complete objective was evaluated. The unchanged six-task G0 was then
started with six workers.

All six G0 tasks stopped with `KeyError: 'k'`. A read-only import-resolution
check proved that `worker_entry_v3.py` resolved bare `import run_g0` to:

`baselines/algorithm_prototypes/dual_guided_resource_order_20260725/run_g0.py`

instead of this candidate's
`resource_slot_pricing_20260725/run_g0.py`. The archived runner expects an
unrelated `k` setting that is intentionally absent from the resource-slot
registration.

No task completed, no candidate complete objective was evaluated, no output
witness was produced, and independent replay did not start. Consequently the
frozen performance criteria were not evaluated; this is an operational G0
startup failure, not evidence that the algorithm improved or failed to improve
the locked HGS-M starts.

The authorization requires reporting the exact terminal result rather than
opening another repair. No v4, retry, algorithm change, budget change or
performance claim is authorized.
