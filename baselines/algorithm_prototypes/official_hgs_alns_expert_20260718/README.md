# Official-HGS-based mechanism-expert HGS--ALNS

This directory is an isolated development prototype under approval
`EA-HGS-002`. It does not modify the pinned official HGS-CVRP installation or
the protected ReSETP referee files.

The official Vidal HGS-CVRP remains the population, crossover, Split, local
search, diversity, and penalty-management engine. This derivative adds a
sparse ALNS-style education step after ordinary HGS local search. Three cheap
CVRP experts are available:

1. dissolve a weak route and rebuild its customers;
2. remove high-detour customers and reinsert them by regret;
3. remove related route strings and reinsert them by regret.

The operator weights react only to actual improvements. All extra work is
charged inside the same HGS CPU-time limit. The experts are a common-domain
engineering probe, not the final ReSETP mechanism contribution. The intended
ReSETP story remains one dedicated expert for each active model mechanism:
fleet--charging coupling, depot responsibility/fairness, carbon--price
conflict, and frozen-prefix dynamic repair.

Build:

```bash
python baselines/algorithm_prototypes/official_hgs_alns_expert_20260718/setup_build.py
```

The generated binary lives under `build/official-hgs-alns-expert-20260718/`.
The official source commit and the two replaced files are hash-checked before
every build.

Development-only environment controls:

- `RESET_ME_EXPERT_ENABLED=0|1`
- `RESET_ME_EXPERT_INTERVAL=<positive integer>`
- `RESET_ME_EXPERT_STAGNATION=<non-negative integer>`
- `RESET_ME_EXPERT_KIND=-1|0|1|2` (`-1` means adaptive)
- `RESET_ME_EXPERT_REMOVAL=<positive integer>` (`0` means `sqrt(n)`)
- `RESET_ME_EXPERT_FAILURE_STOP=<positive integer>` (pause after this many
  consecutive failures; a new ordinary-HGS incumbent reopens the expert lane)
- `RESET_ME_EXPERT_MAX_CPU_SHARE=<0..0.5>` (hard cap on the share of measured
  CPU time spent inside experts; default `0.10`)

No formal benchmark, China81, E2--E7 rerun, or Stage 2 work is authorized by
this prototype.
