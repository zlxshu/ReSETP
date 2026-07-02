# E2-G0 Phase A C0 Hygiene

本阶段只做证据卫生：清理非 `.git` AppleDouble/cache，登记 `.git` 内 AppleDouble 但不触碰，重生涉证目录 clean hash。

Verdict: `C0_HYGIENE_COMPLETE`

- HEAD: `0bc17e58cc2caeb7ab632122fe6630b0e11407c6`
- removed non-git hygiene artifacts: `12`
- registered .git AppleDouble artifacts not touched: `7817`
- refreshed evidence hash dirs: `5`

## Hash Refresh

| evidence dir | status | old hash contaminated | old backup | clean entries |
|---|---|---:|---|---:|
| baselines/e2_alns/ev_heavy_findability_gate_long_same_instance_v2_data | REFRESHED | True | baselines/e2_alns/ev_heavy_findability_gate_long_same_instance_v2_data/artifact_hashes.contaminated_appledouble_20260702.json | 48 |
| baselines/e2_alns/e2_g0_same_value_platform_audit_data | REFRESHED | False |  | 8 |
| baselines/e2_alns/native_channel_autopsy_data | REFRESHED | False |  | 9 |
| baselines/e2_alns/decoder_fix_validation_data | REFRESHED | False |  | 11 |
| baselines/e2_alns/bridge_fix_validation_data | REFRESHED | False |  | 10 |
