FLOATFIX_DONE

# 已获批浮点权威值常量化修复报告（2026-08-13）

## 一、结论

`USER DECISION`：`docs/paper_gci_dmm_vrp_20260804/pending_decisions.md:312-319` 的 P55 已规定：已获批的权威参数必须以最终常量存储和传递，不得在运行时由分项相加得到；分项只保留作来源说明。

`FACT`：本轮在活动计算链中查到并修复 **4 处**同类问题，涉及两组已获批最终值：

1. EV 非能源里程成本 `0.9145`，不再由 `0.6700 + 0.2445` 重构；
2. EV 每车日固定成本 `220.0`，不再由 `170.0 + 50.0` 重构或闭合校验。

`FACT`：最终运行时只接收以下具名常量，见 `solver/src/setp_solver/china81.py:45-47`：

```python
CV_FIXED_CNY_PER_DAY = 170.0
EV_FIXED_CNY_PER_DAY = 220.0
EV_NON_ENERGY_CNY_PER_KM = 0.9145
```

`FACT`：`data/ChinaInstances/china81_private_rebuild_v1_20260811/vehicle_costs.csv:1-3` 仍保留 `0.6700`、`0.2445`、`170.00`、`50.00` 等分项及来源文字，但运行时不再读取这些分项来合成 `0.9145` 或 `220.0`。该数据文件未改，SHA-256 仍为 `87707b48876e1487f1a13e556c16fbd3a836d7d68bd9a3f41d5b1b068f790640`，与 `artifact_hashes.json:24` 一致。

`FACT`：没有运行求解器正式实验，没有改算例几何、算法参数或任何获批数值。三个受保护文件均未修改。

## 二、全仓库排查方法与结果

### 2.1 排查范围

`FACT`：排查组合使用了以下三种方式：

- 对 Git 已登记的全部 Python 文件和当前 `solver/src`、`solver/scripts` 下尚未登记的活动 Python 文件做 AST 扫描；
- 全仓检索 `0.67`、`0.2445`、`0.9145`、`170`、`50`、`220` 及 `base`、`premium`、`effective`、`depreciation` 等字段的算术上下文；
- 回查 P43、P54、P55 的批准记录，以及 CSV/JSON 参数表和历史产物清单，区分“生成权威参数”和“用最终参数做正常业务总账”。

`FACT`：明确属于 P55 的位置共 4 处。除第七节列出的 1 条存疑链外，没有发现其他获批浮点最终值由分项相加生成的活动计算链。

### 2.2 全部明确同类位置

| 编号 | 施工前位置 | 旧算式／行为 | 修复后位置 | 新行为 |
|---|---|---|---|---|
| F1 | `solver/src/setp_solver/private_instance_rebuild_20260811.py:127-144,182-199` | 从 CSV 读取 `base_non_energy_cost_cny_per_km` 与 `battery_depreciation_cny_per_km`，执行 `float(base) + float(depreciation)`，再把结果写入 EV 运行时档案 | 同文件 `:120-139,177-194` | CSV 只读取最终字段作精确核对；运行档案直接赋 `EV_NON_ENERGY_CNY_PER_KM` |
| F2 | `solver/scripts/build_private_instance_rebuild_20260811.py:451-476`，具体旧 `:466` | `f"{0.67 + BATTERY_DEPRECIATION_CNY_PER_KM:.4f}"` 生成 effective 字段 | 同文件 `:456-481`，具体 `:471` | 直接格式化 `EV_NON_ENERGY_CNY_PER_KM`；分项列仍保留作溯源 |
| F3 | `solver/src/setp_solver/china81.py:683-704`，具体旧 `:695-699` | 读取 base 与 premium，执行 `base + premium` 后与已存 effective 固定成本比较 | 同文件 `:672-702` | 不读取分项做算术；CSV effective 精确核对 `CV_FIXED_CNY_PER_DAY`／`EV_FIXED_CNY_PER_DAY`，运行时返回最终常量 |
| F4 | `solver/scripts/build_private_instance_rebuild_20260811.py:1390-1393` | `fleet_reduction_count * (170.0 + EV_DAILY_FIXED_PREMIUM_CNY)` 重构 220 后计算固定成本节省上界 | 同文件 `:1395-1396` | 直接乘 `EV_FIXED_CNY_PER_DAY`；下界也改为具名的 `CV_FIXED_CNY_PER_DAY` |

