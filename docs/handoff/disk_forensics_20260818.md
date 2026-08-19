# 系统盘清理与一次性配置方案（2026-08-18）

## 先说结论

- `FACT（用户已测）`：系统卷上次撞墙时只剩约 3GiB，现在约有 20GiB 可用；主线临时目录迁到移动硬盘后，系统盘压力已经缓解。
- `FACT（本轮实测）`：当前最大的可再生缓存是 `~/.cache/uv`，共 **2.16GiB**；但两个正在运行的 `browser-use` AI 工具正从里面加载文件，**现在不能清**。完全退出相关 AI 工具并确认 `lsof +D "$HOME/.cache/uv"` 无输出后，才是低风险清理项。
- `FACT（本轮实测）`：当前最大的 AI 硬占用是 Claude 的 `vm_bundles`，实际分配 **10.09GiB**。它今天仍在更新，是 Claude Cowork 的现行虚拟机，不是僵尸；删除会让功能失效或重新下载，且本轮未找到可靠的迁移配置。
- `FACT（本轮实测）`：不必退出全部 AI 就能优先处理的明确残留，是废纸篓中两个旧 ReSETP 质量环境约 **347.5MiB**，以及 `/private/tmp/claude-501/-Volumes------512G--ReSETP/b0b3cff2-8881-445a-9722-3342e28df4bb` 这份无进程占用的 Claude 临时目录约 **203.0MiB**。两者仍须用户批准后才能删。
- `CORRECTION`：Codex 的 3.1G 会话归档不是一大批无关僵尸。按实际占用统计，其中约 **3.02GiB 属于 ReSETP**，其他工作约 **120MiB**；若执行“保留最近 30 天 + 保留全部 ReSETP”，只可直接删掉约 **71MiB** 的 30 天前非项目归档。
- `FACT（本轮实测）`：`logs_2.sqlite` 是 Codex 运行日志库，不是会话正文。文件约 1.21GiB，其中约 **1.03GiB 是已经空出来、但尚未归还给文件系统的 SQLite 页面**。退出所有 Codex 进程后做增量压缩，预计可回收接近 1.03GiB，不需要先删现存日志。
- `FACT（本轮实测）`：`/opt/anaconda3` 占 **5.1G**，但它不是僵尸：ReSETP 外盘上的现行虚拟环境直接链接它的 Python 3.13，Claude 的 Zotero/Matlab MCP 等进程也正在使用它。现在删除会直接破坏工作环境。
- `DECISION（建议）`：永久迁移 pip/uv 缓存；全局 `TMPDIR` 和 `XDG_CACHE_HOME` 保持系统默认。外盘临时目录只给单个长任务按需启用，因为拔盘时全局 `TMPDIR` 会把 AI 会话、Git、Python 和构建工具一起拖死。
- `CORRECTION（执行异常）`：并行取证过程中，一次本应只读的 `brew list --versions` 查询自动刷新了 Homebrew API 索引，更新了 `~/Library/Caches/Homebrew/api/internal/` 下 4 个缓存文件；它们当前合计约 29.4MiB。这个自动写入超出了“只写报告”的要求，本支线没有为掩盖它而再次删除或回滚缓存。

除上述 Homebrew 自动缓存刷新外，本支线没有删除或移动任何文件，也没有修改项目中的其他文件；唯一主动写入的项目文件是本报告。主线会话在同一时段自行产生的质量报告和清理动作不计入本支线，也未被本支线干预。

## 0. 统一主表

大小均按文件系统实际分配块数计；`UNKNOWN` 表示本轮不能诚实地给出峰值或归属。建议栏只是清理方案，不代表已经执行。

