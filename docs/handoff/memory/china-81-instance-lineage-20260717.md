# 中国 81 个自建算例谱系与数据边界（2026-07-17）

## 当前状态

用户最终确认三区域（京津冀、珠三角、成渝）各自覆盖 9 个客户梯度：10、15、20、25、50、75、100、150、200；每个梯度有 01/02/03 三个不完全一致变体，共 81 个。10--25 客户为 1 个车场，50--100 为 2 个车场，150--200 为 3 个车场；所有算例为 24 小时三班（00--08、08--16、16--24），同时具有公共充电站和车场充电字段。

构造结果位于 `data/ChinaInstances/CHINA81_DRAFT_20260717_source_bound/`，81/81 结构门通过，搜索评价=0。构造器为 `baselines/china_instances/build_china_81_source_bound_instances_20260717.py`，权威设计为 `docs/handoff/china_81_instance_design_20260717.md`。旧 C31 3×3 目录只作历史探针，不得混入当前 81 集。

最终复核：`baselines/china_instances/test_china_81_source_bound_instances_20260717.py` 定向测试 3/3 通过；Ruff 和 `py_compile` 通过；正式输出没有 `._*` 旁文件；总 `artifact_hashes.json` 排除自身和旁文件；各实例 `source_manifest.json` 排除自身后逐文件哈希复核通过。

## 数据来源边界

- 客户地点：已有 OpenStreetMap Map API 快照中的命名 POI，保留 OSM 类型、编号、名称/品牌、源响应哈希；这是实际地图标注，不是政府经营主体名录。
- 车场：OSM `landuse=industrial` 工业候选；未人工核验前不能写成运营物流园。
- 公共站：OSM `amenity=charging_station`；多数站点没有正数容量/功率标签，1 桩和 60 kW 是显式派生默认。
- 需求、服务时长、时间窗：逐客户继承 Goeke--Schneider `E-UK{N}_{01/02/03}.txt`，源行号和哈希进入 `source_manifest.json`；将 9 小时源窗按 8/9 缩放后放进三班。不能称中国真实订单。
- 碳：仓库 `china_tvci_source_gate_20260717_v2` 的中国省级 S1-2025 预测数据，不能称实测实时碳强度。
- 距离：当前为局部投影直线距离×1.4，仅为 DRAFT；路网矩阵仍是正式冻结前的阻断项。

## 不能越过的门

结构门通过不等于正式实验授权。正式搜索前仍需用户终审、车场/充电站核验、距离矩阵决定、价格合同、零 EV 源变体的混合车队下界裁决，以及既定 E7、ALNS G0、非线性内核和统一重跑顺序。