`FACT`：`solver/src/setp_solver/china81.py:911` 的基础 EV 档案也由裸字面量改为同一个 `EV_NON_ENERGY_CNY_PER_KM`，避免同一获批值出现多个代码事实源；数值仍是 `0.9145`。

`FACT`：配套删除了 private loader 施工前 `:427-433` 的 `effective_ev - effective_cv == 50` 分项闭合校验；当前 `:429-445` 分别把 CSV 与运行时的 CV/EV effective 值精确核对最终常量 `170.0`／`220.0`。这不是第 5 处正向相加，但用于保证 loader 不再让 50 元分项参与最终值合同的运行时闭合。

### 2.3 查到但明确不属于本轮的算术

`FACT`：以下位置没有修改：

- `solver/scripts/build_private_instance_rebuild_20260811.py:1159` 的 `EV_NON_ENERGY_CNY_PER_KM + ev_kwh_per_km * price`：这是用最终 `0.9145` 加动态电能成本，所得运营总成本不是另一个已获批权威参数；
- `solver/scripts/build_china81_suite_rebuild_20260812.py:1597` 的同类运营总账：同上；该 suite 在 `:107,962,2433-2434` 原本就直接使用 `0.9145` 和 `220.0`；
- `solver/tests/test_private_rebuild_search_adapter.py:178` 的 `8 * 170.0 + 50.0`：这是一个解的多车固定成本断言，不是在生成单车权威参数 `220.0`；
- `solver/src/setp_solver/cost.py` 的车型汇总：正常解评价，且文件受保护；
- `private_instance_rebuild_20260811.py:359-368` 的 `ev_fixed - cv_fixed`：只从最终 `170/220` 反向计算 `cost_fix_ev_premium` 审计分解，不读取 50 元分项，也不构造或传递 `220`；
- `algorithms/problem_hgs/evaluation.py:850-872` 的同类差额：完整成本已由 `evaluate()` 使用最终 `170/220` 计算；这里核对的是 P43-F/H/I 独立批准的 50 元机制参数并输出审计分解，不生成最终固定成本；
- builder `:1171-1173` 的 `50 / 每公里节省`：计算获批 50 元机制参数对应的临界里程，不构造 `220`；
- `total_fleet_cap = num_cv + num_ev` 等整数结构量：没有本次浮点尾差，也不是获批浮点权威值。

## 三、防复发测试

新增 `solver/tests/test_authoritative_float_constants.py`，包含三层防线：

1. `:21-42` 精确断言：
   - `0.6700 + 0.2445` 为 `0x1.d4395810624dep-1`；
   - 最终常量 `0.9145` 为 `0x1.d4395810624ddp-1`；
   - 两者不相等；
   - 私有算例 loader 的实际运行值必须精确等于最终常量，并具有 `…4dd` 位串。
2. `:67-333` 的识别器和变异用例覆盖本轮删掉的 4 种旧表达式，以及变量/导入别名、`+=`、`sum(...)`、`builtins.sum(...)`、`math.fsum(...)`、`operator.add(...)`、NumPy add/sum 与以 add 为归约函数的 `functools.reduce(...)` 等同义重引入方式；同时断言以乘法归约时不会误报。
3. `:336-379` 扫描全部已登记 Python 源码，加上 `solver/src`、`solver/scripts` 的活动未登记源码；发现 `0.6700+0.2445` 或 `170+50` 家族重新合成最终值时，测试直接失败并报告文件、行号和表达式。

`FACT`：定向回归命令使用 CPython 3.13，设置 `PYTHONDONTWRITEBYTECODE=1`、`PYTHONHASHSEED=0`，并使用 `PYTHONPATH=solver/src:third_party/setp_hgs_kernel`。结果：

```text
........................................                                 [100%]
40 passed in 16.08s
```

覆盖文件：

- `solver/tests/test_authoritative_float_constants.py`
- `solver/tests/test_china81_bundle_20260720.py`
- `solver/tests/test_private_rebuild_search_adapter.py`
- `solver/tests/test_china81_suite_rebuild_builder.py`
- `solver/tests/test_china81_endogenous_fleet_parameters.py`

