# 充电择时链路代码审查（只读）2026-09-04

审查人：Claude（只读；未修改任何仓库文件；未运行任何搜索）
仓库根：`/Volumes/移动硬盘（512G）/ReSETP`　分支 `codex/reporting-pipeline`　HEAD `2a8e9c05b`（09-04 15:03）

---

## 1. 自检 1/2 与 `REPLAY_TOLERANCE` 有没有被削弱

**判定：通过。**

`REPLAY_TOLERANCE` 仍是 `1e-6`，与提交版逐字相同：

`solver/scripts/build_charge_timing_comparison.py:126`
```python
REPLAY_TOLERANCE = 1e-6
```

自检 1 的致命路径仍在，判据未放宽（`> REPLAY_TOLERANCE` → `SystemExit`）：

`build_charge_timing_comparison.py:568-579`
```python
            for key, value in official.items():
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                dev = abs(float(stage_a[key]) - float(value))
                ...
                if dev > REPLAY_TOLERANCE:
                    raise SystemExit(
                        f"REPLAY MISMATCH {label} policy={run['policy']} "
```

“可行性”分叉的实现确实按描述做了，且分叉点是**解自身策略 vs 探针策略**，不是自检 1 本身：

`build_charge_timing_comparison.py:462-483`
```python
    def _settle(individual, changed, context, evaluator, policy, label, *, required):
        ...
        if not evaluation.feasible:
            violations = [str(item) for item in evaluation.violations]
            if required:
                raise SystemExit(
                    f"{label}: re-settled solution infeasible under the "
                    f"solution's own policy: {violations}"
                )
            return None, violations
```

调用侧：阶段 A 恒为 `required=True`（`:562`），阶段 B 只有 `name == run["policy"]` 才是 `required=True`（`:590`）。
自检 2 与提交版同判据同容差（`build_charge_timing_comparison.py:601-616`），只是把“asap vs cost_plus_carbon”推广成“基准 vs 其余各策略”，默认口径下逐字等价。

与提交版对照（`git show HEAD:` 版第 399-401 行）原先是“任何策略不可行即 `SystemExit`”，现在只有原策略不可行才致命。**这是放宽，但放宽的是探针策略，不是自检 1**，且被排除的解在 `summary.json.infeasible_under_policy` 与 `same_route.*.excluded_solutions` 里逐条落盘。

---

## 2. 阶段 A 是否恒用原日历与批次碳价；阶段 B 是否独立；A≡B 断言

**判定：通过（一条口径说明）。**

`build_charge_timing_comparison.py:441-445`
```python
    stage_a_context = _stage_context(None, batch_carbon_price)
    stage_a_evaluator = DutyFullEvaluator(stage_a_context)
    stage_b_context = _stage_context(tariff_calendar_authority, stage_b_carbon_price)
    stage_b_evaluator = DutyFullEvaluator(stage_b_context)
```

阶段 A 的第一个实参写死 `None`（＝原日历），第二个写死 `batch_carbon_price`（来自 `shared["carbon_price_cny_per_kg"]`，`:392`），`--carbon-price` 只能落到 `stage_b_carbon_price`（`:394-398`）。两个 evaluator 与两套重排策略字典（`:452-460`）分开构造。

`context_cache` 以日历 CSV 的绝对路径为键（`:418`）：日历不同 → 两次独立 `_build_context`；日历相同 → 共用同一份底层 bundle，再各自 `replace(...)` 出新 context。**口径说明**：默认口径（authority=None）下两阶段命中同一缓存项，A≡B 断言退化为“同一 context 上两个 evaluator 各评一遍”，只测确定性，不测日历通道；真正两次独立构建的对照是 identity probe（不同目录、同字节），见第 6 节。

A≡B 逐位断言存在且判据是 `!= 0.0`（不是 1e-6）：

`build_charge_timing_comparison.py:637-650`
```python
            if stages_identical:
                for key, value in stage_a.items():
                    ...
                    if dev != 0.0:
                        raise SystemExit(
                            f"STAGE A/B DISAGREE {label} key={key}: "
```
`stages_identical = calendar_identical and stage_b_carbon_price == batch_carbon_price`（`:412`），`calendar_identical` 由两份 CSV 的 sha256 判定（`:406-410`），不是路径。

产物实测：`solver/reports/charge_timing_comparison_v2_20260904/summary.json` 的 `stage_a_b_identity = {"applies": true, "max_abs_deviation": 0.0}`。

