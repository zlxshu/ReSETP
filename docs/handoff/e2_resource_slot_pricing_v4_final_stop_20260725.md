# E2 资源—时隙定价候选 V4 最终停止

状态：`FINAL_STOP_RESOURCE_SLOT_PRICING_NO_LOW_COST_STRONG_HGS_HEADROOM`
（2026-07-25）。

## 最终授权与工程闭合

用户在 V3 因 runner 同名解析错误而没有进入候选评价后，最后授权一次根因级工程
隔离。V1--V3 注册、监控现场和五件套均原样保留。V4 新建唯一可导入包
`rsp_final_isolated_20260725`；worker、工程入口和 G0 入口均使用包限定名称。冻结
算法及依赖从登记的精确文件加载，任何模块名已被其他文件占用或文件身份不一致均
立即失败。

六进程零目标身份冒烟返回 6/6 行和 6 个不同 PID。所有子进程在加载任何真实算例前
均报告 runner 模块
`rsp_final_isolated_20260725._frozen_g0_runner`，runner 文件均为本候选冻结的
`baselines/algorithm_prototypes/resource_slot_pricing_20260725/run_g0.py`。随后六个
零目标工程任务 6/6 PASS，候选完整目标评价数为 0，资源门 PASS。

工程进程已经正常写出 PASS 五件套后，最初观察器因配置文件相对路径基准重复拼接
结果目录，误报“进程退出但未发现完成标记”；该现场原样保留。执行前后的登记源码、
保护输入、旧 V1--V3 证据和工程五件套哈希均重新闭合，且六进程身份记录完整。G0
随后使用仓库根目录观察配置，保护文件、资源、CSV 和完成标记全程无 finding，观察器
终态为 `COMPLETED`。没有为处理该观察器路径问题重跑工程任务或改变冻结实验。

## 冻结 G0 结果

G0 保持三道预登记算例、每题 `LOCAL` 与 `RESOURCE-SLOT` 两臂、强 HGS-M 起点、
6 workers、50000 标签扩展、最多 8 条新路线、每任务一次完整候选评价、5 秒 MIP
和 60 秒安全上限不变。六任务 6/6 完成，直接检查与精确评分违约均为 0，六个输出
witness 全部独立重放闭合，所有候选数、评价次数和时间上限均满足。

三个算例中，两臂都返回原强 HGS-M 成本。`RESOURCE-SLOT` 严格改善起点 0/3，改善
不低于 0.05% 为 0/3，胜 `LOCAL` 为 0/3，负于 `LOCAL` 为 0/3；选入旧池外负约化
成本且改变客户相邻关系的新路线为 0/3，资源价格改变选路排序的归因为 0/3。墙钟比
中位为 0.998893，最大为 1.004203。

## 终局边界

预登记效果门判
`STOP_RESOURCE_SLOT_PRICING_NO_LOW_COST_STRONG_HGS_HEADROOM`，下一步为
`FINAL_STOP_NO_RESCUE`。本次结果已经排除此前 Python 接线歧义，说明该冻结机制在
所选低成本门上没有显示出深化强 HGS 解的能力。不得修改参数、题、起点、标签上限、
出弧数、候选数、筛选、评分或阈值后重跑；不得扩大 China81、启动 E3、公开
BKS/SOTA 或写入论文性能与 `1+1>2`。

权威产物：

- 工程门：`rsp_final_isolated_20260725/engineering_gate_v4/`
- G0 与独立复算：`rsp_final_isolated_20260725/g0_gate_v4/`
- 冻结登记：`rsp_final_isolated_20260725/g0_registration_v4.json`
- 执行合同：`docs/handoff/e2_resource_slot_pricing_isolated_final_v4_20260725.md`
