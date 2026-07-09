# output/ — 运行输出区

## by_experiment/

按实验归档：`E1` … `E7`、`PAPER`。  
每次任务生成子目录：`{artifact}_{UTC时间戳}/`，内含 `job_plan.json` 与产物。

## by_type/

按类型归档：

| 子目录 | 内容 |
|--------|------|
| `tables/` | 表 CSV/TeX 指针或导出 |
| `figures/` | 图 PDF/PNG 指针或导出 |
| `logs/` | 中控台运行日志（`control_console_run_*.json`） |
| `raw_csv/` | 原始跑分 |
| `reports/` | 文字报告 |
| `checkpoints/` | 断点/中间态 |

默认**不**自动覆盖 `docs/paper_submission_final/generated_*`；若要同步进论文目录，在 `PARAMETERS_CONSOLE.yaml` 里把 `figures.write_to.paper_generated` / `tables.write_to.paper_generated` 设为 `true`。
