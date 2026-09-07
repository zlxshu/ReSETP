# split 默认口径全批重跑后的重生成手册（顺序执行清单）

**日期**：2026-09-08　**性质**：只写清单，未执行任何一步；写作期间没有跑求解器、没有动
`solver/reports/*_split_20260908/`。

**依据**：`docs/handoff/rerun_inventory_split_20260908.md`（展品→生成器→目录→命令）与
`solver/reports/rerun_split_20260908/README.md`（清单怎么造的、怎么跑、采样深度）。
本手册只补它们没写的那一段：**跑完之后照什么顺序做什么**。

**前提**：`solver/reports/rerun_split_20260908/launcher.log` 里已出现「全批结束」，
且主清单 201 条 ＋ 动力配置补充清单 112 条都跑完。没跑完不要开始第 1 步。

**执行前先把第 6 节的三条来源更正读一遍**——其中两条会改变你对某些数字该去哪里取的判断。

---

## 第 0 步：只读快照（不改任何东西）

```zsh
cd /Volumes/移动硬盘（512G）/ReSETP
D=solver/reports/rerun_split_20260908
grep -c '启动' $D/launcher.log; grep -c '完成' $D/launcher.log; grep -c 'exit=0' $D/launcher.log
grep -v 'exit=0' $D/launcher.log | grep '完成'          # 非零退出码的行，应为空
ls -la solver/reports | grep -E '_split_20260908|_20260906|_20260907|_20260904'
```

`run_one.sh` 对已有 `best_solution.json` 的目录会打印「跳过」并 `exit 0`，
所以**只看 exit=0 不足以证明跑完**；真正的完整性闸门是第 2 步的「run 数与原目录一致」。

---

## 第 1 步：目录换名（有严格先后顺序，不能打乱）

**为什么必须换名而不是改脚本路径**：`build_charging_windows_table.py`（ARMS 常量）、
`diagnose_charging_windows_20260906.py`（ARMS 常量）、`probe_combo_margin_20260908.py`
（ROOTS 常量）都把批次目录**写死在源码里、没有命令行开关**；
`build_policy_table.py` 的 ROWS 十行同样写死。换名是让这些脚本原封不动地读到新数据的唯一办法。

### 1.1 先把全部原目录改成 `_parallel_pre_split_20260908`（一次做完，不要边改边换）

```zsh
cd /Volumes/移动硬盘（512G）/ReSETP/solver/reports
mv grid2x2_v3_20260906              grid2x2_v3_20260906_parallel_pre_split_20260908
mv carbon_price_sweep_v3_20260906   carbon_price_sweep_v3_20260906_parallel_pre_split_20260908
mv charging_arrangements_20260906   charging_arrangements_20260906_parallel_pre_split_20260908
mv ablation_v6_20260906             ablation_v6_20260906_parallel_pre_split_20260908
mv fleet_composition_formal_v3_20260904 fleet_composition_formal_v3_20260904_parallel_pre_split_20260908
```

`carbon_price_sweep_v2_20260906` **不动**（它是 v3 那 7 档符号链接的落点，本次重跑后
新的 v3 目录里 22 档全是真跑、不再有链接，但归档下来的旧 v3 仍要能指向 v2）。

`policy_combos_20260907` **整个目录不动**，只换其中 4 个子目录（见 1.4）。

### 1.2 立刻修归档 ablation 的两条符号链接（这一步漏掉会静默串数据）

`ablation_v6_20260906/MT-HGS`、`MTC-HGS` 是**相对符号链接**，指向
`../grid2x2_v3_20260906/beijing/P=0.2/{MT-HGS,MTC-HGS}`。
1.1 之后它们暂时断了；等 1.3 把新数据搬进 `grid2x2_v3_20260906` 这个名字，
**归档目录里的链接就会重新连上，但连的是新数据**——归档就不再是历史快照了。
所以必须在 1.3 之前把归档里的链接改成指向归档：

```zsh
cd /Volumes/移动硬盘（512G）/ReSETP/solver/reports/ablation_v6_20260906_parallel_pre_split_20260908
rm MT-HGS MTC-HGS
ln -s ../grid2x2_v3_20260906_parallel_pre_split_20260908/beijing/P=0.2/MT-HGS  MT-HGS
ln -s ../grid2x2_v3_20260906_parallel_pre_split_20260908/beijing/P=0.2/MTC-HGS MTC-HGS
ls -la MT-HGS MTC-HGS          # 核对：箭头右边必须带 _parallel_pre_split_20260908
```

### 1.3 再把新目录改成原名

```zsh
cd /Volumes/移动硬盘（512G）/ReSETP/solver/reports
mv grid2x2_v3_20260906_split_20260908              grid2x2_v3_20260906
mv carbon_price_sweep_v3_20260906_split_20260908   carbon_price_sweep_v3_20260906
mv charging_arrangements_20260906_split_20260908   charging_arrangements_20260906
mv ablation_v6_20260906_split_20260908             ablation_v6_20260906
mv fleet_composition_formal_v3_20260904_split_20260908 fleet_composition_formal_v3_20260904
```

### 1.4 policy_combos：逐子目录换，不要整目录换

`policy_combos_20260907/` 磁盘上有 10 个情形子目录，本次**只重跑了 4 个**
（另有 2 个是本批新造的情形，原目录里根本没有）。整目录换名会把 5 个未重跑的情形一起搬走。

