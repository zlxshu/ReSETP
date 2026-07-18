# 机制贯穿式 ALNS：隔离开发区

这里承载 2026-07-19 起的新一轮算法开发。它只新增隔离原型，不修改正式求解器、
历史 v7/v8/v9 证据或三份受保护的成本、检查、预算文件。

第一张门只回答一件事：把当前单一起点替换为真正不同、同时包含纯路由和机制
倾向的起点池，是否能在新鲜开发题上稳定产生更好的完整可行起点。

十二选一阶段不运行短 ALNS，也不调用终局机制修复。选出赢家后，默认起点与新
赢家才各走一次相同终局修复，用来确认构造优势没有被共同处理抹掉。

运行顺序：

```bash
PYTHONPATH=solver/src:models/src \
python3 baselines/algorithm_prototypes/unified_mechanism_alns_20260719/build_blind_d1_bundles.py

PYTHONPATH=solver/src:models/src \
python3 -m unittest \
baselines/algorithm_prototypes/unified_mechanism_alns_20260719/test_initial_pool.py

PYTHONPATH=solver/src:models/src \
python3 baselines/algorithm_prototypes/unified_mechanism_alns_20260719/run_initial_pool_gate.py
```

本目录内任何 `decision.json` 都是开发门结论，不授权阶段二或正式实验。

第一张多样初解门已按原合同停止。当前冻结候选改为
`dual_basin_solver.py`：官方 HGS-CVRP 只提供一份不同的客户顺序；路线内
车型、补能与低碳时刻成本负责选择该顺序或当前 ALNS 起点。选择当前起点且
预算足够时，只允许一次按 G0 规则计费的中段机制校正；选择 HGS 起点时保留
一段不间断 ALNS，避免重演固定分段失败。

候选测试：

```bash
PYTHONPATH=solver/src:models/src:\
baselines/algorithm_prototypes/mechanism_hgs_alns_20260718:\
baselines/algorithm_prototypes/unified_mechanism_alns_20260719 \
python3 -m unittest \
baselines/algorithm_prototypes/unified_mechanism_alns_20260719/test_dual_basin_solver.py
```

新鲜开发门合同是
`docs/handoff/dual_basin_mechanism_alns_fresh_gate_contract_20260719.md`。