**一条报告缺口（非正确性问题）**：默认口径下 `extended=False`（`:413-417`），自检 3 与 A≡B **照常执行**，但不写进 `summary.json`。所以 `solver/reports/charge_timing_comparison_20260904/summary.json` 里只有两条自检记录。

---

## 3. 自检 3 的两条断言

**判定：通过。**

路线六项容差为 **0**（逐位），不是 1e-6：

`build_charge_timing_comparison.py:619-630`
```python
            native = settled[run["policy"]]
            for key in ROUTE_INVARIANT_KEYS:
                dev = abs(float(native[key]) - float(official[key]))
                ...
                if dev != 0.0:
                    raise SystemExit(
                        f"COUNTERFACTUAL ROUTE DRIFT {label} key={key}: "
```

`cost_elec` 必须不同，判据 `dev == 0.0` 即退出，且触发条件用 **sha 判定**的 `calendar_identical`，不是路径：

`build_charge_timing_comparison.py:631-639`
```python
            if not calendar_identical:
                dev = abs(float(native["cost_elec"]) - float(official["cost_elec"]))
                ...
                if dev == 0.0:
                    raise SystemExit(
                        f"COUNTERFACTUAL CALENDAR NOT READ {label}: cost_elec "
```

产物实测（`P=1.0`）：`T=original` → `cost_elec_must_differ=false`；`T=midday_valley` → `true`，最小偏差 `7.357955086374702`；`T=uniform` → `true`，最小偏差 `1.2777766875112775`。全部 > 0。

**一条边界说明**：`original` 日历 + 非批次碳价的格子里，3b 与 A≡B 双双 `applies=false`（日历同、碳价异）。这批格子没有任何“日历通道被吃到”的自检覆盖——但它们本来也不换日历，是正确的。

---

## 4. `--route-source-arms` 的作用面 与 `reoptimised_vs_resettled`

**判定：通过。**

“重新优化对照”循环写死两臂，不读 `route_source_arms`：

`build_charge_timing_comparison.py:500`
```python
    for arm in (ASAP_ARM, CARBON_ARM):
```
只有“同一路线对照”的取路线循环用它（`:552`　`for arm in route_source_arms:`）。

产物实测 `charge_timing_comparison_v2_20260904`（`route_source_arms=["MT-HGS"]`）：`reoptimised` 仍是 `{'MT-HGS': 10, 'MTC-HGS': 10}`，`same_route` 只有 `pooled`（n=10）与 `from_MT-HGS`。

`reoptimised_vs_resettled` 的两侧正是要求的口径：

`build_charge_timing_comparison.py:934-944`
```python
            mt_resettled = [
                row[contrast_policy]["total_cost"]
                for row in mt_rows
                if contrast_policy in row
            ]
            mtc_reoptimised = [
                row["total_cost"]
                for row in reoptimised[CARBON_ARM]["per_run"].values()
            ]
```
即 MTC 十次重搜的落盘总成本 vs MT 十组路线在 `cost_plus_carbon` 下重排后的总成本。检验用 scipy 双侧：`:963-971`　`mannwhitneyu(left, right, alternative="two-sided")`。产物实测 U=69.0，p=0.161972410480126，n=10/10。

---

## 5. `emission_robustness` 的剔除规则

**判定：不通过（唯一影响“会被写进论文的数字”的一条）。**

既不是写死 run_09，也不是“5 油 1 电”或任何离群判据，而是**无条件取最大值剔除**：

`build_charge_timing_comparison.py:766-776`
```python
    worst_run = max(
        reoptimised[ASAP_ARM]["per_run"].items(), key=lambda item: item[1]["E_total"]
    )
    trimmed = [
        value
        for run_name, row in reoptimised[ASAP_ARM]["per_run"].items()
        for value in (row["E_total"],)
        if run_name != worst_run[0]
    ]
```

两个后果：

1. 换批次重跑不会“剔错”成 run_09，但会**无条件剔掉 asap 臂排放最高的那一次**，无论它是不是离群。本批 run_09 确实是离群（实测 asap 臂十次 E_total：185.67 / 191.53 / 196.83 / 199.88 / 200.89 / 201.23 / 202.36 / 203.80 / 204.45 / **263.68**，且 run_09 是 5CV/1EV，其余为 2–3CV/3EV），所以本批的数字碰巧站得住；规则本身站不住。
2. `mean_gap_excluding_that_run = mean(碳感知臂，未剔) − mean(asap 臂，剔掉自身最大值)`（`:785-788`），减数被单边下压，**按构造必然朝一个方向移动**。`median_gap_excluding_that_run` 同理（`:791-794`）。

