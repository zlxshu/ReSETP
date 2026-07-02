# C3 / E2-G1 independent ALNS migration report

人话结论：本步只做运行时剥离，不做算法增强。主 ALNS 已从 N-Wouda `alns` 包迁到项目内 `resetp_alns` 后端；destroy/repair 算子、成本、约束、价格默认值和 TeX 都没有改。

Verdict: `ALNS_INDEPENDENCE_CONFIRMED`.

## Boundary

- This is not formal T3 and must not be written as an algorithm win/loss.
- `Reference Algorithm/ALNS-7.0.0@N-Wouda` is retained untouched.
- `run_alns_wouda` keeps its legacy API name for runner compatibility, but the main runtime backend is now project-local.

## Anchors

### goeke80_100_01_seed2

- pre commit `b6cf9b902f85d3f614704479161b25a358a70a5c` best_cost `2677.7953638343815`, solution_hash `88dcd835d3b18cf0d22f24303859a64cbc8a50b7c963c50fbc535a3d7d97a8e5`.
- post commit `b9663c6ab9d457dae33d60b63402f84a0554468d` best_cost `2677.7953638343815`, solution_hash `88dcd835d3b18cf0d22f24303859a64cbc8a50b7c963c50fbc535a3d7d97a8e5`.
- primary parity: `True`.

### threeshift_150c_01_seed1_B280_eval2000

- pre commit `b6cf9b902f85d3f614704479161b25a358a70a5c` best_cost `3561.080964207054`, solution_hash `daa1662ed1c1df3886915802ba4c1ab722aa1eaf612b845798389032bfd56afc`.
- post commit `b9663c6ab9d457dae33d60b63402f84a0554468d` best_cost `3561.080964207054`, solution_hash `daa1662ed1c1df3886915802ba4c1ab722aa1eaf612b845798389032bfd56afc`.
- primary parity: `True`.

## Historical Anchor Note

- goeke80_100_01_seed2: historical expected_best_cost 4779.053444002934 is stale under pre-migration current HEAD; pre-migration actual was 2677.7953638343815. Migration parity is judged against pre/post current-chain anchors.

## Non-result Differences

- goeke80_100_01_seed2: raw history hash includes wall-clock time_seconds
- threeshift_150c_01_seed1_B280_eval2000: raw history hash includes wall-clock time_seconds
- threeshift_150c_01_seed1_B280_eval2000: raw operator_counts hash differs only after retaining timing ledger

## Gates

- grep gate ok: `True`.
- protected-file gate ok: `True`.
- reference algorithm directory gate ok: `True`.
- environment: `{'python': '/opt/anaconda3/bin/python3.13', 'numpy': '2.3.5', 'pythonhashseed': '0'}`.

## Next Boundary

后续 E2 baseline bridge/liveness/debug 应统一基于 independent backend。若要修 bridge 或调参，需要另起任务；本报告不授权改建模或写算法胜负。
