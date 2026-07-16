# E2 CVRPLIB公开BKS层：E7结束后的启用清单

日期：2026-07-16  
状态：`DEFERRED_UNTIL_E7_RELEASES_SHARED_KERNEL`

## 1. 目标

在E7及其当前算法版本证据闭合后，安全恢复E2公开BKS实验所需的三个真实评价计数字段，重算正式合同，并运行6个CVRPLIB公开最优算例×10个种子×4000次完整方案评价。该实验区分基础CVRP搜索能力与本文完整模型求解能力，不改变E7结果，也不把新旧算法版本混入同一论文证据。

## 2. 启用前硬门

1. E7监控已经产生完成事件，或用户明确确认共享内核不再受任何活跃冻结合同保护；不得只因CPU空闲推断E7结束。
2. 不存在`e7_parent_child_recovery_runner_20260716.py`或其他绑定`winner.py`冻结哈希的活跃进程。
3. `solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py`的SHA-256必须为：

   ```text
   0eb31fd5c90aaf923db4edd511f4cb102487887f6b213740db9c93e8ec02101b
   ```

4. 下列补丁必须可无冲突应用：

   ```bash
   git apply --check docs/handoff/patches/e2_cvrplib_winner_metrics_20260716.patch
   ```

5. 正式输出目录`baselines/e2_alns/cvrplib_optimal_search_formal_20260716`不存在或为空。存在任何合同、断点或失败残留时保存现场，不覆盖。

## 3. 补丁重放与验签

执行：

```bash
git apply docs/handoff/patches/e2_cvrplib_winner_metrics_20260716.patch
```

应用后必须同时满足：

```text
winner.py SHA-256 = 0e49a7fc7b94e4ec6db30935accb185d4cb17b47cbef9fc42c77450a1068e61d
git diff --check = PASS
winner.py diff = 补丁本身，无附带修改
```

补丁只把`candidate_scores`、`repair_scores`和`repair_delta_count`暴露到既有返回载荷，并删除三个未使用导入；不改变搜索动作、接受规则、评价预算、目标函数或可行性语义。

## 4. 零搜索合同门

补丁验签后，先使用runner的合同构造入口重算而不启动搜索。合同必须固定：

```text
实例：X-n101-k25, X-n120-k6, X-n200-k36,
      X-n214-k11, X-n313-k71, X-n322-k28
种子：1--10
评价预算：4000
workers：4
单任务上限：1800 s
PYTHONHASHSEED：0
Python：/opt/anaconda3/bin/python3.13
NumPy：2.3.5
```

正式合同应覆盖runner登记的全部求解源码和18个bundle文件。旧SHA-256=`2ff322e1...12e77`只代表此前补丁生效时的开发快照；重新启用时必须记录实际重算哈希，不得因为期望相同而跳过核验。

## 5. 定向测试

```bash
PYTHONHASHSEED=0 /opt/anaconda3/bin/python3.13 -m pytest -q \
  solver/tests/test_e2_cvrplib_formal_runner_20260716.py
```

全部测试通过后才允许启动。不得再对六个冻结测试算例做结果导向的调参或搜索型冒烟。

## 6. 正式命令

正式搜索必须由`codex-experiment-monitor`在非沙箱环境启动：

```bash
PYTHONHASHSEED=0 /opt/anaconda3/bin/python3.13 \
  baselines/e2_alns/run_cvrplib_optimal_benchmark_20260716.py \
  --out baselines/e2_alns/cvrplib_optimal_search_formal_20260716 \
  --instances X-n101-k25 X-n120-k6 X-n200-k36 X-n214-k11 X-n313-k71 X-n322-k28 \
  --seeds 1 2 3 4 5 6 7 8 9 10 \
  --eval-budget 4000 \
  --workers 4 \
  --max-runtime-seconds 1800
```

监控AI保持关闭；健康运行不人工轮询。失败、超时、Gap波动和不利结果全部保留。

## 7. 失败关闭语义

当前E7冻结版`winner.py`不返回E2所需的真实计数字段。正式runner现于环境核验后、创建任务和启动搜索前直接解析`_run_staged_hybrid_entry()`的返回字段；若缺少`candidate_scores`、`repair_scores`或`repair_delta_count`，立即以`FormalRunError`停止。因此，漏打补丁不会再浪费一次搜索，也不会伪造计数或形成合法OK断点；目标哈希门仍是强制项。定向回归20项通过。

## 8. 结果后的唯一判定

先生成正式五记录面和论文证据表，再按预注册规则判断：孤立算例、单个种子或runner配置问题不触发算法换代；只有跨小、中、大规模和多个种子的一致短板，且能够归因于搜索结构，才允许一次ALNS协调大修。若换代，受源码影响的E2--E7必须在同一新版本下重跑，旧E7只保留为旧版本完整性证据。