受影响的产物字段：`emission_robustness.mean_gap_excluding_that_run`、`emission_robustness.median_gap_excluding_that_run`；以及 `summary.md` 第五节第 2 条与第六节 (a) 段直接引用这两个数的正文。

**修法（一句话）**：把无条件 `max` 换成显式离群判据（例如 `n_veh_ev` 与众数构型不同，或与中位数差 > k×IQR），判据不成立时该字段返回 `None`；并且两臂同时剔除或明确改名为“单边截尾”。

---

## 6. 反事实日历生成器

**判定：全部通过（a–e 逐条实测）。**

**(a) 只改 beijing 行、只改四列、`energy+service==total`。**
非目标城市的行整行原样透传：`build_counterfactual_tariff_calendar.py:280-284`
```python
        if fields[idx["city"]] != TARGET_CITY:
            midday_lines.append(line)
            uniform_lines.append(line)
            continue
```
写出前逐行验证“移动的列 ⊆ 四列白名单”：`:317-333`（`if not moved <= set(MUTABLE_COLUMNS): raise SystemExit`）。价格闭合在两处校验：源侧 `:146-149`（`abs((public+service)-total) > 1e-12` → 退出），uniform 侧 `:263-271`。`public_service_fee_cny_per_kwh` 不在可变列里，且逐行校验其恒定（`:287-288`）。

**(b) 三档各 16 槽 / 8.0 h 的断言。**
`:227-243`：源日历与 midday 布局都逐档校验 `== 8.0`，否则 `SystemExit`；`:244-249` 再校验 midday 的槽集恰好是 1..48 的划分。

**(c) 三份日历日均未加权电价逐位相等的断言，失败是否真退出。**
`:346-372`：写出后**重读三份文件**复算 `math.fsum` 均值，`if len(set(values.values())) != 1: raise SystemExit(...)`。是真退出。

**(d) 午谷时段边界（实测读生成的 CSV，beijing / 2025-02-12，48 槽）。**