`FACT`：另执行了语法编译检查、`git diff --check` 和 Ruff 的致命错误子集 `E9,F63,F7,F82`，均通过。完整 Ruff 扫描仍报告两个施工前已经存在的未使用导入：builder 的 `Iterable` 与 private loader 的 `Node`；本轮没有顺手清理，以免扩大范围。

`FACT`：第一次用系统 `python3`/不完整 `PYTHONPATH` 收集宽回归时，两个测试因找不到 `setp_hgs_kernel` 而失败；补齐仓库第三方内核路径并固定 CPython 3.13 后，以上 40 项全部通过。该环境失败没有被隐去，也没有当作业务失败。

## 四、固定 EV 解的位串与 SHA-256 对照

### 4.1 复算对象与口径

`FACT`：固定解取自：

`solver/reports/combat_prescreen_speedup_20260812/equivalence_before_3cycles/best_solution.json`

其保存评价含 6 辆实体 EV、EV 总里程 `968387.3698812299 m`，复算直接读取 `evaluation.prepared_solution`，不搜索、不改路线。

`FACT`：前后两臂只改变一个输入：

- 修复前模拟值：`0.6700 + 0.2445`；
- 修复后当前值：`EV_NON_ENERGY_CNY_PER_KM`。

其他实例、价格、时间剖面、解结构和受保护评价器完全相同。

### 4.2 数值与位串

| 项目 | 修复前模拟 | 修复后当前 |
|---|---:|---:|
| EV 非能源成本 | `0.9145000000000001` | `0.9145` |
| EV 非能源成本 `float.hex()` | `0x1.d4395810624dep-1` | `0x1.d4395810624ddp-1` |
| `cost_km` | `984.8463877032989` | `984.8463877032988` |
| `cost_km.hex()` | `0x1.ec6c566ea8b3ep+9` | `0x1.ec6c566ea8b3dp+9` |
| `total_cost` | `2967.7155033949475` | `2967.715503394947` |
| `total_cost.hex()` | `0x1.72f6e567602f4p+11` | `0x1.72f6e567602f3p+11` |

`FACT`：完成客户数前后均为 `50/50`，完成需求量前后均为 `12223/12223`，违规数前后均为 0。

### 4.3 哈希口径与结果

为避免把不同哈希对象混称为“解哈希”，本报告明确记录载荷：

```python
payload = {
    "prepared_solution": solution_to_dict(solution),
    "evaluation": evaluate(solution, instance, time_profile, prices),
}
json.dumps(
    payload,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
    allow_nan=False,
)
```

该“固定解结构＋完整评价记录”的 SHA-256 为：

- 修复前：`cb14c327fb614eff3b381d40f0b0dc8b6c54daa9e04ffccbe55ba915785fd213`
- 修复后：`bcaba1346ad26bb578aef611a9401f5018628f6c9921d62cee410dc5af11f5ba`

`FACT`：哈希改变的唯一原因是权威浮点值从 `…624de` 变为字面常量的 `…624dd`，继而让 `cost_km` 和 `total_cost` 各改变 1 ULP；解的路线、车型和充电结构没有改变。

`FACT`：项目生产函数 `solution_signature_hash()` 只哈解结构，前后均为：

`5c83a4c146926f60799633fb8fdf02e91d2744dda28af060d06e4426b1233a90`

这说明结构哈希没有变化；变化的是包含浮点评价记录的哈希。

`FACT`：P55 原始记录中的最小复算 `json.dumps({"c": value}, sort_keys=True)` 也已复现：

- `{"c": 0.9145000000000001}` → `bcf66ef3d276b70edf491c1b1cba99ed30f2f727607cb9f3cb86c641e59a91a3`
- `{"c": 0.9145}` → `3d2279c8e95dcfae81aed104ad63f3e9b582800f7d8e848b806d3bcc5b539d21`

它是 P55 的最小演示字典，不是仓库某个 `best_solution.json` 的文件哈希。

## 五、已保存哈希基线影响清单

### 5.1 活跃测试基线

`FACT`：需要立即更新的活动测试硬编码 SHA-256 基线为 **0 条**。`solver/tests` 中已有的 64 位哈希只涉及动态冻结文件和 E7 事件/所有者文件，与本次 EV 参数链无关。

### 5.2 历史私有 EV 结果包

