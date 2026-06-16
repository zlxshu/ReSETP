# Task B 100-01 headline 复核

- gate: `PASS_BEST_VERIFIED`
- V2 summary headline mean: £4878.331796
- 10 个落盘解独立重算 mean: £4878.331796
- 零违约解: 10/10
- best concrete solution: seed 2, £4779.053444, routes=32 (CV=11, EV=21)
- best 成本分解: fix=£2560.000000, km=£1376.731188, fuel=£574.645792, elec=£212.180198, carbon=£55.019106, occ=£0.477160

结论：£4878.331796 是 10-seed mean headline；可落地的 best-known 解是 seed2 的 £4779.053444。两者都由 `evaluate()` 独立重算并通过 `check_solution()` 零违约。
