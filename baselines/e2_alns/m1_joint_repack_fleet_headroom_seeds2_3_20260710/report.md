# M1 joint route-repack and fleet-closure headroom

Verdict: `JOINT_REPACK_FLEET_HEADROOM_PARTIAL`.

This probe does not add an operator to ALNS. It asks whether route regrouping followed by repeated vehicle-type and charging repair beats either step used alone.

Fleet closure calibration against exact fixed-route enumeration: 6/6 matched.

- small / ALNS_T3 / seed 2: source 1209.510970, fleet-only 1209.510970, repack-only 1209.510970, joint 1209.510970, joint-beyond-separate 0.000000, routes 6->6, EV 3->3.
- small / LNS / seed 2: source 1207.542070, fleet-only 1207.542070, repack-only 1207.542070, joint 1207.542070, joint-beyond-separate 0.000000, routes 6->6, EV 4->4.
- small / SA / seed 2: source 1722.545382, fleet-only 1613.551351, repack-only 1722.545382, joint 1556.122523, joint-beyond-separate 57.428828, routes 7->7, EV 2->6.
- small / ALNS_T3 / seed 3: source 1153.018969, fleet-only 1153.018969, repack-only 1153.018969, joint 1153.018969, joint-beyond-separate 0.000000, routes 6->6, EV 5->5.
- small / LNS / seed 3: source 1200.255147, fleet-only 1200.255147, repack-only 1200.255147, joint 1200.255147, joint-beyond-separate 0.000000, routes 6->6, EV 4->4.
- small / SA / seed 3: source 1689.726107, fleet-only 1689.726107, repack-only 1689.726107, joint 1610.362875, joint-beyond-separate 79.363232, routes 7->7, EV 5->5.
- medium / ALNS_T3 / seed 2: source 2870.632044, fleet-only 2628.683969, repack-only 2870.632044, joint 2628.683969, joint-beyond-separate 0.000000, routes 16->16, EV 3->12.
- medium / LNS / seed 2: source 2899.583258, fleet-only 2899.583258, repack-only 2899.583258, joint 2849.042119, joint-beyond-separate 50.541139, routes 17->17, EV 12->13.
- medium / SA / seed 2: source 4042.810758, fleet-only 3777.840324, repack-only 3975.533140, joint 3614.556673, joint-beyond-separate 163.283652, routes 15->15, EV 1->8.
- medium / ALNS_T3 / seed 3: source 2537.794586, fleet-only 2537.794586, repack-only 2537.794586, joint 2537.794586, joint-beyond-separate 0.000000, routes 15->15, EV 11->11.
- medium / LNS / seed 3: source 2829.664092, fleet-only 2829.664092, repack-only 2829.664092, joint 2771.831102, joint-beyond-separate 57.832990, routes 16->16, EV 10->12.
- medium / SA / seed 3: source 3905.670885, fleet-only 3777.840324, repack-only 3905.670885, joint 3614.556673, joint-beyond-separate 163.283652, routes 15->15, EV 4->8.
- large / ALNS_T3 / seed 2: source 5506.573656, fleet-only 4936.384180, repack-only 5506.573656, joint 4936.384180, joint-beyond-separate 0.000000, routes 32->32, EV 7->29.
- large / LNS / seed 2: source 6351.339834, fleet-only 6351.339834, repack-only 6351.339834, joint 6286.213682, joint-beyond-separate 65.126152, routes 30->32, EV 23->28.
- large / SA / seed 2: source 7041.797568, fleet-only 6611.287279, repack-only 7041.797568, joint 6611.287279, joint-beyond-separate 0.000000, routes 28->28, EV 7->16.
- large / ALNS_T3 / seed 3: source 6324.283000, fleet-only 6324.283000, repack-only 6324.283000, joint 6323.690684, joint-beyond-separate 0.592316, routes 33->29, EV 25->19.
- large / LNS / seed 3: source 6944.238048, fleet-only 6944.238048, repack-only 6944.238048, joint 6712.771331, joint-beyond-separate 231.466717, routes 32->30, EV 23->21.
- large / SA / seed 3: source 7083.143153, fleet-only 6607.393645, repack-only 7083.143153, joint 6607.393645, joint-beyond-separate 0.000000, routes 28->28, EV 5->16.

Boundary: a positive value means the sequential combination exposes headroom missed by both isolated steps. It does not yet prove that scheduling this move inside ALNS improves a long run.
