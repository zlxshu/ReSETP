# 借用 BKS 方法 + 混合算法设计（已联网查证，Codex复核后部分降级）

> **2026-07-19 现行边界：** 本文只保留为方法地图和来源调查，不再决定算例或
> 对手。用户已批准按陈雨蝶式分工重建为“公开 X-100 + China81”，对手按外部强手
> 与母算法/组成算法分组；权威合同为
> `docs/handoff/algorithm_comparison_foundation_20260719.md`。下文任何“按题族借
> 不同核心”或 Solomon/Homberger 主战场建议均不得覆盖新合同。

- 编号：ALGO-BKS-BORROW-DESIGN-001
- 日期：2026-07-19
- 状态：`PARTIALLY_ACCEPTED_AS_BACKGROUND__CVRP_SUBSTITUTION_REJECTED`
  （`formal_search_allowed=false`；外部代码接入/许可证仍须逐项落地核实）
- 方法：Claude 联网查证当前 VRP BKS 来源方法与开源状态，再据此设计。来源见文末。
- 目标读者：Codex、任何接手 ReSETP 算法线的代理

---

## 0. 一句话

**别再自研一个打不过 HGS 的路由器——BKS 是一套已知、开源的方法跑出来的，直接把每个题族最强的那个"借"过来当核心；你的创新加在上面。** 查证还纠正了一个我之前的错：**大规模 CVRP 的当前王者不是 HGS，是 AILS-II**。

### 0.1 Codex复核后的强制更正

本文的 AILS-II 数字只适用于无时间窗 CVRP，不能拿来替代 ReSETP 的 VRPTW 公开
基准。CVRPLIB XL 报告也写明 HGS-CVRP 原设计和校准规模至多约1000客户，XL比较
没有为它重调参数；因此“AILS-II在XL表胜HGS”是真实结果，但不是“它在本论文问题
上普遍胜HGS”的证据。本文第3--6节凡把“大CVRP胜HGS”直接算作ReSETP公开目标完成
的说法全部降级为题族外背景，不得进入主论文胜负表。

另一个必须纠正的逻辑是：“强化层只收改善，所以等墙钟下不可能输核心”不成立。
强化动作会占用核心搜索时间并改变种群轨迹；2026-07-19 的 `HGS-AEALNS-03`
实测正是2胜2平2负。单次候选不倒退不等于整机同时间不倒退。

---

## 1. 查证结果：BKS 到底是谁跑出来的（硬数据）

来自 2026-01 的 CVRPLIB XL 挑战赛权威报告（arXiv:2601.11467）与各方法原始仓库：

### 1.1 CVRP（无时间窗）当前 SOTA，按题规模分

| 题规模 | 当前最强方法 | 类型 | 许可 / 语言 | 仓库 | 硬成绩 |
|---|---|---|---|---|---|
| **大规模 XL（1k–10k 客户）** | **AILS-II** ⭐ | 元启发（自适应 ILS） | **MIT / Java** | `INFORMSJoC/2023.0106`、`vinymax10/AILS-CVRP` | **XL 100 题拿 93 个 BKS，平均 gap 0.07%** |
| 大规模 XL 次席 | FILO2 | 元启发（ILS 局部化） | 开源 / C++ | `acco93/filo2` | 6/100，gap 0.21%，可跑 100 万客户 |
| 大规模 XL | SISRs | 元启发（ruin-recreate） | 复刻可得 | — | gap 0.50% |
| 大规模 XL | KGLS^XXL | 元启发（知识引导 LS） | 开源 | `ArnoldF/LocalSearchVRPXXL` | gap 1.00% |
| **中小规模（X-n）** | **HGS-CVRP** | 元启发（HGS） | MIT / C++ | `vidalt/HGS-CVRP` | 中小最强；**但 XL 上 gap 1.36%** |
| 精确求最优 | **分支定价割 / VRPSolver** | 精确 | 开源（VRPSolverEasy，pip） | `inria-UFF/VRPSolverEasy` | **X 系 100 题证明最优 61 个**；XL 0 个证明最优 |

**关键**：LKH-3（gap 6.66%）、OR-Tools（6.81%）在大 CVRP 上明显落后，别用它们当核心。

### 1.2 VRPTW（带时间窗，= 你的 Solomon / Homberger 战场）

| 题族 | 当前最强方法 | 许可 / 语言 | 仓库 | 硬成绩 |
|---|---|---|---|---|
| **Solomon 100c / Gehring-Homberger 200–1000c** | **PyVRP / HGS-VRPTW**（同一 HGS 血统） | MIT / Python+C++ | **`PyVRP/PyVRP`（你仓库已有）** | **PyVRP 延长跑刷新了 300 个 Homberger BKS 中的 27 个** |
| 精确求最优 | VRPSolver | 开源 | VRPSolverEasy | 小题证明最优 |

