# D6 corrected S3 observation-only trajectories

Decision: `PASS_D6_CORRECTED_S3_TRAJECTORIES`.

Each displayed seed was registered by distance to the algorithm's ten-seed mean cost before observing its curve. The hook copied only route skeletons and timestamps. Offline full-model scoring occurred after search. Every rerun final cost equals the sealed corrected S3 cost exactly within 1e-9. The registered shape gate also requires at least six genuine cost decreases and eight plotted observations per algorithm, with the sealed final solution as the final plotted point. Curve observations do not replace official table scores.
