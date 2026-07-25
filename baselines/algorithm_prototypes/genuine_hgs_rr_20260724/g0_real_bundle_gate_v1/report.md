# G0 real China81 bundle wiring gate

Decision: `HALT_G0_REAL_BUNDLE_WIRING`.

0/3 preregistered bundles passed.

This gate loads real frozen inputs and exercises completion, exact scoring, tailored finite-fleet decoding, and PyVRP warm-start roundtrip without running any search iteration.

It cannot support performance, 1+1>2, BKS, or SOTA claims. G1 remains separately gated.

- `cn-jjj-25c-02-V2-LOCATIONS`: FAIL — RuntimeError:decoder shortlist has no globally feasible candidate
- `cn-prd-100c-03-V2-LOCATIONS`: FAIL — RuntimeError:decoder shortlist has no globally feasible candidate
- `cn-cy-150c-03-V2-LOCATIONS`: FAIL — RuntimeError:decoder shortlist has no globally feasible candidate
