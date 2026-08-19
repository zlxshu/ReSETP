# MEM-CENSUS 任务书：对象持有者普查（发给 Codex，MEM-DIAG 的续篇）

先读 `docs/handoff/codex_standing_charter_20260817.md` 与你自己的
`solver/reports/mem_diag_20260817/report.md`（本任务就是执行你在其结尾提议的下一步，
方案被 Claude 采纳，细化如下）。

## 目标（一句话）

把深区段仍未归属的数 GiB 活对象钉死成一条闭环：**对象类型 → 直接持有容器（字段路径）→
创建行号**。不再试任何缓存阈值。

## 执行要点（按你自己的提案）

1. 扩展现有外置探针（`mem_diag_20260817/` 的脚本可复用；无 memray/objgraph，不引新依赖）：
   同命令同 seed 跑一次，在约第 200 圈与安全阀触发前（约第 700+ 圈）各取一次快照——
   对象类型计数＋浅层大小；对增长最快的前几类（`ChargingAction`、tuple、dict 等）
   抽样 `gc.get_referrers()`，记录容器类型与字段路径（向上追 2–3 层到具名属主）。
2. 两次快照做差，报：每类型的数量/大小增量、TOP 持有链（带文件:行号）、
   与七个时序缓存已知贡献的切割（哪些 GiB 归它们、哪些归新发现的持有者）。
3. **安全阀照旧**（≈10GiB 优雅停；绝不许系统杀第三次）；referrer 抽样注意别把探针自身
   的临时引用计入（gc 普查的经典假阳性，采样前 `gc.collect()` 并排除探针帧对象）。

## 修法边界（拿到闭环后）

- 持有者在**未冻结**文件（如 `charge_timing.py`）且属纯精确键 memoization／可释放的滞留引用
  → 按 P85 直接做**最小修**并依次验收：200 圈逐位、800 圈指纹
  `fc541b…d5970a3`（成本 2896.722268412695）逐位、深区段（阀内跑到 ≥900 圈）内存曲线平稳；
- 持有者落在任一**冻结** `charging.py`（P78）→ 立即 HALT 报告，不越界；
- 修法会改变搜索语义（如 education 缓存类）→ HALT 写清，留用户。

## 产物

`solver/reports/mem_census_20260817/`：`report.md` 首行 `MEM_CENSUS_DONE`／`_HALT`、
末行 `MEM_CENSUS_END`；快照差分 CSV、持有链清单、四件套、done.json、resume。
边界照旧（不动三保护文件与两个冻结 charging；不动既有现场）。结尾答"接下来该干什么"。