| 路径 | 大小 | 属于谁 | 本可以放移动硬盘吗 | 建议 | 删了会失去什么 | 恢复难度 |
|---|---:|---|---|---|---|---|
| 系统 `$TMPDIR/tmp*` 中的 8 个 Semgrep 基线工作副本（事故现场，现已自动消失） | 峰值 `UNKNOWN`；系统盘曾从约 21GiB 降至约 3GiB | 本项目质量工具 | **可以，而且现轮已这样修** | 每次质量命令单独设外盘 `TMPDIR`；不全局设置 | 删除活跃副本会中断检查；事故残留现已不存在 | 自动重建，但会重跑 |
| `/Volumes/移动硬盘（512G）/tmp_quality/...` | 取证时活跃；最终复核时已由主线自行结束并清理 | 本项目质量工具 | 已在移动硬盘 | 运行时严禁触碰；现路径已不存在 | 当轮质量检查现场 | 需重跑 |
| 项目 `.quality-venv` | 2.12GiB | 本项目 | 已在移动硬盘 | 保留 | Semgrep、pre-commit 等正式质量环境 | 中等，可按 wheelhouse 重建 |
| `tools/quality/wheelhouse` | 96.5MiB | 本项目 | 已在移动硬盘 | 保留 | 离线重建质量环境的 172 个 wheel | 中等，需重新下载 |
| `build/python_envs` | 6.21GiB | 本项目 | 已在移动硬盘 | 保留，按复现合同另行审查 | 封存实验的解释器与依赖 | 困难 |
| 项目 `.git` | 2.14GiB | 本项目 | 已在移动硬盘 | 保留 | 版本历史、对象与 worktree 元数据 | 困难 |
| 项目源码树中的 `__pycache__` / `.pytest_cache` / `.ruff_cache` | 368.1 / 2.8 / 4.1MiB | 本项目 | 已在移动硬盘 | 可删但收益次要；不碰当前主线 | Python 字节码和测试/检查缓存，下次重建 | 容易 |
| `~/.Trash/ReSETP-quality-venv-offline-check-20260818*` | 347.5MiB | 本项目旧试建环境 | **本应留在移动硬盘或及时清理** | 用户批准后清空这两个精确目录 | 两个已废弃的质量环境试建副本 | 容易重建 |
| `~/.cache/uv` | 2.16GiB | Python/uv，部分由本项目与 AI 工具产生 | 可以 | **待两个 `browser-use` 进程退出后**用 uv 官方命令清 | uvx 环境、下载包和构建缓存 | 容易，但需联网和时间 |
| `~/Library/Caches/pip` | 112.8MiB | Python/pip，共享 | 可以 | 用户批准后用 pip 官方命令清 | 下载缓存 | 容易 |
| `~/.codex/python_envs` 与 `~/.codex/venvs/resetp-main3b-20260816` | 246.8 + 85.8MiB | Codex / 本项目 | 可以新建在外盘；现有路径已入历史记录 | 保留或带清单冷迁，不直接删 | 封存结果的复算路径 | 困难 |
| `/opt/anaconda3` | 5.11GiB | 共享 Python；本项目正在依赖 | 新装时可以，现状不能直接搬 | 保留 | 外盘 ReSETP venv 的基础解释器及多个 MCP | 困难，需成套重建 |
| `/opt/homebrew` | 7.83GiB | 系统/用户共享工具 | 可在安装时另选前缀，现状不应为本项目搬 | 只登记，不建议整库清理 | 大量个人软件及依赖 | 困难 |
| `~/.codex/archived_sessions` | 3.14GiB | Codex；约 3.02GiB 属 ReSETP | 可以冷迁到外盘 | 旧 ReSETP 约 2.03GiB可归档；非项目旧档逐份确认 | 原位置里的会话续接与搜索便利 | 文件易恢复，应用索引不确定 |
| `~/.codex/sessions` | 1.60GiB | Codex；含当前会话 | 可以设计新存储，但无已验证配置 | 保留 | 当前/近期会话正文 | 困难 |
| `~/.codex/logs_2.sqlite` | 1.21GiB；其中约 1.03GiB 空页 | Codex | 可备份到外盘；活库位置不擅改 | 全部 Codex 退出后增量压缩 | 不删现存日志，只回收空页 | 容易，先备份 |
| `~/.codex/sqlite/logs_2.sqlite` | 193.8MiB | Codex 旧日志库 | 可以归档 | 无进程占用；用户确认后归档/删除 | 旧运行日志 | 中等 |
| `~/.codex/packages` | 538MiB | Codex | 应由应用管理，不手工迁 | 两个旧 release 和死链接需用户确认 | 旧 App 运行包，可能重下 | 容易至中等 |
| `~/.codex/plugins` | 447.6MiB | Codex | 部分技术上可，当前配置有绝对路径 | 保留；`.plugin-appserver` 258.6MiB 另行确认 | 插件及 App 回退运行副本 | 中等 |
| `~/.cache/codex-runtimes` | 1.86GiB | Codex | 当前主 runtime 路径写入配置 | 保留 1.55GiB 主 runtime；可清 313MiB 安装残留 | 两个失败/旧安装 payload | 容易重下 |
| `~/.claude/projects` | 343.1MiB | Claude；约 338MiB 属 ReSETP | 无已验证配置 | 保留 | 当前项目转录与续接能力 | 困难 |
| `~/.claude/plugins` | 40.8MiB | Claude | 无必要 | 保留 | 插件缓存/市场记录 | 容易重建但收益小 |
| `~/Library/Application Support/Claude/vm_bundles` | **10.09GiB 实占** | Claude Cowork | 本轮未找到可靠迁移开关 | **保留，属于不可回收硬占用** | Claude Cowork 虚拟机；可能重下 10GiB | 困难且会复发 |
| `~/Library/Application Support/Claude/{Cache,Code Cache}` | 310 + 87.1MiB | Claude | 可再生但通常由应用管理 | Claude 完全退出后可清 | GUI/代码缓存，下次重建 | 容易 |
| `/private/tmp/claude-501/-Volumes------512G--ReSETP/b0b3cff2-8881-445a-9722-3342e28df4bb` | 203.0MiB | Claude 旧会话临时目录 | 可以 | 无进程引用；用户批准后清 | 一份 8 月 16 日旧临时现场 | 容易 |
| `/private/tmp/claude-501/-Volumes------512G--ReSETP/caf32b49-1ef5-47ec-b671-e10b80cf9c56` | 170.7MiB | Claude 当前会话 | 可以，但当前正在使用 | **保留** | 当前 Claude 会话文件 | 困难，可能中断会话 |
| `/private/var/vm` | 1.00GiB | 系统 | 否 | 保留 | macOS 交换/休眠相关状态 | 系统管理 |
| `/private/var/db` | 2.41GiB | 系统 | 否 | 保留 | macOS 数据库与服务状态 | 困难 |

### 0.1 本项目为何会写进系统盘

- `FACT`：项目仓库、正式质量环境、wheelhouse 和主要实验环境都在移动硬盘；本轮后续质量 worktree 也确实改到了移动硬盘。
- `FACT`：Python 工具没有设置 `TMPDIR`、`UV_CACHE_DIR`、`PIP_CACHE_DIR`；因此临时工作副本走 macOS 系统临时卷，uv/pip 走用户目录默认缓存。外盘项目位置不会自动改变这些工具的默认目录。
- `FACT`：事故报告中的 8 个并行 Semgrep 基线 checkout 在系统临时卷写满后，子进程以 `ENOSPC` 退出；目录自动清理后，系统盘空闲量又恢复到约 20GiB。这解释了“项目明明在外盘，系统盘却突然少约 18GiB”。
- `FACT（时序更正）`：取证早段 Git 还登记 6 个指向旧系统临时目录的 `prunable` worktree；本报告没有处理。主线随后自行清掉 14 条失效登记。最终只读复核时 `git worktree list` 只剩外盘主 worktree，不再有这项残留。
- `FACT`：历史 P80 长跑曾把中间产物放在 `/tmp`，系统清理后丢失。现行边界是：系统临时目录只容纳可丢的过程文件；长跑、正式结果和被引用产物必须落项目目录。

事故原始证据在 `solver/reports/w0_foundation_20260818/resume_attempt_20260818_semgrep_halt/report.md`；P80 的当前边界记录在 `docs/handoff/CURRENT_PROJECT_CONTEXT.md` 和 `docs/paper_gci_dmm_vrp_20260804/pending_decisions.md`。本报告引用它们，不改动它们。主线后来生成的 `resume_attempt_20260818_external_tmp_semgrep_timeout/report.md` 进一步确认：外盘 `TMPDIR` 下最低仍有约 57GiB，没有再发生系统临时卷写满；新失败是 300 秒 checkout 超时，属于另一问题。

### 0.2 系统盘可见范围 Top 30

这是本轮在当前权限下能量出的、尽量避免父子目录重复计算的 30 个大头。完整扫描 `/System/Volumes/Data` 两次都超过本轮终端窗口；照片、邮件、信息、MobileSync、CloudDocs 等受 macOS 权限保护，故这不是“全盘数学意义上的完整 Top 30”。用户自己的文件和应用只登记，不建议删除。

