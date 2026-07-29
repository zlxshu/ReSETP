# 门二 D3：当前源码零搜索重放

**结论：HALT_TREATMENT_CROSS_SITE_NOT_CONSTRUCTIBLE_FOR_36_SINGLE_DEPOT_INSTANCES。** 当前源码哈希已重新登记，未沿用 2026-07-24 的旧 PASS。搜索空间硬锁、完整候选守卫、路线池初筛与 MIP 二次过滤、最终证书守卫均在当前源码上闭合；新 D2-A witness 对 81 个实例的控制臂重放均为 0 违约、0 跨场。

严格逐实例条件仍未通过：只有 45/81 个多车场实例能够构造处理臂跨场服务；其余 36/81 个实例只有一个车场，不存在不同的服务车场，因此即使 `hard_home_depot_lock=False` 且 `Exchange11` 启用，跨车场服务仍在拓扑上不可能。不能把“删除锁维度/算子启用”的结构开放性改写为这 36 个实例上“可以产生跨车场服务”。

36 个反例为：

- `cn-cy-10c-01-V2-LOCATIONS`
- `cn-cy-10c-02-V2-LOCATIONS`
- `cn-cy-10c-03-V2-LOCATIONS`
- `cn-cy-15c-01-V2-LOCATIONS`
- `cn-cy-15c-02-V2-LOCATIONS`
- `cn-cy-15c-03-V2-LOCATIONS`
- `cn-cy-20c-01-V2-LOCATIONS`
- `cn-cy-20c-02-V2-LOCATIONS`
- `cn-cy-20c-03-V2-LOCATIONS`
- `cn-cy-25c-01-V2-LOCATIONS`
- `cn-cy-25c-02-V2-LOCATIONS`
- `cn-cy-25c-03-V2-LOCATIONS`
- `cn-jjj-10c-01-V2-LOCATIONS`
- `cn-jjj-10c-02-V2-LOCATIONS`
- `cn-jjj-10c-03-V2-LOCATIONS`
- `cn-jjj-15c-01-V2-LOCATIONS`
- `cn-jjj-15c-02-V2-LOCATIONS`
- `cn-jjj-15c-03-V2-LOCATIONS`
- `cn-jjj-20c-01-V2-LOCATIONS`
- `cn-jjj-20c-02-V2-LOCATIONS`
- `cn-jjj-20c-03-V2-LOCATIONS`
- `cn-jjj-25c-01-V2-LOCATIONS`
- `cn-jjj-25c-02-V2-LOCATIONS`
- `cn-jjj-25c-03-V2-LOCATIONS`
- `cn-prd-10c-01-V2-LOCATIONS`
- `cn-prd-10c-02-V2-LOCATIONS`
- `cn-prd-10c-03-V2-LOCATIONS`
- `cn-prd-15c-01-V2-LOCATIONS`
- `cn-prd-15c-02-V2-LOCATIONS`
- `cn-prd-15c-03-V2-LOCATIONS`
- `cn-prd-20c-01-V2-LOCATIONS`
- `cn-prd-20c-02-V2-LOCATIONS`
- `cn-prd-20c-03-V2-LOCATIONS`
- `cn-prd-25c-01-V2-LOCATIONS`
- `cn-prd-25c-02-V2-LOCATIONS`
- `cn-prd-25c-03-V2-LOCATIONS`

逐实例四层结果和反例字段见 `raw_runs.csv`，当前源码哈希见 `metadata.json`。