| 槽 | 时刻 | 原 period | 原 depot | 午谷 period | 午谷 depot | 均一 period | 均一 depot |
|---:|---|---|---:|---|---:|---|---:|
| 1 | 00:00 | valley | 0.56328575 | flat | 0.83644275 | flat | 0.8494500833333333 |
| 2 | 00:30 | valley | 0.56328575 | flat | 0.83644275 | flat | 0.8494500833333333 |
| 3 | 01:00 | valley | 0.56328575 | valley | 0.56328575 | flat | 0.8494500833333333 |
| 4 | 01:30 | valley | 0.56328575 | valley | 0.56328575 | flat | 0.8494500833333333 |
| 5 | 02:00 | valley | 0.56328575 | valley | 0.56328575 | flat | 0.8494500833333333 |
| 6 | 02:30 | valley | 0.56328575 | valley | 0.56328575 | flat | 0.8494500833333333 |
| 7 | 03:00 | valley | 0.56328575 | valley | 0.56328575 | flat | 0.8494500833333333 |
| 8 | 03:30 | valley | 0.56328575 | valley | 0.56328575 | flat | 0.8494500833333333 |
| 9 | 04:00 | valley | 0.56328575 | valley | 0.56328575 | flat | 0.8494500833333333 |
| 10 | 04:30 | valley | 0.56328575 | valley | 0.56328575 | flat | 0.8494500833333333 |
| 11 | 05:00 | valley | 0.56328575 | valley | 0.56328575 | flat | 0.8494500833333333 |
| 12 | 05:30 | valley | 0.56328575 | valley | 0.56328575 | flat | 0.8494500833333333 |
| 13 | 06:00 | valley | 0.56328575 | flat | 0.83644275 | flat | 0.8494500833333333 |
| 14 | 06:30 | valley | 0.56328575 | flat | 0.83644275 | flat | 0.8494500833333333 |
| 15 | 07:00 | flat | 0.83644275 | flat | 0.83644275 | flat | 0.8494500833333333 |
| 16 | 07:30 | flat | 0.83644275 | flat | 0.83644275 | flat | 0.8494500833333333 |
| 17 | 08:00 | flat | 0.83644275 | flat | 0.83644275 | flat | 0.8494500833333333 |
| 18 | 08:30 | flat | 0.83644275 | flat | 0.83644275 | flat | 0.8494500833333333 |
| 19 | 09:00 | flat | 0.83644275 | flat | 0.83644275 | flat | 0.8494500833333333 |
| 20 | 09:30 | flat | 0.83644275 | flat | 0.83644275 | flat | 0.8494500833333333 |
| 21 | 10:00 | peak | 1.14862175 | peak | 1.14862175 | flat | 0.8494500833333333 |
| 22 | 10:30 | peak | 1.14862175 | peak | 1.14862175 | flat | 0.8494500833333333 |
| 23 | 11:00 | peak | 1.14862175 | peak | 1.14862175 | flat | 0.8494500833333333 |
| 24 | 11:30 | peak | 1.14862175 | peak | 1.14862175 | flat | 0.8494500833333333 |
| 25 | 12:00 | peak | 1.14862175 | valley | 0.56328575 | flat | 0.8494500833333333 |
| 26 | 12:30 | peak | 1.14862175 | valley | 0.56328575 | flat | 0.8494500833333333 |
| 27 | 13:00 | flat | 0.83644275 | valley | 0.56328575 | flat | 0.8494500833333333 |
| 28 | 13:30 | flat | 0.83644275 | valley | 0.56328575 | flat | 0.8494500833333333 |
| 29 | 14:00 | flat | 0.83644275 | valley | 0.56328575 | flat | 0.8494500833333333 |
| 30 | 14:30 | flat | 0.83644275 | valley | 0.56328575 | flat | 0.8494500833333333 |
| 31 | 15:00 | flat | 0.83644275 | flat | 0.83644275 | flat | 0.8494500833333333 |
| 32 | 15:30 | flat | 0.83644275 | flat | 0.83644275 | flat | 0.8494500833333333 |
| 33 | 16:00 | flat | 0.83644275 | flat | 0.83644275 | flat | 0.8494500833333333 |
| 34 | 16:30 | flat | 0.83644275 | flat | 0.83644275 | flat | 0.8494500833333333 |
| 35 | 17:00 | peak | 1.14862175 | peak | 1.14862175 | flat | 0.8494500833333333 |
| 36 | 17:30 | peak | 1.14862175 | peak | 1.14862175 | flat | 0.8494500833333333 |
| 37 | 18:00 | peak | 1.14862175 | peak | 1.14862175 | flat | 0.8494500833333333 |
| 38 | 18:30 | peak | 1.14862175 | peak | 1.14862175 | flat | 0.8494500833333333 |
| 39 | 19:00 | peak | 1.14862175 | peak | 1.14862175 | flat | 0.8494500833333333 |
| 40 | 19:30 | peak | 1.14862175 | peak | 1.14862175 | flat | 0.8494500833333333 |
| 41 | 20:00 | peak | 1.14862175 | peak | 1.14862175 | flat | 0.8494500833333333 |
| 42 | 20:30 | peak | 1.14862175 | peak | 1.14862175 | flat | 0.8494500833333333 |
| 43 | 21:00 | peak | 1.14862175 | peak | 1.14862175 | flat | 0.8494500833333333 |
| 44 | 21:30 | peak | 1.14862175 | peak | 1.14862175 | flat | 0.8494500833333333 |
| 45 | 22:00 | flat | 0.83644275 | peak | 1.14862175 | flat | 0.8494500833333333 |
| 46 | 22:30 | flat | 0.83644275 | peak | 1.14862175 | flat | 0.8494500833333333 |
| 47 | 23:00 | valley | 0.56328575 | flat | 0.83644275 | flat | 0.8494500833333333 |
| 48 | 23:30 | valley | 0.56328575 | flat | 0.83644275 | flat | 0.8494500833333333 |

对照图纸：谷 = 槽 3–12（01:00–06:00）+ 槽 25–30（12:00–15:00）；峰 = 槽 21–24（10:00–12:00）+ 槽 35–46（17:00–23:00）；平 = 槽 1–2（00:00–01:00）+ 13–20（06:00–10:00）+ 31–34（15:00–17:00）+ 47–48（23:00–24:00）。**逐槽一致。** 计数 valley/flat/peak = 16/16/16（原日历同为 16/16/16），uniform 为 flat 48。
uniform 价 0.8494500833333333 = (0.56328575+0.83644275+1.14862175)/3，与原日历 48 槽算术均值逐位相同。