**AILS-II 不支持时间窗（纯 CVRP）**，所以你的 Solomon 用不上它——VRPTW 的王者就是 PyVRP。

---

## 2. 核心判断：借，不要自研（有硬证据）

- **没有任何自研/homebrew 方法进得了 BKS 名单**。名单里全是 AILS-II / FILO2 / SISRs / KGLS / HGS / VRPSolver。你自研 ALNS 打不过 HGS，不是你工程差，是**你在跟标准答案制造者对着干**。教训你已交过学费：自己复刻 SISR → 失活淘汰。**别复刻，用官方开源实现。**
- **"BKS ≠ 数学天花板"你完全对**，但要精确分：
  - **精确解已证明最优的题**（X 系 61/100）= 真天花板，谁都超不了。
  - **未证明最优的题**（全部 XL、大 Homberger）= 有 headroom，现代方法每年在刷（PyVRP 刷了 27 个 VRPTW BKS）。**你的"超 BKS、拉开 5%"只可能在这里。**

## 3. 能不能"公开胜过 HGS"——查证后的精确答案（分题族，别再笼统）

- **VRPTW（Solomon/Homberger）：不能靠"借一个比 HGS 更强的方法"取胜——因为 VRPTW 的 BKS 方法就是 HGS/PyVRP 本身，没有更强的可借。** 现实路线：**用 PyVRP 当核心 → 构造上就是 HGS 级、绝不输**；小 Solomon 追平（多为最优），大 Homberger 靠充足预算 + 第 4 节的只收改善层去刷新老 BKS。
- **大规模 CVRP（CVRPLIB X/XL）：能——把核心从 HGS 换成 AILS-II，它是被验证的王者（93/100，gap 0.07% vs HGS 1.36%）。** 这是"公开胜过 HGS"唯一有硬证据的地方。**若你要一份"我碾 HGS"的公开跑分表，就把战场放在大规模 CVRP，用 AILS-II 当核心。**

## 4. 混合算法设计（三层，可施工）

```
借来的 SOTA 核心（按题族选）
        │  只收改善（不可能变差）
        ├── 强化层：LNS-kick + 集合划分重组
        │
        └── 机制层：碳/EV/多车场/公平/动态（借来方法都没有 → 你的真创新）
```

### 4.1 第 0 层：借来的 SOTA 核心（按题族，查证后的确定选择）

| 战场 / 题族 | 借哪个当核心 | 为什么 |
|---|---|---|
| 公开 VRPTW（Solomon/Homberger）+ 富模型 China81（多车场/异构车队/时窗） | **PyVRP** | VRPTW SOTA；原生支持多车场+异构车队+时窗+多趟；仓库已有 |
| 公开中小 CVRP（X-n） | **HGS-CVRP** 或直接 **VRPSolver 求最优** | 中小最强 / 可证最优 |
| 公开大规模 CVRP（XL 1k–10k）——"碾 HGS"主战场 | **AILS-II** | 验证过的王者，构造性胜 HGS |
| 公开超大 CVRP（10万–100万） | **FILO2** | 唯一能在普通机器上跑百万客户 |
| 小题最优保底/天花板锚 | **VRPSolver（VRPSolverEasy）** | 精确，给真"保底=最优" |

### 4.2 第 1 层：只收改善的强化（在核心之上开 gap，且构造上不可能输核心）

- **LNS-kick**：停滞时对精英解破坏 25–35% + 后悔修复，**只在严格更优时接受**。
- **集合划分重组**：把核心跑出的精英路线池喂给集合划分 MIP（可用 VRPSolver 的定价机做列），**只收更优**。
- **不变式**：因为两者只收改善，`混合体 ≤ 借来核心` 恒成立、`< 核心` 当它们抓到东西 → **构造性地不输核心，也就不输 HGS/PyVRP**，直接堵死"不如直接用现成的"。
- **诚实工程难点**：等墙钟下，强化层偷走核心的时间，所以必须**便宜 + 停滞触发**，其收益要 ≥ 偷的时间。这是这条路成不成的真关卡。
- 依据：AILS-II/FILO 本质就是"核心 + 自适应 ILS/局部化强化"；LNS+GA 混合有 Liu 2024 先例。

### 4.3 第 2 层：机制层（你的真创新，借来方法一个都没有）