| 排名 | 路径 | 实占 | 归属/与本任务关系 | 处理口径 |
|---:|---|---:|---|---|
| 1 | `~/Library/Application Support/Claude/vm_bundles` | 10.09GiB | Claude 现行虚拟机 | 保留，硬占用 |
| 2 | `/Applications/MATLAB_R2025b.app` | 8.68GiB | 用户应用 | 只登记 |
| 3 | `/opt/homebrew` | 7.83GiB | 系统/用户工具 | 只登记 |
| 4 | `/opt/anaconda3` | 5.11GiB | 共享且 ReSETP 正在依赖 | 保留 |
| 5 | `~/.codex/archived_sessions` | 3.14GiB | Codex，多数属 ReSETP | 可冷归档 |
| 6 | `/Library/Developer` | 3.03GiB | 系统开发工具 | 只登记 |
| 7 | `/Applications/Microsoft Word.app` | 2.69GiB | 用户应用 | 只登记 |
| 8 | `/Applications/Microsoft Excel.app` | 2.50GiB | 用户应用 | 只登记 |
| 9 | `/Library/Application Support/Adobe` | 2.49GiB | 用户应用支持 | 只登记 |
| 10 | `/private/var/db` | 2.41GiB | 系统 | 保留 |
| 11 | `/Applications/Microsoft PowerPoint.app` | 2.19GiB | 用户应用 | 只登记 |
| 12 | `~/.cache/uv` | 2.16GiB | Python/AI/部分项目 | 进程退出后可清 |
| 13 | `~/.cache/codex-runtimes` | 1.86GiB | Codex | 保留主 runtime，清安装残留 |
| 14 | `~/Library/Application Support/Google` | 1.80GiB | 用户应用数据 | 只登记 |
| 15 | `/private/var/folders` | 1.80GiB | 系统临时与应用缓存 | 不整目录清理 |
| 16 | `~/.codex/sessions` | 1.60GiB | Codex 当前/近期会话 | 保留 |
| 17 | `/Applications/Google Chrome.app` | 1.37GiB | 用户应用 | 只登记 |
| 18 | `/Applications/ChatGPT.app` | 1.34GiB | AI 应用 | 只登记 |
| 19 | `~/Library/Containers/com.tencent.xinWeChat` | 1.27GiB | 用户数据 | 只登记 |
| 20 | `/Applications/Visual Studio Code.app` | 1.24GiB | 用户应用 | 只登记 |
| 21 | `~/.codex/logs_2.sqlite` | 1.21GiB | Codex，约 1.03GiB 是空页 | Codex 全退后压缩 |
| 22 | `/Library/Frameworks` | 1.07GiB | 系统/语言框架 | 只登记 |
| 23 | `/Library/Updates` | 1.04GiB | 系统更新 | 交给 macOS 管理 |
| 24 | `/Library/Application Support/Blackmagic Design` | 1.02GiB | 用户应用支持 | 只登记 |
| 25 | `/private/var/vm` | 1.00GiB | 系统 | 保留 |
| 26 | `~/Library/Application Support/MathWorks` | 0.91GiB | 用户应用数据 | 只登记 |
| 27 | `/Applications/Doubao.app` | 0.81GiB | 用户应用 | 只登记 |
| 28 | `/Applications/Claude.app` | 0.78GiB | AI 应用本体 | 保留 |
| 29 | `/Applications/LibreOffice.app` | 0.78GiB | 用户应用 | 只登记 |
| 30 | `/Library/Audio` | 0.67GiB | 用户/系统音频内容 | 只登记 |

## 1. 两个 AI 存储里哪些是僵尸

### 1.1 Codex 会话：时间和项目归属

统计方法：只读每个 JSONL 的首行 `session_meta.payload.cwd` 判断项目归属，用实际分配块数计算磁盘占用；没有扫描会话正文。30 天分界取 **2026-07-19**。

| 存储 | 时间范围 | 2026-06 | 2026-07 | 2026-08 | ReSETP 实占 | 其他工作实占 |
|---|---|---:|---:|---:|---:|---:|
| `~/.codex/archived_sessions` | 2026-06-08 至 2026-08-16 | 110 个 | 379 个 | 241 个 | 3,092.6MiB | 119.8MiB |
| `~/.codex/sessions` | 2026-06-10 至 2026-08-18 | 2 个 | 52 个 | 413 个 | 1,611.6MiB | 26.0MiB |

归档会话进一步拆分：

| 归属 | 最近 30 天 | 30 天以前 | 判断 |
|---|---:|---:|---|
| ReSETP | 317 个，1,062.9MiB | 309 个，2,029.7MiB | 按“保留当前项目”不能删；可考虑移到外盘冷存档 |
| 其他工作 | 36 个，48.8MiB | 68 个，71.0MiB | 68 个旧归档是直接清理候选，但“工作是否已经结束”仍需用户确认 |

`UNKNOWN`：仅凭工作目录和日期，不能证明那 68 个非项目会话对应的工作已经结束。因此报告把它们列入“需用户确认”，不把“旧”自动写成“废”。

推荐保留规则：

1. 保留最近 **30 天**的全部会话。
2. 无论日期，保留 ReSETP 会话；30 天以前的 ReSETP 归档若要腾空间，迁到移动硬盘冷存档，不删除。
3. 只清理 30 天以前、工作目录不是 ReSETP、且用户确认已经结束的 `archived_sessions` 文件。
4. `sessions` 不做批量删除；它包含当前或仍可续接的会话。

### 1.2 Claude 会话

| 项目目录 | 时间范围 | JSONL 数 | 实占/目录占用 | 判断 |
|---|---|---:|---:|---|
| ReSETP | 2026-07-11 至 2026-08-18 | 226 | 目录约 338M | 当前项目，保留 |
| `/Users/zhouleixishu` | 2026-07-19 至 2026-08-10 | 20 | 约 4M | 数量很小，无优先清理价值 |
| `/private/tmp` | 2026-07-30 | 1 | 小于 0.1M | 可确认后删除，但几乎不释放空间 |

Claude 的 344M `projects` 中，约 338M 就是 ReSETP。按“最近 30 天 + 当前项目”规则，几乎没有可回收量。

Claude 本地目录逐类核对如下；本机没有单独名为 `todos` 或 `shell_snapshots` 的目录，对应内容分别落在 `tasks` 和 `session-env`：

| `~/.claude` 类别 | 实占 | 保留价值/判断 |
|---|---:|---|
| 整体 | 397.2MiB | 不是清理大头 |
| `projects` | 343.1MiB | 绝大多数是当前 ReSETP 转录，保留 |
| `plugins` | 40.8MiB | 插件缓存与 marketplace，收益小，保留 |
| `file-history` | 3.6MiB | 文件历史，保留 |
| `history.jsonl` | 2.2MiB | 命令/交互历史，保留 |
| `session-env` | 2.1MiB | shell 环境快照，供会话恢复，保留 |
| `telemetry` | 1.9MiB | 可归档但收益很小 |
| `cache` | 0.48MiB | 可再生，收益可忽略 |
| `tasks`（含 todos） | 136KiB | 当前任务状态，保留 |
| `plans` | 208KiB | 计划记录，收益可忽略 |

Claude App 另有 `~/Library/Application Support/Claude` **11.08GiB**：其中 `vm_bundles` 实占 10.09GiB；`Cache` 310MiB、`Code Cache` 87.1MiB；`claude-code` 281MiB、`claude-code-vm` 259MiB。后两者和虚拟机都是现行运行组件，只有普通 Cache/Code Cache 可在完全退出 Claude 后重建。

### 1.3 Codex 根目录逐类核对

