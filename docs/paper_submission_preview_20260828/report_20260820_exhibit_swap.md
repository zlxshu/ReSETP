# `docs/paper_v2` 数值实验展品替换施工报告

日期：2026-08-20

## 本轮目标与边界

`USER DECISION`：解封 `docs/paper_v2/RETIRED_paper_main.tex`，只把数值实验章换成用户指定来源中的 10 张表和 4 张实验图；删除全文表注、图注；保留引言、模型建立、算法设计、结语，以及算法章两张旧图；复制四个既有 PDF，不重新出图；最后用 XeLaTeX 编译并检查成品。

`FACT`：本轮没有运行求解器、实验或数据生成程序，没有修改任何数值，没有执行 `git commit` 或 `git push`。

## 1. 主文件解封

`FACT`：目标文件已由

`docs/paper_v2/RETIRED_paper_main.tex`

直接改名为

`docs/paper_v2/paper_main.tex`。

先尝试了 `git mv`，但当前执行环境不能创建 `.git/index.lock`，命令以退出码 128 结束，文件当时没有变化。随后按任务允许的另一种方式使用普通 `mv` 完成改名。因此当前 Git 视图显示旧文件删除、新文件未跟踪；文件内容和后续施工不受影响，Git 索引没有被写入。

## 2. 数值实验章删除的旧结构

`FACT`：从旧 `\section{数值实验}` 到 `\section{结语}` 之前的内容已整体移除。删除的小节或内容块如下：

1. “实验设计和最终解分析”，包括“实验设计”和“最终解分析”；
2. “算法有效性分析”，包括“公开标准算例实验”“公开算例最好解的边界探查”“本文模型实验”，以及其中的五臂分层、配对成本效应和性能剖面内容；
3. “历史客户归属与联合重分”；
4. “路线--车型--充电联合优化”；
5. “合作收益与联盟分配”；
6. “数值实验分析讨论”。

`FACT`：随这些内容删除的旧展品逐项如下：

1. 仿真算例节点信息表；
2. 车型参数；
3. 车场充电设施分时电能价格情景；
4. 三大城市群典型日电网碳强度曲线；
5. 仿真实验最终路径表；
6. MDVRPTW 标准算例结果表；
7. 公布最好解与本文热启动结果对比；
8. 不同算法对比表；
9. 不同算法迭代图（旧版）；
10. 中国三大城市群算例集五臂分层结果；
11. MV-HGS-SP 相对各对照臂的配对成本效应；
12. 五臂性能剖面覆盖率；
13. E2 算法性能剖面；
14. 历史客户归属固定与算法联合重分结果；
15. 路线--车型--充电联合优化的排放与成本变化；
16. 固定配送排班补充检验中的典型日电网碳强度和能量加权充电开始时刻分布；
17. 四承包商合作收益与分配结果。

## 3. 搬入的新结构与展品

`FACT`：数值实验章现在按下列顺序排列。表体、列结构、数值、小数位、`\TBD{}`、展品环境、题名和标签取自指定来源；四处 `\includegraphics` 只把来源目录的 `figures/...` 改成目标目录的 `generated_figures/...`。

| 小节 | 类型 | 标签 | 题名 |
|---|---|---|---|
| 4.1 算例与参数 | 表 | `tab:parameters` | 关键车辆、充电、电价与碳强度参数及来源 |
| 4.2 公开算例上的求解结果 | 表 | `tab:public28` | 公开算例上不同算法的求解结果 |
| 4.3 代表实例最终解 | 表 | `tab:final-solution` | 代表实例最终配送方案 |
| 4.4 本文算法收敛过程 | 图 | `fig:convergence` | 不同算法迭代图 |
| 4.5 时变碳强度下的充电时刻层 | 表 | `tab:carbon-charging` | 时变电网碳强度与充电选择规则对比 |
| 4.5 时变碳强度下的充电时刻层 | 图 | `fig:carbon-charging` | 电网碳强度、分时电价与充电负荷图 |
| 4.6 碳价情景扫描 | 表 | `tab:carbon-price` | 单位碳价情景扫描结果 |
| 4.7 混合车队车型指派层 | 表 | `tab:fleet-levels` | 混合车队可用名额与实际派遣对比 |
| 4.7 混合车队车型指派层 | 图 | `fig:fleet-carbon-price` | 不同碳价下混合车队车辆数图 |
| 4.8 动态需求响应层 | 表 | `tab:dynamic` | 动态需求响应方式对比 |
| 4.9 多车场配送协同 | 表 | `tab:synergy` | 多车场配送协同模式对比 |
| 4.9 多车场配送协同 | 图 | `fig:collaboration-fairness-routes` | 独立配送与联合配送最终路径图（示意） |
| 4.10 非线性充电对照 | 表 | `tab:nonlinear-charging` | 不同充电功率函数的账面求解与非线性回算对比 |
| 4.11 协同收益公平分配 | 表 | `tab:allocation` | 协同收益公平分配结果 |

