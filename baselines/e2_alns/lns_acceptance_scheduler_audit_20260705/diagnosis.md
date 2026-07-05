# LNS Scheduler/Acceptance Trace Audit Diagnosis

Verdict scope: diagnostic only, not formal T3.
Rows: 96/96; OK=96; fail=0.

LNS path contribution summary is reported from explicit trace_path values: scan_initial, vehicle_type_mutation, strong_bridge, fallback_relocate.
ALNS candidate summary is reported from diagnostic candidate_trace; UNKNOWN means the trace did not record enough information and is not inferred.

LNS best-improved counts by path:
- strong_bridge: 1334
- vehicle_type_mutation: 339
- scan_initial: 33
- fallback_relocate: 19

ALNS attempts by revert reason:
- unchanged: 103460
- candidate_usable: 87751
