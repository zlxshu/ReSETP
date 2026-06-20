# DR-ALNS-PPO Lane

This directory is isolated from the formal solver lane. The PPO process uses
the packages pinned in `requirements.txt`. It communicates with the SETP
solver through JSONL worker messages and writes artifacts only under
`solver/reports/dr_alns_ppo/`.

## Setup

```bash
cd /Volumes/移动硬盘（512G）/ReSETP
python3.11 -m venv solver/rl/.venv
solver/rl/.venv/bin/python -m pip install --upgrade pip
solver/rl/.venv/bin/pip install -r solver/rl/requirements.txt
```

If `python3.11` is unavailable, use Python 3.12. Do not use Python 3.13 for
this lane unless `torch==2.5.1` and `stable-baselines3==2.4.1` install cleanly.

## Non-Pollution Rule

Do not edit `solver/src/setp_solver/search/formal_runner.py`,
`solver/src/setp_solver/search/candidates.py`, or `docs/paper_submission_final/*`
for this lane. Smoke and pilot outputs belong in `solver/reports/dr_alns_ppo/`.