对应位置的表前、表后、图前、图后正文也按来源搬入，包括代表实例最终解后的（1）（2）（3）分析和碳价表后的盈亏平衡碳价说明。

`FACT`：指定来源中的收敛图、充电图和混合车队图没有 LaTeX `\caption{}`，而是用 `\refstepcounter{figure}` 和 `\label{}`，题名在批准的 PDF 内；本轮保持这一既有环境，没有自行添加 `\caption{}`。协同路径示意图原本有 `\caption{}`，已原样保留。

`FACT`：目标导言区原先没有 `\TBD{}`。已把来源 `main.tex` 第 76--79 行的 `\DeclareRobustCommand{\TBD}` 定义原样加入导言区。

## 4. 表注、图注的逐处处理

全文检索结果中，旧主稿共有 14 处 `\tabnote`；没有 `\figurenote`，也没有数值实验章以外以“注:”或“注：”开头的表内、图内说明行。14 处处理如下：

| 位置 | 处理 |
|---|---|
| 仿真算例节点信息表后 | 随退役表整块删除；内容只解释旧广州/深圳算例的时间窗和节点口径，不迁入新展品。 |
| 车型参数表后 | 随退役表整块删除；新 4.1 节已用来源正文说明当前参数来源、单位、数据日期和 1 小时分辨率。 |
| 车场充电设施分时电能价格情景表后 | 随退役表整块删除；旧三城市群/深圳价区构造口径不迁入统一京津冀代表实例。 |
| 三大城市群典型日电网碳强度曲线后 | 随退役图整块删除；新 4.1 和 4.5 节正文已说明北京 2025-02-12、逐小时信息和 24 小时图形口径。 |
| 仿真实验最终路径表后 | 随退役表整块删除；新 4.3 节表前正文和表后（1）（2）（3）已承担实体车、多趟、固定成本、服务量和排放口径。 |
| MDVRPTW 标准算例结果表后 | 随退役表整块删除；新 4.2 节表前正文已说明 28 题、单次运行、完成客户和待补需求量口径。 |
| 公布最好解与本文热启动结果对比表后 | 随退役表和“边界探查”小节删除，不补写。 |
| 旧“不同算法对比表”后 | 随退役表删除，不补写。 |
| 中国三大城市群算例集五臂分层结果表后 | 随退役表删除；旧 China81、五种子和跨批汇总口径不迁入。 |
| MV-HGS-SP 相对各对照臂的配对成本效应表后 | 随退役表删除，不补写。 |
| 五臂性能剖面覆盖率表后 | 随退役表删除，不补写。 |
| 历史客户归属固定与算法联合重分结果表后 | 随退役表和小节删除，不补写。 |
| 路线--车型--充电联合优化的排放与成本变化表后 | 随退役表和小节删除，不补写。 |
| 四承包商合作收益与分配结果表后 | 随退役表和小节删除；新 4.9 与 4.11 节的正文分别承担协同效率和事后分摊口径。 |

`FACT`：新搬入的 10 张表和 4 张实验图在指定来源中本来就没有 `\tabnote`、`\figurenote` 或“注：”行，所以没有新增表注、图注。最终 `paper_main.tex` 对这三类文本的全文检索结果为 0。

`FACT`：引言的文献比较表和模型章的符号说明表本来没有表注，表体与正文均未改。

## 5. 图形文件

以下四个 PDF 已从只读来源原样复制到 `docs/paper_v2/generated_figures/`：

