# Existing Trace Audit

Status: `EXISTING_REPORTS_NOT_BLOCK_TRAINING_DATA`.

Existing artifacts are episode/run summaries and do not contain per-block observation/action/outcome rows.

| source | exists | rows | usable as block training rows |
| --- | ---: | ---: | ---: |
| async_self_check_episode_log | True | 6 | False |
| full_gate_comparison_strict | True | 50 | False |