**(e) 非北京行逐字节不变（自行 diff）。**
以原始 CRLF 文本逐行对比：三份 cf 日历都是 12098 行、表头相同，**非 beijing 行差异 0 行**；beijing 行 1344 行中，midday 差异 392 行（= 28 日期 × 14 个换档槽，与上表 14 个换档槽吻合），uniform 差异 1344 行（全改），identity_probe 差异 0 行。
`china81_cf_calendar_identity_probe_20260904` 的 CSV sha256 与原日历**完全相同**（`7f9ce897c4593bf0…`）。

**再生复现**：用 `--midday-out/--uniform-out` 指到 scratchpad 重跑生成器，产出 CSV 的 sha256 与仓库内产物逐位相同（midday `c9c9b2e2354ed04c…`，uniform `2f5e7b864b682432…`）。脚本在**写完两份 CSV、两份 README 与全部断言之后**，在最后一行 `print(midday_dir.relative_to(repo))`（`:477`）对仓库外路径抛 `ValueError`——只影响打印，不影响产物，不算缺陷。

---

## 7. 网格脚本

**判定：全部通过。**

**(a) 每格是否真跑三条自检。** 是。每格独立调用 `build_comparison`：`run_charge_timing_grid.py:292-301`
```python
            summary = build_comparison(
                repo=repo,
                batch_dir=batch_dir,
                policies=list(GRID_POLICIES),
                route_source_arms=list(DEFAULT_ROUTE_SOURCE_ARMS),
                carbon_price_override=price,
                tariff_calendar_authority=authority,
                context_cache=context_cache,
```
`context_cache` 只缓存 `_build_context` 的结果（按日历 CSV 路径），重排与评价每格都重做；每格自己的 `self_checks` 逐格落盘（`readout["self_checks"] = summary["self_checks"]`，`:203`）。24 个格子的 `summary.json` 都带完整四行自检记录，实测已核 `P=1.0` 三格。

**(b) 偏离比例的定义与分母。** 分母是**两个策略都可行的解数**：`run_charge_timing_grid.py:130-152`
```python
    comparable = [
        row for row in rows if "cost_plus_carbon" in row and "cost_min" in row
    ]
    deviating = [ ... if abs(row["cost_plus_carbon"]["cost_elec"]
                          - row["cost_min"]["cost_elec"]) > REPLAY_TOLERANCE ]
    ...
        "share": len(deviating) / len(comparable) if comparable else None,
```
判据是充电费差 > 1e-6 元。另有一条 `schedule_deviation` 用 `E_total` 读“充电时刻是否真的动了”（平价日历下 `cost_elec` 看不出来），同分母。

**(c) 两条断言是否覆盖全部格子。** 覆盖。碳恒等式断言遍历 `per_solution_by_cell` 的**每个格子 × 每个解 × 每个可行策略**，判据 `!= 0.0`（`run_charge_timing_grid.py:339-355`）；跨碳价的时刻不变断言遍历**每份日历 × 除参考价外的每个碳价 × 每个解 × 三个价格无关策略 × 三个字段**，判据同为 `!= 0.0`（`:357-386`）。产物实测：`carbon_identity_max_abs_deviation = 0.0`，`price_independent_schedule_max_abs_deviation = 0.0`。

**(d) uniform 日历下 `cost_min` 的平局是否可复现。** 可复现，且脚本自己把这个风险标了出来（`cost_indifference` 块，`:170-192`）。
底层平局处理是确定性的：候选集是排序后的元组（`charge_timing.py:673`　`tuple(sorted(round(value, 9) for value in candidates))`），取最小用 `(score, start)` 复合键（`charge_timing.py:812`　`min(scored, key=lambda item: (item[0], item[1]))[1]`），同分取最早开始时刻，无集合/字典迭代序参与。
实测：`--only-carbon-price 1.0` 连跑两次写到两个目录，`T=uniform/P=1.0/summary.json` 除时间戳外完全相同（`cost_min` 均值总成本两次都是 `2807.2641996173393`），且与仓库内 `solver/reports/charge_timing_grid_20260904/T=uniform/P=1.0/summary.json` 完全相同。

---

## 8. `carbon_min` 在 MT-HGS/run_04 上不可行（`latest_start_second` 未编码班次回场约束）

**判定：这是求解器搜索侧本来就有的问题，不是重排工具引入的。不修，只判断。**

