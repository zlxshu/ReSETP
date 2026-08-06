# C1：7.20 那批 MV-HGS-SP 结果是否被求解器缺陷污染

编号：`MV-AUDIT-C1-20260806`
执行：Codex（只读取证，codex 会话 `019fd5a5-a395-71d2-9096-9a3ee8b8aebf`，任务 `task-msh3swhl-dogxw2`）
落盘：终端 Claude（codex 沙箱对本外置盘只读，`apply_patch` 与 `mkdir` 均被拒，故由 Claude 代写）
状态：`AUDIT_COMPLETE`

> **口径说明**：本文正文为 Codex 交回的取证结论原文，未经改写。
> Codex 未能自行写入本文件，其完整长报告（含逐条 FACT/INFERENCE 标注与"顺带发现"）
> 已另行索取，回来后追加到本文件"§6 完整报告"一节。在此之前，本文即为唯一落盘产物。

---

## 1. 缺陷在 2026-07-20 时是否已存在

**`FACT`：已存在，而且是"从一开始就没有"，不是"后来被删掉"。**

- 2026-07-20 的初始提交 `6a624939e3cc7680cd7f00ee4ed33d4506f5ebe3` 就已包含缺陷：
  每车场 `num_available=len(customers)`，且静默 `except` 当时已经存在。
- 实体车队上限**首次加入**于 `a6d927b99bc95f4ca5e3675aa12e9cead7773902`（2026-07-23）。
- 证据：`pyvrp_adapter.py:208-240`、`epochal_hgs.py:228-243`。

> 这一条更正了一个容易产生的误读：不是"07-20 有约束、后来被谁删了"，
> 而是**07-20 那批本来就跑在没有实体车队上限的代理问题上**。
> （与之相区别的另一件事：集合划分模型里的车队上限约束确实是被 T28 越界删除的，
> 见 `HANDOFF.md` 2026-08-06 条第 2—4 点。两件事不是同一处代码，不要混。）

## 2. 7.20 那批在 898 包盘点里的判定

**`FACT`**：H4、H5、H6 三个实验包分别位于
`docs/handoff/asset_audit_20260803/package_inventory.csv` 第 47、48、49 行。

| 包 | `completion_attempted` / `completion_succeeded` | 盘点聚合值 | 种子指纹 | 分类 |
|---|---|---|---|---|
| H4 | **字段未找到** | 0/216 | — | `UNDETERMINED` |
| H5 | **字段未找到** | 0/216 | — | `UNDETERMINED` |
| H6 | — | **0/648** | `groups=3、single=1`，**存在真实种子变异** | **`AFFECTED_CONFIRMED`** |

Codex 明确记录：H4/H5 的成功率为 `UNDETERMINED`，**不得把 `archive_candidates_completed`
误当成功数**。这是记录纪律缺口，不是"查过了没问题"。

## 3. 7.20 那一门的对照对象核实

**`FACT`：7.20 没有真正的开源距离基线臂。**

7.20 实际出现的搜索视角只有三个：`cv_only`、`naive_ev`、`mechanism_ev`；
另有两个来源标签 `best_exact_hgs_parent` 与 `set_partitioning_recombination`。
比较对象是**同批三个成本代理 HGS 视角中最好的完整父方案**，
不是 `distance_only`（纯距离）的开源 HGS。

## 4. 7.27「MV 领先开源 HGS 1.92%」是否同样受影响

**`FACT`：是。该结论建立在被判定为受影响的封存搜索结果之上。**

- 7.27 确认集为 405 个配对单元，复用封存 F/E/M/MV 共 1620 行；
  结果 MV 对 O 为 354 胜、46 平、5 负，平均领先 `1.919118015025895%`。
- 复用源 `corrected_china81_rerun_v7_small_archive_ledger_20260724/full_gate`
  在 `package_inventory.csv:649` 被判为 **`AFFECTED_LIKELY`**、求解路径 P1。
- 外层 7.27 wrapper 的 `NOT_AFFECTED_PATH/P4` **只涉及新增的 O 臂**，
  不能拿它给复用的 MV 侧背书。

## 5. 总判定

**【已污染，不能作证据】**

对"多视角是不是噱头"这个问题：7.20 那批（H6 `AFFECTED_CONFIRMED`，H4/H5 `UNDETERMINED`）
与 7.27 那个 1.92%（MV 侧 `AFFECTED_LIKELY`）**都不能作为证据**——
既不能用来证明多视角有用，也不能用来证明它是噱头。

## 6. 完整报告

（待 Codex 补交全文后追加。）
