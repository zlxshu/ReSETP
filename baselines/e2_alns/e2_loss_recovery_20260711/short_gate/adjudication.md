# First short-gate adjudication

The 27 runs are complete, full-budget, zero-violation, and provenance-valid, but they do not answer the intended formal-E2 question.  The formal E2 runner uses `make_shared_initial_solution`, which introduces EV routes and applies inferred fleet limits.  This gate mistakenly built a CV-only start.  Its LNS arm also disabled the formal `common_flip_preprocess` setting.

The original raw rows and decision are preserved.  The verdict is superseded by `RESTART_SHORT_GATE_INVALID_START_CONTRACT`; the same 27-task scope must be rerun after aligning the start and LNS preprocessing contracts.  No full matrix is authorized.