| 目标文件 | SHA-256 |
|---|---|
| `generated_figures/figure_2_algorithm_convergence.pdf` | `09608135abb22e6673514391c9be5a2c4103134b1f24c70f33e8d7dd3ca58809` |
| `generated_figures/figure_3_carbon_tariff_charging.pdf` | `b40dc5fd81be9f6d79f7342c708f190957e9e5afb481683c751186a5dc5118c6` |
| `generated_figures/figure_4_mixed_fleet.pdf` | `50839ad2f35b2268e1e127e1913e8939a7e80e17e09516248f1e629c4389b628` |
| `generated_figures/concept_collaboration_fairness_notitle.pdf` | `36cacec3427d1bec15e78c1a89fc6ddd33f42b98192f9b923710786bebce0ce0` |

每个目标文件的哈希都与对应来源文件一致，未重新生成、未改图。

## 6. 未改内容与范围核对

`FACT`：以 Git 中原 `RETIRED_paper_main.tex` 为基准，按章节边界逐字比较：引言、模型建立、算法设计、结语及其后的参考文献均完全相同。

`FACT`：算法流程正文、`\input{generated_figures/algorithm_flow.tex}` 和“三视角路线池与限时 MIP 重组示意”保持原样。

`FACT`：结语中没有指向被删旧展品的 `\ref{}`，因此没有改结语。

`FACT`：`docs/paper_v2/setp-new.cls` 未改，SHA-256 仍为 `66d2f99056efe522ab91afa2fd05c105ba7bc8d42e3a9c5cdc29c6cc0ec2efa5`。

`FACT`：三个受保护文件未改，任务前后 SHA-256 一致：

- `solver/src/setp_solver/cost.py`：`268147a7ac307c6e6a390e2e55cfb8f3e366d1b785157053d20a39dea26b6b86`；
- `solver/src/setp_solver/check.py`：`1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072`；
- `solver/src/setp_solver/search/evaluation.py`：`c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3`。

`FACT`：没有写入 `docs/paper_gci_dmm_vrp_20260804/` 或 `docs/paper_submission_final/`。工作区开始时这些目录已有其他未提交或未跟踪内容，本轮均保留。

## 7. 静态结构检查

`FACT`：当前 TeX 与“Git 中原主稿未改部分 + 指定来源片段 + 四处图片路径替换 + 来源 `\TBD` 宏”的机械重建结果逐字节一致。

`FACT`：当前 TeX 及既有算法流程输入文件静态统计为 12 个表标签、6 个图标签。这里包括数值实验章外原样保留的 2 张表，以及算法章原样保留的 2 张图。

表标签：

1. `tab:literature-comparison`
2. `tab:symbols`
3. `tab:parameters`
4. `tab:public28`
5. `tab:final-solution`
6. `tab:carbon-charging`
7. `tab:carbon-price`
8. `tab:fleet-levels`
9. `tab:dynamic`
10. `tab:synergy`
11. `tab:nonlinear-charging`
12. `tab:allocation`

图标签：

1. `fig:algorithm-flow`
2. `fig:route-pool`
3. `fig:convergence`
4. `fig:carbon-charging`
5. `fig:fleet-carbon-price`
6. `fig:collaboration-fairness-routes`

`FACT`：静态检查中，所有 `\ref{}` 和 `\eqref{}` 都能在当前 TeX 或算法流程输入文件中找到标签，缺失目标数为 0。

`HALT`：来源参数段使用 `\cite{ref:goeke-2015}` 和 `\cite{ref:chen-wanru-2023}`，而旧 `paper_v2` 参考文献中同两篇文献的键分别是 `ref:27` 和 `ref:23`。为遵守“对应正文逐字搬运”和“不改未授权内容”，本轮没有擅自替换引用键或修改参考文献。若直接编译，这两处会形成未解析文献引用；需要用户确认是否允许把两个键机械映射到旧稿已有的同篇文献。

当前 `paper_main.tex` 的 SHA-256 为 `e911e43d7678726d2423c8f65d47643c41cab99d8b541365e5ffa0d578c88113`。

## 8. XeLaTeX 编译结果与阻断

`HALT`：本轮没有生成新的 `paper_main.pdf`。

实际尝试如下：

