# T12 充电重叠约束容差

## 门禁与真错例验证（最前）

`FACT` 本次唯一代码改动是 `solver/src/setp_solver/check.py::_check_charging_trip_overlap`：复用已有 `FEASIBILITY_TOL = 1e-9`，将两侧相交比较改为 `charge_start < returned - FEASIBILITY_TOL` 与 `departure < charge_end - FEASIBILITY_TOL`。T11 已有的在途公共站跳过逻辑未改；`cost.py` 与 `search/evaluation.py` 未改。

`HALT_REGRESSION_FAILED` 定向门禁结果为 **36 passed / 5 failed**，不是预期的 7 项全部恢复。已恢复的是 `test_public_station_multitrip_20260723.py` 的 2 项。仍失败的是 `test_refined_carbon_charging.py` 的 2 项和 `test_search.py` 的 `test_h2_...`、`test_h3_...`、`test_m0_evheavy_...` 3 项。精细充电失败值为真实重叠 `[8000.000000, 21090.909091)` 与行程 `[0.000000, 10492.783666)`，以及 `[9000.000000, 22090.909091)` 与同一行程；搜索 3 项均为 `HALT_H2: no feasible EV route with a nonzero charging action`。按停止条件未调大容差、未改测试、未跑全量套件。

`FACT` 容差未放跑原缺陷真错例。三个阳性样本仍全部为 `CHARGING_TRIP_OVERLAP`，实际最大重叠秒数为：`C_seed2_budget1000` = `6563.0712245500035 s`；`C_seed1_budget100` = `6365.9078330282355 s`；`C_seed3_budget1000` = `6239.742124296223 s`。T10 的 18 个解复核为 **18/18 合法**，无新违反；T9 当时判定无重叠的 20 个解复核为 **20/20 合法**，无误报。

## FACT

开工前三项 SHA-256 为：`cost.py` = `e7ea406da87a3172cd1ff7dc87fe7def536e74f197f6c67b29da2394fe42b00d`；`check.py` = `93139ea143d361d1b4cde7e9e2a34506bf90b95fe718809c1a467c2fd97b7f73`；`search/evaluation.py` = `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3`。

收工后三项 SHA-256 为：`cost.py` = `e7ea406da87a3172cd1ff7dc87fe7def536e74f197f6c67b29da2394fe42b00d`；`check.py` = `1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072`；`search/evaluation.py` = `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3`。

定向命令使用 `PYTHONHASHSEED=0` 与 `PYTHONPATH=solver/src:models/src`，耗时 120.11 秒。没有重跑搜索，也没有运行全量测试；因此没有新的全量计数。T10 基线 `898 passed / 1 skipped / 14 failed` 与预期全量 `905 passed / 1 skipped / 7 failed` 均不作本轮实测结果。

## INFERENCE

`INFERENCE` 当前证据只说明 `1e-9` 容差修复了公共站多趟测试中的浮点端点误报；它没有使全部 7 项门禁恢复。精细充电剩余失败不是 `1e-9` 端点尾数，而是秒级真实相交；搜索失败是由候选构造未得到带非零充电动作的可行 EV 路线。不能据此扩大容差或修改其他逻辑。

## DECISION

`DECISION` 本轮状态为 `HALT_REGRESSION_FAILED`。`paper_claim_allowed = false`。未改 `cost.py`、`search/evaluation.py`、测试文件、T10/T11 witness、T10 生成器或论文目录。

## 产物

`regression_verify_tolerance.py` 是只读 witness 回放脚本；`witness_results.json` 保存三个阳性、T10 18 个解和 T9 20 个解的复核结果。`artifact_hashes.json` 排除 `._*`、`__pycache__`、`.pytest_cache`。
