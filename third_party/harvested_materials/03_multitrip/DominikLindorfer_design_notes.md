# DominikLindorfer/Computational-Logistics 多趟设计摘录

## 取证范围

- 仓库：<https://github.com/DominikLindorfer/Computational-Logistics>
- 固定提交：`4017842f4ab325c6b4d01a0f2bce7833a880003f`
- 对应材料：Dominik Lindorfer 的 JKU 硕士论文项目，README 指向 <https://epub.jku.at/urn:nbn:at:at-ubl:1-38493>
- 本文只概括实际读取到的结构和流程，不复制实现代码。

## 许可复核结论

结论：**未找到覆盖该仓库全部代码的开源许可，因此没有克隆或快照全仓。**

实际核查了以下位置：

1. 仓库根目录未找到 `LICENSE*`、`COPYING*`、`setup.py` 或 `pyproject.toml`；因而也不存在可核对的 Python 打包许可字段。
2. 当前 README 及可检索到的 13 次 README 历史提交（2020-10-03 至 2021-04-06）均未出现 MIT、BSD、Apache、GPL、license 或 copying 等全仓许可声明。最后一次 README 修改只是把论文占位链接换成 JKU 论文链接。
3. GitHub 仓库 About/侧栏未显示许可证。
4. 作者主页线索、JKU 论文页面和可检索的论文/技术报告信息中，未找到授权仓库代码再分发或采用某一开源许可证的声明。
5. `Simplified_A/B/src/boolinq.h` 内能检索到第三方头文件自身的许可文字，但它只覆盖该嵌入文件，不能解释为覆盖整个仓库。

因此，本轮只留下设计摘录；若日后作者补充明确许可证，再重新判断是否可做原样快照。

## 1. trip 在数据结构中的表示

结论：**路线构造阶段把每个 trip 当作一条独立 route；物理车辆不是在这里直接嵌套保存 trip 序列，而是在后续月台排程阶段把 route 转成 job，再把多个 job 串到同一辆实体车上。**

- 顶层解结构按“天 → 当天的 routes → 每条 route 的停靠序列”保存；route 内每个元素保存门店和需求量。来源：`MasterProject/src/MasterProject.cpp:178-179`。
- 初始路线生成中，每次外层循环都会新增一条 route，并把一个原型车辆的剩余载重重置为满载；这说明构造阶段的一条 route 就是一趟独立行程。来源：`MasterProject/src/metaheuristics.hpp:37-46`。
- 到月台排程阶段，每条优化后的 route 被转换成一个 `job`；`job` 保存允许开始时间、最晚开始时间、行驶时间、等待时间、载重和装货时间，随后再写入实体车编号和月台编号。来源：`MasterProject/src/datastructures.hpp:199-223`；转换入口见 `MasterProject/src/MasterProject.cpp:471-495`。
- 实体 `truck` 的每日任务表是多个 `(开始时间, 结束时间, job 编号, dock 编号)` 元组组成的列表，因此同一辆实体车可以按时间顺序承担多个 route/job。来源：`MasterProject/src/datastructures.hpp:56-65`。

可提取的局部设计：路径优化器可以继续把“一趟”当作独立路线；在路径确定后，再建立 `route -> job -> physical truck` 的第二层映射，实现实体车复用，而不必把物理车辆身份塞进每个路径邻域算子。

## 2. trip 的划分与生成逻辑

### 初始生成

- 只要当天仍有未完成需求，就开始一条新 route，并把可用载重重置为车辆容量。来源：`MasterProject/src/metaheuristics.hpp:37-46`。
- 新 route 先选择仍有需求且距离仓库最远的客户；本趟对该客户的交付量取“剩余需求”和“本车剩余容量”的较小值。来源：`MasterProject/src/metaheuristics.hpp:47-65`。
- 随后从当前客户出发选择距离最近、仍有需求且能满足时间窗的下一个客户；继续装入时仍受剩余容量约束。来源：`MasterProject/src/metaheuristics.hpp:67-124`，其中时间窗候选检查在 `:104-110`。
- 当车辆容量用完、没有时间窗可行的下一客户，或本日已无剩余需求时，本 route 结束；若仍有需求，外层循环另开新 route。没有找到另一套显式的“trip 对象切分器”。来源：`MasterProject/src/metaheuristics.hpp:37-124`。

### VND 后的需求修复

