# Trace Limitations

This audit uses existing run outputs only. UNKNOWN means the current source history did not record the field; it is not inferred.

- A0/A1/A2 winner history records eval, time, best_cost, best_obj, operator, and channel, but it does not record route_count for best updates.
- Route-elimination counts expose four outcome buckets, but they do not record candidate route_count delta or exact revert reason.
- LOCAL_SEARCH timing can be counted when timing ledger is enabled, but local_search_improve_count and local_search_route_count_delta are not recorded per candidate.
- LNS history records route_count for best updates, so LNS source attribution is stronger than ALNS winner attribution.

Minimal diagnostic instrumentation patch:

1. Extend _winner_history_entry() with route_count and signature, matching baseline _SearchSession.score().
2. Add candidate_route_count, previous_route_count, hard_violation_count, changed, accepted, and revert_reason to a diagnostic-only ALNS trace row.
3. Around improve_solution_locally(), record before/after objective and route_count when SETP_ALNS_CRUSH_TRACE_DIAGNOSTIC=1.
4. Keep instrumentation behind a diagnostic flag and out of formal algorithm semantics.
