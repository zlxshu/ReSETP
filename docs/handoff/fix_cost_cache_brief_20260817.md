# FIX-COST-CACHE 任务书：根除 cost.py id 键缓存泄漏（发给 Codex，P87 已授权）

先读 `docs/handoff/codex_standing_charter_20260817.md` 与你自己的
`solver/reports/mem_census_20260817/report.md`。

## 授权（P87，用户 2026-08-17 上午三选一选 A）

**单独授权最小修受保护 `cost.py`**：让城市过滤后的行表具有稳定身份，使
`_CARBON_PROFILE_SORT_CACHE` 只见到少量稳定对象。**仅限这一处**；
不设阈值、不改任何排序值或评价语义；其余四个冻结文件照旧不动
（`check.py`／`search/evaluation.py`／两个 `charging.py`）。

## 施工顺序（P87 验收条款已冻结，逐级过）

0. **改前先备份**：`cost.py` 原样复制进 `solver/reports/fix_cost_cache_20260817/oracle_cost_pre_fix.py`，
   记原哈希 `525e91f7bd2cf7a4b6610ee1c8f662e8a4233c5daec800dcae5e5f21ac727989`。
1. **证明义务**：逐项证明"同一算例＋同一源 profile＋同一城市 ⇒ 每次过滤结果逐项相同"
   （查 time_profile 的来源是否算例级静态；给文件:行号）。证不出 → HALT，不动手。
2. **最小修设计**（你定具体方案并论证，注意别复刻同一反模式——新的稳定身份缓存
   **不得再拿短命对象的 id 当键**；键要么是 (源profile身份, city) 且源确为算例级长命对象，
   要么直接挂在算例/实例对象上）。写清 diff 与为什么值语义不变。
3. **验收逐级**：
   ①200 圈轨迹逐位（对照既有 202 圈产物或重跑原版）；
   ②800 圈指纹 `fc541b…d5970a3`＋成本 `2896.722268412695` 逐位（除 wall 字段）；
   ③安全阀（≈10GiB 优雅停）内深跑**越过 ≥900 圈**，报内存曲线证明平稳
   （对照：修前 755 圈即 8.9GiB）；若 900 圈后仍能继续，让它多跑（上限 3600 秒墙钟），
   顺带把 `convergence.csv` 新改进点如实带回——**这不是正式收敛跑，只是验收副产品**；
   ④回归 197（29 文件，断言不动）＋你此前的聚焦测试；
   ⑤`cost.py` 改后新哈希入册；其余四冻结文件哈希前后一致。
   **任一级不过 → 回滚至原哈希，如实 HALT。**

## 产物

`solver/reports/fix_cost_cache_20260817/`：`report.md` 首行 `FIX_COST_CACHE_DONE`／`_HALT`、
末行 `FIX_COST_CACHE_END`；oracle 备份、diff、逐级验收表、内存曲线 CSV、四件套、done.json、resume。
结尾按章程答"接下来该干什么"。