| 子目录 | 处置 |
|---|---|
| `green_window` | 换（原→`_parallel_pre_split_20260908`，新→原名） |
| `quota200` | 换 |
| `subsidy_alone` | 换 |
| `midday_subsidy` | 换。**归档里有 10 次、新目录只有 3 次，这是对的**：本次按 2026-09-08 用户裁定只跑 run_01–03。**绝不许从归档拷 run_04–10 补进新目录**——新旧口径混在一个目录里是本步唯一剩下的静默污染路径 |
| `midday_subsidy24_P1.2` | **新增**，直接搬进来，无原目录可归档 |
| `midday_subsidy47_P0.6` | **新增**，同上 |
| `midday_nofee` | **保留不动** |
| `midday_subsidy_lunch1114` | **保留不动** |
| `midday_subsidy_nofee` | **保留不动** |
| `nofee_beijing` | **保留不动** |
| `subsidy_nofee_beijing` | **保留不动** |

```zsh
cd /Volumes/移动硬盘（512G）/ReSETP/solver/reports
OLD=policy_combos_20260907
NEW=policy_combos_20260907_split_20260908
for s in green_window quota200 subsidy_alone midday_subsidy; do
  mv "$OLD/$s" "$OLD/${s}_parallel_pre_split_20260908"
  mv "$NEW/$s" "$OLD/$s"
done
for s in midday_subsidy24_P1.2 midday_subsidy47_P0.6; do
  mv "$NEW/$s" "$OLD/$s"
done
rmdir "$NEW" 2>/dev/null || ls -la "$NEW"    # 应该已空；不空就先看剩了什么再决定
ls -la "$OLD"
```

### 1.5 在新的 ablation 目录里补建两条符号链接（新批只跑了 M 臂）

本批 `ablation_v6_20260906_split_20260908` 的清单里**只有 M-HGS 10 条**，
没有 MT/MTC——因为这两臂本来就是指向 grid2x2 的链接、不另跑。换名后新目录里没有这两个名字，
必须补建，否则表 9 的三行只剩一行：

```zsh
cd /Volumes/移动硬盘（512G）/ReSETP/solver/reports/ablation_v6_20260906
ln -s ../grid2x2_v3_20260906/beijing/P=0.2/MT-HGS  MT-HGS
ln -s ../grid2x2_v3_20260906/beijing/P=0.2/MTC-HGS MTC-HGS
ls -la MT-HGS MTC-HGS && ls MT-HGS | head        # 箭头右边不带后缀 = 指向新数据，正确
```

### 1.6 把批次自带的说明与汇总器搬进新目录

新目录是 `run_one.sh` 一条条建出来的，只有 `run_*/`，没有 `README.md`／`joblist.txt`／
`summarise.py`。其中 **`summarise.py` 是必须搬的**——它用
`ROOT = Path(__file__).resolve().parent`，必须住在它要汇总的那个目录里，
而正文的翻转碳价 1.24／1.52 就出自它写的 `summary.md`（见第 6 节更正二）。

```zsh
cd /Volumes/移动硬盘（512G）/ReSETP/solver/reports
cp carbon_price_sweep_v3_20260906_parallel_pre_split_20260908/summarise.py carbon_price_sweep_v3_20260906/
# README/joblist 按需拷贝，供后人追溯；旧的 summary.json / summary.md 不要拷，第 3 步会重生成
```

---

## 第 2 步：验收核对

### 2.1 逐目录期望 run 数（换名后的新目录）

| 目录 | 期望 run 数 | 结构 |
|---|---:|---|
| `grid2x2_v3_20260906` | 80 | `{beijing,midday}/P={0.2,1.0}/{MT-HGS,MTC-HGS}/run_01..10` |
| `carbon_price_sweep_v3_20260906` | 66 | 22 个 `P=*/run_*`，每档 3 |
| `charging_arrangements_20260906` | 20 | `{cost_min,carbon_min}/run_01..10` |
| `ablation_v6_20260906/M-HGS` | 10 | 只查 M 臂；MT/MTC 是链接，计入 grid2x2 |
| `policy_combos_20260907` 的 6 个重跑子目录 | 3/3/10/3/3/3 | `green_window` 3、`quota200` 3、`subsidy_alone` **10**、`midday_subsidy` 3、两个新情形各 3 |
| `fleet_composition_formal_v3_20260904` | 112 | 7 档 × 各档分法，最优与次优分法各补 run_2/run_3 |

**两个已知会假报错的坑，核对时先避开**：

- `carbon_price_sweep_v3`：**旧目录**是 15 个真跑目录 ＋ 7 个指向 v2 的符号链接
  （沿链接可达 66 个 run），**新目录**是 22 个真目录 66 个 run。
  用 `find -type d` 不跟随链接去比，会得到 45 vs 66，看起来像失败。
  正确的判据是「22 档 × 3 ＝ 66」；要清点旧目录请用 `find -L` 跟随链接。
- `ablation_v6`：旧目录沿链接可达 30 个 run，新目录在 1.5 补链接之前只有 10 个。
  **先做 1.5，再核对**；或者只核 `M-HGS` 的 10 vs 10。

### 2.2 一次性核对脚本

字段路径已在源码与已落盘产物上逐个核过：
`metadata.json` → 顶层 `status`、顶层 `public_station_candidate_mode`、
`route_engine_wiring.first_trip_window`；
`best_solution.json` → `evaluation.feasible`、`individual.unserved_customers`。
其中 `public_station_candidate_mode` 是本次口径的**唯一判别字段**——
2026-09-08 以前的所有批次 metadata 里根本没有这个键（已在
`grid2x2_v3_20260906/beijing/P=0.2/MTC-HGS/run_01/metadata.json` 上实测确认），
所以「有这个键且等于 split」＝确实是新口径产物。

把下面这段存成 `solver/reports/rerun_split_20260908/verify_after_rename.py` 再跑（脚本本身只打印、不写任何产物）。
**这个文件到执行这一步的时候再建**——写手册这轮没有建，因为全批还在跑，那个目录当时不许动：

