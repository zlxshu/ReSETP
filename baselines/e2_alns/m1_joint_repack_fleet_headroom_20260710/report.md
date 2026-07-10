# M1 joint route-repack and fleet-closure headroom

Verdict: `JOINT_REPACK_FLEET_HEADROOM_PARTIAL`.

This probe does not add an operator to ALNS. It asks whether route regrouping followed by repeated vehicle-type and charging repair beats either step used alone.

Fleet closure calibration against exact fixed-route enumeration: 6/6 matched.

- small / ALNS_T3 / seed 1: source 1209.390416, fleet-only 1209.390416, repack-only 1209.390416, joint 1209.390416, joint-beyond-separate 0.000000, routes 7->7, EV 6->6.
- small / LNS / seed 1: source 1250.938813, fleet-only 1250.938813, repack-only 1250.938813, joint 1250.938813, joint-beyond-separate 0.000000, routes 7->7, EV 6->6.
- small / SA / seed 1: source 1601.679401, fleet-only 1601.679401, repack-only 1601.679401, joint 1575.394558, joint-beyond-separate 26.284843, routes 6->7, EV 4->6.
- medium / ALNS_T3 / seed 1: source 2804.417204, fleet-only 2595.256147, repack-only 2804.417204, joint 2595.256147, joint-beyond-separate 0.000000, routes 17->17, EV 3->14.
- medium / LNS / seed 1: source 2941.950501, fleet-only 2941.950501, repack-only 2941.950501, joint 2911.811968, joint-beyond-separate 30.138533, routes 18->17, EV 14->13.
- medium / SA / seed 1: source 3980.787701, fleet-only 3777.840324, repack-only 3975.533140, joint 3614.556673, joint-beyond-separate 163.283652, routes 15->15, EV 2->8.
- large / ALNS_T3 / seed 1: source 4990.916297, fleet-only 4990.916297, repack-only 4990.916297, joint 4865.907262, joint-beyond-separate 125.009035, routes 32->30, EV 29->27.
- large / LNS / seed 1: source 6401.555934, fleet-only 6401.555934, repack-only 6401.555934, joint 6401.555934, joint-beyond-separate 0.000000, routes 30->30, EV 22->22.
- large / SA / seed 1: source 6987.734121, fleet-only 6746.629498, repack-only 6987.734121, joint 6688.882262, joint-beyond-separate 57.747236, routes 28->28, EV 10->17.

Boundary: a positive value means the sequential combination exposes headroom missed by both isolated steps. It does not yet prove that scheduling this move inside ALNS improves a long run.
