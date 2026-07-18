# Official HGS-CVRP B gate

- Decision: **GO_A_ENGINEERING_DISCOVERY**
- Upstream commit: `1a927955cd2861a29d978f0d359d6e647db9319c`
- Budget: 3 development instances × 3 seeds × 3 seconds × 2 algorithms
- Upstream tests passed: `True`
- All shared tasks valid: `True`
- HGS near-BKS gate: `True`
- Clear HGS wins: `3/3`

## Shared development comparison

| Instance | BKS | HGS median | ALNS median | HGS gap | HGS advantage | HGS routes | ALNS routes |
|---|---:|---:|---:|---:|---:|---:|---:|
| X-n110-k13 | 14971 | 14971 | 16863 | 0.000% | 11.220% | 13 | 14 |
| X-n157-k13 | 16876 | 16879 | 19216 | 0.018% | 12.162% | 13 | 15 |
| X-n190-k8 | 16980 | 17136 | 19638 | 0.919% | 12.741% | 8 | 8 |

## Claim boundary

This is a CVRP-only development diagnostic. Official HGS-CVRP does not model ReSETP time windows, heterogeneous fleets, SOC, nonlinear charging, electricity prices, carbon, or fairness. A GO result therefore supports examining HGS search machinery in isolation; it is not evidence that HGS solves the full ReSETP problem.

The upstream self-test touched frozen X-n101-k25 only as an unmodified official software reproduction test. It was not used for tuning, comparison, or this decision.

## Hash hygiene

The first hash manifest accidentally included macOS AppleDouble sidecars and is preserved as `artifact_hashes_contaminated_appledouble.json`. The sidecars were removed and the formal `artifact_hashes.json` was regenerated. No raw run, task result, or decision value was changed.

Generated at `2026-07-18T10:26:45.862329+00:00`.
