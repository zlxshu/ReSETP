# S1 Three-view preflight task card

## Objective

Test the three China81 single-view HGS arms on three preregistered instances with
seed 1 before any full补跑: `cv_only`, `naive_ev`, and `mechanism_ev`.

## Inputs and facts

- Frozen China81 V2-LOCATIONS instances and the existing P3 runner/import path.
- Existing P3 `mother` logic, `build_pyvrp_problem(bundle, route_proxy_mode=...)`,
  `TIER_CAPS`, `complete_china81_route_skeleton`, and `exact_china81_score`.
- PyVRP 0.12.2 HGS environment:
  `build/python_envs/pyvrp-hgs-0.12.2/bin/python`.

## Allowed changes

- Add S1 runner and S1 evidence under this `preflight_gate/` directory.
- Do not alter P3 raw data, the solver evaluator, model parameters, or paper TeX.

## Frozen execution

- Instances: `cn-cy-25c-01-V2-LOCATIONS`, `cn-prd-75c-01-V2-LOCATIONS`,
  `cn-cy-200c-01-V2-LOCATIONS`.
- Seed: 1.
- Modes: `cv_only`, `naive_ev`, `mechanism_ev`.
- Stop rule per mode: `NoImprovement(K_M)` or `MaxRuntime(CAP_M)` from P3
  `TIER_CAPS`; full nonlinear completion and exact scoring after HGS.
- Worker pool: 6 independent real tasks on the 8-logical-core M1 machine.

## Acceptance

1. Every row completes full skeleton completion and exact scoring with no
   violations.
2. On the 200-customer instance, the three final exact costs do not all collapse
   to one value (`>=2` distinct finite costs).

## Stop conditions

- Any exception, incomplete/invalid solution, or violation: write `HALT_S1_*`.
- Fewer than two distinct finite costs on the 200-customer instance: write
  `HALT_S1_NO_VIEW_DISCRIMINATION`.
- Do not modify the contract or tune the views after a failed gate.

## Required outputs

`metadata.json`, `raw_runs.csv`, `decision.json`, `artifact_hashes.json`, and
`report.md`, with the command, environment, protected-file hashes, raw failures,
and the exact gate decision recorded.