`FACT`：全量扫描 `solver/reports` 后，找到 11 个同时满足以下条件的保存包：

- `metadata.json` 的 `instance_id` 为 `cn-prd-50c-01-V3-TWO-SHIFT-GZ-FS`；
- `best_solution.json` 含 EV；
- 结果产生于旧 private loader 的 `…4de` 参数链。

这些是“若按当前代码重建，必须新建基线与 manifest”的历史包：

| 目录 | 旧 `best_solution.json` SHA-256 |
|---|---|
| `solver/reports/combat_prescreen_speedup_20260812/combat_5cycles_trajectory_off` | `961ddf3b6a1d258ae3caf08cb259699bb36790f46bfa90d31dc9f81fbc03f594` |
| `solver/reports/combat_prescreen_speedup_20260812/equivalence_after_3cycles_audit2000` | `0c83fb25c7c101c2236f57308117f62066e70ef69d89362ae2a5655a6df555e8` |
| `solver/reports/combat_prescreen_speedup_20260812/equivalence_before_3cycles` | `f764daba2c7d9f1c1326dcff8eebb37b22c67aeda6bd256bc686ead78415df04` |
| `solver/reports/combat_readiness_20260812/combat_5cycles` | `8f882522891c4f2bac5fefb87509a6acafb7e759ed820c89e5f36463b8d2f497` |
| `solver/reports/combat_v2_20260812/closure_charge_timing_1cycle` | `a2288c740ed0294e5bd0550313f77d476e8cf5362fa303e4d0c184c9136a64fc` |
| `solver/reports/combat_v2_20260812/closure_charge_timing_final` | `1bec5dfa6416da6ffb6bfd45fc1c6368c0a16926b5ba27a2864a6942b76754c1` |
| `solver/reports/combat_v2_20260812/closure_cross_depot_1cycle` | `ba3a4031a4d06a227be389913e28057916cf2d8b86bc6167fd295c025446df19` |
| `solver/reports/combat_v2_20260812/closure_cross_depot_final` | `b6cf1012695830912f4773aa11b1d31d7b4b70215b5ac7d6cd142b44598fbd58` |
| `solver/reports/combat_v2_20260812/combat_v2_5cycles` | `fd3ad6077dec0ea1fe4bd48b2b164cb389c6fff14031735d53dd40454b6cb1a8` |
| `solver/reports/combat_v2_20260812/combat_v2_5cycles_final` | `18028202f6b453e91e044bb53b3c876b003412d64baee0b776a33b3105bb4fbb` |
| `solver/reports/combat_v2_20260812/smoke_combat_1cycle` | `c7a631bc7592b3b911da09ea5b1d2e8bb0812da3ef3eb48afac5a4253fe952c6` |

`FACT`：上述 11 个旧文件当前的逐字节 SHA-256 全部仍与各自 `artifact_hashes.json:2` 匹配。本轮没有覆盖任何旧 `best_solution.json` 或 manifest。旧 manifest 对旧文件仍然有效；若以后用当前常量重放或重建，必须写入新目录并生成新 manifest，不能把新哈希静默写回历史包。

`FACT`：其余已保存的 V3 PRDFIX/China81 suite 路径原本就使用最终常量 `0.9145`，不属于本次 private loader 位串修复的受影响基线。

### 5.3 参数数据产物

`FACT`：private `vehicle_costs.csv` 未变，原 manifest 继续有效。构建器从“相加后格式化”改为“直接格式化最终常量”时，输出文本仍是 `0.9145`，因此不会仅因本修复改变该 CSV 的字节哈希。

## 六、受保护文件与施工文件哈希

### 6.1 三个受保护文件

| 文件 | 任务前 SHA-256 | 任务后 SHA-256 | 结果 |
|---|---|---|---|
| `solver/src/setp_solver/cost.py` | `525e91f7bd2cf7a4b6610ee1c8f662e8a4233c5daec800dcae5e5f21ac727989` | `525e91f7bd2cf7a4b6610ee1c8f662e8a4233c5daec800dcae5e5f21ac727989` | 未改 |
| `solver/src/setp_solver/check.py` | `1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072` | `1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072` | 未改 |
| `solver/src/setp_solver/search/evaluation.py` | `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3` | `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3` | 未改 |

