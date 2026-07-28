# Pilot25 Absorption

This file records source-backed mechanisms consumed before the Pilot25 endgame runner. It is not a claim that every external system was fully reimplemented overnight.

## Cao DRL-ALNS-EVRP

- Mechanism: DQN guides ALNS choices around EVRP-specific destroy/repair; EV charging feasibility is treated as a first-class repair problem through FRVCP-style station/charge insertion.
- Adopted in Pilot25: Keep charging repair first-class and expose carbon timing as a controllable policy rather than only a generic destroy id.
- Local evidence: `Reference Algorithm\CodeforADeepReinforcementLearning-BasedAdaptiveLargeNeighborhoodSearchforCapacitatedElectricVehicleRoutingProblems (1)\工作-曹\CEVRP-NL\Code\ALNS-master\net\dqn.py`
- Local evidence: `Reference Algorithm\CodeforADeepReinforcementLearning-BasedAdaptiveLargeNeighborhoodSearchforCapacitatedElectricVehicleRoutingProblems (1)\工作-曹\CEVRP-NL\Code\ALNS-master\alns\ALNS.py`
- Local evidence: `Reference Algorithm\CodeforADeepReinforcementLearning-BasedAdaptiveLargeNeighborhoodSearchforCapacitatedElectricVehicleRoutingProblems (1)\工作-曹\CEVRP-NL\Code\ALNS-master\TEST\EVRP.py`
- Local evidence: `Reference Algorithm\CodeforADeepReinforcementLearning-BasedAdaptiveLargeNeighborhoodSearchforCapacitatedElectricVehicleRoutingProblems (1)\工作-曹\CEVRP-NL\Code\ALNS-master\utils\FRVCP.txt`

## Robbert Reijnen DR-ALNS

- Mechanism: The RL environment wraps ALNS state and operator rewards; useful as evidence that operator-selection DR alone is a narrow control surface.
- Adopted in Pilot25: Do not treat operator selection alone as the final DR surface; use it only as an A-group comparator.
- Local evidence: `Reference Algorithm\DR-ALNS@RobbertReijnen\code\src\rl\environments\cvrp_AlnsEnv_LSA1.py`
- Local evidence: `Reference Algorithm\DR-ALNS@RobbertReijnen\code\src\routing\cvrp\alns_cvrp\repair_operators.py`
- Local evidence: `Reference Algorithm\DR-ALNS@RobbertReijnen\code\src\routing\cvrp\alns_cvrp\destroy_operators.py`

## N-Wouda ALNS

- Mechanism: Clean ALNS separates selection, acceptance, stopping, and operators; this repository's ALNS-Wouda wrapper is the strong non-DR baseline.
- Adopted in Pilot25: Use ALNS-Wouda as strong-method baseline and referee-compatible plain/strong comparator.
- Local evidence: `Reference Algorithm\ALNS-7.0.0@N-Wouda\alns\ALNS.py`
- Local evidence: `Reference Algorithm\ALNS-7.0.0@N-Wouda\README.md`

## NeuOpt

- Mechanism: Learns local-search move effects, including feasible/infeasible routing regions and k-opt-style moves.
- Adopted in Pilot25: Pilot25 records it as evidence for moving beyond operator picking; full k-opt policy is out of scope for this overnight runner.
- External source: https://github.com/yining043/NeuOpt
- External commit checked by `git ls-remote`: `ccf6b5f0f6a8fda2792b4be11d4ec35390a8139b`

## NLNS

- Mechanism: Learns repair/repair-order decisions inside large-neighborhood search rather than merely selecting a handcrafted destroy operator.
- Adopted in Pilot25: Pilot25 uses the repository's learned-destroy pointer policy because it learns customer removal plus repair/q/threshold heads inside the worker repair loop.
- External source: https://github.com/ahottung/NLNS
- External commit checked by `git ls-remote`: `8fd1e83faeb0ecff7986c4e5993f7398e6b6b6f8`

## POMO

- Mechanism: Uses multiple optima/starts with shared baseline to reduce variance for neural combinatorial optimization.
- Adopted in Pilot25: Keep the Pilot22-24 POMO shared-baseline rule for any learned policy updates.
- External source: https://github.com/yd-kwon/POMO
- External commit checked by `git ls-remote`: `d7c3d6ea580499a53e874fe9e065f69e799a8551`

## GLOP / Learning to Delegate

- Mechanism: Uses decomposition/delegation for large-scale routing, explaining why direct monolithic training is expensive.
- Adopted in Pilot25: Report scale limits honestly; do not claim undertrained overnight runs prove impossibility.
- External source: https://arxiv.org/search/cs?query=Learning+to+Delegate+large-scale+vehicle+routing&searchtype=all
