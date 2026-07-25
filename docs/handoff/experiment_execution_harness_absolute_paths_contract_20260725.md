# 实验启动器绝对路径基础设施合同

- 编号：`EXPERIMENT-ABSOLUTE-HARNESS-001`
- 日期：2026-07-25
- 状态：`REGISTERED_FOR_NO_INSTANCE_INTEGRATION_GATE`

## 目标

修复多个候选共同遇到的启动器路径问题，不修改任何候选算法、评价器、算例、预算、
阈值或科学合同。该基础设施只负责证明监督器、主进程与六个 spawn 子进程均解析到
同一预期仓库和脚本。

## 冻结要求

1. 项目根目录必须是已解析的绝对目录，并同时存在 `HANDOFF.md`、
   `docs/handoff/READ_ME_FIRST_FOR_AGENTS.md` 与 `solver/src/setp_solver`；
2. Python、监督器、主脚本、保护文件、结果文件、完成标记和监督目录全部使用已验证
   的绝对路径；禁止依赖当前目录或配置文件相对路径；
3. 主进程在创建子进程前核对当前目录、项目根、Python、脚本和注册哈希；
4. 六个 spawn worker 不加载任何真实算例，各自回报进程号、模块名、模块绝对路径、
   当前目录、项目根与 Python；六个进程号必须互异且全部逐位一致；
5. 监督器必须识别正式 `done.json`，结果与保护路径不得出现重复前缀或不存在项；
6. 自动 AI 关闭，测试中不读取候选中间成绩。

任何一项失败均判 `HALT_EXPERIMENT_ABSOLUTE_HARNESS_V1`。通过只说明共用启动基础设施
可用，不授权自动重跑任何候选；JRC 是否重开必须由协调任务另行授权。