```python
#!/usr/bin/env python3
"""换名后的一次性验收：run 数、status、窗口口径、候选模式、可行性、未服务客户。"""
import json, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
EXPECT = {
    "grid2x2_v3_20260906": 80,
    "carbon_price_sweep_v3_20260906": 66,
    "charging_arrangements_20260906": 20,
    "ablation_v6_20260906/M-HGS": 10,
    "policy_combos_20260907/green_window": 3,
    "policy_combos_20260907/quota200": 3,
    "policy_combos_20260907/subsidy_alone": 10,
    "policy_combos_20260907/midday_subsidy": 3,
    "policy_combos_20260907/midday_subsidy24_P1.2": 3,
    "policy_combos_20260907/midday_subsidy47_P0.6": 3,
    "fleet_composition_formal_v3_20260904": 112,
}
# 动力配置批的参数集本来就与其余批不同（无 --stop-after-nonimproving-rounds、
# 无 --tariff-calendar-authority），只查窗口与候选模式，不做跨批参数一致性断言。
bad, total = [], 0
for rel, n_exp in EXPECT.items():
    base = REPO / "solver/reports" / rel
    # 注意：pathlib 的 rglob **不会**下钻符号链接目录（3.13 以前无 recurse_symlinks）。
    # 上表列的都是换名后的真实目录，所以够用；若要核归档里那些带链接的旧目录，
    # 改用 `find -L <dir> -name best_solution.json | wc -l`。
    sols = sorted(base.rglob("best_solution.json"))
    if len(sols) != n_exp:
        bad.append(f"[run数] {rel}: {len(sols)} != {n_exp}")
    for sp in sols:
        total += 1
        run = sp.parent
        try:
            md = json.loads((run / "metadata.json").read_text())
            sol = json.loads(sp.read_text())
        except Exception as e:
            bad.append(f"[读不了] {run.relative_to(REPO)}: {e}"); continue
        if md.get("status") != "COMPLETE":
            bad.append(f"[status] {run.relative_to(REPO)}: {md.get('status')!r}")
        if md.get("public_station_candidate_mode") != "split":
            bad.append(f"[候选模式] {run.relative_to(REPO)}: "
                       f"{md.get('public_station_candidate_mode')!r}（缺键＝旧口径遗留）")
        w = (md.get("route_engine_wiring") or {}).get("first_trip_window")
        if w != "prev_return":
            bad.append(f"[窗口] {run.relative_to(REPO)}: {w!r}")
        if sol.get("evaluation", {}).get("feasible") is not True:
            bad.append(f"[不可行] {run.relative_to(REPO)}")
        uns = sol.get("individual", {}).get("unserved_customers")
        if uns:
            bad.append(f"[未服务] {run.relative_to(REPO)}: {len(uns)} 个")
print(f"共核 {total} 个 run；问题 {len(bad)} 条")
for b in bad:
    print(" ", b)
sys.exit(1 if bad else 0)
```

```zsh
cd /Volumes/移动硬盘（512G）/ReSETP
python3 solver/reports/rerun_split_20260908/verify_after_rename.py
```

**有任何一条不过就停下**，不要带着问题往第 3 步走。
特别是「run 数不足」——`run_one.sh` 幂等跳过的是有 `best_solution.json` 的目录，
中途崩掉的跑会留下一个没有解的目录，只有 run 数这条查得出来，status 那条查不出来
（那个目录压根进不了循环）。

---

## 第 3 步：生成器执行顺序与命令

**统一前提**：

```zsh
cd /Volumes/移动硬盘（512G）/ReSETP
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src'
PY=.public-hgs-venv/bin/python3        # 画图脚本必须用它（matplotlib 3.11.1 + fontTools 都在里面）
```

出表脚本用系统 `python3` 也能跑，但**统一都用 `$PY`** 更省事，不会出现某一步缺包。

### 3.1 碳价扫描汇总（必须最先，后面几处数字都引它）

```zsh
$PY solver/reports/carbon_price_sweep_v3_20260906/summarise.py
```

产出该目录下的 `summary.json` / `summary.md`。
**翻转碳价（正文 1.24／1.52）就在 `summary.md` 的「翻转点」那一行**，
去那里取新值，不要去别处。

### 3.2 表 11 不同充电安排（必须先于表 12）

```zsh
$PY solver/scripts/build_charging_arrangements_table.py
# → docs/paper_v2/generated_tables/carbon_charging_table.tex
```

默认四列目录：`grid2x2_v3_20260906/beijing/P=0.2/MT-HGS`（即充）、
`charging_arrangements_20260906/cost_min`、`.../carbon_min`、
`grid2x2_v3_20260906/beijing/P=0.2/MTC-HGS`。换名后自动指到新数据，**不要加任何路径参数**。

这个脚本自带四道免费闸门，报错就是真出事，不许用 `--skip-policy-check` 绕：
逐 run 查 `status`、查实际充电时刻策略与该列要求一致、查解可行、
查四列之间的批次口径 `shared` 完全一致。

同时把它 stderr／stdout 打印的每列均值、车队构型计数抄下来——第 4 步 4.4.1 那几个数要用。

### 3.3 表 12 各补电窗口

```zsh
$PY solver/scripts/build_charging_windows_table.py
# → docs/paper_v2/generated_tables/charging_windows_table.tex
```

ARMS 写死同样四个目录、没有路径开关。脚本内有断言：按充电会话重算出来的
充电成本与电动车充电排放，必须与该 run 落盘的 `cost_elec` / `E_ev_indirect` 逐位相符
（1e-6 相对容差）。断言炸了说明换名或重跑本身不一致，**回第 1、2 步查，不要改脚本容差**。

