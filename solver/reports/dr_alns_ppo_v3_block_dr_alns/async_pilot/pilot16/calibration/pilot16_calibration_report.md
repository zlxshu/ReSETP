# Pilot16 Resource Calibration

Selected: `6 actors / eval_budget 20 / block_size 4`.
6-vs-4 throughput improvement: `39.6%`.

| config | ep/h | episodes | updates | peak used MB | min avail MB | busy | candidate nondefault | search noncontinue | violations |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| actors4_budget20_block4 | 656.70 | 130 | 10 | 13680.4 | 2555.6 | 0.923 | 0.733 | 0.497 | 0 |
| actors6_budget20_block4 | 916.89 | 134 | 10 | 13553.2 | 2682.8 | 0.894 | 0.705 | 0.524 | 0 |

Interpretation: this is a resource calibration only. It is not a performance comparison.
