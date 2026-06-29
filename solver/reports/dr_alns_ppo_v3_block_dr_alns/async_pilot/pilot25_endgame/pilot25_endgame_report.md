# Pilot25 Endgame Report

Final verdict: `PARTIAL_WIN_NO_DR`
Stop reason: dr_gain=-24.426%, learned_vs_operator=-24.426%, learned_vs_plain=-15.885%, weak_field_gain=27.769%, stage1=HALT_NO_VALIDATION_GAIN, zero_violations=True, worker_ok=True

## 人话结论

- DR 成没成：-24.42560331247945% vs operator-select/plain-ALNS comparator；Stage1=HALT_NO_VALIDATION_GAIN
- 对弱场 10% 拿没拿到：27.76855956360977%
- 学习机器稳没稳：variant=learned_destroy_pointer_with_repair_q_threshold_heads；KL ok=True；max_kl=0.0144358891993761；零违约=True
- 规模边界：本次正式判级是 x86 same-scale 25c fresh-per-batch；未把 50c 小→大泛化当作已证明结论。
- DR 去还是留：DR 暂写 future-work：DR 增量不足，但强方法对弱场 10% 保底成立。
- 证据链：Stage0 absorption/wiring=G0_PASS；Stage1=best_validation_gain=1.629%, final_validation_gain=1.629%, recent_slope=0.0924951, stable_keep=True, finite_losses=True, kl_ok=True, zero_violations=True, entropy_floor_ok=True, fresh_no_reuse=True；Stage2=dr_gain=-24.426%, learned_vs_operator=-24.426%, learned_vs_plain=-15.885%, weak_field_gain=27.769%, stage1=HALT_NO_VALIDATION_GAIN, zero_violations=True, worker_ok=True
- 跑到哪：stage2；墙钟 10001.3s

## Artifacts

- `pilot25_absorption.md`
- `pilot25_data_manifest.json`
- `pilot25_update_log.csv`
- `pilot25_test_rows.csv`
- `pilot25_best_validation_checkpoint.pt`
- `pilot25_endgame_report.json`
