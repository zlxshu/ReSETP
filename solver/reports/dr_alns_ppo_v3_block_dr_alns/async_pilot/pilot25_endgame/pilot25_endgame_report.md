# Pilot25 Endgame Report

Final verdict: `PARTIAL_WIN_NO_DR`
Stop reason: dr_gain=0.000%, weak_field_gain=28.080%, stage1=HALT_NO_VALIDATION_GAIN, zero_violations=True, worker_ok=True

## 人话结论

- DR 成没成：0.00019639931060701755% vs plain timing/ALNS comparator；Stage1=HALT_NO_VALIDATION_GAIN
- 对弱场 10% 拿没拿到：28.08017534740684%
- DR 去还是留：DR 暂写 future-work：DR 增量不足，但强方法对弱场 10% 保底成立。
- 证据链：Stage0 absorption/wiring=G0_PASS；Stage1=learned_strategy=aware, avg_validation_gain=0.000%, best_validation_gain=0.000%, threshold=3.000%, zero_violations=True；Stage2=dr_gain=0.000%, weak_field_gain=28.080%, stage1=HALT_NO_VALIDATION_GAIN, zero_violations=True, worker_ok=True
- 跑到哪：stage2；墙钟 27.2s

## Artifacts

- `pilot25_absorption.md`
- `pilot25_data_manifest.json`
- `pilot25_update_log.csv`
- `pilot25_test_rows.csv`
- `pilot25_best_validation_checkpoint.json`
- `pilot25_endgame_report.json`
