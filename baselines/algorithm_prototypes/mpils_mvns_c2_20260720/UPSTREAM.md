# Upstream provenance

- Package: PyVRP 0.13.4
- Release commit recorded by ReSETP:
  `18815548d04a90a0e5eea2a0bed53a81ea9d2d49`
- Migrated source:
  `pyvrp/IteratedLocalSearch.py`
- Installed upstream file SHA-256:
  `f5c2979b2ea3d54a427fd4187c4dc6070fb9ee47886ccf3a0422dda7d83ddfcb`
- Upstream license: MIT; full text is preserved in `LICENSE-PYVRP.md`.
- Academic citation: Wouda, Lan, and Kool (2024),
  DOI `10.1287/ijoc.2023.0055`.

`event_driven_ils.py` is a clearly marked modified copy.  The original
late-acceptance, restart, penalty, statistics, and exhaustive-on-best
semantics are retained.  ReSETP adds optional before-search and
after-iteration event hooks so a mechanism perturbation can replace one
ordinary perturbation and so accepted/best events can be observed.

