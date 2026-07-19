# SEG-GEN-01 fresh warning runner incident v1

- Date: 2026-07-19
- Status: `REPORTING_RUNNER_FAILED_AFTER_WORKERS_BEFORE_RESULT_DISCLOSURE`
- Failed runner SHA-256: `0b1ae97c5cdbd0d86d544934a8f51451a833d1201f3f4405ea94fe80c60943d4`
- Blind-lock SHA-256: `5730383819c6c27237ae3460fc2e3620506de6c9bb90c6f29c1cc508f68e7328`
- Confirmed result disclosure before repair: none

The six locked worker calls completed, but the parent reporting process failed
while normalizing a no-selection event. The event stored `selected: null`; the
reporting code assumed `selected` was always an object and raised:

`AttributeError: 'NoneType' object has no attribute 'get'`

This is a reporting-only defect. No algorithm source, task, arm, seed, budget,
start solution, price, or pass/fail threshold is changed. Worker payloads lived
only in parent-process memory and were lost when the parent exited; no result
artifact directory was created and no cost comparison was inspected.

The allowed repair is restricted to treating `selected: null` as an empty
object in the two reporting expressions. A replacement source hash and lock
must be recorded before rerunning. The rerun remains subject to the original
no-rescue rule.
