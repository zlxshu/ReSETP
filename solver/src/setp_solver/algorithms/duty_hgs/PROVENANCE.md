# Provenance

- DCREX method: Lei, Hao, and Wu (2026), Algorithm 3, Equation (4), and Figure
  A1 in the author manuscript stored in the repository.
- Five insertion actions and duplicate-removal precedent: Lei et al. (2026)
  and the MIT-licensed MA-FIRD / ARIX implementation by the same first author.
- Population, penalty, and compiled local-search modules used on public
  benchmarks: PyVRP 0.12.2.  PyVRP itself remains a frozen external baseline;
  this directory does not modify its installed source.
- Public fast crossover: PyVRP 0.12.2's unmodified compiled
  Nagata--Kobayashi selective route exchange (SREX), called only from this
  algorithm's separate controller.
- Private complete evaluation and mechanism actions: project code migrated
  from the isolated 2026-08-07 Duty-HGS prototype and then connected to the
  formal DCREX core.  Its fast crossover moves one complete trip between
  compatible physical-vehicle duties and is not represented as SREX.

The DCREX paper does not publish implementation source.  Route-pair increments
are reconstructed explicitly from Figure A1 and protected by a numerical
regression test; this project does not claim line-for-line reproduction of an
unavailable program.
