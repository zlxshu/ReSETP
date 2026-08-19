BLUEPRINT_BEGIN

# ReSETP 下一阶段施工蓝图（2026-08-18）

`STATUS: BLUEPRINT_V2_P99_ROUND_2_MERGED_AWAITING_CLAUDE_TERMINAL_READ_NOT_EXECUTION_AUTHORITY`

`VERSION: v2`（P99 第 2/3 轮合并修订）——本版收窄 K3/K5，新增 K7，补齐 K6 与 F3 manifest 字段，加入 F3 cut 观测探针，改正在途趟分类件身份，按线路重排按键时序，并把第一轮 14 条只读 E 命令回填到对应工作项。文末列出 v1→v2 的逐项差异。

## 0. 施工者先读

- 本文件是设计取证和拼装说明书，不是开工记录。只有用户批准后的施工轮才可以改源码、安装依赖或运行求解器。
- 本轮取证基线为 Git `69f544dabf6ff4b50463a54ae66ab280c0f55fc1`。仓库已有未提交改动属于用户；施工者不得清理、覆盖或据此假定工作树干净。
- 三份受保护文件在本轮开始时的 SHA-256：
  - `solver/src/setp_solver/cost.py`：`13ae664bae0e9c8b5033780fbbc43cedcd43c626ac1eb23023a4a667bd2d1bbd`；
  - `solver/src/setp_solver/check.py`：`1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072`；
  - `solver/src/setp_solver/search/evaluation.py`：`c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3`。
- `FACT` 表示本轮从当前 checkout、官方源码或官方项目页核到；`DECISION` 表示本蓝图建议的拼法，尚不是用户批准；`UNKNOWN` 不得补猜；`HALT_*` 是机械停点。
- 行号是本基线的定位锚。施工前必须用本节 E 栏的 `rg/nl` 命令重新定位签名；若函数签名或相邻语义已漂移，不得按旧行号盲贴。
- 新增／搬移文件的最终出处身份严格沿用已批准 `construction_rules_merged.md` 的四类：`UPSTREAM_UNMODIFIED`、`UPSTREAM_PATCHED`、`PROJECT_ADAPTER`、`PROJECT_DOMAIN`；编排配置／脚本归入后两类并另注代码角色。出处 TSV 可另把 `provenance_status` 记为 `UNKNOWN`，但这是审计轴，不是第五种文件身份；UNKNOWN 不得冒充 upstream/human brick，经用户已批准的“搬出 third_party 不改语义”动作可记 `PROJECT_DOMAIN + provenance_status=UNKNOWN`，但搬移本身不解除 formal provenance HALT。每个适配文件有效行不超过 250，单函数不超过 50 条语句，圈复杂度不超过 10。任何搜索循环、候选枚举、调度算法、缓存策略均不得写进适配件。

## 1. 双镜头总图：论文主张 → 图表行 → 数据批次 → 工作项

| 论文主张／八行图表 | 正式数据批次 | 必需工作项 | 不做时直接缺失的展品 |
|---|---|---|---|
| 1. 分时电价与时变碳强度共同改变充电和车型结果 | F1 | W1.2、W2.2、W3.1；W1.4 仅在违规量进入算法诊断时启用 | 图 3 碳价格、图 5 碳价—车型曲线 |
| 2. 混合燃油／电动车队的内生选择 | F1 | W1.2、W2.2、W3.1 | 图 5 两条车辆数曲线和对应成本／排放账 |
| 3. 两企业联合配送产生可核合作节约 | F2 | W1.3a、W1.3b、W1.3c、W2.2、W3.2 | 合作前后成本行、两企业分摊行 |
| 4. 多趟排程是正式求解对象而非后处理 | F1、F2 | W1.2、W2.2、W3.1、W3.2 | 私有主结果中的多趟执行证书和车队使用行 |
| 5. 现实成本、车队参数和 DEPOTSEARCH 实例共同闭合 | F1、F2 | W1.2、W1.3b、W2.2、W3.1、W3.2 | 私有算例参数表、企业成本分解 |
| 6. 动态订单下承诺历史保持且未来可重排 | F3 | W1.1、W1.2、W2.2、W3.3 | 动态对比行；W1.1 缺砖时整行保持空白 |
| 7. 合作参与约束与分摊账分开核 | F2 | W1.3b、W1.3c、W1.3d、W2.2、W3.2 | 运营账与 Shapley 分摊后的参与裕量各一列；论文口径见 K6 |
| 8. 公开算例上有干净、可复现的竞争力证据 | F5 | W0.2、W0.3、W1.2、W2.2、W3.4 | 28 题 × 10 种子的公开主表 |

横切依赖：

1. W0.1 是所有后续改动的机器检查面，不新增科学门槛。
2. W0.2 是公开算法血统和 vendor 边界的前置条件；未解时 F5 不得冠以“干净内核”。
3. W0.3 只分离探索包与正式包字样，不改变可行性或服务量判据。
4. W4 只做开源狩猎；找到并经用户批准前不接入，不用狩猎结果拖延能独立完成的 F1/F2/F5。

## 2. 依赖次序与用户按键

按线路写的依赖与按键时序如下；一个线路的按键不得扩大成其他线路的总门：

```text
公共底座：W0.1 + W0.3 + W1.2
F5：K0 -> W0.2 -> W2.2 public 标定 -> K4/S5 -> W3.4
F1：K7 -> W2.2 private 标定 -> K3/K4 -> S5 -> W3.1
F2：K1 -> K7 -> W1.3a -> W1.3b -> W1.3c -> W1.3d -> K6 -> S5a code-source SHA -> standalone -> Pi0 -> S5b -> joint
F3：10 流共同 initial + cut 观测探针 -> K5 -> W1.1 / mechanical 血统处置 -> W2.2 dynamic 标定 -> W3.3
独立门：K2 -> W1.4；不阻塞 F1/F2/F5
```

必须由用户而非施工者决定的按键：

- `K0-PROVENANCE`：W0.2 是否把第四件 `NativePopulationAdapter.py` 以及被改写的 `GeneticAlgorithm.py` 一并纳入血统清理；见 W0.2 D。
- `K1-FACILITY`：必须早于 F2 enterprise slice。A＝共享公共站＋正文披露（**代理推荐**，因为现数据只支持该语义）；B＝企业私有设施（当前没有 ownership 权威字段，F2 停止并等待新数据）。推荐不是用户决定。
- `K2-VIOLATION`：是否允许改冻结的 `check.py`，添加结构化 violation magnitude。
- `K3-F1-ARMS`：P18 的 `asap/cost_min/cost_plus_carbon` 三条线已经确定；K3 **只决定三条线如何跨碳价格点布局**：A＝三策略全价格点，C＝碳感知全价格点＋两基线只在共同 `g_ref`。见 W3.1 D。
- `K4-S5`：冻结碳价格点、`g_ref` 的 exact `point_id`、标定预算、正式实例身份和正式批次配置；只把 P18 已定的三个 policy id 落盘，不重问策略集合。F2 因 Pi0 依赖必须分 S5a standalone 与 S5b joint 两份不可变 revision。旧 1.223/1.472/2.27 仅是跨时代参考，不是冻结数字。
- `K5-F3`：P10 已定“30 分钟或累计需求量先到者触发”，不再重问 policy 家族。K5 只冻结：①需求阈值精确 kg 与来源；②符合 P34 的 idle-EV readiness 具体执行口径；③initial／每决策点预算；④mechanical control 血统处置；⑤W1.1 在途趟状态转移语义。必须先看 10 流共同 initial 的 cut 观测探针。见 W3.3 D。
- `K6-F2-PARTICIPATION-LEDGER`：A＝以现有 route-home-depot 运营账施加参与约束（可继续 F2，Shapley allocated margin 另报）；B＝以 Shapley allocated profit 作搜索参与约束（当前触发 `HALT_NO_BRICK_ALLOCATED_PARTICIPATION_SEARCH`）。必须早于 F2 的 S5a code-source SHA；值写入 manifest，不得由聚合器硬编码。
- `K7-PRIVATE-INIT-PROVENANCE`：覆盖 F1 封存见证的离线生成血统与 F2 拟用三件初始化算法，**不覆盖 F5**。A＝接受既有项目初始化算法并披露（对全部 private 用途一致生效）；B＝停用并找替代（须重建封存见证与 enterprise seed）。必须早于 F1/F2 private 初始化身份冻结。

---

### 工作项 W0.1　机器闸门

#### A. 现状取证

1. 仓库根目录当前没有 `.pre-commit-config.yaml`、根 `pyproject.toml`、`.importlinter` 或项目 Semgrep 规则。
2. 本机当前可直接调用的相关工具只有 `/opt/anaconda3/bin/ruff 0.12.0`；`/opt/homebrew/bin/uv` 为 0.10.9。根 Python、`third_party/setp_hgs_kernel/.venv` 均没有 pre-commit/import-linter/vulture/semgrep。
3. 以拟启用规则只读扫描当前项目代码，现有债务至少包括：`C901=162`、`PLR0915=101`、`PLR0912=98`、`BLE001=50`、`SIM105=10`、`TRY203=1`。Ruff 是 file-level，不会只看新改行；private/dynamic/public runner 等本蓝图必触碰 legacy 文件已经超限。因此不能把“全仓零存量问题”或“触碰 legacy 文件即可绿”伪装成第一天门；blocking Ruff 先只管本蓝图新增 adapter/脚本，legacy 只做非阻断全量清单。
4. `solver/src/setp_solver/main3b_backend.py:22-30` 把 `solver/scripts` 加入 `sys.path`，随后按顶层模块导入 runner；`solver/scripts` 不是 Python package。因此 Import Linter 不得声称能直接管这些顶层脚本间的全部依赖。
5. W0.2 已发现 `third_party/setp_hgs_kernel/setp_hgs_kernel/GeneticAlgorithm.py:9` 依赖未知出处的 `HGSControl`；这个反向依赖会成为 vendor 边界合同的真实阻断项。

#### B. 积木清单

| 库 | 固定版本 | 使用的模块／命令 | 许可证 | 仓内／URL | 人类作品证据 |
|---|---:|---|---|---|---|
| pre-commit | 4.6.2 | `pre-commit install/run` | MIT | https://pypi.org/project/pre-commit/4.6.2/ | Anthony Sottile 维护；PyPI 2026-08-10 发布 |
| pre-commit-hooks | 6.0.0 | `check-ast/check-yaml/check-toml/trailing-whitespace/end-of-file-fixer` | MIT | https://github.com/pre-commit/pre-commit-hooks/tree/v6.0.0 | GitHub 约 6.5k stars，公开维护者与发布史 |
| Ruff | 0.16.3 | `ruff check`；C901/PLR/SIM/BLE/TRY | MIT | https://pypi.org/project/ruff/0.16.3/ | Astral 公开项目；PyPI 固定发行物 |
| Import Linter | 2.13 | `lint-imports --config .importlinter` | BSD-2-Clause | https://pypi.org/project/import-linter/2.13/ | David Seddon；PyPI 标注 Production/Stable |
| Vulture | 2.16 | `vulture ... --min-confidence 60 --sort-by-size` | MIT | https://pypi.org/project/vulture/2.16/ | Jendrik Seipp 等维护；标准 whitelist API |
| Semgrep | 1.173.0 | `semgrep scan/test` | LGPL-2.1-or-later | https://pypi.org/project/semgrep/1.173.0/ | Semgrep Inc. 公开引擎和规则格式 |
| Flake8 | 7.3.0 | `flake8 --select FLN` | MIT | https://pypi.org/project/flake8/7.3.0/ | PyCQA；公开版本史 |
| flake8-file-length | 0.1.0 | `FLN001 / --max-file-length` | MIT | https://pypi.org/project/flake8-file-length/0.1.0/ | Elie Terrien；公开 PyPI 插件及接口 |

离线边界：

- 当前仓内 venv **没有**上述固定版本；只有外部 Anaconda Ruff 0.12.0，版本不合合同，不能冒充施工环境。
- 有网时先用标准 `python3 -m pip download` 把固定 wheels 和所有传递依赖囤入 `tools/quality/wheelhouse/`，再从该目录离线安装到 `.quality-venv`。
- 新鲜 clone 若没有 wheelhouse 或 pre-commit 缓存，离线安装会失败；这是物理事实，不写“离线自动可用”。

#### C. 拼装步骤

1. 在仓库根新增 `tools/quality/requirements.in`（`declared_identity=PROJECT_DOMAIN`，`file_role=ORCHESTRATION_CONFIG`），内容逐行固定：

   ```text
   pre-commit==4.6.2
   pre-commit-hooks==6.0.0
   ruff==0.16.3
   import-linter==2.13
   vulture==2.16
   semgrep==1.173.0
   flake8==7.3.0
   flake8-file-length==0.1.0
   ```

2. 有网施工机执行标准锁定与囤货，不自行写安装器：

   ```bash
   uv pip compile tools/quality/requirements.in \
     --generate-hashes -o tools/quality/requirements.lock
   python3 -m pip download \
     --require-hashes -r tools/quality/requirements.lock \
     --dest tools/quality/wheelhouse
   python3 -m venv .quality-venv
   .quality-venv/bin/python -m pip install \
     --no-index --find-links tools/quality/wheelhouse \
     --require-hashes -r tools/quality/requirements.lock
   ```

   把 `.quality-venv/` 加入现有 `.gitignore`；wheelhouse 是否入仓由用户另批，未批时不得提交二进制。

3. 在根新增 `pyproject.toml:1`（`declared_identity=PROJECT_DOMAIN`，`file_role=ORCHESTRATION_CONFIG`），把 Ruff 内容写死为：

   ```toml
   [tool.ruff]
   target-version = "py310"
   line-length = 100
   exclude = [
     "third_party",
     "Reference Algorithm",
     "solver/reports",
     "baselines",
     "build",
     "dist",
   ]

   [tool.ruff.lint]
   select = ["C901", "PLR0912", "PLR0915", "BLE001", "SIM105", "TRY203"]

   [tool.ruff.lint.mccabe]
   max-complexity = 10

   [tool.ruff.lint.pylint]
   max-branches = 12
   max-statements = 50
   ```

   这组规则分别落实圈复杂度、分支数、语句数、宽捕异常、可由 `contextlib.suppress` 代替的空异常块和无意义的 try/except 重抛。Ruff 不提供文件总行数，文件 250 行限制由 Flake8 插件承担，不新增 AST 脚本。

4. 在根新增 `.importlinter:1`（`declared_identity=PROJECT_DOMAIN`，`file_role=ORCHESTRATION_CONFIG`），内容写死为：

   ```ini
   [importlinter]
   root_packages =
       setp_solver
       setp_hgs_kernel
       setp_instance_lab
   include_external_packages = True
   exclude_type_checking_imports = False

   [importlinter:contract:vendor-does-not-import-project]
   name = Frozen HGS vendor must not import ReSETP project code
   type = forbidden
   source_modules =
       setp_hgs_kernel
   forbidden_modules =
       setp_solver
       setp_instance_lab

   [importlinter:contract:problem-hgs-does-not-call-retired-alns]
   name = Problem HGS must not depend on retired fairness or ALNS entrypoints
   type = forbidden
   allow_indirect_imports = True
   source_modules =
       setp_solver.algorithms.problem_hgs
   forbidden_modules =
       setp_solver.search.fairness
       setp_solver.search.alns_wouda
       setp_solver.algorithms.resetp_alns.api
       setp_solver.algorithms.resetp_alns.kernel
       setp_solver.algorithms.resetp_alns.operators
       setp_solver.algorithms.resetp_alns.runtime
   ```

   调用时固定 `PYTHONPATH=solver/src:models/src:third_party/setp_hgs_kernel`。不为 `solver/scripts` 伪造 package 合同。不得禁止整个 `setp_solver.algorithms.resetp_alns`：`problem_hgs/charging.py:35-39` 直接复用 `support.charging`，而该 support 在 `resetp_alns/support/charging.py:51-53` 又间接 import `operators.repair_scoring`。因此本合同必须显式 `allow_indirect_imports=True`，只禁止 Problem-HGS **直接** import 已退役 entry/kernel/operator/runtime；若日后要让 support 与 operators 解耦，另立有出处的积木工作项，不在架构合同中假装已解耦。

5. 对 Vulture 只使用其标准 whitelist 格式。首次施工先生成存量基线：

   ```bash
   .quality-venv/bin/vulture solver/src models/src solver/tests \
     --exclude 'third_party,solver/reports,baselines,*/._*' \
     --min-confidence 60 --sort-by-size --make-whitelist \
     > tools/quality/vulture_whitelist.py
   ```

   人工逐行标注动态注册／协议方法的真实消费者；疑似真死码另记清理卡，不在 W0.1 顺手删除。正式钩子调用：

   ```bash
   .quality-venv/bin/vulture solver/src models/src solver/tests \
     tools/quality/vulture_whitelist.py \
     --exclude 'third_party,solver/reports,baselines,*/._*' \
     --min-confidence 60 --sort-by-size
   ```

6. 在 `tools/quality/semgrep_tests/project_behaviour.yml:1`（`declared_identity=PROJECT_DOMAIN`，`file_role=QUALITY_RULE_CONFIG`）新增以下四条 Semgrep 配置；它们调用官方匹配引擎，不实现自制 AST。规则文件与官方 test target 使用同一 stem，避免 `semgrep --test` 找不到配对：

   ```yaml
   rules:
     - id: resetp-no-object-id-cache-key
       languages: [python]
       severity: ERROR
       message: Do not key a cache by id(); use a stable value identity.
       pattern-either:
         - pattern: $CACHE[id($OBJ)] = $VALUE
         - pattern: $CACHE[id($OBJ)]
         - pattern: $CACHE.get(id($OBJ), ...)
         - pattern: $CACHE.setdefault(id($OBJ), ...)
         - pattern: $CACHE[(id($OBJ), $REST)] = $VALUE
         - pattern: $CACHE[($REST, id($OBJ))] = $VALUE
         - pattern: $CACHE[(id($OBJ), $REST)]
         - pattern: $CACHE[($REST, id($OBJ))]
         - pattern: $CACHE.get((id($OBJ), $REST), ...)
         - pattern: $CACHE.get(($REST, id($OBJ)), ...)
         - pattern: $CACHE.setdefault((id($OBJ), $REST), ...)
         - pattern: $CACHE.setdefault(($REST, id($OBJ)), ...)
         - patterns:
             - pattern-inside: |
                 $KEY = (id($OBJ), $REST)
                 ...
             - pattern-either:
                 - pattern: $CACHE[$KEY] = $VALUE
                 - pattern: $CACHE[$KEY]
                 - pattern: $CACHE.get($KEY, ...)
                 - pattern: $CACHE.setdefault($KEY, ...)
         - patterns:
             - pattern-inside: |
                 $KEY = ($REST, id($OBJ))
                 ...
             - pattern-either:
                 - pattern: $CACHE[$KEY] = $VALUE
                 - pattern: $CACHE[$KEY]
                 - pattern: $CACHE.get($KEY, ...)
                 - pattern: $CACHE.setdefault($KEY, ...)

     - id: resetp-no-module-mutable-cache
       languages: [python]
       severity: ERROR
       message: Mutable module cache must belong to a RunContext lifecycle.
       patterns:
         - metavariable-regex:
             metavariable: $CACHE
             regex: (?i)^.*cache.*$
         - pattern-either:
             - pattern: $CACHE = {}
             - pattern: $CACHE = []
             - pattern: $CACHE = set()
             - pattern: $CACHE = collections.OrderedDict(...)
             - pattern: $CACHE = collections.defaultdict(...)
         - pattern-not-inside: |
             def $FUNC(...):
               ...
         - pattern-not-inside: |
             class $CLASS:
               ...

     - id: resetp-no-detail-message-regex-control-flow
       languages: [python]
       severity: ERROR
       message: Human detail/message text must not drive control flow.
       pattern-either:
         - pattern: |
             if re.search($REGEX, $OBJ.detail, ...):
               ...
         - pattern: |
             if re.match($REGEX, $OBJ.detail, ...):
               ...
         - pattern: |
             if re.search($REGEX, $OBJ.message, ...):
               ...
         - pattern: |
             if re.match($REGEX, $OBJ.message, ...):
               ...

     - id: resetp-no-broad-except-return-default
       languages: [python]
       severity: ERROR
       message: Broad exception must not silently return a default value.
       pattern-either:
         - pattern: |
             try:
               ...
             except:
               ...
               return $DEFAULT
         - patterns:
             - pattern: |
                 try:
                   ...
                 except $EXC:
                   ...
                   return $DEFAULT
             - metavariable-regex:
                 metavariable: $EXC
                 regex: ^(Exception|BaseException)$
         - patterns:
             - pattern: |
                 try:
                   ...
                 except $EXC as $ERR:
                   ...
                   return $DEFAULT
             - metavariable-regex:
                 metavariable: $EXC
                 regex: ^(Exception|BaseException)$
   ```

7. 在同 stem 的 `tools/quality/semgrep_tests/project_behaviour.py`（`declared_identity=PROJECT_DOMAIN`，`file_role=QUALITY_TEST_FIXTURE`）中同时写官方 `# ruleid: <id>` 病例和 `# ok: <id>` 对照。至少覆盖四条规则各 2 个命中和 2 个不命中；id-key 必须同时覆盖直接 tuple 形态 `_CARBON_PROFILE_SORT_CACHE[(id(data), profile)] = value`、反向 tuple 位置，以及当前 `cost.py:139-152` 同形的派生键 `cache_key=(id(time_profile), city)` 后接 `CACHE.get(cache_key)` 与 `CACHE[cache_key]=value`，稳定 value-key tuple 为 ok；宽捕规则另必须分别命中裸 `except`、`except Exception`、`except Exception as exc`。用显式 `--config <same-stem-rule> <same-stem-target>` 的官方 test 模式验证，不依赖目录自动猜规则。若官方引擎不能让四个 rule id 全通过，尤其派生 tuple-key 任一例漏报，标 `HALT_NO_BRICK_SEMGREP_RULE`，不得用自写 AST 扫描器顶替。

8. 在根新增 `.pre-commit-config.yaml:1`（`declared_identity=PROJECT_DOMAIN`，`file_role=ORCHESTRATION_CONFIG`）。为离线可重复性，全部使用已锁定 `.quality-venv` 的 `repo: local / language: system`，不让 pre-commit 临时联网建第二套环境：

   ```yaml
   default_stages: [pre-commit]
   fail_fast: false
   repos:
     - repo: local
       hooks:
         - id: check-ast
           name: check Python AST
           entry: .quality-venv/bin/check-ast
           language: system
           types: [python]
           exclude: ^(third_party|Reference Algorithm|solver/reports|baselines)/
         - id: check-yaml
           name: check YAML
           entry: .quality-venv/bin/check-yaml
           language: system
           types: [yaml]
         - id: check-toml
           name: check TOML
           entry: .quality-venv/bin/check-toml
           language: system
           types: [toml]
         - id: trailing-whitespace
           name: trim trailing whitespace
           entry: .quality-venv/bin/trailing-whitespace-fixer
           language: system
           types: [text]
         - id: end-of-file-fixer
           name: ensure final newline
           entry: .quality-venv/bin/end-of-file-fixer
           language: system
           types: [text]
         - id: ruff-behaviour-limits
           name: Ruff complexity and exception rules
           entry: .quality-venv/bin/ruff check
           language: system
           types: [python]
           files: ^solver/src/setp_solver/(instance_subset|mapping_identity|pi0_manifest|formal_campaign)\.py$|^solver/src/setp_solver/algorithms/problem_hgs/(execution_identity|enterprise_adapter)\.py$|^solver/scripts/(coalition_accounting_adapter|plot_s5_convergence|build_f2_inputs|aggregate_formal_campaign)\.py$
         - id: import-contracts
           name: import architecture contracts
           entry: env PYTHONPATH=solver/src:models/src:third_party/setp_hgs_kernel .quality-venv/bin/lint-imports --config .importlinter
           language: system
           pass_filenames: false
         - id: vulture
           name: Vulture against reviewed baseline
           entry: .quality-venv/bin/vulture solver/src models/src solver/tests tools/quality/vulture_whitelist.py --exclude third_party,solver/reports,baselines --min-confidence 60 --sort-by-size
           language: system
           pass_filenames: false
         - id: semgrep-project-rules
           name: Semgrep project behaviour rules
           entry: .quality-venv/bin/semgrep scan --config tools/quality/semgrep_tests/project_behaviour.yml --error --metrics=off --baseline-commit HEAD
           language: system
           types: [python]
           exclude: ^(third_party|Reference Algorithm|solver/reports|baselines|tools/quality/semgrep_tests)/
         - id: project-adapter-file-length
           name: PROJECT_ADAPTER maximum 250 lines
           entry: .quality-venv/bin/flake8 --select FLN --max-file-length 250 --file-length-ignore-blank --file-length-ignore-comments --file-length-ignore-shebang
           language: system
           files: ^solver/src/setp_solver/(instance_subset|mapping_identity|pi0_manifest|formal_campaign)\.py$|^solver/src/setp_solver/algorithms/problem_hgs/(execution_identity|enterprise_adapter)\.py$|^solver/scripts/(coalition_accounting_adapter|plot_s5_convergence|build_f2_inputs|aggregate_formal_campaign)\.py$
   ```

9. 若用户最终未批准某个适配文件路径，在步骤 8 的 `files` 正则中删除该路径；不得把“候选路径”冒充已批准文件。新增适配件必须显式加入该正则。

#### D. 缺口如实

- `HALT_NO_BRICK`：上述 Semgrep 第三条只能可靠捕捉直接位于条件表达式中的 `detail/message` 正则。跨函数“先解析文字、后据解析结果分支”的完整数据流没有在本仓或所查 Semgrep 社区规则中找到无歧义现成规则；不得补写自制 AST/污点分析器。检索范围：Semgrep Python pattern/taint 文档、仓内现有规则（无）。
- `HALT_NO_BRICK_SEMGREP_TUPLE_ID`：若官方 `semgrep --test` 不能让 C.6 的二元 tuple 两个位置对 assignment/read/get/setdefault 全部命中，就不得声称 id-key 闸门完成，也不得改写自制 AST；保留失败 fixture 与官方引擎输出呈用户。
- `HALT_NO_BRICK`：尚无标准工具能证明“每个公开状态字段既有唯一生产者又有真实消费者”。Vulture 只查符号使用，Import Linter 只查依赖方向；本项不发明状态注册表。
- `HALT_NO_BRICK_INCREMENTAL_RUFF`：Ruff 本身没有“只阻断本次新增行、忽略同文件旧债”的 baseline 合同；本轮未核到已囤且可锁定的增量 Ruff wrapper。故 legacy touched files 只能非阻断扫描，blocking hook 严格限新增文件；不得自写 diff 解析器来伪造行级门。Semgrep 则直接复用其官方 `--baseline-commit HEAD`，不另造 diff。
- W0.2 的 vendor 反向依赖未裁决时，Import Linter 合同失败是正确阻断，不得用 `ignore_imports` 消音。

#### E. 验收

1. 版本与离线安装：

   ```bash
   .quality-venv/bin/pre-commit --version
   .quality-venv/bin/ruff --version
   .quality-venv/bin/lint-imports --version
   .quality-venv/bin/vulture --version
   .quality-venv/bin/semgrep --version
   .quality-venv/bin/flake8 --version
   ```

   预期依次出现 4.6.2、0.16.3、2.13、2.16、1.173.0、7.3.0，Flake8 行同时出现 `flake8-file-length: 0.1.0`。

2. 断网复装验证：删除的目标只能是明确临时目录 `.quality-venv-offline-check`，不得动正式 venv：

   ```bash
   python3 -m venv .quality-venv-offline-check
   .quality-venv-offline-check/bin/python -m pip install \
     --no-index --find-links tools/quality/wheelhouse \
     --require-hashes -r tools/quality/requirements.lock
   ```

   预期 exit 0 且没有访问 PyPI；验完将该明确目录移到废纸篓或删除。

3. 规则 fixture：

   ```bash
   .quality-venv/bin/semgrep --test \
     --config tools/quality/semgrep_tests/project_behaviour.yml \
     tools/quality/semgrep_tests/project_behaviour.py
   ```

   预期四条规则测试全部通过，0 mismatch。

4. 适配件限额：

   ```bash
   .quality-venv/bin/flake8 --select FLN --max-file-length 250 \
     --file-length-ignore-blank --file-length-ignore-comments \
     --file-length-ignore-shebang \
     solver/src/setp_solver/algorithms/problem_hgs/enterprise_adapter.py
   .quality-venv/bin/ruff check \
     --select C901,PLR0912,PLR0915 \
     solver/src/setp_solver/algorithms/problem_hgs/enterprise_adapter.py
   ```

   预期无输出、exit 0；病样本 251 行／复杂度 11 必须 exit 非 0。

5. 架构合同：

   ```bash
   PYTHONPATH=solver/src:models/src:third_party/setp_hgs_kernel \
     .quality-venv/bin/lint-imports --config .importlinter
   ```

   预期两个合同 kept；若 W0.2 尚未解决而显示 vendor→project 依赖，则预期是 non-zero 并停止后续合并。

6. 完整钩子：

   ```bash
   .quality-venv/bin/pre-commit validate-config
   for hook in check-ast check-yaml check-toml ruff-behaviour-limits \
     import-contracts vulture semgrep-project-rules project-adapter-file-length; do
     .quality-venv/bin/pre-commit run "$hook" --all-files || exit $?
   done
   .quality-venv/bin/pre-commit run trailing-whitespace --files \
     .pre-commit-config.yaml .importlinter pyproject.toml .gitignore \
     tools/quality/requirements.in tools/quality/requirements.lock \
     tools/quality/vulture_whitelist.py \
     tools/quality/semgrep_tests/project_behaviour.yml \
     tools/quality/semgrep_tests/project_behaviour.py
   .quality-venv/bin/pre-commit run end-of-file-fixer --files \
     .pre-commit-config.yaml .importlinter pyproject.toml .gitignore \
     tools/quality/requirements.in tools/quality/requirements.lock \
     tools/quality/vulture_whitelist.py \
     tools/quality/semgrep_tests/project_behaviour.yml \
     tools/quality/semgrep_tests/project_behaviour.py
   ```

   `--all-files` 只用于 non-mutating hooks；Ruff hook 因 `files:` 只阻断新增 adapter/脚本，Semgrep 用官方 baseline 只报相对 HEAD 新发现。另对 legacy touched files 单独运行 `.quality-venv/bin/ruff check --select C901,PLR0912,PLR0915,BLE001,SIM105,TRY203 <explicit_paths>`，允许 nonzero并把原样输出附施工报告，不能冒充 blocking pass。两个 fixer 仅收本工作项明确触碰的文件，禁止对全仓或用户脏文件运行。以后每个工作项把自己的明确触碰路径传给两个 fixer。

#### F. 净行数预算

- 配置、锁文件（不含传递依赖哈希展开）和 Semgrep fixtures：预计 `+180/−0`。
- Vulture whitelist 的行数由首次标准命令输出决定，当前 `UNKNOWN`；不得为了满足预算删条目。
- 生产求解代码：`+0/−0`。

---

### 工作项 W0.2　third_party 出处清单与搬出

#### A. 现状取证

1. 冻结 PyVRP 0.12.2 上游身份写在 `third_party/setp_hgs_kernel/README.md:10-15`：commit `ea0c421...`、MIT。对干净 0.12.2 安装内省，以下四个模块均不存在：
   - `IntegratedGeneticAlgorithm.py`：258 行，`class IntegratedGeneticAlgorithm` 位于 75，`__init__` 78-89，`run` 106；
   - `ExternalPopulation.py`：267 行，`EvaluatedSolution` 26-29，`class ExternalPopulation` 43，`__init__` 46-54；
   - `HGSControl.py`：101 行，状态类 17-35，`class HGSControl` 37，`__init__` 40-48，`iterations` 75；
   - `NativePopulationAdapter.py`：94 行，`class NativePopulationAdapter` 14，`__init__` 17-24。
2. 四件最早同时出现在 Git commit `15ea991...`；Git 作者为 Leixishu Zhou，但文件内容的原作者／算法出处仍是 `UNKNOWN`，不能把提交者等同原创作者。
3. `third_party/setp_hgs_kernel/setp_hgs_kernel/GeneticAlgorithm.py:9` 新增 `from setp_hgs_kernel.HGSControl import HGSControl`，并在 177 调它；冻结上游版本的遗传循环是文件内联实现。故当前 `GeneticAlgorithm.py` 本身也是“打补丁上游”，不是原样上游。
4. 全仓活跃 import：
   - Integrated：`integrated_private.py:20`、`public_search.py:26`；历史只读报告 `solver/reports/ev_survival_trace_20260817/trace_integrated_lineage.py:27`。
   - External：vendor `NativePopulationAdapter.py:8`；vendor `IntegratedGeneticAlgorithm.py:13`；`bi_objective_population.py:18`、`integrated_private.py:16`、`public_search.py:19`；测试 `test_problem_hgs_bi_objective_population.py:7`、`test_problem_hgs_integrated_foundation.py:33`；历史报告同上 :26。
   - HGSControl：vendor `GeneticAlgorithm.py:9`、vendor `IntegratedGeneticAlgorithm.py:10`、`test_problem_hgs_control.py:1`。
   - Native adapter：`public_search.py:30`。
5. `third_party` 当前含用户未提交变化和本地 venv；manifest 必须只覆盖 Git 跟踪文件，不能把缓存／环境混进去。

#### B. 积木清单

| 积木 | 版本／commit | 接口 | 许可证 | 路径／URL | 人类作品证据 |
|---|---|---|---|---|---|
| PyVRP upstream | 0.12.2 / `ea0c421...` | `GeneticAlgorithm`、`SolveParams` 等 | MIT | https://github.com/PyVRP/PyVRP/tree/v0.12.2 | PyVRP 团队；EJOR 论文和公开 release |
| POSIX/macOS SHA tool | 系统 `shasum` | `shasum -a 256 FILE` | 系统工具 | 本机 | 标准摘要实现 |
| Git tracked-file enumerator | 当前 Git | `git ls-files` | GPL-2.0 | 本机 | Git 官方实现 |

未知四件不能列作“人类开源积木”；它们的两轴记录是 `declared_identity=PROJECT_DOMAIN`、`provenance_status=UNKNOWN`，不得写成 copied/upstream。

#### C. 拼装步骤

1. 在移动任何文件前，先对全部待搬文件运行 `shasum -a 256 <exact-old-path>`，把施工前摘要写进施工记录以及获批目的文件的 provenance 头；此时**不要**生成声称描述最终 third_party 树的 TSV。全部获批 `git mv` 和 GA 处置结束后，再新增／从头重建 `third_party/UPSTREAM_PROVENANCE.tsv`（`declared_identity=PROJECT_DOMAIN`，文件角色＝`PROVENANCE_MANIFEST`）。除 `UPSTREAM_PROVENANCE.tsv` 自身和 `UPSTREAM_MANIFEST.sha256` 外，对最终 `git ls-files third_party` 的每个路径 exact 一行，字段固定为：

   `path<TAB>declared_identity<TAB>provenance_status<TAB>upstream_url<TAB>version_or_commit<TAB>license<TAB>byte_status<TAB>evidence`。

   `declared_identity` 只准总则的四种值；`provenance_status` 只准 `VERIFIED|UNKNOWN`。四个未知模块必须 `PROJECT_DOMAIN + UNKNOWN`；当前 `GeneticAlgorithm.py` 必须 `UPSTREAM_PATCHED + UNKNOWN`，不得写成原样上游。

2. 所有获批搬移必须用精确 `git mv <old> <approved-new>`，让 index 的 tracked path 与最终树一致，不得用普通 `mv` 后让旧路径留在 index。步骤 1 的最终 TSV 必须删除已搬出 third_party 的旧行，并加入仍在 third_party 的最终 tracked path；先只执行 `git add -- third_party/UPSTREAM_PROVENANCE.tsv`（不得 `git add third_party`），再生成最终摘要。`UPSTREAM_MANIFEST.sha256` 首次生成前不存在，禁止预先 `git add` 它；生成成功后才执行 `git add -- third_party/UPSTREAM_MANIFEST.sha256`：

   ```bash
   set -euo pipefail
   manifest_tmp="$(mktemp third_party/.UPSTREAM_MANIFEST.sha256.XXXXXX)"
   trap 'rm -f "$manifest_tmp"' EXIT
   git -c core.quotePath=false ls-files third_party \
     | LC_ALL=C sort \
     | while IFS= read -r tracked_path; do
         test -f "$tracked_path" || {
           echo "missing tracked third_party file: $tracked_path" >&2
           exit 1
         }
         case "$tracked_path" in
           third_party/UPSTREAM_MANIFEST.sha256) continue ;;
         esac
         shasum -a 256 "$tracked_path"
       done > "$manifest_tmp"
   mv "$manifest_tmp" third_party/UPSTREAM_MANIFEST.sha256
   trap - EXIT
   git add -- third_party/UPSTREAM_MANIFEST.sha256
   ```

3. 把三件候选目的地固定为：
   - `IntegratedGeneticAlgorithm.py` → `solver/src/setp_solver/algorithms/problem_hgs/integrated_genetic_algorithm.py`；
   - `ExternalPopulation.py` → `.../problem_hgs/external_population.py`；
   - `HGSControl.py` → `.../problem_hgs/hgs_control.py`。

   实际搬移必须用步骤 2 的 exact `git mv`。文件名转 snake_case，只做路径和 import 拼装；类名、函数体、状态字段保持逐字不变。新文件头写两轴：`declared_identity=PROJECT_DOMAIN`、`provenance_status=UNKNOWN`、首现 commit 和“原作者 UNKNOWN”；不得写 `PROJECT_OWNED_PROVENANCE_UNKNOWN` 这个第五类名称，不得虚构许可证。这是已批准的 third_party 隔离动作，不是把它们升格为人类开源积木。

4. 在执行步骤 3 前触发 W0.2 D 的 `HALT_SCOPE_MISMATCH`。只有用户批准扩界方案后才继续；未批准时本工作项停在 provenance 清单和 manifest。

5. 若用户批准“至少四件搬出”，再把 `NativePopulationAdapter.py` 原样移到 `.../problem_hgs/native_population_adapter.py`，并机械改：
   - `public_search.py:30` → 从 `.native_population_adapter` 导入；
   - 新 adapter 文件原 :8 → 从 `.external_population` 导入。

6. 三件获批后机械改 import：
   - `integrated_private.py:16`、`bi_objective_population.py:18`、`public_search.py:19` → `from .external_population import ...`；
   - `integrated_private.py:20`、`public_search.py:26` → `from .integrated_genetic_algorithm import ...`；
   - `test_problem_hgs_bi_objective_population.py:7`、`test_problem_hgs_integrated_foundation.py:33` → 从项目模块导入 External；
   - `test_problem_hgs_control.py:1` → 从项目模块导入 HGSControl；
   - 移出的 Integrated 文件原 :10/:13 → 相对导入项目 HGSControl/External；其原 :9 仍只读 vendor `GeneticAlgorithmParams`。

7. 历史报告 `solver/reports/ev_survival_trace_20260817/trace_integrated_lineage.py` 只登记旧时代 import，不改历史产物；若未来复跑该报告，另建新版本，不能静默改旧报告。

8. `GeneticAlgorithm.py` 的处置没有用户按键前不得执行。可呈用户的两个真实分支只有：
   - 分支 A：把当前 patched GA 也移为项目文件，并在 vendor 恢复 PyVRP 0.12.2 原文件；需要把 `solve.py:7`、`__init__.py:6-7` 的公共／私有调用分流，行为保持方案尚未取证完整；
   - 分支 B：直接恢复 upstream GA；会改变循环、restart/计时语义，必须作为算法行为变更另批。

   两分支均未达到机械施工条件，因此本蓝图不替用户选。

#### D. 缺口如实

- `HALT_SCOPE_MISMATCH`：用户原工作项点名三件，但 `NativePopulationAdapter.py` 是同类第四件且依赖 External。只搬三件会在 vendor 留下项目适配件，出处边界仍不干净。
- `HALT_NO_BRICK`：把 HGSControl 搬到项目侧后，vendor `GeneticAlgorithm.py` 若反向 import 项目侧会违反 W0.1 合同；恢复 upstream GA 又改变现有搜索循环／计时语义。已比较冻结 PyVRP 0.12.2 和当前补丁，未找到可无行为变化替换的上游整件。
- K0-PROVENANCE 决定第四件与 patched GA 的边界；未解前不能完成整个 vendor 依赖闭合。三件搬出可作已批准隔离，但在人类来源／许可证未解时仍 `HALT_FORMAL_PROVENANCE_UNKNOWN`；不靠改名搬出洗白。

#### E. 验收

1. 第一轮事实复现 E1（四件同提交首现＋GA／adapter 反向依赖）：

   ```bash
   for f in IntegratedGeneticAlgorithm.py ExternalPopulation.py HGSControl.py NativePopulationAdapter.py; do
     git log --follow --diff-filter=A --format='%H|%an|%aI' -- "third_party/setp_hgs_kernel/setp_hgs_kernel/$f" | tail -n 1
   done
   rg -n 'HGSControl|ExternalPopulation' \
     third_party/setp_hgs_kernel/setp_hgs_kernel/GeneticAlgorithm.py \
     third_party/setp_hgs_kernel/setp_hgs_kernel/NativePopulationAdapter.py
   ```

2. 完整 import 盘点：

   ```bash
   MOVE_NATIVE="${MOVE_NATIVE:?set true or false exactly from the K0 decision}"
   case "$MOVE_NATIVE" in true|false) ;; *) exit 2;; esac
   ! rg -n 'setp_hgs_kernel\.(IntegratedGeneticAlgorithm|ExternalPopulation|HGSControl)' \
     --glob '*.py' solver/src solver/tests
   if [[ "$MOVE_NATIVE" == true ]]; then
     ! rg -n 'setp_hgs_kernel\.NativePopulationAdapter' --glob '*.py' solver/src solver/tests
   else
     test -f third_party/setp_hgs_kernel/setp_hgs_kernel/NativePopulationAdapter.py
   fi
   ```

   前三件预期生产和测试命中为 0；Native 只在 K0 批准搬出时要求 0，否则必须仍在原路径且 provenance 仍为 `PROJECT_DOMAIN + UNKNOWN`。历史报告若保留，必须被单独列为 legacy，不计作活跃生产。

3. manifest 可复算：

   ```bash
   MOVE_NATIVE="${MOVE_NATIVE:?set true or false exactly from the K0 decision}"
   case "$MOVE_NATIVE" in true|false) ;; *) exit 2;; esac
   shasum -a 256 -c third_party/UPSTREAM_MANIFEST.sha256
   moved=(IntegratedGeneticAlgorithm ExternalPopulation HGSControl)
   if [[ "$MOVE_NATIVE" == true ]]; then
     moved+=(NativePopulationAdapter)
   fi
   for moved in "${moved[@]}"; do
     test ! -e "third_party/setp_hgs_kernel/setp_hgs_kernel/${moved}.py"
   done
   ```

   第一条预期全部 `OK`；第二段只核用户实际批准的搬移集合。Native 未批准时另断言原文件存在且 TSV 行未擅改。**禁止**要求整个 `third_party/setp_hgs_kernel` 对 HEAD 零 diff：A.5 已确认该目录有用户现场，清零断言会诱导施工者覆盖或提交无关改动。patched GA 另按 K0 分支的目标文件 byte hash／独立 patch 证据验收。

4. provenance 行覆盖：

   ```bash
   tracked_count="$(git -c core.quotePath=false ls-files third_party | wc -l | tr -d ' ')"
   tsv_rows="$(awk 'NR>1 {n++} END {print n+0}' third_party/UPSTREAM_PROVENANCE.tsv)"
   test "$tracked_count" = "$((tsv_rows + 2))"
   ```

   再以 Bash 执行下列集合核对，禁止只靠行数碰巧相等：

   ```bash
   set -euo pipefail
   provenance_diff="$(comm -3 \
     <(git -c core.quotePath=false ls-files third_party \
         | LC_ALL=C sort \
         | rg -v '^third_party/(UPSTREAM_PROVENANCE\.tsv|UPSTREAM_MANIFEST\.sha256)$') \
     <(tail -n +2 third_party/UPSTREAM_PROVENANCE.tsv | cut -f1 | LC_ALL=C sort))"
   test -z "$provenance_diff"
   ```

   两条命令均预期 exit 0，`provenance_diff` 为空；`+2` 就是 TSV 自身和 manifest 自身。临时 fixture 人为删／加一个 TSV path 时 `test -z` 必须 nonzero，不能因为 `comm` 自身通常返回 0 而漏报集合差异。任一 tracked third_party 路径缺文件都必须在 C.2 fail-closed，不能静默从摘要丢掉。另在临时 Git fixture 中保留一个旧 manifest、删除一个 tracked fixture 文件再跑 C.2，预期 nonzero 且旧 manifest SHA 不变，证明临时文件没有把失败输出截断／stage。上述 staging 只包本项 exact move/管理文件，不包其他用户脏改。

5. 定向回归（不在本蓝图轮运行）：

   ```bash
   PYTHONPATH=solver/src:models/src:third_party/setp_hgs_kernel \
     build/python_envs/setp-independent-hgs/bin/python -m pytest -q \
     solver/tests/test_problem_hgs_control.py \
     solver/tests/test_problem_hgs_bi_objective_population.py \
     solver/tests/test_problem_hgs_integrated_foundation.py
   ```

   预期全部通过。

6. 受保护哈希必须与本文件开头三值逐位相同。

#### F. 净行数预算

- 三件或四件纯移动：`+0/−0`（文件改名不计净行）。
- `UPSTREAM_PROVENANCE.tsv` 与 manifest：令最终 `git ls-files third_party`（含这两个管理文件）行数为 `T`，TSV 为 `T−1` 行（`T−2` 数据行＋表头），manifest 为 `T−1` 行（只排除自引用的 manifest，包含 TSV 字节），合计 `+(2T−2)/−0`；不写旧现场的假定 T。
- GA 处置在 K0-PROVENANCE 前为 `UNKNOWN`，不得写“净增 ≤0”。

---

### 工作项 W0.3　探索包与正式包字样分离

#### A. 现状取证

1. 通用 `solver/scripts/experiment_acceptance.py` 接受调用方传入 `success_verdict/failure_verdict`，没有把探索包写成正式包；骨架把病灶归给该文件是错误的。
2. 真正病灶在 `solver/scripts/run_public_v2_28_clean_ruler.py`：
   - `_worker_failure:860-904` 把 success 字样硬编码为 `FORMAL_RUN_COMPLETE`；
   - `_worker_main:907`，metadata 在 :918-919 已保存 `run_kind`，但 :1002-1027 的 acceptance 仍对 probe/formal 都传正式字样；
   - `_validate_run_package:1151-1187` 在 :1161 总是期待 `FORMAL_RUN_COMPLETE`；
   - probe 调用在 :1351-1382（:1363 明确 `run_kind="probe"`），正式 batch 在 :1435；
   - parser :1579-1604 已有 `--run-kind {probe,formal}`。
3. `solver/tests/test_public_clean_ruler_worker_env.py:78-116` 的 worker fixture 尚未断言 probe/formal verdict 分离。

#### B. 积木清单

| 积木 | 版本 | 接口 | 许可证 | 路径 | 人类作品证据 |
|---|---|---|---|---|---|
| 项目现有 acceptance | 当前 HEAD | `assess_run(..., success_verdict, failure_verdict)` | 项目代码 | `solver/scripts/experiment_acceptance.py:51-91` | 已有测试和多个 runner 消费 |
| Python stdlib | 3.10+ | 常量、纯函数 tuple 返回 | PSF | 本机 | Python 官方实现 |

不新增判定器；只把现有 `run_kind` 映射到已有参数。

#### C. 拼装步骤

1. 在 `run_public_v2_28_clean_ruler.py` 的模块常量区新增四个字符串常量：
   - `PROBE_SUCCESS_VERDICT = "PROBE_RUN_COMPLETE"`；
   - `PROBE_AUDIT_FAILURE_VERDICT = "PROBE_RUN_FAILED_AUDIT"`；
   - `FORMAL_SUCCESS_VERDICT = "FORMAL_RUN_COMPLETE"`；
   - `FORMAL_AUDIT_FAILURE_VERDICT = "FORMAL_RUN_FAILED_AUDIT"`。

2. 在 :907 前新增纯函数 `_run_verdicts(run_kind: str) -> tuple[str, str]`：只接受 `probe/formal`，返回上述对应 tuple；其他值抛 `ValueError`。这是配置映射，不改变 acceptance 算法。

3. 在 `_worker_main:1002-1027`，把硬编码字符串改为：
   - `success_verdict, failure_verdict = _run_verdicts(args.run_kind)`；
   - 将两变量传给现有 `assess_run`；不得导入不存在的 `assess_experiment_acceptance`。

4. 在 `_validate_run_package:1151-1187`，从包 metadata 读取并校验 `run_kind`，用 `_run_verdicts(run_kind)[0]` 代替 :1161 的固定正式成功字样。

5. `_worker_failure:860-904` 的异常收口继续使用通用 `RUN_FAILED`，因为这是“worker 异常”而非 acceptance 审计失败；只把其未实际消费的固定 success 参数改为按已写入 metadata 的 run_kind 选择，不能把异常伪装成 audit failure。

6. 在 `test_public_clean_ruler_worker_env.py:78-116` 参数化 `run_kind`，分别断言 probe/formal 的成功与审计失败字样；保留故障注入 exit 2 断言。

7. 在共享 `experiment_acceptance.py:183-227 validate_five_file_package` 内，复用 `finalize_five_file_package:164-170` 已有的文件枚举规则：对 `output.rglob("*")` 下所有 regular file 重算 `actual_hashes`；finalize 与 validate 两边都只排除 `artifact_hashes.json` 自身、`._*` AppleDouble 和第 8 步明确的五件套外 operational marker `DONE`。要求 `recorded_hashes == actual_hashes` 的 key 集与每个 SHA 逐位相等，再做现有 accepted/verdict 检查。这不新造完整性判据，只把 finalize 已有的 exact map 作反向验证；删一个 hash key、增一个非 `DONE` 的未登记文件或改一个字节均必须拒绝。

8. `run_public_v2_28_clean_ruler.py:1549-1563` 的 `DONE` 明确是 **seed-batch 五件套外**的运维完成 marker，不是 worker leaf 或科学 artifact。保持现有安全顺序 `finalize -> validate -> _atomic_text(DONE)`，不得在五件套闭合前预写成功 marker。`_validate_run_package` 继续只验 worker leaf 的五件套，**不要求 leaf 有 DONE**；只有 F5 aggregate 验 seed-batch 时另外要求 `DONE` 存在且内容以 `FORMAL_CANDIDATE_BATCH_COMPLETE` 开头。seed-batch finalize、hash 或 validate 任一步异常时 `DONE` 必须不存在。

#### D. 缺口如实

- 无外部积木缺口。病灶是已有枚举值到已有 acceptance 参数的漏接线。
- `UNKNOWN`：历史消费者是否把 `FORMAL_RUN_COMPLETE` 当作所有 probe 的查询键。施工前需用 E.1 全仓 grep；发现消费者时同步改为按 metadata `run_kind` 分支，不得保留兼容谎言。

#### E. 验收

1. 第一轮事实复现 E2（acceptance 已参数化，FORMAL 硬编码位于 public caller）：

   ```bash
   rg -n 'def assess_run|success_verdict|failure_verdict' \
     solver/scripts/experiment_acceptance.py
   rg -n 'FORMAL_RUN_COMPLETE|FORMAL_CANDIDATE_BATCH_COMPLETE' \
     solver/scripts/run_public_v2_28_clean_ruler.py
   ```

2. 全仓字样定位：

   ```bash
   rg -n 'FORMAL_RUN_COMPLETE|PROBE_RUN_COMPLETE|run_kind' \
     solver/scripts solver/tests --glob '*.py'
   ```

   预期 public runner 中正式硬编码只存在常量定义和正式映射，不存在 probe 路径直接引用。

3. 定向测试：

   ```bash
   PYTHONPATH=solver/src:models/src:third_party/setp_hgs_kernel \
     build/python_envs/setp-independent-hgs/bin/python -m pytest -q \
     solver/tests/test_public_clean_ruler_worker_env.py
   ```

   预期全部通过；probe 成功＝`PROBE_RUN_COMPLETE`，formal 成功＝`FORMAL_RUN_COMPLETE`，故障注入仍 exit 2。

4. 纯函数内省：

   ```bash
   PYTHONPATH=solver/scripts python3 -c \
     'import run_public_v2_28_clean_ruler as r; assert r._run_verdicts("probe")[0]=="PROBE_RUN_COMPLETE"; assert r._run_verdicts("formal")[0]=="FORMAL_RUN_COMPLETE"'
   ```

   预期无输出、exit 0；不运行求解器。

5. 共享 package validator 增定向 fixture：正常 finalize 包通过；从 `artifact_hashes.json` 删一个仍存在文件的 key 被拒绝；新增非 `DONE` 的未登记文件被拒绝；public finalize/validate 故障时 `DONE` 不存在，只有成功后才原子写入固定 verdict 前缀。每个失败 fixture 都应在调用 child solver 前暴露，不得由聚合器补 hash key。

#### F. 净行数预算

- 生产：约 `+32/−8`（包括 shared validator exact-map 和 public `DONE` marker 接线）。
- 测试：约 `+40/−2`。

---

### 工作项 W1.1　动态在途趟的未来充电分类

#### A. 现状取证

1. 解的数据结构不是“Route 内嵌 charging action”：
   - `solver/src/setp_solver/solution.py:28-33`：`@dataclass(frozen=True) class Route(vehicle_id, vehicle_type, home_depot_id, node_sequence)`；
   - :36-46：`ChargingAction(vehicle_id, station_id, energy_kwh, occupancy_minutes, charge_start_second, charge_day_offset=0, start_energy_kwh, end_energy_kwh, charging_curve_id)`；
   - :83-87：`Solution(routes, charging_actions, cross_site_services)`。
   真实关联键是 `ChargingAction.vehicle_id == Route.vehicle_id`；:11-19 的 `physical_vehicle_id()` 说明带 `#T` 的完整 route id 才绑定具体趟。
2. duty 层已有更细结构：
   - `algorithms/problem_hgs/model.py:34-78 DutyTrip`；
   - :81-105 `DutyChargingSession(trip_index, station_id, energy_kwh, occupancy_minutes, charge_start_second, charge_day_offset, start_energy_kwh, end_energy_kwh, charging_curve_id, locked)`；
   - :328-338 `PhysicalVehicleDuty(..., trips, charging_sessions, dynamic_commitment, schedule)`；
   - :492-525 `to_solution()` 用 `duty.route_id(session.trip_index)` 生成 action；:527-630 `from_solution()` 在 :567-582 按 physical base＋trip index 回绑。
3. `search/multitrip_schedule.py:84-99 ScheduledTrip` 已有起终 SOC、趟间充电、`in_route_charge_energy_kwh`、固定出发 SOC；:142-161 `MultiTripCertificate` 的 `initial_battery_kwh` 在 :155。
4. 静态证书 cut：
   - `search/dynamic_multitrip_schedule.py:123-235 cut_certificate_at_trigger()`；
   - :145-157 把路线分为 completed/in_progress/editable；
   - :159-176 建 route→asset/action，:175-176 只锁 `start <= trigger` 的 action；
   - :181-185 已由 walk_first 修为先读 `certificate.initial_battery_kwh`，缺失才读 `prices.initial_ev_battery_kwh`；
   - :187-201 对 started route 扣整趟 drive (:195-196)，却只加已经开始的 charge (:197-201)。
   因此 trigger 位于趟内且该趟公共充电在未来时，整趟已被当成承诺，却既不锁未来 action，也不把其能量计入释放 SOC。
5. 动态证书 cut：
   - 同文件 :238-354 `cut_dynamic_certificate_at_trigger()`；
   - :279-289 分类趟；:291-299 按 `trip_by_id[action.vehicle_id]` 回绑，但 :298 仍只锁已开始 action；
   - :301-320 同样扣 started trip 全耗能 (:312-315)，只加已开始充电 (:316-320)；
   - :342-344 合并 inherited/new locks。
6. 丢失会继续传播：`main3b_backend.py:806-809` 把 completed＋in-progress 都视为 committed；:1271-1302 的 `_advance_prior_history()` 把 route 全进历史，但 action 只取 prior＋`cut.locked_charging_actions`。`scripts/run_problem_hgs_c8_stream.py:143-173` 同构。
7. 不是所有未来 action 都应锁。`tests/test_dynamic_multitrip_schedule.py:301-455` 已覆盖“未出发 route 的未来出发前充电仍可编辑”；缺口仅为 `IN_PROGRESS` route 所附未来充电。

#### B. 积木清单

| 现成件 | 版本／路径 | 签名 | 许可证／出处 | 能做什么 | 不能做什么 |
|---|---|---|---|---|---|
| 执行账本 | 当前 HEAD / `certificate_execution.py:108-189` | `build_certificate_execution_ledger(solution, certificate, instance, prices) -> CertificateExecutionLedger` | 项目现有实现 | :145-169 按 route 聚合 action，:173-182 做全账校验 | 不返回 cut-time SOC 或 action disposition |
| 充电账校验 | 同文件 :416-553、:556-669 | `_validate_charging_ledger`、私有 `_validate_public_charging_ledger` | 项目现有实现 | 用现有能耗与充电曲线闭合整趟 | 私有、返回 None，不是分类 API |
| 路线时序 | `multitrip_schedule.py:389-398` | `route_timing(..., charging_actions=None, validate_battery=True, ...) -> TripTiming` | 项目现有实现 | 复算整趟 timing/SOC | 不计算 cut 释放状态 |
| 固定路线充电 | `search/charging.py:93-102` | `solve_charging_fixed_route(...) -> list[ChargingAction]` | 项目现有实现 | 从全局初始电量重放整趟 | 不是在途 cut API |
| PyVRP | 0.12.2／当前主线 | multi-trip HGS | MIT / https://github.com/PyVRP/PyVRP | 有 multi-trip 基础 | EVRP 仍是公开缺口，见 https://github.com/PyVRP/PyVRP/issues/441；没有本语义 |
| VROOM | 1.15.0 | VRP engine | BSD-2-Clause / https://github.com/VROOM-Project/vroom | 公开路线优化引擎 | 未发现本 cut-time SOC/action API |

底层受保护核 `cost.py:516-520 charging_curve_for_action(...)` 与 :1108-1114 `ev_instance_arc_energy_kwh(...)` 只能调用，不得在本项改动。

#### C. 拼装步骤

1. 先完成 W3.3 的 10 流共同 initial cut 观测探针，再进入 K5。当前没有允许直接拼装的分类积木，因此未按 K5 前不得新增 `is_future_charge_committed()`、不得在两个 cut 函数中手写 boolean 规则。
2. 若后续狩猎找到并经用户批准标准“在途 trip event ledger”积木，或 K5 明确选择“批准一个 PROJECT_DOMAIN 状态转移组件”，接线位置固定为：
   - 在 `cut_certificate_at_trigger():145-157` 完成 route 状态分类后调用一次；
   - :175 的 locked-action 选择与 :197 的 SOC 回放必须读取同一个 disposition 结果，不能各写一套条件；
   - 在 `cut_dynamic_certificate_at_trigger():279-289` 完成 trip 状态分类后调用一次；
   - :298 的锁定与 :316 的 SOC 回放同读该结果。
3. 输入只准现有 `Route/ChargingAction` 或 `DutyTrip/DutyChargingSession` dataclass；输出必须是 typed event/disposition，不得新造平行字典。若走 K5 的项目实现分支，文件身份必须为 `PROJECT_DOMAIN`、代码角色为状态转移纯函数；它拥有“哪些未来动作承诺／何时释放 SOC”的领域语义，**不是 PROJECT_ADAPTER**，也不借适配件 250 行上限掩盖身份。
4. 复算能量时只调用 B 栏现有 `ev_instance_arc_energy_kwh`、`charging_curve_for_action` 和完整账校验；状态转移组件不得复制能耗公式、充电曲线或调度循环。
5. 保留 `NOT_STARTED` route 的未来出发前充电可编辑语义；只有积木能明确表达“在途 trip 已承诺、其 route-attached future action 随之承诺”时才解锁本项。

#### D. 缺口如实

`HALT_NO_BRICK`：仓内、冻结 PyVRP 0.12.2、PyVRP 当前主线／issue #441、VROOM、仓内 dvrpsim/EURO 快照中，均未找到“在途趟＋趟内未来充电＋下一合法释放边界 SOC／锁定归属”的标准人类实现/API。已有函数只做整趟生成或验证。按 P101，本项停，不以“项目薄层”名义自行发明分类器。只有 K5 对“批准一个 PROJECT_DOMAIN 状态转移组件”的明确选择才能解锁项目实现；未选或选择缓办时保持 HALT。

#### E. 验收

第一轮事实复现 E3（Route 与 ChargingAction 分离，并以完整 `vehicle_id` 关联）：

```bash
nl -ba solver/src/setp_solver/solution.py | sed -n '8,90p'
rg -n 'action\.vehicle_id|route\.vehicle_id|physical_vehicle_id' \
  solver/src/setp_solver/algorithms/problem_hgs/dynamic.py
```

第一轮事实复现 E5（当前 future charging 只收 editable route；in-progress route 被归入 committed）：

```bash
nl -ba solver/src/setp_solver/algorithms/problem_hgs/dynamic.py | sed -n '139,170p'
rg -n 'in_progress_route_ids|locked_charging_actions' \
  solver/src/setp_solver/search/dynamic_multitrip_schedule.py \
  solver/src/setp_solver/algorithms/problem_hgs/dynamic.py
```

**E5 证据边界**：这条命令证明的是当前仓内与已检索范围的状态，不是“全网不存在”该实现。

当前 HALT 前另做只读接口定位：

```bash
rg -n 'def cut_certificate_at_trigger|def cut_dynamic_certificate_at_trigger|locked_charging_actions|initial_battery_kwh' \
  solver/src/setp_solver/search/dynamic_multitrip_schedule.py
```

预期定位到 A 栏所列接口，不产生文件。

只有标准积木获批后才新增并运行：

```bash
PYTHONPATH=solver/src:models/src:third_party/setp_hgs_kernel \
  build/python_envs/setp-independent-hgs/bin/python -m pytest -q \
  solver/tests/test_dynamic_multitrip_schedule.py \
  -k 'future_public_charge_on_in_progress or certificate_initial_battery'
```

预期新增的三个测试：

- `test_static_cut_locks_future_public_charge_on_in_progress_trip`；
- `test_dynamic_cut_locks_future_public_charge_on_in_progress_trip`；
- `test_static_cut_uses_certificate_initial_battery_with_legacy_fallback`；

均通过；原文件当前 10 tests，新增后预期 13 passed。未获砖前不得创建这些“先写死自造语义”的测试。

#### F. 净行数预算

- HALT 前：`+0/−0`。
- 找到人类标准砖后的 adapter 预算：`UNKNOWN`，由真实 API 决定，不能预编。
- 只有 K5 明确批准项目实现分支时，单列 `PROJECT_DOMAIN` 状态转移组件预算：候选模块约 `+70/−0`，两个 cut 接线约 `+24/−12`，性质与回归测试约 `+90/−0`；合计约 `+184/−12`。这是施工估算，不是科学门槛，也不与 adapter 预算合并。

---

### 工作项 W1.2　统一实际执行身份

#### A. 现状取证

1. 请求参数散在三层：
   - `algorithms/problem_hgs/runner.py:59-80 ProblemHGSSearchParameters(frozen=True)`：seed、population、penalties、stagnation、crossover、whole-duty、DCREX、objective、education depth；
   - :279-302 `run_integrated_problem_hgs(...)` 另收 evaluator/policy/population identity/stop/arm/route engine/trajectory/proposal/initial accounting/treatment/prescreen/audit/cross/multi/type/route-layer；
   - `integrated_private.py:161-189 build_integrated_private_hgs(...)` 再收 penalty、stagnation、mechanism、whole-duty、charging、stop、population、proposal、schedule 两开关、fleet activation、objective、prescreen/audit、cross/multi/type、route-layer、education depth。
2. runner :332-335 自己临时拼 `active_proposal_engine = Sequential(route_engine, Mechanism(...原始 charging_policy))`；但 :426-463 调 builder 时传的是原 `proposal_engine`（通常 None）和散点开关。记录对象与真实执行 stage 不同。
3. builder :228 创建 `copied_parameters = SolveParams()`；:231-238 在 static＋请求 gap-off 时把实际 policy 改成 `charging_gap_enabled=True`；:325-348 才决定真实 route/mechanism stage；:1157-1209 `_educate` 消费它们；:1228-1265 才物化 kernel population 和 GA 参数；:1268-1276 返回 `IntegratedPrivateHGSBundle`。
4. 骨架称 copied SolveParams 是“不可变模式”不成立：
   - `third_party/setp_hgs_kernel/setp_hgs_kernel/solve.py:31-69 class SolveParams` 是 constructor＋私有属性，:83-109 只有只读 property；
   - 它不是 dataclass；嵌套 `genetic/penalty` 是可变 dataclass，`node_ops/route_ops` 是 list；
   - `GeneticAlgorithm.py:24 GeneticAlgorithmParams`、`PenaltyManager.py:13 PenaltyParams` 都可变。
   正确描述只能是“property-only 浅只读 facade”。
5. 当前 `runner.py:544-580 search_configuration_sha256(parameters, charging_policy, *, arm, proposal_engine=None, treatment=None)` 只 hash arm、`asdict(parameters)`、请求 policy、单一 proposal identity、可选 treatment；它在 builder 之前的 :341-351 计算，漏掉实际 policy rewrite、双 stage、kernel 参数和多组 live switches。
6. 直接 hash 消费者：`scripts/run_component_interaction.py:913-915`、`run_private_ablation.py:468-470`、`run_mixed_fleet_experiment.py:959-960`。完整 provenance 消费者包括 private runner :4105、mixed :1057；动态技术 runner :497-501 只读 singular proposal source/hash；包导出在 `problem_hgs/__init__.py:36-84`。
7. 另一个活接线缺口：private runner :205-207、:3059-3063 支持 `--mechanism-off charge_timing`，显式 engine :3398-3406 会传 `include_charging_candidates`；但默认 `proposal_mode=system` 在 :3412-3419 传 None，runner 没有该参数，builder :171 默认 True。故“system＋charge_timing off”仍可能实际生成充电候选。
8. `crossover_mode`、`dcrex_discount_factor` 当前只进入校验/hash/metadata，不改变 builder 行为；`PopulationParameters.tournament_size` 也未映射到 kernel params。它们是 requested-only/dead，不能放进 effective hash 冒充行为。
9. 两个仍在漏接的 live 身份：
   - `DutyEvaluationContext.incremental_full_truth_sentinel_enabled` 在 `evaluation.py:941-969` 决定 full-truth replay，在 `education.py:635-658` 决定接受动作后的 truth recheck；private CLI 的 `--disable-truth-sentinel` 可改它，因此不是只读 provenance。`DutyEvaluationContext.shift_aware_departure_enabled` 则在 `evaluation.py:436-460` 直接决定 rebuilt shift timing 是否启用，同样是稳定行为 bool，不是单纯 input 数值。
   - dynamic scout `:1182-1193` 的 route-only ablation 会把 `include_mechanism_refinement` 设为 false；当前 common `run_integrated_problem_hgs` 没有该参数，删除 scout 重复 runner 后若不补传，会静默回到 builder 默认 true。

#### B. 积木清单

| 积木 | 版本／commit | 接口 | 许可证 | 路径／URL | 人类作品证据 |
|---|---|---|---|---|---|
| Python dataclasses | Python ≥3.10 | `@dataclass(frozen=True)`、`asdict` | PSF | stdlib | Python 官方 |
| Python JSON/hashlib | Python ≥3.10 | `json.dumps(sort_keys=True, separators=(",", ":"))`、`hashlib.sha256` | PSF | stdlib | Python 官方 |
| PyVRP kernel params | 0.12.2 / `ea0c421...` | `SolveParams`、`PopulationParams`、`PenaltyParams` | MIT | 仓内 `third_party/setp_hgs_kernel` | README 指向 PyVRP commit 和 LICENSE |
| 项目 adaptive penalty params | 当前 HEAD | `population.PenaltyParameters`、`AdaptivePenaltyManager` | PROJECT_DOMAIN（existing） | `solver/src/setp_solver/algorithms/problem_hgs/population.py:74-110,139-159` | 已有冻结参数与真实罚系数管理器；不是 PyVRP `PenaltyParams` |
| 项目 route engine identity | 当前 HEAD | `IndependentKernelDutyRouteProposalEngine.source_id / identity payload` | 项目现有 | `kernel_proposals.py:203-317` | 已有 source/hash API 与测试 |
| 项目组合 proposal stage | 当前 HEAD | `SequentialProposalEngine(providers, source_id)`、`MechanismProposalEngine(context, charging_policy, *, include_...)` | PROJECT_DOMAIN（existing） | `solver/src/setp_solver/algorithms/problem_hgs/proposals.py:83-123,330-371` | 已在 private runner 与 builder 使用；provider 顺序和机制开关决定真实候选流 |
| evaluator context identity | 当前 HEAD | `evaluation_context_sha256` | 项目现有 | `evaluation.py:288-298,499-505` | 已有 canonical mapping hash |

#### C. 拼装步骤

1. 新增 `solver/src/setp_solver/algorithms/problem_hgs/execution_identity.py`（身份＝PROJECT_ADAPTER，≤250 行）。只定义冻结 carrier 与 canonical primitive payload；不拥有搜索、RNG、stage 调度或 cache。
2. 在该文件定义 `@dataclass(frozen=True) class EffectiveExecutionBundle`，字段固定为以下并集：
   - 身份：`schema_version: str`，固定新值 `resetp.problem_hgs.effective_execution.v1`；
   - 运行对象：`effective_charging_policy`、`route_engine`、`route_stage_engine`、`mechanism_stage_engine | None`；
   - 稳定算法身份：`formal_identity_eligible: bool`、`route_engine_source_id`、`route_stage_source_id`、nullable `mechanism_stage_source_id`、nullable `route_stage_configuration`、nullable `mechanism_stage_configuration`；configuration 只能是步骤 3 产生的 JSON primitive snapshot，不能保存 live object；charging policy 的九个标量／枚举字段 `strategy,carbon_weight,depot_charge_window_mode,charge_timing_policy,charge_amount_strategy,public_station_candidate_mode,first_trip_prev_night_enabled,frvcpy_enabled,charging_gap_enabled`；以及从最终 `evaluator.context` 读取的 `fairness_enabled: bool` 与有效 `fairness_theta: float | None`（关闭时固定 None，不能让不生效 theta 改 hash）；
   - 运行时身份：`route_engine_runtime_sha256`、`route_stage_runtime_sha256`、nullable `mechanism_stage_runtime_sha256`、`charging_profile_input_sha256`。现有 engine `identity_sha256` 含 instance、seed、fleet registry，动态时还含 trigger/assets/future customers（`kernel_proposals.py:240-317`）；这四个 runtime hash 必须写 provenance，但不得进入跨 seed 的 search-configuration hash；
   - kernel population 六个原始量：`min_pop_size`、`generation_size`、`num_elite`、`num_close`、`lb_diversity`、`ub_diversity`；
   - complete-duty adaptive penalty 的实际 primitive snapshot：对传入 `population.PenaltyParameters` 做 `asdict`，完整保存 `initial_penalty_per_unit`、`solutions_between_updates`、`penalty_increase`、`penalty_decrease`、`target_feasible`、`feasibility_tolerance`、`minimum_penalty`、`maximum_penalty`、排序后的 `initial_penalty_by_type`；不得用 PyVRP `PenaltyParams` 冒充这组实际参数；
   - 真正被消费的 copied kernel 字段：`repair_probability` 与 `repair_booster`；把传入 `stagnation_patience` 以实际接线名 `num_iters_no_improvement` 保存；其余未消费的 copied `PenaltyParams` 字段不进 effective hash；
   - live 行为开关：`include_mechanism_refinement`、`include_whole_duty_type_exchange`、`include_charging_candidates`、`incremental_full_truth_sentinel_enabled`、`shift_aware_departure_enabled`、`schedule_cross_repair_fallback`、`schedule_all_changed_move_evaluation`、`fleet_activation_enabled`、`objective_mode`、`charging_prescreen_enabled`、`charging_prescreen_audit_limit`、`cross_depot_enabled`、`multi_trip_enabled`、`type_exchange_enabled`、`route_layer_crossover_enabled`、`education_depth_limit`。
3. 在 `execution_identity.py` 定义只读 `proposal_stage_configuration(engine) -> dict[str, JSON primitive]`；它不调用 `propose`，只允许并递归快照以下已知项目类型：
   - `IndependentKernelDutyRouteProposalEngine`：保存类型标记和现有 `source_id`；该 source id 已在 `kernel_proposals.py:203-239` 编码 propulsion、depot split、volume、shift-neighbour、cross-depot、multi-trip、type-exchange、shift-aware price、truth-boundary/epsilon 与 stream role；
   - `MechanismProposalEngine`：保存类型、`source_id`、`include_charging_candidates`、`include_non_charging_candidates`、`include_structural_channels`、`cross_depot_enabled`、`multi_trip_enabled`、`type_exchange_enabled`，以及九字段 charging-policy snapshot；
   - `SequentialProposalEngine`：保存类型、outer `source_id`，再按 `providers` tuple 原顺序递归保存每个 provider 的上述配置。

   private runner `:3407-3411` 的已知 combat 形态必须准确成为：outer source `problem-hgs-combat-all-duty-channels-v1`；provider 0＝route engine；provider 1＝source `problem-hgs-problem-mechanism-actions-v1` 的 mechanism engine，其中 `include_non_charging_candidates=True`、`include_structural_channels=True`，其余开关和 policy 取实际值。builder 默认形态则保留 :334-342 的 route stage 与 nullable mechanism stage 两个顺序阶段；不得把两种执行结构压成同一个 source id。遇到其他类型时：若 `expected_search_configuration_sha256 is not None`，在 `algorithm.run` 前触发 D.5；若 technical 且 expected 为 None，则保留 runtime/source provenance、置 `formal_identity_eligible=false` 和 configuration/search hash 为 null 后继续既有行为。不用 `repr()` 或类名猜配置，也不让该结果冒充 formal identity。

   给 bundle 提供两个只读 payload：
   - `algorithm_configuration_payload() -> dict[str, JSON primitive]`：排除四个 live object、三个 runtime engine SHA、instance/seed/fleet/dynamic state/evaluator input data；放入完整 `route_stage_configuration`／nullable `mechanism_stage_configuration`、charging policy 九字段、effective fairness 开关／theta、population、project penalty、copied kernel 字段和 live switches；Pi0 values/hash 仍是 input identity，只进 provenance；
   - `runtime_identity_payload()`：保存三个完整 engine SHA 与 `charging_profile_input_sha256`，供 provenance，不承担跨样本相等合同。

   `search_configuration_sha256` 只在 `formal_identity_eligible=true` 时 hash 第一个 payload；否则为 null。`carbon_profiles_by_day_offset` 的数据内容若非 None，canonical 化后只进 `charging_profile_input_sha256`；其使用方式已由 policy 字段记录。禁止 `repr(live_object)`。
4. 在 `integrated_private.py:126-138 IntegratedPrivateHGSBundle` 新增 `effective_execution: EffectiveExecutionBundle`。在 `runner.py:188-203 ProblemHGSRunResult` 同样新增 `effective_execution: EffectiveExecutionBundle`；现有唯一正常结果构造点 `_finish_result:617-650` 增同名参数，`:506` 调用点传 `built.effective_execution`，`:638 ProblemHGSRunResult(...)` 必须写入该字段。caller stop 仍返回正常 result；异常继续向外抛给 runner 的失败包逻辑，不新造“异常也返回 `ProblemHGSRunResult`”语义。
5. 在 `build_integrated_private_hgs` 中：
   - :231-238 得到 actual policy 后保存；
   - :325-348 得到 actual stages 后保存；
   - 把 :1228-1265 只做参数物化的部分前移到 stage 决议后，先得到 actual population primitives、传入项目 `PenaltyParameters` 的 canonical `asdict`、copied `repair_probability/repair_booster` 与 `num_iters_no_improvement`；
   - 在创建 cache/coordinator/GA 前构造唯一 `effective_execution`；`fairness_enabled`、effective theta、`incremental_full_truth_sentinel_enabled` 与 `shift_aware_departure_enabled` 必须从此时最终 `evaluator.context` 读取，因为它们分别在 `evaluation.py:436-460,680-691,773-784,941-969` 改变 shift timing／violation／penalised cost／truth replay；
   - 后续 cache、`_educate`、GA 参数全部从 bundle 字段读，不再从原始函数参数重复读取。
6. 在 `runner.py:279-302 run_integrated_problem_hgs` 新增三个 keyword-only 参数：
   - `include_mechanism_refinement: bool = True`，向 builder 原名透传；dynamic scout 的 route-only ablation 传 false，其他调用保持现有 true；
   - `include_charging_candidates: bool = True`，向 builder 透传；private runner :3513-3536 传入 :3059-3063 的实际 `mechanism_enabled["charge_timing"]`，只补现有开关漏传；
   - `expected_search_configuration_sha256: str | None = None`，technical 调用传 None，formal 调用必须传 manifest 对所选 profile 冻结的 64 位值。
7. 删除 `runner.py:332-335 active_proposal_engine`。把 :341-376 的 provenance/hash 构造移到 :426-463 builder 返回之后，以 `built.effective_execution` 为事实源；只有 formal-eligible bundle 才算 `actual_search_configuration_sha256`。若 expected 非 None 而 bundle 不 eligible、actual 为 null或不等于 expected，立即 `raise ValueError`。这个比较必须位于 builder 返回之后、现 :471 `bundle.algorithm.run(_IntegratedStop())` 之前；不允许搜索结束后才验。
8. 把 `runner.py:544-580` 签名改为 `search_configuration_sha256(effective_execution: EffectiveExecutionBundle) -> str`，只 hash `algorithm_configuration_payload()`；旧的 parameters/policy/proposal/treatment 兼容分支删除，不伪装旧 digest。
9. 在 `ProblemHGSRunProvenance:206-227`：
   - 保留 arm、instance、declared seed、population/profit/fairness/sentinel/trajectory/initial accounting；
   - 用 `route_engine_source_id/runtime_sha256`、`route_stage_source_id/runtime_sha256`、nullable `mechanism_stage_source_id/runtime_sha256` 代替 singular proposal 字段；
   - 保留 evaluator context、instance、declared seed、fleet/input identity，使每次运行仍可逐位追溯；这些 runtime 字段不进入 search-configuration hash；
   - 新增 `effective_execution_schema`、`effective_algorithm_configuration: Mapping[str, object] | None`、`effective_runtime_identity: Mapping[str, object]` 和 `search_configuration_sha256: str | None`。formal-eligible 时 configuration/hash 非 null；technical 遇未知 custom engine 时两者为 null 而runtime identity 仍保留。前两个 mapping 分别由构造时的 `algorithm_configuration_payload()` 与 `runtime_identity_payload()` 深拷贝成 JSON primitive snapshot；持久化 provenance 不得依赖 live policy/engine 对象。
10. 同步消费者：
    - 动态 runner 原 :497-501 改读三组 stage 身份；
    - private runner :3851-3966 的当场 policy/stage/switch metadata 改读 `result.effective_execution`；需写 JSON 的部分只序列化 `result.provenance.effective_algorithm_configuration/effective_runtime_identity`，不序列化 live object；
    - `run_component_interaction.py:913-915`、`run_private_ablation.py:468-470`、`run_mixed_fleet_experiment.py:959-960` 不再提前自行 hash；只读 runner 返回的最终 hash；
    - `problem_hgs/__init__.py:36-84` 导出新 dataclass 和新函数签名。
11. `crossover_mode`、`dcrex_discount_factor`、`tournament_size` 明标 `requested_only_no_effect`，不进入 effective hash。若未来要接活，另做开源积木取证和用户批准，不能在身份工作项顺手改变算法。

#### D. 缺口如实

- 冻结 dataclass 只冻结外壳；policy、engine、PyVRP params 内部仍可能可变。hash 必须来自构造时 primitive snapshot，蓝图不声称深不可变。
- `HALT_NO_BRICK`：当前 `stop: Callable[[ProblemHGSSearchState], bool]` 没有 typed/canonical identity；不能 hash `repr(stop)`。本版把 stop/budget 留在 run provenance，不进 search-configuration hash。若用户要求其进 hash，先找标准 typed stop descriptor。
- runner :305 与 :384-405、:617-638 存在初始化／run wall 可能双计时的问题；它不属于“身份接线”，本项只登记，不顺手改语义。
- declared random seed 与 route engine constructor seed 当前无一致性校验。拒绝不一致还是记录双身份会改变合同，标 `UNKNOWN`，不在本项替用户定。
- `HALT_NO_BRICK_CONFIGURATION_IDENTITY`：任意未知外注入 `proposal_engine` 目前只承诺 `source_id/identity_sha256`，后者可能混入 runtime data。正式 profile 只允许步骤 3 能完整递归快照的 builder 标准 stages 或 private runner 已知 combat `Sequential(route_engine, mechanism_engine)`；Legacy、用户自定义或新 provider 若没有人类来源且字段完整的稳定 configuration payload，只可 technical并得到 null stable hash，不得靠 source_id 猜配置，也不得阻断原有 technical harness。

#### E. 验收

1. 第一轮事实复现 E4（`SolveParams` 只是 property facade，内部 dataclass/list 仍可变）：

   ```bash
   nl -ba third_party/setp_hgs_kernel/setp_hgs_kernel/solve.py | sed -n '31,110p'
   rg -n '^@dataclass|^class (GeneticAlgorithmParams|PenaltyParams)|node_ops|route_ops' \
     third_party/setp_hgs_kernel/setp_hgs_kernel/GeneticAlgorithm.py \
     third_party/setp_hgs_kernel/setp_hgs_kernel/PenaltyManager.py
   ```

2. 第一轮风险 R3 复现（`charge_timing off` 在 default system 路径丢失；本轮双方已核实）：

   ```bash
   nl -ba solver/scripts/run_problem_hgs_private_technical.py | sed -n '201,208p;3057,3064p;3398,3420p;3513,3535p'
   nl -ba solver/src/setp_solver/algorithms/problem_hgs/runner.py | sed -n '279,303p;330,336p;426,440p'
   nl -ba solver/src/setp_solver/algorithms/problem_hgs/integrated_private.py | sed -n '161,175p;325,344p'
   ```

   证据链固定为：`mechanism_off` 正确算出 `charge_timing=false` → 显式 mechanism engine 正确接收 false → 默认 `system` 把 `proposal_engine=None` 传入 common runner → common runner fallback 自建 `MechanismProposalEngine` 时没有 `include_charging_candidates` 参数 → builder 采用默认 `True`。因此 W1.2 的接线测试必须锁住“metadata 关闭＝真实候选也关闭”。

3. 新增 `solver/tests/test_problem_hgs_execution_identity.py`，至少十例：
   - `test_default_runner_records_the_same_two_stages_that_builder_executes`；
   - `test_gap_off_static_request_hashes_effective_gap_on_policy`；
   - `test_each_live_execution_switch_changes_effective_hash`；
   - `test_requested_dead_fields_do_not_change_effective_hash`；
   - `test_system_charge_timing_off_reaches_actual_mechanism_stage`；
   - `test_seed_instance_and_dynamic_state_change_runtime_identity_not_search_hash`；
   - `test_charge_timing_policy_changes_search_hash`；
   - `test_fairness_on_and_theta_change_search_hash_but_disabled_theta_does_not`；
   - `test_truth_sentinel_switch_changes_effective_hash_and_formal_override_rejects`；
   - `test_shift_aware_departure_switch_changes_effective_hash`；
   - `test_route_only_dynamic_ablation_reaches_builder_with_mechanism_refinement_false`；
   - `test_expected_search_hash_mismatch_raises_before_algorithm_run`（mock `algorithm.run` 并断言 0 次调用）；
   - `test_unknown_custom_engine_runs_technical_with_null_formal_identity_but_formal_rejects_before_run`（复用现有 `_Provider/_OneBatchEngine` 形态，technical 行为不变，formal 0 次 run）。
   - `test_caller_stop_result_contains_effective_execution_and_primitive_provenance`（覆盖正常 caller stop，并对 provenance 做 `json.dumps(..., allow_nan=False)`；预期 hash 错配测试另断言异常向外抛且 `algorithm.run` 0 次）。

4. 运行：

   ```bash
   PYTHONPATH=solver/src:models/src:third_party/setp_hgs_kernel \
     build/python_envs/setp-independent-hgs/bin/python -m pytest -q \
     solver/tests/test_problem_hgs_execution_identity.py
   ```

   预期上述 tests 全部 pass。

5. 回归有限合同：

   ```bash
   PYTHONPATH=solver/src:models/src:third_party/setp_hgs_kernel \
     build/python_envs/setp-independent-hgs/bin/python -m pytest -q \
     solver/tests/test_problem_hgs_integrated_foundation.py \
     solver/tests/test_problem_hgs_p81_wiring.py \
     solver/tests/test_problem_hgs_runner_sentinel.py \
     solver/tests/test_component_interaction_harness.py \
     solver/tests/test_private_ablation_harness.py \
     solver/tests/test_mixed_fleet_experiment_harness.py
   ```

   预期 exit 0；不写“全仓回归必定 N passed”的跨时代数字。

6. 静态断言：

   ```bash
   ! rg -n 'active_proposal_engine|search_configuration_sha256\(.*parameters' \
     solver/src/setp_solver/algorithms/problem_hgs/runner.py
   PYTHONPATH=solver/src:models/src:third_party/setp_hgs_kernel \
     build/python_envs/setp-independent-hgs/bin/python -c \
     'from setp_solver.algorithms.problem_hgs.execution_identity import EffectiveExecutionBundle as E; assert E.__dataclass_params__.frozen is True'
   ```

   第一条预期 0 命中；第二条 exit 0。每个 canonical hash 长度 64，JSON round-trip 后逐位相同。

#### F. 净行数预算

- 生产：约 `+150/−45`（含已知 stage 递归配置快照与 fail-before-search guard）。
- 测试：约 `+140/−0`。
- 合计：约 `+290/−45`；`execution_identity.py` 自身必须 ≤250 行。

---

### 工作项 W1.3a　单企业子算例与独立初始解

#### A. 现状取证

1. DEPOTSEARCH loader 不是“读一张 assignment CSV”：
   - `solver/scripts/run_problem_hgs_private_technical.py:682-690 _build_context(repo, instance_id, *, fleet_parameters, depot_charging_scenario_name)`；
   - :741-752 对 DEPOTSEARCH 固定 `60kw`，路由到 `_build_saved_suite_context`，package root 为 `data/ChinaInstances/china81_final_suite_v2_20260815`，witness report root 为 `solver/reports/instance_build_only_d996f755bd_20260815`；
   - :884-890 `_load_v3_suite_bundle(...) -> tuple[China81Bundle, Mapping[...]]`。
2. 该 loader 实际读取：package `instance_catalog.csv` (:902-920)、实例 `nodes.csv/orders.csv` (:911-920)、`fleet_caps.csv` (:922-940)、`facilities.csv` 或 source pool (:942-948)、可选 station assignments (:949-955)、DEPOTSEARCH 必需 `enterprise_assignment.csv` (:957-972)、`source_mapping.csv` (:1038-1044)、matrix reference 和 CV/EV 三类矩阵 (:1045-1074)、vehicle cost authority (:1075-1096)、固定日期 `2025-02-12` 的共享日历 (:1113-1134)。
3. :1291-1445 `_suite_context_from_built(...)` 还读 `shift_contract.json`、fleet rows、report 下 `health_witness_routes.csv`；:1409-1427 创建假中性的 `Pi0={depot:1.0}`、`externally_frozen=False`、`fairness_enabled=False`。bundle 在 :1224 明写 `formal_search_allowed=False`。
4. assignment 接口：
   - `solver/src/setp_solver/enterprise_assignment.py:16-24` 必需字段 `instance_id, customer_id, enterprise_id, enterprise_depot_osm, rule_id`；真 CSV 另含 `source_order_index`；
   - :36-45 `EnterpriseAssignment(customer_home_depot, enterprise_by_customer, source_path, source_sha256, normalized_mapping_sha256, rule_ids)`；
   - :48-57 `normalize_enterprise_depot_id(source_identity)` 将 `way/<digits>` 变为 `D_OSM_WAY_<digits>`；
   - :60-66 `load_enterprise_assignment(assignment_path, nodes_path, *, expected_instance_id, expected_customer_ids) -> EnterpriseAssignment`，:69-152 fail-closed。
5. 真数据：
   - 文件 `data/ChinaInstances/china81_final_suite_v2_20260815/instances/cn-jjj-50c-01-DEPOTSEARCH-d996f755bd/enterprise_assignment.csv`；
   - SHA-256 `68e3d65a99881d5dbafbee41da8ea954e0fcf48e8addbfbc2313f07fc1d5d25e`；
   - ENT_A＝C001..C025，25 户、6597 kg、47.5 m³，depot `D_OSM_WAY_1003511503`；
   - ENT_B＝C026..C050，25 户、6667 kg、48.0 m³，depot `D_OSM_WAY_1071205721`；
   - 唯一 rule `P65_2_NUMBERED_EQUAL_SPLIT_RAO2022_PRINT_P2731`；
   - `fleet_caps.csv:174-175`：A 为 3 CV＋3 EV，总 cap 6；B 为 7 CV＋7 EV，总 cap 14；均 60 kW。
6. `nodes.csv` 只有 `node_id,node_type,city,latitude,longitude,source_identity`，没有公共站的 enterprise ownership。若 `f` 是共享公共基础设施，可保留全部 f；若“own facilities”指企业私有站，现输入无法切分。
7. joint `health_witness_routes.csv` 不可按企业筛行：只读核算发现 24 个 customer/depot 与 assignment 不一致，首例 A-depot route `C022|C035` 含 ENT_B 的 C035。单干必须重建 seed。
8. 现成子集设施逐项：
   - `models/src/setp_instance_lab/generator.py:16 generate_scenario(config: ScenarioConfig) -> Scenario`：生成／重采样，不能保留 China81 身份；
   - `evrptwmf.py:28 parse_evrptwmf(path)`、:76 `load_base_distribution`、:97 `pairwise_distances`：解析／欧氏矩阵，不是 sealed subset；
   - `io.py:29 write_scenario_bundle(...)`：另一种 bundle 格式；
   - `search/dynamic.py:1391 _subinstance_for_customers(instance, customer_ids)` 保留全部 depot/f；
   - 同文件 :2110-2172 `_rebuild_instance_matrix(source: Instance, nodes: list[Node]) -> Instance` 正确切 distance、CV/EV profiles、vehicle params，可复用但当前是私有函数；
   - `c8_dynamic_stream.py:884 subset_c8_bundle(bundle, active_customer_ids)` 不切 depot/fleet caps；
   - 退役 `search/fairness.py:317 _subinstance_for_depot(...)` 丢 road profiles、vehicle params、num_cv/num_ev，禁止复用；
   - `build_china81_suite_rebuild_20260812.py:730 build_instance(...)` 会重新 zip task locations 和 shift assignment，改变当前 customer identity，不能用来重生成子例。
9. 可复用的现有 seed 设施：
   - 同 build script :1139 `build_edf_route_plans(built: BuiltInstance) -> tuple[tuple[RoutePlan, ...], str]`；
   - :1231 `minimum_edf_order_chains(built, plans) -> list[list[ScheduledPlan]]`；
   - :1369 `plans_to_solution(built, plans) -> tuple[Solution, dict[str,float], dict[str,tuple[ScheduledPlan,...]]]`；
   - `china81_completion.py:330 complete_china81_route_skeleton(skeleton, bundle, *, ...) -> China81CompletionResult`。
   不直接调用 build script :1416 `build_witness`，因为它先用 all-CV 检查，企业有限 fleet cap 下可能在 completion 前触发 FLEET_SIZE。
10. `_build_context` 的真实返回是 `(bundle, initial, pi0, context)`（private runner :3158-3166）；内部 `SimpleNamespace` :1469-1477 不对外返回。对 seed 函数 :1070-1415 做字段读取盘点，它们只访问 `built.instance`、`built.orders_by_customer`、`built.customer_home_depot`。因此不能声称 loader 已给调用方一个 `BuiltInstance`，但可由企业 slice 的既有 Node/route-contract 字段构造只含这三项的 typed input view。
11. private 初始化血统必须按真实用途分开：

   | 用途 | 当前真实依赖 | K7 覆盖 |
   |---|---|---|
   | F1 DEPOTSEARCH | 每次运行直接读取封存 `health_witness_routes.csv`；该见证由 `build_china81_suite_rebuild_20260812.py:1416 build_witness` 离线调用 `build_edf_route_plans` → `minimum_edf_order_chains` 生成 | 覆盖前两件的离线派生血统；不是运行时调用三件 |
   | F2 standalone 拟建 seed | C.8 拟现场调用 EDF route seed、chain/plan conversion 与 `complete_china81_route_skeleton` | 覆盖拟用三件 |
   | F5 公共 28 题 | 对三件的精确检索为 0 | **不覆盖，不得被 K7 阻塞** |

   DEPOTSEARCH 在 private runner :741 进入 saved-suite context，:1399 读取封存见证；通用 fallback 的 completion 路径不等于 DEPOTSEARCH 每次运行调用。K7 因此命名为 `K7-PRIVATE-INIT-PROVENANCE`，不能扩大成全仓初始化总门。

#### B. 积木清单

| 积木 | 版本／路径 | 签名 | 许可证／身份 | 人类作品证据／适用性 |
|---|---|---|---|---|
| assignment loader | 当前 HEAD | `load_enterprise_assignment(...) -> EnterpriseAssignment` | PROJECT_DOMAIN（existing） | 已有 fail-closed 测试；直接复用 |
| exact matrix slicer | 当前 HEAD / `solver/src/setp_solver/search/dynamic.py:2110-2172` | `_rebuild_instance_matrix(source, nodes) -> Instance` | PROJECT_DOMAIN（existing） | 已在动态路径使用；只原样搬为公共纯函数 |
| EDF route seed | 当前 HEAD / `solver/scripts/build_china81_suite_rebuild_20260812.py:1139` | 见 A.9 | PROJECT_DOMAIN；`provenance_status=UNKNOWN` | 贪心装箱属于行为代码；“已用于 witness”不是人类开源出处证据，当前不得调用 |
| exact chain cover | 当前 HEAD / `solver/scripts/build_china81_suite_rebuild_20260812.py:1231-1366` | 见 A.9 | PROJECT_DOMAIN；`provenance_status=UNKNOWN` | 含子集递归／链覆盖搜索；Git 提交者不证明原作者，当前不得调用 |
| route skeleton completion | 当前 HEAD / `solver/src/setp_solver/china81_completion.py:330-641` | 见 A.9 | PROJECT_DOMAIN；`provenance_status=UNKNOWN` | 它会建 all-CV baseline、枚举／贪心试验 EV variants 并分配有限车队，是行为算法而非单纯 checker replay；当前不得调用 |
| Python dataclasses | ≥3.10 | `dataclasses.replace`、`@dataclass(frozen=True)` | PSF | 标准 typed carrier |

没有找到“一次调用产出 exact enterprise bundle＋route contract＋finite-fleet seed”的整套外部积木。

#### C. 拼装步骤

1. 先执行 K1-FACILITY。A＝共享公共站＋正文披露（代理推荐，现数据只支持该语义）时继续；B＝企业私有设施时停在 D.2，等待带 ownership 的权威输入。推荐不得写成用户已决。
2. 新增 `solver/src/setp_solver/instance_subset.py`（`declared_identity=PROJECT_DOMAIN`，`code_role=PURE_FUNCTION`）。把 `search/dynamic.py:2110-2172 _rebuild_instance_matrix` **逐字搬出**，只改名为公开 `rebuild_instance_matrix(source: Instance, nodes: Sequence[Node]) -> Instance` 和类型 import；原 `search/dynamic.py` 改为 import/call 该函数，不保留双份。
3. 新增 `solver/src/setp_solver/algorithms/problem_hgs/enterprise_adapter.py`（身份＝PROJECT_ADAPTER，≤250 行），定义：

   ```python
   @dataclass(frozen=True)
   class EnterpriseSeedInput:
       instance: Instance
       orders_by_customer: Mapping[str, Mapping[str, float | str]]
       customer_home_depot: Mapping[str, str]

   @dataclass(frozen=True)
   class EnterpriseProblemSlice:
       bundle: China81Bundle
       route_constraints: RebuiltRouteConstraintContract
       seed_input: EnterpriseSeedInput
       enterprise_id: str
       depot_id: str
       customer_ids: tuple[str, ...]
       source_id: str
       mapping_sha256: str

   def slice_enterprise_problem(
       bundle: China81Bundle,
       route_constraints: RebuiltRouteConstraintContract,
       enterprise_id: str,
   ) -> EnterpriseProblemSlice:
       ...
   ```

4. `slice_enterprise_problem` 只做以下字段拼装，不拥有路线／搜索：
   - 从 `bundle.enterprise_assignment_by_customer` 选 exact customer ids，并拒绝空集／未知 enterprise；
   - 验证这些客户的 `customer_home_depot` 只有一个 depot；
   - 节点顺序固定为该 depot＋全部共享 `f`＋该企业客户，调用步骤 2 的矩阵切片得 `sliced_instance`；
   - 把 `bundle.fleet_caps_by_depot` 限成该 depot 的唯一一行 `selected_caps`，只从该行取 `num_cv/num_ev/total_fleet_cap`；紧接着执行 `sliced_instance = dataclasses.replace(sliced_instance, num_cv=int(selected_caps["num_cv"]), num_ev=int(selected_caps["num_ev"]))`，并把这个已同步 cap 的 instance 放入子 bundle。不得保留 `_rebuild_instance_matrix` 带回的 joint `Instance.num_cv/num_ev`；
   - 把 `bundle.charger_scenario_by_node` exact 限成 `{该 enterprise depot} ∪ {步骤 4 保留的全部共享 f node ids}`；depot row 的 `charger_count/active_concurrency_limit/capacity_mode/charge_power_kw/parameter_class` 从原 bundle 对应 depot 原样复制，每个 retained `f` row 也从 joint bundle 逐字段原样复制。不得从 selected fleet caps 取充电功率，也不得保留 instance 中的公共站却删掉其 charger-scenario 真值；用标准 `dataclasses.replace` 建子 bundle；
   - 缩减 customer home/enterprise owner/shift/volume/source mappings；
   - `RebuiltRouteConstraintContract`（`evaluation.py:94-130`）的 `customer_shift_by_id/customer_volume_m3_by_id` 按入选客户裁剪，`shift_window_second_by_id` 只保留这些客户实际用到的 shift；`vehicle_volume_capacity_m3=route_constraints.vehicle_volume_capacity_m3` 原样传递，`source_id` 追加 enterprise slice identity。不得漏掉其必填正有限容量字段或另猜容量；
   - 构造 `EnterpriseSeedInput.orders_by_customer` 时，对每个入选 customer Node 精确映射：`shift_id=route_constraints.customer_shift_by_id[id]`、`time_window_early_minute=node.ready_time/60`、`time_window_late_minute=node.due_time/60`、`service_minutes=node.service_time/60`、`source_volume_m3=route_constraints.customer_volume_m3_by_id[id]`、`demand_kg=node.demand`；`instance` 使用已切片 instance，`customer_home_depot` 使用已切片 mapping。不得重新读／重排 sealed orders；
   - source id 包含原 bundle identity＋enterprise id；mapping hash 复用现有 canonical mapping hash，不写 `id()`。
5. 在 `run_problem_hgs_private_technical.py:2824-3015` 新增 `--enterprise-id`（不写死 choices，由 adapter fail-closed）。现有 `main:3159` 真实返回四个局部变量 `bundle, initial, pi0, context`；在该行后、evaluator 构造前调步骤 3，并在 D.4 解除且 C.8 有获准 seed 后一次性改成：
   - `bundle = enterprise_slice.bundle`；`initial = approved_enterprise_seed`；
   - `neutral = {enterprise_slice.depot_id: 1.0}`，`pi0 = neutral`；
   - `context = replace(context, bundle=bundle, independent_profit=neutral, independent_profit_identity=FrozenMappingIdentity(source_id=f"enterprise-neutral/{enterprise_slice.source_id}", value_sha256=mapping_sha256(neutral), externally_frozen=False), prior_profit={enterprise_slice.depot_id: 0.0}, rebuilt_route_constraints=enterprise_slice.route_constraints, fairness_enabled=False, theta=0.0)`。

   `EnterpriseSeedInput.instance` 与 `enterprise_slice.bundle.instance` 必须都引用 C.4 同一个已同步 cap 的 `sliced_instance`。上述四组 depot keys 必须 exact 为该企业单 depot，不改 sealed package，不让原 joint `initial/pi0/context` 混入 standalone。
6. `--enterprise-id` 与未来 `--pi0-manifest` 设为 argparse mutually exclusive。独立运行固定 `fairness_enabled=False`，不能用自己对自己的参与约束。
7. 不筛 joint witness，也不假装 `_build_context` 返回 `BuiltInstance`。runner 只取 `enterprise_slice.seed_input`；其 exact 三字段由步骤 4 构造，不重新分配 location/shift，不引入 `SimpleNamespace`。
8. **只有 K7-PRIVATE-INIT-PROVENANCE 选择 A，或三件分别找到并获准替代砖后**，seed 拼装才可严格调用获准的现有链，返回值逐项解包固定为：
   - `plans, reason = build_edf_route_plans(enterprise_slice.seed_input)`；`reason` 非空立即 `HALT_NO_ENTERPRISE_SEED`，不得把失败 tuple 继续传下去；
   - `skeleton, departures, scheduled_by_physical = plans_to_solution(enterprise_slice.seed_input, plans)`；三个返回值都按真实签名接住，哪怕本入口只继续消费 skeleton；
   - `completed = complete_china81_route_skeleton(skeleton, enterprise_slice.bundle, charge_amount_strategies=("just_enough",), depot_charge_window_mode="same_day_predeparture", charge_timing_policy="carbon_min", public_station_candidate_mode="fallback")`；四项逐字等于当前默认常量，不改成 F2 搜索 policy；
   - `approved_enterprise_seed = _with_registered_idle_duties(DutyIndividual.from_solution(completed.solution, customer_node_ids=enterprise_slice.customer_ids, source=f"enterprise-seed/{enterprise_slice.source_id}"), enterprise_slice.bundle)`；不得把 `China81CompletionResult` 本体误传给 `from_solution`。
   唯一接线固定为 private runner 从同目录模块直接导入 `from build_china81_suite_rebuild_20260812 import build_edf_route_plans, plans_to_solution`，把 `enterprise_slice.seed_input` 作为参数；Python 运行时只读上述三字段。不得动态加载、不得搬出／复制循环、不得现场二选一。若施工环境不能稳定导入该同目录模块，则 `HALT_IMPORT_SURFACE`，先把事实呈用户，不改写算法。
9. 若步骤 8 在 A 的 3+3 或 B 的 7+7 cap 下不能得到满服务可行 seed，立即触发 D.3；不增加车、不放宽时间窗、不写新 packing/search。

#### D. 缺口如实

1. `HALT_NO_BRICK`：不存在整套 exact enterprise subset＋seed API；本蓝图只允许用户已明确认可的“项目真值薄层”做字段裁剪，并拼现有 EDF/chain/completion。
2. `HALT_NO_BRICK`：若 `f` 被解释为企业私有设施，当前 nodes/facilities 没 ownership 字段。检索范围：实例 nodes、facilities、station assignments、enterprise assignment 和 loader。需要用户语义键或新权威数据。
3. `HALT_NO_BRICK`：现有 EDF＋completion 若不能在冻结 cap 下满服务，没有获批的替代装箱／搜索积木；停，不造。
4. `HALT_USER_KEY_K7_PRIVATE_INIT_PROVENANCE`：`build_edf_route_plans`、`minimum_edf_order_chains` 与 `complete_china81_route_skeleton` 都拥有贪心装箱／递归链覆盖／EV variant 枚举及有限车队分配行为，当前只有项目提交，未核到人类开源出处。已检索本仓 ORIGIN/PROVENANCE、Git history、`setp_instance_lab`、China81 generator。K7 两个真实选项只有：
   - A，接受既有项目初始化算法并披露：对 F1 封存见证的前两件离线血统与 F2 拟用三件一致生效，C.8 可继续；
   - B，停用并找替代：F1 封存见证与 F2 enterprise seed 都须重建；F5 不受影响。

   K7 未决时 C.8、F1 private 初始化身份冻结与 seed 探针均停止，不以“已有代码”为由绕过 P101。
5. `formal_search_allowed=False` 是 W2.2/S5/W3 的正式化问题；W1.3a 不得偷翻。

#### E. 验收

1. 第一轮结构复现 E6（W1.3 已拆成四件）：

   ```bash
   rg -n '^### 工作项 W1\.3[abcd]' \
     docs/handoff/reform_council_20260818/execution_blueprint_20260818.md
   ```

2. 第一轮事实复现 E7（原样复现 joint witness 的 24 个 customer/depot 错配）：

   ```bash
   python3 -c 'import csv; from pathlib import Path; instance="cn-jjj-50c-01-DEPOTSEARCH-d996f755bd"; root=Path("data/ChinaInstances/china81_final_suite_v2_20260815/instances")/instance; assignment={r["customer_id"]:"D_OSM_WAY_"+r["enterprise_depot_osm"].split("/",1)[1] for r in csv.DictReader((root/"enterprise_assignment.csv").open()) if r["instance_id"]==instance}; witness=[r for r in csv.DictReader(Path("solver/reports/instance_build_only_d996f755bd_20260815/health_witness_routes.csv").open()) if r["instance_id"]==instance]; mismatches=[(r["route_vehicle_id"],r["depot_id"],c,assignment[c]) for r in witness for c in r["customers"].split("|") if c and r["depot_id"]!=assignment[c]]; print("mismatch_count=",len(mismatches),sep=""); print("first=","|".join(mismatches[0]),sep=""); assert len(mismatches)==24; assert mismatches[0]==("CV_D_OSM_WAY_1003511503_001#T1","D_OSM_WAY_1003511503","C035","D_OSM_WAY_1071205721")'
   ```

   当前已由双方独立复现的输出为 `mismatch_count=24`，首例为 `CV_D_OSM_WAY_1003511503_001#T1|D_OSM_WAY_1003511503|C035|D_OSM_WAY_1071205721`。

3. assignment 真值：

   ```bash
   PYTHONPATH=solver/src python3 - <<'PY'
   from pathlib import Path
   from setp_solver.enterprise_assignment import load_enterprise_assignment
   root = Path("data/ChinaInstances/china81_final_suite_v2_20260815/instances/cn-jjj-50c-01-DEPOTSEARCH-d996f755bd")
   a = load_enterprise_assignment(
       root / "enterprise_assignment.csv",
       root / "nodes.csv",
       expected_instance_id="cn-jjj-50c-01-DEPOTSEARCH-d996f755bd",
       expected_customer_ids=[f"C{i:03d}" for i in range(1, 51)],
   )
   assert len(a.enterprise_by_customer) == 50
   assert sum(v == "ENT_A" for v in a.enterprise_by_customer.values()) == 25
   assert sum(v == "ENT_B" for v in a.enterprise_by_customer.values()) == 25
   PY
   ```

   预期无输出、exit 0。

4. 单元与集成测试：

   ```bash
   PYTHONPATH=solver/src:models/src:third_party/setp_hgs_kernel \
     build/python_envs/setp-independent-hgs/bin/python -m pytest -q \
     solver/tests/test_enterprise_problem_adapter.py
   ```

   必须逐企业断言：客户 exact cover、另一 depot 不存在、公共 f 集合与 joint 相同、矩阵三种 profile 维度匹配、`ENT_A` 的 `slice.bundle.instance.num_cv/num_ev == (3,3)`、`ENT_B == (7,7)`，且两者都与子 bundle 唯一 `fleet_caps_by_depot` 行逐字段相等；`charger_scenario_by_node.keys()` exact 等于 sliced instance 的全部 `d/f` node ids，本企业 depot 保留真实功率，每个 retained `f` row 与 joint bundle 对应 row 逐位相同；再断言 shift/volume key exact cover、子 contract 的 `vehicle_volume_capacity_m3` 与 joint contract 逐位相同、`seed_input` 六个 order 字段逐客户等于 slice Node/contract、原 bundle 未变。D.4 解除后的 seed probe 还断言 `reason == ""`、`completed.solution` 满服务且可行，并验证 `.solution` 而非 result carrier 被传给 `DutyIndividual.from_solution`。
   runner 接线测试另断言 `evaluator.context.bundle is enterprise_slice.bundle`、`seed_input.instance is enterprise_slice.bundle.instance`，`bundle depots == independent_profit.keys() == prior_profit.keys() == pi0.keys()`，且 metadata 中的 Pi0 map/hash 等于 `context.independent_profit_identity`，不是 loader 原先的 joint neutral map。

5. seed 施工探针属于求解器施工轮，不能在本蓝图轮运行，且仅在 K7 解除后执行。未来命令：

   ```bash
   for enterprise in ENT_A ENT_B; do
     PYTHONPATH=solver/src:models/src:third_party/setp_hgs_kernel \
       build/python_envs/setp-independent-hgs/bin/python solver/scripts/run_problem_hgs_private_technical.py \
       "solver/reports/enterprise_seed_probe/${enterprise}" \
       --instance-id cn-jjj-50c-01-DEPOTSEARCH-d996f755bd \
       --enterprise-id "${enterprise}" \
       --seed 1 --iterations 1 --stagnation-patience 1 \
       --max-runtime-seconds 60
   done
   ```

   shell 实际变量应为 `$enterprise`；上面路径的花括号仅用于文档可见性。预期每包 25/25 客户、6597/6597 或 6667/6667 kg、0 hard violations；任何失败触发 D.3，不调参数救。

#### F. 净行数预算

- `instance_subset.py` 原样搬出：约 `+65/−63`。
- `enterprise_adapter.py`：约 `+180/−0`。
- runner/seed 接线：D.4 解除后约 `+85/−20`；停点解除前实际 `+0/−0`。
- 本项生产合计：约 `+330/−83`；测试约 `+100/−0`。

---

### 工作项 W1.3b　企业账与单干成本

#### A. 现状取证

1. `solver/src/setp_solver/profit.py:29-50 DepotProfitBreakdown` 已含八个成本分项以及 `cost_total, profit, customers_served, demand_kg, emissions_kg`。
2. :68-78 真实签名：

   `calculate_depot_profits(solution, instance, carbon_profile, prices=..., *, customer_home_depot=None, prior_profit=None, carbon_quota_kg=0, revenue_per_kg=None) -> dict[str, DepotProfitBreakdown]`。

3. :79-85 的语义是：成本归车辆 home depot、收入归 serving depot、跨企业时另记 transshipment；:234-266 最终 `profit = prior + revenue - cost_total`。
4. Problem-HGS evaluator 已在 `algorithms/problem_hgs/evaluation.py:670-679` 调该函数，但 `FullEvaluation.depot_profit`（:252-263）只保存每 depot 的 profit float，丢掉成本分项。
5. private runner :4030-4068 的 `raw_runs.csv` 只有 `best_cost`；:4088-4102 的 `best_solution.json.evaluation.total_cost` 只有总成本，没有企业账。

#### B. 积木清单

| 积木 | 版本／路径 | 签名 | 许可证／身份 | 人类作品证据 |
|---|---|---|---|---|
| depot profit ledger | 当前 HEAD / `profit.py` | `calculate_depot_profits(...)` | PROJECT_DOMAIN（existing） | 已有 `solver/tests/test_profit.py` |
| dataclass serializer | Python ≥3.10 | `dataclasses.asdict` | PSF | Python 官方 |
| canonical JSON/hash | Python ≥3.10 | `json.dumps(sort_keys=True)`、SHA-256 | PSF | Python 官方 |

#### C. 拼装步骤

1. 在 private runner 最终 best 已确定、写 :4030-4102 产物之前，再逐项复用 evaluator `algorithms/problem_hgs/evaluation.py:670-678` 的真实调用：`calculate_depot_profits(result.best_evaluation.prepared_solution, bundle.instance, bundle.time_profile, bundle.prices, customer_home_depot=dict(bundle.customer_home_depot), prior_profit=dict(evaluator.context.prior_profit), carbon_quota_kg=float(evaluator.context.carbon_quota_kg))`；`China81Bundle` 没有 `carbon_profile` 字段，且不得漏掉 prior profit／carbon quota 另造第二套账。
2. 新增包文件 `enterprise_ledger.json`，schema 固定：

   ```json
   {
     "schema": "resetp.enterprise_ledger.v1",
     "instance_id": "...",
     "seed": 1,
     "solution_sha256": "...",
     "rows": {
       "D_OSM_WAY_...": { "cost_total": 0.0, "profit": 0.0 }
     }
   }
   ```

   `rows` 的真实内容为每个 `DepotProfitBreakdown` 的完整 `asdict`，示意中的两个字段不是裁剪清单。`solution_sha256` 的唯一含义固定为 `result.best.fingerprint`（`algorithms/problem_hgs/model.py:468-490` 对 duty、charging schedule 与 unserved customers 的 canonical SHA-256），必须是 64 位小写十六进制；它不是 `best_solution.json` 文件字节 hash，后者只由 `artifact_hashes.json` 记录。`best_solution.json`、metadata 与 enterprise ledger 均写同一 fingerprint，禁止在三种解身份之间自行选择。
3. 把 `enterprise_ledger.json` 加入现有 `artifact_hashes.json`；metadata 记录 ledger schema、ledger 文件 hash 与 `individual_fingerprint=result.best.fingerprint`，不复制账本数值。在 `private runner:4088-4106` 写 `best_solution.json` 时同样新增顶层 `individual_fingerprint=result.best.fingerprint`；`dataclasses.asdict(result.best)` 不会自动包含 cached property，不能把该字段留给序列化器猜。
4. standalone 每个 seed 的 Pi0 候选取该唯一 depot row 的 `profit`；单干成本 `c(A)/c(B)` 取**同一条获选 standalone 运行**的 `cost_total`，不得从另一个较低成本 seed 拼接。
5. 按现行 P28，分别在 10 个完整服务、可行的 standalone seed 中以最高 profit 选 Pi0。选择表必须保留全部 10 行及 `selected` 布尔；若有 seed 不满服务或不完整，不删除行，标失败并使正式批次停。
6. joint 的 `c(AB)` 取同一 best solution 的 `best_solution.json.evaluation.total_cost`，并断言等于 joint ledger 两个 depot 的 `cost_total` 之和（允许既有数值容差，禁止另设科学阈值）。

#### D. 缺口如实

- 若 ledger 两行成本和与 evaluator total 不闭合，说明现有记账语义或字段覆盖有缺口；`HALT_ACCOUNTING_MISMATCH`，不得用 residual 分摊补平。
- 若 standalone profit 非正，现有 participation context 的正数 Pi0 合同无法表达；`HALT_NO_BRICK`，不平移、不取绝对值。
- 单干“最高 profit”与“最低 cost”不是同一选择目标；按同一获选行取两者，防止事后拼出虚假 coalition table。

#### E. 验收

```bash
PYTHONPATH=solver/src:models/src:third_party/setp_hgs_kernel \
  build/python_envs/setp-independent-hgs/bin/python -m pytest -q \
  solver/tests/test_enterprise_accounting.py \
  solver/tests/test_profit.py
```

预期：

- standalone ledger 只有一个 depot row，customers=25，demand 分别 6597/6667 kg；
- joint ledger exact 两行，客户与需求总量为 50 和 13264 kg；
- `sum(row.cost_total) == evaluation.total_cost`；
- `enterprise_ledger.solution_sha256 == best_solution.individual_fingerprint == result.best.fingerprint`，且包内 `artifact_hashes.json` 另核文件字节；
- ledger hash 随 best solution 变化且包内引用逐位一致；
- 所有失败行仍写入 raw/decision，不被 selection 丢弃。

#### F. 净行数预算

- 生产：约 `+60/−0`。
- 测试：约 `+50/−0`。

---

### 工作项 W1.3c　pyCoopGame 两企业 Shapley 成本分摊

#### A. 现状取证

1. 冻结快照位于 `third_party/harvested_materials/07_collaboration_profit/pycoopgame/`。`ORIGIN.md:3-8` 记录 GitHub `flechtenberg/pyCoopGame`、commit `72153c7771bc6d910be023e5d72c8922cecaa80f`、BSD-3-Clause、定向原样快照，仅供分摊核算。
2. `upstream/setup.py:7-22`：版本 0.0.5，作者 Fabian Lechtenberg，声明 Python 3.9–3.12，无 install dependencies。仓内已有 `/opt/homebrew/bin/python3.12 3.12.13`，但该解释器尚无 pandas。
3. `upstream/pyCoopGame/Shapley.py:3 dif_gain(name, n, game)`；:30 `Shapley(game)`。输入是 pandas-like 两列 table：
   - `coalition`：每格为 player iterable；
   - `value`：该 coalition 的数值；
   返回 `dict[player, value]`。
4. `upstream/pyCoopGame/__init__.py:1-6` 导入快照未包含的 `Core/CostGap/Create_game/Validate_game`；普通 `import pyCoopGame` 会 ImportError。不得补 third_party 缺文件。
5. README :175-177 指向 Lechtenberg et al., `Applied Energy 377 (2025) 124581`，是该人类作品的论文出处。
6. `Nucleolus.py:58 nucleolus(game, delta=.5, GAMS=False, tk=False)` 依 Pyomo 和外部 GLPK/GAMS（:49-55）；快照 setup 没声明它们，当前工作项也没有获批的 LP solver 依赖链。

#### B. 积木清单

| 积木 | 版本／commit | 接口 | 许可证 | 路径／URL | 人类作品证据 |
|---|---|---|---|---|---|
| pyCoopGame Shapley | 0.0.5 / `72153c...` | `Shapley(game) -> dict` | BSD-3-Clause | 仓内快照；https://github.com/flechtenberg/pyCoopGame | Fabian Lechtenberg；Applied Energy 377 (2025) 124581 |
| pandas | 3.0.3 | `pandas.DataFrame(data)` | BSD-3-Clause | https://pypi.org/project/pandas/3.0.3/ | pandas 开发团队与公开 release |
| pytest | 9.1.1 | `python -m pytest` | MIT | https://pypi.org/project/pytest/9.1.1/ | pytest-dev 人类维护项目；仅用于该隔离 adapter 的验收 |
| importlib | Python 3.12.13 | `spec_from_file_location/module_from_spec/exec_module` | PSF | stdlib | Python 官方 |

#### C. 拼装步骤

1. 在施工环境新增独立 `.coop-venv`，必须用 `/opt/homebrew/bin/python3.12` 创建；只安装锁定 `pandas==3.0.3`、`pytest==9.1.1` 及其传递依赖。它是零搜索后处理／验收环境，不与 solver venv 混装；pytest 不能假定由 pandas 带入。
2. 新增 `solver/scripts/coalition_accounting_adapter.py`（身份＝PROJECT_ADAPTER，≤250 行），定义三个 frozen dataclass。固定放在零搜索 scripts 层，避免 `.coop-venv` 导入 `setp_solver.algorithms.problem_hgs.__init__` 后连带要求 `setp_hgs_kernel`：
   - `TwoEnterpriseCoalitionCosts(enterprise_a: str, enterprise_b: str, standalone_cost_a: float, standalone_cost_b: float, joint_cost: float)`；
   - `TwoEnterpriseParticipationInputs(joint_revenue: Mapping[str,float], joint_cost_total: Mapping[str,float], joint_profit: Mapping[str,float], pi0_profit: Mapping[str,float])`；
   - `TwoEnterpriseShapleyAllocation(allocated_cost: Mapping[str,float], saving_cny: Mapping[str,float], saving_pct: Mapping[str,float], allocated_total: float, joint_prior_profit: Mapping[str,float], allocated_profit: Mapping[str,float], operational_participation_margin: Mapping[str,float], allocated_participation_margin: Mapping[str,float], source_commit: str)`。
3. 适配函数固定为：

   `allocate_two_enterprise_costs(costs: TwoEnterpriseCoalitionCosts, participation: TwoEnterpriseParticipationInputs, *, repo_root: Path) -> TwoEnterpriseShapleyAllocation`。

   它只验证两个 standalone cost 有限且严格 `>0`、joint cost 有限且 `>=0`、企业名不同，然后拼 DataFrame 和调用上游；standalone 严格正值使 `saving_pct` 的分母有定义。不得内写 Shapley 公式。
4. 绕开损坏的 `__init__.py`，直接加载具体文件：

   ```python
   module_path = repo_root / (
       "third_party/harvested_materials/07_collaboration_profit/"
       "pycoopgame/upstream/pyCoopGame/Shapley.py"
   )
   spec = importlib.util.spec_from_file_location(
       "resetp_pycoopgame_shapley", module_path
   )
   module = importlib.util.module_from_spec(spec)
   assert spec.loader is not None
   spec.loader.exec_module(module)
   shares = module.Shapley(game_df)
   ```

   这是标准 importlib API；不改 snapshot。
5. coalition-value table 固定完整四行，顺序和字段映射写死：

   | coalition | value |
   |---|---:|
   | `[]` | `0.0` |
   | `["ENT_A"]` | W1.3b 选中 ENT_A standalone ledger 的 `cost_total` |
   | `["ENT_B"]` | W1.3b 选中 ENT_B standalone ledger 的 `cost_total` |
   | `["ENT_A","ENT_B"]` | joint best solution 的 `evaluation.total_cost`，且已通过 ledger 和断言 |

6. 上游返回值解释为 allocated cost；只做字段换算：
   - `saving_i = standalone_cost_i - allocated_cost_i`；
   - `saving_pct_i = 100 * saving_i / standalone_cost_i`；
   - `profit.py:234-266` 固定 `profit=prior_profit+revenue-cost_total`，而 `DepotProfitBreakdown` 未单列 prior，因此逐企业还原 `joint_prior_profit_i = joint_profit_i - joint_revenue_i + joint_cost_total_i`；
   - `allocated_profit_i = pi0_profit_i + (standalone_cost_i - allocated_cost_i)`；这里的 Shapley 成本节约是期末转移支付后的合作增益，必须加回各企业单干利润，不能拿联合运营收入按分摊成本重做一遍利润；
   - `operational_participation_margin_i = joint_profit_i - pi0_profit_i`；
   - `allocated_participation_margin_i = allocated_profit_i - pi0_profit_i`；
   - 断言 allocated total 与 joint cost 闭合，并断言用还原 prior 重建的 operational profit 与 ledger `profit` 均在现有浮点容差内闭合。
7. 结果写入 F2 汇总目录的 `shapley_allocation.json`，同时保存四行原始 coalition table、两套参与裕量、snapshot commit、snapshot file SHA、pandas/Python 版本和输入三份 ledger/solution hash；不把打印出来的一句话当证据。

#### D. 缺口如实

- `HALT_NO_BRICK`：snapshot 的 nucleolus 依赖未锁定的 Pyomo＋GLPK/GAMS，且当前工作项只要求两企业标准 Shapley 核算。不得安装任意 solver 或自己写两方 nucleolus。若论文必须报 nucleolus，另做依赖与许可证取证后交用户。
- pyCoopGame setup 未声明 pandas，故 pandas 必须作为独立显式积木锁定，不能依赖“碰巧已安装”的系统 3.0.3。
- 若 joint cost 大于 standalone 两者之和，Shapley 仍会给成本份额，但“合作节约”为负；如实输出，不换分摊法救故事。
- `HALT_USER_KEY_K6_PARTICIPATION_LEDGER`：论文的“参与约束成立”必须在 F2 joint 正式批次前由用户二选一：
  - A，现有 route-home-depot 运营账：现成 checker/HGS 罚值确实施加它，F2 可按现路径施工，Shapley allocated margin 另报但不称为搜索约束；
  - B，Shapley allocated profit：当前 pyCoopGame 只是 post-hoc 核算，既不进 evaluator 也不进 population 可行性，立即 `HALT_NO_BRICK_ALLOCATED_PARTICIPATION_SEARCH`。必须先找到能把该人类 Shapley API 接成 evaluator constraint 的标准砖，并获用户对模型语义／受保护 checker 的单独批准；不得在 10 个 seed 跑完后用 post-hoc margin 挑有利 seed 冒充“约束已施加”。

#### E. 验收

1. 第一轮事实复现 E8（pyCoopGame 根导入缺模块；Nucleolus 依赖 Pyomo／GLPK／GAMS）：

   ```bash
   nl -ba third_party/harvested_materials/07_collaboration_profit/pycoopgame/upstream/pyCoopGame/__init__.py
   nl -ba third_party/harvested_materials/07_collaboration_profit/pycoopgame/upstream/pyCoopGame/Nucleolus.py | sed -n '1,60p'
   rg -n 'def Shapley' \
     third_party/harvested_materials/07_collaboration_profit/pycoopgame/upstream/pyCoopGame/Shapley.py
   ```

2. 固定算例：

   ```bash
   PYTHONPATH=solver/scripts .coop-venv/bin/python -m pytest -q \
     solver/tests/test_coalition_accounting.py
   ```

   对 `cA=100,cB=120,cAB=180`，预期 A allocated=80、B allocated=100、sum=180；另给 joint ledger 的 `revenue/cost_total/profit` 与 Pi0，逐企业断言 prior、allocated profit 和两套 margin 算术正确；还要覆盖企业顺序交换、非法缺 coalition、非有限数。

3. snapshot 不变：

   ```bash
   git diff --exit-code -- \
     third_party/harvested_materials/07_collaboration_profit/pycoopgame
   shasum -a 256 \
     third_party/harvested_materials/07_collaboration_profit/pycoopgame/upstream/pyCoopGame/Shapley.py
   ```

   第一条预期 exit 0；第二条摘要写入正式 allocation provenance。

4. 真实 F2 后处理只读三个已完成输入包；任一 hash、服务量、ledger 闭合或状态不合格即 exit 非 0，不创建成功 verdict。

#### F. 净行数预算

- 生产 adapter：约 `+90/−0`。
- 测试：约 `+40/−0`。
- third_party：`+0/−0`。

---

### 工作项 W1.3d　Pi0 参与约束接线与旧 ALNS 公平入口退役

#### A. 现状取证

1. 唯一现成 Pi0 parser 在 `solver/scripts/run_mixed_fleet_experiment.py:287-315 _load_pi0_manifest(path)`。schema：
   - 顶层 `schema="resetp.formal_pi0.v1"`、`instances`；
   - 每实例 `values:{depot_id: positive float}`、非空 `source_id`、可选 `value_sha256`；
   - hash 是 sorted `[[key,float.hex()],...]`；
   - :331-344 验证请求 instance 和 depot key exact cover。
2. 同 runner :626-671 `_arm_setup(...)` 把 values 写入 `DutyEvaluationContext.independent_profit`，创建 `FrozenMappingIdentity(source_id,value_sha256,externally_frozen=True)`，并设 `theta=1.0`、`fairness_enabled=True`。
3. 参与约束消费链：
   - `algorithms/problem_hgs/evaluation.py:163-220 DutyEvaluationContext` 验 exact depot cover、正数、hash 和正式运行时 externally frozen；
   - :652-791 `DutyFullEvaluator._evaluate_prepared` 调企业账→`FairnessContext`→`check_solution`→participation margins；
   - `check.py:98-106,188` 传开关，:1225-1266 `_check_profit_fairness` 检查 `Pi_d >= theta * Pi0_d`；
   - `runner.py:206-220,345-366` 写 source/hash/frozen/fairness provenance。
4. private runner :1409-1427 仍造 `1.0` 假 Pi0 且 fairness off；:3988-3993、:4066 硬编码 false。
5. `search/fairness.py` 中应退役的行为入口：
   - :29 `run_independent_profit_baselines`，:64-73 调 `run_alns_wouda`；
   - :133 `build_concatenated_independent_seed`；
   - :225 `run_equal_budget_fairness_comparison`，:261-288 两次 ALNS；
   - :317 `_subinstance_for_depot`（有损）；
   - :332 `_write_subbundle`。
6. 活跃生产 import/call：
   - `search/formal_runner.py:50`；调用 :580/:590、:1222/:1231、:1280/:1289、:1317/:1327，所属函数 `run_e6_fairness_scan:563`、`_run_e3_independent_variant:1209`、`_build_e3_concatenated_seed:1266`、`_run_e3_fairness_variant:1304`；
   - 同文件 `run_e3_ablation:449-505` → `_run_e3_variant:1152-1206` → 上述三个 E3 helper；CLI choices :703 及 dispatcher :748-749 仍公开 E3。`run_e6_fairness_scan` 的 CLI dispatcher 在 :763-764；
   - `search/__init__.py:29,71-74` lazy export；
   - `solver/tests/test_profit.py:19,462`；`solver/tests/test_formal_runner.py:27-28,631-693` 仍 import／patch E3 runner helpers。
7. 历史／baseline import（只登记，不改旧产物）：`solver/reports/formal/run_w2_parallel_chain.py:30,93,250`；`baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/run_stage1_algorithm_closeout.py:53-54,536` 及同目录 `test_fairness_deficit_decoder.py:19,36`；`baselines/e6_fairness/e6_participation_formal_20260714.py:51`；`baselines/e3_ablation/` 下 `e3_common_fleet_envelope_design_20260713.py:34`、`e3_same_start_wiring_probe_20260713.py:39`、`e3_mismatch_fair_probe_20260713.py:27`、`e3_mismatch_probe_20260713.py:30`、`e3_v3_runner.py:45`、`m1_e3_cumulative_ablation_runner.py:31`。

#### B. 积木清单

| 积木 | 版本／路径 | 接口 | 许可证／身份 | 人类作品证据 |
|---|---|---|---|---|
| 现有 Pi0 parser | 当前 HEAD / mixed runner :287-315 | `_load_pi0_manifest(path) -> dict` | PROJECT_DOMAIN（existing） | 已在 mixed-fleet 正式结构使用 |
| frozen identity | 当前 HEAD | `FrozenMappingIdentity`、`mapping_sha256` | PROJECT_DOMAIN（existing） | evaluator 已 fail-closed |
| fairness checker | 当前 HEAD | `_check_profit_fairness` | PROJECT_DOMAIN（existing；受保护） | 已有测试；本项不改 checker |
| argparse | Python ≥3.10 | `add_mutually_exclusive_group` | PSF | Python 官方 |

#### C. 拼装步骤

1. 先把 `algorithms/problem_hgs/evaluation.py:288-298 mapping_sha256(values)` 函数体逐字搬到新增 `solver/src/setp_solver/mapping_identity.py`（`declared_identity=PROJECT_DOMAIN`，`code_role=PURE_FUNCTION`）；`evaluation.py` 改为从 `setp_solver.mapping_identity` import/re-export，原函数体删除，`problem_hgs.__init__` 的旧公开 import 保持兼容。再把 `run_mixed_fleet_experiment.py:287-315 _load_pi0_manifest` 原样搬到新增 `solver/src/setp_solver/pi0_manifest.py`（`declared_identity=PROJECT_ADAPTER`，`code_role=THIN_ADAPTER`，≤250 行），公开名 `load_pi0_manifest(path: Path) -> dict[...]`；它与 `build_f2_inputs.py` 都直接从中性模块 import 同一 `mapping_sha256`，不经 `algorithms.problem_hgs.__init__`、不留第二份公式。
2. mixed runner 删除本地 parser，改 import 公共函数；其现有 schema、错误字样和输出保持。
3. W1.3b 的 20 个 standalone 包全部合格后，只调 W3.2 已在 S5a 前冻结的 `build_f2_inputs.py select`，生成唯一文件 `solver/reports/f2_${CAMPAIGN_ID}/inputs/pi0_manifest.json`。不再并列第二个 `formal_pi0.json` 真值源；其 schema 与 W3.2 C.4 逐字段相同：

   ```json
   {
     "schema": "resetp.formal_pi0.v1",
     "instances": {
       "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd": {
         "values": {
           "D_OSM_WAY_1003511503": 0.0,
           "D_OSM_WAY_1071205721": 0.0
         },
         "source_id": "f2_${campaign.campaign_id}_standalone_10seed_selection",
         "value_sha256": "...",
         "selected_package_sha256_by_enterprise": {
           "ENT_A": "<64-hex selected package SHA-256>",
           "ENT_B": "<64-hex selected package SHA-256>"
         }
       }
     }
   }
   ```

   两个 `0.0` 只是 schema 占位示意；正式文件必须从获选 ledger 的 `profit` 填，且 parser 要求正数。`${campaign.campaign_id}` 由 `build_f2_inputs.py` 从已验证 manifest dataclass 格式化，不是 shell 字面量；两份获选包身份只放在 `selected_package_sha256_by_enterprise`，键必须 exact 为 `ENT_A/ENT_B`、值必须各为 64 位 SHA-256。公共 parser 对旧 v1 文件保持兼容：该字段存在时即验证并原样保留；private formal F2 必须要求它存在，不能把包 hash 再塞进 `source_id`。
4. 在 private runner parser :2824-3015 新增 `--pi0-manifest Path`，与 `--enterprise-id` 互斥；只有 joint 运行传入。
5. 在完整 joint bundle/context 建好后：
   - 保持搬出函数真实返回形状：`entry = load_pi0_manifest(path)[args.instance_id]`；原 parser 已返回解析后的 instances 映射，不能再索引一次 `"instances"`；
   - 验 `values.keys()` exact 等于两个 joint depot ids；
   - 先把局部真值载体写成 `pi0 = {str(k): float(v) for k, v in entry["values"].items()}`，再用该 runner 已导入的 `replace(...)` 一次写入 `context = replace(context, independent_profit=pi0, independent_profit_identity=FrozenMappingIdentity(source_id=entry["source_id"], value_sha256=entry["value_sha256"], externally_frozen=True), theta=1.0, fairness_enabled=True)`。`pi0`、context mapping 与 identity 必须基于同一份内容；
   - :3988-3993、:4066 等输出改读最终 context，不再硬编码 false；`metadata.json` 与每个 `raw_runs.csv` row 都显式新增 `fairness_enabled`、`fairness_theta`、`pi0_source_id`、`pi0_sha256`，不得要求聚合器从 report 文本猜。
6. 保留 `check.py` 现有参与约束，不在本项修改冻结文件。W1.4 magnitude 未获批时，违反仍可用既有 detail/类型判失败。
7. 退役旧 ALNS 公平入口：
   - 从 `search/__init__.py:29,71-74` 删除 `run_independent_profit_baselines` export；
   - 从 `search/formal_runner.py:50` 删除四个 fairness import；
   - 整条旧 E3/E6 ALNS 入口从根删除：`run_e3_ablation:449-505`、`run_e6_fairness_scan:563-604`、`_e3_variant_specs:839`、`_write_e3_derived_bundle:934`、`_run_e3_variant:1152-1206`、`_run_e3_independent_variant:1209`、`_build_e3_concatenated_seed:1266`、`_run_e3_fairness_variant:1304`、`_retained_e3_m0_rows:1929`、`_e3_table_rows:1955`、`_e3_note_rows:1995`、`_e6_table_rows:2115`、`_e6_figure_rows:2143`、`_prices_with_theta:2190`、`_min_ratio:2196`；从 parser choices :703 删除 `E3/E6`，同时删除只服务二者的 `--variants/--thetas` :709/:712 及解析变量 :717/:720，删除 dispatcher :748-749/:763-764。不得只删叶函数留下 NameError；
   - `test_formal_runner.py:27-28,631-693` 删除对已退役 `_e3_*` API 的 import/patch/runner 断言；:545-606 对共享碳核的纯函数测试保留，因为它们不调用 ALNS 公平入口。`test_profit.py` 的旧 fairness runner 测试迁到新 enterprise accounting/Pi0 测试；
   - 若 formal runner 其他路径仍需要 `infer_customer_home_depots`，直接从 `profit.py:23` 导入，不能借 fairness 转出；
   - `search/fairness.py` 保留为 legacy source snapshot，模块头列出 A.5 五个 retired 函数和替代入口＝W1.3a/b/d HGS 路径；不再由生产 package export；
   - `test_profit.py` 中依赖旧 runner 的测试迁到新 enterprise accounting/Pi0 测试；历史 reports/baselines 不改。

#### D. 缺口如实

- `HALT_PI0_NONPOSITIVE`：任一 standalone 最佳 profit ≤0 时，现有 positive Pi0 ratio 合同不能直接用；不平移、不加 epsilon。
- `HALT_FORMAL_AUTHORITY`：DEPOTSEARCH bundle 仍 `formal_search_allowed=False`。打开 fairness 不等于正式放行；必须等 W2.2/S5 的用户冻结。
- 历史 baseline 文件继续可读不等于允许复跑。新 F2 的 private Problem-HGS 路径、编排脚本和 provenance 中不得出现 `run_alns_wouda`；`formal_runner.py` 内与本项无关的 carbon-quota／旧 baseline ALNS 路径不在本轮删除范围。

#### E. 验收

1. parser/context：

   ```bash
   PYTHONPATH=solver/src:models/src:third_party/setp_hgs_kernel \
     build/python_envs/setp-independent-hgs/bin/python -m pytest -q \
     solver/tests/test_pi0_manifest.py \
     solver/tests/test_enterprise_participation_wiring.py
   ```

   覆盖 schema 错、hash 错、depot 缺／多、非正值、standalone 与 joint 互斥、fairness 真开、Pi0 source/hash 进入 provenance。另断言 `set(context.bundle depots) == set(pi0) == set(context.independent_profit) == set(context.prior_profit)`，`metadata.pi0_sha256 == context.independent_profit_identity.value_sha256 == mapping_sha256(pi0)`；错 key/hash 在 evaluator/search 前拒绝。

2. 退役 import：

   ```bash
   ! rg -n 'from .*search\.fairness|from \.fairness|run_alns_wouda' \
     solver/src/setp_solver/algorithms/problem_hgs \
     solver/scripts/run_problem_hgs_private_technical.py \
     solver/scripts/build_f2_inputs.py \
     solver/src/setp_solver/search/__init__.py
   ```

   预期 0 命中。不得对整个 `solver/src/setp_solver` 宣称 `run_alns_wouda` 为 0：`formal_runner.py:34,192,974` 的其他旧 baseline／carbon-quota 路径仍合法保留。

   另执行 `! rg -n 'from \.fairness|run_e3_ablation|run_e6_fairness_scan|_run_e3_variant|_build_e3_concatenated_seed' solver/src/setp_solver/search/formal_runner.py solver/tests/test_formal_runner.py`，预期 0 命中；parser choices 也无 `E3/E6`。保留的顶层 `from .alns_wouda import ...` 不属于这个断言。

3. W0.1 Import Linter 的 retired-ALNS contract 必须 kept。

4. joint 一评估的 fail-closed 测试：一方 profit 比 Pi0 少 1 个可精确表示的货币单位时产生 `PROFIT_FAIRNESS`；等于 Pi0 时不产生该 violation。该测试只验证现有 checker，不改阈值。

#### F. 净行数预算

- Pi0 parser 公共化与两 runner 接线：约 `+95/−29`。
- 删除生产 ALNS 公平 dispatcher／函数族：预计 `+8/−180 至 −230`，施工时以函数边界实数为准，不为贴预算留死码。
- 测试迁移／新增：约 `+60/−20`。

---

### 工作项 W1.4　Violation 结构化量化（规格先行）

#### A. 现状取证

1. 冻结文件 `solver/src/setp_solver/check.py:45-52`：

   `@dataclass(frozen=True) class Violation: type: str; vehicle_id: str; location: str; detail: str; severity: str = "hard"`。

2. 用户给的 1034/1202 行对应**非保护清单中的** `solver/src/setp_solver/algorithms/problem_hgs/evaluation.py`；受保护的是另一文件 `solver/src/setp_solver/search/evaluation.py`，本项不需要改后者。
3. `algorithms/problem_hgs/evaluation.py:252-260 FullEvaluation.violation_magnitudes: tuple[float,...]` 已存在“按 violation type 使用原生单位的 scalar”合同。
4. :1034-1091 `_measure_violations(...)` 当前逐类：
   - 默认 magnitude=1；
   - CAPACITY :1049-1066 先正则 volume，失败后按 route payload 重算；
   - PROFIT_FAIRNESS :1067-1073 从 participation margin；
   - TIME_WINDOW :1074-1077 从 detail 正则；
   - BATTERY :1078-1081 从 detail 正则；
   - FLEET_SIZE :1082-1085 从 detail 前两个整数；
   - CHARGING_ENERGY/WINDOW_GAP :1086-1089 从 structured `ChargingGap`。
5. 正则 helpers：:1225-1232 `_volume_capacity_magnitude`；:1235 `_NUMBER`；:1238-1242 `_time_window_magnitude`；:1245-1269 `_battery_magnitude`；:1272-1276 `_fleet_magnitude`。:1488-1502 `_violation_keys` 只含五个旧字段。
6. 已掌握差值的 producer：
   - check.py FLEET_SIZE :562-579；CAPACITY :709-730、:747-776；TIME_WINDOW :798-806；BATTERY :1037-1044、:1061-1068、:1081-1082、:1099-1100、:1167-1203；FAIRNESS :1243-1264；
   - Problem-HGS rebuilt route：`evaluation.py:1171-1183` volume、:1202-1210 early、:1212-1220 late；charging gaps :744-763；
   - China81 fleet：`china81_completion.py:262-305`。

#### B. 积木清单

| 积木 | 版本／路径 | 接口 | 许可证／身份 | 用途 |
|---|---|---|---|---|
| Python frozen dataclass | ≥3.10 | 默认字段追加 | PSF | 保持旧位置参数兼容 |
| 现有 Violation | 当前 HEAD / `check.py` | `Violation(...)` | PROJECT_DOMAIN（existing；受保护） | 唯一 violation carrier |
| 现有 ChargingGap | 当前 HEAD / problem_hgs evaluation | `missing_energy_kwh/window_shortage_seconds` | PROJECT_DOMAIN（existing） | 已结构化的两个量 |

这是给现有项目真值 dataclass 加字段，不是新算法；不需要外部搜索组件。

#### C. 拼装步骤

1. **先等 K2-VIOLATION 用户单独批准，并记录三份保护文件施工前 SHA。** 未批准时本节其余步骤不执行。
2. 在 `check.py:45-52 Violation` 的 `severity` 后追加唯一字段：

   在 `detail` 后先插入 `_: KW_ONLY`，再保留 `severity: str = "hard"`，最后追加 `magnitude: float | None = None`；把 import 改为 `from dataclasses import KW_ONLY, dataclass`。真实签名必须是 `Violation(type, vehicle_id, location, detail, *, severity="hard", magnitude=None)`。本轮只读 AST 已确认 `solver/**/*.py` 没有 ≥5 个位置实参的 `Violation(...)`，因此用 stdlib keyword-only 屏障消除“数值静默占 severity”的歧义，不写自制检查器。

   不新增 unit enum；现有 `type` 已决定 native unit。`None` 表示 producer 没有精确连续量，显式 0.0 不得当 None。
3. 在 A.6 各 producer 只对**单一 predicate、两边数值都在现场**的分支传下列唯一公式；所有 producer 一律以关键字 `magnitude=<expr>` 传值，禁止把数值作为第五个位置参数；确需显式 severity 时同时写 `severity=<str>, magnitude=<expr>`。不得自行选 max/sum/first：
   - `check.py:709-730` CAPACITY：initial over=`loads[0]-capacity`；negative arc=`-load`；arc increase=`load-loads[idx-1]`；delivered mismatch=`abs(delivered-node.demand)`；
   - `check.py:747-776` inherited CAPACITY：negative remaining=`-remaining`；over cap=`remaining-capacity`；customer demand over remaining=`demand-remaining`；扣减后 negative=`-remaining`；
   - `algorithms/problem_hgs/evaluation.py:1170-1183` volume CAPACITY：`volume-capacity`，m³；
   - `check.py:798-806` TIME_WINDOW late：`start-due`；`algorithms/problem_hgs/evaluation.py:1202-1220` early=`start-departure_second`、late=`return_second-end`，秒；混 shift 或缺 scheduled certificate 保持 None；
   - `check.py:1037-1100` BATTERY：所有 over cap=`battery-battery_cap`；arc 后负值=`-battery`，kWh；
   - `check.py:1167-1190` charging metadata mismatch：start=`abs(actual_start-expected_start)`、end=`abs(actual_end-expected_end)`；`:1140-1166` 缺字段／非有限保持 None；`:1191-1203` 同一 violation 同时覆盖 start/end 四个 bounds，保持 `magnitude=None`，沿用类别 fallback 1.0，除非用户另批聚合语义；
   - `check.py:562-579` FLEET_SIZE：CV/EV 分别 `count-cap`；`china81_completion.py:280-304` depot type/total 分别 `count-cap`，vehicle；
   - `check.py:1255-1264` PROFIT_FAIRNESS：`required-profit`，CNY；`:1243-1253` 非正 Pi0 类别错误保持 None；
   - `algorithms/problem_hgs/evaluation.py:744-763` CHARGING_ENERGY_GAP=`missing_energy_kwh`，CHARGING_WINDOW_GAP=`window_shortage_seconds`。

   纯类别、缺证书、复合 predicate、非有限输入仍留 None；不得为了“全有数”写 1。
4. 在 `algorithms/problem_hgs/evaluation.py:1034-1091 _measure_violations`，把各类解析统一替换为：

   `float(violation.magnitude) if violation.magnitude is not None else 1.0`。

   fallback 1.0 只保持旧的类别罚值；不从 `detail` 再解析。
5. 删除 :1225-1276 四个 regex helper、`_NUMBER` 和只为它们存在的 `re` import；若 `re` 另有消费者则保留 import。
6. 从 `_measure_violations` 及调用点删除只为 magnitude 反推而传入的 `prepared/bundle/participation_margin/charging_gap` 参数；仍被其他逻辑消费的参数不得误删。
7. 在 :1488-1502 `_violation_keys` 的 tuple key 末尾追加 `violation.magnitude`（包括 None），维持 full/incremental 同一性。
8. 更新所有 `asdict(Violation)` snapshot/schema fixture；`detail` 保留给人读，绝不用于控制流。
9. 施工后立即重算保护 hash：只有 `check.py` 应变化；`cost.py` 和 `search/evaluation.py` 必须等于本文件开头基线。

#### D. 缺口如实

- `HALT_USER_GATE`：字段源头在冻结 `check.py`，用户未单独按键前，源码净改动必须为 0。
- 不加 unit enum 是有意的最小规格：当前消费合同按 violation type 知道单位；新增没有消费者的 enum 会成为自造规格。
- 若某 producer 当前没有比较两边的数值，保留 None；不得在下游猜。

#### E. 验收

1. 第一轮事实复现 E9（正则消费者和受保护 evaluation 确为两个文件）：

   ```bash
   shasum -a 256 \
     solver/src/setp_solver/search/evaluation.py \
     solver/src/setp_solver/algorithms/problem_hgs/evaluation.py
   rg -n '_measure_violations|_NUMBER|re\.search' \
     solver/src/setp_solver/algorithms/problem_hgs/evaluation.py
   ```

2. 原 checker 定向回归：

   ```bash
   PYTHONPATH=solver/src:models/src:third_party/setp_hgs_kernel \
     build/python_envs/setp-independent-hgs/bin/python -m pytest -q \
     solver/tests/test_check.py::CheckSolutionTests::test_detects_fleet_size_cap_violation \
     solver/tests/test_check.py::CheckSolutionTests::test_fleet_size_is_a_hard_physical_vehicle_cap \
     solver/tests/test_check.py::CheckSolutionTests::test_profit_fairness_default_frozen_and_enabled_context
   ```

3. 新增 `solver/tests/test_problem_hgs_violation_magnitude.py`，覆盖 volume/payload、early/late、battery below/above/mismatch、fleet、fairness、两个 charging gaps，并专门断言复合 charging-state bounds violation 的 magnitude 为 None、只改 detail 文案不改变其他 magnitude；用 `inspect.signature(Violation)` 断言 severity/magnitude 都为 keyword-only，并用 `pytest.raises(TypeError)` 断言任何第五位置实参被拒，所有非 None magnitude 的 severity 仍为字符串 `"hard"`。不另写 AST 检查器。
4. 静态禁反解析：

   ```bash
   ! rg -n 're\.(search|findall)|_volume_capacity_magnitude|_time_window_magnitude|_battery_magnitude|_fleet_magnitude' \
     solver/src/setp_solver/algorithms/problem_hgs/evaluation.py
   ```

   预期 0 命中；`_measure_violations` 范围内 `violation.detail` 也应 0 命中。
5. hash：施工记录中 `check.py` 有 before/after；`search/evaluation.py` 必须仍为 `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3`，`cost.py` 仍为开头基线。

#### F. 净行数预算

- 生产：约 `+42/−68`，净减约 26。
- 测试：约 `+110/−0`。
- 用户未按 K2 前：实际预算 `+0/−0`。

---

### 工作项 W2.2　收敛标定与 S5 冻结

#### A. 现状取证

1. private runner 已有真实 convergence 设施：
   - `run_problem_hgs_private_technical.py:2829` 参数 `--convergence-csv Path`；未传时 :3451-3455 默认写 `<output>/convergence.csv`；
   - :3460-3465 header 固定 `cycle,wall_seconds,best_total_cost`；
   - :3470-3489 `stop_and_record(state)` 只在 best 变好时逐行 fsync，并同时读 `--iterations` 与 `--max-runtime-seconds`；
   - :3573-3593 在最终 best 尚未记录时补末行。
2. private CLI :2827-2832 已有 `--instance-id/--seed/--iterations/--max-runtime-seconds/--stagnation-patience`，其中项目默认 patience=500；该值不是外层预算：`third_party/setp_hgs_kernel/setp_hgs_kernel/IntegratedGeneticAlgorithm.py:136-143` 把它接到 `HGSControl.restart_after_iterations_without_improvement`，`HGSControl.py:75-85` 达阈值会清空／重建 population。:2869-2885 已有 `--truth-guided-route-boundary` 和 `--route-truth-candidate-limit`；:2960-2977 有 `--proposal-mode` 和 `--proposal-config`。
3. 当前没有可用的最终算法收敛包。旧 900 秒曲线按 P79 已被判为下降途中截断，不能提供正式预算；`/tmp` 旧长任务也没有留下可复核产物。
4. `solver/reports/p31_boundary_weld_20260817/report.md:46-58` 只给 seed 11、1 cycle、education depth 1 的存在性探针：ε 候选 `1,2,3,5,10`；ε=3 首次看到 rank-3 可接受动作。报告明确说没有全邻域 census，不能把 ε=3 当正式值。
5. public runner 也有标准轨迹积木：
   - `run_public_v2_28_clean_ruler.py:279-330 _TraceRow/_TracingStop` 每 iteration 记录 `iteration,elapsed_seconds,best_cost`；
   - :993-995 把 trace 写为每个 run package 的 `raw_runs.csv`；:1179-1180 验证非空；
   - :1579-1604 worker/probe/batch 有 `--seed/--max-runtime-seconds/--no-improvement/--run-kind`；
   - :1610-1615 当前把 batch seed 硬锁 11、runtime 上限硬锁 1200 秒。这两数不能作为 P79 正式预算。
6. 动态 technical runner `run_problem_hgs_dynamic_technical.py:201-229` 当前无 `--seed`、无 convergence CSV，且 :329/:340/:511 固定常量 `SEED`；W1.1 又处于缺砖 HALT，所以动态每决策点预算当前不可标定。

#### B. 积木清单

| 积木 | 版本／路径 | 接口 | 许可证／身份 | 人类作品证据 |
|---|---|---|---|---|
| private convergence writer | 当前 HEAD | `stop_and_record(state)` | PROJECT_DOMAIN（existing） | 已逐行 fsync 并被 runner 使用 |
| public tracing stop | 当前 HEAD | `_TracingStop(max_runtime_seconds, no_improvement)` | PROJECT_DOMAIN（existing） | 已生成 per-iteration raw trace |
| experiment acceptance | 当前 HEAD | 五件套 finalize/validate | PROJECT_DOMAIN（existing） | 多 runner 共用；W0.3 只修字样 |
| canonical JSON/SHA | Python ≥3.10 | `json`、`hashlib.sha256` | PSF | Python 官方 |
| Matplotlib | 3.11.1（仓内 `build/python_envs/setp-independent-hgs` 已有；官网 `https://matplotlib.org/`） | `pyplot.subplots/step/savefig` | Matplotlib License（PSF-based） | Matplotlib 人类开发团队；只画原始 step 曲线，不做平滑／判定 |

标定判官不是新工具：P79 已定“看收敛曲线形态，由用户看图”；不得写自动斜率阈值。

#### C. 拼装步骤

1. 先完成**接线层**再采曲线：W0.2 血统分支、W1.2 effective hash、W1.3 standalone/joint 入口、W2.2 本节 C.7-C.13 的 convergence／manifest 基础设施，以及 W3.1 C.1-C.10 的共用 private carbon/formal 入口都必须先施工；F5 标定前还须完成 W3.4 C.1-C.10 对同一 public runner 的全部 manifest/per-unit budget/aggregate 接线，不得 S5 冻结其代码 SHA 后再给它补 `aggregate` 子命令。F2 线若 K6-A 获批，`build_f2_inputs.py` 的 `select` 与 `finalize` 两子命令也必须在 S5a 计算 code-source map 前一次完成；K6 未决时 F2 stage1 formal 等待，K6-B 则按 W3.2 HALT。此时只运行 technical/probe，不运行 formal。然后才做本节标定，每档 metadata 记录 Git commit、该行为 profile 的 `search_configuration_sha256` 和另存的 runtime identities。同一 profile 跨 seed 必须配置 hash 相同，但 route-engine runtime hash 应随 seed/instance/state 如实变化。任何行为代码变化后，已有标定全部作废重来。这个分段解除“W2 需要碳价 CLI、碳价 CLI 又写在 W3.1”的文面循环；W3.1/W3.2 的正式命令仍必须等 S5 manifest。
2. private 观测矩阵固定为：
   - 算例 `cn-jjj-50c-01-DEPOTSEARCH-d996f755bd`；
   - 探索 seeds `1,2,3`（P79 允许 1–3，不拿它作正式效应）；
   - common flags：`--population-mode copied_hgs_defaults --proposal-mode system --proposal-config combat --trajectory off`；
   - boundary OFF 一格；
   - boundary ON × ε `1,2,3,5,10` 五格。五个候选只来自 A.4 的当前实现存在性读数，不是论文参数。
   - P18 已固定 `asap/cost_min/cost_plus_carbon` 三个 policy；K3 只决定它们在价格格点上的 cell 布局。每个实际进入 `f1_run_cells` 的 policy 都是独立配置格，命令必须显式传 `--charge-timing-policy <exact-policy>`；在 K4 候选 grid 的最低／最高点以及 scout 发现的车型或充电断点各取曲线。每个 policy 只能冻结由这些曲线共同支持的 budget/patience，不能用默认 `cost_plus_carbon` 曲线替 `asap/cost_min`；若用户选择一个跨价共同预算，取其亲自批准的各观测点充分档，不由脚本自动取 max。
   - restart patience 是独立算法配置轴，不能跟随每个 iteration tier 改。每个待观察候选先登记 `value/source_kind/source_locator`；现有项目默认 500 只能作为首个 exploration 候选，不自动成为正式值。每个 patience 候选使用独立 `CONFIG` 与稳定 hash；用户依据同一候选内部的 3-seed 曲线／最终 restarts 选择，未冻结时停在 D.1。
3. 对每个固定 `RESTART_PATIENCE` 候选，分别从一个短观测档开始，只有外层 `iterations` 按现行规则成 10 倍增加；同一候选所有 tier 的 stable hash 必须相同。起始档 `T0`、运营安全墙钟 `SAFETY_WALL_SECONDS`、500 之外是否需要其他 patience 候选当前均为 `UNKNOWN`，施工前在观测清单中登记来源。命令模板：

   ```bash
   INSTANCE=cn-jjj-50c-01-DEPOTSEARCH-d996f755bd
   CONFIG="${CONFIG:-boundary_off}"
   SEED="${SEED:?set one exploration seed: 1, 2, or 3}"
   case "$SEED" in 1|2|3) ;; *) exit 2;; esac
   RESTART_PATIENCE="${RESTART_PATIENCE:?set one pre-registered candidate}"
   ITERATIONS="${ITERATIONS:?set one pre-registered tenfold tier}"
   SAFETY_WALL_SECONDS="${SAFETY_WALL_SECONDS:?set the registered nonbinding operational ceiling}"
   OUT="solver/reports/s5_convergence_20260818/${CONFIG}/patience_${RESTART_PATIENCE}/seed_${SEED}/tier_${ITERATIONS}"
   PYTHONPATH=solver/src:models/src:third_party/setp_hgs_kernel \
     build/python_envs/setp-independent-hgs/bin/python solver/scripts/run_problem_hgs_private_technical.py \
     "$OUT" \
     --instance-id "$INSTANCE" --seed "$SEED" \
     --iterations "$ITERATIONS" \
     --stagnation-patience "$RESTART_PATIENCE" \
     --max-runtime-seconds "$SAFETY_WALL_SECONDS" \
     --convergence-csv "$OUT/convergence.csv" \
     --population-mode copied_hgs_defaults \
     --proposal-mode system --proposal-config combat --trajectory off
   ```

   每个 tier 新目录从头跑，不能续接上档后把两段曲线拼成一次 run；绝不能再写 `--stagnation-patience "$ITERATIONS"`，那会同时改变 restart 行为和 stable hash。
   F1 配置格在上述命令末尾明确追加 `--charge-timing-policy "$POLICY" --carbon-price-cny-per-kg "$OBSERVATION_PRICE"`，且 `CONFIG="f1_${POLICY}_price_${PRICE_TAG}_${BOUNDARY_TAG}"`；两个值均来自预登记观测表。F2 standalone 格则显式追加最终 F2 policy/reference price 和 `--enterprise-id`。
4. boundary ON 只在步骤 3 末尾加：

   ```bash
   ROUTE_TRUTH_CANDIDATE_LIMIT="${ROUTE_TRUTH_CANDIDATE_LIMIT:?set one of 1,2,3,5,10}"
   case "$ROUTE_TRUTH_CANDIDATE_LIMIT" in 1|2|3|5|10) ;; *) exit 2;; esac
   BOUNDARY_ARGS=(
     --truth-guided-route-boundary
     --route-truth-candidate-limit "$ROUTE_TRUTH_CANDIDATE_LIMIT"
   )
   ```

   将 `"${BOUNDARY_ARGS[@]}"` 追加到步骤 3 的 runner 命令。目录 `CONFIG` 固定为 `boundary_on_e1` 等，不能靠 metadata 外的口头说明区分。
5. W1.3a 完成后，对 `ENT_A`、`ENT_B` 分别复用同一观测流程、seeds 1–3 和十倍 tier，只在步骤 3 增加 `--enterprise-id ENT_A/ENT_B`。S5 分别冻结 25-customer A、25-customer B、50-customer joint 的 restart patience 与外层预算；不得借 joint 曲线猜 standalone。
6. public 28 题用已有 `probe` controller 做零论文效力标定；controller 会经 `_worker_command` 为 independent 选择独立 HGS Python、为 frozen 选择 `/opt/anaconda3/bin/python3.13` 并清掉 `PYTHONPATH`。不得从 independent Python 直接调用 `worker --arm frozen_pyvrp`。每题、每臂 seed 1，`no_improvement` 十倍扩档，墙钟只作不应触发的安全绳：

   ```bash
   INSTANCE="${INSTANCE:?set one of PR11A..PR24B}"
   ARM="${ARM:?set independent or frozen_pyvrp}"
   NO_IMPROVEMENT="${NO_IMPROVEMENT:?set one preregistered tier}"
   SAFETY_WALL="${SAFETY_WALL:?set a nonbinding observational ceiling}"
   OUT="solver/reports/s5_public_convergence_20260818/${INSTANCE}/${ARM}/seed_1/tier_${NO_IMPROVEMENT}"
   build/python_envs/setp-independent-hgs/bin/python solver/scripts/run_public_v2_28_clean_ruler.py probe \
     "$OUT" --instance "$INSTANCE" --arm "$ARM" \
     --seed 1 \
     --no-improvement "$NO_IMPROVEMENT" \
     --max-runtime-seconds "$SAFETY_WALL"
   ```

   在此之前把 :1612 的 `>1200` 自造上限删除，只保留正数校验；若安全墙钟触发，该档只记 censored，不提供收敛预算。
   每个 probe 还必须复用 public runner 现有 `_independent_source_identity/_frozen_source_identity` 的文件枚举，改为对实际 runtime package root 下 `.py/.pyi/.so/.dylib`（排除 `._*`）生成**相对 package root**的 `path->sha256` 与 canonical 总 SHA；instance/runner 另由各自既有字段记，不混进 package SHA。同一 arm 的全部 probe 必须给出同一 runtime package SHA，S5 才能把该 map/SHA 冻结进 manifest；版本字符串相同但二进制不同不得通过。
7. 在 private runner `:3460-3483`，把 convergence header 从三列扩为 `cycle,wall_seconds,full_evaluations,incremental_evaluations,sentinel_evaluations,actual_full_model_evaluations,best_total_cost`；每次 best 改善时直接从现有 `ProblemHGSSearchState:123-133` 写六个计数／时钟字段，不新增计数器。这里 `wall_seconds` 唯一定义为现有 `state.elapsed_seconds = initialization_wall_seconds + in_runner_elapsed` 的**总算法时钟**。同步改写 `:3573-3593`：抽出同一七字段常量／row builder，搜索结束后的终态 wall 必须取 `result.accounting.initialization_wall_seconds + result.accounting.run_wall_seconds`，不得只取较小的 `run_wall_seconds`；`raw_runs.csv` 同步新增同值 `total_algorithm_wall_seconds`，保留原 `run_wall_seconds` 的现有含义。终态行从 `result.iterations`、`result.accounting` 和 `result.best_evaluation.total_cost` 构造；若现有末行的 cycle、总 wall 和全部 counters 已与终态逐位相同才去重，否则无论 best 是否再改善都追加，best 可与上行相同。禁止保留第二份三字段 `fieldnames`，也禁止因 `last_logged_best` 相等而丢掉平台期终点。客户数与需求量不在 state 中，只从每个完成包的 `raw_runs.csv` 作为端点读取，禁止伪造逐 iteration 服务曲线；本项不顺手重定义 `SearchAccounting.run_wall_seconds`。
8. 新增 `solver/scripts/plot_s5_convergence.py`（`declared_identity=PROJECT_ADAPTER`，`code_role=ORCHESTRATION`，≤250 行），只用 stdlib `csv/pathlib` 和已囤 Matplotlib 3.11.1：
   - 参数固定 `--private-root --public-root --output-dir`；
   - private 生成 `private_convergence.pdf` 三 panel：best vs cycle、actual full-model evaluations、total algorithm wall seconds；
   - public 生成 `public_convergence.pdf` 两 panel：best vs iteration、elapsed seconds；
   - 每个 config/seed/tier 一条原始 best-so-far step line，不平滑、不丢末点、不算斜率；
   - 另写 `endpoint_service.csv`，逐包保存客户完成数、需求完成量、`termination_status`、`censored`、acceptance 状态及包路径。

   固定调用：

   ```bash
   PYTHONPATH=solver/src:solver/scripts \
     build/python_envs/setp-independent-hgs/bin/python \
     solver/scripts/plot_s5_convergence.py \
     --private-root solver/reports/s5_convergence_20260818 \
     --public-root solver/reports/s5_public_convergence_20260818 \
     --output-dir solver/reports/s5_convergence_20260818/figures
   ```

   该脚本只呈证据，不拥有“是否收敛”的判据。
9. F2 存在真实依赖环：fairness-on joint 的收敛曲线需要先有 20 个 standalone 产生的外冻 Pi0。不得用 fairness-off joint 曲线填 joint profile。为保持 30 个正式求解包而不覆盖证据，用户分两次冻结、文件均不可变：
   - S5a 新增 `solver/config/formal_campaign_20260818_stage1.json`，只把 `private/f2/ENT_A`、`private/f2/ENT_B` 的 hash/budget 置为非 null；`private/f2/joint` 与未完成 profile 为 null。W3.2 用它正式跑 20 个 standalone；
   - 20 包全合格并生成 Pi0 后，按步骤 10 做 fairness-on joint 标定；用户 S5b 再新增启用 F2-joint 的 immutable revision，不得覆盖 stage1。**只有启用 F2 且 `private/f2/joint` 非 null 的 revision** 才必须保存 `predecessor_manifest_path/predecessor_manifest_sha256/pi0_manifest_sha256`；F1-only、F3-only、F5-only revision 不被未完成的 F2 predecessor/Pi0 卡住。各线路只在自身证据齐后加入 `enabled_campaigns` 并填其 section，不要求等别的线路。
10. joint 标定必须显式消费同一 Pi0，使用 W3.2 生成的路径、seeds 1–3、固定 patience 候选和十倍 iteration tier；命令骨架：

   ```bash
   CAMPAIGN=solver/config/formal_campaign_20260818_stage1.json
   CAMPAIGN_ID="$(jq -er '.campaign_id' "$CAMPAIGN")"
   PI0="solver/reports/f2_${CAMPAIGN_ID}/inputs/pi0_manifest.json"
   SEED="${SEED:?set one exploration seed: 1, 2, or 3}"
   case "$SEED" in 1|2|3) ;; *) exit 2;; esac
   RESTART_PATIENCE="${RESTART_PATIENCE:?set one pre-registered joint candidate}"
   ITERATIONS="${ITERATIONS:?set one pre-registered tenfold tier}"
   SAFETY_WALL_SECONDS="${SAFETY_WALL_SECONDS:?set the registered nonbinding operational ceiling}"
   POLICY="$(jq -er '.f2_charge_timing_policy' "$CAMPAIGN")"
   PRICE="$(jq -er '.f2_reference_carbon_price_cny_per_kg' "$CAMPAIGN")"
   BOUNDARY_ENABLED="$(jq -r '.truth_guided_route_boundary' "$CAMPAIGN")"
   BOUNDARY_LIMIT="$(jq -r '.route_truth_candidate_limit // empty' "$CAMPAIGN")"
   BOUNDARY_ARGS=()
   if [[ "$BOUNDARY_ENABLED" == true ]]; then
     test -n "$BOUNDARY_LIMIT"
     BOUNDARY_ARGS=(--truth-guided-route-boundary --route-truth-candidate-limit "$BOUNDARY_LIMIT")
   else
     test -z "$BOUNDARY_LIMIT"
   fi
   OUT="solver/reports/s5_convergence_20260818/f2_joint_fairness_on/patience_${RESTART_PATIENCE}/seed_${SEED}/tier_${ITERATIONS}"
   PYTHONPATH=solver/src:models/src:third_party/setp_hgs_kernel \
     build/python_envs/setp-independent-hgs/bin/python solver/scripts/run_problem_hgs_private_technical.py \
     "$OUT" --instance-id cn-jjj-50c-01-DEPOTSEARCH-d996f755bd \
     --pi0-manifest "$PI0" --seed "$SEED" \
     --iterations "$ITERATIONS" --stagnation-patience "$RESTART_PATIENCE" \
     --max-runtime-seconds "$SAFETY_WALL_SECONDS" \
     --convergence-csv "$OUT/convergence.csv" \
     --population-mode copied_hgs_defaults \
     --proposal-mode system --proposal-config combat --trajectory off \
     "${BOUNDARY_ARGS[@]}" \
     --charge-timing-policy "$POLICY" \
     --carbon-price-cny-per-kg "$PRICE"
   ```

   这是 exploration/technical 标定，不写 formal verdict；metadata 必须为 `fairness_enabled=true`、`theta=1.0`、Pi0 SHA exact 等于 20 包生成值。只有这些曲线才能给 `private/f2/joint` 冻结 hash/budget。
11. 两份 manifest 共用 schema `resetp.formal_campaign.v1`，字段固定：
   - `revision/campaign_id/decision_id/approved_at/approved_by/enabled_campaigns`；`campaign_id` 必须匹配 `[a-z0-9_]+`，是输出根、Pi0 source id 与 launch label 的唯一目录身份，不从文件名猜；`enabled_campaigns` 只含 `f1/f2/f3/f5` 且不得重复，正式入口只可启动已列入的线路；这样 F2 stage1 不会被尚未冻结的 F1/F5 字段反向卡死；
   - `git_commit/code_source_sha256/code_source_files/effective_execution_schema`；`git_commit` 不能代替对 dirty worktree 的字节身份；
   - `private_input_files/private_input_sha256`：前者是 DEPOTSEARCH 运行实际读取的 repo-relative regular-file `path->SHA256` exact map，后者是同一排序 map 的 canonical JSON SHA；stage1/final 都必须非空且逐位相同，不能只冻结 `private_instance_id`；
   - `public_instance_sha256_by_id`：F5 未启用时为 null；F5 启用时 keys 必须 exact 为 28 个 `INSTANCES`，value 为对应 `.vrp` 文件字节 SHA，不得只冻结文件名；
   - `search_configuration_sha256_by_profile`：有限 mapping；key 固定为 `private/f1/<charge_timing_policy>`、`private/f2/ENT_A`、`private/f2/ENT_B`、`private/f2/joint`、`dynamic/f3/initial`、`dynamic/f3/rolling`，value 为 W1.2 稳定算法配置 hash或 null；不得存 seed/instance/stage runtime hash；
   - `private_budget_by_profile`：与上述 `private/*` keys exact cover；每个非 null row 为 `iterations/restart_patience/safety_wall_seconds`。F1 每 policy 一行，F2 每 scope 一行；值必须来自该 exact policy/fairness 配置的固定-patience曲线；
   - `private_instance_id`、`truth_guided_route_boundary/route_truth_candidate_limit`；
   - `dynamic_initial_restart_patience`、`dynamic_restart_patience_per_decision`、`dynamic_initial_iterations`、`dynamic_iterations_per_decision`、`dynamic_safety_wall_seconds`（W1.1/W3.3 未解时必须 null）；
   - `f3_trigger_policy/f3_time_threshold_seconds/f3_demand_threshold_kg/f3_demand_threshold_source/f3_idle_ev_readiness_mode/f3_arms`：F3 未启用或 K5 未决时全部为 null；启用时 `f3_trigger_policy` 只承载 P10 已定的“时间或累计需求先到者触发”，`f3_time_threshold_seconds` 必须为 P10 已定的 `1800`，需求阈值必须是 finite positive kg，source 必须非空且能指向 K5 采用的数据表／推导式。formal runner 必须逐项读取并与实际 `build_o1_batches` 输入比较，不得再调用 `demand_threshold_kg(full_bundle.instance)` 偷算默认值；
   - `public_budget_by_instance_and_arm`；F5 未启用时为空 mapping；启用时每个 `instance/arm` 明列 `no_improvement_iterations/safety_wall_seconds` 且 exact cover 56 个 unit；
   - `public_runtime_package_files_by_arm/public_runtime_package_sha256_by_arm`；F5 未启用时为空 mapping；启用时 keys exact 为 `independent/frozen_pyvrp`，每个 files map 以 package-root-relative path 为 key并覆盖 `.py/.pyi/.so/.dylib`，SHA 为其 canonical 总摘要，且两 arm value 非 null、互相复算一致；
   - `carbon_price_grid`；F1 未启用时为空 tuple，启用时每点含用户直接冻结的唯一 `point_id`与 `value_cny_per_kg/source_kind/source_locator`；`point_id` 必须匹配 `[a-z0-9_]+`、全表唯一，loader 不根据 float 四舍五入生成目录 tag；
   - `f1_arm_semantics/f1_policy_list/f1_reference_carbon_point_id`；F1 未启用时分别为 null/空/null；启用时 `f1_policy_list` 必须 exact 为 P18 已定的 `("asap","cost_min","cost_plus_carbon")`，不是 K4 再选；semantics 只准 `FULL_POLICY_PRICE_CARTESIAN` 或 `PRIMARY_SWEEP_BASELINES_AT_REFERENCE`，reference 在前一语义可为 null、后一语义必须指向 grid member；
   - `f1_run_cells`；F1 未启用时为空 tuple；启用时每行为 `policy/carbon_point_id/profile`，exact nonempty 且 `(policy,carbon_point_id)` 唯一。K3-A 由用户冻结为 policy×grid 完整笛卡尔集；K3-C 由用户直接列出主策略全 grid＋两基线 reference 点。施工者不从一句 semantics 自行展开；
   - `f2_reference_carbon_price_cny_per_kg/f2_charge_timing_policy/f2_participation_ledger`；F2 未启用时都为 null；启用时前两项必须为 finite nonnegative／非空枚举值，`f2_participation_ledger` 只准 `"operational"|"allocated"`。该值来自 K6：当前只有 `"operational"` 可继续 S5a/joint；`"allocated"` 必须按既有 HALT 停在 formal 之前。loader、runner 与聚合器都读字段，不得硬编码 operational；
   - `seeds=[1,2,3,4,5,6,7,8,9,10]`、`formal_search_allowed=true`；
   - 仅当 `"f2" in enabled_campaigns` 且 `private/f2/joint` profile/budget 非 null 时，predecessor path/hash 与 Pi0 hash 三项必为非 null并互相复算；F2 standalone stage1 及不启用 F2-joint 的独立 revision三项都为 null。
12. 新增 `solver/src/setp_solver/formal_campaign.py`（身份＝PROJECT_ADAPTER，≤250 行），只用 stdlib JSON/dataclasses/hashlib 加载和验证，不判断“曲线是否收敛”，不生成价格点或预算。公开 API 固定：

   ```python
   @dataclass(frozen=True)
   class PrivateBudget:
       iterations: int
       restart_patience: int
       safety_wall_seconds: float

   @dataclass(frozen=True)
   class PublicBudget:
       no_improvement_iterations: int
       safety_wall_seconds: float

   @dataclass(frozen=True)
   class CarbonPricePoint:
       point_id: str
       value_cny_per_kg: float
       source_kind: str
       source_locator: str

   @dataclass(frozen=True)
   class F1RunCell:
       policy: str
       carbon_point_id: str
       profile: str

   @dataclass(frozen=True)
   class CodeSourceIdentity:
       files: Mapping[str, str]
       sha256: str

   @dataclass(frozen=True)
   class FormalCampaign:
       revision: str
       campaign_id: str
       decision_id: str
       approved_at: str
       approved_by: str
       enabled_campaigns: tuple[str, ...]
       git_commit: str
       code_source_sha256: str
       code_source_files: Mapping[str, str]
       private_input_files: Mapping[str, str]
       private_input_sha256: str
       public_instance_sha256_by_id: Mapping[str, str] | None
       effective_execution_schema: str
       search_configuration_sha256_by_profile: Mapping[str, str | None]
       private_budget_by_profile: Mapping[str, PrivateBudget | None]
       private_instance_id: str
       truth_guided_route_boundary: bool
       route_truth_candidate_limit: int | None
       dynamic_initial_restart_patience: int | None
       dynamic_restart_patience_per_decision: int | None
       dynamic_initial_iterations: int | None
       dynamic_iterations_per_decision: int | None
       dynamic_safety_wall_seconds: float | None
       f3_trigger_policy: str | None
       f3_time_threshold_seconds: int | None
       f3_demand_threshold_kg: float | None
       f3_demand_threshold_source: str | None
       f3_idle_ev_readiness_mode: str | None
       f3_arms: tuple[str, ...] | None
       public_budget_by_instance_and_arm: Mapping[str, Mapping[str, PublicBudget]]
       public_runtime_package_files_by_arm: Mapping[str, Mapping[str, str] | None]
       public_runtime_package_sha256_by_arm: Mapping[str, str | None]
       carbon_price_grid: tuple[CarbonPricePoint, ...]
       f1_arm_semantics: str | None
       f1_policy_list: tuple[str, ...]
       f1_reference_carbon_point_id: str | None
       f1_run_cells: tuple[F1RunCell, ...]
       f2_reference_carbon_price_cny_per_kg: float | None
       f2_charge_timing_policy: str | None
       f2_participation_ledger: str | None
       seeds: tuple[int, ...]
       formal_search_allowed: bool
       predecessor_manifest_path: str | None
       predecessor_manifest_sha256: str | None
       pi0_manifest_sha256: str | None
       source_path: Path
       source_sha256: str

   def compute_code_source_identity(repo: Path) -> CodeSourceIdentity: ...
   def compute_file_set_identity(repo: Path, relative_paths: Iterable[str]) -> CodeSourceIdentity: ...
   def load_formal_campaign(path: Path, *, repo: Path) -> FormalCampaign: ...
   ```

   `compute_code_source_identity` 对 `solver/src/setp_solver`、`models/src`、`third_party/setp_hgs_kernel/setp_hgs_kernel` 下的行为文件（`.py/.pyi/.c/.cc/.cpp/.h/.hpp/.so/.dylib`）和 vendor `UPSTREAM_COMMIT/LICENSE.md/meson.build/pyproject.toml` 建立 `path->file_sha256`；排除 `__pycache__/.venv/build/reports` 以及 AppleDouble `._*`。`.so/.dylib` 必须纳入，因为当前 `LocalSearch.py` 等实际加载五个 Mach-O extension；只 hash C++ 源不能标识运行字节。另外 **必须 exact 包含且任一缺失即拒绝**：`third_party/UPSTREAM_PROVENANCE.tsv`、`third_party/UPSTREAM_MANIFEST.sha256`，`solver/scripts/run_problem_hgs_private_technical.py`、`run_problem_hgs_dynamic_disclosure_scout.py`、`run_public_v2_28_clean_ruler.py`、`experiment_acceptance.py`、`build_china81_suite_rebuild_20260812.py`、`build_f2_inputs.py`、`coalition_accounting_adapter.py`、`aggregate_formal_campaign.py`，`baselines/china_e3_e7/e7_h0_g2_foundation_20260801/stream.py`、`baselines/china_e3_e7/e7_o1_replanning_20260801/policy.py`、`baselines/china_e3_e7/e7_trigger_policies_20260801/trigger_policies.py`，以及 `third_party/harvested_materials/07_collaboration_profit/pycoopgame/upstream/pyCoopGame/Shapley.py`。正式预检还先执行等价于 `shasum -a 256 -c third_party/UPSTREAM_MANIFEST.sha256` 的逐行复算。对全部相对路径排序后用现有 canonical JSON 形式算总 SHA。manifest 同时冻结 exact path map 与 SHA，因此 HEAD 相同但任一未提交 provenance、行为源或 native binary 改一字节也会被拒绝。`compute_file_set_identity` 只接受 repo 内 regular files，拒绝目录、缺失、重复与越界路径，并用同一排序 JSON 规则返回 map/SHA；它不解析领域数据，也不扩目录。
13. private/dynamic/public 正式入口在 W3 统一要求 `--formal-campaign-manifest`；先要求本线路存在于 `enabled_campaigns`。在构建 evaluator/builder 或启动任何 worker 前，调同一 `compute_code_source_identity(repo)` 并对 manifest 的 exact file map 与总 SHA，任一差异即 fail-before-search。private/dynamic 还必须把 loader 返回的 concrete `bundle.source_paths` values 交 `compute_file_set_identity`，与 `private_input_files/private_input_sha256` exact compare；public controller/worker 则在 solve 前把当前 `.vrp` 字节 SHA 与 `public_instance_sha256_by_id[instance_id]` compare。使用仓内 HGS kernel 的进程还要对已导入的 `setp_hgs_kernel._setp_hgs_kernel`、`setp_hgs_kernel.crossover._crossover`、`setp_hgs_kernel.diversity._diversity`、`setp_hgs_kernel.repair._repair`、`setp_hgs_kernel.search._search` 逐个读取 `module.__file__`，要求其 resolved path 与 SHA exact 命中 manifest map；加载到 `.venv/site-packages` 的另一份同名二进制也必须拒绝。使用 HGS 的入口另要求有限 `--search-configuration-profile`，把 mapping 中该 key 的值传给 W1.2 新增的 `run_integrated_problem_hgs(..., expected_search_configuration_sha256=...)`。common runner 在 builder 返回、搜索循环开始前把 actual stable hash 与 expected exact compare；runtime engine SHA 只进 provenance。null profile 一律拒绝 formal。只有 manifest 的源码/native/输入字节、静态字段与 profile hash 都通过，运行身份才为 formal；不得直接把 sealed DEPOTSEARCH package 里的 false 原地改 true。
14. P102 碳价格点在 S5 前还要完成两步：
    - 文献表：每个候选范围写 DOI、PDF 页、原币种／质量单位与是否可直接换算；
    - 新鲜测量：W3.1 碳价 override 接通后，用最终 config、当前 instance、seed 1 做 exploration-only 粗到细 scout，保存每点车型数／充电量／成本／排放及满服务。旧 1.223/1.472/2.27 只可作为待重测定位参考，不自动入 grid。

#### D. 缺口如实

- `HALT_RESTART_PATIENCE`：每个 private F1 policy 与 F2 scope 的 restart patience 未经 exact 配置的固定候选曲线与用户 S5 冻结前，不能生成对应 formal profile；当前默认 500 只是有出处的首个 exploration 候选。
- `HALT_F2_JOINT_PROFILE`：stage1 的 joint hash/budget 必须为 null；20 个 standalone、Pi0 和 fairness-on joint 标定完成前，最终 manifest 不得把 `private/f2/joint` 填成非 null。
- `UNKNOWN`：T0、P0、安全墙钟、各正式预算、500 之外的 patience 候选、boundary 开关、ε、carbon grid。它们只能来自当前最终代码的曲线／文献页码／用户 S5。
- `HALT_DYNAMIC_BUDGET`：W1.1 缺砖，且多阶段 runner 当前绕开 common runner、没有 exact per-decision iteration convergence；五个 dynamic patience/budget 字段必须为 null，F3 不开跑。
- `FACT_CANDIDATE_LIBRARY_RESOLVED`：Chen et al. 2023、Liao et al. 2019、Shen et al. 2018、Wilson & Stone 2026 已补到原文页码；候选范围已具备。`HALT_FINAL_GRID` 仍有效：当前实例新测量、CO2/CO2e 口径和用户 S5 未完成前，不能形成正式 grid。
- 收敛曲线若仍持续改善，继续下一十倍档；若机时不可承受，把事实和曲线呈用户，不设自动“差不多”阈值。

#### E. 验收

1. 第一轮事实复现 E14（S5 各 scope 字段及 v2 新增字段均可机械定位）：

   ```bash
   rg -n 'search_configuration_sha256_by_profile|private_budget_by_profile|dynamic_initial|public_budget_by_instance_and_arm|carbon_price_grid|f1_run_cells|f1_reference_carbon_point_id|f2_participation_ledger|f3_time_threshold_seconds|f3_demand_threshold_kg|f3_demand_threshold_source' \
     docs/handoff/reform_council_20260818/execution_blueprint_20260818.md
   ```

2. 每个 private `convergence.csv`：

   ```bash
   python3 - <<'PY'
   import csv, json, pathlib
   paths = list(pathlib.Path("solver/reports/s5_convergence_20260818").rglob("convergence.csv"))
   assert paths, "no convergence.csv files"
   for path in paths:
       rows = list(csv.DictReader(path.open()))
       assert rows and tuple(rows[0]) == (
           "cycle", "wall_seconds", "full_evaluations",
           "incremental_evaluations", "sentinel_evaluations",
           "actual_full_model_evaluations", "best_total_cost",
       )
       cycles = [int(r["cycle"]) for r in rows]
       walls = [float(r["wall_seconds"]) for r in rows]
       actual = [int(r["actual_full_model_evaluations"]) for r in rows]
       best = [float(r["best_total_cost"]) for r in rows]
       assert cycles == sorted(cycles) and walls == sorted(walls)
       assert actual == sorted(actual)
       assert all(b <= a for a, b in zip(best, best[1:]))
       meta = json.loads((path.parent / "metadata.json").read_text())
       raw = next(csv.DictReader((path.parent / "raw_runs.csv").open()))
       assert cycles[-1] == int(meta["iterations"]) == int(raw["iterations"])
       assert actual[-1] == int(raw["actual_full_model_evaluations"])
       assert abs(walls[-1] - float(raw["total_algorithm_wall_seconds"])) <= 1e-6
   PY
   ```

   预期无输出、exit 0。该命令只查轨迹内部一致性，不替用户判断收敛。
3. 执行 C.8 固定绘图命令；预期 `private_convergence.pdf`、`public_convergence.pdf`、`endpoint_service.csv` 三件存在且非空，PDF/CSV SHA 写入该标定包 `artifact_hashes.json`。
4. 每包 acceptance 必须满客户、满需求、0 hard violation；censored 安全墙钟包保留但不能进入 S5 候选预算证据。
5. manifest loader 测试 `solver/tests/test_formal_campaign.py` 覆盖 revision/campaign_id/predecessor SHA、Git/profile hash/instance/seed/grid source/批准字段错配，`campaign_id/point_id` 安全 ASCII 与唯一性，`f1_run_cells` 的 policy/point/profile exact membership 和 A/C 两种用户冻结集，并断言 F1 启用时 policy list exact 为 P18 三项；覆盖 `f2_participation_ledger` 的 null/operational/allocated 三态，证明聚合读取该字段且 allocated 在 formal 前按 HALT 拒绝；覆盖 F3 的 1800 秒、finite-positive demand kg、非空 source 三字段与实际 batching 输入逐位一致。并证明 `enabled_campaigns=("f2",)` 的 stage1 可令 F1 tuple 为空、F5 mapping 为空、F3 字段为 null，同时 joint profile 必须 null；F1-only 与 F5-only revision 在 predecessor/Pi0 为 null 时也能加载；启用各线路时才要求其 section 非空，启用 F2-joint 时 joint/Pi0/predecessor 必须非 null，technical run 不能靠命令行口头写 formal。在 `tmp_path` 复制的行为文件集上先冻结 `code_source_files/code_source_sha256`，再分别改一份 `.py` 与一份 `.so` 一字节，并模拟某 extension 的 `module.__file__` 指向 map 外路径；三种正式预检都必须拒绝。另复制 DEPOTSEARCH exact input map，分别改 `orders.csv`、一份 matrix CSV、runtime calendar 一字节；再复制一个 public `.vrp` 改一字节；对应 private/dynamic `algorithm.run` 与 public solve/worker subprocess 均须 0 次。另复制一份 frozen runtime package、保持版本字符串但改 `.so` 一字节，public formal worker必须在 solve 前拒绝。
6. 用户 S5a/S5b 后的 manifest 验收：

   ```bash
   PYTHONPATH=solver/src python3 - <<'PY'
   from pathlib import Path
   from setp_solver.formal_campaign import load_formal_campaign
   repo = Path.cwd().resolve()
   s = load_formal_campaign(Path("solver/config/formal_campaign_20260818_stage1.json"), repo=repo)
   f = load_formal_campaign(Path("solver/config/formal_campaign_20260818.json"), repo=repo)
   assert f.predecessor_manifest_sha256 == s.source_sha256
   print(s.search_configuration_sha256_by_profile)
   print(f.search_configuration_sha256_by_profile)
   PY
   ```

   预期 stage1 `enabled_campaigns=("f2",)`，只有 ENT_A/ENT_B profile 非 null，F1/F5 sections 为空且不阻断加载；final predecessor hash exact。每个非 null value 都是 64 位。同一 profile、同一 fixed patience 下的 3-seed 与所有 iteration tiers 配置 hash逐位相同并等于对应 value，runtime identity 不要求相同。若同一 patience 的 tier 间 hash 漂移则拒绝 S5；halted dynamic profile 仍为 null。

#### F. 净行数预算

- `formal_campaign.py` 与三个 runner 的 manifest 接口：约 `+125/−2`。
- convergence 计数字段接线与 `plot_s5_convergence.py`：约 `+105/−3`；绘图脚本必须 ≤250 行。
- 两份不可变 manifest 配置本体：约 `+90/−0`，分别只在用户 S5a/S5b 后生成。
- 测试：约 `+80/−0`。
- 标定输出行数／机时：`UNKNOWN`，由曲线决定，不计源码预算。

---

### 工作项 W3.1　F1 时变碳价 × 混合车队正式批次

#### A. 现状取证

1. 当前碳价格不是 runner 参数，而是在 `solver/src/setp_solver/china81.py:47-48` 写死：`carbon_price=0.07502 CNY/kg`，`carbon_price_low=0.05632 CNY/kg`。
2. `China81Bundle` 是冻结 dataclass（`china81.py:213-247`），其中只有 `prices: PriceParameters`，没有“本情景采用的碳价”字段。`China81Bundle.__post_init__:249-287` 又在 `expected_core` 中强制 `prices.carbon_price == CHINA81_CARBON_PRICE_CNY_PER_KG`。因此在 bundle 建好后对 `prices` 做 `replace` 会被一致性检查拒绝。
3. `_china_prices(time_profile, *, diesel_price_by_city, vehicle_parameters) -> PriceParameters` 位于 `china81.py:1192-1197`，在 `:1227-1254` 构造价格对象并于 `:1252` 写入常量。通用 `load_china81_bundle:325-342` 与 DEPOTSEARCH 专用 `run_problem_hgs_private_technical.py:884-890 _load_v3_suite_bundle` 都最终走这个构造点；专用调用在 `:1130-1134`。
4. DEPOTSEARCH 路由为 `run_problem_hgs_private_technical.py:682-690 _build_context` → `:741-752` → `:1448-1469 _build_saved_suite_context` → `:884-1244 _load_v3_suite_bundle` → `:1291-1445 _suite_context_from_built`。碳价必须沿这条所有权链显式传递，不能在搜索函数里另读全局变量。
5. 当前 CLI 已有 `--seed`、`--iterations`、`--max-runtime-seconds`、`--stagnation-patience`（`private runner:2824-2832`）和 `--charge-timing-policy {asap,cost_min,cost_plus_carbon,carbon_min}`（`:2930-2934`），但没有 `--carbon-price-cny-per-kg`、`--run-kind` 或 `--formal-campaign-manifest`。真正搜索调用在 `:3513-3536`。
6. 骨架 v1 把 `asap/cost_min` 称作“价无关”并据此算成 `20+70=90`，与代码不符；P18 又已经确定 `asap/cost_min/cost_plus_carbon` 三条线，不再重问 policy 集合：
   - 总成本在冻结的 `cost.py:233` 用 `prices.carbon_price`；
   - 企业账在 `profit.py:195` 用同一值；
   - 充电核在 `charge_timing.py:444-457,500-516,640-649,689-736` 用它；
   - route proposal 在 `kernel_proposals.py:937,1110,1173` 用它；
   - Problem-HGS 评价在 `algorithms/problem_hgs/evaluation.py:1444` 用它。

   所以即使充电时机 policy 是 `asap` 或 `cost_min`，只要重新跑完整搜索，碳价仍会改变路线／车型选择与总目标。K3 只能在 A/C 两种跨价布局中选择；90 只在 C 且 `|G|=7` 时成立，不再由“基线价无关”推出。
7. 当前验收在 `private runner:3773-3781` 固定写 `TECHNICAL_TRIAL_COMPLETE/FAILED`；metadata 在 `:3791-3815` 明写 `instance_formally_selected=False`，`raw_runs.csv:4030-4068` 已保存 seed、成本、客户数、需求量，但没有碳价、policy 的独立列。`best_solution.json:4088-4106` 已保存成本分解、完整执行解、accounting、provenance。
8. P102 当前规则是：旧 `1.223/1.472/2.27` 与“0–2.5 七点”不是用户冻结值；每个正式碳价点必须同时有原文页码来源、当前最终算法／实例的新测量定位和用户 S5。W2.2 的 manifest 是唯一正式数值入口。

#### B. 积木清单

| 积木 | 版本／签名 | 许可证 | 路径／URL | 人类作品证据与本项角色 |
|---|---|---|---|---|
| Python `dataclasses` | Python 3.12；`replace(obj, **changes)`、`@dataclass(frozen=True)` | PSF-2.0 | https://docs.python.org/3.12/library/dataclasses.html | Python 核心团队；只做不可变配置传递 |
| jq | 1.8.1；`jq -e/-r/-c` | MIT | https://github.com/jqlang/jq/releases/tag/jq-1.8.1 | jqlang 人类维护项目；本机 `/opt/homebrew/bin/jq` 已有，只从已验证 manifest 机械取字段，不决定参数 |
| 项目 China81 权威构造 | 当前基线；`_china_prices(...) -> PriceParameters`、`China81Bundle` | PROJECT_DOMAIN（existing） | `solver/src/setp_solver/china81.py:213-287,1192-1260` | 已有项目输入真值；本项只把原先常量参数化，不新造定价算法 |
| 正式 manifest loader | W2.2 后；`load_formal_campaign(path: Path, *, repo: Path) -> FormalCampaign` | PROJECT_ADAPTER | `solver/src/setp_solver/formal_campaign.py` | 只验证用户冻结 JSON 与运行身份，不生成价格点 |
| 现有验收框架 | `assess_run(...) -> RunAcceptance`、`finalize_five_file_package(...)` | PROJECT_DOMAIN（existing） | `solver/scripts/experiment_acceptance.py:51-180` | 当前仓已有且 W0.3 已证 run-kind 可参数化；本项不重写验收 |
| Chen et al. (2023) | Table 12/13：0–1.0 每 0.1；0–2.5 每 0.5 CNY/kg | Elsevier/TAVERNE 阅读许可 | https://doi.org/10.1016/j.eswa.2023.120979 | Chen、Zhang、Van Woensel 等；`Expert Systems with Applications` 233, 120979；PDF 文件页 12–13／论文页 11–12 |
| Liao, Liu & Fu (2019) | 0.05/0.25/1.25/5 CNY/kg | CC BY 4.0 | https://doi.org/10.3390/ijerph16173120 | 同行评议 IJERPH 16(17), 3120；PDF 页 15、19–22 |
| Shen, Tao & Wang (2018) | 0.015/0.025/0.035 CNY/kg | CC BY 4.0 | https://doi.org/10.3390/ijerph15092025 | 同行评议 IJERPH 15(9), 2025；PDF 页 16 Table 11 |
| Wilson & Stone (2026) | 63/127/226/385 USD/tCO2e；只作区间来源 | CC BY | https://doi.org/10.1371/journal.pcsy.0000092 | PLOS Complex Systems 3(2), e0000092；PDF 页 15–16；换算前必须冻结汇率日期 |

#### C. 拼装步骤

1. 在 `solver/src/setp_solver/china81.py:213-247` 的 `China81Bundle`，于 `model_config` 后新增 `carbon_price_cny_per_kg: float = CHINA81_CARBON_PRICE_CNY_PER_KG`。它表示构造该 bundle 时实际采用的主碳价；`carbon_price_low` 仍保留现有低情景常量。
2. 在 `China81Bundle.__post_init__:249-287`，新增“`carbon_price_cny_per_kg` 必须 finite 且 ≥0”的项目真值校验；把 `expected_core["carbon_price"]` 从全局常量改为 `float(self.carbon_price_cny_per_kg)`。其余柴油因子和 low 值不动。
3. 在 `china81.py:1192-1197 _china_prices`，增加 keyword-only 参数 `carbon_price_cny_per_kg: float = CHINA81_CARBON_PRICE_CNY_PER_KG`；把 `:1252 carbon_price=常量` 改成 `carbon_price=float(carbon_price_cny_per_kg)`。函数不选择网格、不读 CLI。
4. 在 `load_china81_bundle:325-342` 增同名 keyword-only 参数，并在其 `_china_prices` 调用与 `China81Bundle(...)` 构造中传同一值；所有旧调用因默认值保持现状语义。
5. 在 `run_problem_hgs_private_technical.py:884-890 _load_v3_suite_bundle`、`:1291-1301 _suite_context_from_built`、`:1448-1455 _build_saved_suite_context`、`:682-690 _build_context` 各增加同名 keyword-only 参数；在 `:1130-1134` 调 `_china_prices` 以及构造 `China81Bundle` 时传同一值。不得在 `run_integrated_problem_hgs` 或 evaluator 内另设 override。

   同时把 `_load_v3_suite_bundle:1170-1193` 与 `_suite_context_from_built:1373-1388` 的 `bundle.source_paths` 改成**只列本次运行真正读取的 regular files**，不得留下 `suite/instance/road_matrices` 目录占位。DEPOTSEARCH exact 集合为：package `instance_catalog.csv/fleet_caps.csv/facilities.csv/artifact_hashes.json`，存在时的 `station_parameter_assignments.csv`；instance `nodes.csv/orders.csv/source_mapping.csv/matrix_reference.json/shift_contract.json/enterprise_assignment.csv/artifact_hashes.json`；resolved matrix root 下 `cv` 与 `ev` 各三份 `road_distance_m.csv/road_duration_s.csv/road_sum_v2d_m3_s2.csv`；实际采用的 `vehicle_cost_contract.json` 或 fallback `vehicle_costs.csv`；`resolve_calendar_path(runtime_root)` 返回的日历；以及 `report_root/health_witness_routes.csv`。key 用稳定用途名，value 统一为 repo-relative file path。未实际读取的 optional 文件不列，实际读取却缺失即 loader 先失败；authority 目录仍由 `static_input_authority/road_matrix_authority/runtime_parameter_authority` 保存，只作人读 provenance，不进入 file-set hash。
6. 在 `private runner:2824-3015 main` 新增：
   - `--carbon-price-cny-per-kg`，`type=float`，默认 `None`；
   - `--carbon-point-id`，`type=str`，默认 `None`；只在 F1 formal 使用，必须与 manifest 中唯一 `f1_run_cells` member 的 point/policy/profile/price 四元组逐位一致；
   - `--run-kind {technical,formal}`，默认 `technical`；
   - `--formal-campaign-manifest`，`type=Path`，默认 `None`；
   - `--search-configuration-profile`，`type=str`，默认 `None`，formal HGS 必须是 manifest mapping 的 exact key。

   technical 时 price `None` 映射旧常量；formal 时 manifest/profile 必须存在，CLI price、seed、instance 先预检；F1 还必须用 `--carbon-point-id` 在 `f1_run_cells` 中唯一找到同 policy/profile 的 cell，并断言对应 grid value 与 CLI price exact 相同，不能从输出路径猜 point。随后把 profile mapping 的 hash 作为 `expected_search_configuration_sha256` 传进 common runner；由 common runner 在 builder 返回后且搜索开始前与 actual exact compare。runtime engine identity 只写 provenance，不参与这个相等比较。
7. 在 `private runner:3057-3105`，先以 `repo=repo` 加载 W2.2 manifest，再确定唯一 `effective_carbon_price_cny_per_kg`。在调 `_build_context` 前就把现 `:3106` 的初始 `RUNNING metadata.json` 前移并原子持久化，此时先写 `run_kind`、`formal_campaign_sha256`、configuration profile、code-source SHA、manifest expected private-input SHA 和 `actual_private_input_sha256=null`，使 context loader 异常也能进正确 formal failure 收口。然后把 price 传给 `_build_context`；返回后、构造 evaluator/builder 前，把 `bundle.source_paths.values()` 交 `compute_file_set_identity(repo, ...)`，要求 actual map/SHA 与 manifest 的 `private_input_files/private_input_sha256` 逐位相等，通过后再原子更新同一 RUNNING metadata 的 actual map/SHA。任一路径为目录、缺失或 hash 不同都写 formal failure 五件套，且 `run_integrated_problem_hgs/algorithm.run` 0 次。最终 metadata、`raw_runs.csv` 各新增 `carbon_price_cny_per_kg`、`carbon_point_id`、`f1_run_cell_profile`、`charge_timing_policy`、`formal_campaign_sha256`、`run_kind`。
8. 在 private runner 新增纯选择 helper `_private_run_verdicts(run_kind) -> tuple[success_verdict, failure_verdict]`：technical 返回 `TECHNICAL_TRIAL_COMPLETE/TECHNICAL_TRIAL_FAILED`，formal 返回 `FORMAL_PRIVATE_RUN_COMPLETE/FORMAL_PRIVATE_RUN_FAILED`。`private runner:3773-3781` 的正常 `assess_run` 与 `_write_failure_package:416-482` 都必须调同一 helper；后者从已落盘 RUNNING metadata 读 `run_kind`，raw row、`assess_run`、decision/report 标题和正文都用对应 failure verdict，不再硬编码“技术试跑”。不改客户、需求、可行性和 protected-hash 条件；formal 异常包仍五件齐全且进程 nonzero。
   同时在现有 `stop_and_record:3451-3489` 只补**停止原因候选记账**，不改原来的 OR 停止时刻。formal 返回后计算 `total_algorithm_wall_seconds = result.accounting.initialization_wall_seconds + result.accounting.run_wall_seconds`；只有 `result.iterations == manifest_budget.iterations` 且该总墙钟 `<= manifest_budget.safety_wall_seconds` 才规范化为 `ITERATION_BUDGET_REACHED`、`termination_ok=true`。任何总墙钟超限（包括 iteration 与 wall 在同次 callback 命中）都让 wall 优先，规范化为 `CENSORED_SAFETY_WALL`、写完整失败五件套、`accepted=false`、exit 2。technical 保持原 `STOPPED_BY_CALLER` 兼容口径，不能把 safety wall 冒充正式预算完成。
9. 在 `_build_context` 返回后的 `private runner:3158-3166`，顺序固定，禁止 enterprise slice 与 formal flip 互相覆盖：① 保存 joint `source_bundle` 及 `source_package_formal_search_allowed=False`；② 用这份 source joint 做 commit/instance/seed/price/profile/code/input 静态预检；③ 通过后用该文件现有 `replace` 创建 `runtime_joint=replace(source_bundle, formal_search_allowed=True)`，并令当前 bundle/context 指向 runtime joint；④ 若有 `--enterprise-id`，此时才对 **runtime_joint** 调 W1.3a adapter，并一次性把 `bundle/initial/pi0/context` 改成单 depot child（child 因从 runtime joint replace 而保持 `formal_search_allowed=True`）；⑤ 若有 `--pi0-manifest`，保持 runtime joint 双 depot，只把同一外冻 Pi0 mapping/identity 接入 context；⑥ 最后才造 evaluator/builder。不得写成未导入的 `dataclasses.replace`，不得原地改 sealed package，也不得在 slice 后把 bundle 覆盖回 joint。private runner 从 manifest 取 profile hash并传给 common runner 的 `expected_search_configuration_sha256`；不符时 common runner 必须在 `algorithm.run` 前退出，且不得写 formal success。`:3791-3815` 读最终 runtime bundle，metadata 同时保存 source=false/runtime=true；测试分别断言 standalone 为单 depot runtime true、joint 为双 depot runtime true、原 source 仍 false，且 `context.bundle is bundle`。
10. 在 `private runner:4030-4068`，`pi0_externally_frozen` 改读 context；F1 应为 false。新增 `cv_used/ev_used`、`total_emissions_kg`、`total_charging_kwh`，只从 `best_evaluation.prepared_solution` 与已有 breakdown 读取；同一 raw/metadata 还要逐项复制 W1.2 provenance 的 `route_engine_runtime_sha256/route_stage_runtime_sha256/mechanism_stage_runtime_sha256`，nullable mechanism 用空值表示，不让聚合器再导入搜索对象反推。
11. 用户冻结 `carbon_price_grid` 与 exact `f1_run_cells` 后，只按 cells×seeds 展开。下面是可直接执行的**单 leaf 模板**；操作者只设置三项选择变量 `POLICY/POINT_ID/SEED`，其余全由 Homebrew `jq 1.8.1` 从已验证 manifest 取值，任何非 member 立即 nonzero，不把 `<manifest...>` 当 shell 重定向：

   ```bash
   set -euo pipefail
   CAMPAIGN=solver/config/formal_campaign_20260818.json
   INSTANCE=cn-jjj-50c-01-DEPOTSEARCH-d996f755bd
   POLICY="${POLICY:?set POLICY to one manifest f1 cell policy}"
   POINT_ID="${POINT_ID:?set POINT_ID to the same manifest cell point}"
   SEED="${SEED:?set SEED to one manifest seed}"
   CAMPAIGN_ID="$(jq -er '.campaign_id' "$CAMPAIGN")"
   jq -e --argjson seed "$SEED" '((.enabled_campaigns|index("f1"))!=null) and ((.seeds|index($seed))!=null)' "$CAMPAIGN" >/dev/null
   CELL="$(jq -ce --arg p "$POLICY" --arg q "$POINT_ID" '[.f1_run_cells[]|select(.policy==$p and .carbon_point_id==$q)]|if length==1 then .[0] else error("cell") end' "$CAMPAIGN")"
   PROFILE="$(jq -er '.profile' <<<"$CELL")"
   PRICE="$(jq -er --arg q "$POINT_ID" '[.carbon_price_grid[]|select(.point_id==$q)]|if length==1 then .[0].value_cny_per_kg else error("price") end' "$CAMPAIGN")"
   ITERATIONS="$(jq -er --arg p "$PROFILE" '.private_budget_by_profile[$p].iterations' "$CAMPAIGN")"
   RESTART_PATIENCE="$(jq -er --arg p "$PROFILE" '.private_budget_by_profile[$p].restart_patience' "$CAMPAIGN")"
   SAFETY_WALL="$(jq -er --arg p "$PROFILE" '.private_budget_by_profile[$p].safety_wall_seconds' "$CAMPAIGN")"
   BOUNDARY_ENABLED="$(jq -r '.truth_guided_route_boundary' "$CAMPAIGN")"
   BOUNDARY_LIMIT="$(jq -r '.route_truth_candidate_limit // empty' "$CAMPAIGN")"
   BOUNDARY_ARGS=()
   if [[ "$BOUNDARY_ENABLED" == true ]]; then
     test -n "$BOUNDARY_LIMIT"
     BOUNDARY_ARGS=(--truth-guided-route-boundary --route-truth-candidate-limit "$BOUNDARY_LIMIT")
   else
     test -z "$BOUNDARY_LIMIT"
   fi
   OUT="solver/reports/f1_${CAMPAIGN_ID}/$POLICY/$POINT_ID/seed_$SEED"

   PYTHONPATH=solver/src:models/src:third_party/setp_hgs_kernel \
     build/python_envs/setp-independent-hgs/bin/python solver/scripts/run_problem_hgs_private_technical.py \
     "$OUT" --instance-id "$INSTANCE" --seed "$SEED" \
     --iterations "$ITERATIONS" --stagnation-patience "$RESTART_PATIENCE" \
     --max-runtime-seconds "$SAFETY_WALL" \
     --population-mode copied_hgs_defaults \
     --proposal-mode system --proposal-config combat --trajectory off \
     "${BOUNDARY_ARGS[@]}" \
     --charge-timing-policy "$POLICY" \
     --carbon-price-cny-per-kg "$PRICE" \
     --carbon-point-id "$POINT_ID" \
     --search-configuration-profile "$PROFILE" \
     --run-kind formal --formal-campaign-manifest "$CAMPAIGN"
   ```

   manifest loader 必须在展开前验证：boundary=false 时 limit 必须 null 且 `BOUNDARY_ARGS` 为空；boundary=true 时 limit 必须为冻结正整数并精确展开两个 flag。不得以 private runner 的 OFF default 代替 manifest。
12. 每个命令只写一个从不存在的叶目录。批次 exact 集合为 `{(cell.policy, cell.carbon_point_id, seed) | cell in f1_run_cells, seed in seeds}`，包数精确为 `len(f1_run_cells) * len(seeds)`；不筛结果、不重试换种子。失败包原地保留并使批次失败。
13. 在 S5 计算 `code_source_sha256` **之前**新增共享脚本 `solver/scripts/aggregate_formal_campaign.py`（`declared_identity=PROJECT_ADAPTER`，`code_role=ORCHESTRATION`，≤250 行）；这是 F1/F3 唯一 campaign 聚合器，不进入搜索进程。公开接口固定：

   ```python
   @dataclass(frozen=True)
   class AggregateRequest:
       kind: Literal["f1", "f3"]
       root: Path
       campaign_manifest: Path
       output: Path

   def aggregate_formal_campaign(request: AggregateRequest, *, repo: Path) -> int: ...
   ```

   CLI 只有 `f1|f3 --root PATH --formal-campaign-manifest PATH --output PATH`。实现只调 W2.2 `load_formal_campaign(path, repo=repo)` 与 W0.3 已改为“recorded map 与 actual map exact 相等”的 `validate_five_file_package(..., require_accepted=False)`、`file_sha256`、`assess_run`、`finalize_five_file_package`、`package_exit_code`；不得 import solver、重评路线、补跑、选 winner、算显著性或新造验收阈值。
14. `f1` 的 expected key set exact 为 `f1_run_cells × seeds`，leaf path 固定 `<root>/<policy>/<carbon_point_id>/seed_<seed>`；`f3` exact 为 `f3_arms × seeds`，leaf path 固定 `<root>/runs/<arm>/seed_<seed>`，正式 F3 时 loader 要求 `f3_arms == ("rolling", "mechanical")`。聚合器先用目录名构造 actual leaf set，missing/extra 均写失败 inventory；每个存在 leaf 均调用五件套 validator。hash 损坏、child `accepted=false`、少客户、少需求都保留一行，绝不从汇总删除。每个 row 的 `artifact_hashes_sha256` 固定为 child `artifact_hashes.json` 文件字节 SHA；不是另造 package hash。

   `f1 raw_runs.csv` 列固定为：`kind,policy,carbon_point_id,profile,seed,package_path,package_present,package_hash_valid,artifact_hashes_sha256,child_accepted,termination_status,best_feasible,customers_served,customers_total,demand_served,demand_total,best_cost,total_emissions_kg,cv_used,ev_used,total_charging_kwh,search_configuration_sha256,route_engine_runtime_sha256,route_stage_runtime_sha256,mechanism_stage_runtime_sha256,validation_error`。字段只从 child metadata/decision/单行 raw 复制。

   `f3 raw_runs.csv` 列固定为：`kind,arm,seed,package_path,package_present,package_hash_valid,artifact_hashes_sha256,child_accepted,termination_status,final_feasible,customers_served,customers_total,demand_served,demand_total,final_cost,total_emissions_kg,total_wall_seconds,history_all_preserved,stage_trace_sha256,initial_visible_solution_sha256,search_configuration_sha256,control_source_id,validation_error`。字段只从 child metadata/decision 复制；stage trace 仍在 child 包，不压成伪单阶段。
15. aggregate metadata 固定写 `formal_campaign_sha256/code_source_sha256/expected_child_count/present_child_count/hash_valid_child_count/accepted_child_count`。分别用 verdict `FORMAL_F1_CAMPAIGN_COMPLETE/FAILED` 与 `FORMAL_F3_CAMPAIGN_COMPLETE/FAILED` 调 `assess_run`；只有 key set exact、全部 hash valid、全部 child accepted、逐行满客户满需求时 complete。`decision.json` 只记完整性计数和失败 key，不作策略胜负／效应判断；report 是确定性 inventory。F1 调用命令固定：

   ```bash
   set -euo pipefail
   CAMPAIGN=solver/config/formal_campaign_20260818.json
   CAMPAIGN_ID="$(jq -er '.campaign_id' "$CAMPAIGN")"
   PYTHONPATH=solver/src:solver/scripts \
     build/python_envs/setp-independent-hgs/bin/python \
     solver/scripts/aggregate_formal_campaign.py f1 \
     --root "solver/reports/f1_${CAMPAIGN_ID}" \
     --formal-campaign-manifest "$CAMPAIGN" \
     --output "solver/reports/f1_${CAMPAIGN_ID}/aggregate"
   ```

   预期 `expected_child_count=len(f1_run_cells)*len(seeds)`，actual key set 与 manifest exact 相等；任何少服务行保持失败，聚合进程按 `package_exit_code` 非零。

#### D. 缺口如实

1. `HALT_USER_KEY_K3`：P18 三条线已定，用户只在以下两种跨价格点布局中选一；施工者不能从“90”倒推：
   - **A：三策略全价格点。** exact cells=`3|G|`，总跑数=`3×|G|×10=30|G|`；若 `|G|=7`，即 `3×7×10=210`。每个价格点都有 `asap/cost_min/cost_plus_carbon` 三条干净同点配对，可逐价画“减排 vs 碳价”。
   - **C：碳感知全价格点＋两基线共同参考点。** exact cells=`|G|+2`，总跑数=`(|G|+2)×10=10|G|+20`；若 `|G|=7`，即 `(7+2)×10=90`。唯一 `g_ref∈G` 必须由用户在 K4 冻结为 exact `point_id`，脚本不得按浮点最近值、默认价或结果挑选。**后果必须随选项一起呈用户：跨臂配对比较只在 `g_ref` 精确成立；图 3 的“减排 vs 碳价”在其他价格点只能报碳感知臂绝对量＋`g_ref` 基线参考线，并如实披露；不能画成每个价点都有基线配对。**
2. `HALT_NO_BRICK_FIXED_ROUTE_CHARGING_ONLY`：旧 B“冻结共同路线／车队，只重排充电时机”当前没有完整标准砖，不列为 K3 可选布局，也不能为凑 90 现场实现。
3. `HALT_USER_KEY_K4`：`|G|`、各点和 `g_ref` exact `point_id` 尚未 S5 冻结；policy list 已由 P18 固定为三项，不属于 K4 待选。
4. `HALT_USER_KEY_K7_PRIVATE_INIT_PROVENANCE`：F1 每次运行读取的封存 witness 带有前两件 EDF 初始化算法的离线派生血统；K7 未冻结前不得冻结 F1 private 初始化身份。K7 不表示 F1 每次现场调用三件，也不阻塞 F5。
5. `HALT_FINAL_GRID`：文献候选已覆盖 0.015–5 CNY/kg；当前实例响应曲线、CO2/CO2e 口径与必要的 USD 汇率日期未冻结前，不能由文献直接拼正式七点。
6. 若需要修改冻结 `cost.py` 才能实现新碳价语义，立即停；本方案只改构造参数。

#### E. 验收

1. 第一轮事实复现 E10（碳价进入完整成本、利润、route proxy 与充电核）：

   ```bash
   rg -n -H 'carbon_price' \
     solver/src/setp_solver/cost.py \
     solver/src/setp_solver/profit.py \
     solver/src/setp_solver/charge_timing.py \
     solver/src/setp_solver/algorithms/problem_hgs/evaluation.py \
     solver/src/setp_solver/algorithms/problem_hgs/kernel_proposals.py
   ```

2. 构造接线：

   ```bash
   PYTHONPATH=solver/src:models/src:third_party/setp_hgs_kernel \
     build/python_envs/setp-independent-hgs/bin/python -m pytest -q \
     solver/tests/test_china81_bundle_20260720.py \
     solver/tests/test_problem_hgs_carbon_price_wiring.py
   ```

   至少断言默认值不漂；0 和 manifest 正值可构造；负值／NaN／inf 被拒；bundle、prices、metadata、raw row 四处精确一致；错 point/policy/profile/price 任一项都在 build 前拒绝。新 wiring 测试再注入一个发生于 RUNNING metadata 落盘后的异常，断言五件齐、`run_kind=formal`、verdict=`FORMAL_PRIVATE_RUN_FAILED`、`accepted=false`、进程 nonzero；另分别让 iteration 先到、safety wall 先到和两者同次命中但总墙钟越界，只有 exact iterations 且总墙钟未越界才接受，后两者必须 `CENSORED_SAFETY_WALL`、accepted=false、exit 2。
3. 单一所有者：

   ```bash
   rg -n 'CHINA81_CARBON_PRICE_CNY_PER_KG|carbon_price_cny_per_kg' \
     solver/src/setp_solver/china81.py \
     solver/scripts/run_problem_hgs_private_technical.py
   ```

   预期常量只作默认，正式值沿 CLI→manifest→context→`_china_prices` 单向传递。
4. 正式包：

   ```bash
   PYTHONPATH=solver/src:models/src:third_party/setp_hgs_kernel \
     build/python_envs/setp-independent-hgs/bin/python - <<'PY'
   import csv, json, pathlib
   from setp_solver.formal_campaign import load_formal_campaign
   repo = pathlib.Path.cwd().resolve()
   campaign = load_formal_campaign(repo / "solver/config/formal_campaign_20260818.json", repo=repo)
   root = repo / f"solver/reports/f1_{campaign.campaign_id}"
   expected = {
       (cell.policy, cell.carbon_point_id, seed)
       for cell in campaign.f1_run_cells
       for seed in campaign.seeds
   }
   paths = list(root.glob("*/*/seed_*/metadata.json"))
   actual = {
       (p.relative_to(root).parts[0], p.relative_to(root).parts[1], int(p.parent.name.removeprefix("seed_")))
       for p in paths
   }
   assert actual == expected and len(paths) == len(expected)
   for p in paths:
       run = p.parent
       meta = json.loads(p.read_text())
       row = next(csv.DictReader((run / "raw_runs.csv").open()))
       assert meta["run_kind"] == "formal"
       assert row["verdict"] == "FORMAL_PRIVATE_RUN_COMPLETE"
       assert int(row["customers_served"]) == int(row["customers_total"])
       assert float(row["demand_served"]) == float(row["demand_total"])
       assert float(row["carbon_price_cny_per_kg"]) == float(meta["carbon_price_cny_per_kg"])
       assert row["carbon_point_id"] == p.relative_to(root).parts[1]
       assert row["charge_timing_policy"] == meta["effective_charge_timing_policy"]
   PY
   ```

   预期无输出；包数必须从 manifest 算，不写死 90。
5. `shasum -a 256` 复核三份 protected files；除 W1.4 另获批准外，预期仍为文件开头三条 hash。
6. `PYTHONPATH=solver/src:solver/scripts build/python_envs/setp-independent-hgs/bin/python -m pytest -q solver/tests/test_aggregate_formal_campaign.py`；覆盖 F1/F3 exact key set、零 child、missing/extra、child hash 损坏、accepted=false、少服务，以及失败行不被过滤。再执行 C.15 命令，预期 aggregate 自身五件齐且 child 行数 exact。

#### F. 净行数预算

- China81 参数化约 `+28/−3`；private runner formal/carbon 接线约 `+75/−10`；共享 F1/F3 聚合器约 `+190/−0` 且必须 ≤250 行；测试约 `+190/−0`。
- 合计约 `+483/−13`；F1 运行数由 K3/K4 精确为 A 的 `30|G|` 或 C 的 `10|G|+20`，在 `|G|=7` 时分别为 210／90。聚合器预算只在本项计一次，W3.3 不重复计。

---

### 工作项 W3.2　F2 单干、联合、企业账与参与约束正式批次

#### A. 现状取证

1. standalone 必须由完整 DEPOTSEARCH bundle 切企业子例，不能筛 joint witness；联合必须加载外部冻结 `resetp.formal_pi0.v1` manifest。对应源码缝已在 W1.3a–d 逐处定位。
2. 当前 private runner 只有 joint technical 路径；W1.3a 才会增加 `--enterprise-id`，W1.3d 才会增加 `--pi0-manifest`。两者必须互斥：单干不施加联合参与约束，联合才消费 Pi0。
3. `calculate_depot_profits(...) -> dict[str, DepotProfitBreakdown]`（`profit.py:68-78`）已有 `cost_total/profit/customers_served/demand_kg/emissions`；当前 `FullEvaluation.depot_profit` 只留利润 float，private runner 尚无 `enterprise_ledger.json`。W1.3b 负责补账本，本批次不重算另一套成本。
4. P28 的单干基准规则是：每企业 10 seeds；在完整服务且可行的行中选 profit 最大的一行冻结为 Pi0。同一行的 `cost_total` 才是 `c(A)/c(B)`；不得从不同 seed 分别摘利润和成本。
5. pyCoopGame `Shapley(game)` 只在求解包完成后读取四行 coalition-value 表；它不参与 route search，也不替换参与约束。因此 K6 必须早于 F2 的 S5a code-source SHA 冻结：manifest 写 `f2_participation_ledger="operational"` 才可沿本节继续；写 `"allocated"` 则停在 W1.3c 的 `HALT_NO_BRICK_ALLOCATED_PARTICIPATION_SEARCH`。`__init__.py` 绕开路径与两方表形状已在 W1.3c 写死。
6. F2 是固定 30 个正式求解样本：ENT_A 10、ENT_B 10、joint fairness 10。Shapley 核算不是第 31 个求解器 run。

#### B. 积木清单

| 积木 | 固定版本／签名 | 许可证 | 路径 | 人类作品证据／角色 |
|---|---|---|---|---|
| W1.3 企业 adapter | `slice_enterprise_problem(...) -> EnterpriseProblemSlice` | PROJECT_ADAPTER | `solver/src/setp_solver/algorithms/problem_hgs/enterprise_adapter.py` | 只做项目身份筛选与既有矩阵／seed 积木拼接 |
| 现有企业账 | `calculate_depot_profits(...)` | PROJECT_DOMAIN（existing） | `solver/src/setp_solver/profit.py:68-266` | 当前统一成本与路线归属事实源 |
| Pi0 parser | `load_pi0_manifest(path)` | PROJECT_ADAPTER | `solver/src/setp_solver/pi0_manifest.py` | 从 mixed runner 原样搬出，不另造 schema |
| pyCoopGame | 0.0.5，commit `72153c7771bc6d910be023e5d72c8922cecaa80f`；`Shapley(game)` | BSD-3-Clause | `third_party/harvested_materials/07_collaboration_profit/pycoopgame` | Fabian Lechtenberg；Applied Energy 377 (2025) 124581 |
| pandas `DataFrame` | 3.0.3；`DataFrame(data, columns=["coalition","value"])` | BSD-3-Clause | https://pypi.org/project/pandas/3.0.3/ | PyData 社区；与 W1.3c `.coop-venv` 同一锁定版本，仅满足 pyCoopGame 表容器合同 |
| jq | 1.8.1；`jq -e/-r/-c` | MIT | https://github.com/jqlang/jq/releases/tag/jq-1.8.1 | jqlang 人类维护项目；复用 W3.1 已有本机 binary，从 manifest 取预算／campaign id |
| 现有五件套验收 | `assess_run/finalize_five_file_package` | PROJECT_DOMAIN（existing） | `solver/scripts/experiment_acceptance.py` | 同 F1，不新造验收框架 |

#### C. 拼装步骤

1. 前置分两段，不得成环：K6 必须在 F2 的 S5a code-source 冻结前决定，并把选择写成 `f2_participation_ledger: "operational"|"allocated"`。只有 `"operational"` 才先一次完成本节 `build_f2_inputs.py` 的 `select` **和** `finalize` 两子命令，再计算 stage1 code map；`"allocated"` 按 `HALT_NO_BRICK_ALLOCATED_PARTICIPATION_SEARCH` 停止，不生成 stage1 formal manifest。W1.2、W1.3a–d 与 standalone 标定通过后，S5a stage1 manifest 只要求 `private/f2/ENT_A`、`private/f2/ENT_B` 的 hash 和 `private_budget_by_profile` rows 非 null；用它跑完 20 个 standalone 并生成 Pi0。随后按 W2.2 C.10 用该 Pi0 做 fairness-on joint technical 标定，用户 S5b 冻结 final manifest 的 `private/f2/joint` hash/budget；最后才跑 10 个 joint。seed/enterprise/Pi0 values 进入 runtime/input identity；fairness 开关/theta 与 independently frozen patience 进入 stable hash，三个 profile不能强称相同。
2. 对每个 enterprise × seed 跑 standalone：

   ```bash
   set -euo pipefail
   CAMPAIGN=solver/config/formal_campaign_20260818_stage1.json
   INSTANCE=cn-jjj-50c-01-DEPOTSEARCH-d996f755bd
   ENTERPRISE="${ENTERPRISE:?set ENT_A or ENT_B}"
   case "$ENTERPRISE" in ENT_A|ENT_B) ;; *) exit 2;; esac
   SEED="${SEED:?set one manifest seed}"
   CAMPAIGN_ID="$(jq -er '.campaign_id' "$CAMPAIGN")"
   PROFILE="private/f2/$ENTERPRISE"
   jq -e --argjson seed "$SEED" '((.enabled_campaigns|index("f2"))!=null) and ((.seeds|index($seed))!=null)' "$CAMPAIGN" >/dev/null
   ITERATIONS="$(jq -er --arg p "$PROFILE" '.private_budget_by_profile[$p].iterations' "$CAMPAIGN")"
   RESTART_PATIENCE="$(jq -er --arg p "$PROFILE" '.private_budget_by_profile[$p].restart_patience' "$CAMPAIGN")"
   SAFETY_WALL="$(jq -er --arg p "$PROFILE" '.private_budget_by_profile[$p].safety_wall_seconds' "$CAMPAIGN")"
   PRICE="$(jq -er '.f2_reference_carbon_price_cny_per_kg' "$CAMPAIGN")"
   POLICY="$(jq -er '.f2_charge_timing_policy' "$CAMPAIGN")"
   BOUNDARY_ENABLED="$(jq -r '.truth_guided_route_boundary' "$CAMPAIGN")"
   BOUNDARY_LIMIT="$(jq -r '.route_truth_candidate_limit // empty' "$CAMPAIGN")"
   BOUNDARY_ARGS=()
   if [[ "$BOUNDARY_ENABLED" == true ]]; then
     test -n "$BOUNDARY_LIMIT"
     BOUNDARY_ARGS=(--truth-guided-route-boundary --route-truth-candidate-limit "$BOUNDARY_LIMIT")
   else
     test -z "$BOUNDARY_LIMIT"
   fi
   OUT="solver/reports/f2_${CAMPAIGN_ID}/standalone/$ENTERPRISE/seed_$SEED"

   PYTHONPATH=solver/src:models/src:third_party/setp_hgs_kernel \
     build/python_envs/setp-independent-hgs/bin/python solver/scripts/run_problem_hgs_private_technical.py \
     "$OUT" --instance-id "$INSTANCE" --enterprise-id "$ENTERPRISE" \
     --seed "$SEED" --iterations "$ITERATIONS" \
     --stagnation-patience "$RESTART_PATIENCE" \
     --max-runtime-seconds "$SAFETY_WALL" \
     --population-mode copied_hgs_defaults \
     --proposal-mode system --proposal-config combat --trajectory off \
     "${BOUNDARY_ARGS[@]}" \
     --charge-timing-policy "$POLICY" \
     --carbon-price-cny-per-kg "$PRICE" \
     --search-configuration-profile "$PROFILE" \
     --run-kind formal --formal-campaign-manifest "$CAMPAIGN"
   ```

   不带 `--pi0-manifest`；metadata 写 `fairness_enabled=false` 和 `enterprise_id`。
3. 新增 `solver/scripts/build_f2_inputs.py`（`declared_identity=PROJECT_DOMAIN`，`code_role=ORCHESTRATION`，≤250 行）。它只：
   - 接受 `select --standalone-root --campaign-manifest --output`；
   - 用现有五件套 validator 校验 exact 20 个预期目录，并要求 ENT_A/ENT_B 各 10 个包全部 `accepted=true`、满服务且各有 `enterprise_ledger.json` 唯一一行；任何一行失败即 `HALT_INCOMPLETE_STANDALONE_10SEED`，不从剩余行缩样本；
   - validator 输出统一为 JSON-like mapping；用可执行 Python `max(rows, key=lambda row: (float(row["profit"]), -int(row["seed"])))` 实现 P28；profit 完全相同以较小 seed 作确定展示键，但保存全部并列行；
   - 输出 `standalone_selection.json`、`pi0_manifest.json`、`coalition_cost_inputs.json`，均含输入包 SHA-256。

   不调用求解器、不重评路线、不因失败换 seed；0 合格即 `HALT_NO_VALID_STANDALONE`。
4. `pi0_manifest.json` 固定：

   ```json
   {
     "schema": "resetp.formal_pi0.v1",
     "instances": {
       "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd": {
         "values": {
           "D_OSM_WAY_1003511503": "<selected ENT_A profit>",
           "D_OSM_WAY_1071205721": "<selected ENT_B profit>"
         },
         "source_id": "f2_${campaign.campaign_id}_standalone_10seed_selection",
         "value_sha256": "<mapping_sha256 exact implementation>",
         "selected_package_sha256_by_enterprise": {
           "ENT_A": "<64-hex selected package SHA-256>",
           "ENT_B": "<64-hex selected package SHA-256>"
         }
       }
     }
   }
   ```

   `values` 是 Pi0 利润；`${campaign.campaign_id}` 表示 `build_f2_inputs.py` 从已验证 manifest dataclass 直接格式化的字段，不是 shell 文本；`selected_package_sha256_by_enterprise` 的 exact 两键记录各自获选 child package SHA，且必须与 `standalone_selection.json` 的获选行逐位相等；`coalition_cost_inputs` 另存同两行的 `cost_total`。
5. 20 包及输入文件通过后，跑 joint seeds 1–10：

   ```bash
   set -euo pipefail
   CAMPAIGN=solver/config/formal_campaign_20260818.json
   CAMPAIGN_ID="$(jq -er '.campaign_id' "$CAMPAIGN")"
   PI0="solver/reports/f2_${CAMPAIGN_ID}/inputs/pi0_manifest.json"
   SEED="${SEED:?set one manifest seed}"
   PROFILE=private/f2/joint
   jq -e --argjson seed "$SEED" '((.enabled_campaigns|index("f2"))!=null) and ((.seeds|index($seed))!=null)' "$CAMPAIGN" >/dev/null
   ITERATIONS="$(jq -er --arg p "$PROFILE" '.private_budget_by_profile[$p].iterations' "$CAMPAIGN")"
   RESTART_PATIENCE="$(jq -er --arg p "$PROFILE" '.private_budget_by_profile[$p].restart_patience' "$CAMPAIGN")"
   SAFETY_WALL="$(jq -er --arg p "$PROFILE" '.private_budget_by_profile[$p].safety_wall_seconds' "$CAMPAIGN")"
   POLICY="$(jq -er '.f2_charge_timing_policy' "$CAMPAIGN")"
   PRICE="$(jq -er '.f2_reference_carbon_price_cny_per_kg' "$CAMPAIGN")"
   BOUNDARY_ENABLED="$(jq -r '.truth_guided_route_boundary' "$CAMPAIGN")"
   BOUNDARY_LIMIT="$(jq -r '.route_truth_candidate_limit // empty' "$CAMPAIGN")"
   BOUNDARY_ARGS=()
   if [[ "$BOUNDARY_ENABLED" == true ]]; then
     test -n "$BOUNDARY_LIMIT"
     BOUNDARY_ARGS=(--truth-guided-route-boundary --route-truth-candidate-limit "$BOUNDARY_LIMIT")
   else
     test -z "$BOUNDARY_LIMIT"
   fi
   OUT="solver/reports/f2_${CAMPAIGN_ID}/joint/seed_$SEED"

   PYTHONPATH=solver/src:models/src:third_party/setp_hgs_kernel \
     build/python_envs/setp-independent-hgs/bin/python solver/scripts/run_problem_hgs_private_technical.py \
     "$OUT" --instance-id cn-jjj-50c-01-DEPOTSEARCH-d996f755bd \
     --pi0-manifest "$PI0" --seed "$SEED" --iterations "$ITERATIONS" \
     --stagnation-patience "$RESTART_PATIENCE" \
     --max-runtime-seconds "$SAFETY_WALL" \
     --population-mode copied_hgs_defaults \
     --proposal-mode system --proposal-config combat --trajectory off \
     "${BOUNDARY_ARGS[@]}" \
     --charge-timing-policy "$POLICY" \
     --carbon-price-cny-per-kg "$PRICE" \
     --search-configuration-profile "$PROFILE" \
     --run-kind formal --formal-campaign-manifest "$CAMPAIGN"
   ```

   final manifest loader 必须先验证 `predecessor_manifest_sha256` 等于 20 个 standalone 所用 stage1 文件 SHA，且 `pi0_manifest_sha256` 等于 `$PI0`。同时读取 predecessor 并要求 `campaign_id`、`code_source_files/code_source_sha256`、`private_input_files/private_input_sha256`、seeds、instance、F2 price/policy、`f2_participation_ledger`、boundary/limit、ENT_A/ENT_B profile hash 与 budget 逐位相同；只允许 `private/f2/joint` 从 null 变为 S5b 冻结值及补入 Pi0/predecessor 字段。任一漂移都拒绝 joint，不能把旧 Pi0 喂给新代码／新输入／新配置。不带 `--enterprise-id`；metadata 必须为 `fairness_enabled=true`、`theta=1.0`、`pi0_externally_frozen=true`，并逐位复制 manifest 的 `f2_participation_ledger`。
6. K6 冻结后，在 **S5a code-source SHA 计算前**与 `select` 一并新增 `build_f2_inputs.py finalize` 子命令；loader 必须读取 `f2_participation_ledger`，不许在聚合器里硬编码 operational。字段为 `"allocated"` 时在任何 formal child 启动前按既有 HALT 退出；字段为 `"operational"` 时，standalone 跑完后只调用已冻结代码，不再改该脚本。函数一开始就在 output 写 RUNNING metadata，并先构造 exact 30-key inventory：`(standalone,ENT_A,1..10)`、`(standalone,ENT_B,1..10)`、`(joint,null,1..10)`；缺目录也保留一行 `package_present=false`，存在目录逐一调用 W0.3 exact-map 版 `validate_five_file_package(path, require_accepted=False)`，捕获缺件／hash 错为该行 `validation_error`，不得裸异常后无 summary。joint eligible 行必须同时满足 `package_present/hash_valid/metadata.acceptance_passed/decision.accepted` 全 true、满客户、满需求、best feasible、`fairness_enabled=true`、`theta=1.0`、Pi0 hash 与 final manifest 逐位一致，并且序列化 `best_solution.evaluation.violations` 中没有 `type == "PROFIT_FAIRNESS"`。**不再对 operational margin 数值二次施加 `>=0` 阈值**；`check.py:40,1255-1257` 的 `FEASIBILITY_TOL=1e-9` 已是唯一 canonical 判定，margin 只照实报告。只在 eligible 中选 `total_cost` 最小，完全相同时取较小 seed。缺任一 seed 包记 `HALT_INCOMPLETE_JOINT_10SEED`；10 行中没有 canonical checker 认可的 joint 行时记 `HALT_NO_PARTICIPATING_JOINT`，不关闭约束救结果。
7. 对 winning joint 断言 `best_solution.evaluation.total_cost == sum(enterprise_ledger[*].cost_total)`，绝对误差 ≤`1e-9`；失败表示账本接线错。
8. 构造四行 `([],0),([ENT_A],c_A),([ENT_B],c_B),([ENT_A,ENT_B],c_AB)`。`c_A/c_B` 来自 winning standalone 同一 ledger 行，`c_AB` 来自 winning joint。同时把 winning joint 两行 ledger 的 `revenue/cost_total/profit` 与 Pi0 映射传给 W1.3c adapter，输出 allocated cost、saving、saving_pct、operational margin 和 allocated margin；验分摊和等于 `c_AB`，但不用 post-hoc allocated margin 重挑 seed。
9. aggregate 五件套的 `metadata.json`、`raw_runs.csv` 与 `decision.json` 都逐位复制 manifest 的 `f2_participation_ledger`；`raw_runs.csv` 固定保留上述 30 行，以 `scope/enterprise_id/seed` 区分，winning 两企业行另有 `operational_participation_margin` 与 `allocated_participation_margin`。`decision.json` 分开记 `operational_participation_satisfied`、`allocated_participation_satisfied`、K6 冻结口径与 Shapley efficiency，不把两套账合并成一个“公平有效”。最后只调用已有验收积木：

   `assess_run(..., success_verdict="FORMAL_F2_CAMPAIGN_COMPLETE", failure_verdict="FORMAL_F2_CAMPAIGN_FAILED") -> finalize_five_file_package(...) -> package_exit_code(...)`。

   complete 条件 exact 为：30 keys 全 present、hash valid、child accepted、满客户满需求；standalone selection/Pi0 hashes 闭合；至少一个由 child canonical checker 判为 feasible 且无 `PROFIT_FAIRNESS` 的 joint winner；winning ledger cost closure；Shapley efficiency 误差 ≤`1e-9`。任何 missing/hash 错/child failure/0 eligible/closure failure 仍写 summary 自身 `metadata.json/raw_runs.csv/decision.json/artifact_hashes.json/report.md`，verdict 为 FAILED 且 nonzero；不得把失败 inventory 缩成较少行，也不得在 finalize 前抛出使五件套缺失的异常。

#### D. 缺口如实

1. `HALT_NO_BRICK`：EDF+completion 若不能在 A 的 3CV+3EV 或 B 的 7CV+7EV 下构造满服务 seed，不能写新装箱／route search。
2. `HALT_USER_KEY_K1`：若 `f` 是企业私有站，数据无 ownership，standalone slice 不可施工。
3. `HALT_INCOMPLETE_STANDALONE_10SEED`：20 个 standalone 中任一包缺失、未接受或未满服务，Pi0 不生成，joint 不开跑；不得缩成“最好若干 seed”。
4. `HALT_INCOMPLETE_JOINT_10SEED`：任一 joint seed 包缺失，aggregate 停；已有失败包保留，不补跑更有利 seed。
5. `HALT_NO_PARTICIPATING_JOINT`：10 个 joint 行均违反 Pi≥Pi0，结果保留；不得调退役 ALNS、降 theta 或重挑 Pi0。
6. pyCoopGame `nucleolus` 依 Pyomo+外部 GLPK/GAMS，当前无固定依赖链；若用户要求，`HALT_NO_BRICK`。
7. `HALT_USER_KEY_K6_PARTICIPATION_LEDGER`：K6 未冻结时 joint formal 不开跑。K6-B 选 allocated-profit 时触发 `HALT_NO_BRICK_ALLOCATED_PARTICIPATION_SEARCH`，不用聚合后挑 seed 代替搜索内约束。

#### E. 验收

1. 20 个 standalone 后：

   ```bash
   set -euo pipefail
   CAMPAIGN=solver/config/formal_campaign_20260818_stage1.json
   CAMPAIGN_ID="$(jq -er '.campaign_id' "$CAMPAIGN")"
   PYTHONPATH=solver/src:solver/scripts python3 solver/scripts/build_f2_inputs.py select \
     --standalone-root "solver/reports/f2_${CAMPAIGN_ID}/standalone" \
     --campaign-manifest "$CAMPAIGN" \
     --output "solver/reports/f2_${CAMPAIGN_ID}/inputs"
   ```

   预期 `selected_counts={"ENT_A":1,"ENT_B":1}`、`validated_run_count=20`。
2. 30 包后：

   ```bash
   set -euo pipefail
   CAMPAIGN=solver/config/formal_campaign_20260818.json
   CAMPAIGN_ID="$(jq -er '.campaign_id' "$CAMPAIGN")"
   PYTHONPATH=solver/src:solver/scripts \
     .coop-venv/bin/python solver/scripts/build_f2_inputs.py finalize \
     --standalone-inputs "solver/reports/f2_${CAMPAIGN_ID}/inputs" \
     --joint-root "solver/reports/f2_${CAMPAIGN_ID}/joint" \
     --campaign-manifest "$CAMPAIGN" \
     --output "solver/reports/f2_${CAMPAIGN_ID}/summary"
   ```

   预期 `validated_run_count=30`、`joint_selected_count=1`、`shapley_efficiency_error<=1e-9`、verdict=`FORMAL_F2_CAMPAIGN_COMPLETE`，并显式输出两套 margin；`metadata.json/raw_runs.csv/decision.json` 的 `f2_participation_ledger` 必须与 manifest 逐位相等，不能用测试写死 operational。manifest 为 allocated 时预期在启动任何 formal child 前 nonzero HALT。另分别删除一个 child、篡改一个 `artifact_hashes.json`、让 10 个 joint 的 canonical child 全部含 `PROFIT_FAIRNESS` violation；三例都必须产生 verdict=`FORMAL_F2_CAMPAIGN_FAILED` 的 summary 五件套、exit nonzero，`raw_runs.csv` 仍 exact 30-key inventory且缺失／失败行未被过滤。另加 margin=`-5e-10` 但 child 无 `PROFIT_FAIRNESS`、best feasible/accepted 的 fixture，聚合器不得用 exact zero 二次排除。
3. `PYTHONPATH=solver/src:solver/scripts .coop-venv/bin/python -m pytest -q solver/tests/test_coalition_accounting.py solver/tests/test_f2_batch_inputs.py`；固定 `100/120/180` 例预期 allocation `80/100`，并断言未导入 `setp_solver.algorithms.problem_hgs`／`setp_hgs_kernel`。`solver/src` 只用于 stdlib-only 的 `mapping_identity/pi0_manifest/formal_campaign`，不等于允许加载搜索包。
4. `! rg -n 'search\.fairness|from \.fairness|run_alns_wouda' solver/src/setp_solver/algorithms/problem_hgs solver/scripts/build_f2_inputs.py solver/scripts/run_problem_hgs_private_technical.py solver/src/setp_solver/search/__init__.py`；预期新 F2 生产路径 0 调用。另对 `formal_runner.py` 只断言旧 E3/E6/fairness import 消失，不把其余 baseline ALNS 路径误判为失败。
5. 扫描 30 个 `raw_runs.csv`，断言客户数与需求量逐行满服务，且恰 10 行 `fairness_enabled=True`；同 10 行的 `fairness_theta=1.0` 与 `pi0_sha256` 必须和 joint metadata 一致。

#### F. 净行数预算

- 编排脚本约 `+190/−0`，必须 ≤250 行；private runner 少量接线约 `+35/−5`；测试约 `+100/−0`。
- 合计约 `+325/−5`；W1.3a–d 预算不重复计入。

---

### 工作项 W3.3　F3 滚动重优化 vs 机械在线正式批次

#### A. 现状取证

1. `solver/scripts/run_problem_hgs_dynamic_technical.py:198-235` 是单一切点接线检查：只有 `--trigger-second/iterations/runtime/stagnation/proposal-mode`，没有 seed 参数；`:326-340`、`:511` 使用固定 `SEED`，`decision.json:540-555` 明说不回答 dynamic effect。它不是 F3 主入口。
2. 真正多阶段入口是 `solver/scripts/run_problem_hgs_dynamic_disclosure_scout.py`：
   - CLI `:666-718` 有 `--stream-seed`、`--search-seed`、trigger policy、stage/total runtime、`--mechanical-insertion-control`；
   - `:777-789` 用 `build_o1_stream/build_o1_batches` 生成披露流；
   - `:797-827` 先求或加载只含初始可见客户的共同方案；
   - `:841-850` 后对每个 disclosure batch 循环；
   - `:1233-1259` 每阶段写 active/completed 客户、iterations、cost、history hash；
   - `:1387-1472` metadata/raw rows 保存 stream/search seed 和每阶段状态；
   - `:1474-1494` verdict 仍是 technical scout。
3. 一个 F3 样本包内部包含“初始可见订单求解 + 所有披露阶段”，不是一个切点，也不能把每个 stage 当独立统计样本。
4. `_solve_initial_visible_plan:231-325` 内 route engine 和 population 在 `:270,273` 使用固定 `SEED`，未接 `args.search_seed`。后续阶段才在 `:966-975` 用 CLI search seed。这会让 metadata 声称的 seed 与初始方案实际 RNG 不一致。
5. `_run_integrated_stage:108-146` 直接调用 `build_integrated_private_hgs(...).algorithm.run(stop)`，手工回填 accounting，绕开 `runner.py:279-524 run_integrated_problem_hgs`。因此当前多阶段线不取得 W1.2 的 effective bundle/provenance/hash。
   同时 `dynamic_disclosure_scout.py:971-975` 把 `stream_role=f"dynamic_stage_{stage_index}_route"` 传入 route engine，而 `kernel_proposals.py:203-239` 把 stream role 编入 source id。W1.2 的 stable payload 若直接保留该字符串，同一 `dynamic/f3/rolling` profile 会每阶段变 hash。
6. 当前 `--stage-stop-mode=stagnation` 在 `:1169-1177` 只把外部 stop 设为 total wall clock；没有 `dynamic_iterations_per_decision` 精确停止。`:719-722` 又把 stage 和 total runtime 自设为 ≤1200 秒，与 P79 “预算来自本算法本算例收敛曲线”冲突。
7. mechanical arm 在 `:1120-1155` 不运行 HGS；它从 `build_dynamic_warm_start_population` 的 complete feasible candidates 中取最低完整成本，身份写 `mechanical-regret2-insertion-control`。底层 `repair.py:242-356 regret2_repair` 是有行为的算法代码，Git 只显示 2026-08-10 项目提交，当前没有可核上游代码出处。
8. 检索到 GraphHopper jsprit 2.0.0 的 `Insertion.regretFast()`/regret-k（Apache-2.0，人类维护约 1.8k stars），但它是 Java 全套 rich-VRP 搜索器，不能直接消费本项目 Duty/SOC/充电证书，也不能用 ≤250 行 adapter 保持现有完整评价语义。
9. 当前默认 instance 是旧 `cn-prd-50c-01-V2-LOCATIONS`（`:669-672`）；F3 必须显式传选定 `cn-jjj-50c-01-DEPOTSEARCH-d996f755bd`。`_build_context` 已有该 loader 路由，不新写第二个 loader。
10. `baselines/china_e3_e7/e7_o1_replanning_20260801/policy.py:48-58 demand_threshold_kg(instance)` 当前返回 `2.0 * fmean(全部 customer demand)`，scout `:779-782` 在 `hybrid_two_mean_orders_or_30_minutes` 下直接调用。这个“2×全客户平均需求”是未获批的 AI 自造参数；P74-3 已废止 500 kg，并要求从本算例的**动态订单尺寸分布**开跑前重定。它不能因 policy 名称含 `two_mean_orders` 就自动进入 formal。
11. 旧动态包虽有 `charging_times_json`，却没有 cut 前证书、source solution 或 `in_progress` 字段，故“cut 时在途且仍有未来充电”的精确次数目前是 `UNKNOWN`，不是 0。证据命令见 E.3。

#### B. 积木清单

| 积木 | 版本／签名 | 许可证 | 路径／URL | 人类作品证据／角色 |
|---|---|---|---|---|
| 统一 Problem-HGS runner | W1.2 后；`run_integrated_problem_hgs(...) -> ProblemHGSRunResult` | PyVRP-derived kernel MIT + PROJECT_ADAPTER | `runner.py:279-524` | 底层 PyVRP v0.12.2 commit `ea0c421...`；替换 scout 的重复 HGS 调度 |
| 固定迭代停止 | `MaxIterations(value)(ProblemHGSSearchState)->bool` | PROJECT_ADAPTER | `algorithms/problem_hgs/stopping.py:10-21` | 已有 typed stop，语义来自用户标定预算 |
| 上游组合停止 | PyVRP 0.12.2；`MultipleCriteria(criteria)` | MIT | `third_party/setp_hgs_kernel/setp_hgs_kernel/stop/MultipleCriteria.py:4-16` | PyVRP 人类上游；只作 `any(crit(arg))`，可拼项目 `MaxIterations` 与 scout 已有 absolute-deadline predicate |
| 已有 absolute deadline predicate | 当前 HEAD；`lambda _state, deadline=total_deadline: perf_counter() >= deadline` | PROJECT_DOMAIN（existing） | `run_problem_hgs_dynamic_disclosure_scout.py:1171-1180` | 当前 runner 已用的全进程 monotonic deadline；本项只把同一 predicate 传入 common runner／population callback，不重写计时器 |
| 动态披露流 | `build_o1_stream(...)`、`build_o1_batches(...)` | PROJECT_DOMAIN（existing） | `baselines/china_e3_e7/e7_o1_replanning_20260801` | 当前项目 Git 作者 Leixishu Zhou；不是上游声明，formal trigger 仍须用户冻结 |
| 动态 cut/证书 | `cut_certificate_at_trigger`、`cut_dynamic_certificate_at_trigger` | PROJECT_DOMAIN（existing） | `search/dynamic_multitrip_schedule.py` | 已有项目执行真值；W1.1 缺砖未闭合时不可正式使用 |
| jsprit regret-k 候选 | 2.0.0；`Insertion.regretFast()` | Apache-2.0 | https://github.com/graphhopper/jsprit | GraphHopper 人类团队、约 1.8k stars；仅检索候选，当前接口不合格 |
| RoutingBlocks 检索候选 | 当前已检官方 API；`BestInsertionOperator`／可定制 move selector | MIT | https://github.com/tumBAIS/RoutingBlocks | 有 insertion primitives，但已检 API 无现成 regret/regret-2 算子；“第 n 个 insertion move”不等于跨未插客户比较第一／第二可行位置 |
| N-Wouda ALNS 检索候选 | 当前已检官方仓库与 CVRP example | MIT | https://github.com/N-Wouda/ALNS | 框架要求项目自供 destroy/repair；官方 CVRP 例用 greedy repair，未提供可直接接入的 regret-2 |
| 当前 `regret2_repair` | `regret2_repair(...)` | `UNKNOWN` 上游身份 | `problem_hgs/repair.py:242-356` | Git 提交者不能证明代码出处；formal mechanical arm 的阻断点 |
| 现有五件套验收 | `assess_run/finalize_five_file_package/package_exit_code` | PROJECT_DOMAIN（existing） | `solver/scripts/experiment_acceptance.py:51-213` | 现有 private/public runner 已用；动态正常和异常收口统一复用 |
| jq | 1.8.1；`jq -e/-r/-c` | MIT | https://github.com/jqlang/jq/releases/tag/jq-1.8.1 | jqlang 人类维护项目；只展开已冻结 F3 manifest 字段 |

#### C. 拼装步骤

**K5 前置取证（观测，不是算法）**：在最终拟用的 10 个正式流种子及各自冻结的共同 initial 上，每次调用既有 cut 后、任何 rolling／mechanical 优化前，追加一行只读观测：

`seed, stage, trigger_second, route_id, in_progress, future_charge_count, earliest_future_charge_second`

探针只读取 cut 返回的证书、cut 前 source solution 与其 `ChargingAction`；不得生成候选、改变锁定／释放规则、修改状态、参与排序、进入 stable configuration hash 或成为任一 arm 的控制输入。结果单独落盘并带 stream/initial SHA。先按该表统计目标状态在 10 流中的精确出现次数，再呈 K5；现有旧包缺字段的事实由 E.3 证明，不能拿旧包补 0。探针代码只属于观测编排，不能被登记成新算法组件。

1. F3 主入口固定为 `run_problem_hgs_dynamic_disclosure_scout.py`；`run_problem_hgs_dynamic_technical.py` 保留单切点技术测试身份，不扩成第二个正式 runner。
2. 删除 `dynamic_disclosure_scout.py:108-146` 中 HGS 分支的手工 `build_integrated_private_hgs/algorithm.run/accounting`。机械分支需要的结果 carrier 改名 `MechanicalControlResult`，只服务 `:1120-1155`。
3. 在非 mechanical 分支 `:1156-1209`，改调 `run_integrated_problem_hgs`；参数逐项为：
   - `initial_candidates=tuple(built.candidates)`；
   - `initial_evaluations=tuple(built.evaluations)`；
   - `initial_population_identity=FrozenPopulationIdentity(source_id=f"dynamic-stage-{stage_index}-population", value_sha256=population_sha256(tuple(built.candidates)))`；
   - evaluator/policy/parameters/route_engine 均用该 stage 已构造对象；
   - `initialization_full_evaluation_count=built.full_evaluation_count`；
   - `initialization_wall_seconds=built.wall_seconds`；
   - mechanism/cross-depot/multi-trip/type-exchange 等继续逐项取该 stage 当前已构造的显式参数／固定构造值，并传给 common runner；其中 technical route-only 必须精确传 `include_mechanism_refinement=not args.route_only_dynamic_ablation`，formal 构造值固定为经标定 profile 对应的 true，禁止临时 CLI override。W2.2 manifest 只保存 expected stable hash，并不存在“W1.2 effective manifest 字段”；builder 返回的 `EffectiveExecutionBundle` 才是 actual 值，common runner 用 expected hash fail-closed，scout 不再复制一套默认或谎称从不存在的字段读取。
   - formal initial/rolling stage 从各自 profile 取 hash，传 `expected_search_configuration_sha256`；technical 传 None。比较点由 common runner 保证在 `algorithm.run` 之前。
   - 在 `:971-975` 把 formal rolling route engine 的 stable `stream_role` 从 `f"dynamic_stage_{stage_index}_route"` 改为常量 `"dynamic_rolling_route"`；initial 用常量 `"dynamic_initial_route"`。`stage_index`、active customers、trigger 继续写进每阶段 runtime identity/provenance，不进 stable source/config payload。这只改身份字符串的分类，不改候选生成或 RNG。
4. 在 CLI `:666-718` 新增 `--stage-iterations`、`--initial-iterations`、`--stage-stagnation-patience`、`--initial-stagnation-patience`、`--time-threshold-seconds`、`--demand-threshold-kg`、`--run-kind {technical,formal}`、`--formal-campaign-manifest`、`--search-configuration-profile`。formal HGS 时两类预算、两类 restart patience 和 profile 必须由 manifest exact match；`--time-threshold-seconds` 必须逐位等于 manifest `f3_time_threshold_seconds=1800` 且与 `policy.py:41 INTERVAL_SECONDS` 相等，`--demand-threshold-kg` 必须逐位等于 `f3_demand_threshold_kg`，`build_o1_batches(..., threshold_kg=...)` 只吃该显式值；`f3_demand_threshold_source` 同步进入 metadata/provenance。formal 路径不得再调用 `demand_threshold_kg(full_bundle.instance)`。删除 `stage-stop-mode` 与 `stage-runtime-seconds` 在 formal 分支的控制作用，technical 兼容分支可暂留。formal 的 `total_runtime_seconds` 只验 finite positive 且 exact 等于 manifest `dynamic_safety_wall_seconds`，删除源码 :719-722 的 `<=1200` 自造上限；technical 可保留旧 ceiling。initial 与 rolling stage 分别使用稳定 profile，seed/active customers/trigger 只进 runtime identity。
   `_build_context` 返回后保留 `source_bundle` 及 `source_package_formal_search_allowed=False`。先要求 `"f3" in manifest.enabled_campaigns`，并把 `source_bundle.source_paths.values()` 交 W2.2 `compute_file_set_identity(repo, ...)`，要求 actual map/SHA exact 等于 `private_input_files/private_input_sha256`；任一文件变字节时 initial/rolling/mechanical 都 0 次。只有 manifest/code/input/seed/trigger/profile 静态预检全部通过，才用现有 stdlib `replace` 创建 `runtime_bundle=replace(source_bundle, formal_search_allowed=True)`，并把 initial `base_context` replace 为该 bundle；以后每个 `_subset_bundle` 必须从 runtime base 派生并断言 `formal_search_allowed is True`，不得从 source bundle 重建回 false。technical 继续用 source false。metadata 同时写 source=false/runtime=true 与 actual private-input SHA；evaluator、initial 与所有 rolling stage 只读 runtime bundle，不改 sealed 文件。
5. formal 子命令通过 manifest 后立刻设置唯一 `total_deadline = perf_counter() + manifest.dynamic_safety_wall_seconds`。进入 initial 或每个 rolling stage 的 population build 前先核 `perf_counter() < total_deadline`，并把当前 scout :1171-1180 **同一 absolute predicate** `deadline_reached = lambda _state=None, deadline=total_deadline: perf_counter() >= deadline` 传给已有 population/repair `stop_requested`；命中即写 `CENSORED_SAFETY_WALL`，不得启动 HGS。紧贴 common-runner 调用构造 `MultipleCriteria([MaxIterations(stage_budget), deadline_reached])`，initial 对应 `initial_budget`；不用上游 `MaxRuntime(remaining)`，因为它从第一次回调才起表、会把 pre-callback 时间漏出全局墙钟。`MultipleCriteria` 虽把参数注解成 float，函数体只原样传参，项目两个 callable 可直接消费同一 state。common runner 再把这个 composite 传给内部 builder/repair 和外层循环。

   返回后先核总墙钟：只在 `perf_counter() <= total_deadline` 且 `result.iterations == budget` 时记 `ITERATION_BUDGET_REACHED`；哪怕 iteration 与 deadline 在同次 callback 命中，只要返回时越墙，仍规范化为 `CENSORED_SAFETY_WALL`、失败五件套、nonzero。这样 safety wall 永远是安全绳，不会因 criterion 顺序冒充跑满预算。

   mechanical 分支也在 population build 前核同一 absolute deadline，并把现有 `stop_requested=lambda: perf_counter() >= total_deadline` 传给已有 build/repair callback；候选完成后再核 deadline。该分支本来不宣称 iteration budget，只有在 deadline 前正常得到完整结果才可完成。旧 CLI 默认 `stage_runtime_seconds=30` 和 `total_runtime_seconds=600` 均不得静默参与 formal。
6. 把 private runner `:3451-3489 stop_and_record` 的记录形态原样搬为本脚本的小型编排 helper，CSV 增 `stage,cycle,wall_seconds,best_total_cost`。它只观察现有 `ProblemHGSSearchState`，不平滑、不判收敛；W2.2 用它冻结 initial 和 per-decision 两类预算。
7. 给 `_solve_initial_visible_plan:231-325` 增 `search_seed:int`、`iterations:int`；把内部三处 `SEED` 改为参数，并改走步骤 3 的统一 runner。`main:797-809` 传 `args.search_seed/args.initial_iterations`。
8. 把当前单命令拆成两个子命令而不改算法：
   - `prepare-initial`：只执行 `build_o1_stream`、`_solve_initial_visible_plan`，写 `initial_visible_solution.json`、diagnostic、`initial_visible_manifest.json` 和 artifact hashes 后退出。manifest 固定保存 formal campaign path/SHA、instance、stream seed、search seed、trigger policy、`f3_time_threshold_seconds/f3_demand_threshold_kg/f3_demand_threshold_source`、排序 visible-customer ids 及其 SHA、`dynamic/f3/initial` configuration hash、solution 相对路径/SHA；
   - `run`：必须同时带 `--source-initial-visible-solution` 与 `--source-initial-manifest`，不再内部重求 initial。搜索任何 rolling/mechanical stage 前，exact compare 两文件 SHA，以及 source manifest 的 campaign SHA、instance、两 seed、trigger policy、三项 threshold 字段、visible-customer ids/hash、initial profile/hash 与当前 CLI/manifest/重建披露流；任一不符 fail-before-stage。

   这样同一 seed 的 rolling/mechanical 精确读同一初始解。正式数据是 20 个 arm 包；另有 10 个只作共同输入的 prepare 调用，必须在机时账中披露为总共 30 次 solver 进程。
9. `prepare-initial` 命令：

   ```bash
   set -euo pipefail
   CAMPAIGN=solver/config/formal_campaign_20260818.json
   SEED="${SEED:?set one manifest seed}"
   CAMPAIGN_ID="$(jq -er '.campaign_id' "$CAMPAIGN")"
   jq -e --argjson seed "$SEED" '((.enabled_campaigns|index("f3"))!=null) and ((.seeds|index($seed))!=null)' "$CAMPAIGN" >/dev/null
   TRIGGER_POLICY="$(jq -er '.f3_trigger_policy' "$CAMPAIGN")"
   TIME_THRESHOLD="$(jq -er '.f3_time_threshold_seconds' "$CAMPAIGN")"
   DEMAND_THRESHOLD="$(jq -er '.f3_demand_threshold_kg' "$CAMPAIGN")"
   INITIAL_ITERATIONS="$(jq -er '.dynamic_initial_iterations' "$CAMPAIGN")"
   INITIAL_PATIENCE="$(jq -er '.dynamic_initial_restart_patience' "$CAMPAIGN")"
   SAFETY_WALL="$(jq -er '.dynamic_safety_wall_seconds' "$CAMPAIGN")"
   OUT="solver/reports/f3_${CAMPAIGN_ID}/inputs/seed_$SEED"
   PYTHONPATH=solver/src:models/src:third_party/setp_hgs_kernel \
     build/python_envs/setp-independent-hgs/bin/python solver/scripts/run_problem_hgs_dynamic_disclosure_scout.py \
     prepare-initial "$OUT" \
     --instance-id cn-jjj-50c-01-DEPOTSEARCH-d996f755bd \
     --stream-seed "$SEED" --search-seed "$SEED" \
     --trigger-policy "$TRIGGER_POLICY" \
     --time-threshold-seconds "$TIME_THRESHOLD" \
     --demand-threshold-kg "$DEMAND_THRESHOLD" \
     --initial-iterations "$INITIAL_ITERATIONS" \
     --initial-stagnation-patience "$INITIAL_PATIENCE" \
     --total-runtime-seconds "$SAFETY_WALL" \
     --search-configuration-profile dynamic/f3/initial \
     --run-kind formal --formal-campaign-manifest "$CAMPAIGN"
   ```
10. 每个 arm × seed 命令：

   ```bash
   set -euo pipefail
   CAMPAIGN=solver/config/formal_campaign_20260818.json
   ARM="${ARM:?set rolling or mechanical}"
   case "$ARM" in rolling|mechanical) ;; *) exit 2;; esac
   SEED="${SEED:?set one manifest seed}"
   CAMPAIGN_ID="$(jq -er '.campaign_id' "$CAMPAIGN")"
   jq -e --argjson seed "$SEED" --arg arm "$ARM" '((.enabled_campaigns|index("f3"))!=null) and ((.seeds|index($seed))!=null) and ((.f3_arms|index($arm))!=null)' "$CAMPAIGN" >/dev/null
   TRIGGER_POLICY="$(jq -er '.f3_trigger_policy' "$CAMPAIGN")"
   TIME_THRESHOLD="$(jq -er '.f3_time_threshold_seconds' "$CAMPAIGN")"
   DEMAND_THRESHOLD="$(jq -er '.f3_demand_threshold_kg' "$CAMPAIGN")"
   STAGE_ITERATIONS="$(jq -er '.dynamic_iterations_per_decision' "$CAMPAIGN")"
   STAGE_PATIENCE="$(jq -er '.dynamic_restart_patience_per_decision' "$CAMPAIGN")"
   SAFETY_WALL="$(jq -er '.dynamic_safety_wall_seconds' "$CAMPAIGN")"
   IDLE_MODE="$(jq -er '.f3_idle_ev_readiness_mode' "$CAMPAIGN")"
   SOURCE="solver/reports/f3_${CAMPAIGN_ID}/inputs/seed_$SEED/initial_visible_solution.json"
   SOURCE_MANIFEST="solver/reports/f3_${CAMPAIGN_ID}/inputs/seed_$SEED/initial_visible_manifest.json"
   OUT="solver/reports/f3_${CAMPAIGN_ID}/runs/$ARM/seed_$SEED"
   if [[ "$ARM" == rolling ]]; then
     EXTRA_ARGS=(
       --stage-stagnation-patience "$STAGE_PATIENCE"
       --search-configuration-profile dynamic/f3/rolling
     )
   else
     EXTRA_ARGS=(--mechanical-insertion-control)
   fi

   PYTHONPATH=solver/src:models/src:third_party/setp_hgs_kernel \
     build/python_envs/setp-independent-hgs/bin/python solver/scripts/run_problem_hgs_dynamic_disclosure_scout.py \
     run "$OUT" \
     --instance-id cn-jjj-50c-01-DEPOTSEARCH-d996f755bd \
     --stream-seed "$SEED" --search-seed "$SEED" \
     --trigger-policy "$TRIGGER_POLICY" \
     --time-threshold-seconds "$TIME_THRESHOLD" \
     --demand-threshold-kg "$DEMAND_THRESHOLD" \
     --source-initial-visible-solution "$SOURCE" \
     --source-initial-manifest "$SOURCE_MANIFEST" \
     --stage-iterations "$STAGE_ITERATIONS" \
     --total-runtime-seconds "$SAFETY_WALL" \
     --idle-ev-readiness-mode "$IDLE_MODE" \
     "${EXTRA_ARGS[@]}" \
     --run-kind formal --formal-campaign-manifest "$CAMPAIGN"
   ```

   rolling 必须 exact match `dynamic/f3/rolling` 的稳定配置 hash；mechanical 不冒充 HGS，因此只传控制 flag，并在 provenance 记其独立 source/commit。
11. 在任何 initial/stage build 前先写 RUNNING metadata，含 `run_kind`、formal manifest/hash、code-source SHA、source initial manifest/hash、initial solution hash、arm，以及 `f3_time_threshold_seconds/f3_demand_threshold_kg/f3_demand_threshold_source`。新增 `_dynamic_run_verdicts(run_kind)`：technical 映射原 `TECHNICAL_SCOUT_COMPLETE/FAILED`，formal 映射 `FORMAL_DYNAMIC_RUN_COMPLETE/FORMAL_DYNAMIC_RUN_FAILED`。`:1375-1559` 正常收口与 `_write_failure:577-635` 都使用该映射，并统一调现有 `assess_run`、`finalize_five_file_package`、`package_exit_code`；五件套必须有 `metadata.acceptance_passed`与 `decision.accepted`，formal 异常不得再写 `TECHNICAL_SCOUT_FAILED`。每阶段必须继续保存 history hash、active/completed 客户与需求量；失败进程 nonzero。

   在当前 `dynamic_disclosure_scout.py:1298-1301` 删除 final 收口的 `DutyFullEvaluator(replace(final_context, fairness_enabled=True))` 强开路径；F3 合同没有外冻 Pi0，也不研究企业参与约束，正式终态必须继续使用 fairness-off 的 `final_result.best_evaluation`。否则 runtime bundle 已为 formal true 而 neutral Pi0 identity 仍 `externally_frozen=False`，`DutyEvaluationContext.__post_init__:204-210` 会在搜索后抛错。不得为绕开该错伪造 Pi0 或把 formal flag 降回 false。

   正常 finalize 前，`raw_runs.csv` 已 durable 后用现有 `file_sha256` 计算 `stage_trace_sha256=file_sha256(raw_runs.csv)`，并在 child metadata 写确定性终态摘要：`final_feasible=bool(final_result.best_evaluation.feasible)`、`customers_served=len(set(completed_ids))`、`customers_total=len(_active_customer_ids(full_bundle))`、`demand_served=completed_demand`、`demand_total=total_demand`、`final_cost=adjusted_total_cost`、`total_emissions_kg=adjusted_total_emissions`、`total_wall_seconds=actual_total_wall_seconds`、`history_all_preserved=all(row["history_preserved"] is True for row in stage_rows)`、`stage_trace_sha256`、`initial_visible_solution_sha256`、对应 HGS `search_configuration_sha256` 或 mechanical `control_source_id`。这些值全部来自本函数现有变量／stage rows，不重放路线；aggregate 只复制这份 child summary。失败 child 缺终态值时保留空值和 validation error，不伪造 0。
12. 复用 W3.1 C.13-C.15 的唯一 `aggregate_formal_campaign.py f3`，不得在 dynamic runner 再写第二套聚合逻辑。它按 manifest exact `("rolling","mechanical") × seeds` 校验 20 个 leaf，同 seed 的 `initial_visible_solution_sha256` 必须一致；逐行复制最终全日成本、排放、总 wall、stage trace SHA 与 history preservation，失败／成功行全保留。固定命令：

   ```bash
   set -euo pipefail
   CAMPAIGN=solver/config/formal_campaign_20260818.json
   CAMPAIGN_ID="$(jq -er '.campaign_id' "$CAMPAIGN")"
   PYTHONPATH=solver/src:solver/scripts \
     build/python_envs/setp-independent-hgs/bin/python \
     solver/scripts/aggregate_formal_campaign.py f3 \
     --root "solver/reports/f3_${CAMPAIGN_ID}" \
     --formal-campaign-manifest "$CAMPAIGN" \
     --output "solver/reports/f3_${CAMPAIGN_ID}/aggregate"
   ```

   预期 `expected_child_count=20`、`accepted_child_count=20` 才写 `FORMAL_F3_CAMPAIGN_COMPLETE`；任一 source-initial 不配对、history false、少服务或 child 失败均写 aggregate failure 并 nonzero，不筛行、不改科学判据。

#### D. 缺口如实

1. `HALT_NO_BRICK_W1_1`：先看 K5 前置观测表。若 10 流精确计数全为 0，K5 只需确认沿用当前 committed 语义并披露“正式候选流未触发该状态”；若任一行 `in_progress=true` 且 `future_charge_count>0`，用户只在两案中选择：A＝**批准一个 PROJECT_DOMAIN 状态转移组件**，按 W1.1 的锁定／SOC 三例施工；B＝缓办 F3。未按 A 前不得把它降格成 adapter 或临时 boolean。
2. `HALT_NO_BRICK_MECHANICAL_PROVENANCE`：当前 regret-2 只能追到项目提交；jsprit、RoutingBlocks、N-Wouda ALNS 均未提供可直接接 ReSETP Duty/SOC 的现成 regret-2。K5 只给两案：A＝**用户授权项目依据文献实现（指定论文页码＋公式＋伪代码，性质测试锁定第一/第二可行位置、单一可行位置、无可行位置、确定性 tie-break）**；B＝不授权，F3 暂停。A 是用户对 `HALT_NO_BRICK` 的显式解锁，身份为 PROJECT_DOMAIN 行为组件；不得改写成“直接采用人类开源 regret-2”。
3. `HALT_USER_KEY_K5` 不再重问 trigger policy 家族：P10 已定“30 分钟或累计需求量先到者触发”，时间字段固定 `f3_time_threshold_seconds=1800`。K5 只冻结以下五组：
   - **需求阈值与来源**：候选 A＝按 P74-3 示例，从最终冻结的 10 条动态流计算全部动态订单的平均单量，取 `k=2`，把计算所得精确 kg、10 流数据 SHA、公式与“k=2 是项目标定而非文献值”一并呈用户；这与当前“2×全客户平均需求”不是同一数据口径，后者须明确作废。候选 B＝不接受 A，暂停 F3，待补另一项能给出精确 kg、原始数据行与开跑前推导式的候选。500 kg 已由 P74-3 废止，不得复活；任何候选都不得看两臂结果后再选。
   - **idle-EV readiness**：P34 已定其进入最终算法并在“不充／何时／充多少／去哪里”候选中内生选择，K5 只冻结最终 A1 潜在池与候选组件的精确 source/config identity；当前技术 CLI 的 `none|observed_max_single_order` 不能冒充新的“启用／停用”选择。
   - **预算**：冻结 `dynamic_initial_iterations`、`dynamic_iterations_per_decision`、两类 restart patience 与总 safety wall；只取 W2.2 对 exact initial/rolling profile 的同机收敛曲线，不抄旧 30/600/1200。
   - **mechanical 血统**：只在本节第 2 条 A/B 中选择。
   - **W1.1 语义**：只按本节第 1 条的观测结果选择，不在未观测前预写分类规则。

   上述任一字段没有精确值／source 时，manifest 保持 null，施工者不得补默认；旧 metadata 中两个 `formally_selected=False` 也不得自行翻成 true。
4. 若共享 initial 在任一 seed 对当前可见客户不满服务，该 seed 失败；不得让两臂各自另找更好 initial。

#### E. 验收

1. 第一轮事实复现 E11（F3 是 multi-stage disclosure；stream/search seed 分开）：

   ```bash
   rg -n 'for stage_index|stream_seed|search_seed|mechanical_insertion_control|_run_integrated_stage' \
     solver/scripts/run_problem_hgs_dynamic_disclosure_scout.py
   ```

2. 第一轮事实复现 E12（当前 regret-2 来源只能追到项目提交）：

   ```bash
   git log --follow --diff-filter=A --format='%H|%an|%aI' -- \
     solver/src/setp_solver/algorithms/problem_hgs/repair.py | tail -n 1
   rg -n 'def regret2_repair|mechanical-regret2' \
     solver/src/setp_solver/algorithms/problem_hgs/repair.py \
     solver/scripts/run_problem_hgs_dynamic_disclosure_scout.py
   ```

   这条命令与 B 表中的 RoutingBlocks／ALNS 检索证明的是**当前仓内与已检索范围**的状态，不是“全网不存在 regret-2”。

3. K5 前置探针的旧包缺字段证据；它证明精确次数为 `UNKNOWN`，不把未知写成 0：

   ```bash
   python3 -c 'import csv,pathlib; p=pathlib.Path("solver/reports/probe_all_mechanisms_20260818/dynamic_paired_seed11_w1"); cols=set(next(csv.reader((p/"per_reveal_events.csv").open()))); state_cols=sorted(c for c in cols if any(t in c for t in ("in_progress","certificate","pre_trigger","source_solution"))); state_files=sorted(x.name for x in p.iterdir() if x.is_file() and any(t in x.name for t in ("certificate","pre_trigger","stage_solution","source_solution"))); print("charging_times_json_present=", "charging_times_json" in cols, sep=""); print("pre_cut_state_columns=",state_cols,sep=""); print("pre_cut_state_files=",state_files,sep=""); print("exact_count=UNKNOWN"); assert "charging_times_json" in cols and not state_cols and not state_files'
   ```

   当前已复现输出应为 `charging_times_json_present=True`、两个空列表与 `exact_count=UNKNOWN`。新探针另断言 exact 10 stream seeds、每行七字段齐、同一 `(seed,stage,route_id)` 唯一，并证明删掉探针写出后两臂的输入、候选顺序、RNG 与终态逐位不变。

4. 定向测试：

   ```bash
   PYTHONPATH=solver/src:models/src:third_party/setp_hgs_kernel \
     build/python_envs/setp-independent-hgs/bin/python -m pytest -q \
     solver/tests/test_problem_hgs_dynamic_disclosure_runner.py \
     solver/tests/test_dynamic_multitrip_schedule.py
   ```

   至少覆盖：initial seed 穿透、每阶段 exact iteration、旧 30/600 默认不约束 formal、manifest safety wall 大于 1200 仍能过 parser 且 exact 接入、safety wall 失败、两臂共同 initial hash、未来充电 W1.1 三例、formal manifest 错配；断言 source bundle 仍 false，而 initial/每个 subset evaluator 的 runtime bundle 都 true 且 metadata 两值一致；改任一 private input 文件一字节时 initial/stage 0 次。formal 全流程收口还要断言没有构造 `fairness_enabled=True` evaluator、neutral Pi0 不触发外冻校验，最终五件套正常落盘。专门让 inner rolling stage 的 absolute deadline 在 `MaxIterations` 前命中，断言它及时返回且写 `CENSORED_SAFETY_WALL`、accepted=false、exit 2；再让两条件同次命中但返回时越墙，仍必须 wall failure。另各做 wrong search seed、wrong initial profile hash、wrong campaign SHA 的 source-initial 拒绝例，并断言 stage runner 0 次调用。两个不同 `stage_index` 必须得到同一 `dynamic_rolling_route` stable source/config hash，但 runtime identity 不同；technical route-only 例还必须证明 `include_mechanism_refinement=false` 到达 builder；注入 rolling search 异常后断言 formal 失败五件套为 `FORMAL_DYNAMIC_RUN_FAILED`、`accepted=false`、exit nonzero。
5. `! rg -n 'build_integrated_private_hgs|_run_integrated_stage|random_seed=SEED|demand_threshold_kg\(full_bundle\.instance\)' solver/scripts/run_problem_hgs_dynamic_disclosure_scout.py`；预期四类旧旁路／默认阈值均为 0。
6. 包数与配对：

   ```bash
   set -euo pipefail
   CAMPAIGN=solver/config/formal_campaign_20260818.json
   export CAMPAIGN_ID="$(jq -er '.campaign_id' "$CAMPAIGN")"
   python3 - <<'PY'
   import json, os, pathlib
   root = pathlib.Path(f"solver/reports/f3_{os.environ['CAMPAIGN_ID']}")
   inputs = list(root.glob("inputs/seed_*/initial_visible_solution.json"))
   runs = list(root.glob("runs/*/seed_*/metadata.json"))
   assert len(inputs) == 10 and len(runs) == 20
   for seed in range(1, 11):
       hashes = {
           json.loads((root / f"runs/{arm}/seed_{seed}/metadata.json").read_text())[
               "initial_visible_solution_sha256"
           ]
           for arm in ("rolling", "mechanical")
       }
       assert len(hashes) == 1
   PY
   ```

7. 每个 `raw_runs.csv` 每阶段断言 `history_preserved=True`、`completed_customers=total_active_customers`；最终另断言全天客户和需求量均完整。预期 20 包全满足，否则 aggregate 失败。
8. provenance 断言 prepare 的配置 hash 等于 manifest `dynamic/f3/initial`，rolling 每个 stage 等于 `dynamic/f3/rolling`；各 stage 的 runtime engine SHA 如实不同且均为 64 位。mechanical 明确 `search_configuration_sha256=null`、`control_source_id` 非空，不能冒充 HGS；三项 F3 threshold 字段与 manifest 逐位相等。
9. 执行 C.12 固定聚合命令；预期 aggregate `raw_runs.csv` exact 20 行、每 seed 两臂且 initial hash 相同，五件套 hash 可复算。删除一个 child、增加一个额外 seed 或篡改一个 child artifact 时，预期 `FORMAL_F3_CAMPAIGN_FAILED`、进程 nonzero，已有 20-key inventory 不被静默缩样。

#### F. 净行数预算

- K5 前置只读观测写出约 `+35/−0`，对应字段／不干预性质测试约 `+25/−0`；这部分可以在 W1.1 语义未解时单独施工，但不得进入 arm 控制。
- K5 之后删除重复 HGS 调度并接 common runner 约 `+55/−55`；CLI/subcommands/正式身份约 `+95/−10`；其余测试约 `+115/−0`。共享 aggregate 脚本及其测试已计入 W3.1，本项不重复计。
- 全项合计仍约 `+325/−65`；W1.1 未解前只允许前置观测的 `+60/−0`，正式两臂施工保持 `+0/−0`。W1.1 的 PROJECT_DOMAIN 状态转移组件预算只在 W1.1 F 栏计算，不在这里重复。

---

### 工作项 W3.4　F5 公开 28 题 × 10 seeds × 两臂正式批次

#### A. 现状取证

1. 唯一 clean-ruler 入口为 `solver/scripts/run_public_v2_28_clean_ruler.py`。`INSTANCES` 在 `:64-68` 生成 PR11A–PR24B 共 28 题；`ARMS=("independent","frozen_pyvrp")` 在 `:69`。正确总单元数是 `28×10×2=560`，不是“560 再乘两臂”。
2. independent worker Python 固定在 `:54-63`；底层是仓内 `setp_hgs_kernel`，其 README 固定 PyVRP v0.12.2 commit `ea0c4211819edac6fd920413ad7508cc9ad56e0e`。frozen Python 是 `/opt/anaconda3/bin/python3.13`，本轮只读内省的 distribution version 为 PyVRP 0.12.2。
3. `_worker_main:907-1084` 按 arm 分派；`:916-950` 保存 seed/预算/组件，`:927-940` 明写 private Duty 组件全关；`:983-1015` 保存服务量并做 raw-precision audit。`_run_dir:1087-1088` 已把 seed 纳入叶目录。
4. `_worker_command:1091-1138` 已能把 instance/arm/seed/runtime/no-improvement/run-kind 逐项传给隔离 Python；无需新写 subprocess scheduler。
5. `_batch_main:1385-1499` 每次只跑一个 seed、严格串行 56 个 unit；这个粒度可复用为“一 seed 一批”，避免自造跨夜续跑器。它最后调用 `_pair_summary(output,args.seed)` 生成 28 个同 seed 配对行。
6. CLI `:1574-1604`：worker 支持任意 `--seed` 和 `--run-kind`；batch 只有一个 `--seed`，默认 11；batch 的 runtime/no-improvement 是一对全局值。`main:1608-1615` 又把 formal batch 写死 seed 11 和 runtime≤1200，均不是当前 10-seed/S5 合同。
7. W0.3 已定位 probe/formal verdict 混用；F5 必须在其修复后跑。现有 formal batch verdict `FORMAL_CANDIDATE_BATCH_COMPLETE` 属 seed-batch 包，可保留。
8. 当前 batch 没有 formal manifest，也不能按 `instance×arm` 读取各自标定预算；直接跑会把 56 个不同规模单元强压成同一 1200/5000，不符合 P79。

#### B. 积木清单

| 积木 | 固定版本／签名 | 许可证 | 路径／URL | 人类作品证据／角色 |
|---|---|---|---|---|
| PyVRP HGS | 0.12.2，commit `ea0c4211819edac6fd920413ad7508cc9ad56e0e` | MIT | https://github.com/PyVRP/PyVRP/tree/v0.12.2 | Wouda、Lan、Kool 等公开项目；论文／GitHub 明确作者 |
| 仓内 independent kernel | 同上游身份，W0.2 后 manifest 固定 | MIT + project patch classification | `third_party/setp_hgs_kernel` | README/UPSTREAM_COMMIT/许可证；W0.2 未决 patch 不得隐去 |
| frozen mother arm | PyVRP 0.12.2 | MIT | `/opt/anaconda3/lib/python3.13/site-packages/pyvrp` | 本轮 `importlib.metadata.version("pyvrp")==0.12.2` |
| clean-ruler 编排 | `_worker_command`、`_batch_main`、`_pair_summary` | PROJECT_DOMAIN（existing），`code_role=ORCHESTRATION` | `run_public_v2_28_clean_ruler.py` | 当前项目 Git 版本；本项只扩 seed/manifest 输入，不造搜索 |
| 正式 manifest loader | W2.2 `load_formal_campaign`；模块只依赖 stdlib | PROJECT_ADAPTER | `solver/src/setp_solver/formal_campaign.py` | 用户冻结预算的唯一读取器；可按文件路径隔离加载，不要求 frozen 环境导入整个 `setp_solver` |
| jq | 1.8.1；`jq -e/-r` | MIT | https://github.com/jqlang/jq/releases/tag/jq-1.8.1 | jqlang 人类维护项目；仅给外围 shell 取 `campaign_id`，worker 仍用隔离 Python loader |
| 五件套验收 | `assess_run/finalize/validate` | PROJECT_DOMAIN（existing） | `experiment_acceptance.py` | 已有统一验收；W0.3 仅修字样 |

#### C. 拼装步骤

1. 在 `run_public_v2_28_clean_ruler.py:1578-1587` worker parser 增 `--formal-campaign-manifest: Path`、默认 `None`；只在 `run_kind=="formal"` 时由程序 fail-closed 要求非空，保证 W2.2 的 probe worker 仍可运行。在 `batch parser:1599-1604` 增 required `--formal-campaign-manifest`，并把 batch 的 `--max-runtime-seconds/--no-improvement` 默认从 1200/5000 改为 `None`；保留单个 `--seed`，不新增嵌套 seed scheduler。
2. 在 `main:1608-1620` 按 command 分支校验：`aggregate` 必须在任何 `seed/max_runtime_seconds/no_improvement` 属性读取前直接分派到 `_aggregate_main(args)`，不得访问它未声明的参数；worker/probe/batch 各自在自己的分支验证。batch 分支删除 `args.seed != 11` 拒绝，改从 manifest 验证 `args.seed in seeds=[1..10]`；旧 runtime≤1200 检查删除；worker/probe 只在值非 None 时做正数校验，formal worker 的 safety wall必须 exact match manifest，formal batch 则要求两项 CLI override 都为 None。
3. `batch` 不再从 CLI 一对全局 `--max-runtime-seconds/--no-improvement` 决定正式预算；两项只要被显式传入就拒绝，避免旧 default 冒充手填值。对每个 `(instance,arm)` 唯一地从 `public_budget_by_instance_and_arm` 读取 `no_improvement_iterations` 与 `safety_wall_seconds`；probe worker 仍用自己的显式参数。
4. 在本 public runner 新增 `_load_formal_campaign_isolated(path)` 编排 helper：先定 `repo = Path(__file__).resolve().parents[2]`，再用 `repo / "solver/src/setp_solver/formal_campaign.py"` 定位 W2.2 的唯一 stdlib-only loader；固定私有模块名 `resetp_formal_campaign_isolated`，依次执行 `spec_from_file_location`、`module_from_spec`、`sys.modules[spec.name] = module`、`spec.loader.exec_module(module)`，再调 `module.load_formal_campaign(path, repo=repo)`。必须先注册 `sys.modules`，否则其中 frozen dataclass 装饰时可能找不到 `cls.__module__`；返回实例仍活着时保留该私有 module 项。不得复制 schema parser，也不得导入 `setp_solver`。`_batch_main` 在启动任何 subprocess 前用该 helper 核 `"f5" in enabled_campaigns`、manifest SHA、Git、code-source map/SHA、seed、完整 56 项 budget map，并对 `INSTANCES` 生成的 28 个 `INSTANCE_ROOT/<id>.vrp` 逐个算字节 SHA，要求 key/value exact 等于 `public_instance_sha256_by_id`；任一差异时 worker subprocess 0 次。`:1401-1422` metadata 把标量预算改为这份 canonical map、public instance map 及各自 SHA-256，保留 `strictly_serial=True`、`run_count=56`。
5. 在 `_batch_main:1425-1437`，对当前 instance/arm 取预算传 `_run_one_subprocess`；`_worker_command:1091-1138` 增传 `--formal-campaign-manifest`。`_worker_main` 搜索前再次调用同一 `_load_formal_campaign_isolated`，核 manifest SHA、Git、seed、instance、arm、该 unit 预算，并在读取/求解前以现有 `_common_source_identity(instance_path)["instance_sha256"]` 与 `public_instance_sha256_by_id[instance]` exact compare。把现有 `_independent_source_identity/_frozen_source_identity` 的 package 文件枚举抽成同文件纯 helper `_runtime_package_identity(arm) -> {files, sha256}`：路径 relative 于实际 imported package root，suffix exact `.py/.pyi/.so/.dylib`、排除 `._*`，总 SHA 用 W2.2 同一 canonical JSON。formal worker 在调用 `_solve_independent/_solve_frozen` **之前**把 actual instance SHA、package files map/总 SHA 与 manifest 对应值逐位比较；不符即失败包且 solve 0 次，符合后才写 `formal_candidate_result=True`，metadata 保存 actual instance/package map/SHA。probe 只记录 actual，供 S5 冻结。不得给 frozen arm 增 `solver/src` 或继承 controller `PYTHONPATH`；现 :1136 的 `environment.pop("PYTHONPATH", None)` 保持，independent arm 也只保留既有 kernel 路径。

   formal worker 的 acceptance 必须同时检查 `_TracingStop.termination_reason == "NO_IMPROVEMENT"` **且**完整 solver runtime 未越墙：independent 读现有 `result.accounting.elapsed_seconds`（本 runner :445-452 的返回字段），frozen 读现有 `result.runtime`（:480-486），统一落为 `runtime_seconds <= manifest safety_wall_seconds`；`stop.rows[-1].elapsed_seconds` 只作 trace 单调性辅证，不能代替 return 后完整时间。任何 `MAX_RUNTIME`、完整 runtime 超墙，或两条件同次 callback 命中／callback 墙内但 finalize 后越墙，均优先规范化为 `CENSORED_SAFETY_WALL`、`accepted=false`、exit 2。probe 保持现有技术验收，不把这个 formal 规则倒灌。另在 `_batch_main` 循环前设 `completed_runs=0`，只在 `_validate_run_package(run_output)` 成功后加 1；`:1476-1495` 异常 decision/metadata/progress 写真实 `completed_runs`、失败 `instance/arm`、`remaining_unstarted=56-completed_runs-1`，不得沿用硬编码 0，也不得把失败 unit 算完成。
6. 把 `_batch_report:1279-1321` 签名改为 `_batch_report(rows, *, seed, budget_map)`；标题／正文从当前 seed 和 manifest 的逐 `instance×arm` budget rows 生成，预算不相同时明确写“各单元使用自身 S5 冻结预算”，不得再出现固定 seed 11 或“两臂相同 1200 秒上限”。`:1518` 调用点传本 batch seed 和 C.4 已验证的 canonical budget map。
7. 目录结构不改 `_run_dir`，外围一 seed 一批：`solver/reports/f5_${CAMPAIGN_ID}/seed_${SEED}/${INSTANCE}_${ARM}_seed${SEED}/`；这些变量都由步骤 8 的 manifest 校验与循环赋值，不允许手填。seed-batch 五件套在 `seed_${SEED}/`，unit 五件套在子目录。
8. 正式命令：

   ```bash
   set -euo pipefail
   CAMPAIGN=solver/config/formal_campaign_20260818.json
   CAMPAIGN_ID="$(jq -er '.campaign_id' "$CAMPAIGN")"
   jq -e '((.enabled_campaigns|index("f5"))!=null) and (.seeds==[1,2,3,4,5,6,7,8,9,10])' "$CAMPAIGN" >/dev/null
   for SEED in 1 2 3 4 5 6 7 8 9 10; do
     OUT="solver/reports/f5_${CAMPAIGN_ID}/seed_$SEED"
     build/python_envs/setp-independent-hgs/bin/python solver/scripts/run_public_v2_28_clean_ruler.py batch \
       --output-dir "$OUT" --seed "$SEED" \
       --formal-campaign-manifest "$CAMPAIGN" \
       --launch-label "f5_${CAMPAIGN_ID}_seed_$SEED"
   done
   ```

   十次调用可分十个夜间窗口，每个 seed-batch 严格串行。沿用现有 fail-fast：任一 worker nonzero 时保存该失败包和已完成前缀，当前 batch 返回 nonzero，外层 `set -e` 不再启动后续 seed；未启动 unit 不得伪造为空包，也不换 seed。
9. 新增现有脚本 `aggregate` 子命令，只接 `--root --formal-campaign-manifest`，输出目录固定为 `Path(args.root) / "aggregate"`，不再让操作者另选第二个汇总路径。它先创建该 output 的 RUNNING metadata，再由 manifest 构造 exact 10 个 seed-batch key 与 560 个 `(seed,instance,arm)` unit key；缺目录也保留 inventory row，存在 child 用 W0.3 exact-map 版 `validate_five_file_package(path, require_accepted=False)` 校 hash/accepted/service，异常写入该 row 的 `validation_error`，不得裸抛后无 aggregate。每个存在的 seed-batch 还必须有五件套外 `DONE`，且固定以 `FORMAL_CANDIDATE_BATCH_COMPLETE` 开头；worker unit leaf 不要求 `DONE`。`raw_runs.csv` 固定为 560 行 unit inventory；只有 560 行全 present/hash-valid/accepted/full-service 时，才逐 seed 调现有 `_pair_summary` 并合并另一个 `pair_summary.csv` exact 280 行。后者也进 artifact hashes；不重算路线，不设胜负门槛。
10. `pair_summary.csv` 每行键为 `instance,seed`，保存两臂成本、客户／需求、raw feasibility、iterations、wall、termination、source identity；`decision.json` 只计 independent/frozen/tie 与完整性。aggregate 唯一收口为 `assess_run(..., success_verdict="FORMAL_PUBLIC_CAMPAIGN_COMPLETE", failure_verdict="FORMAL_PUBLIC_CAMPAIGN_FAILED") -> finalize_five_file_package(...) -> package_exit_code(...)`。complete 必须同时满足 exact 10 batch、560 unit 全 present/hash-valid/accepted/full-service 和 280 pair rows；任一缺失／hash 错／child 失败仍写 aggregate 自身五件套和 exact 560-key inventory，verdict FAILED、exit nonzero，不伪造缺失 unit，也不产成功 `pair_summary.csv`。
11. F5 不传 `--sisr-enabled`；`--disable-vidal-compound` 仍由 worker command 自动传。metadata 必须维持 `sisr=false`、private Duty components 全 false。

#### D. 缺口如实

1. `HALT_PROVENANCE_W0_2`：W0.2 未完成 vendor patch／UNKNOWN 文件分类前，F5 不得宣传“干净 independent kernel”；可留 probe，不启动正式 560。
2. `HALT_USER_KEY_K4`：28×2 各自 no-improvement/safety wall 待 W2.2 和用户 S5；不填旧 5000/1200。
3. 现有 batch 没有 unit resume；本方案用 10 个 seed-batch 降低损失，不写新续跑器。若单 seed 仍跨越不可接受窗口，`HALT_NO_BRICK_BATCH_RESUME`，先找现成 workflow runner。
4. frozen 环境若施工时不再是 0.12.2，立即停；不得用 0.13.4 ILS 冒充 HGS。
5. `HALT_INCOMPLETE_F5`：任一 worker 或 seed-batch nonzero 后，保留已经产生的前缀和失败包，未启动项如实缺失；可以运行 aggregate 生成 FAILED 五件套与 560-key 缺失 inventory，但不得冒充 560-unit／280-pair 成功结果。若用户要求失败后继续剩余 unit，需要先找到标准 workflow/resume 积木，不能在本项发明 scheduler。

#### E. 验收

1. 第一轮事实复现 E13（F5 总数是 `28×10×2=560`）：

   ```bash
   PYTHONPATH=solver/scripts python3 -c 'import run_public_v2_28_clean_ruler as r; n=len(r.INSTANCES)*10*len(r.ARMS); print(len(r.INSTANCES),len(r.ARMS),n); assert (len(r.INSTANCES),len(r.ARMS),n)==(28,2,560)'
   ```

2. parser/manifest/环境：

   ```bash
   PYTHONPATH=solver/src:solver/scripts python3 -m pytest -q \
     solver/tests/test_public_clean_ruler_worker_env.py \
     solver/tests/test_public_clean_ruler_formal_batch.py
   /opt/anaconda3/bin/python3.13 -c \
     'import importlib.metadata as m; assert m.version("pyvrp") == "0.12.2"'
   ```

   覆盖 aggregate parser 能在无 seed/runtime/no-improvement 属性时直接分派的 smoke test、seed 1/10 接受、seed 11 拒绝、batch 省略 budget flags 后逐 unit 读 manifest、batch 手填旧 1200/5000 拒绝、worker budget mismatch、probe/formal verdict、formal SISR 拒绝；保持 `pyvrp==0.12.2` 字符串但改临时 frozen package `.so` 一字节，断言 `_solve_frozen` 0 次且 formal failure。对 formal worker 分别注入 `NO_IMPROVEMENT` 与 `MAX_RUNTIME`，断言只有未越墙的前者 accepted；再让 no-improvement 与 wall 在同一 callback 达标但完整 `runtime_seconds` 超墙，以及 callback 墙内但 solve 返回 runtime 越墙，两例均必须 `CENSORED_SAFETY_WALL` 且 exit 2。再注入第二个和中间 worker nonzero，断言 `completed_runs` 分别为真实前缀、failed unit 精确、remaining 未启动数闭合。另断言 worker leaf 无 `DONE` 合同，seed-batch 只在 finalize+validate 全成功后写固定 verdict `DONE`，中途故障时 marker 不存在；frozen worker 环境仍无 `PYTHONPATH`、没有 `solver/src`，且隔离 file-loader 能读取同一 manifest 而不会导入 `setp_solver`/private solver 包。`! rg -n 'seed 11|1200 秒|same 1200|相同.*1200' solver/scripts/run_public_v2_28_clean_ruler.py` 预期正式 report 模板 0 命中（CLI 历史 default 若尚保留须另行限定行号核对）。
3. 完整聚合：

   ```bash
   set -euo pipefail
   CAMPAIGN=solver/config/formal_campaign_20260818.json
   CAMPAIGN_ID="$(jq -er '.campaign_id' "$CAMPAIGN")"
   build/python_envs/setp-independent-hgs/bin/python solver/scripts/run_public_v2_28_clean_ruler.py aggregate \
     --root "solver/reports/f5_${CAMPAIGN_ID}" \
     --formal-campaign-manifest "$CAMPAIGN"
   ```

   仅在所有 batch 成功时预期 `validated_seed_batches=10`、`validated_unit_runs=560`、`paired_rows=280`、verdict=`FORMAL_PUBLIC_CAMPAIGN_COMPLETE`；任一不完整时预期 verdict=`FORMAL_PUBLIC_CAMPAIGN_FAILED`、nonzero 和 `HALT_INCOMPLETE_F5`，但 summary 五件套及 560-key inventory 仍齐。分别删除一个 child、篡改一个 child hash、置一个 child accepted=false，三例均须失败五件套且不得缩 inventory。
4. 扫 aggregate `raw_runs.csv` 断言 exact 560 个 unit key、每行 coverage complete 与 raw precision feasibility 全 true；成功 aggregate 另扫 `pair_summary.csv` exact 280 个 `(instance,seed)`，每行两臂齐。失败 aggregate 不要求 `pair_summary.csv` 存在，但它若存在也不得进入成功 verdict。
5. 扫 560 个 metadata，断言 SISR false、P82 private components 全 false；每个 `(instance,seed)` 恰两臂、同 seed、各用 manifest 对应预算。

#### F. 净行数预算

- public runner seed/manifest/per-unit budget/aggregate 接线约 `+95/−18`；测试约 `+110/−0`。
- 合计约 `+205/−18`；正式产物 560 unit + 10 seed-batch + 1 aggregate 包。

---

### 工作项 W4.1　狩猎卡：第二父代车队／车型遗传

#### A. 现状取证

1. 当前 route-layer crossover `hybrid_decoder.py:367-380 route_layer_order_from_parents(first,second,rng)` 用两父代做 OX 客户序列，但 `:372` docstring 明写“first-parent type hints”，`:376-379` 只有第一父代缺客户时才补第二父代 hints。正常完整父代下，第二父代车型信息完全不进入 decoder。
2. 当前上游砖 `setp_hgs_kernel.crossover.selective_route_exchange(parents,data,cost_evaluator,rng)->Solution`（`third_party/setp_hgs_kernel/setp_hgs_kernel/crossover/selective_route_exchange.py:13-18`）确实交换第二父代路线；但要核它在 heterogeneous/multi-trip route 类型上的继承语义，不能只因函数名叫 SREX 就认定合格。
3. 本卡只查有没有完整人类实现；不设计“如何融合两父代车型”、不改 `hybrid_decoder.py`。

#### B. 积木清单

| 候选 | 固定版本／commit | 相关入口 | 许可证 | URL | 人类作品证据／当前判定 |
|---|---|---|---|---|---|
| PyVRP | v0.12.2 `ea0c4211819edac6fd920413ad7508cc9ad56e0e` | `crossover.selective_route_exchange`；`Solution.routes()/Route.vehicle_type()` | MIT | https://github.com/PyVRP/PyVRP/tree/v0.12.2 | Wouda/Lan/Kool，INFORMS JOC 2024；首查对象，尚未证明第二父代 type 契约 |
| PyVRP current | HEAD `27a6f6a70566298323c3200f350b2bddaddde48d` | heterogeneous + multi-trip model；0.13+ 已是 ILS | MIT | https://github.com/PyVRP/PyVRP | 约 639 stars；只查可抽取组件，不得称 current 为 HGS |
| Vidal HGS-CVRP | v1.0.0；当前 HEAD `1a927955cd2861a29d978f0d359d6e647db9319c` | `Genetic` crossover/individual route representation | MIT | https://github.com/vidalt/HGS-CVRP | Thibaut Vidal；约 1.1k stars；Vidal 2022 COR 140:105643 |
| VROOM | v1.15.0；HEAD `07be776fc20b8d6c85d9f78797e38a9f4e44ec44` | heterogeneous `vehicle.type`、route construction | BSD-2-Clause | https://github.com/VROOM-Project/vroom | VROOM 人类团队；约 8k+ stars；不是 GA，须查有无可复用 route/type recombination |
| jsprit | 2.0.0；HEAD `c8d94631543ac8154b17d31fd03e67d1f72a23f1` | heterogeneous fleet、initial solution／operator API | Apache-2.0 | https://github.com/graphhopper/jsprit | GraphHopper；约 1.8k stars；Java，适配成本待判 |

#### C. 拼装步骤

本卡无源码拼装；只有以下检索任务，完成前 `+0/−0`：

1. 对每个固定 commit 搜 `selective route exchange vehicle type heterogeneous multi-trip second parent route type offspring`。
2. 定位到函数级源码和测试，记录精确签名、输入父代表示、offspring route 的 vehicle-type 来源；只读 README 不算通过。
3. 用候选自带测试／论文例确认第二父代贡献的是“车型／物理槽”，不是只贡献客户顺序。
4. 检查是否同时支持 heterogeneous fleet、multi-trip/reload、固定可用车辆数；缺任一项写 rejected reason。
5. 估算 adapter 只做 `DutyIndividual↔library Solution` 是否 ≤250 行且不拥有 crossover/repair/search；超过即不合格。
6. 形成 `source URL + commit + license + upstream test path + API mapping` 一页检索报告；不得在本卡写替代算法。

#### D. 缺口如实

`HALT_NO_BRICK`：截至本轮只确认候选项目存在，尚未找到“把第二父代车型／物理车槽以明确契约遗传到 heterogeneous multi-trip offspring”的直接可接 API。现有第一父代 hints 不得自行扩写。

#### E. 验收

1. 候选报告每项必须有 commit、license、函数签名、上游测试路径和 pass/reject。
2. pass 的最低标准：
   - 两父代 type 来源可用上游测试观察；
   - offspring 完整保留客户且不超车型数；
   - 无项目自写搜索／修复循环；
   - adapter ≤250 行；
   - Python/C++ ABI 或 REST/CLI 可固定。
3. 若无 pass，报告末行精确为 `HALT_NO_BRICK: SECOND_PARENT_FLEET_INHERITANCE`。

#### F. 净行数预算

`+0/−0`。本项只产检索报告；发现候选后另呈用户批准，不能自动进入施工。

---

### 工作项 W4.2　狩猎卡：共享充电桩联合调度

#### A. 现状取证

1. 冻结 `check.py:583-644 _check_station_capacity` 只按物理站／日／半小时槽统计占用并报 `STATION_CAPACITY`；它是 checker，不是调度器。
2. `schedule_oracle.py:1244-1286 build_capacity_calendar` 明说 mirror checker，返回 occupied calendar；它仍不等于一套经核上游的“多车共享充电时段优化”积木。文件中其余调度行为的上游身份尚未在本卡证明。
3. `frvcpy 0.1.1` 解决单辆固定路线的充电站插入和充电量，不处理多车同站容量，因此只能作单车内核候选，不能冒充共享调度。
4. 本卡不根据 OR-Tools primitives 自写 CP-SAT model；`new_interval_var/add_no_overlap/add_cumulative` 是零件，不是已经拼好的共享 EV 调度套件。

#### B. 积木清单

| 候选 | 固定版本／commit | 相关 API | 许可证 | URL | 人类作品证据／当前判定 |
|---|---|---|---|---|---|
| Google OR-Tools CP-SAT | 9.15；HEAD `98c165af62df62b3056c2ee0fca66b24e79097cb` | `CpModel.new_interval_var`、`add_no_overlap`、`add_cumulative`、`CpSolver.solve` | Apache-2.0 | https://github.com/google/or-tools | Google，约 13.5k stars；只是标准调度 primitives，未达整套件 |
| SAP emobility-smart-charging | commit `feab7c3fba4689e9b166c2bb45635e8614046262` | Java optimizer + REST，15 分钟 charge plans | Apache-2.0 | https://github.com/SAP/emobility-smart-charging | SAP 人类团队、63 stars；引用 Frendo et al. IEEE TSG 2019 |
| frvcpy | 0.1.1，sdist SHA-256 `726f25739f6445ca646f21c400cca503ed3edaf5406b323f43843c8ac05c86ca` | `solver.Solver(instance,route,q_init).solve()` | Apache-2.0 | https://pypi.org/project/frvcpy/ | Nicholas Kullman；Froger et al. 论文；仅单车 fixed-route |
| VROOM | v1.15.0；`07be776fc20b8d6c85d9f78797e38a9f4e44ec44` | vehicle plan mode/time windows | BSD-2-Clause | https://github.com/VROOM-Project/vroom | 人类开源 VRP 引擎；当前 API 未见共享 EVSE 容量 |
| PyVRP | v0.12.2 与 current `27a6f6...` | multi-trip/heterogeneous route model | MIT | https://github.com/PyVRP/PyVRP | RoutingLab；当前公开能力列表未声明 EV charging/shared charger |

#### C. 拼装步骤

本卡无源码拼装；检索任务：

1. 精确搜索 `shared EV charger scheduling fleet route fixed arrival departure nonlinear charging station capacity open source API`、`EVSE fleet smart charging REST optimizer`、`multi-vehicle fixed-route charging station capacity`。
2. 对 SAP 候选固定 OpenAPI/Swagger request/response：车辆到离站窗口、初始/目标 SOC、桩／站容量、电价、时间粒度、不可用时段、求解状态。
3. 对 OR-Tools 只查官方已有完整 EV/fleet charging sample 或模块；若仍需我们定义 variables/constraints/objective，则判“不成套”，不得把 primitives 拼成自写 scheduler。
4. 对 frvcpy 查有没有多 vehicle/global station capacity 扩展；没有就明确 reject，不在外层自己写冲突消解。
5. 对所有候选核非线性充电曲线、跨日、reserved actions、多个枪、infeasible certificate、确定性 seed／solver version。
6. 只在完整 API 能由 ≤250 行 typed adapter 映射 `ChargingAction` 输入输出时标 pass；adapter 不能拥有时间槽枚举、冲突消解或优化目标。

#### D. 缺口如实

`HALT_NO_BRICK`：当前只有 OR-Tools primitives、SAP 独立 smart-charging 服务和 frvcpy 单车内核，尚未证明任何一件能直接保持本项目路线时间、非线性曲线、公共／场站容量及动态 reserved action 的全合同。不得自行建 CP-SAT 模型。

#### E. 验收

1. pass 报告必须附可运行的上游 example 请求、固定 commit/container digest、license、状态码语义和上游测试。
2. 标准合格例必须由候选原生处理：两车同站一枪、重叠窗口、不同初始 SOC、其中一车跨日；输出不重叠且两车能量闭合。该例由上游 API 配置完成，不写项目调度逻辑。
3. 若无 pass，末行 `HALT_NO_BRICK: SHARED_CHARGER_SCHEDULER`。

#### F. 净行数预算

`+0/−0`。不安装、不下载、不生成 adapter。

---

### 工作项 W4.3　狩猎卡：代理分数非负候选的 exact-truth 救回

#### A. 现状取证

1. 当前 truth boundary 在 `kernel_proposals.py:480-549` 调 `LocalSearch.promising_candidates(...,limit)`，再把返回候选转成完整 Duty 交 exact evaluator；因此 exact truth 只能看见上游先放行的候选。
2. 该 API 是仓内 patch，不在冻结 PyVRP 0.12.2 原版中。C++ `third_party/setp_hgs_kernel/setp_hgs_kernel/cpp/search/LocalSearch.cpp:57-123` 在 `:107-110` 对 node move 明确 `if (deltaCost >= 0) continue`；`:135-138` 对 depot removal 也过滤正值。故代理分数非负但完整 Duty 可能更优的 move 永远到不了 exact truth。
3. `truth_candidate_limit` 只限制已经“proxy promising”的 top-k；把 ε 调大不能救回在 `delta>=0` 被删的候选。
4. 本卡只找“枚举／返回 bounded top-k（允许非改善 proxy）+ caller exact scoring”的人类 API；不设计扫描顺序、阈值或自写候选容器。

#### B. 积木清单

| 候选 | 固定版本／commit | 检索入口 | 许可证 | URL | 人类作品证据／当前判定 |
|---|---|---|---|---|---|
| PyVRP v0.12.2/current | `ea0c421...` / `27a6f6...` | `search.LocalSearch`、operator bindings、candidate API | MIT | https://github.com/PyVRP/PyVRP | RoutingLab；当前公开 API 主要是 improve-in-place，未确认非改善 top-k |
| Vidal HGS-CVRP | v1.0.0 / `1a927955...` | `LocalSearch` move evaluation／granular neighbourhood | MIT | https://github.com/vidalt/HGS-CVRP | Vidal 2022；公开高性能实现，需核是否暴露候选 |
| VROOM | v1.15.0 / `07be776f...` | local-search job addition／route exchange internals | BSD-2-Clause | https://github.com/VROOM-Project/vroom | VROOM 团队；需核 callback/候选导出 |
| OR-Tools Routing | 9.15 / `98c165af...` | local-search operators/filters/monitors | Apache-2.0 | https://github.com/google/or-tools | Google；需核是否可返回未接受 neighbour，而非只在 solver 内过滤 |
| PyVRP issue/docs | current | operator API、`LocalSearch.add_operator` | MIT | https://pyvrp.org/api/search.html | 官方文档；仅接口证据，不把 discussion 当实现 |

#### C. 拼装步骤

本卡无源码拼装；检索任务：

1. 搜 `local search enumerate top-k moves including non-improving delta external exact evaluator callback`、`filter and refine candidate list expensive objective`、`VRP local search candidate callback move delta`。
2. 对每个候选定位“评价但不立即 apply/accept”的函数；记录能否指定 top-k、是否返回 move identity/solution、是否允许 `delta>=0`。
3. 查 operator 覆盖面是否含当前 node exchange、route exchange、reload/multi-trip；只覆盖一个玩具 relocate 的不算整套替代。
4. 查 RNG/扫描顺序/并列键是否可固定；exact callback 必须由 caller 决定 winner，library 不得在 exact score 前吞掉候选。
5. 检查 license、ABI、测试和性能计数；adapter 只能转换 move/solution，不能复制 neighbourhood loop。
6. 若 API 只提供 operator primitives 或 visitor callback、仍要项目自己写枚举循环，判 reject。

#### D. 缺口如实

`HALT_NO_BRICK`：本轮未找到满足“允许 proxy 非改善 + bounded top-k + 完整候选导出 + 外部 exact evaluator”的现成人类 VRP API。当前 patched `promising_candidates` 不能改一行比较符号来充当新算法。

#### E. 验收

1. 合格候选必须用其上游测试或最小官方 example 展示三个候选 proxy delta `-1,0,+1` 均可被 top-k 返回，caller exact score 可选择 proxy `+1`。
2. 报告必须列 commit、函数签名、license、上游测试文件、operator 覆盖、adapter 行数估算。
3. 若无 pass，末行 `HALT_NO_BRICK: NONNEGATIVE_PROXY_CANDIDATE_RESCUE`。

#### F. 净行数预算

`+0/−0`。本卡不改 vendor、不写 C++、不调 ε。

---

## 3. 直接对 Claude 说

Claude，P99 第 2/3 轮的合并修订已经全部进入蓝图本体。第一轮 14 处事实纠正、5 条风险、四处漏网，以及用户本轮给出的 11 项合并清单，现在均由对应工作项、K 键、manifest 字段、E 命令和净行数预算承载，不再靠本节重复另一套说明。

本轮新增事实闭环包括：E1 的四件同提交首现与 GA 反向 import、E7 的 `mismatch_count=24`、`charge_timing` 关闭信号未穿入 default system builder，均由用户复现确认；F3 旧包缺 cut 前状态字段，因此事件次数仍为 `UNKNOWN`，先做 10 流共同 initial 观测；RoutingBlocks／N-Wouda ALNS 没有解除 regret-2 的现有 HALT；K1 的数据只支持共享公共站语义，但仍保留为用户选择。

仍待用户将来按下的 K0–K7 是蓝图有意保留的研究／授权选择，不是 Claude 与 Codex 的分歧，也不得由终读者补默认。

**v2 终读状态：无遗留分歧。**

---

## 4. 条件式施工顺序与停工面

1. **公共底座**：W0.1、W0.3 与 W1.2 的有限身份 adapter 可先施工；W2.2 只有在行为代码与执行身份稳定后才有效，任何后续行为改动都会使旧标定曲线失效。
2. **F5 线路**：K0 必须早于 W0.2 与 F5 开工；K0 未按下时不能动 vendor，也不能把 public 正式线称为干净 independent kernel。
3. **F2 线路**：K1 早于 enterprise slice；A＝共享公共站并在正文披露，基于现有数据是推荐项，但仍由用户决定。随后 K7 早于 private 初始化身份冻结；K6 再早于 S5a code-source SHA。只有对应键成立后才按 W1.3a→b→c→d、standalone→Pi0→joint 推进。
4. **F1 线路**：K7 早于封存见证的 private 初始化身份冻结；K3/K4 决定 A/C 跨价布局、精确 grid、`g_ref point_id` 和预算，再进入 S5 与正式批。
5. **F3 线路**：先冻结 10 条拟正式流与共同 initial，完成 cut 观测探针，再按 K5 冻结需求阈值、readiness、两类预算、mechanical 血统和 W1.1 语义；任一字段仍为 null/HALT 时不开 F3。
6. **独立门**：K2 只控制 W1.4 对受保护 `check.py` 的变更，不阻塞 F1/F2/F5，也不能借其他正式批顺手修改。
7. **狩猎卡**：W4 永远不自动接线；报告只证明当前仓内与已检范围，找到候选后另呈用户批准施工。

---

## 5. 我认为哪几处风险最大、为什么

1. **W1.1 的状态语义**仍是最大技术风险，但现在先由 10 流观测决定它是否真实触发；只有触发时才需要用户批准 PROJECT_DOMAIN 状态转移组件。
2. **W0.2 的血统闭环**仍直接影响 F5：四个同提交首现文件与 `GeneticAlgorithm.py → HGSControl` 反向依赖不能靠机械搬文件消失。
3. **F2 的账链**同时依赖 K1、K7、K6：24 个 witness 错配已排除筛选捷径；任一设施语义、初始化血统或参与账口径错误，Pi0、联合约束与 Shapley 会一起失真。
4. **W1.2 的执行身份**决定标定是否可复用；metadata/hash 与真实 builder stage 未统一前，先跑收敛曲线只会产生跨身份数字。
5. **F3 的两个未授权行为点**是需求阈值和 regret-2：前者当前偷用 2×全客户均值，后者只有项目提交血统；二者都必须由 K5 显式处置。
6. **F1 的 A/C 布局后果**不能在画图时补救：A 每价点都可配对；C 只有 `g_ref` 可配对，其他价点只能给碳感知绝对量和参考线。
7. **W1.4 的保护边界**仍由 K2 单独控制；producer 分散且 `check.py` 受保护，不能借正式批次顺带施工。

---

## 6. 本轮改了什么（v1 → v2）

1. K5 收窄为需求阈值与来源、P34 readiness 具体口径、两类预算、mechanical 血统和 W1.1 语义；P10 已定的“30 分钟或累计需求先到者触发”不再重问，并明确当前 2×全客户均值是未获批参数。
2. K3 只保留跨价格点 A/C 两案，写明 `30|G|` 与 `10|G|+20`，以及 C 仅在 `g_ref` 可干净配对的作图后果。
3. manifest 新增并贯通 `f2_participation_ledger`；K6 提前到 S5a code-source SHA 之前，聚合器不得硬编码 operational。
4. F3 新增 K5 前置 cut 观测探针，七字段在最终 10 流共同 initial 上逐 cut 保存；旧包缺字段的复现命令进入 E 栏。
5. 在途趟分类件改为 PROJECT_DOMAIN 状态转移行为组件，并在 W1.1 单列净行数预算，不再称 adapter。
6. regret-2 的 K5 解锁改为“用户授权项目依据指定论文实现＋五类性质测试”；RoutingBlocks／N-Wouda ALNS 的无现成算子结论进入积木证据。
7. 新增 K7-PRIVATE-INIT-PROVENANCE：覆盖 F1 封存见证的离线生成与 F2 三件初始化，不覆盖检索为 0 的 F5；两案后果均已写明。
8. 按键时序改为按线路表达：K0→W0.2/F5，K1→F2 slice，K7→F1/F2 初始化，K6→F2 S5a，K3/K4→S5，K5→F3，K2 独立。
9. manifest 新增 `f3_time_threshold_seconds/f3_demand_threshold_kg/f3_demand_threshold_source`，并写进 F3 CLI、initial provenance、child metadata 与验收。
10. 第一轮 E1–E14 全部分配到对应工作项；E5、E12 明确只证明仓内与已检索范围，E7 原样保留 24 错配复现。
11. witness 血统表、K1“数据支持共享语义但仍由用户决定”等其余已同意更正同步进入正文；“直接对 Claude 说”更新为 v2 收敛状态。

## 勘误记录

- 2026-08-18 **地基收官止损裁定（用户 P111）**：Semgrep 钩子改用官方 `--no-error` 全量报告模式，
  pre-commit 开启 `verbose: true`；本轮不再区分“新增”与“存量”来决定阻断。36 文件／77 条额外
  存量结果登记在 `tools/quality/semgrep_legacy_registry.md`，与挂账 L11 双向互引。待该队列清零且
  全量扫描确认无旧债后，恢复 `--error` 阻断。其余钩子保持阻断。本裁定取代下条勘误中“新增违规
  照样阻断”的未落地方案；不修改 Semgrep 规则或生产源码，也不再开启第四种 Semgrep 方案。
- 2026-08-18 施工第七轮**换维度裁定**（Claude 批准，依据 P83「几轮不成换更高维度根除」＋
  P98「AI 规则默认无效」）：**弃用 Semgrep 的 `--baseline-commit HEAD` 机制**。
  该机制是蓝图的 AI 设计选择（原理由＝避免自写 diff），非用户决定；它在本移动硬盘上连续
  三次失败（临时卷写满→并发超时→基线副本清理 Errno 66），根因是它必须复制一份 HEAD 工作树，
  而 macOS 持续在外置卷生成 AppleDouble 文件，与其复制/清理动作天然打架。
  **替代做法（更透明，非放宽）**：Semgrep 改为全量扫描；已逐条查实的存量命中写入
  `tools/quality/semgrep_legacy_registry.md`（file:line＋性质＋理由），**新增违规照样阻断**。
  与隐式的 baseline 相比，显式红名单可审计、可追责，判据严格度不降反升。
  自写 diff 解析器仍然禁止。
- 2026-08-18 施工第五轮裁定（Claude 批准，纯运行时开关，不改任何文件）：Semgrep 钩子运行时
  加官方开关 `PRE_COMMIT_NO_CONCURRENCY=1`。实测根因＝两层并行争用（pre-commit 拆 8 分片、
  每片 Semgrep 再开 7 job，8 份 HEAD 基线 checkout 全部超 300 秒上限）；同规则改单线程后
  15 个原超时文件 7.65 秒扫完、零超时。该开关只改并发度，不改规则、不改判据、不改文件。
  **授权放宽（仅限本类）**：今后凡属"工具并发度/资源争用导致的超时"，可用官方运行时开关
  或串行化直接处置并在报告登记，不必停工报批；判据严格度不得因此放宽。
- 2026-08-18 施工第三轮两项裁定（Claude 批准，均属记账/环境，不碰语义）：
  ①断网复装自检明确使用 Python 3.13（与锁定工具环境和 wheelhouse 一致；系统 3.14 的
  wheelhouse 未锁定，不得混用）；②恢复的干净上游文件行数不计入"项目自写生产净增 ≤0"
  ——该预算只约束项目自写代码，恢复纯正上游内容属出处清理，方向与预算目的一致。
- 2026-08-18 施工第二轮补正（Claude 批准）：`._*` 改为 `*/._*`——Vulture 按绝对路径匹配
  exclude，相对形态不命中嵌套目录中的 AppleDouble 文件；施工会话已用只读试验证明 `*/._*`
  正确排除全部 19 个元数据文件且不忽略任何真实源码。**授权放宽（仅限本类）**：今后凡属
  "让检查工具正确跳过 macOS 元数据文件（`._*`／`.DS_Store` 等）"的匹配形态修正，
  按本勘误精神直接执行并在报告中登记，不必再停工报批；其余任何蓝图偏差照旧停工。
- 2026-08-18 施工第一轮（Claude 批准，非语义修正）：Vulture 两条命令的 exclude 增加 `._*`
  ——本移动硬盘为 macOS 外置卷，AppleDouble 元数据文件（`._*.py`）会被 Vulture 当源码读取并
  报编码错误退出（实测 19 个文件、exit 3，见 `solver/reports/w0_foundation_20260818/report.md`）。
  该排除只忽略 macOS 元数据，不忽略任何真实 Python 源码；施工会话按"现场与蓝图不符即停"
  规矩诚实停工报批，未擅改蓝图、未删现场文件，行为正确。

BLUEPRINT_END
