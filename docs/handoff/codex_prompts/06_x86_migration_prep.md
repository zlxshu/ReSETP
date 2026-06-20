# Codex 提示词 06｜x86 迁移准备（Scheme 3：盘单程去 M1 + GitHub 同步）

> Claude 写于 2026-06-20。user 选定 Scheme 3：x86(本机) 变成脱离大盘的独立 DR 训练机，大盘单程去 M1 并留在 M1。
> **本提示词只做迁移准备：刷新 GitHub + 把仓库复制到 x86 本地 D: + 验证脱盘能训。不训练、不删原盘 H:。**

## 0. 开工前必读
1. 仓库根 `HANDOFF.md`（单一事实源；尤其 §1 环境铁律 + 变更日志最新几条，含 Scheme 3 决策）。
2. 根目录 `AGENTS.md`/`CLAUDE-FABLE-5.md` 是 Claude 模型系统提示词，忽略。

## 1. 背景与目标
- 现状：仓库在外置盘 `H:\ReSETP`（exFAT），x86 正用它。两个 venv 在本地 `C:\Users\zlxshu\.venvs\`（不在盘上）。
- Scheme 3 要点：代码靠 GitHub(`zlxshu/ReSETP`, 私有) 在两机间同步；DR 产出极小(模型~几十KB+几个CSV/MD)，靠 U盘/网盘/`git add -f` 传，**不倒腾大盘回来**。`.gitignore` 已排除 `models/`、`solver/reports/`、`*.npy`、`Reference Algorithm/`（算例/报告/模型不在 git）。
- **本提示词目标**：①commit+push 刷新 GitHub（让 M1 能拉到最新代码）；②把仓库做成 x86 本地自包含副本 `D:\ReSETP`；③验证 x86 能脱离大盘从 `D:\ReSETP` 跑 DR 训练管线。**做完报告，等 user 拔盘去 M1。不训练、不删 H:\。**

## 2. 施工步骤（做完即报告；任一步出问题立即 HALT，别硬来）

### 步骤 0：提交并刷新 GitHub
0.1 `git -C H:\ReSETP status`：把所有未提交改动 stage+commit，包括 `HANDOFF.md`、`docs/handoff/codex_prompts/04_dr_curriculum_pilot_build.md`、`05_dr_curriculum_pilot_run.md`、`06_x86_migration_prep.md`、`docs/handoff/memory/feedback_communication_style.md` 等文档改动。message 写清"Claude DR pilot prompts + Scheme 3 migration docs"。
0.2 确认远程：`git -C H:\ReSETP remote -v` 应有 `zlxshu/ReSETP`。push 当前分支（应为 `codex/reporting-pipeline`）。**报告 push 后的 HEAD hash**，确认 GitHub 已是最新（M1 之后靠它拉代码）。
0.3 若 push 需要认证且失败 → HALT 报告（让 user 处理凭证），别卡住。

### 步骤 1：测体积、定复制方式
1.1 `du -sh H:\ReSETP .git models solver/reports "Reference Algorithm"`（git bash）测各大块体积；查 D: 盘可用空间。
1.2 决定复制方式并报告：
- **若 D: 空间充裕**（仓库总量 + 30% 余量 < D: 可用）→ **整盘复制**（最省事、自包含、带 .git 与 GitHub 远程）。
- **若 D: 空间紧**→ **精简复制**：含 `.git` + 所有 git 跟踪的代码/文档 + 训练评测要用的算例目录(`models/data_bundle/generated_instances/` 下：`E-UK100_02__u0_seed2_24h_20251113`、`E-UK100_03__u0_seed3_24h_20251113`、`E-UK100_01__d2_s3_seed1_24h_20251113`、`E-UK24h-三班-01`、`E-UK24h-三班-150`、`E-UK24h-三班-200`) + `solver/reports/dr_alns_ppo_v3_block_dr_alns/`；**排除** `Reference Algorithm/`、其它实验的大 reports、其它 models 数据。

### 步骤 2：复制到 D:\ReSETP
2.1 用 robocopy 复制 `H:\ReSETP` → `D:\ReSETP`（整盘或按 1.2 精简的目录集）。**不要用镜像删除参数**（别 `/MIR` 删 D 盘已有内容）；保留 `.git`。报告复制的目录与体积、有无报错。
2.2 复制后 `git -C D:\ReSETP status` 确认是有效 git 仓库、远程指向 `zlxshu/ReSETP`、工作区干净。

### 步骤 3：验证 x86 脱盘能训（关键，确认不依赖 H:）
3.1 从 `D:\ReSETP` 跑一次 async **self-check**（小 case、少量 episode，用 PPO venv 的 python，`SETP_WORKER_PYTHON` 指向 py313 venv）。确认：`PASS_ASYNC_SELF_CHECK`、worker=py313、numpy=2.3.5、零违约、worker_python_executable 是本地 venv 路径。
3.2 **核查无 H: 依赖**：确认 self-check 解析的 repo_root=`D:\ReSETP`、PYTHONPATH 指向 `D:\ReSETP\solver\src`（看 `worker_client._worker_env`）、运行中无任何路径回落到 `H:\`。若某 venv 有 editable 安装把 `setp_solver`/`models` 钉在 `H:\`（`pip show setp_solver` 看 Location）→ 从 `D:\ReSETP` 重装 editable 或确认走 PYTHONPATH 即可，使其脱 H:。
3.3 关掉残留 worker 进程，别留后台。

### 步骤 4：报告并停（不训练、不删 H:）
报告：push 的 HEAD hash + GitHub 是否最新；D: 路径/可用空间/复制方式/体积/有无报错；`D:\ReSETP` self-check 结果 + repo_root/PYTHONPATH/worker 路径核查（证明脱 H:）；有无 venv 重指。**然后 HALT，告诉 user "可以拔盘去 M1 了"。保留 `H:\ReSETP` 原样不动**（等 user 确认 D: 可用且盘已安全转移后再说，本提示词不删）。

## 3. 边界 / 禁止项
- **不训练**（reduced-budget DR pilot 是下一条提示词）。
- **不删除、不改动 `H:\ReSETP` 内容**（除步骤 0 的 commit）；D: 是副本，原盘留作迁移源。
- 不改 `cost.py`/`check.py`/`search/evaluation.py` 等任何代码语义；本提示词是运维(git/复制/验证)，不写功能代码。
- push 仅当前分支到既有私有远程；不建新远程、不强推。
- D: 空间不够别硬塞 → 报告走精简复制或等 user 指示。
- 拿不准就停下报告。

## 4. 报告给我什么
push HEAD hash + GitHub 最新确认；D: 路径/空间/复制方式/体积/报错；`D:\ReSETP` self-check 通过 + 脱 H: 核查证据（repo_root/PYTHONPATH/worker 路径）；venv 是否重指；明确写"可否拔盘去 M1"。
