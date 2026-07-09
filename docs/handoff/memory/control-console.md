# Root Control Console

Updated: 2026-07-09

## Files

| Path | Role |
|------|------|
| `CONTROL_CONSOLE.py` | One-click entry (VS Code / CLI) |
| `CONTROL_CONSOLE.yaml` | What to run: batch / select / range |
| `PARAMETERS_CONSOLE.yaml` | How: algorithm params, paths, figure style |
| `input/` | User inputs by file type |
| `output/` | Outputs by experiment and by type |
| `console/` | Implementation package |
| `.vscode/launch.json` | F5 configs (dry-run / self-check / list) |

## Defaults

- `dry_run: true` — plans jobs, writes `job_plan.json`, does not start multi-hour solvers
- Formal instances: L-main 9-step threeshift (from PARAMETERS)

## Hang-account

E2 +5% performance push paused while control console is built.
