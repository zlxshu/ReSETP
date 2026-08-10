# SETP HGS Kernel

This directory is an independently named source copy of the mature HGS
foundation in PyVRP 0.12.2.  It is used as the low-level routing kernel of the
project-owned algorithm.  The frozen open-source baseline remains in its own
environment and is not imported or called at runtime.

## Provenance

- Upstream project: PyVRP
- Upstream repository: https://github.com/PyVRP/PyVRP
- Upstream tag: `v0.12.2`
- Upstream commit: `ea0c4211819edac6fd920413ad7508cc9ad56e0e`
- License: MIT, preserved verbatim in `LICENSE.md`

The source was copied on 2026-08-09.  The mechanical separation changes are:

1. the Python package was renamed from `pyvrp` to `setp_hgs_kernel`;
2. Python imports, the top-level compiled extension, C++ namespaces, build
   paths, the package name, and the command entry point were renamed to match;
3. upstream algorithm behaviour was otherwise retained at this boundary.

The copied kernel is not a claimed research contribution.  Project-owned
crossovers, controllers, full-problem completion and experimental entry points
live outside this directory.

`UPSTREAM_README.md` and `CITATION.upstream.cff` preserve the original project
description and citation metadata.
