# Official HGS-CVRP dependency

ReSETP uses the unmodified official HGS-CVRP C++ core only as a CVRP route
source and as a strong control. It is not a solver for ReSETP's multi-depot,
heterogeneous-fleet, charging, carbon, fairness, or dynamic semantics.

- Upstream: <https://github.com/vidalt/HGS-CVRP>
- Pinned commit: `1a927955cd2861a29d978f0d359d6e647db9319c`
- License: MIT; the upstream license is preserved verbatim in `LICENSE`.
- Rebuild entrypoint: `scripts/setup_official_hgs_cvrp_20260718.py`

The source checkout and compiled products deliberately live under ignored
`build/`. On a fresh repository checkout, run:

```bash
python3 scripts/setup_official_hgs_cvrp_20260718.py
```

The script checks out the pinned commit, builds the executable and shared
library, runs the upstream test suite, checks the source license against the
tracked copy, and writes an install manifest containing the actual binary and
library hashes. The D2 gate verifies that manifest and the actual files again
before producing any algorithm score.
