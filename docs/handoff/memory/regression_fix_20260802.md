# W3 shared completion 回归修复（2026-08-02）

状态：`W3_REGRESSION_FIX_COMPLETE`。权威证据目录为 `baselines/china_e3_e7/regression_fix_20260802/`。

## FACT：根因与 authority 判定

fleet authority v3 没有缺陷。`cn-jjj-10c-01-V2-LOCATIONS / D_beijing` 的固定总量为 `T_d=2`，0% 档是 2 CV+0 EV，默认 25% 档是 1 CV+1 EV。第一项回归中，旧 `exact_china81_score` 信任 `CV1#T1/CV1#T2` 的共同前缀，把时间重叠的两趟误计成一台 CV，得到伪基线 499.75649570293297；严格多趟排班证明需 2 台 CV，合法 0% 参照为 669.7564957029331。默认混合解为 577.531087595572，相对合法参照实际降低 92.22540810736109。

第二项回归来自旧 completion 直接比较 `route_count` 与 `num_cv+num_ev`。三条测试路线中，R1 于 46062.83456 秒返回，R3 于 48168.19208 秒出发，可由同一台 CV 连续执行；R2 转成 EV 后是 1 台 CV+1 台 EV，满足默认档。路线数 3 不等于物理车数 2。

## FACT：生产修复

W3 只改 `solver/src/setp_solver/china81_completion.py`，没有改测试或 authority。评分前调用既有 `build_multitrip_certificate` 重建物理车—trip 映射；全 CV 参照按同一 `T_d` 的 0% 档检查，混合解按活动车型上限检查；车场车型/总量按唯一物理车集合计数；mandatory 车型转换只接受使 `(CV overage, EV overage, total overage)` 严格下降的候选；最终解返回认证后的 `physical_vehicle#T` 标识。

## FACT：回归终态

两项目标测试 2/2，通过整个目标文件 3/3；相关 China81/multitrip 集合 49/49。全量为 `909 passed, 1 skipped, 3 failed`。残留只有 W2 已分类的两项 E5 `unresolved_historical` 和一项 EV-heavy `old_contract`，`real_regression` 为 0。

W2 构造器 `--audit-only` 复认证仍为 0/25/50/75/100% 各 81，合计 405/405，违反项 0、车队总量 943、路径搜索与正式实验均为 0。`check.py`、`search/evaluation.py`、`paper_main.tex` 的 `git diff --quiet` 均为 0。`cost.py` 是 W3 启动前已有脏文件，W3 没有编辑。

## BOUNDARY

本任务不处理 `test_e5_ablation` 两项历史失败，也不重定义 `test_ev_heavy_findability_gate` 的旧契约。W3 没有启动正式实验、路径搜索，没有删除、移动或覆盖既有结果目录。
