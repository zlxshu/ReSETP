# Winner Kernel Reproducibility Note

- classification: `floating_or_blas_numeric_drift`
- conclusion: NumPy default_rng probes match across environments, so the winner-cost drift is not explained by the sampled RNG stream; the remaining evidence points to numeric/BLAS/Python-version drift.
- rng_probe_equal: `True`

## Gold Standard Environment

- python_executable: `/opt/anaconda3/bin/python3.13`
- python_version: `3.13.9 | packaged by Anaconda, Inc. | (main, Oct 21 2025, 19:11:29) [Clang 20.1.8 ]`
- numpy_version: `2.3.5`

## RL Venv Environment

- python_executable: `/Volumes/移动硬盘（512G）/ReSETP/solver/rl/.venv/bin/python`
- python_version: `3.11.3 (v3.11.3:f3909b8bc8, Apr  4 2023, 20:12:10) [Clang 13.0.0 (clang-1300.0.29.30)]`
- numpy_version: `1.26.4`

## BLAS Summary

- system_blas_excerpt: `name: openblas     openblas configuration: USE_64BITINT=0 DYNAMIC_ARCH=1 DYNAMIC_OLDER= NO_CBLAS=       NO_LAPACK=0 NO_LAPACKE= NO_AFFINITY=1 USE_OPENMP=0 VORTEX MAX_THREADS=128     pc file directory: /opt/anaconda3/lib/`
- venv_blas_excerpt: `"name": "openblas64",       "found": true,       "version": "0.3.23.dev",       "detection method": "pkgconfig",       "include directory": "/opt/arm64-builds/include",       "lib directory": "/opt/arm64-builds/lib",    `

## Reproducibility Policy

Formal solver/winner experiments should bind the audited system Python environment above. For paper reproducibility, pin that Python/numpy stack in documentation; this task does not modify the RL venv dependencies.