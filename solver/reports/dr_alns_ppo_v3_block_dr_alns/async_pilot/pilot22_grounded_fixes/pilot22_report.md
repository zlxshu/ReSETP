# Pilot22 Learned-Destroy Grounded Fixes Report

Final verdict: `HALT_POLICY_UNSTABLE`
Stop reason: best_validation_gain=11.507%, final_validation_gain=2.410%, gain_slope=-0.102373, finite_losses=True, kl_ok=False, zero_violations=True, entropy_floor_ok=True

## 人话结论

- 现 ckpt 差距缩没缩：Stage A avg vs operator-select = -15.933959524025147%，Pilot21 ckpt gap is -15.934%; Stage B still proceeds with the grounded fixes
- 按文献修齐后学没学到：best_validation_gain=11.507%, final_validation_gain=2.410%, gain_slope=-0.102373, finite_losses=True, kl_ok=False, zero_violations=True, entropy_floor_ok=True
- 最终判级：`HALT_POLICY_UNSTABLE`
- 下一步：验证曾有峰值但训练后期回落且 KL 不稳；先查 PPO 更新幅度、学习率、batch/clip，再决定是否新开稳定性实验。
- 跑到哪：stageB；墙钟 12397.8s

## 三修法落地

- G1_VALIDATION_COST：症状=Pilot21 failed only because entropy increased although reward, slope, loss, and KL were healthy.；出处=POMO NeurIPS 2020 discourages premature convergence; RL4CO reports validation/test gaps rather than entropy-drop gates.；改哪=Pilot22 Stage B G1 uses held-out deterministic cost improvement, finite losses, KL stability, and only an entropy floor.；为什么只改这=The failure was a gate-definition problem, not evidence that high entropy itself is unhealthy.
- POMO_SHARED_BASELINE：症状=Single-trajectory GAE gave high-variance credit for the same instance.；出处=POMO uses multiple rollouts per instance and a shared group baseline.；改哪=Pilot22 groups multiple stochastic learned-destroy rollouts on the same bundle and uses group mean return as the advantage baseline.；为什么只改这=It changes the credit estimator while preserving the existing policy, worker, and solution-feasibility contract.
- DISCRETE_5_3_1_0_REWARD：症状=Pilot21 still used custom 120x best-gain scaling after removing the max(0) clamp.；出处=Cao alns/ALNS.py reward_list=[5,3,1,0]; Reijnen-style ALNS outcome classes are best, better, accepted, rejected.；改哪=learned_destroy_reward maps new best/accepted improvement/accepted worsening/rejected to 5/3/1/0.；为什么只改这=This is the published operator-selection reward shape; the rest of the search/referee semantics stay unchanged.

## Artifacts

- `pilot22_preflight.json`
- `pilot22_literature_fixes.json`
- `pilot22_stageA_exploratory.csv`
- `pilot22_update_log.csv`
- `pilot22_validation_rows.csv`
- `pilot22_report.json`
- `pilot22_phase_rows.csv` (Stage C skipped marker)