`~/.codex` 合计 **7.86GiB**，不能把整个目录叫“日志”或“僵尸”，内部同时有当前会话、项目记忆、技能、运行包和可清残留：

| `~/.codex` 类别 | 实占 | 保留价值/判断 |
|---|---:|---|
| `archived_sessions` | 3.14GiB | 多数是 ReSETP；旧项目会话优先冷迁，不直接删 |
| `sessions` | 1.60GiB | 含当前会话，保留 |
| 根目录 `logs_2.sqlite` | 1.21GiB | 活跃日志库；约 1.03GiB 空页，退出 Codex 后压缩 |
| `packages` | 538MiB | 两个旧 standalone release，需用户确认 |
| `plugins` | 447.6MiB | 当前配置、缓存与运行副本混合，不能整删 |
| `python_envs` | 246.8MiB | ReSETP 封存复算环境，保留 |
| `.tmp` | 244.7MiB | marketplace/安装过程材料混合，未证明为纯僵尸，不批量删 |
| `sqlite/logs_2.sqlite` | 193.8MiB | 旧库、无活进程引用，可冷归档 |
| `cache` | 20MiB | 应用缓存，收益低 |
| `skills` | 12.4MiB | 当前技能定义，保留 |
| `memories` | 5.7MiB | 当前项目记忆与历史证据索引，保留 |

此外，`~/Library/Application Support/Codex` 约 263.6MiB，`~/Library/Caches/Codex` 约 76.9MiB，属于 App 数据/可再生缓存；收益小于上表的明确大头，不能与会话正文混为一谈。

### 1.4 `logs_2.sqlite` 是什么，怎样安全瘦身

只读检查得到：

- 只有两个业务表：迁移记录表和 `logs` 表；`logs` 字段包括时间、级别、模块、文件、线程、进程和日志正文。
- 共 **164,255 行**，时间覆盖 **2026-08-08 12:28:54 至 2026-08-18 12:20:54**。它保存的是最近约 10 天 Codex 运行日志，不是 6–8 月会话原文。
- 数据库完整性检查返回 `ok`；使用 WAL 日志模式和 `auto_vacuum=INCREMENTAL`。
- 文件有 317,065 个 4KiB 页面，其中 268,973 页在 freelist：约 **1.03GiB 空页**；仍在用的页面约 188MiB。
- 当前有 **3 个 Codex 进程**打开该数据库，故本轮不能压缩。

