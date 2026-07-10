# E2 full-benchmark performance closeout

Verdict: `E2_FULL_BENCHMARK_LEAD_SUPPORTED`.

The staged hybrid plus carbon-aware charging has total benchmark cost 173139.284391, versus 185862.880926 for runner-up LNS; aggregate lead 6.846%.
Across the 45 matched instance-seed pairs, the mean/median gains are 2.830%/0.842%, with W/T/L=[25, 5, 15] and bootstrap mean 95% CI [0.9815109976446956, 4.893671471128481].
Mean rank is 1.556 versus 1.956 for LNS. Mean runtime is 102.170s; the fastest non-ablation baseline averages 127.300s.
Carbon scheduling preserves route structure and charged energy for 45/45 pairs; 40 pairs reduce indirect EV emissions and 40 pairs record charging-time moves.

Claim boundary: the >5% statement applies to the aggregate full-benchmark cost, not every instance or the unweighted mean paired percentage. The full paired statistics must be reported beside it. Historical coarse carbon destroy/repair operators remain excluded.