### 6.2 本轮代码文件

| 文件 | 任务开始快照 SHA-256 | 本报告形成时 SHA-256 |
|---|---|---|
| `solver/src/setp_solver/china81.py` | `9842568f4ed64ca96650bc58e18687908848e78f02b70400583e2851d121b826` | `19d4c1cafbf8bd65bfa70e5d7825fc9170af28ba83c4bf7f1f6e9ef5ca64b2c3` |
| `solver/src/setp_solver/private_instance_rebuild_20260811.py` | `0e8fc432f6930ca28d57165c8321e34f7d0a88e7a3cb20f2d20be80674aeee1f` | `909dd2b2ab15764c971b5357d2e104c5826723bdd0918e594f08d6d089f4932b` |
| `solver/scripts/build_private_instance_rebuild_20260811.py` | `1787e16024d16c4734823517b50bdf55c430e21575efcc2dc83b04a1ef6d76ea` | `6ec65fb632df109f3eeaf3173b9fbb26eae99caedd6fe4a531189c567b22889f` |
| `solver/tests/test_authoritative_float_constants.py` | 不存在 | `7212ddd78463b02175ae352f7aff7dffac599352a04eb67a360785d8429547b9` |

## 七、本轮未处理但疑似同类的清单

### UNKNOWN-1：公共充电总价的分项闭合

`UNKNOWN`：公共充电表含 `public_energy_cny_per_kwh`、已获批服务费 `0.4` 和存储的 `public_total_cny_per_kwh`。以下位置存在“电能价＋服务费”的链：

- 活动 loader：`solver/src/setp_solver/china81.py:1018-1040`，执行 `energy + service`，但只用于容差校验；真正传入运行时的是 CSV 的 `total` 字段；
- 初始生成器：`baselines/china_instances/build_china_stage2_static_inputs_20260718.py:184-188`，用 `round(float(prices[label]) + 0.4, 9)` 生成 total；
- 历史校验/审计副本：`baselines/china_instances/build_china81_runtime_parameter_authority_v3_20260723.py:122-131`、`baselines/china_e3_e7/pre_e3_full_chain_audit_20260723/run_pre_e3_full_chain_audit.py:1668-1679`、`baselines/china_e3_e7/e3_pooling_probe_20260731/frozen_baseline/solver/src/setp_solver/china81.py:780-800`。

`FACT`：复算当前 v4 权威表 12,096 行，有 4,256 行的分项和与存储 total 不逐位相等。第一例：

- `0.83644275 + 0.4` → `0x1.3c878316a0558p+0`
- 存储的 `1.23644275` → `0x1.3c878316a0557p+0`

`UNKNOWN`：P54 明确批准的是服务费 `0.4`，当前证据没有证明 12,096 个逐槽 `public_total` 各自都是“已获批最终权威参数”。活动 loader 也没有把相加结果写入运行参数。因此本轮按“拿不准就停”的要求，只登记这一条，不改代码、不改数据、不扩大 P55 范围。

除 UNKNOWN-1 外，本轮未发现其他疑似的已获批浮点和值链。

## 八、历史记录纠正

`CORRECTION`：`docs/handoff/base_defaults_fix_20260812/report.md:24,66,68` 把 private loader 的 `0.67+0.2445` 描述为“保持逐位一致／已按 0.9145”。数值在普通十进制展示上接近，但位串实际是 `…4de`，并非字面量 `0.9145` 的 `…4dd`。旧报告作为历史记录不覆盖；以本报告的位串和固定解复算为准。

`CORRECTION`：`docs/handoff/CURRENT_PROJECT_CONTEXT.md:743` 原称“同一私有见证的解哈希与账单浮点位串修复前后一致”，也被本报告的固定解复算推翻；当前事实源已同步更正为“结构哈希不变，含评价浮点值的记录哈希改变”。

## 九、交付边界

`FACT`：本任务是代码修复与零搜索固定解重放，不产生正式实验包，因此不产生 `metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json` 四件套。

`FACT`：本轮没有修改 `pending_decisions.md`，因为 P55 的用户决定没有变化；只执行该决定。

`FACT`：本轮停止在“权威最终值由分项运行时相加”这一类问题；没有顺手重构其他数值代码，也没有对 UNKNOWN-1 作未经批准的裁决。
