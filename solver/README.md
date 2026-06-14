# setp_solver

Standalone scoring utilities for generated SETP/EVRPTW-MF instances.

This package is intentionally independent from `models/`: it does not import
`setp_instance_lab`, and it only reads generated files such as
`instance_evrptwmf.txt` and `carbon_profile.csv`.

Current scope:

- load generated instance nodes and distance matrices;
- represent a given solution as routes, charging actions, and cross-site service records;
- evaluate cost and CO2e emissions for that given solution.

Out of scope for this first block:

- route feasibility checks;
- solver algorithms;
- charging time selection;
- charging amount decisions;
- automatic cross-site service detection.

Run tests:

```bash
cd solver
PYTHONPATH=src python3 -m unittest discover -s tests
```
