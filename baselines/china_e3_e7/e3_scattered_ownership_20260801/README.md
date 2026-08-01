# E3 scattered historical ownership

This sibling experiment does not reuse the retired mismatch25/mismatch50
inputs.  It keeps every China81 customer location, demand and time window, and
imports only the public initial-owner sequence (`p`) from the 4-depot,
200-customer Uniform_Balanced and Uniform_Unbalanced instances published with
Soriano, Gansterer and Hartl (2023).

Source dataset: `https://data.mendeley.com/datasets/rhgk26ngs8/1`

Downloaded archive: `MDVRP-PF.rar`

Archive SHA-256:
`b7c217d2af44506138b8c536c989a5758461534471daf3b3c002214d8609fea3`

Mechanical mapping fixed before search:

- China81 customers are sorted by `node_id`.
- Soriano owner labels 0, 1, 2 and 3 map to China81 depots sorted by
  `node_id`.
- Instance suffixes 01, 02 and 03 use the corresponding public replicate.
- A 150-customer China81 instance uses the first 150 labels from the
  corresponding public 200-customer sequence.
- The public Uniform family is used because customer coordinates are not
  imported; the experiment imports ownership only.

The mapping is a declared transfer rule, not a claim that China81 reproduces
the geometry of the public instances.  Both balanced and unbalanced source
sequences are retained; no instance, replicate or seed is selected after
observing an effect.

Capacity infeasibility is evaluated separately for each source family. A
family that breaches its original-fleet payload lower bound records its own
HALT rows and does not prevent every predeclared seed of another feasible
family from running.

Only the public customer-owner sequence is transferred.  Vehicle availability
is not transferred from Soriano: every China81 case keeps its existing maximum
CV and EV counts at each depot.  No fleet ratio, minimum vehicle-type share or
extra vehicle quota is imposed; the optimizer chooses actual vehicle use within
those maxima.  The earlier unversioned pilot is retained only as superseded
history and is not reused by the existing-fleet pilot.
