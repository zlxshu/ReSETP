# Homberger 200客户开发bundle适配门

状态：`PASS_HOMBERGER_200_DEVELOPMENT_BUNDLE_GATE`。本门只转换和核验数据，搜索评价次数为0，不授权算法胜负实验。

## 作用

12个预注册Homberger 200客户实例用于G1/G2算法开发，不进入Solomon 56例最终测试。开发集只提供问题输入，不保存BKS数值、参考代码或详细路线，从数据层阻断测试集调参和参考答案泄漏。

## 输入与输出

输入为SINTEF官方压缩包中冻结的`C1/C2/R1/R2/RC1/RC2`六类各首末两个实例，来源门为`baselines/e2_alns/e2_homberger_200_source_gate_20260717_v2/`。转换脚本为`baselines/e2_alns/build_homberger_200_development_bundles_20260717.py`，权威输出为`baselines/e2_alns/homberger_200_development_bundles_20260717/`。

每个bundle包含：201个节点的`instance.json`、按原始整数坐标重新计算的双精度欧氏距离矩阵，以及只为通用加载器占位且不进入VRPTW目标的零碳曲线。元数据固定为50辆同质燃油车、原算例容量、硬时间窗和“先最少车辆、再最短距离”的分层目标。

## 验证

逐例核对源文件哈希、节点0--200、车辆上限、分组容量、需求、服务时间和时间窗；随后用项目通用bundle加载器逐字段回读，并以`1e-12`绝对容差核验201×201双精度距离矩阵。12/12例通过，所有搜索可读`instance.json`均不含`bks`字段或字符串。

`solver/tests/test_homberger_200_source_gate_20260717.py`、`solver/tests/test_homberger_200_development_bundles_20260717.py`、Solomon适配器和正式runner相关测试合计33项通过；Ruff、py_compile、diff检查和AppleDouble检查通过。

## 下一门

E7十步收口和ALNS预算G0闭合之前不得启动G1。G1严格使用12例×3种子×1600次完整候选评价，候选与冻结基线共同起点；开发结果不得并入Solomon最终测试表，也不得单独支持算法领先主张。