它的 stderr 会逐臂打印三个窗口的开始时刻／成本／碳排，第 4 步 4.4.2 的窗口级数字从这里取。

### 3.4 四格对照表（当前正文没有引用，可跳）

```zsh
# 只在需要人工比对四格时才跑；tex 里没有 \input{generated_tables/grid2x2_table.tex}
$PY solver/scripts/build_grid2x2_table.py
```

跑不跑都不影响论文编译。`build_policy_table.py` 复用的是同一批数据目录，不是这个脚本的输出。

### 3.5 表 13 政策表

```zsh
$PY solver/scripts/build_policy_table.py
# → docs/paper_v2/generated_tables/policy_table.tex
```

十行数据源写死在 `ROWS`（源码第 116–155 行），换名后自动对上。
**组合行「谷段设在午间＋购置补贴」仍限 `runs=("run_01","run_02","run_03")`**
——这是 2026-09-08 的用户裁定，写在源码第 148–153 行，本次重跑只跑了 3 次，不要改。
聚合口径 `ROW_STATISTIC = "mean"`（不带 `runs=` 的行取该目录下**全部**
`best_solution.json` 的算术均值），所以第 2 步的 run 数核对是这张表正确的前提。

### 3.6 图 6 碳价响应

```zsh
$PY solver/scripts/generate_carbon_price_response_figure.py
# → docs/paper_v2/generated_figures/figure_6_carbon_price_response.pdf
```

数据源 `carbon_price_sweep_v3_20260906`（写死在 `SWEEP`）。
它会先逐档打印「P=… n=… 电动车／燃油车／排放／成本／首趟前谷段占比」，
第 4 步正文里「首趟前补电自 0.7 元/kg 起离开谷段」那句从这份打印里核。

### 3.7 图 4 分时电价与补电窗口（可跳）

```zsh
# 只画电价/碳强度/班次日历，不读任何 run 产物，重跑不影响它
$PY solver/scripts/generate_tariff_carbon_window_figure.py
```

### 3.8 4.4.2 正文数字的诊断脚本

```zsh
$PY solver/scripts/diagnose_charging_windows_20260906.py \
    --out docs/handoff/charging_window_root_cause_20260908.md
```

ARMS 写死同样四个目录。它是正文 4.4.2 里
「每千瓦时多付 0.585 元／少排 0.113 kg」「0.76 元/kg 与 4 元/kg 两个门槛」
「全部电量都在 13:00 也只能再减 15.7 kg（8%）」这几个数的唯一来源。
**输出文件名改成 `_20260908`，不要覆盖 09-06 那份**，两份要能并排对照。
改名的代价：`rerun_inventory_split_20260908.md` 里「正文里手工引用、不经生成器的数字」那张表记的还是 09-06 的旧路径，本步与 3.9 做完后要回去把来源列改成新路径。

### 3.9 公共站补电上限探针（0.67／0.45／1.48 三个数）

```zsh
$PY solver/scripts/probe_station_topup_20260907.py \
    --out solver/reports/probe_station_topup_20260908
```

`TARGETS` 写死 `grid2x2_v3_20260906` 四格 ＋ `policy_combos_20260907/midday_subsidy`（取前 3 次），
换名后自动指向新数据。产出 `per_kwh_gap.csv` / `summary.csv` / `trip_upper_bound.csv`。
**取数前先读第 6 节更正三**——这三个数现在对不上已落盘的探针输出，重跑后要重新导出并说明取的是哪一行。

### 3.10 组合边际探针（补贴 46.97 元/日）

```zsh
$PY solver/scripts/probe_combo_margin_20260908.py
# → solver/reports/probe_combo_margin_20260908/margin_table.csv, config_detail.csv
```

`ROOTS` 写死 `grid2x2_v3_20260906`、`carbon_price_sweep_v3_20260906`、
`policy_combos_20260907`、`charging_arrangements_20260906` 四个批次，全部换名后自动更新。
两个新情形（`midday_subsidy24_P1.2`、`midday_subsidy47_P0.6`）的落点也在
`policy_combos_20260907` 下，会一并进池。
它会覆盖同名输出目录，需要留旧版就先改名备份。

### 3.11 表 7 仿真实验最终路径表

```zsh
$PY solver/scripts/generate_final_solution_table.py \
    solver/reports/ablation_v6_20260906/MTC-HGS/run_XX 0.20
# → docs/paper_v2/generated_tables/final_solution_trip_rows.tex
```

`argv[1]` 是 run 目录、`argv[2]` 是碳价（默认 0.20）。
**`run_XX` 要人工选**：取 `ablation_v6_20260906/MTC-HGS`（＝ grid2x2 beijing/P=0.2/MTC-HGS）
十次里 `evaluation.total_cost` 最低的那一次。选法：

```zsh
$PY - <<'PY'
import json, glob
rows = [(json.load(open(p))["evaluation"]["total_cost"], p)
        for p in glob.glob("solver/reports/ablation_v6_20260906/MTC-HGS/run_*/best_solution.json")]
for c, p in sorted(rows): print(f"{c:10.2f}  {p}")
PY
```

注意脚本的默认值是 `ablation_reseed_20260901/MTC-HGS/run_1`（09-01 的旧批），
**必须显式传参**，不能靠默认。

### 3.12 表 9 消融表（脚本产出的是散行，tex 里是硬编码，须人工搬）

```zsh
TABLE8_BATCH=solver/reports/ablation_v6_20260906 \
  $PY solver/scripts/backfill_table8.py
# → docs/paper_v2/generated_tables/table8_rows.tex
```

`TABLE8_BATCH` **必须显式给**：脚本默认值是 `ablation_formal_10x_20260902`（陈的旧批）。

