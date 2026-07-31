# ReSETP Claude 配额看门狗调查、实现与自测报告

报告时间：2026-07-30（Asia/Singapore）

## 总结

FACT：配额信号已经找到。Claude Desktop 一方面在 `~/Library/Application Support/Claude/plan-usage-history.json` 中约每 5 分钟写一次五小时用量百分比，另一方面在真正撞到会话限额时，会在 `~/Library/Logs/Claude/main.log` 写出本地会话 ID、`You've hit your session limit` 和明确的 `resets ... (Asia/Singapore)`。后者可直接作为“重置前禁止唤醒”的高可靠闸门。

FACT：看门狗脚本、独立辅助程序、持久状态和审计日志均已实现并通过静态检查、实时只读探测和限额时间解析测试。

FACT：交付目前是 `BLOCKED_ACCESSIBILITY_PERMISSION`，不是完成状态。专用辅助程序尚未获得 macOS“辅助功能”权限，真实发送自测在发送前即明确失败，测试消息没有发出；因此看门狗没有作为后台进程启动，PID 为 `null`。

INFERENCE：这是当前唯一确认的阻塞点。权限授予后仍必须先跑真实发送自测；只有自测通过后，才能诚实地启动常驻进程。

## 任务一：配额状态和限额特征信号

### 1. `~/.claude/`、Claude Desktop 本地数据和日志

FACT：当前 ReSETP Claude Code 会话的 CLI session ID 是 `38318a55-922c-41ef-968a-bdf76591b1cd`，会话 JSONL 是：

`~/.claude/projects/-Volumes------512G--ReSETP/38318a55-922c-41ef-968a-bdf76591b1cd.jsonl`

FACT：对应的 Claude Desktop 本地会话元数据位于 `~/Library/Application Support/Claude/claude-code-sessions/` 下。元数据中有 `cliSessionId`、`bridgeSessionIds`、`cwd`、`title` 和 `lastActivityAt`，因此脚本可以按 `cwd == /Volumes/移动硬盘（512G）/ReSETP` 动态找到当前未归档会话，而不依赖窗口坐标或固定 UI 索引。

FACT：当前会话对应的临时任务根目录是：

`/private/tmp/claude-501/-Volumes------512G--ReSETP/38318a55-922c-41ef-968a-bdf76591b1cd/`

其中 `tasks/*.output`、`scratchpad/*.pid` 和 `scratchpad/*.log` 可作为后台任务完成或退出的行为信号。

FACT：`~/Library/Application Support/Claude/plan-usage-history.json` 是版本 2 的 JSON，包含 `samples[]`；每条样本有时间 `t`、组织标识 `org` 和 `u.fh`（five-hour utilization）。实测样本大约每 5 分钟一次。2026-07-30 03:47:15 的当前样本为 79%。这个文件没有直接保存 `resets at` 字段。

FACT：历史样本中可看到 `u.fh` 从 100 降到 0 的窗口切换。脚本仅在找不到精确日志重置时间时，才用“最近一次明显下降 + 5 小时 + 10 分钟安全量”作保守备用估计；如果当前百分比已到 99–100%，但无法可靠估计重置时间，脚本会保持等待，而不会每 20 分钟盲发。

FACT：`~/Library/Logs/Claude/main.log` 中存在多次真实限额记录，格式包括：

`You've hit your session limit · resets 8pm (Asia/Singapore)`

同一日志还会记录 `unhealthy cycle ... reason=api_error`。这些记录包含 Claude Desktop 的 `local_...` 会话 ID，脚本只接受当前 ReSETP 本地会话 ID 的记录，避免把别的 Claude 会话限额误套到当前会话。

FACT：日志还出现过 `You've hit your monthly spend limit`、`529 Overloaded` 和网络错误。这三者不是五小时滚动配额，脚本不会把它们伪装成同一种信号。

FACT：`~/.claude/telemetry`、`~/.claude/debug`、`history.jsonl` 和项目 JSONL 中没有找到比 `main.log` 更稳定的“当前五小时配额 + 精确重置时间”结构化来源。项目 JSONL 中大量 `rate_limit` 字符串属于用户/助手讨论或工具输出文本，不能仅靠关键词命中判定撞限额。