**定位。** 趟间车场补电的时刻上界在
`solver/src/setp_solver/algorithms/problem_hgs/charging.py:2198-2205`
```python
                else:
                    if previous_return is None:
                        raise AssertionError("missing preceding trip return")
                    earliest = previous_return
                    latest = (
                        _latest_trip_departure_second(
                            timing, route, instance, prices
                        )
                        - duration
                    )
                    mode = "full_gap"
```
该上界的来源是
`solver/src/setp_solver/algorithms/problem_hgs/charging.py:1513-1528`
```python
def _latest_trip_departure_second(timing, route, instance, prices) -> float:
    """Latest depot departure a pre-departure depot charge may end at.
    ... the charge may run until the latest departure that still meets
    every customer deadline (``route_timing`` backward recursion).
    """
    latest = getattr(timing, "latest_departure_second", None)
```
`latest_departure_second` 由 `solver/src/setp_solver/search/multitrip_schedule.py:675/742` 的 `latest_feasible_departure` 给出，是**单趟自身**客户时间窗与终点节点 `due_time` 的后向递推结果。**它不含“本车必须在 AM 班次结束前回场”这条 duty 级约束**。班次侧只有下界被接进来（`_shift_minimum_departure_second_by_route` 提供 `shift_floors`，`charging.py:2245-2255`），上界没有。

违规是在评价器里才发现的：`solver/src/setp_solver/algorithms/problem_hgs/evaluation.py:1698`
```python
                    f"returns after {shift_id} end; late by {late:.12g} s",
```

**为什么是搜索侧的问题。** `repair_changed_duties` 不是重排工具私有的：搜索的教育/修复阶段调用同一个函数——`education.py:396`、`integrated_private.py:417`、`initialization.py:808`、`runner.py:660`。所以正式搜索里同一条过宽上界照样生效。

**在正式搜索里造成什么。** 充电修复会把趟间补电排到晚于班次回场允许的时刻，产出一个**带硬时间窗违规的个体**；该个体随后被 `DutyFullEvaluator` 判为不可行。往下追到消费端（三处逐行核过，不是从 `is_feasible=` 那一行推的）：

- 分类口径：`integrated_private.py:850`　`is_feasible=lambda evaluation: bool(evaluation.feasible)`；
- 保留而非丢弃：`external_population.py:68-72`
  ```python
        subpopulation = (
            self._feasible
            if self._is_feasible(candidate.evaluation)
            else self._infeasible
        )
  ```
  不可行个体进 `_infeasible` 子种群，仍然入池、仍然参与多样性与配对；
- 不会被当成最优：`integrated_genetic_algorithm.py:234-239`
  ```python
        candidate_feasible = self._adapter.is_feasible(candidate.evaluation)
        ...
        if not candidate_feasible:
            return False
  ```
  且 `_best_value` 对不可行个体返回 `inf`（`:222-226`）；`_add` 只在 `repaired` 可行时把修复结果加回池（`:203-205`）。

所以：不会崩溃、不会把不可行解写成最优解，也不会把它直接扔掉。代价是**白白浪费候选、并且丢掉本可以靠“早一点开始充电”救活的个体**——修复器本身没有能力回退到一个满足班次的更早时刻。

**波及面（实测，不是推断）。** 24 个格子里：
- `carbon_min` 在 **全部 24 格**上让 `MT-HGS/run_04` 不可行（违规固定为 `EV_D_OSM_WAY_1071205721_7#T2` 晚 `118.6639562` s）；
- `cost_plus_carbon` 在 **uniform 日历的全部 8 格**上让同一个解不可行；`original` 与 `midday_valley` 日历下 `cost_plus_carbon` 全部可行。

论文当前正式产物（`solver/reports/charge_timing_comparison_20260904`，原日历、批次碳价、只用 asap 与 cost_plus_carbon）**没有任何解被排除**，20/20 全参与。两条臂的搜索策略分别是 `asap` 与 `cost_plus_carbon`，都不是 `carbon_min`。所以这条缺陷**不污染已落盘的论文数字**；但它在“均一电价 + cost_plus_carbon”这类新情景里已经被触发，属于要登记的搜索侧欠账。

---

## 9. 默认参数重跑回归

**判定：通过。**

重跑 `build_charge_timing_comparison.py`（默认全部参数）到 scratchpad，与 `solver/reports/charge_timing_comparison_20260904/summary.json` 比对：
- 自写比较器（逐键递归）：`IDENTICAL`；
- `summary.md` 去掉首行时间戳后 `diff` 无输出；`README.md` 仅首行时间戳不同；
- 该代理的 `compare_charge_timing_summaries.py` 交叉核验：payload sha256 两侧同为 `542416bf5f10565358b77c8a181f3cd63ea0959c4ea622e8f5898738de0a3d16`，原始行数 1730 vs 1730，差异行 1 行且是 `generated_utc`，`VERDICT: identical except generated_utc`，退出码 0。

