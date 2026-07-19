# MPILS-MVNS-C2 G1 搜索前启动失败留痕

日期：2026-07-20。

这两次失败均发生在任何 B 题求解开始以前，没有创建 G1 结果目录，没有消耗首发性能
次数，也没有改变算法、常数、实例或判据。

第一次使用 `/opt/anaconda3/bin/python3.13` 启动外层运行器。运行器导入独立验解模块
时，该环境没有 PyVRP，立即报 `ModuleNotFoundError: No module named 'pyvrp'`。
处理：改用合同已冻结的
`build/python_envs/pyvrp-0.13.4/bin/python` 启动同一运行器，不改代码。

第二次在祖先检查处停止。`git merge-base --is-ancestor` 成功时退出码为零但不输出
文本；运行器错误地把空文本当成检查失败。处理：保留命令的 `check=True` 退出码硬门，
删除对标准输出文本的错误布尔判断。该修复只影响搜索前 Git 血缘检查，不影响求解器、
随机数、参数、实例、计时或结果判定。
