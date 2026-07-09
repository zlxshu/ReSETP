# input/ — 用户输入区（按文件类型分类）

| 子目录 | 放什么 |
|--------|--------|
| `instances/` | 用户自备算例清单、覆盖说明、符号链接说明（正式 9 阶三班倒仍在 `models/.../L-main`） |
| `configs/` | 额外实验配置 JSON/YAML（可选） |
| `styles/` | 图表样式覆盖（mplstyle、色板 JSON 等） |
| `data_csv/` | CSV 输入 |
| `data_json/` | JSON 输入 |
| `data_xlsx/` | Excel 输入 |
| `data_other/` | 其他杂项 |

中控台默认**读取** `PARAMETERS_CONSOLE.yaml` 中的正式算例路径；本目录用于你手动投放的附加输入。
