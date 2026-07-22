# S6-SUP-03 PyVRP 0.12.2 HGS 教育阶段邻域清单

机器判定：`PASS_S6_SUP_03_PYVRP_NEIGHBORHOOD_AUDIT`。以下清单来自冻结环境中 PyVRP 0.12.2 的默认 `NODE_OPERATORS`/`ROUTE_OPERATORS` 列表、运行时类文档和本项目实际调用代码；没有把未出现在源码中的 2-opt 或其他算子补进来。

在 `cn-prd-50c-01-V2-LOCATIONS` 的 PyVRP 数据上，`num_clients=50`、`num_depots=2`、`num_vehicles=200`。实际通过 `supports(data)` 并加入搜索的是：Exchange10, Exchange20, Exchange11, Exchange21, Exchange22, SwapTails, SwapRoutes, SwapStar；被数据支持门排除的是：RelocateWithDepot。

## 实际算子

| 阶段 | English original name | 一句中文释义 | 本代表题是否加入 |
|---|---|---|---|
| node | `Exchange10` | 交换一条路线的连续 1 个客户与另一侧的 0 个客户段，即单客户 RELOCATE 特例。 | 是 |
| node | `Exchange20` | 交换一条路线的连续 2 个客户与另一侧的 0 个客户段，即双客户段 RELOCATE 特例。 | 是 |
| node | `Exchange11` | 交换两条路线各自连续 1 个客户的片段，即单客户 SWAP 特例。 | 是 |
| node | `Exchange21` | 交换两条路线的连续 2 客户段与连续 1 客户段。 | 是 |
| node | `Exchange22` | 交换两条路线各自连续 2 客户的片段。 | 是 |
| node | `SwapTails` | 交换两个节点后继所形成的路线尾段；源码明确标注为 VRP 文献中的 2-OPT*。 | 是 |
| node | `RelocateWithDepot` | 在搬移客户时插入 reload depot 的多趟路线邻域；本代表题未通过数据支持门。 | 否（supports(data)） |
| route | `SwapRoutes` | 交换两条路线的访问序列。 | 是 |
| route | `SwapStar` | SWAP* 自由重插：交换两个客户，但不要求把客户插回彼此原来的位置。 | 是 |

## HGS 教育调用链

PyVRP 的 `GeneticAlgorithm._improve_offspring` 调用 `LocalSearch.__call__`；`LocalSearch.__call__` 先执行 node-operator 的 `search`，再执行 route-operator 的 `intensify`。本项目的 S3 观察 runner 在每个 HGS epoch 中按同一结构创建 `SolveParams()`、计算 granular neighbourhood、逐个加入支持的 node/route operator，然后运行 `GeneticAlgorithm`。源文件哈希见 `metadata.json`。

## 项目调用是否裁剪

算子种类层面：没有发现项目自定义删减；项目沿用 PyVRP 0.12.2 默认 7 个 node operator 和 2 个 route operator，再由 `supports(data)` 过滤。因此本代表题只少了 `RelocateWithDepot`，原因是数据支持门返回 False，不是项目为结果而裁剪。
候选邻接层面：项目使用默认 `NeighbourhoodParams(num_neighbours=40)`。`compute_neighbours` 对每个客户保留最多 40 个最接近客户（本题 50 客户），所以这是候选边的 granular pruning，而不是删除算子类型；车场不进入该客户邻域。

`SwapTails` 的运行时文档明确称其为 2-OPT*；源码没有一个独立名为 `TwoOpt` 的默认算子，所以论文步骤应写 `SwapTails (2-OPT*)`，不要写成一个未实际启用的泛称 `2-opt`。

## 复核锚点

PyVRP 发行版本：`0.12.2`；安装 wheel 的来源和文件哈希已保存在 `metadata.json`。源码/文档文件 SHA-256：{"baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/pyvrp_adapter.py": "bd79018720edf8233cfc6f832dbabd7fb5ae1b853b5e386405acdf459e70d200", "baselines/e2_alns/external_tools/pyvrp-0.12.2/pyvrp-0.12.2-cp313-cp313-macosx_11_0_arm64.whl": "3725680fcb75dc4a424160460e5ba7e3a4ea9694ed4b3b196049047922d8f226", "baselines/e2_final_campaign_20260720/mv_hgs_sp_final/run_china81_convergence_gate.py": "4355ef84e1dd4205e5ded5c5a9348f35a813b5242038aa47170944973ddbbec5", "baselines/e2_final_campaign_20260720/p2p3_threeview/representative_gate/s3_traj_v4/run_s3_trajectory_v4.py": "44c6186f5430eaf0862e3824db33323d1cb87e827c0e78bbfeced981bf46fdce", "baselines/e2_final_campaign_20260720/p2p3_threeview/s6_support/s6_sup_03_pyvrp_education_neighborhoods/run_s6_sup_03.py": "6f2deaa5990d9bc49ba70763ed40e334c4aa9b42913cd759447f43e7f0f5e70a", "build/python_envs/pyvrp-hgs-0.12.2/lib/python3.13/site-packages/pyvrp-0.12.2.dist-info/direct_url.json": "e235ed751c1b2ab519f333283502b20b5094acbca8dc3d742acce1891350ddcb", "build/python_envs/pyvrp-hgs-0.12.2/lib/python3.13/site-packages/pyvrp/GeneticAlgorithm.py": "c7c8c068a1fbd42d341e3dddda66b703a8d99ea9236a19ad5fd300d8963470fe", "build/python_envs/pyvrp-hgs-0.12.2/lib/python3.13/site-packages/pyvrp/search/LocalSearch.py": "fd6a961e3065afcd3be455f7616ed70c0892f98dc2870eba1f1457371c369212", "build/python_envs/pyvrp-hgs-0.12.2/lib/python3.13/site-packages/pyvrp/search/__init__.py": "47f91938cc9450b96eb9d5dd1c30ac82a793aad53918910d04742e88639c0eee", "build/python_envs/pyvrp-hgs-0.12.2/lib/python3.13/site-packages/pyvrp/search/_search.pyi": "7093a4ff84b5a9f3c2c23bbc97b767391b793eac6c328baf620ff00e732ed52e", "build/python_envs/pyvrp-hgs-0.12.2/lib/python3.13/site-packages/pyvrp/search/neighbourhood.py": "159d4a4c19cee222d89da63d3d9efb5c02aed193bddf7a00d5ed66b514225b23", "build/python_envs/pyvrp-hgs-0.12.2/lib/python3.13/site-packages/pyvrp/solve.py": "1e304cfdd21fcdffb7bac03afe300d3a18cee7c22defa652bada42776417f0cc", "data/ChinaInstances/china81_stage2_static_inputs_v1_20260718/instances/cn-prd-50c-01-V2-LOCATIONS/nodes.csv": "9491a191be1f00287c46ca8b11ee6e414b379e20d63870d22b15853d7fd40521"}。

主 TeX、封存数据、评价器和 PyVRP 环境没有修改；本目录只是论文引用用的只读审计产物。
