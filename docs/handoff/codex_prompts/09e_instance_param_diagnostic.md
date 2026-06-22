# 提示词⑨e — 算例/参数根因诊断:为什么真实英国碳价下全油车最优(控制变量、内存覆盖、不改文件)

> 先读 `HANDOFF.md` + `baselines/e2_alns/throughput_halt_report.md` + `solver/src/setp_solver/prices.py`(区块A=Goeke物理、区块B=UK经济)。M1 系统 Python、`codex/reporting-pipeline`。**这是诊断,不是正式对比、不改算法、不动碳价。**

## 背景 / 要回答的问题
固定真实英国碳价(`carbon_price=0.05034`,£50.34/t)下,优化器自选车型时收敛到**全油车**,导致(a)混合车队故事退化、(b)我们的碳/EV 感知 ALNS 在纯成本上输给无 EV 机器的通用 GLNS 基线。已知:物理参数(电池80kWh/速度90km/h)是 Goeke 2013 原值、经济参数是 UK 2025 本地化替换。**需用控制变量实锤:到底是哪个非碳参数让 EV 不划算——EV 续航(电池/速度)、充电太贵(公共电价/占用费)、还是地理太散?**

## 铁律(必须遵守)
- **不改任何文件的参数语义**:`prices.py`/算例 bundle/`cost.py`/`check.py`/`evaluation.py` 一律不动。所有参数扰动用**内存覆盖**:`dataclasses.replace(DEFAULT_PRICES, B_battery_kwh=..., v_speed_ms=..., ...)`,把覆盖后的 prices 传给 `evaluate()/check_solution()/求解器`。
- **碳价全程钉死 `0.05034` 不扫**(碳敏感是 E4 的事,不在本环节)。本诊断只扫**非碳**参数。
- 只产出诊断脚本 + 报告(可 commit 为新文件);不 promote、不改 winner/基线算法。
- 系统 Python + `PYTHONHASHSEED=0`;零违约才计。

## Phase 0 — audit:确认覆盖真的生效
- 验证 `dataclasses.replace` 的 prices 覆盖能穿透到:① `evaluate()` 的能耗/成本(改 `v_speed_ms` 或 `B_battery_kwh` 后,EV 能耗/续航/可行性确实变);② 求解器/充电修复(`candidates` 的 EV 充电、`check_solution` 的 SoC 可行性是否读传入 prices 的电池容量)。若某条路径硬编码 DEFAULT_PRICES、覆盖穿不过去,**如实报告、并改用"对固定参考解重算"的退路**(见 Phase 1 退路)。输出到报告。

## Phase 1 — 成本分解 + 充电行为(baseline,不改参数,看机制)
取小算例(建议 `e2-vanilla-25c-01`、`e2-vanilla-50c-01`、`e2-threeshift-50c-01`,小=快)。用现有求解器(winner ALNS 或 LNS,小预算)在每个算例上取三种解:
- **全油车**(`SearchPolicy(max_ev=0)`)、**全电动**(`max_cv=0`)、**自由混合**。
对每个解报**完整成本分解**(`evaluate()` 的 `cost_fix/cost_km/cost_fuel/cost_elec/cost_occ/cost_carbon/total`)并排对照,外加 **EV 充电行为**:充电次数、公共 vs 场站充电的能量与花费、占用费合计、充电绕行距离、**多少 EV 路线撞到 80kWh 上限/被迫公共充电**。→ 实锤"全电动/混合到底输在哪个分项、是不是被逼上贵公共充电"。

## Phase 2 — 控制变量单参数扫描(内存覆盖,碳钉死,逐一隔离)
在同一小算例上,**每次只改一个非碳参数**(其余全真实、碳价钉死),重求(若覆盖能穿透)或对参考解重算(退路),报 **全油车 vs 全电动 vs 自由混合 的最优成本**,看**哪个参数把"全油车最优"翻成"混合/全电动 ≤ 全油车"**:
- **电池 `B_battery_kwh`**:80(基线)/160/320/480(现代电动货车量级)。
- **速度 `v_speed_ms`**:25(=90km/h 基线)/16.7(=60)/11.1(=40,城市配送)。
- **公共充电价 `electricity_price`+`station_electricity_price`**:0.82(基线)/0.40/0.1853(=场站价,验证"充电太贵"是不是命门)。
- **占用费 `occupancy_fee`**:0.50(基线)/0.10/0。
- (可选)**地理尺度**:若能在内存里缩放 instance 距离矩阵(×0.5/×0.25)而不落盘,测"地理太散"假设;不能干净做就注明、跳过。

每行报:该单参数取该值时,(全油/全电/混合)最优成本、最优车队的 CV/EV 数、混合是否反超全油车。

## 交付 + 结论
`baselines/e2_alns/instance_param_diagnostic.md`:Phase1 分解+充电行为表 + Phase2 单参数扫描表 + **一句话结论**:在固定真实碳价下,**哪个(或哪几个)非碳参数是"全油车最优"的真凶**,以及把它更新到什么现实值(如现代电池/城市速度)能让混合车队成为最优。+ 诊断脚本 + commit(报告写 hash)。**诚实:若没有任何单参数能翻盘、需要组合,或若发现是别的原因,如实写。**

## 边界
- 不改文件参数/不动算法/不碰碳价;纯内存覆盖的诊断。
- 禁改 `cost.py`/`check.py`/`evaluation.py` 语义(只是用 override 的 prices 调它们,这是受支持的入参)。
- 跑不出诚实 HALT;系统 Python 金标准。
