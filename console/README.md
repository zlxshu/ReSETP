# console/ — 中控台实现包

| 模块 | 作用 |
|------|------|
| `registry.py` | 实验/图表 ID 与顺序 |
| `planner.py` | batch / select / range → Job 列表 |
| `runner.py` | dry-run 规划、IO 树、预检、有限 live hook |
| `config.py` | 加载两份 YAML |

根目录入口：`CONTROL_CONSOLE.py`。
