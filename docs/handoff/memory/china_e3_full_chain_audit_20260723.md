# China E3 正式实验前全链路审计（2026-07-23）

权威审计包：
`baselines/china_e3_e7/pre_e3_full_chain_audit_20260723/`。

最终判定：
`HOLD_E3_DECISIONS_AND_EXECUTION_BINDINGS_OPEN`。本轮正式搜索评价数为 0，
`formal_search_allowed=false`。旧 E2 终局标记只保留为历史版本收口，不再表示
修正后 China81 权威可直接复用。

## 已闭合的确定性问题

新建并独立验收以下版本化权威，旧文件和旧证据不覆盖：

- `data/ChinaInstances/china81_runtime_parameter_authority_v3_20260723/`
- `data/ChinaInstances/china81_customer_location_assignments_gis_v3_20260723/`
- `data/ChinaInstances/china81_order_attributes_gis_v2_20260723/`
- `data/ChinaInstances/china81_stage2_static_inputs_corrected_v3_20260723/`
- `data/ChinaInstances/china81_local_directed_matrices_corrected_v10_20260723/`

新权威验收 86/86 通过；运行时价区/碳列边界与故障注入 10/10 通过；目标函数与
检查器独立复算 29/29 通过。深圳由显式 `price_area_id` 和合同情景属性选择电价，
经纬度只验证声明区域，不用于猜测价格。成都改用四川碳强度列，重庆继续使用重庆列。

强证书现重放实体车、逐弧 SOC、公共站时钟、非线性充电和跨趟电量。审计还修复了
动态阶段过滤初始方案时删除公共充电站、保留充电动作并静默退回燃油方案的生产缺陷；
公共站节点现按原顺序保留。定向回归 117/117 通过。

## 对 E2 的影响

修正后的地理权威改变 54/81 个实例、2221 个客户位置；15 个成都实例受历史碳列
错误影响；若启用日期对齐柴油价，81/81 个实例都会改变燃油成本。预登记仿真算例
`cn-prd-50c-01` 也在地理修正范围内。

因此 China81 私有分层表、仿真算例十次算法表、路径明细、迭代图以及相应统计和
文字结论均须在新权威下重跑。公开标准 benchmark 输入不受这批中国输入问题影响，
但旧公开批次未保存足以通过当前增强检查器逐解重放的完整 witness；只能保留并披露
其检查器版本边界，不能补写不存在的重验结论。

## 仍阻断 E3 的事项

1. `D1-DIESEL`：日期对齐柴油价候选已取证，尚未批准启用。
2. `D2-FLEET-CHARGERS`：现有每车型等于客户数的上限不约束，车场桩数和功率缺少
   经批准的构造情景规则。
3. `D3-E3-ARMS`：当前冻结算法没有实现“客户必须由所属车场服务”的可执行控制臂。
4. `D4-BUDGET`：正式成对实验没有冻结确定性的完整候选评价预算和线程环境。
5. `D5-SP-CLAIM`：限时 HiGHS 在未证明最优时仍可接受 incumbent，不能称“精确重组”。
6. `D6-RERUN-SCOPE`：修正后 China81 私有 E2 与仿真算例 S3--S5 的重跑范围待批准。
7. 正式任务尚未绑定输入、算法、评价器、事件、初解、解、证书和独立复算哈希；
   受保护语义修复也须形成新版本合同与哈希。

建议口径和备选方案见审计包中的
`unresolved_decision_register.md`。只有 D1--D6 全部登记、正式 runner 和逐任务
见证闭合、81 个 bundle 与对抗门全部通过，才可另立 `GO_E3`。不得用安装依赖、
旧 PASS 或历史收官标记替代这些门。

## 回归、环境与论文边界

相关全量测试共收集 888 项：878 通过、1 跳过、9 失败。9 项已逐一分类为 4 个旧
封存哈希报警、3 个硬编码旧环境门、2 个历史 E5 证据真实违反有限车队/充电语义；
没有把红灯改成假绿，也没有发现本轮新增实现回归。

审计环境依赖闭合，但冻结 PyVRP 0.12.2 环境未绑定 SciPy/HiGHS，路线池代码仍可能
借用 `/opt/anaconda3`，线程变量也未冻结。论文数学审计 36 通过、0 错误、1 警告；
XeLaTeX 已写出 21 页 PDF，无未定义引用或 overfull。逐句主张审计为 2 PASS、
1 REVIEW、9 FAIL；在替代证据封存前，不得用旧数值改写修正后结论。

