# Semgrep 存量命中：P124 清扫结果

状态：`FROZEN_EXEMPTIONS_ONLY`（2026-08-19）。

## 当前结论

- 2026-08-18 的基线为 77 条规则结果、36 个文件。
- P124 清扫后，同一项目规则全量扫描 265 个 Git 跟踪 Python 文件，剩余 10 条结果、2 个文件。
- 原清单中 67 条非冻结结果已全部消失；同轮另外清掉了 3 条在当前工作区新暴露的活跃结果。
- 剩余 10 条全部位于用户指定的冻结文件，未修改源码，按本轮命令登记为冻结豁免。
- 因全量扫描仍非零，`.pre-commit-config.yaml` 中 Semgrep 保持报告模式；未恢复为拦截模式。

复核命令：

```bash
PRE_COMMIT_NO_CONCURRENCY=1 TMPDIR=/tmp/resetp-semgrep-p124 \
  .quality-venv/bin/pre-commit run semgrep-project-rules --all-files
```

## 冻结豁免（10 条规则结果）

| 序号 | file:line | 类别 | 原因 |
|---:|---|---|---|
| 1 | `solver/src/setp_solver/cost.py:46` | 模块级可变缓存 | 冻结文件，本轮禁止修改 |
| 2 | `solver/src/setp_solver/cost.py:47` | 模块级可变缓存 | 冻结文件，本轮禁止修改 |
| 3 | `solver/src/setp_solver/cost.py:140` | `id(...)` 对象地址缓存键 | 冻结文件，本轮禁止修改 |
| 4 | `solver/src/setp_solver/cost.py:152` | `id(...)` 对象地址缓存键 | 冻结文件，本轮禁止修改 |
| 5 | `solver/src/setp_solver/cost.py:152` | `id(...)` 对象地址缓存键（重叠结果） | 冻结文件，本轮禁止修改 |
| 6 | `solver/src/setp_solver/cost.py:1303` | `id(...)` 对象地址缓存键 | 冻结文件，本轮禁止修改 |
| 7 | `solver/src/setp_solver/cost.py:1308` | `id(...)` 对象地址缓存键 | 冻结文件，本轮禁止修改 |
| 8 | `solver/src/setp_solver/cost.py:1308` | `id(...)` 对象地址缓存键（重叠结果） | 冻结文件，本轮禁止修改 |
| 9 | `solver/src/setp_solver/search/evaluation.py:115` | `id(...)` 对象地址缓存键 | 冻结文件，本轮禁止修改 |
| 10 | `solver/src/setp_solver/search/evaluation.py:115` | `id(...)` 对象地址缓存键（重叠结果） | 冻结文件，本轮禁止修改 |

## 已清理范围

- 整块删除：强化学习算子手册及其运行链、双目标种群、旧交叉入口、旧 ALNS 内核与运行脚本、零入边历史诊断模块，以及它们的专用测试。
- 就地修复：现役人口缓存、充电时序缓存、稳定指纹键、异常处理、单目标输出契约，以及删除模块后的现役测试夹具。
- 附带清理：AppleDouble `._*` 资源叉文件；旧解析警告所在模块已随退役链删除。

本表仍是扫描结果登记，不是 Semgrep 的 suppress 或 exclude 输入；冻结文件继续参与扫描。