### 2. Claude Code CLI

FACT：用户级 Claude CLI 版本为 `2.1.220`；Claude Desktop 当前嵌入的 CLI 为 `2.1.219`。

FACT：只读检查了 `claude --help`、`claude auth --help`、`claude auth status` 和 `claude agents --json --all --cwd ...`。CLI 没有只读的 quota/usage 子命令；`auth status` 只报告登录状态，`agents --json` 能确认当前交互会话，但不返回配额。

FACT：没有执行 `claude -p`、新建会话、刷请求或其他会为“测试配额”而消耗额度的 CLI 操作。

### 3. Claude Desktop UI

FACT：Claude Desktop 版本为 `1.24012.9`。通过当前已授权的 Computer Use 辅助功能树，点开用量区域后，2026-07-30 约 03:20 读到：`5-hour limit`、`Resets in 2 hr 56 min`、`76%`。这证明 UI 能显示用量和重置倒计时。

FACT：UI 辅助功能树同时能读到当前会话标题、输入框和发送按钮。因此，在具备独立辅助功能权限时，可以验证目标会话后设置短消息并按发送。

INFERENCE：UI 倒计时是精确的人类可读信号，但对无人值守脚本而言，`main.log` 的当前会话精确限额文本更稳定；百分比历史文件则比 OCR 更适合持续采样。

### 4. 信号源可靠性结论

FACT：最高可靠性是 `main.log` 中当前 `local_...` 会话的 `You've hit your session limit · resets ...`；它明确表示已撞限额并给出时区化重置时间。

FACT：高可靠性行为信号是当前会话 JSONL/本地元数据的活动时间，加上会话专属 `tasks/`、`scratchpad/` 和仓库内有效 `done.json` 的完成时间。

FACT：高可靠性用量信号是 `plan-usage-history.json` 的新鲜 `u.fh` 百分比；它不能单独给出精确重置时刻。

FACT：UI 用量弹窗本身可靠，但后台读取依赖该读取进程自己的 macOS 辅助功能授权。

FACT：CLI help、telemetry 关键词和单纯的全局进程数不能可靠表示当前会话是否撞限额。

## 任务二：看门狗实现

FACT：主脚本是 `claude_quota_watchdog.py`。它只使用 Python 标准库，默认每 60 秒检查一次，15 分钟为停滞阈值，成功或失败的唤醒尝试均受至少 20 分钟持久冷却约束。

FACT：脚本动态解析当前 ReSETP Claude Desktop 会话，不把会话 UUID、窗口坐标或 UI element index 写死。

FACT：完成事件包括：会话专属 `tasks/*.output` 从空变为非空、`scratchpad/*.pid` 所指进程已经退出，以及 `docs/handoff/` 或 `baselines/china_e3_e7/` 下具有非空 `status` 的 `done.json`。交付目录自身被排除，避免本任务的 `done.json` 唤醒 Claude。

FACT：脚本只有在“完成事件比 Claude 会话活动更新”“事件已至少 15 分钟”“Claude 会话本身也已至少 15 分钟无活动”三个条件同时满足时，才进入唤醒候选。任何晚于事件的当前会话活动都会把事件视为已处理。

INFERENCE：15 分钟足以覆盖 Claude 正常收取后台任务结果、整理产物和写一次回复的延迟，同时比小时级配额停顿短；双时间条件比单看某个 `done.json` 年龄更不容易误报。

FACT：命中当前会话精确限额日志后，脚本在日志给出的重置时刻再加 60 秒安全量之前绝不发消息。没有精确日志时，若五小时用量是 99–100%，脚本使用保守备用估计或保持等待。

FACT：唤醒消息固定为：

`Codex 任务已完成，请读取最新的 done.json 和 report.md 并继续推进 ReSETP 项目。`

FACT：独立发送通道由交付目录内的 `ReSETP Claude Quota Watchdog Helper.app` 承担。脚本先用当前会话 `bridgeSessionId` 的 `claude://code/...` deep link 导航到精确会话并预填，然后 helper 验证会话标题、设置输入框、发送 Return，最后要求“消息在会话树中可见”且“输入框已清空”才记为成功。

