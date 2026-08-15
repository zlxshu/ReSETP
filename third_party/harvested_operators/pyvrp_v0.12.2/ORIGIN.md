# PyVRP 0.12.2 operator-source provenance

- Upstream repository: https://github.com/PyVRP/PyVRP
- Upstream tag: `v0.12.2`
- Tag commit: `ea0c4211819edac6fd920413ad7508cc9ad56e0e`
- Upstream license: MIT; the unmodified license text is preserved as `LICENSE.md`.
- Local source package used for extraction:
  `build/python_envs/pyvrp-frozen-0.12.2-clean/lib/python3.13/site-packages/`
- Package identity is preserved verbatim as `PACKAGE_METADATA`.
- Extraction date: 2026-08-11.

The files below are byte-for-byte copies. No operator logic was written or
modified for this harvest:

- `src/search/RelocateWithDepot.cpp`
- `src/search/RelocateWithDepot.h`
- `src/search/Route.cpp`
- `src/search/Route.h`
- `src/search/SwapRoutes.cpp`
- `src/search/SwapRoutes.h`
- `src/search/python_init.py` (upstream `pyvrp/search/__init__.py`)

Semantic limitation: `RelocateWithDepot` inserts a reload depot while moving a
client. It is a close source-backed implementation for depot insertion in a
multi-trip route, but it is not the pure Depot-Insert operator defined by Lei &
Hao. `SwapRoutes` exchanges route contents after fixed depots; it is not the
three-case Depot-Replace operator.
