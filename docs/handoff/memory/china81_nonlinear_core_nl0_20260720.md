# China81 非线性充电核心 NL0

日期：2026-07-20

权威判定：`PASS_NL0_PRODUCTION_CHARGING_CURVE_CORE`

用户授权在公开算法线按预登记止损后转向 China81，并以最终性能和后续 E1--E7 可用性
为中心自主推进。分批合同为
`docs/handoff/china81_nonlinear_core_g1_contract_20260720.md`。

NL0 新增唯一纯数学内核 `solver/src/setp_solver/charging_curve.py`，合并归一曲线缩放、
累计时间及逆函数、可达电量、多趟后向递推、精确分时电量和候选开始时点。它没有修改
`cost.py`、`check.py`、`prices.py`、`search/evaluation.py`、主 TeX 或正式搜索入口。

全量验证逐行读取既有冻结 `action_replay.csv` 的 264,600 行：261,027 个可行动作的
持续时间不一致为 0、分时电量不一致为 0，两个最大误差均为 0；恒功率退化网格失败
为 0，最大浮点误差约 `7.28e-12` 秒。24 项目标数学/旧回归测试和 Ruff 均通过，保护
文件 Git diff 为零，10 件登记制品哈希复算一致。

开发期两个错误原样记录：未设置仓库 `PYTHONPATH` 导致导入前失败；相邻断点数组误用
`zip(strict=True)` 导致曲线构造测试失败。均在正式证据生成前修复，没有进入搜索或
改变输入/判据。

本门只证明统一数学内核可接线，不授权 China81 搜索或算法性能主张。下一门固定为
NL1：解结构与多趟排班/证书同批接入；NL1 通过后先做三个事前固定 China81 开发实例
的零搜索物理预检。真正胜负探针必须等待 NL2 成本与检查器闭合。
