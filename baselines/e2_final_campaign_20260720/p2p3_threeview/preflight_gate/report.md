# S1 Three-view preflight

Decision: `PASS_S1_THREEVIEW_PREFLIGHT`.
Rows: 9/9; exact-feasible rows: 9.
200-customer exact costs: `{"cv_only": 9390.71355197382, "mechanism_ev": 9389.14724976716, "naive_ev": 9390.193755425857}`.
Reason: all three views are exactly feasible and the 200-customer costs have 3 distinct value(s).

Integrity: `HASH_CONTAMINATED_APPLEDOUBLE` was observed in the phase directory; AppleDouble sidecars were removed and artifact hashes were recomputed. The raw CSV was not overwritten.

This gate is feasibility/discrimination evidence only. It does not alter the evaluator, model, instance, or stopping contract.
