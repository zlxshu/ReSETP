# E3 scattered historical ownership and joint reassignment

The user-approved formal panel is
`formal_panel_solomon_i1_20260801`. It keeps every China81 customer location,
demand, time window, vehicle type and per-depot CV/EV limit. It imports only
the public initial-owner sequence (`p`) from the 4-depot, 200-customer
Uniform_Unbalanced instances published with Soriano, Gansterer and Hartl
(2023). The retired mismatch25/mismatch50 inputs are not reused.

Source dataset: `https://data.mendeley.com/datasets/rhgk26ngs8/1`

Downloaded archive: `MDVRP-PF.rar`

Archive SHA-256:
`b7c217d2af44506138b8c536c989a5758461534471daf3b3c002214d8609fea3`

Formal mapping fixed before search:

- China81 customers are sorted by `node_id`.
- The four source-label customer groups are ranked by their total China81
  demand, from largest to smallest.
- The four China81 depots are ranked by payload capacity under their original
  per-depot CV/EV limits, from largest to smallest.
- Ranked groups and depots are matched one-to-one; ties are resolved by source
  label and `depot_id`.
- Instance suffixes 01, 02 and 03 use the corresponding public replicate.
- A 150-customer China81 instance uses the first 150 labels from the
  corresponding public 200-customer sequence.
- The public Uniform family is used because customer coordinates are not
  imported; the experiment imports ownership only.

The historical-standalone arm keeps this ownership fixed. The joint-optimized
arm removes the ownership lock and lets the algorithm choose service depot,
route and vehicle type. Vehicle availability is not transferred from Soriano:
every China81 case keeps its existing maximum CV and EV counts at each depot.
No fleet ratio, minimum vehicle-type share or extra vehicle quota is imposed.

The six formal cases are the three Pearl River Delta 150-customer instances and
the three 200-customer instances, each with seeds 1--10. Both arms use the same
Solomon I1 initial construction and the same frozen search settings. Earlier
pilots and `formal_panel_20260801` are retained as superseded history; they are
not part of the user-approved formal panel.