FACT：Anthropic 的官方说明明确说 deep link 的 `q` 只预填、供用户检查后发送，并不会自动提交。因此实现不能把“打开了 deep link”误报成“消息已发送”：https://support.claude.com/en/articles/14729294-open-claude-desktop-with-a-link

FACT：helper 是最小 Objective-C/Core Accessibility 程序，源码为 `ClaudeWakeHelper.m`，构建脚本为 `build_helper.sh`。它以固定 bundle ID `org.resetp.claude-quota-watchdog-helper` 进行 ad-hoc 签名。授予权限后不要重新构建 helper；重签名可能要求重新授权。

FACT：状态写入 `state.json`，审计日志写入 `watchdog.log`，运行 PID 应写入 `watchdog.pid`。脚本启动前会探测 helper 权限；权限缺失时以非零状态退出并写明用户动作，而不是启动一个无法唤醒的假看门狗。

FACT：没有修改实验代码、solver、TeX、封存证据或 `tools/claude_quota_watchdog/` 之外的仓库文件。

## 任务三：真实发送自测

FACT：2026-07-30 03:51:21 执行了：

`python3 tools/claude_quota_watchdog/claude_quota_watchdog.py --test-wake`

FACT：预定测试消息是 `配额看门狗自测，请忽略。`

FACT：测试在发送动作前失败，退出码为 2。`watchdog.log` 记录：

`result=BLOCKED_WAKE_CHANNEL`

以及：

`error=ACCESSIBILITY_NOT_AUTHORIZED`

FACT：helper 的 `AXIsProcessTrusted()` 返回 false。测试消息没有出现在 Claude 会话中；因此 `wake_channel_tested` 必须是 false，不能把当前 Codex 会话自身的 Computer Use 权限冒充成这个后台 helper 的权限。

FACT：已调用 helper 的 macOS 权限请求，并尝试打开“系统设置 → 隐私与安全性 → 辅助功能”。本执行上下文没有得到一个可由自动化控制的 System Settings 窗口，无法替用户完成最后的 TCC 开关。

INFERENCE：代码路径之外的阻塞是 macOS 对每个发送进程单独授予辅助功能权限的安全边界。只有用户在系统设置里授权这个精确 helper 后，真实发送测试才有意义。

### 用户必须执行的动作

FACT：打开“系统设置 → 隐私与安全性 → 辅助功能”，点击 `+`，添加并启用：

`/Volumes/移动硬盘（512G）/ReSETP/tools/claude_quota_watchdog/ReSETP Claude Quota Watchdog Helper.app`

FACT：授权后先运行以下命令；只有它返回 `self_test result=PASS`，才说明测试消息真实出现且输入框清空：

```bash
cd '/Volumes/移动硬盘（512G）/ReSETP'
python3 tools/claude_quota_watchdog/claude_quota_watchdog.py --test-wake
```

## 任务四：后台启动状态

FACT：由于任务三未通过，按用户硬约束没有启动看门狗。当前 `watchdog_running=false`，`watchdog_pid=null`，不存在可停止的后台 PID。

FACT：2026-07-30 03:54:13 实测执行默认启动入口。权限预检以退出码 2 返回 `startup_blocked`，且没有创建 `watchdog.pid`；这验证了脚本不会在唤醒通道无效时伪装成已运行。

FACT：授权且真实自测通过后，启动命令是：

```bash
cd '/Volumes/移动硬盘（512G）/ReSETP'
nohup python3 tools/claude_quota_watchdog/claude_quota_watchdog.py \
  >> tools/claude_quota_watchdog/watchdog.stdout.log 2>&1 </dev/null &
sleep 2
cat tools/claude_quota_watchdog/watchdog.pid
```

FACT：启动后主审计日志为：

`/Volumes/移动硬盘（512G）/ReSETP/tools/claude_quota_watchdog/watchdog.log`

FACT：停止命令是：

```bash
kill "$(cat '/Volumes/移动硬盘（512G）/ReSETP/tools/claude_quota_watchdog/watchdog.pid')"
```

FACT：守护进程会在收到 SIGTERM 后删除它自己的 `watchdog.pid` 并在日志写入 `stopped`。
