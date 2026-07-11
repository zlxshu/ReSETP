# E2负例恢复：未见种子4000评价验证合同

状态：`PRE-REGISTERED_AND_IMPLEMENTED / BLOCKED_BY_PROPORTIONAL_SHORT_GATE`

## 已准备的正式入口

短门通过前不得启动。通过后只使用独立的57次入口，不得用原来写死9组样本的短门脚本冒充：

```bash
PYTHONPATH=solver/src:. python baselines/e2_alns/e2_loss_recovery_unseen_seed_gate.py \
  --output-dir baselines/e2_alns/e2_loss_recovery_20260711/unseen_seed_4000_gate \
  --eval-budget 4000 --max-runtime-seconds 1800 --battery-kwh 280 --workers 3
```

运行结束后必须再用保存解独立验收：

```bash
PYTHONPATH=solver/src:. python baselines/e2_alns/e2_loss_recovery_unseen_seed_verify.py \
  --output-dir baselines/e2_alns/e2_loss_recovery_20260711/unseen_seed_4000_gate
```

验收器必须得到57行且逐解复算成本和违规，同时核对矩阵、4000评价、hash和运行源码。启动前还必须确认当前求解器文件与通过短门的候选一致，不得带入新的未验证修改。

## 目的

如果比例true-LNS短门通过，不能立即用已经看过的seeds1--5宣布成功。本门用未参与候选开发的seeds6--8，验证改善是否能迁移到新的随机搜索轨迹，然后才决定是否重跑论文种子。

## 固定矩阵

负例高发规模固定为`15c、20c、50c、75c、100c、150c`，每档seeds6--8。另加`200c seed6`作为大规模强项防退化样本。共19个实例-种子配对。

每个配对运行三种算法：冻结staged hybrid、比例true-LNS-middle候选、LNS。每次4000次真实评价、280 kWh任务内覆盖、正式`make_shared_initial_solution`、LNS共同预处理设置不变。总计57次运行，最多3个CPU worker，任务独立落盘并支持resume。

## 晋级条件

所有57次必须`OK`、严格4000评价、零违规、保存解复算和hash通过。科学门同时要求：候选相对staged的19组平均改善大于0；候选对LNS的负例数至少比staged少2组；六个负例高发规模中至少四个规模的候选均值不差于staged；任何规模候选均值相对staged不得退化超过2%；200c seed6相对staged不得退化超过2%；候选相对LNS的总体配对中位数不得低于staged。

## 通过后的动作

只运行九档×seeds1--5的最终候选45次。冻结LNS及其他基线若代码、场景、起点、预算和hash合同未变则复用，不重复烧算力；合并后重新统计45组胜平负、逐规模均值/中位数/最坏值、总体均值与bootstrap区间。只有新证据确实减少15负，才更新论文候选；旧E2冻结证据继续保留。

## 失败后的动作

不得换未见种子、删失败行或降低门槛。比例true-LNS路线关闭，回到`e2_loss_recovery_literature_contingency_20260711.md`规定的只读结构证据门；不启动正式矩阵、80 kWh或16000评价。

## 红线

禁止修改`cost.py`、`check.py`、`search/evaluation.py`、价格、物理约束、算例、LNS基线或预算记账。禁止把本门的seeds6--8并入seeds1--5正式配对后假装样本独立；两组证据必须分开报告。
