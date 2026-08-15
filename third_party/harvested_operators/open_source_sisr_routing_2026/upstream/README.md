# Open-source C++ implementation of Slack Induction by String Removals for vehicle routing and team orienteering problems

### Authors: Martin Pajerský, Václav Sobotka, Hana Rudová, Faculty of Informatics, Masaryk University, Brno, Czech Republic

The SISRs algorithm for vehicle routing problems is implemented based on [1].
The authors of this implementation proposed its extension for team orienteering problems.

### Cite

To cite the contents of this repository, please cite the paper that also references the repository.

_Martin Pajerský , Václav Sobotka, and Hana Rudová. Open-Source Implementation of Slack Induction by String Removals for Routing and Orienteering Problems. In the 23rd International Conference on the Integration of Constraint Programming, Artificial Intelligence, and Operations Research (CPAIOR), pages 359-357. Springer LNCS 16595, 2026._

```bibtex
@inproceedings{PajerskyEtAl:SISR-VRP-OP26,
  author       = {Martin Pajersk\'y and V\'aclav Sobotka and Hana Rudov\'a},
  title        = {Open-Source Implementation of Slack Induction by
                  String Removals for Routing and Orienteering Problems},
  year         = {2026},
  booktitle    = {23rd International Conference on the Integration of Constraint Programming,
                  Artificial Intelligence, and Operations Research (CPAIOR)},
  publisher    = {Springer LNCS 16595},
  pages        = {359--357},
  doi          = {https://doi.org/10.1007/978-3-032-27242-3_22}
}
```
Contact: Hana Rudová <hanka@fi.muni.cz>

## Features of the implementation
* Vehicle routing: achieved higher speedups than the original solver [1], up to 10 times on the largest instances
* Team orienteering: computing 49 new best-known solutions and delivering about 85% of the best-known solutions across all considered variants of orienteering problems

## Repository

The repository contains a collection of C++ implementations of the Slack
Induction by String Removals (SISR) algorithm for the following problems:

* Capacitated vehicle routing problem (branch __cvrp__)
* Vehicle routing problem with time windows (branch __vrptw__)
* Pickup and delivery problem with time windows (branch __pdptw__)
* Team orienteering problem (branch __top__)
* Team orienteering problem with time windows (branch __toptw__)
* Capacitated team orienteering problem (branch __ctop__)

The individual branches contain further information, including benchmark data
compatible with the solver and instructions for building and running the solver.

## Sources

[1] Jan Christiaens, Greet Vanden Berghe (2020)
Slack Induction by String Removals for Vehicle Routing Problems.
Transportation Science 54(2):417-433. https://doi.org/10.1287/trsc.2019.0914
