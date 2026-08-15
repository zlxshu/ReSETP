# Origin and use boundary

- Retrieved: 2026-08-11
- Upstream: https://github.com/hankarudova/open-source-sisr-routing
- License: Apache License 2.0; the upstream text is preserved as
  `upstream/LICENSE.txt`, `cvrp/LICENSE.txt`, and `vrptw/LICENSE.txt`.
- Main-branch commit: `d71919811f64a4bf158ae91cd159cf3cb6a35e5c`
- CVRP-branch commit: `fe1a33a6b5bf0dfaba87fb65565dcb4db2d9a89c`
- VRPTW-branch commit: `857c8eeafd95cbdf8245620486d309369f1aab20`
- Retrieval method: immutable GitHub commit archives, extracted without source
  modification. The `upstream/` directory is the main branch; `cvrp/` and
  `vrptw/` are complete solver branches, including their benchmark material.

This is the primary study source for the SISR hunt. The repository names Martin
Pajersky, Vaclav Sobotka, and Hana Rudova as authors and is tied to a CPAIOR
2026 publication and a defended Masaryk University thesis. Its public Git
history is short (14 commits, with solver branches imported as branch-creation
commits), so the academic publication, thesis, named institutional authors, and
benchmark corpus are the stronger human-authorship evidence.

Use is permitted under Apache-2.0. Any code reused in ReSETP must retain the
required license and attribution notices and must still be reviewed and tested
under the ReSETP project contract. This snapshot is study material; it is not
called by the project at runtime.
