# E2-RERUN-UNIFIED-01 第 0 步报告

结论：`HALT_NON_SANDBOX_EXECUTION_UNAVAILABLE`。本次完成了强制入口读取、目标沙箱六进程环境探针、柴油价审批痕迹登记和第五条代码级口径审计；45 个结果盲收敛单元没有启动，2025 个正式单元也没有启动。

## 2026-07-27 第三、四条补跑续记

本次续接只处理第三、四条。当前执行通道仍是 `workspace-write` 沙箱，且会话策略明确禁止申请或使用提权执行；因此未能切换到非沙箱/全权限通道。按照冻结合同，没有再次运行同一个六进程配置，没有降为更少进程，也没有启动任何实验 runner。第三条仍为 0/45 单元，第四条仍无可评估数据。

上一轮第 0 步唯一一次六进程探针的完整原始 stderr 已从该轮会话日志恢复如下，并同步写入 `environment_probe.json`：

```text
Traceback (most recent call last):
  File "/Volumes/移动硬盘（512G）/ReSETP/baselines/e2_rerun_unified_01_step0_20260727/mp_probe.py", line 34, in <module>
    main()
    ~~~~^^
  File "/Volumes/移动硬盘（512G）/ReSETP/baselines/e2_rerun_unified_01_step0_20260727/mp_probe.py", line 19, in main
    with ProcessPoolExecutor(max_workers=6, mp_context=context) as pool:
         ~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/anaconda3/lib/python3.13/concurrent/futures/process.py", line 651, in __init__
    _check_system_limits()
    ~~~~~~~~~~~~~~~~~~~~^^
  File "/opt/anaconda3/lib/python3.13/concurrent/futures/process.py", line 594, in _check_system_limits
    nsems_max = os.sysconf("SC_SEM_NSEMS_MAX")
PermissionError: [Errno 1] Operation not permitted
```

因此，K=3000 的“至少 95% 单元满足 L/S < 0.5”判据仍未评估，不能声称满足或不满足；建议 K 仍为未定，也没有证据判断是否需要按客户数缩放。

## 环境门

目标沙箱内唯一一次六进程 `spawn` 空转探针在创建 `ProcessPoolExecutor(max_workers=6)` 时失败。原始异常摘要为：`PermissionError: [Errno 1] Operation not permitted`；调用链停在 Python 3.13 的 `ProcessPoolExecutor._check_system_limits()` 读取 `os.sysconf("SC_SEM_NSEMS_MAX")`。合同要求失败后转非沙箱执行且不得重试同一配置。本会话没有非沙箱执行通道，因此没有用单进程、shell 后台任务或另一种沙箱多进程实现替代。原始现场摘要见 `environment_probe.json`。

## 柴油价登记

用户批准的 2025-02-12 分城市值已追加登记到 `docs/handoff/model_change_approval_register_20260718.md`：北京 7.48，天津 7.43，石家庄及河北 7.43，广州、深圳、东莞、佛山 7.44，成都 7.48，重庆 7.50 元/升。来源为 `baselines/china_e3_e7/pre_e3_full_chain_audit_20260723/diesel_price_2025_02_12_source_register.csv`。

`solver/src/setp_solver/prices.py:120-134` 只增加注释：一段保留旧运行快照 6.87/6.83/6.90 及其 2026-07 来源标识，一段记录新值与新来源。`diesel_price`、空的 `diesel_price_by_city` 默认和 `DEFAULT_PRICES` 均未改变。

## 盲试跑与 K 判据

预登记样本为三个城市群各取 25/100/200 客户 `-01` 一题、种子 1，共 9 题；五臂共 45 个单元。所有单元原计划记录 S、L、L/S、完整 best-so-far 轨迹、进程 CPU、墙钟和峰值 RSS；MV 的 `cv_only`、`naive_ev`、`mechanism_ev` 三视角必须分别使用完整 `NoImprovement(K)`，不得分割一个总预算。

由于环境门先失败，`raw_runs.csv` 只有表头，轨迹和资源数据均不存在。因此 K=3000 是否满足“至少 95% 单元 L/S < 0.5”没有被评估，建议 K 只能记为未定；同样没有证据判断是否应采用 `max(5000, 20n)` 一类客户数缩放。给出任何数值都会伪造本次未产生的收敛证据。

## 第五条口径确认

完成器读取柴油价：是。`solver/src/setp_solver/china81_completion.py:81-102` 把 `bundle.prices` 传给完整 `evaluate`；`solver/src/setp_solver/cost.py:178-183` 用每条 CV 路线油耗乘 `diesel_price_for_route`，而 `cost.py:234-270` 按路线起点车场城市读取城市价。`solver/src/setp_solver/china81.py:346-355` 从时间档案生成城市价格映射，`china81.py:964-1000` 要求每城 48 槽均带已批准且与登记常量一致的唯一值，否则失败关闭。

O 臂共同初始解安全网：触发规则不变。`baselines/algorithm_prototypes/china81_vs_opensource_20260727/run_comparison.py:267-308` 先完成并计分共同初始解；只有搜索解能完成且其完整目标严格满足 `searched < initial - 1e-9` 才采用，否则回退共同初始解。新城市价通过同一个 `bundle` 同时进入两侧计分，因此价值变化不改变这条触发逻辑。

五臂不改受保护文件同批运行：静态代码结论为可以，但本次未取得运行证据。隔离 O adapter 已提供 `distance_only`；冻结 China81 adapter 已提供 `cv_only`、`naive_ev`、`mechanism_ev`；`route_pool_sp.py:88-118` 明确依次给 MV 的三个视角各自运行 HGS 后才重组。为这五臂建立新的统一收敛 runner 不需要修改 `cost.py`、`check.py` 或 `search/evaluation.py`。因此没有触发 `HALT_AWAITING_USER_APPROVAL`；当前 HALT 原因仅是非沙箱执行通道不可用。

## 保护与范围

受保护的 `cost.py`、`check.py`、`search/evaluation.py` 均未修改。2026-07-24 v7 与 2026-07-27 O 臂封存目录均未写入。本次使用独立目录 `baselines/e2_rerun_unified_01_step0_20260727/`。第 1 步 2025 单元正式重跑保持未授权、未启动，仍须等待车型载重结论和 Claude 的另行指令。
