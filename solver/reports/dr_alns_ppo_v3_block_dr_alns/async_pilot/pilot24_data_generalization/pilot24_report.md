# Pilot24 Learned-Destroy Data Generalization Report

Final verdict: `HALT_NO_VALIDATION_GAIN`
Stop reason: best_validation_gain=1.629%, final_validation_gain=1.629%, recent_slope=0.0924951, stable_keep=True, finite_losses=True, kl_ok=True, zero_violations=True, entropy_floor_ok=True, fresh_no_reuse=True

## 人话结论

- 样本够不够/干不干净：train_count=250, min_train_count=200, val_count=30, test_count=30, complete=True, overlap=False, scale=25c
- 数据自修：跳过无效生成样本 6 个；generation_attempts={'train': 256, 'val': 32, 'test': 31}
- 同规模 validation：best_validation_gain=1.629%, final_validation_gain=1.629%, recent_slope=0.0924951, stable_keep=True, finite_losses=True, kl_ok=True, zero_violations=True, entropy_floor_ok=True, fresh_no_reuse=True
- 同规模独立 test：Stage2 未运行或未完成
- 最终判级：`HALT_NO_VALIDATION_GAIN`；DR 去留：去
- 下一步：数据修后 validation 闸未过，不进独立 test；DR 不再扩训，转 future-work。
- 跑到哪：stage1；墙钟 10030.7s

## 数据修落地

- LARGE_SAME_SCALE_GENERATED_POOL：症状=Pilot23 validation learned but independent cross-scale test failed.；出处=Neural CO training relies on many same-distribution, same-scale generated instances.；改哪=Pilot24 generates train/val/test 25c pools by disjoint seed ranges with complete carbon bundles.；为什么只改这=It removes the identified data cause without changing the learned-destroy algorithm.
- FRESH_PER_BATCH_POMO：症状=Earlier pilots repeatedly trained on a tiny fixed set of bundles.；出处=POMO-style training samples fresh problem instances per batch and uses grouped rollouts per instance.；改哪=Each Stage1 POMO group uses one unused train bundle and multiple rollouts on that bundle.；为什么只改这=It preserves the stable PPO/reward stack while replacing the overfit data regime.
- SAME_SCALE_TEST：症状=Pilot23 had to test 25c-trained policies on 50/100c bundles because old 25c test bundles were incomplete.；出处=Generalization claims need independent test data from the intended distribution before cross-scale claims.；改哪=Pilot24 tests the best-validation checkpoint only on held-out generated 25c bundles.；为什么只改这=This isolates data generalization from cross-scale extrapolation.

## Artifacts

- `pilot24_data_manifest.json`
- `pilot24_update_log.csv`
- `pilot24_validation_rows.csv`
- `pilot24_independent_test.csv`
- `pilot24_report.json`
- `pilot24_best_validation_model.pt`
