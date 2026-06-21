# E2 Instance Generation Audit

Gate: OK.
Generated instances: 69 total, 69 warm-start OK.
Python: `/opt/anaconda3/bin/python3.13`; numpy: `2.3.5`.
Generator commit: `78866171f3efbe7eb49c0b7dba1ed4b85b1c5362`.

## Key facts

- Vanilla uses `--base-id` semantics with `empirical_exact_base=True` and no `synthetic-only`; this switches coord/demand/time-window modes to empirical and preserves Goeke customer values.
- The generator now preserves exact Goeke depot/station coordinates in exact-base mode. For multidepot, D0 is preserved and only the second depot is generated.
- Raw Goeke files contain duplicate coordinates such as D0/S0 and station/customer overlaps, so generated-scenario validation relaxes the duplicate-coordinate and isolated-share synthetic guards only when `empirical_exact_base=True`.
- Fleet metadata uses `numPetrolVeh`/`numElectroVeh` from each Goeke donor. Current solver feasibility does not use these counts as hard caps; vehicle fixed cost remains the usage pressure.
- Three-shift variants rotate `_01/_02/_03` donors by anchor id, reuse first-shift facilities, shift customer windows by 0h/9h/18h, and drop only customers whose shifted due time exceeds 24h.

## Counts by category

- vanilla: 27 instances; OK=27.
- multidepot: 27 instances; OK=27.
- threeshift: 15 instances; OK=15.

## Three-shift count plans

- e2-threeshift-50c-01: target=50, actual=50, child_counts=[22, 22, 22], bases=['E-UK50_01', 'E-UK50_02', 'E-UK50_03'].
- e2-threeshift-50c-02: target=50, actual=50, child_counts=[22, 22, 22], bases=['E-UK50_02', 'E-UK50_03', 'E-UK50_01'].
- e2-threeshift-50c-03: target=50, actual=50, child_counts=[22, 23, 22], bases=['E-UK50_03', 'E-UK50_01', 'E-UK50_02'].
- e2-threeshift-75c-01: target=75, actual=75, child_counts=[34, 35, 33], bases=['E-UK75_01', 'E-UK75_02', 'E-UK75_03'].
- e2-threeshift-75c-02: target=75, actual=75, child_counts=[32, 33, 33], bases=['E-UK75_02', 'E-UK75_03', 'E-UK75_01'].
- e2-threeshift-75c-03: target=75, actual=75, child_counts=[33, 33, 34], bases=['E-UK75_03', 'E-UK75_01', 'E-UK75_02'].
- e2-threeshift-100c-01: target=100, actual=100, child_counts=[46, 46, 44], bases=['E-UK100_01', 'E-UK100_02', 'E-UK100_03'].
- e2-threeshift-100c-02: target=100, actual=100, child_counts=[45, 45, 44], bases=['E-UK100_02', 'E-UK100_03', 'E-UK100_01'].
- e2-threeshift-100c-03: target=100, actual=100, child_counts=[45, 45, 44], bases=['E-UK100_03', 'E-UK100_01', 'E-UK100_02'].
- e2-threeshift-150c-01: target=150, actual=150, child_counts=[70, 70, 66], bases=['E-UK150_01', 'E-UK150_02', 'E-UK150_03'].
- e2-threeshift-150c-02: target=150, actual=150, child_counts=[68, 69, 66], bases=['E-UK150_02', 'E-UK150_03', 'E-UK150_01'].
- e2-threeshift-150c-03: target=150, actual=150, child_counts=[66, 67, 66], bases=['E-UK150_03', 'E-UK150_01', 'E-UK150_02'].
- e2-threeshift-200c-01: target=200, actual=200, child_counts=[91, 92, 88], bases=['E-UK200_01', 'E-UK200_02', 'E-UK200_03'].
- e2-threeshift-200c-02: target=200, actual=200, child_counts=[88, 88, 88], bases=['E-UK200_02', 'E-UK200_03', 'E-UK200_01'].
- e2-threeshift-200c-03: target=200, actual=200, child_counts=[92, 93, 88], bases=['E-UK200_03', 'E-UK200_01', 'E-UK200_02'].