**前置：第 1.5 步的两条符号链接必须已经建好**。MT／MTC 两臂是靠链接读到 grid2x2 的数据的，跳过 1.5 直接跑这一步，拿到的是缺两行的表或一个不好读的报错。

**这一步和别的都不一样**：`paper_main.tex` 里**没有** `\input{generated_tables/table8_rows.tex}`
（全文 `\input`／`\includegraphics` 已逐条核过），表 9 的三行数字是**硬写在 tex 第 1066–1068 行**的。
所以脚本产出的行要**人工抄进 tex**，并且第 1073–1093 段依赖这三行的整段论述也要重写
（见第 4 步表内 §4.2.2 那 13 条）。

另注：本次重跑前 `table8_rows.tex` 的内容已经是 `M 2704.00 / MT 2518.13 / MTC 2504.97`，
而 tex 里还是旧批的 `2704.00 / 2657.41 / 2605.70`——**回填在重跑之前就已经欠着一轮了**。

### 3.13 表 10 动力配置七档（没有生成器，须按正文口径自己聚合）

全仓 `solver/scripts` 与 `docs` 里**没有任何脚本消费 `fleet_composition_formal_v3_20260904`**
（已 grep 确认），表 10 的 7 行也是硬写在 tex 第 1118–1124 行。聚合口径以正文自述为准
（`paper_main.tex` 第 1105–1106 行）：「各档给定的车辆在两个车场之间的**全部分配方式均予枚举**，
其中**成本最低的分配方式独立运行三次，取其最优配送方案**」。即：

1. 每档（`0-6` … `6-0`）下遍历全部分法目录；
2. 每个分法取其 `run_1`（基础一次）的 `total_cost`，选出该档最低的那个分法；
3. 在该分法下取 `run_1..run_3` 中 `total_cost` 最低的那一次，作为该档入表的方案；
4. 从它的 `evaluation.breakdown` 取 `cost_fix / cost_km / cost_elec / cost_fuel /
   cost_carbon / E_total` 与 `total_cost` 七列。

```zsh
$PY - <<'PY'
import json, glob, os
base = "solver/reports/fleet_composition_formal_v3_20260904"
KEYS = ["cost_fix","cost_km","cost_elec","cost_fuel","cost_carbon","E_total"]
for lvl in ["6-0","5-1","4-2","3-3","2-4","1-5","0-6"]:
    splits = sorted(d for d in glob.glob(f"{base}/{lvl}/*") if os.path.isdir(d))
    scored = []
    for s in splits:
        p = f"{s}/run_1/best_solution.json"
        if os.path.exists(p):
            scored.append((json.load(open(p))["evaluation"]["total_cost"], s))
    if not scored: print(lvl, "无数据"); continue
    _, best_split = min(scored)
    reps = [(json.load(open(p))["evaluation"], p)
            for p in sorted(glob.glob(f"{best_split}/run_*/best_solution.json"))]
    ev, p = min(reps, key=lambda t: t[0]["total_cost"])
    b = ev["breakdown"]
    print(f"{lvl} 分法={os.path.basename(best_split)} 取自={os.path.basename(os.path.dirname(p))} "
          + " ".join(f"{k}={b[k]:.2f}" for k in KEYS) + f" total={ev['total_cost']:.2f}")
PY
```

**注意口径差异（是差异不是笔误）**：这一批的参数集比其余批旧，原批没有
`--first-trip-window` / `--stop-after-nonimproving-rounds` / `--tariff-calendar-authority`
三个开关；本次补充清单只补了 `--first-trip-window prev_return`，另两项没补。
写进论文时表 10 与表 9／表 11 严格说不是同一套停止规则，第 5 步之后要向用户点明。

### 3.14 图 7 配送路径示意图（人工复核，不自动重生成）

```zsh
$PY solver/scripts/generate_route_schematic_figure.py
```

它只读写死的示意几何 `solver/scripts/assets_route_schematic_geometry.json`，不读 run 产物。
**若表 14（不同配送模式）后续重跑导致路线变了，这张图要人工改几何**，脚本不会自己跟。
本次重跑不含表 14，暂时不动。

### 3.15 本次不涉及的生成器（写明原因，免得后人再查一遍）

| 展品 | 为什么不跑 |
|---|---|
| 表 4 公共站信息 | 只读算例 `nodes.csv`，不读 run 产物 |
| 图 1 算法流程图、图 5 机理图 | TikZ 手绘，无数据 |
| 图 2 逐时电网碳强度 | 画算例日历；生成器脚本在全仓 `*.py` 里 0 命中 |
| 表 8、图 3（28 个公开算例／PR17B 收敛） | 目标函数是纯行驶距离、不含充电，本次修复层动不了；且该批没有 joblist／launcher.log，命令无从复原 |
| 表 14／表 15／表 16（配送模式、成本分摊） | 数据目录已不在磁盘上 或 依赖已退役算例 PRDFIX，须用户先裁定 |
| 表 17（动态需求） | 该批 `decision.json` 自判 `MAIN3B_FAILED`／`accepted=false`，重跑与否本身待裁定 |
| `generate_carbon_price_curve_figure.py` | 它的输出 `figure_5_carbon_price_curve.pdf` **不在论文里**（tex 无引用）。翻转碳价请走 3.1 的 `summarise.py`，见第 6 节更正二 |

---

## 第 4 步：正文内联数字核对清单

下表是 **tex 里来自跑批、但不经生成器落地**（即必须人工改）的每一个数字。
行号以本次改动后的 `paper_main.tex` 为准。「新值」一列留空，回填时逐条填。

摘要（第 98 行）与引言（112–164 行）**没有**来自本批跑数的数字——
唯一的量化说法是「28 个标准算例」，那批本次不重跑。逐句核过，此处无条目。

