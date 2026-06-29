# Pilot23 Learned-Destroy Stabilization Report

Final verdict: `HALT_POLICY_UNSTABLE_V2`
Stop reason: best_validation_gain=12.072%, final_validation_gain=8.688%, recent_slope=0.449225, stable_keep=False, finite_losses=True, kl_ok=True, zero_violations=True, entropy_floor_ok=True

## 人话结论

- 峰值 ckpt 独立 test：avg vs operator-select = -17.72629109121851%，保没保住 +10% = False；avg_vs_operator=-17.726%, min_scale=-23.635%, avg_vs_random=-16.775%, avg_vs_worst=-11.453%, zero_violations=True, worker_ok=True, preserves_plus_10=False
- 独立 test 集：['models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113', 'models/data_bundle/generated_instances/E-UK50_01__curric_d2_s3_seed1_24h', 'models/data_bundle/generated_instances/E-UK50_02__curric_d2_s3_seed2_24h', 'models/data_bundle/generated_instances/E-UK50_03__curric_d2_s3_seed3_24h']；与训练/验证重叠 = False
- KL 稳没稳：Stage B max_approx_kl=0.01693066954612732，approx_kl_ok=True，stable_keep=False
- 最终判级：`HALT_POLICY_UNSTABLE_V2`
- 下一步：KL 已被 target-KL/LR/clip 稳住，但验证峰后保持未过闸；扩大前先复核 best-validation checkpoint 或调整稳定保持策略。
- 跑到哪：stageB；墙钟 9463.1s

## 稳定化落地

- PEAK_CHECKPOINT_INDEPENDENT_TEST：症状=Pilot22 final checkpoint fell back to +2.4% after a +11.5% validation peak.；出处=Standard NCO/RL practice selects checkpoints on validation and reports on a separate test set.；改哪=Pilot23 Stage A locates the Pilot22 validation peak checkpoint and evaluates it on non-overlapping independent test bundles/seeds.；为什么只改这=It tests the cheapest explanation, checkpoint selection, before spending another training run.
- TARGET_KL_EARLY_STOP：症状=Pilot22 gate failed because approx_kl exceeded the stability bound.；出处=PPO implementations commonly stop update epochs when approximate KL crosses a target.；改哪=Pilot23 Stage B stops the current PPO update when minibatch approx_kl exceeds target_kl and logs the stop.；为什么只改这=It directly limits the observed failure mode without changing the learned-destroy action space.
- LR_ANNEAL_SMALLER_CLIP_FEWER_EPOCHS：症状=Pilot22 validation peaked and then regressed late in training.；出处=PPO stabilization uses smaller updates via LR schedules, tighter clipping, and fewer epochs.；改哪=Pilot23 defaults to lr 1e-4 -> 1e-5, clip 0.1, and one PPO epoch while preserving POMO and 5/3/1/0 reward.；为什么只改这=The reward/baseline fixes worked; this only reduces late destructive update size.

## Artifacts

- `pilot23_preflight.json`
- `pilot23_peak_checkpoint.json`
- `pilot23_stageA_independent_test.csv`
- `pilot23_update_log.csv`
- `pilot23_validation_rows.csv`
- `pilot23_phase_rows.csv`
- `pilot23_report.json`
- `pilot23_best_validation_model.pt`
- `pilot23_best_validation_metadata.json`
