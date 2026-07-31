# 首次启动预检记录

首次监控启动未把 `OMP_NUM_THREADS`、`OPENBLAS_NUM_THREADS`、
`MKL_NUM_THREADS` 和 `VECLIB_MAXIMUM_THREADS` 的冻结值传给子进程，
运行器在进入任何 JOINT 单元之前以
`HALT_THREAD_ENV_NOT_FROZEN` 停止，完成单元为 0/20。

本目录原样保留该次预检的报告、日志、四件套和监控现场。旧停机报告中的
“发现逐位不一致后停止”是通用停机模板的不准确措辞；实际错误和 traceback
均明确为线程环境预检失败，没有产生可供比较的科学结果。正式回放随后从
0/20 重新启动，并使用四个线程变量均为 `1` 的冻结环境。