- 邻域改变路线后，`updateDemand` 按 route 顺序重新分配服务量；每进入一条 route 都把可用容量重置为整车容量，并删除已经满足或不再需要的停靠。来源：`MasterProject/src/metaheuristics.hpp:835-883`。
- `repair` 先利用已有 route 的剩余容量填补未服务需求；仍有需求时再追加新 route，直到剩余需求为零。来源：`MasterProject/src/metaheuristics.hpp:886-957`。
- 路线的最晚可开始时间、最早可开始时间、总行驶/服务时间及时间窗不可行性分别由路线评估函数计算。来源：`MasterProject/src/metaheuristics.hpp:708-819`；聚合入口见 `:822-833`。

没有找到由月台占用直接反向触发“拆一趟/另开一趟”的实现；trip 的初始划分先由容量与客户时间窗决定，月台冲突在后续排程层处理。

## 3. VND 邻域算子

### 路线层 VND（3 个邻域）

路线层循环在 `MasterProject/src/MasterProject.cpp:323-445`。实际启用的算子为：

1. **route swap**：在两条路线之间交换两个停靠点。调用 `routes_swap_2`：`MasterProject/src/MasterProject.cpp:372-376`；实现：`MasterProject/src/metaheuristics.hpp:1049-1103`。
2. **route relocate/move**：把一个停靠点从一条路线移到另一条路线。调用 `routes_move`：`MasterProject/src/MasterProject.cpp:377-381`；实现：`MasterProject/src/metaheuristics.hpp:1127-1169`。
3. **route 2-opt/reversal**：在单条路线内反转一个区段。调用 `routes_opt_2`：`MasterProject/src/MasterProject.cpp:382-386`；实现：`MasterProject/src/metaheuristics.hpp:1105-1125`。

候选解会重新核对服务量、容量和时间窗并按目标值决定是否接受；改进后邻域层级归零，否则进入下一邻域。来源：`MasterProject/src/MasterProject.cpp:401-445`。

在当前合并求解流程中，**未找到启用的 Or-opt、cross-exchange 或更长链式交换算子**。

### 月台/实体车排程层 VND（3 个邻域）

月台层循环在 `MasterProject/src/MasterProject.cpp:577-613`。实际启用的算子为：

1. **交换两辆车上的两个 job**：`docks_swap_2jobs_trucks`，调用 `MasterProject/src/MasterProject.cpp:593-597`；实现 `MasterProject/src/metaheuristics.hpp:495-554`。
2. **把一个 job 移到另一辆车**：`docks_move_job`，调用 `MasterProject/src/MasterProject.cpp:598-607`；实现 `MasterProject/src/metaheuristics.hpp:556-614`。
3. **同一辆车的 job 序列做 2-opt/区段反转**：`docks_opt_2`，调用 `MasterProject/src/MasterProject.cpp:608-613`；实现 `MasterProject/src/metaheuristics.hpp:454-493`。

## 4. 与月台/仓库排程的耦合

结论：**仓库实现了月台排程，但采用顺序分解：先独立优化多趟路线，再把每条路线转成装货 job，最后安排实体车辆和月台；不是路径与月台的联合同步搜索。** README 对这一结构的文字说明见 `README.md:7-18`。

具体接线如下：

1. 建立月台和实体车辆集合，并把路线层输出逐条转换成带时间窗、路线时长、载重和装货时长的 job。来源：`MasterProject/src/MasterProject.cpp:471-495`。
2. 初始月台解由 `initial_solution_docks` 生成。入口：`MasterProject/src/MasterProject.cpp:502-537`；主体：`MasterProject/src/metaheuristics.hpp:161-270`。
3. 排程器优先选择较早可用的实体车辆，再在车辆返回后寻找可容纳装货作业的月台空档；若装货结束超过该 route 的最晚可开始时间，则该排程失败。来源：`MasterProject/src/metaheuristics.hpp:198-270`。
4. 月台对象也维护按时间排列的 job 元组，形成与车辆日历对应的资源日历。来源：`MasterProject/src/datastructures.hpp:125-130`。
5. 月台层邻域改变 job 顺序或车辆归属后，会从受影响位置向后重排；上一趟返回时间约束下一趟的可开始时间，同时重新寻找月台空档并检查最晚开始时间。来源：`MasterProject/src/metaheuristics.hpp:340-438`。
6. 三个排程邻域每次提出变动后都会重新执行受影响的车辆/月台排程。来源：`MasterProject/src/metaheuristics.hpp:454-614`。

对本项目最直接的可用局部设计，是把“路径可行性”和“实体车/月台日历可行性”分成两个模块，并用 route 的最早/最晚开始时间、时长、载重和装货时长作为接口。该仓库没有实现让月台排程结果反向重构客户访问顺序的联合邻域。
