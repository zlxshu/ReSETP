# E2 type-aware resource chromosome: sealed-witness activity audit

This is a read-only descriptive audit of the 405 sealed corrected China81 v7 witness files. It performs no solver, completion, objective, or scorer call.

## Direct results

### HGS-M

- solutions: 405
- routes: 4953
- solutions using both CV and EV: 322/405
- solutions with at least three depot/powertrain labels: 193/405
- mean distinct depot/powertrain labels: 2.819753
- EV route share: 10.498688%
- EV customer share: 7.827735%
- public charging actions: 0/520
- charging actions at second zero: 497/520
- vehicles with multiple charging actions: 0
- solutions with cross-site service: 28/405

### MV-HGS-SP

- solutions: 405
- routes: 4932
- solutions using both CV and EV: 314/405
- solutions with at least three depot/powertrain labels: 188/405
- mean distinct depot/powertrain labels: 2.765432
- EV route share: 9.671533%
- EV customer share: 7.162791%
- public charging actions: 0/477
- charging actions at second zero: 457/477
- vehicles with multiple charging actions: 0
- solutions with cross-site service: 28/405

## Claim boundary

The results can establish only whether depot/powertrain labels are present and how active they are in the protected solutions. They do not establish that inheriting those labels improves search. The absence of public-station actions also means that a new method cannot justify itself primarily as public-charger optimization on this frozen panel.