### §4.1 最终解分析（数据源：3.11 选定的那个 MTC-HGS run；生成器只出表体，正文全靠手改）

| 行号 | 现值 | 来源（字段／脚本输出） | 新值（待填） |
|---|---|---|---|
| 926 | 50 个客户、13264 kg、总成本 2622.86 元 | `best_solution.json` → `evaluation.total_cost`；客户数／需求量由 3.11 脚本打印 | |
| 927 | 启动 1150.00（43.85%）、行驶 932.78（35.56%） | `evaluation.breakdown.cost_fix` / `cost_km` 及占比 | |
| 928 | 油耗 310.24（11.83%）、充电 191.54（7.30%）、碳 38.30（1.46%） | `breakdown.cost_fuel` / `cost_elec` / `cost_carbon` | |
| 929 | 两项合计 79.41% | 由 927 两项占比相加 | |
| 931 | 碳成本占比 1.46% | 同 928 末项 | |
| 932–934 | 2 油 3 电共 5 辆、15 趟、车均 3.00 趟、2/3/3/3/4 趟分布、油 7 电 8 | `individual.duties` 与 `trip_clock` 计数（3.11 脚本打印趟数） | |
| 936 | 电动车 752.97 km、占 70.63% | 3.11 表体的距离列合计 | |
| 937–938 | 总排放 191.50，油 109.57（57.22%）、电 81.92（42.78%） | `breakdown.E_total` / `E_cv_direct` / `E_ev_indirect` | |
| 939–940 | 0.350 与 0.109 kgCO₂e/km、降 68.86% | 由 937/936 两组数相除 | |
| 942–943 | 均 71.07 km／1.19 h；最长 147.15 km／2.25 h；最短 27.00 km／0.57 h | 3.11 表体的距离与时间列 | |
| 944–945 | 均装载率 51.57%；12 趟 >50%；2 趟低（28.01%、32.05%） | 3.11 表体的装载率列 | |

### §4.2.2 模型实验（消融）——**本次改动量最大的一块**

三行表体（1066–1068）硬编码，须从 3.12 的 `table8_rows.tex` 人工搬；
其余每一句都建在这三行上。

| 行号 | 现值 | 来源 | 新值（待填） |
|---|---|---|---|
| 1066 | M-HGS 2704.00 / 2717.72 / 0.51 | `backfill_table8.py`（`TABLE8_BATCH=ablation_v6_20260906`）→ `table8_rows.tex` 第 1 行 | |
| 1067 | MT-HGS 2657.41 / 2672.82 / 0.58 | 同上第 2 行 | |
| 1068 | MTC-HGS 2605.70 / 2634.90 / 1.12 | 同上第 3 行 | |
| 1076 | 三算法全部运行完成 50 客户、13264 kg | 第 2 步验收脚本的 `unserved_customers==[]` | |
| 1081–1082 | M-HGS 最优派 6 油、15 趟、排放 319.24 全为直接排放 | `ablation_v6_20260906/M-HGS` 最优 run 的 `breakdown` | |
| 1083–1085 | MT 派 2 油 3 电、排放降至 173.44（−45.67%）、成本 2704.00→2657.41（−1.72%） | M／MT 两臂最优 run | |
| 1086 | MTC 充电成本 184.29，较 MT 的 227.16 少 42.87 | 两臂最优 run 的 `cost_elec` | |
| 1087 | 2657.41→2605.70（−1.91%）；十次均值降 1.42%；平均排放 194.94 与 194.96 | 两臂十次的 `total_cost` / `E_total` 均值 | |
| 1088 | MTC 充电排放 74.39 高于 MT 的 56.60 | 两臂最优 run 的 `E_ev_indirect` | |
| 1089 | 谷段 00:00–07:00 碳强度 0.5849–0.6439 | 算例日历（不随重跑变） | |
| 1090 | 碳成本占比 1.48% | MTC 最优 run 的 `cost_carbon/total_cost` | |
| 1092 | Gap 0.51% / 0.58% / 1.12% | 同 1066–1068 第 4 列 | |

### §4.3 不同动力配置（表体 1118–1124 与下文全部硬编码，源见 3.13）

| 行号 | 现值 | 来源 | 新值（待填） |
|---|---|---|---|
| 1118–1124 | 七行 × 七列（6/0 的 2704.00 … 0/6 的 2738.75） | 3.13 的聚合脚本输出 | |
| 1132 | 启动 1020.00→1620.00，每换 1 辆 +100.00 | 表体 `cost_fix` 列 | |
| 1133 | 充电 0→217.97；行驶 716.30→881.85 | `cost_elec` / `cost_km` 列 | |
| 1134 | 油耗 903.86→0；碳成本 63.85→18.93 | `cost_fuel` / `cost_carbon` 列 | |
| 1136 | 最优 3 油 3 电 2633.94 元 | 表体 `total_cost` 最小行 | |
| 1137 | 纯燃油贵 70.06 元（2.66%） | 6/0 − 最优 | |
| 1139 | 纯电贵 104.81 元（3.98%） | 0/6 − 最优 | |
| 1140 | 4 油 2 电 2637.94，与最优差 4.00 元 | 表体两行相减 | |
| 1143 | 碳排 319.24→94.63，降 70.36% | `E_total` 列 | |

### §4.4.1 不同充电安排（表体走 3.2 自动更新，正文四条全靠手改）