附带核到一条：`solver/reports/charge_timing_probe0_identity_20260904/summary.json` 去掉时间戳后与默认产物**完全相同**，且其 `configuration` 为 `null`——即 identity probe 走的是默认口径分支，产物里没有留下“本次用的是 identity_probe 目录”的记录。数字是对的（这正是 identity probe 该有的结果），但该产物**无法自证**用的是哪份日历，只能靠 `run.log` / 命令行。

---

## 10. 短测试

**判定：通过。**

```
PYTHONPATH=.:solver/src:third_party/setp_hgs_kernel:models/src:solver/scripts \
  .public-hgs-venv/bin/python3 -m pytest solver/tests -q -x
→ 248 passed, 3 warnings in 112.64s
```
3 条 warning 全部是 PyVRP 内核的 `PenaltyBoundWarning`，与本次改动无关。

---

## 11. 三个受保护文件今天有没有被改

**判定：今天没有被改。**

| 文件 | mtime | 工作树改动内容 | 与今天主题相关 |
|---|---|---|---|
| `solver/src/setp_solver/cost.py` | 2026-08-30 23:46:35 | 266+/97−，涉及 `carbon_slot_index` 签名（`n_slots` 由可选改必填）、`charging_curve_for_action`、`route_node_schedule`、`charging_slot_breakdown` | 否 |
| `solver/src/setp_solver/check.py` | 2026-09-03 18:25:00 | 单个 hunk，注释自署 “2026-09-03（model alignment）”，把 `current_departure` 从 `route_departure_second(...)` 改成读 `schedule` 的 `origin_row.t_depart` | 否 |
| `solver/src/setp_solver/search/evaluation.py` | 2026-08-31 00:20:25 | 一条注释删掉 “GBP”，一行 `node_lookup` 改用 `context.instance.node_lookup` | 否 |

今天动过的脚本 mtime 均为 2026-09-04 17:30–17:57；三个受保护文件的 mtime 全部早于 09-04。`check.py` 的改动自署 09-03，且与 `charging.py:1513` 那条同样自署 “2026-09-03 (model alignment)” 的 docstring 属同一批工作，与今天的“电价日历参数化 / 两段式 / 多策略 / 碳价 / 路线来源臂过滤”无关。`cost.py` 的 266 行改动全在碳槽索引与充电曲线，主题完全不同。

---

## 追加发现（清单外，但会当场把脚本打断）

**`contrast_policy` 缺列时的 `KeyError`，已实测复现。**

`build_charge_timing_comparison.py:669-673`
```python
            if verbose:
                base_total = row[baseline_policy]["total_cost"]
                contrast_total = row[contrast_policy]["total_cost"]
```
自检 2 里 `settled[baseline_policy]` 也没有同样的存在性保护（`:607-608`，只守了 `name`）。

实测：按脚本自己 README 里写的命令形态跑
`--tariff-calendar-authority data/ChinaInstances/china81_cf_calendar_uniform_v1_20260904`（默认 policies / 默认两臂 / verbose）
在 `MT-HGS/run_04` 上抛
```
File ".../build_charge_timing_comparison.py", line 672, in build_comparison
    contrast_total = row[contrast_policy]["total_cost"]
KeyError: 'cost_plus_carbon'
```
网格脚本传 `verbose=False` 才绕过了它，所以 `charge_timing_grid_20260904` 能跑完。这是**崩溃，不是静默出错**，没有污染任何已落盘产物；但只要有人用命令行在 uniform 日历上单独重建一次对照，就会被拦住。
修法：那两行加 `if baseline_policy in row and contrast_policy in row`（或整段 `row.get(...)` 化），自检 2 同样加 `if baseline_policy not in settled: continue`。

**`set_active_recharge_mode` 未被调用。** `recharge_mode` 在 `SHARED_METADATA_FIELDS`（`:88`）里被读出来做一致性校验，但脚本从不据它设置进程全局。当前批次是 `on_demand`，与进程默认一致，所以自检 1 实测偏差 0.0。这条**由自检 1 实测保住，不是由构造保住**：换一个用不同补电模式的批次会在自检 1 上大声失败，不会静默出错。

---

## 汇总表

