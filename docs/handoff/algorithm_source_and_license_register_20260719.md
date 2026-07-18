# 算法源码、论文引用与许可证登记

- 日期：2026-07-19
- 原则：论文引用回答“方法从哪里来”；许可证回答“源码能否复制、修改和随仓库迁移”。两者不能互相替代。

| 对象 | 本仓库用途 | 固定版本 | 许可证处理 | 必须保留的引用 |
|---|---|---|---|---|
| PyVRP | Python HGS强对照、融合探针 | `0.12.2`；wheel SHA-256 `3725680fcb75dc4a424160460e5ba7e3a4ea9694ed4b3b196049047922d8f226` | MIT；wheel内许可证已原样保存于同目录 `LICENSE.md` | Wouda、Lan、Kool（2024），DOI `10.1287/ijoc.2023.0055`；Vidal（2022），DOI `10.1016/j.cor.2021.105643` |
| 官方 HGS-CVRP | C++原装强对照；在完整 ReSETP 中只作路线顺序来源 | 上游 <https://github.com/vidalt/HGS-CVRP>；commit `1a927955cd2861a29d978f0d359d6e647db9319c`；冷启动入口 `scripts/setup_official_hgs_cvrp_20260718.py` | MIT；原许可证逐字保留于受跟踪路径 `third_party/hgs-cvrp/LICENSE`；源码和编译产物位于忽略的 `build/`，由固定提交重建并在出分前验签，不把机器相关二进制冒充可移植源码 | Vidal 等（2012），DOI `10.1287/opre.1120.1048`；Vidal（2022），DOI `10.1016/j.cor.2021.105643` |
| N-Wouda ALNS | Python原装 ALNS 对照和成熟实现参照 | 上游 <https://github.com/N-Wouda/ALNS>；本地包声明 `7.0.0` | MIT；`Reference Algorithm/ALNS-7.0.0@N-Wouda/LICENSE.md` 原样保留。`CITATION.cff`仍写旧发行版`5.0.4`，该差异如实记录 | Wouda、Lan（2023），DOI `10.21105/joss.05028`；Ropke、Pisinger（2006），DOI `10.1287/trsc.1050.0135` |
| 项目本地 ALNS runtime | ReSETP 使用的接受规则、算子选择和结果枚举；列于 `solver/src/setp_solver/algorithms/resetp_alns/runtime/{accept,select,outcome,__init__}.py` | 依据 N-Wouda/alns `7.0.0` 修改；具体源树哈希由每次盲锁固定 | MIT；上游版权声明和完整许可证同时保留于 `solver/src/setp_solver/algorithms/resetp_alns/runtime/LICENSE-N-WOUDA-ALNS.md`，源文件明确标注为修改副本 | Wouda、Lan（2023），DOI `10.21105/joss.05028`；Ropke、Pisinger（2006），DOI `10.1287/trsc.1050.0135` |
| 机制裁决双盆地选择 | 官方 HGS 产生一份替代客户顺序；当前 ALNS 起点与替代顺序经同一车型、补能、碳时刻完成和完整成本复算后选一个搜索盆地 | 本项目独立设计；实现于 `baselines/algorithm_prototypes/unified_mechanism_alns_20260719/dual_basin_solver.py` | 选择规则未复制第三方源码；HGS 组件继续履行官方 HGS-CVRP MIT，ALNS 组件继续履行 N-Wouda ALNS MIT | 双盆地二选一是本项目依据失败诊断提出，不冒充现成论文算法；HGS 搜索背景引用 Vidal 等（2012、2022），ALNS 引用 Ropke、Pisinger（2006） |
| 有条件中段机制校正 | 选择当前 ALNS 盆地且预算足够时，依次校正跨场责任、车型—补能和低碳充电时刻；校正结果若进入后续搜索，按 G0 消耗一次完整候选评价 | 调用本项目 v5/v6/v7 机制实现；调度实现在 `dual_basin_solver.py` | 只依据论文结构独立实现，未复制无许可证 HGS-IRP 源码 | 结构启发：Zhao 等（2025），arXiv `2506.03172`；车型/补能分层：Hiermann 等（2016），DOI `10.1016/j.ejor.2016.01.038`，Hiermann 等（2019），DOI `10.1016/j.ejor.2018.06.025`；固定路线充电：Froger 等（2019），DOI `10.1016/j.cor.2018.12.013`；低碳充电择时：Cheng 等（2022），DOI `10.1109/SMARTGRIDCOMM52983.2022.9960988`；跨场责任：Soriano 等（2023），DOI `10.1016/j.ijpe.2022.108669` |
| SISR成段移除 | HGS子代内部的大改探针 | 本项目独立接口实现 | 未复制论文源码 | Christiaens、Vanden Berghe（2020），DOI `10.1287/trsc.2019.0914` |
| 后悔插入 | SISR后的修复 | 本项目独立实现 | 未复制无许可源码 | Ropke、Pisinger（2006），DOI `10.1287/trsc.1050.0135` |
| 精确路线仓库重组 | 混合HGS与ALNS产生的互补路线 | 本项目用`scipy.optimize.milp`独立实现隔离原型 | SciPy为BSD-3-Clause；当前只调用公开接口，不复制第三方实现 | Kelly、Xu（1999），DOI `10.1287/ijoc.11.2.161`；Dumez等（2021），DOI `10.1016/j.ejtl.2021.100040`；Hiermann等（2019），DOI `10.1016/j.ejor.2018.06.025` |
| HGS-IRP | “路线改进—机制大改—路线改进—回群体”的结构参照 | commit `61af0f43166719322f41916c36967bdeef01990c` | 上游根目录未发现许可证，不把源码复制进ReSETP；保留主页、提交和论文引用 | Zhao、Archetti、Pham、Vidal（2025），arXiv `2506.03172` |

`run_pyvrp_route_core_worker.py`调用MIT许可的PyVRP公开接口；其中`SISRRegretEducator`依据已发表思想独立编写，没有复制HGS-IRP源码。仓库主页给出的推荐引用可以作为学术引用保留，但不能代替源码许可证。无许可证源码只允许理解方法和独立实现；MIT源码允许迁移，但版权声明与许可证全文必须随副本保留。

官方 HGS-CVRP 在本项目完整模型里只能写成“官方 HGS 路线来源加本项目
ReSETP 完成器”。多车场拆分、时间窗近似、车型、充电、碳、公平和动态需求
均不是官方 HGS-CVRP 的原生能力。双盆地选择和中段调度是本项目自研规则；
引用相关论文用于说明方法背景，不能把它们写成论文作者已经提供的现成算法。