| 行号 | 现值 | 来源 | 新值（待填） |
|---|---|---|---|
| 1174 | 只看电价较即充省 39.59 元（1.48%） | 3.2 打印的各列 `total_cost` 均值之差 | |
| 1175 | 油车直排 −17.18、电车充电排放 +23.39、净增 6.21 kg | 各列 `E_cv_direct` / `E_ev_indirect` / `E_total` 均值 | |
| 1176 | 只看碳减 8.69 kg（4.46%），总成本亦减 14.11 元 | 同上 | |
| 1177 | 两信号与只看电价差 1.67 元、充电排放差 0.74 kg；碳成本占 1.48% | 同上 | |
| 1178–1179 | 限 2 油 3 电构型：只看电价充电成本 −44.76、碳 +20.44；只看碳 −15.77、碳 −4.06 | 3.2 打印的按构型分组均值（脚本会打印构型计数） | |

### §4.4.2 电价与碳强度时段（正文全部手工数字）

| 行号 | 现值 | 来源 | 新值（待填） |
|---|---|---|---|
| 1155 | 碳强度 0.154–0.644、峰谷比 4.18 | 算例日历，不随重跑变 | |
| 1210 | 首趟前窗口约占全日充电量的 40% | 3.8 诊断脚本的窗口电量占比 | |
| 1211 | 午休窗口仅 35% 可延至 13:00 | 3.8 同上 | |
| 1213 | 每 kWh 多付 0.585 元、少排 0.113 kg；17:00 前回场门槛 0.76 元/kg | 3.8 诊断脚本 | |
| 1214 | 17:00 后回场门槛 4 元/kg 以上 | 3.8 同上 | |
| 1215 | 首趟前窗口充电成本 −24.89 元、碳排 +24.25 kg | 3.3 `build_charging_windows_table.py` 的 stderr 窗口行 | |
| 1218 | 全部电量都在 13:00 也只能再减 15.7 kg（8%） | 3.8 诊断脚本 | |
| 1219 | 公共站多付 0.67 元/kWh 换 0.45 kg，平衡碳价约 1.48 元/kg | 3.9 探针 `per_kwh_gap.csv`——**见第 6 节更正三，来源待核** | |
| 1220 | 充电排放占总排放 24.7%；3 油与 4 油差 4.00 元 | 前者取 MTC 最优 run 的 `E_ev_indirect/E_total`；后者同 §4.3 第 1140 行 | |

### §4.4.3 碳减排政策（表体走 3.5 自动更新，正文手改）

| 行号 | 现值 | 来源 | 新值（待填） | n=10 敏感 |
|---|---|---|---|---|
| 1243 | 五种情形 3 次、其余 10 次 | 与 `build_policy_table.py` 的 `runs=` 及各目录实际 run 数一致，须逐行复核这句话 | | |
| 1250 | 午间谷价补贴财政每日支出 45.90 元 | `policy_table.tex` 的 `green_window` 行 | | |
| 1251 | 碳价 1.0 时 10 次中 5 次改派 4 辆电动车 | `grid2x2_v3_20260906/beijing/P=1.0/MTC-HGS` 十次的车队构型计数 | | |
| 1252 | 碳配额只使碳成本平移约 40 元 | `quota200` 行与基准行的 `cost_carbon` 之差 | | |
| 1263 | 1.5 元/kg 以上转纯电动 | 3.6 图 6 的逐档打印 | | |
| 1264 | 翻转点 1.24 与 1.52 元/kg | **3.1 `summary.md` 的「翻转点」行**（不是曲线图脚本，见第 6 节更正二） | | |
| 1265 | 首趟前补电自 0.7 元/kg 起离开谷段 | 3.6 逐档打印的「首趟前谷段占比」 | | |
| 1267 | 午谷＋碳价 1.0：碳排 −39.28%、成本 +100.00 元 | `policy_table.tex` 组合行减基准行 | | |
| 1268 | 午谷＋补贴：碳排 −41.04%、成本 −3.81%，3 次均派 1 油 5 电 | 同上 | | **是** |
| 1269 | 碳价路径企业多付 100.00、政府碳收入 +79.39 | 同上两行的 `cost_carbon` | | |
| 1270 | 补贴路径企业少付 100.41、政府补贴 120.00、每减 1 kg 花 1.50 元 | 同上 | | **是** |
| 1273 | 碳价须达 1.24 元/kg 以上 | 同 1264 | | |

「n=10 敏感」列的意思：`docs/handoff/CURRENT_PROJECT_CONTEXT.md` 顶部 09-08 00:30 那条记着，
`midday_subsidy` 这一行补到 10 次后是 −104.99 元 / −61.44 kg，
即 3 次的 −80 kg 会坍成 −61 kg。用户 09-08 已裁定这一行按 3 次入表，本次也只跑了 3 次；
标注在这里只是让回填的人知道这两处数字的稳定性有已知记录，不是重开这道题。

### §结语（1479–1493 行）

| 行号 | 现值 | 来源 | 新值（待填） |
|---|---|---|---|
| 1479–1481 | 28 算例均值 8656.73、27 题最低、1 题刷新 | `public28_formal_20260830`，本次**不重跑**，不动 | 不变 |
| 1484 | 碳排放累计下降 40.96%、总成本同步下降 3.64% | 由 §4.2.2 的 M 臂与 MTC 臂最优 run 相除得出 | |
| 1488 | 1.24 元/kg 时 2 油 3 电→1 油 5 电；1.52 转纯电 | 同 1264（3.1 `summary.md`） | |
| 1489 | 午谷＋补贴：碳排 −41.04%、成本 −3.81% | 同 1268（**同一对数字，两处要一起改**） | |
| 1490 | 与午谷＋碳价 1.00 的减排幅度相当 | 同 1267 | |
| 1491 | 两企业节约率 20.57% 与 7.49% | 表 15 协作分摊，本次**不重跑**，不动 | 不变 |
| 1492 | 动态 60 客户 16111 kg | 表 17，本次**不重跑**，不动 | 不变 |

---

