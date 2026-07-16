# Homberger 200客户开发集零搜索来源合同

状态：2026-07-17 数据来源与结构门通过以前，禁止把12例用于算法搜索；本合同不提供BKS或详细解。

## 目的与数据隔离

最终ALNS换代合同指定12个Homberger 200客户实例作为开发集：`C1_2_1`、`C1_2_8`、`C2_2_1`、`C2_2_8`、`R1_2_1`、`R1_2_8`、`R2_2_1`、`R2_2_8`、`RC1_2_1`、`RC1_2_8`、`RC2_2_1`、`RC2_2_8`。它们只用于G1/G2算法开发，不进入Solomon 56例最终测试。

权威实例来源为SINTEF Transportation Optimization Portal的[200客户页面](https://www.sintef.no/projectweb/top/vrptw/200-customers/)及其[官方实例压缩包](https://www.sintef.no/globalassets/project/top/vrptw/homberger/200/homberger_200_customer_instances.zip)，文件格式依据[SINTEF VRPTW说明](https://www.sintef.no/projectweb/top/vrptw/documentation2/)。来源快照只冻结官方压缩包、格式说明和12份实例原文，不保存页面中的BKS值或详细解路线。

## 零搜索门

脚本`baselines/e2_alns/audit_homberger_200_source_gate_20260717.py`只做下载、哈希和结构审计。逐例检查节点编号0--200、200个客户、车辆上限50、分组容量、需求、服务时间以及`ready <= due`。每行`search_evaluations=0`，输出五记录面；任何来源哈希漂移、节点缺失、容量错配、时间窗倒置或AppleDouble残留均判失败。

官方压缩包冻结SHA-256为`79092cc627135f370a6381b0c64afc8403e4d4ff74afa8808d28d208ac784571`。SINTEF格式说明快照SHA-256为`e4c08998ec0831d28e659584904d26adc6c7a088a8dbb47a446b6534fee812df`。

首次输出目录`e2_homberger_200_source_gate_20260717`在写入最终`artifact_hashes.json`后由外置盘生成一份AppleDouble伴生文件；科学数据未变，但该目录不作为权威门。脚本补上最终写入后的二次清理与硬检查，权威输出为`e2_homberger_200_source_gate_20260717_v2`。

## 权限边界

该门通过只说明开发数据来源真实、结构完整，不授权启动路径搜索。E7十步收口、共享内核释放、评价预算闭合与新增操作单元测试仍是前置条件。算法不得读取SINTEF 200客户BKS页面、最佳值或详细路线；开发阶段只接触冻结实例文件。