| # | 条目 | 判定 | 关键证据 |
|---|---|---|---|
| 1 | `REPLAY_TOLERANCE` / 自检 1、2 未被削弱；可行性分叉 | 通过 | `build_charge_timing_comparison.py:126, 462-483, 568-579, 601-616` |
| 2 | 阶段 A 恒用原日历+批次碳价；阶段 B 独立；A≡B 逐位断言 | 通过（默认口径下 A≡B 退化，见正文） | `:441-445, 412, 637-650`；v2 产物 `max_abs_deviation=0.0` |
| 3 | 自检 3 两条断言（路线容差 0；`cost_elec` 必不同，按 sha 触发） | 通过 | `:619-639`；实测 midday 最小偏差 7.3580、uniform 1.2778 |
| 4 | `--route-source-arms` 只影响同路线对照；MW 检验口径 | 通过 | `:500 vs :552`；`:934-944, 963-971`；v2 产物 U=69.0 p=0.16197 |
| 5 | `emission_robustness` 剔除规则 | **不通过** | `:766-776, 785-794` 无条件 argmax 截尾，单边 |
| 6 | 反事实日历生成器 (a)(b)(c)(d)(e) | 通过 | 48 槽逐槽核对一致；非京行 0 差异；再生 sha 逐位相同 |
| 7 | 网格 (a)(b)(c)(d) | 通过 | `run_charge_timing_grid.py:292-301, 130-152, 339-386`；两次重跑逐位相同 |
| 8 | `latest_start_second` 未编码班次回场 | 搜索侧缺陷（不修，登记） | `charging.py:2198-2205, 1513-1528`；`multitrip_schedule.py:675/742` |
| 9 | 默认参数重跑回归 | 通过 | payload sha256 两侧相同，仅 `generated_utc` 不同 |
| 10 | `pytest solver/tests -q -x` | 通过 | 248 passed |
| 11 | 三个受保护文件今天是否被改 | 今天未改 | mtime 08-30 / 09-03 / 08-31；改动主题均非今天 |
| 追加 | `contrast_policy` 缺列 `KeyError` | **不通过** | `:669-673`（自检 2 `:607-608` 同病），已实测复现 |

---

## 总判定

**有 2 处须先修。**

1. `emission_robustness` 的无条件最大值截尾（`build_charge_timing_comparison.py:766-776`）。
   **处置是 (a)：数字站得住，只改说法与代码，不必重算、不必重生成产物。** 依据是实测的这批数：asap 臂十次 E_total 为 185.67 / 191.53 / 196.83 / 199.88 / 200.89 / 201.23 / 202.36 / 203.80 / 204.45 / **263.68**，run_09 是 5CV/1EV，其余九次是 2–3CV/3EV；任何合理的离群判据都会挑中同一次，所以 `mean_gap_excluding_that_run` / `median_gap_excluding_that_run` 的**取值就是离群规则本该给出的取值**，`summary.json` 与三个产物目录不需要重跑。
   要改的是两件事：代码里把无条件 `max` 换成显式离群判据（判据不成立时返回 `None`）；以及正文措辞——必须写成“剔除 asap 臂排放最高、且为 5 油 1 电离群构型的 run_09（263.68 kg）”这种把识别依据摆出来的说法，并交代这是**单边截尾**（碳感知臂未做同样处理），不能写成“剔除离群点后”了事。
2. `contrast_policy` / `baseline_policy` 缺列时的 `KeyError`（`:669-673` 与 `:607-608`）——不影响任何已落盘数字，但会挡住命令行重建 uniform 日历下的对照。

除这两处外，第 1、2、3、4、6、7、9、10、11 条全部通过：默认口径产物逐位可复现，三条自检真在跑、容差没有被放宽（自检 3 反而是逐位 0 容差），反事实日历的 48 槽布局与图纸逐槽一致、非北京行零改动、可由生成器逐位重建，网格的两条断言覆盖全部格子且实测偏差为 0，三个受保护文件今天没有被动。第 8 条是搜索侧的既有欠账，不污染论文当前数字，建议单独登记。

**结论：`solver/reports/charge_timing_comparison_20260904`、`charge_timing_comparison_v2_20260904`、`charge_timing_grid_20260904` 与三份反事实日历可以据以写论文，产物不需要重跑；唯一的条件是排放稳健性那两个“剔除后”的数字按上面第 1 条改写措辞（数字不变，只补上识别依据并注明是单边截尾）。两处代码修复（第 1 条与追加发现）是下次复用前的事，不阻塞现在动笔。**
