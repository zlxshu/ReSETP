# Solomon现代强基线执行接口

状态：2026-07-17 零搜索接口与预检五记录面已完成；PyVRP 0.13.4 已在独立Python环境中按官方wheel哈希安装，并通过3客户合成VRPTW候选工具探针。最终工具冻结尚未生成，Solomon路径搜索尚未启动。当前预检仍判定为`HALT_EXTERNAL_BASELINE_PREREQUISITES`，但缺口已收敛为E7步骤1--6证明和最终工具冻结两项；新预检产物在`baselines/e2_alns/e2_solomon_external_baseline_preflight_pyvrp0134_20260717/`。

公开标准算例的外部强基线只使用“同一机器、每个求解器单线程、相同墙钟上限”公平轴。本文ALNS、LNS和组件消融继续使用“相同完整候选评价次数”公平轴；两类结果分表报告，不能把PyVRP/HGS的迭代数或墙钟时间换算成本文评价次数。异机论文中的CPU、RT和Computer仅作背景，不支持速度优越性结论。

零搜索预检为`baselines/e2_alns/audit_solomon_external_strong_baseline_preflight_20260717.py`，正式接口为`baselines/e2_alns/run_solomon_external_strong_baselines_20260717.py`。默认调用只报告HALT，不创建求解任务。正式执行必须同时提供精确授权字符串、E7步骤1--6完成证明和外部工具冻结文件；任务使用56个无BKS的SINTEF bundle与10个预注册种子，BKS只在项目独立双精度复算路线后由父进程关联。

PyVRP适配器使用bundle中的硬时间窗、容量和双精度距离矩阵。由于PyVRP内部采用整数成本，冻结时须指定至少1000的统一缩放因子。固定车辆成本不再由浮点总距离统一取整，而是先逐弧使用与PyVRP相同的整数化规则，再以“最大整数弧×客户数与最大车辆数之和”构造总距离上界，最后加1；这样覆盖逐弧最多0.5单位的累计舍入误差，可证明实现“先车辆数、后距离”的字典序代理。最终车辆数、双精度距离和可行性均由父进程项目评价器重新计算。PyVRP版本、Python解释器、包源码哈希、建模API、命令、种子、墙钟上限和线程环境必须一起冻结。若冻结版本不能可靠导出首次达到最终最好解的时间，正式门不得通过，不能拿总运行时间冒充该指标。

正式接口按任务建立独立`attempt-XXXX`目录，封存输入、实际命令、标准输出、标准错误、worker结果和父进程结果，并生成`task_artifact_hashes.json`。只有worker前后及父进程写checkpoint前的E7完成证明文件、工具、接口、bundle和合同哈希全部一致，且父进程核对任务身份、路线哈希、失败语义并重新计算硬时间窗/容量/距离后，才原子写入单任务checkpoint。重启时只复用合同完全相同且封存哈希复核通过的checkpoint；不完整attempt保留现场并新建下一attempt，既不删除也不当成完成。560个任务不再只保存在内存中。完成后根目录另生成覆盖全部checkpoint和所有attempt（包括未完成事故现场）的全局`task_artifact_hashes.json`，由最终`artifact_hashes.json`绑定；发布前后均重算实际`.tasks`内容自验，后续也可独立调用验证器发现封存后篡改。

每个solver子进程均以新进程组启动。超过“冻结求解墙钟上限+30秒父进程收尾余量”后，父进程向整个进程组发送`SIGTERM`，等待5秒仍未退出则发送`SIGKILL`；该策略和实际命令随attempt封存。父进程收到`SIGINT`或`SIGTERM`时，信号处理器只设置停止标志，主线程随后统一清理活动进程组并原子写incident，避免`start_new_session`子进程成为孤儿。任何checkpoint或attempt被改写都会停止恢复，不能静默重跑覆盖。

E7步骤1--6完成证明不能人工手写。`baselines/e7_dynamic/build_e7_steps_1_to_6_attestation_20260717.py`只读取显式指定的五套封存面：正式120任务、28日零搜索重放、重放不变量、独立总审计和七件论文展品manifest；它不扫描checkpoint、监控目录或中间结果。任一五记录面、精确计数、零搜索字段、外部暂停时效检查、展品来源/生成哈希或搜索合同哈希不闭合时只返回HALT，不创建或覆盖正式attestation；全部通过后才原子发布带`evidence_hashes`、`search_version`和`search_version_closed=true`的证明。

官方`vidalt/HGS-CVRP`只支持CVRP，没有硬时间窗，不能直接参加Solomon VRPTW主表。若后续采用HGS，必须另行提供支持VRPTW的实现、精确版本/源码哈希和独立CLI适配器；当前v1 runner不会把HGS-CVRP冒充为HGS-VRPTW。

PyVRP候选工具探针为`baselines/e2_alns/probe_pyvrp_0134_api_20260717.py`，当前权威证据在`baselines/e2_alns/pyvrp_0134_tool_probe_20260717_v4_repo_runtime/`；v3及更早目录仅保留为历史证据。其固定版本为0.13.4，官方macOS arm64 wheel SHA-256为`49b84319fcfcd2206c05f55e970d090ab054d577a1d82cbac276d376fe89970c`，解释器已迁入仓库内独立环境`build/python_envs/pyvrp-ils-0.13.4/bin/python`，项目迁移不再依赖用户目录。v4探针分别用原生API和正式bundle适配器运行20次合成实例迭代，Solomon正式搜索评价为0；16项检查全部通过，bundle分支返回路线1--2--3和精确整数代理目标106000。0.13.4的`Statistics.runtimes`是逐迭代耗时增量，Tbest必须累加后与`Statistics.data`中的`best_feas/best_cost`对齐，不能把单个增量或总运行时间冒充首次最好时间。最终冻结文件现在还必须校验自身`freeze_payload_sha256`，任一字段被改写都会在搜索前停止；适配器与冻结构建器共32项接口测试通过。

当前停止原因只剩两项：E7步骤1--6证明不存在；`final_external_baseline_freeze/external_baseline_freeze.json`不存在。候选工具探针不等于最终授权；E7完成后还须把精确解释器、wheel、安装环境、适配器、预检器、线程数、墙钟、种子和Tbest抽取器一起冻结。这两项未补齐前，只允许运行零搜索预检、合成工具探针和测试。

最终冻结只能由`baselines/e2_alns/build_final_external_baseline_freeze_20260717.py`生成。该脚本要求精确授权串和E7步骤1--6证明，复核候选探针五记录面、96个PyVRP安装文件、wheel、接口、CPU合同及E7证据哈希，并拒绝覆盖已有冻结。墙钟预算不是沿用模板中的任意1800 s：PyVRP官方VRPTW基准对1000客户使用参考CPU两小时、单核、10种子；本文只把这一规定按客户数线性外推到100客户，再按已冻结PassMark因子1.837换算，得到标准720 s、本机391.94338595536203 s。这个线性外推是本文预注册的公平假设，不是PyVRP官方Solomon协议，正文必须如实说明。4个并行worker分别占用4个性能核，单个求解器仍强制单线程；CPU、RT、Tbest和Runs分别报告。
