# MPD 双节奏门首次启动事故

- 时间：2026-07-20 04:03（UTC+8）
- 性质：监控外壳接线错误，搜索评价 0
- 算法、参数、算例、种子、预算、判据：未改变

首次监控目录使用`.mpd-dual-regime.monitor/`，但隔离目录原有`.gitignore`只覆盖
`.mda-*.monitor/`。监控器先创建目录，正式门随后执行干净仓库检查并在任何求解前
确定性拒绝启动：

`RuntimeError: dual-regime gate must start from a clean commit`

修复只把`.mpd-*.monitor/`加入本目录忽略规则。原监控事故目录保留在仓库内部且被
忽略；合同、算法源码、四臂、A/B题、种子、时间预算和验收门均未修改。修复提交后才
允许用新监控目录重启同一正式门。