碳强度 / 多车场 / 公平 / 协同 / 动态，五个算子（v7 已有几个在赢：车型-充电 25/50c 上 11–13%、多车场 108c −1.254%）。**借来的 SOTA 全是纯路由，对这些机制是瞎的**——这正是你"私有算例打爆纯开源"的底气：机制核心 vs 公平适配但机制瞎的裸开源，在完整模型上决定性赢。

## 5. 四个目标如何各自兑现（查证后可达版）

| 目标 | 兑现方式 | 现实结局 |
|---|---|---|
| 混合算法（看着高级） | 借来 SOTA 核心 + 只收改善强化 + 机制层 = 真三层混合 | ✓ |
| 每机制一个增强 | 机制层五算子，各自绑定区打赢删减版 | ✓（v7 已开局） |
| 公开跑分王 / 不输 HGS | VRPTW：PyVRP 核心构造性不输；**大 CVRP：AILS-II 核心构造性胜 HGS**；+ 强化层刷未证明最优的老 BKS；+ VRPSolver 小题保底 | ✓（大 CVRP 能碾；VRPTW 追平+刷大题） |
| 私有打爆纯开源 | 机制核心 vs 公平适配裸开源，完整模型上机制不瞎者胜 | ✓（真正主场） |

**诚实护栏（保护你不被拒稿）**：论文必须写明路由核心借自 PyVRP/AILS-II（不隐瞒），创新主张落在**强化层的可证增益 + 机制层的绑定区消融 + 大题新 BKS**；只照搬会被质疑"你就是跑了个 PyVRP/AILS-II"。

## 6. 给 Codex 的施工步骤

1. **海选与核实**（不自研、不复刻）：克隆 `PyVRP`、`vidalt/HGS-CVRP`、`vinymax10/AILS-CVRP`(或 `INFORMSJoC/2023.0106`)、`acco93/filo2`、`inria-UFF/VRPSolverEasy`，锁提交与许可证（已查：AILS-II=MIT/Java、PyVRP=MIT、FILO2 开源、VRPSolverEasy 开源），在各自题族对齐当前 BKS，复现各自公开成绩。
2. **选核心**：每个题族按复现成绩选最强核心（VRPTW→PyVRP；大 CVRP→AILS-II；超大→FILO2；小题→VRPSolver 保底）。
3. **接强化层**：在核心的 API/停滞钩子上加"只收改善的 LNS-kick + 集合划分重组"；等墙钟双账；证明不劣于纯核心。
4. **接机制层**：机制算子作用于核心解，非病灶 no-op；富模型上对公平适配裸开源做对决。
5. **双门**：公开门=不输对应 SOTA 核心 + 大题刷老 BKS；私有门=机制混合体碾公平裸开源。结果盲、预注册、保护文件零改、五件套。
6. **跨语言接线**：AILS-II(Java JAR)、FILO2(C++) 用子进程/文件接口调用（前有官方 HGS-CVRP 桥先例），最终解回本仓 `check/evaluate` 复算，避免两套真值。

## 7. 治理与边界

- 保护文件（`cost.py`/`check.py`/`search/evaluation.py`/`prices.py` 默认值/TeX）不改；跨模型语义走 `model_change_approval_register` 审批。
- 外部代码进独立目录、锁提交+许可证，不污染正式 runner；论文引用与许可证合规。
- 正式搜索、China81、E2–E7 重跑仍须单独批准。M1 唯一正式基准。

## 8. 来源（联网查证 2026-07-19）
- CVRPLIB XL BKS 挑战赛报告：arXiv:2601.11467（AILS-II 93/100、FILO2/KGLS/HGS/SISRs 成绩、X 系 61/100 证明最优）
- AILS-II：Máximo, Cordeau, Nascimento (2024), INFORMS JoC 36(4); `github.com/vinymax10/AILS-CVRP`（MIT, Java）、`github.com/INFORMSJoC/2023.0106`
- FILO/FILO2：Accorsi & Vigo；`github.com/acco93/filo`、`github.com/acco93/filo2`
- HGS-CVRP：Vidal (2022)；`github.com/vidalt/HGS-CVRP`（MIT）
- KGLS^XXL：`github.com/ArnoldF/LocalSearchVRPXXL`
- PyVRP：Wouda, Lan, Kool (2024), INFORMS JoC；`github.com/PyVRP/PyVRP`（MIT）；刷新 27/300 Homberger VRPTW BKS
- VRPSolver / VRPSolverEasy：Pessoa, Sadykov, Uchoa, Vanderbeck；`github.com/inria-UFF/VRPSolverEasy`（开源，pip）