SQLite 官方说明：增量自动回收模式不会在每次提交后自动缩文件，必须显式执行 `PRAGMA incremental_vacuum` 才会归还空页；见 [SQLite PRAGMA 官方说明](https://www.sqlite.org/pragma.html#pragma_incremental_vacuum)。

安全压缩步骤（本轮不执行）：

```zsh
# 1. 完全退出 Codex 的所有窗口和后台会话；这里必须无输出
lsof "$HOME/.codex/logs_2.sqlite"

# 2. 把备份放到移动硬盘，避免备份本身再占 1.2G 系统盘
mkdir -p '/Volumes/移动硬盘（512G）/.ai-backups/codex'
cp -p "$HOME/.codex/logs_2.sqlite" \
  '/Volumes/移动硬盘（512G）/.ai-backups/codex/logs_2.sqlite.before-vacuum-20260818'

# 3. 归还空页并复核数据库
sqlite3 "$HOME/.codex/logs_2.sqlite" \
  'PRAGMA wal_checkpoint(TRUNCATE); PRAGMA incremental_vacuum; PRAGMA integrity_check;'

# 4. 重新看文件大小，再启动 Codex
ls -lh "$HOME/.codex/logs_2.sqlite"
```

`DECISION（建议）`：以后每月或在大量会话/日志清理后，退出全部 Codex 再执行一次增量压缩。当前没有在本机配置或 OpenAI 官方资料中找到 Codex 自带的保留天数/轮转开关，因此不建议自行删表内旧行；只回收已空页面已经能解决约 1.03GiB。

### 1.5 `python_envs`、`packages`、`plugins` 的重复和废弃情况

#### `~/.codex/python_envs`：247M，两个都不是僵尸

| 环境 | 大小 | 当前证据 | 结论 |
|---|---:|---|---|
| `pyvrp-frozen-0.12.2` | 80M | ReSETP 多个封存结果的解释器与哈希路径直接引用 | 保留 |
| `setp-independent-hgs` | 167M | ReSETP 多个技术试验 metadata 直接引用 | 保留 |

两者都使用 uv 管理的 Python 3.13.12。它们与外盘 `build/python_envs/...` 不是简单重复：前者已经进入历史结果的复现路径，删除会破坏可复算性。

#### `~/.codex/packages`：538M，发现两个旧运行包和 68 个死链接

- `0.142.5-aarch64-apple-darwin`：242M。
- `0.143.0-aarch64-apple-darwin`：296M。
- `current` 下有 68 个按旧 PID 命名的符号链接：65 个指向 0.142.5、3 个指向 0.143.0；对应 PID 现在全部不存在。
- 当前 `current/codex` 实际指向 `/Applications/Codex.app/.../codex`；终端 `codex` 是 Homebrew/npm 的 **0.147.0**。没有进程或打开文件引用上述两个旧 release。

`INFERENCE`：这 538M 很像旧版 Codex App 的遗留运行包，删除后最可能的后果是旧组件需要重新下载；但这是应用内部目录，未找到官方清理命令，所以列入“需用户确认”，不写成绝对安全。

#### `~/.codex/plugins`：448M，没有发现同一来源内的多版本堆积

- 普通插件缓存约 189M；扫描版本目录没有发现同一插件并存多个语义版本。
- `openai-curated` 与 `openai-curated-remote` 有同名插件，但当前配置分别引用本地插件和远端 hook，不能只因同名就把整组当重复删除。
- 隐藏目录 `.plugin-appserver` 占 **259M**（`codex` 209M、`codex-code-mode-host` 49M）。当前进程使用的是 npm 安装目录里的对应二进制，没有打开这里的文件；它是候选遗留副本，但可能是 App 的回退副本，故仍需用户确认。
- `.remote-plugin-install-staging` 为 0B。

Claude 插件共 41M，其中缓存 16M、marketplaces 24M；没有足够收益，不建议优先动。

#### `~/.cache/codex-runtimes`：1.9G，只有安装残留可在用户批准后清

| 内容 | 大小 | 引用情况 | 结论 |
|---|---:|---|---|
| `codex-primary-runtime` | 1.5G | `~/.codex/config.toml` 当前明确引用 | 不动 |
| `codex-runtime-install-ZwwJBM` | 287M | 2026-08-14 后未更新，无配置/进程引用 | 安装残留，可清 |
| `codex-runtime-install-fj1lx9` | 26M | 2026-08-13 后未更新，无配置/进程引用 | 安装残留，可清 |

## 2. 项目往系统盘写了什么

### 2.1 pip、uv 和 AI 缓存

| 项目 | 当前实际位置 | 大小 | 本可以放移动硬盘吗 | 影响 |
|---|---|---:|---|---|
| pip 缓存 | `~/Library/Caches/pip` | 113M（pip 报 117.2MB） | 可以 | 清除/拔盘只影响后续 pip 下载与构建 |
| uv 缓存 | `~/.cache/uv` | 2.2G | 可以 | 外盘与环境不在同一文件系统时，uv 会从链接优化退化为复制，安装更慢、占用可能更大 |
| uv 管理 Python | `~/.local/share/uv/python` | 56M | 可以迁，但不建议和本轮缓存迁移混做 | 已有虚拟环境记录旧解释器位置，迁后需重建或核对 |
| 整个 `~/.local` | `~/.local` | 493.6MiB | 部分可以，不能整目录迁 | 其中 `share/claude` 约 266.7MiB，另有 uv Python 和用户命令；都是共享运行状态，不是 ReSETP 专属垃圾 |
| Codex runtime | `~/.cache/codex-runtimes` | 1.9G | 技术上可，但当前配置写死内部路径 | 直接搬会让文档/表格/PDF 等运行插件失效 |
| Codex GUI 缓存 | `~/Library/Caches/Codex` | 77M | 可再生，但收益小 | 下次启动重建 |
| CodexBar | `~/Library/Caches/CodexBar` | 89M | 可再生，但与本项目无直接证据 | 下次启动重建 |
| Claude CLI 缓存 | `~/Library/Caches/claude-cli-nodejs` | 7.6M | 可以 | 收益很小 |
| OpenAI CUA 缓存 | `~/Library/Caches/com.openai.sky.CUAService` | 4.1M | 可以 | 收益很小 |
| node-gyp | `~/Library/Caches/node-gyp` | 62M | 可以 | 下次原生 Node 构建需重新下载头文件 |

本轮唯一一次限深度 `~/Library/Caches/*` 排行中，没有发现另一个与 Python/ReSETP 直接相关、且大于 uv 的缓存。uv 官方说明 `uv cache clean` 会清空缓存，`uv cache prune` 只删除不可达/过时对象；不要手工删 uv 缓存内部文件。见 [uv 缓存官方说明](https://docs.astral.sh/uv/concepts/cache/) 和 [uv 存储位置说明](https://docs.astral.sh/uv/reference/storage/)。pip 的正式清理命令是 `python -m pip cache purge`，见 [pip 官方文档](https://pip.pypa.io/en/stable/cli/pip_cache/)。

### 2.2 `/private/tmp` 残留

当前系统 `TMPDIR` 实际是 `/var/folders/.../T/`，不是 `/private/tmp`。当前 `$TMPDIR` 约 216.6MiB，`/private/tmp` 约 388.8MiB，`/private/var/tmp` 约 107.5MiB。本轮没有触碰已经迁到外盘的主线 worktree。

明确可量出的三处旧取证临时目录：

| 目录 | 大小 | 最后修改 | 活进程引用 | 判断 |
|---|---:|---|---|---|
| `goeke-page.lZnGqb` | 1.9M | 2026-08-17 | 未发现 | 可确认后清 |
| `decoder-literature-review-20260817.dLEhU2` | 3.3M | 2026-08-17 | 未发现 | 可确认后清 |
| `resetp-rivals-pdf.6cevou` | 6.0M | 2026-08-17 | 未发现 | 可确认后清 |

合计约 **11.2M**，收益很小。`/private/tmp/claude-501` 当前明确有 Claude 进程使用；`codex-browser-use`、`cc-socks` 等也是当前或近期会话设施，不动。两个 `browser-use-downloads-*` 目录均为 0B。

本轮还检查了“文件已经被删、但进程仍占着磁盘块”的情形：大于 10MiB 的命中只有 macOS LaunchServices 约 12MiB 的 `csstore` 映射，不属于 ReSETP、Codex 或 Claude，也不足以解释空间告急。

`/private/tmp/claude-501` 不能整目录处理，内部状态不同：

- `.../b0b3cff2-8881-445a-9722-3342e28df4bb` 约 **203.0MiB**，最后修改为 8 月 16 日，本轮 `lsof` 未发现任何进程引用，属于当前证据下的纯僵尸候选。
- `.../caf32b49-1ef5-47ec-b671-e10b80cf9c56` 约 **170.7MiB**，有当前 Claude 进程打开文件，仍在使用，严禁删除。
- 其余同级会话目录实际分配为 0B，删除也不能释放有意义的空间。

### 2.3 conda / Anaconda 与 Homebrew Python

| 内容 | 大小 | 与本项目/当前进程的关系 | 本可以放移动硬盘吗 |
|---|---:|---|---|
| `/opt/anaconda3` | 5.1G | 外盘 ReSETP venv 的 `python3.13` 是指向这里的符号链接；Claude MCP 和多个 Python 进程正在使用 | 新建时可以放外盘，但当前不能直接搬；须重建 venv、改 MCP 路径并验证后才可卸载 |
| Anaconda `pkgs` | 523M | `conda clean --all --dry-run` 只找到 15.7M tarballs；无未使用包 | 包缓存可放外盘，但当前几乎没有可安全清的包 |
| Homebrew Python 3.12 | 81M | 未发现 ReSETP venv 引用，Homebrew 也未列出已装依赖者 | 可卸载但需用户确认个人脚本是否使用 |
| Homebrew Python 3.14 | 88M | `openai-whisper`、`yt-dlp` 依赖 | 不动 |
| python.org Framework 3.11 / 3.14 | 311M / 772M | 本轮没有证据归属于 ReSETP | 不纳入本轮清理 |

`FACT`：ReSETP 的外盘虚拟环境已经把包放在移动硬盘，但基础解释器仍来自系统盘 `/opt/anaconda3`；这就是为什么删 Anaconda 会让“外盘环境”也立即坏掉。

## 3. 一次性配置方案

### 3.1 推荐边界

建议在移动硬盘建立：

```text
/Volumes/移动硬盘（512G）/.ai-cache/
├── pip/
├── uv/
├── conda-pkgs/       # 仅未来 conda 下载缓存，可选
└── tmp/              # 只给单个长任务临时启用
```

永久迁移 pip/uv 这类可再生缓存；不迁整个 `~/Library/Caches`，不迁当前 `codex-primary-runtime`，不把所有程序的临时目录绑到移动硬盘。对本项目的 Semgrep、测试和其他会生成大批临时副本的长命令，**逐条**把 `TMPDIR` 指到外盘，这才是防止本次事故复发的首要配置。

### 3.2 环境变量清单

| 变量 | 建议 | 是否写入全局配置 | 拔盘后的真实表现 |
|---|---|---|---|
| `PIP_CACHE_DIR` | 指向外盘 `.ai-cache/pip` | 条件式设置 | pip 安装仍可能运行，但缓存目录无法写时可能报错；不影响已装包和 AI 会话正文 |
| `UV_CACHE_DIR` | 指向外盘 `.ai-cache/uv` | 条件式设置 | uv 每次都要求可用缓存目录；拔盘后 uv 命令会失败，已运行的 AI 会话一般不因此退出 |
| `CONDA_PKGS_DIRS` | 指向外盘 `.ai-cache/conda-pkgs` | 可选、条件式 | conda 安装/更新会失败；已运行的 Python 环境不依赖这个包缓存 |
| `CONDA_ENVS_PATH` | 不设置 | 否 | 现有环境位置复杂，直接改只影响新环境，还会制造两套位置 |
| `XDG_CACHE_HOME` | 不设置 | 否 | 它会把大量不相关工具一起迁走；拔盘影响面过大，并且不会自动修正 Codex 配置里的绝对路径 |
| `TMPDIR` | 保持 macOS 默认 | 否 | 这是避免拔盘拖死 AI、Git、Python、编译器的关键 |
| `UV_PYTHON_INSTALL_DIR` | 本轮不设置 | 否 | 改后已有 venv 仍指向旧解释器，需重建；不应与简单缓存迁移混做 |

### 3.3 写在哪个文件

`DECISION（建议）`：把下面条件式配置写入 `~/.zshenv`。原因是 Codex 和 Claude 当前的命令子进程都通过 zsh 启动；新开的命令 shell 会读取 `.zshenv`。现有已经运行的进程不会被追溯修改，需要新开 shell；图形界面 App 本身也不会仅因 `.zshenv` 自动获得变量，但它启动的 zsh 命令会读取。

```zsh
# AI/Python 可再生缓存：仅在移动硬盘已挂载且目录可写时启用
AI_CACHE_ROOT='/Volumes/移动硬盘（512G）/.ai-cache'
if [[ -d "$AI_CACHE_ROOT" && -w "$AI_CACHE_ROOT" ]]; then
  export PIP_CACHE_DIR="$AI_CACHE_ROOT/pip"
  export UV_CACHE_DIR="$AI_CACHE_ROOT/uv"
  export CONDA_PKGS_DIRS="$AI_CACHE_ROOT/conda-pkgs"
else
  unset PIP_CACHE_DIR UV_CACHE_DIR CONDA_PKGS_DIRS
fi
```

首次配置命令（本轮不执行）：

```zsh
mkdir -p \
  '/Volumes/移动硬盘（512G）/.ai-cache/pip' \
  '/Volumes/移动硬盘（512G）/.ai-cache/uv' \
  '/Volumes/移动硬盘（512G）/.ai-cache/conda-pkgs' \
  '/Volumes/移动硬盘（512G）/.ai-cache/tmp'

# 在写入 ~/.zshenv 前，先退出所有使用 uv 缓存的 AI 工具；这里必须无输出
lsof +D "$HOME/.cache/uv"

# 确认无输出后再清当前系统盘上的旧缓存
uv cache clean --cache-dir "$HOME/.cache/uv"
python3 -m pip cache purge

# 写入后，新开终端/AI 命令 shell并核对
python3 -m pip cache dir
uv cache dir
```

这里故意不提供“永久 `export TMPDIR=外盘`”。如果确有单个长任务需要外盘临时空间，只对该命令设置，并在开跑前检查外盘：

```zsh
AI_TMP='/Volumes/移动硬盘（512G）/.ai-cache/tmp'
[[ -d "$AI_TMP" && -w "$AI_TMP" ]] || { echo '移动硬盘未挂载，任务未启动' >&2; return 72; }
TMPDIR="$AI_TMP/" <长任务命令>
```

本项目 Semgrep 质量检查可直接采用下面这条具体命令；每轮可换一个独立子目录，结束后再由该轮负责人按现场决定是否清理：

```zsh
QUALITY_TMP='/Volumes/移动硬盘（512G）/.ai-cache/tmp/semgrep-project-rules'
mkdir -p "$QUALITY_TMP"
[[ -d "$QUALITY_TMP" && -w "$QUALITY_TMP" ]] || { echo '外盘临时目录不可写，质量检查未启动' >&2; return 72; }
TMPDIR="$QUALITY_TMP/" .quality-venv/bin/pre-commit run semgrep-project-rules --all-files
```

### 3.4 拔盘风险：必须接受的事实

- **启动前未挂载**：条件式 `.zshenv` 会回退到工具默认缓存；AI 会话可以启动。
- **会话中途拔盘**：已经继承外盘 `PIP_CACHE_DIR`/`UV_CACHE_DIR` 的 pip、uv 命令可能失败；普通对话、Git 和不使用这些缓存的 Python 不会仅因这两个变量而整体崩溃。
- **长任务使用外盘 `TMPDIR` 后中途拔盘**：该任务可能立即 I/O 报错、产物不完整，无法通过配置彻底规避。只能在任务期间不拔盘。
- **若全局设置外盘 `TMPDIR`**：影响会扩大到几乎所有子进程，可能直接打断 Codex/Claude 的工具调用。因此本方案明确不这样做。
- **uv 性能**：官方要求缓存与虚拟环境尽量位于同一文件系统。ReSETP 主环境也在外盘，因此对主项目有利；但系统盘上的 `~/.codex/python_envs` 与外盘缓存跨文件系统，新建/更新时会退化为复制，速度较慢。

## 4. 行动清单

以下全是建议命令，本轮一个都没有执行。

先按可回收空间从大到小给出总顺序；后面的 A–C 再按“是否要退出程序、是否还需用户判断”分组给精确命令。

| 总排名 | 动作 | 可回收 | 执行前提 |
|---:|---|---:|---|
| 1 | 清 uv 缓存 | 2.16GiB | 两个 `browser-use` 及其 Python 子进程全部退出 |
| 2 | 旧 ReSETP Codex 会话冷迁外盘 | 2.03GiB | 用户接受原位置不再直接可用；逐文件复制校验 |
| 3 | Codex 活跃日志库增量压缩 | 1.03GiB | 全部 Codex 退出并先备份 |
| 4 | 两个旧 Codex standalone release | 538MiB | 用户接受可能重新下载；Codex 退出 |
| 5 | Claude `Cache` + `Code Cache` | 397MiB | Claude App 完全退出 |
| 6 | 废纸篓两个旧质量环境 | 347.5MiB | 用户批准 |
| 7 | 两个 Codex runtime 安装残留 | 313MiB | 用户批准；保留主 runtime |
| 8 | Codex `.plugin-appserver` 副本 | 258.6MiB | 用户接受可能重建/下载 |
| 9 | Claude `b0b3…` 僵尸临时目录 | 203.0MiB | 施工时再次确认无进程引用 |
| 10 | Codex 旧 `sqlite/logs_2.sqlite` | 193.8MiB | 先冷归档并校验 |
| 11 | pip 缓存 | 112.8MiB | 用户批准 |
| 12 | Homebrew Python 3.12 | 81MiB | 证明没有个人脚本依赖 |
| 13 | 68 个旧非 ReSETP Codex 归档 | 71MiB | 用户确认相应工作均已结束 |
| 14 | conda tarballs | 15.7MiB | 用户批准 |
| 15 | 三个旧取证临时目录 | 11.2MiB | 用户确认材料已经归档 |

### A. 用户批准后、无需退出全部 AI 即可做

| 顺序 | 动作与精确命令 | 实测可回收 | 会失去什么 | 风险 |
|---:|---|---:|---|---|
| 1 | 复核无进程引用后清 Claude 旧临时目录：`lsof +D '/private/tmp/claude-501/-Volumes------512G--ReSETP/b0b3cff2-8881-445a-9722-3342e28df4bb'`；确认无输出后 `rm -rf '/private/tmp/claude-501/-Volumes------512G--ReSETP/b0b3cff2-8881-445a-9722-3342e28df4bb'` | 约 203.0MiB | 8 月 16 日一份未被引用的临时现场 | 低；绝不能清同级当前活跃的 `caf32b49-1ef5-47ec-b671-e10b80cf9c56` |
| 2 | 清废纸篓内两个精确旧环境：`rm -rf "$HOME/.Trash/ReSETP-quality-venv-offline-check-20260818" "$HOME/.Trash/ReSETP-quality-venv-offline-check-20260818-final"` | 约 347.5MiB | 两个已经进入废纸篓的质量环境试建副本 | 低；不影响外盘正式 `.quality-venv` |
| 3 | `rm -rf "$HOME/.cache/codex-runtimes/codex-runtime-install-ZwwJBM" "$HOME/.cache/codex-runtimes/codex-runtime-install-fj1lx9"` | 约 313MiB | 两个已停止更新、无配置和进程引用的安装暂存 payload | 低；不要把同级 1.55GiB `codex-primary-runtime` 加进命令 |
| 4 | `python3 -m pip cache purge` | 约 112.8MiB | 432 个 HTTP 缓存文件；以后重新下载 | 低；没有本地构建 wheel |
| 5 | `/opt/anaconda3/bin/conda clean --tarballs -y` | 15.7MiB | 已下载 conda 压缩包；以后可能重新下载 | 低；dry-run 已确认无未使用包可清 |

这一档合计约 **0.97GiB**。实际施工前仍要重新执行表中的 `lsof` 复核，不能把本轮的“无占用”当作永久状态。

### B. 关闭相应程序后可做

| 顺序 | 动作与精确命令 | 实测可回收 | 会失去什么 | 风险/前提 |
|---:|---|---:|---|---|
| 1 | 完全退出两个 `uv tool uvx ... browser-use` 及其 Python 子进程；确认 `lsof +D "$HOME/.cache/uv"` 无输出后执行 `uv cache clean --cache-dir "$HOME/.cache/uv"` | 约 2.16GiB | uvx 环境、下载包和构建缓存；以后重新下载/构建 | 当前有活进程直接加载其中的 `.so`，未退出前不能清 |
| 2 | 完全退出 Claude App；确认 `lsof +D "$HOME/Library/Application Support/Claude/Cache"` 和 `lsof +D "$HOME/Library/Application Support/Claude/Code Cache"` 均无输出后执行 `rm -rf "$HOME/Library/Application Support/Claude/Cache" "$HOME/Library/Application Support/Claude/Code Cache"` | 约 397MiB | GUI 与代码缓存，下次启动重建 | 不动 `vm_bundles`、`claude-code`、`claude-code-vm` |
| 3 | 退出全部 Codex，按 §1.4 备份并执行 `PRAGMA incremental_vacuum` | 接近 1.03GiB | 不删现存日志，只归还空页面 | 当前 Codex 正在写；必须全退出并先备份 |

前两档合计约 **3.52GiB**；再做 Codex 日志库压缩，合计可到约 **4.55GiB**。这是各项实测值相加，不承诺 `df` 一定逐字节增加相同数量；APFS 快照、稀疏文件和应用立即重建缓存都会造成差异。

### C. 需用户进一步确认

| 顺序 | 动作与精确命令 | 可回收 | 会失去什么 | 风险/前提 |
|---:|---|---:|---|---|
| 1 | 删除旧 standalone 包：`rm -rf "$HOME/.codex/packages/standalone/releases/0.142.5-aarch64-apple-darwin" "$HOME/.codex/packages/standalone/releases/0.143.0-aarch64-apple-darwin"`；再清死链接：`find "$HOME/.codex/packages/standalone/current" -type l -name '.current.*' -delete` | 538MiB | 旧 App 运行包和 68 个死链接；需要时可能重新下载 | 本轮未找到官方清理接口；先完全退出 Codex |
| 2 | 删除未被当前进程使用的插件运行副本：`rm -rf "$HOME/.codex/plugins/.plugin-appserver"` | 258.6MiB | App 的潜在回退副本；可能自动重建/下载 | 当前运行用 npm 副本，但内部回退行为未有官方保证 |
| 3 | 把 30 天前的 ReSETP Codex 归档迁到外盘冷存档 | 约 2.03GiB 系统盘空间 | 不丢文件，但这些会话不再直接出现在原 Codex 归档位置 | 必须先生成精确清单、复制校验后再移除源文件；本报告不把批量移动伪装成单条安全命令 |
| 4 | 归档或删除无活进程引用的旧库 `~/.codex/sqlite/logs_2.sqlite` | 约 193.8MiB | 6 月前后的旧 Codex 运行日志 | 先移到外盘并核对，再决定删源文件 |
| 5 | 卸载 Homebrew Python 3.12：先复核 `brew uses --installed python@3.12` 为空，再执行 `brew uninstall python@3.12` | 约 81MiB | 个人脚本若写死该解释器会失败 | ReSETP 未引用，但本轮不能证明其他个人任务不用 |
| 6 | 删除 30 天前、非 ReSETP 的 68 个 Codex 归档 | 约 71MiB | 对应旧工作的完整会话记录 | 需先由用户确认这些工作确已结束；不建议为 71MiB 冒误删风险 |
| 7 | `rm -rf /private/tmp/goeke-page.lZnGqb /private/tmp/decoder-literature-review-20260817.dLEhU2 /private/tmp/resetp-rivals-pdf.6cevou` | 约 11.2MiB | 三份临时取证副本 | 虽无活进程引用，仍可能是尚未归档的取证材料；收益很小 |

说明：C 组第 3 项虽然可回收更多，但它会改变会话的日常可访问位置，不能只凭“保留项目”四个字替用户决定。若用户选择冷存档，应另做一次“清单 → 复制 → 哈希核对 → 再移除源文件”的独立动作。

C 组第 3 项的精确执行命令如下；它对每个文件先复制、逐字节核对，核对成功后才移除系统盘源文件：

```zsh
CODEX_ARCHIVE_SRC="$HOME/.codex/archived_sessions"
CODEX_ARCHIVE_DST='/Volumes/移动硬盘（512G）/.ai-archives/codex/resetp-before-2026-07-19'
mkdir -p "$CODEX_ARCHIVE_DST"

find "$CODEX_ARCHIVE_SRC" -type f -name 'rollout-*.jsonl' -print0 |
while IFS= read -r -d '' f; do
  session_day=$(basename "$f" | sed -E 's/^rollout-([0-9]{4}-[0-9]{2}-[0-9]{2}).*/\1/')
  IFS= read -r first_line < "$f" || first_line=''
  if [[ "$session_day" < '2026-07-19' && \
        "$first_line" == *'"cwd":"/Volumes/移动硬盘（512G）/ReSETP"'* ]]; then
    target="$CODEX_ARCHIVE_DST/$(basename "$f")"
    cp -p "$f" "$target" && cmp -s "$f" "$target" && rm -- "$f" || exit 1
  fi
done
```

C 组第 4 项的精确冷归档命令如下；核对成功前不会移除系统盘源文件：

```zsh
OLD_CODEX_DB="$HOME/.codex/sqlite/logs_2.sqlite"
OLD_CODEX_DB_ARCHIVE='/Volumes/移动硬盘（512G）/.ai-archives/codex/logs_2.sqlite.old-20260818'
mkdir -p "$(dirname "$OLD_CODEX_DB_ARCHIVE")"
lsof "$OLD_CODEX_DB"
# 上一行必须无输出；随后复制、核对，成功后才移除源文件
cp -p "$OLD_CODEX_DB" "$OLD_CODEX_DB_ARCHIVE" && \
  cmp -s "$OLD_CODEX_DB" "$OLD_CODEX_DB_ARCHIVE" && \
  rm -- "$OLD_CODEX_DB"
```

C 组第 6 项先用下面的预览命令列清单；用户确认清单后，把最后的 `printf` 一行替换为 `rm -- "$f"` 执行。这里不直接给“无预览删除”，因为“非 ReSETP”不等于“工作已经结束”。

```zsh
find "$HOME/.codex/archived_sessions" -type f -name 'rollout-*.jsonl' -print0 |
while IFS= read -r -d '' f; do
  session_day=$(basename "$f" | sed -E 's/^rollout-([0-9]{4}-[0-9]{2}-[0-9]{2}).*/\1/')
  IFS= read -r first_line < "$f" || first_line=''
  if [[ "$session_day" < '2026-07-19' && \
        "$first_line" != *'"cwd":"/Volumes/移动硬盘（512G）/ReSETP"'* ]]; then
    printf '%s\n' "$f"
  fi
done
```

### D. 不建议动

| 对象 | 原因 |
|---|---|
| `/opt/anaconda3` 5.1G | 当前 ReSETP 外盘 venv、Claude Zotero/Matlab MCP 和多个进程都依赖；直接删会立刻损坏环境 |
| `~/.cache/codex-runtimes/codex-primary-runtime` 1.5G | 当前 `config.toml` 明确引用，负责文档/表格/PDF 等插件运行时 |
| `~/.codex/python_envs` 247M | 两个环境都进入 ReSETP 历史结果的解释器路径，关系到复现 |
| `~/.codex/sessions` / Claude ReSETP projects | 混有当前会话，且绝大多数就是当前项目 |
| 整目录删除 `~/.codex/plugins/cache` | 多个 marketplace 和 hook 正被配置引用；同名不等于可替换副本 |
| Homebrew Python 3.14 | `openai-whisper`、`yt-dlp` 已安装依赖 |
| 永久设置外盘 `TMPDIR` / `XDG_CACHE_HOME` | 拔盘故障范围过大，且 XDG 不会修复 Codex 已写死的 runtime 路径 |
| `/private/tmp/claude-501` 整目录、`codex-browser-use`、未知哈希目录 | 其中混有当前会话或归属不明；只能处理主表点名且施工时再次确认无引用的精确子目录 |

### 4.1 不可回收的硬占用

- Claude `vm_bundles` 的 **10.09GiB** 是当前最大的 AI 占用，但今天仍在使用。删除后会失去 Cowork 虚拟机并很可能重新下载，不能把它计入稳定可回收空间。
- `/opt/anaconda3` 的 **5.11GiB** 是 ReSETP 外盘虚拟环境的基础解释器，也是其他 MCP 的共享运行时。除非另开迁移任务、重建所有引用并验证，否则不能回收。
- `/opt/homebrew`、系统 `/private/var/db`、`/private/var/vm`、用户应用和用户数据不是本项目垃圾；本报告只登记，不把它们包装成清理收益。
- `.quality-venv`、wheelhouse、`build/python_envs`、项目 `.git` 已经在移动硬盘，不占系统盘。它们再大也不能解释本次系统盘写满。

## 5. 最终建议顺序

1. 先把本项目所有会大量创建临时副本的质量命令改成**逐条使用外盘 `TMPDIR`**；主线当前已经这样运行，不改全局 `TMPDIR`。
2. 用户批准后，先清两份废质量环境、Claude 明确僵尸目录、两个 Codex 安装残留、pip 与 conda 下载缓存，约 **0.97GiB**。
3. 等两个 `browser-use` 工具完全退出，再清 uv 缓存，约 **2.16GiB**；它目前不是“立即可删”。
4. 等 Claude/Codex 相应程序全部退出，再清 GUI 缓存并压缩 `logs_2.sqlite`，合计再约 **1.43GiB**。
5. 写入条件式 pip/uv 外盘缓存配置。若仍缺空间，再由用户决定旧 Codex 包、插件副本和 2.03GiB 老 ReSETP 会话的冷迁。

## 给用户的直接答复

最大一块**关闭占用进程后可回收**的空间是 uv 缓存，实测 **2.16GiB**；它现在仍被两个 AI 浏览器工具直接使用，不能立刻清。最大的 AI 总占用其实是 Claude Cowork 虚拟机 **10.09GiB**，但这是现行功能的硬占用，不是僵尸，也没有证据证明迁走后能稳定工作。

最该先修的配置不是 uv，而是**本项目质量命令的临时目录**：Semgrep 的 8 个并行基线副本默认落系统 `$TMPDIR`，正是本次从约 21GiB 掉到约 3GiB并写满的直接原因。做法是只给这类命令设置外盘 `TMPDIR`；随后再把 `UV_CACHE_DIR`、`PIP_CACHE_DIR` 条件式指向移动硬盘。绝不能全局永久改 `TMPDIR`，否则中途拔盘会把 Git、Python 和 AI 工具一起打断。
