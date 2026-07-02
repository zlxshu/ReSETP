# Track22 Final Report

Final verdict: `DR_CLEAN_NEGATIVE`

## 人话结论

Track22 的结果不支持继续把 x86 线的 DR-ALNS 推成主算法候选。不是因为训练不够，而是前置杠杆没有肉：学习型破坏的 best-of-k 探针在干净仪器上没有优势，碳时刻控制在默认场景也几乎没有可吃空间。

## 证据链

- Track21 已收口：25c+50c 共 140 行合法比较，判 `MARGIN_REAL_PROVISIONAL_X86`；100c 只保留 1 行 partial，不作公平结论。主方法对健康基线最小平均优势约 5.669%，没有达到“每个基线 >=10%”。
- Stage1 仪器闸：`PASS_INSTRUMENT`；100-01 seed901、300 eval、py313+NumPy2.3.5，winner best `2627.730354`，warm `4079.030056`，unique `11`，updates `10`，violations `0`。
- Stage2 学习型破坏杠杆闸：`NO_DESTROY_LEVERAGE_CLEAN`；rows `45`，worker integrity `True`，zero violations `True`，max-scale headroom `-1.405%`，overall headroom `-4.584%`。
- Stage3 训练/测试：`SKIP_LEARNED_DESTROY_NO_LEVERAGE`；Stage2 status=NO_DESTROY_LEVERAGE_CLEAN; learned-destroy training skipped by Track22 gate.
- Stage4 碳时刻探针：`NO_CARBON_TIMING_LEVERAGE`；默认场景平均 improvement `-0.003%`，gate rows `3`，zero violations `True`。

## 判定

- Learned-destroy: `NO_DESTROY_LEVERAGE_CLEAN`
- Clean training/test: `SKIP_LEARNED_DESTROY_NO_LEVERAGE`
- Carbon timing: `NO_CARBON_TIMING_LEVERAGE`
- Overall: `DR_CLEAN_NEGATIVE`

## 主要证据文件

- `solver/reports/dr_alns_ppo_v3/final_track21_reclaim/final_report.md`
- `stage1_instrument_gate.json`
- `track22_preflight.json`
- `track22_bundle_manifest.json`
- `track22_destroy_leverage_rows.csv`
- `stage2_destroy_leverage_summary.json`
- `track22_learned_destroy_test_rows.csv`
- `track22_carbon_timing_rows.csv`
- `track22_final_report.json`
