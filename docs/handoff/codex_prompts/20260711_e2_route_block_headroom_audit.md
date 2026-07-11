# E2负例恢复：整路块互补性审计合同

状态：`PRE-REGISTERED / AUTHORIZED_AFTER_PROPORTIONAL_REJECTION`

## 人话目的

不再跑新搜索，不再调阶段比例。只把已经产生的staged、LNS、restart、true-LNS和proportional true-LNS保存解拆成整条路线，检查不同运行是否真的提供可互补的优质路线块。

如果这些整路块根本拼不成更好的零违规解，就说明当前15负不能靠最小HGS/SREX式重组修好，E2恢复必须停止。如果多个负例都能拼成更好解，才说明“路线种群+整路交换”有真实headroom。

## 冻结输入

只读以下目录的保存解：

- `short_gate_formal_start/`的`restarted`；
- `true_lns_middle_gate/`的`staged`、`LNS`和`true_lns_middle`；
- `proportional_true_lns_middle_gate/`的`proportional_true_lns_middle`。

固定为原9个短门配对：6个开发负例+3个保护样本。所有父解必须重新通过当前280 kWh的`model_cost()`和`check_solution()`；有任何父解不一致就HALT。

## 审计方法

1. 记录每个父解的路线签名，计算父解两两整路重合率和唯一路线块数。
2. 建立只含现有整路块的set-partitioning模型：每个客户必须被且只被一条路线覆盖。
3. 通过no-good约束为每组最多枚举50个不同路线组合；不增加搜索评价，只复算枚举的现有路块组合。
4. 混合组合必须来至至少两个父解。组合后按当前多趟车辆语义重新绑定车辆ID，保留所选路线的充电动作和跨场服务，然后用原checker/evaluator复算。
5. 父解自身不算headroom；只有混合组合在零违规下比该组最好父解更便宜，才算真实改善。

## 预注册判决

`ROUTE_BLOCK_HEADROOM_SUPPORTED`必须同时满足：

- 9组全部父解复算一致、零违规；
- 6个开发负例中至少3组存在可行混合整路块解；
- 6个开发负例中至少2组的最优混合解比该组最好父解便宜至少0.25%；
- 上述2组必须因此低于LNS，即真正证明可多救回至少2个负例。

未达任一项，判`ROUTE_BLOCK_HEADROOM_NOT_SUPPORTED`：不开发HGS/SREX候选，项目1/2以冻结E2证据收口，立即转入项目3的80 kWh稳健性尝试。

## 红线

不得运行新ALNS/LNS搜索，不得修改父解，不得增加修复算子，不得放宽客户覆盖、车队、充电、时间窗或多趟约束。不得修改`cost.py`、`check.py`、`search/evaluation.py`、价格、物理参数、算例或冻结E2证据。
