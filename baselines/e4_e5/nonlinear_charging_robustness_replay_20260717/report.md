# 非线性充电固定方案稳健性复算

判决：`PASS_NL_CHARGING_REPLAY_CORE_UPGRADE_REQUIRED`。搜索次数为0，路线、客户归属、车辆、充电地点和充电量均未改变。

独立L->L复算覆盖132300次动作，最大实际排放误差为2.842e-14 kg，最大电量误差为5.684e-14 kWh。

| 曲线 | 客户归属 | 经营方式 | 网络轴平均充电减排 | 改善网络 | 改善电网日 | 固定原时刻不可行 | 方向反转 |
|---|---|---|---:|---:|---:|---:|---:|
| NL90_mild | geographic | ownership_fixed | 3.977% | 9/9 | 19/28 | 4 | 6 |
| NL90_mild | geographic | reassignment_allowed | 4.207% | 9/9 | 19/28 | 48 | 1 |
| NL90_mild | mixed | ownership_fixed | 3.134% | 9/9 | 18/28 | 93 | 4 |
| NL90_mild | mixed | reassignment_allowed | 3.688% | 9/9 | 16/28 | 144 | 3 |
| NL80_stress | geographic | ownership_fixed | 4.002% | 9/9 | 19/28 | 56 | 5 |
| NL80_stress | geographic | reassignment_allowed | 4.130% | 9/9 | 19/28 | 65 | 4 |
| NL80_stress | mixed | ownership_fixed | 2.244% | 7/9 | 16/28 | 283 | 14 |
| NL80_stress | mixed | reassignment_allowed | 2.759% | 7/9 | 17/28 | 236 | 5 |

主曲线需升级核心模型：`True`；主曲线不可行seed-day方案168个，方向反转14个。

强压力曲线不可行seed-day方案476个，方向反转28个。两条曲线必须同时保留。

车场桩容量使用客户数上界，因而零冲突只能说明容量不绑定，不能证明有限共享桩机制有效。
