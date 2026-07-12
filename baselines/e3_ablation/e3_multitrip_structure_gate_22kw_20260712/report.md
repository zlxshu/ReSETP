# E3 real-vehicle structure gate — superseded preliminary artifact

Do not use this directory for a formal conclusion.  Its first implementation
stored the "must refill" and "charge only what is needed" certificates under
the same filenames, so one result overwrote the other.

The preserved raw rows are only an audit trail.  The complete replacement is
`baselines/e3_ablation/e3_multitrip_structure_gate_22kw_20260712_v3/`.  That
replacement keeps both recharge definitions, reads the same 22 kW parameter
throughout, and still does not authorize the 70-run batch.