## 第 5 步：编译与渲染

```zsh
cd /Volumes/移动硬盘（512G）/ReSETP/docs/paper_v2
xelatex -interaction=nonstopmode -halt-on-error paper_main.tex
xelatex -interaction=nonstopmode -halt-on-error paper_main.tex
grep -c '^!' paper_main.log            # 须为 0
grep -c 'Overfull' paper_main.log      # 须为 0
grep -ci 'undefined' paper_main.log    # 须为 0
grep -o 'Output written on paper_main.pdf ([0-9]* pages' paper_main.log
```

`Underfull \hbox` 目前有 4 处（第 752–800、818–823、987–1021、1549–1550 行段落），
是既有状态、不是本轮引入，回填后如果条数变多再去看新增的那几处。

渲染目视（改了表就必须看，数字对了版式也可能炸）：

```zsh
pdftotext paper_main.pdf - | grep -n "分担补电"      # 算法步骤四那句在不在
# 逐张看表 7 / 9 / 10 / 11 / 12 / 13 与图 6 有没有串列、跑版、数字被截断
```

最后把变化写回四处（本手册不做，留给回填那轮）：
`docs/handoff/CURRENT_PROJECT_CONTEXT.md` 当前状态、
只有用户决定变了才动 `docs/paper_gci_dmm_vrp_20260804/pending_decisions.md`、
`HANDOFF.md` 文末变更日志、`docs/handoff/memory/MEMORY.md` 证据入口。

---

## 第 6 步（其实是第 0 步）：写这份手册时发现的三条来源更正

**这三条都不是本手册的推测，是把盘点文档与源码／落盘产物对照后的实测差异。**

### 更正一：表 13 碳价两行不走方案池

`docs/handoff/rerun_inventory_split_20260908.md` §2 写着碳价扫描两行
「把 `carbon_price_sweep_v3_20260906/` 下全部 66 个 `best_solution.json`
按该行目标碳价重新核算总成本后取最低者（`CARBON_SWEEP_POOL_DIR`）」。

**源码不是这样**：`solver/scripts/build_policy_table.py` 第 84 行
`CARBON_ROWS_FROM_POOL = False`（注释写明 2026-09-06 改的口径：
「碳价类行不再走方案池，各自在自己目录里取均值」），
且第 85 行的 `CARBON_SWEEP_POOL_DIR` 指的还是 **v2** 不是 v3。
即碳价 0.075 与 1.5 两行现在与其他行同口径——各自目录内取均值。
**照源码走，别照盘点文档那段走。**

### 更正二：翻转碳价 1.24／1.52 出自 summarise.py，不是曲线图脚本

盘点文档把 1.24／1.52 记在
`generate_carbon_price_curve_figure.py` / `generate_carbon_price_response_figure.py` 名下。
实际出处是 `solver/reports/carbon_price_sweep_v3_20260906/summary.md` 第 7 行：
「翻转发生在 **1.2415、1.5224、1.8394 元/kg**」，由该目录里的 `summarise.py` 写出。
曲线图脚本的产物 `figure_5_carbon_price_curve.pdf` **在论文里没有被引用**，不必重生成。

**顺带一条要单独修的代码问题**：`generate_carbon_price_curve_figure.py` 第 280 行的
自校常量 `_SUMMARY_MD_EXPECTED_FLIPS = (1.3316, 1.7959)` 与现行 `summary.md`
的 1.2415／1.5224 对不上，是上一版遗留。属于代码整理，不影响本次回填。

### 更正三：0.45 kg 与 1.48 元/kg 目前对不上探针输出

正文第 1219 行写「多支付 0.67 元/kWh 以减少 0.45 kgCO₂e，盈亏平衡约 1.48 元/kgCO₂e」。
在已落盘的 `solver/reports/probe_station_topup_20260907/per_kwh_gap.csv` 里逐行找过，
最接近的一行是（北京日历、`station_hour=15.0`）：
`delta_energy_cost=0.6731570`、`carbon_saved=0.4608`、`breakeven=1.4608442`。
0.67 对得上，**0.4608 四舍五入是 0.46 不是 0.45，1.4608 是 1.46 不是 1.48**；
而 `station_topup_algorithm_design_20260907.md` 第 159 行给的又是另一组
（0.67316 / 0.4892 / **1.376**）。三处互不吻合。

**处置**：这一处标为「来源待核」。第 3.9 步重跑探针后，
必须先说清取的是 `per_kwh_gap.csv` 的哪一行（哪个日历、哪个 `station_hour`），
再据那一行改写第 1219 行，不要沿用旧数字、也不要假设是四舍五入笔误。

---

## 附：本次重跑不覆盖、但正文仍在引用的批次（回填时要向用户点明）

| 展品／数字 | 数据源 | 状态 |
|---|---|---|
| 表 8、图 3、结语 1479–1481 | `public28_formal_20260830` | 不受充电修复层影响，不重跑 |
| 表 14／15／16、结语 1491 | 目录已不在磁盘 或 依赖退役算例 PRDFIX | 须用户裁定 |
| 表 17、结语 1492 | `submission_fallback_20260824/56_dynamic_formal_seed1_single_seed_corrected` | 该目录 `decision.json` 自判 `MAIN3B_FAILED`、`accepted=false`、`run_class=main3b_small_wiring_trial`；**正文现在用的就是这一包被自己判为失败的接线小试**，重跑与否之前这件事本身要先裁定 |
| 表 10 与表 9／11 的停止规则不同源 | `fleet_composition_formal_v3_20260904` 原批无 `--stop-after-nonimproving-rounds` / `--tariff-calendar-authority`，本次补充清单只补了 `--first-trip-window prev_return` | 口径差异，非笔误，回填时须说明 |
