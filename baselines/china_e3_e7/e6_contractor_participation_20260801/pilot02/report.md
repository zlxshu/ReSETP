# E6 四承包商双方法极小试算

15 个非空联盟均完成路线求解。大联盟利润为 52505.941 元；Shapley 个体理性=不满足，核=为空。

大联盟成本 7810.559 元与四家单干成本之和相同；各家合作后利润也与单干相同。利润下限从 0 到 1 的所有取值都返回相同成本和利润，因此本次试算没有激活合作或利润约束效应。

路线池含 27 条候选路线；利润下限共试 22 个点，可行 22 个，最高可行 theta=1.0。

六项账目闭合残差最大值为 9.095e-13 元。

收入按实际配送路线归其承包商；跨场成本保持输入参数，当前为 0。本结果只验证两种方法接线，不是正式实验结果。
方法 A 对齐饶卫振等（2019，第1518--1520页；2022，第2723、2727--2730页）的先求联盟配送成本、再分配；方法 B 对齐 Soriano 等（第4--7页）的路线优化内利润下限。

运行命令：`OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 PYTHONPATH=solver/src build/python_envs/pyvrp-hgs-0.12.2/bin/python baselines/china_e3_e7/e6_contractor_participation_20260801/run_smoke.py --iterations 10 --archive 2 --theta-step 0.05 --mip-seconds 2 --cross-site-cost 0 --output pilot02`。

仍需用户决定的只有非零跨场真实成本的业务含义和取值；本实现没有给它默认非零值，也没有把内部转移支付重复计入系统成本。
