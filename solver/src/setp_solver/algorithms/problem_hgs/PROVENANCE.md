# Provenance

- Population, penalty, SREX/OX crossover, and compiled local-search modules:
  the independently named source copy in `third_party/setp_hgs_kernel`,
  copied from PyVRP 0.12.2 commit
  `ea0c4211819edac6fd920413ad7508cc9ad56e0e` under the MIT license.
- The copied foundation is not claimed as a research contribution.  The
  complete problem adapters, the Duty representation, charging repair, and
  the full-model evaluation chain are kept in this separate project-owned
  package.
- Private complete evaluation and mechanism actions: project code migrated
  from the isolated 2026-08-07 Problem-HGS prototype.
- Fixed-route charging decisions use the harvested frvcpy implementation;
  see `FRVCPY_LICENSE_NOTICE.md` and `frvcpy_adapter.py`.

The DCREX crossover portfolio (Lei, Hao, and Wu 2026) was implemented,
retired, and removed from this directory; its provenance record lives in
version-control history only.
