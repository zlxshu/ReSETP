# Provenance

- DCREX method: Lei, Hao, and Wu (2026), Algorithm 3, Equation (4), and Figure
  A1 in the author manuscript stored in the repository.
- Five insertion actions and duplicate-removal precedent: Lei et al. (2026)
  and the MIT-licensed MA-FIRD / ARIX implementation by the same first author.
- Population, penalty, SREX, and compiled local-search modules used on public
  benchmarks: the independently named source copy in
  `third_party/setp_hgs_kernel`, copied from PyVRP 0.12.2 commit
  `ea0c4211819edac6fd920413ad7508cc9ad56e0e` under the MIT license.
- The copied foundation is not claimed as a research contribution.  DCREX,
  its control and attribution, and the complete problem adapters are kept in
  this separate project-owned package.
- Private complete evaluation and mechanism actions: project code migrated
  from the isolated 2026-08-07 Problem-HGS prototype and then connected to the
  formal DCREX core.  Its fast crossover moves one complete trip between
  compatible physical-vehicle duties and is not represented as SREX.

The DCREX paper does not publish implementation source.  Route-pair increments
are reconstructed explicitly from Figure A1 and protected by a numerical
regression test; this project does not claim line-for-line reproduction of an
unavailable program.
