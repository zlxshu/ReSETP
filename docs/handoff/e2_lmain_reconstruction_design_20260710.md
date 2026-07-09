# E2 L-main Reconstruction Design (Approved, Not Yet Implemented)

Date: 2026-07-10

## Decision

The formal E1--E7 benchmark will use one `L-main` family with nine **source-scale** ladders:

```text
10, 15, 20, 25, 50, 75, 100, 150, 200
```

Each formal instance is a 24-hour, three-shift, **multi-depot** construction.  The source-scale label describes the size of each Goeke child source; it is not a promise that the merged instance will have that many customers.

The final customer count is the natural result after three source children are shifted to `0h`, `9h`, and `18h`, then only customers whose shifted due time exceeds the 24-hour boundary are removed.  This 24-hour construction exists to expose time-varying carbon intensity; equal customer counts across the three shifts are not a requirement.

## Provenance and multi-depot contract

- The original Goeke sources are single-depot (`D0`) inputs.
- Each generated child must contain two depots: preserved original `D0` plus one generator-created `D1`.
- The first child defines the common two-depot and charging-station layout.  The second and third children reuse that exact layout and recompute their distance matrices.
- Each `-01` instance rotates `E-UK{scale}_01`, `_02`, `_03` through the three shifts.  The manifest must retain every source id, seed, shift offset, customer mapping, and deleted-tail record.
- The 24-hour carbon profile remains fixed to the project anchor and retains all 48 half-hour slots.

## Required generation semantics

1. Take the complete customer set from each of the three source children for a given source scale.
2. Shift customer time windows by `0`, `32400`, and `64800` seconds respectively.
3. Preserve all first- and second-shift customers.  Remove a customer only when its shifted due time is greater than `86400` seconds; under this construction this is the third-shift tail rule.
4. Do not use a count planner, prefix truncation, or post-merge deletion to force the merged customer count to equal the source-scale label.
5. Record both `source_scale` and `merged_customer_count`; paper tables and algorithm reports must use the latter when stating instance size.

## Why this reconstruction is necessary

The current active v2 generator calls `_choose_child_counts(target, ...)` and deliberately makes the merged count equal the source scale.  For example, its `10c-01` instance uses child counts `5+5+4` and ends with `5+5+0`; the complete third source has two customers that are valid in the `18h--24h` interval, but neither survives the prefix selection.  This changes a temporal 24-hour construction into a size-preserving construction and can remove the late-day carbon signal the benchmark was designed to exercise.

The old `E-UK24h-三班-01` construction demonstrates the intended pattern: three complete 100-customer children become 219 retained customers after the 24-hour tail rule, rather than being forced back to 100.

## Acceptance gates before activation

The rebuilt benchmark cannot become formal until all of the following pass:

- Exactly nine `-01` L-main instances exist, one per source scale.
- Every source child has the complete source-scale customer set before merge.
- Every merged instance has exactly `D0` and `D1`; `D0` retains the first source's physical depot identity and coordinates, while its availability is explicitly extended to the 24-hour horizon; all children share the first child's facility layout.
- The only deleted customers have reason `shifted_due_time_exceeds_24h` and originate from the third-shift tail.
- Every formal instance has at least one retained third-shift customer, so the `18h--24h` interval is represented.
- `three_shift_manifest.json`, `scenario_manifest.json`, and all artifact hashes validate; source mapping and final customer counts are exported in the L-main manifest.
- The shared initial solution passes `check_solution` with zero violations for all nine instances.
- E1--E7 registries, formal runners, control-console configuration, and tests resolve only the rebuilt formal set.

## Historical and cleanup boundary

- The current nine size-preserving L-main bundles remain retained as a historical, reproducible snapshot until the rebuilt set passes all gates.  They are not evidence for a rebuilt formal E2 result.
- `L-main_mixed23_archive_20260709`, vanilla, and standalone multidepot pools remain diagnostic/archive material, not formal E2 score inputs.
- No protected evaluator files (`cost.py`, `check.py`, `search/evaluation.py`) are changed by this reconstruction.
- No E2 performance claim is made until the rebuilt set has passed structural, feasibility, and platform-consistency gates.
