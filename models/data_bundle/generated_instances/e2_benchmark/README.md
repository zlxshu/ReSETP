# E2 Benchmark Instances

This directory contains the E2 69-instance benchmark for formal algorithm comparison.

- Categories: vanilla, multidepot, threeshift.
- Counts: 27 vanilla + 27 multidepot + 15 threeshift = 69 bundles.
- Scoring protocol: ReSETP UK cost and two-layer carbon accounting; no external BKS is attached.
- Gate: OK.
- Generator commit: 78866171.

Use `e2_benchmark_manifest.json` as the source of truth for bundle paths, donor Goeke ids, fleet metadata, warm-start cost, and validation status.

## Formal default moved (2026-07-09)

Formal experiments use **L-main v2** (`../L-main/`, 9 threeshift `-01` ladders only). This `e2_benchmark` tree is the generation/stability pool. Threeshift sizes now include 10/15/20/25 (see `threeshift_small_sizes_extension_report.json`).
