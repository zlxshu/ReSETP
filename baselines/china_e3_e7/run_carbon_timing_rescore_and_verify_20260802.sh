#!/bin/zsh
set -euo pipefail

cd '/Volumes/移动硬盘（512G）/ReSETP'
print -r -- "$$" > baselines/china_e3_e7/carbon_timing_rescore_20260802/.experiment_root_pid
python3 baselines/china_e3_e7/run_carbon_timing_rescore_20260802.py
python3 baselines/china_e3_e7/verify_carbon_timing_rescore_20260802.py