1. 在 `docs/paper_v2/` 运行 `xelatex -interaction=nonstopmode -halt-on-error -file-line-error paper_main.tex`。进程在打开论文日志之前持续无输出，`paper_main.log`、`paper_main.aux` 和 `paper_main.pdf` 的时间均没有变化；终止后退出码为 130。
2. 用 `latexmk -xelatex -interaction=nonstopmode -halt-on-error -disable-installer paper_main.tex` 复查，同样在启动阶段无输出，终止后退出码为 1。
3. 在权限允许的 `/private/tmp` 建立本任务专用 MiKTeX 配置/数据目录，并进一步复制现有 MiKTeX 配置、格式缓存和已安装宏包形成 418 MB 的完整可写隔离副本；即使所有 MiKTeX 用户/公共根都指向该副本，`xelatex --version` 仍在会话初始化阶段无输出。
4. `latex:latex-doctor` 的最小烟雾测试也停在调用本机 MiKTeX 的子进程中，手动终止后退出码为 130。

这些现象共同说明当前 Codex 沙箱不能正常启动这台机器上的 x86_64 MiKTeX；不是某张新表、某个图片路径或当前 `paper_main.tex` 的编译错误。当前环境中没有第二套 XeLaTeX/TeX Live/MacTeX，且本轮没有改用用户明确禁止的 Tectonic，也没有安装新运行时。

因此用户要求的以下项目本轮不能给出新成品数据：

- XeLaTeX 至少两遍且退出码为 0；
- 新 `paper_main.aux` 的标签清单；
- 编译后 `??` 数量；
- 新日志中的 overfull、underfull 和图幅超页警告；
- 新 PDF 页数和 SHA-256；
- 新 PDF 逐页栅格化版面检查。

目录里现有的 `paper_main.aux`、`paper_main.log` 和 `paper_main.pdf` 都仍是 2026-08-01 的旧产物，不能冒充本轮结果：

- 旧 PDF：24 页，615905 字节；
- 旧 PDF SHA-256：`bb16c8f0950c563cabd811342c22995542aff2e0f0b58c15b112290ad3067f45`；
- 旧 PDF 修改时间：2026-08-01 23:42:57 +0800；
- 旧 aux 和旧 log 修改时间：2026-08-01 23:42:54 +0800。

## 9. 完成编译所需的最小后续动作

先需要用户确认一个纯机械兼容处理：

- 推荐：把新参数段的 `ref:goeke-2015`、`ref:chen-wanru-2023` 分别改成旧稿已有的 `ref:27`、`ref:23`。显示文字、文献内容和展品均不变；
- 或者：保持来源 TeX 逐字不变，在参考文献系统中另建两个别名。改动更复杂，不推荐。

引用键处理后，需要在当前沙箱之外、使用这台机器现有 MiKTeX 的终端执行至少两遍：

```bash
cd '/Volumes/移动硬盘（512G）/ReSETP/docs/paper_v2'
xelatex -interaction=nonstopmode -halt-on-error -file-line-error paper_main.tex
xelatex -interaction=nonstopmode -halt-on-error -file-line-error paper_main.tex
```

拿到新的 `paper_main.aux`、`paper_main.log` 和 `paper_main.pdf` 后，才能继续完成标签、`??`、警告、页数、SHA-256 与逐页栅格化检查，并把本报告第 8 节改成最终结果。

## 10. 本轮没有做的事

1. 没有修改两处引用键，因为任务要求逐字搬运且遇到实际不一致时停止，不自行猜。
2. 没有把 2026-08-01 的旧 PDF 当作新成品，也没有对它做本轮版面验收。
3. 没有通过重画、缩放、改宽度、改表体或删数据来规避任何潜在排版问题。
4. 没有更新项目总交接、当前事实源或待决表；本轮报告已经是用户指定的独立交付文件，且尚未完成编译收口。
5. 本任务不产生实验包，实验四件套不适用。
6. MiKTeX 排查时建立的 418 MB 临时副本仍在 `/private/tmp/restep-paper-v2-miktex.TxkVdR`；清理命令被当前环境的安全策略拒绝，本轮没有绕过限制。该目录不在项目仓库内，只含本轮复制的 MiKTeX 配置、格式缓存和宏包。
