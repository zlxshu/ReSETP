# 门二 D3：多车场适用域当前源码重放

**结论：PASS_D3_MULTI_DEPOT_CURRENT_SOURCE。** 本次按用户更正只在 45 个多车场实例上重放，未复用旧 PASS。搜索空间硬锁、完整候选守卫、路线池初筛与 MIP 二次过滤、最终证书守卫四层均通过；LOCK 为 0 跨场，FREE 在每个适用实例均可构造跨场服务。当前源码哈希见 `metadata.json`。

36 个单车场实例不含跨场拓扑，按适用域排除，不计作失败：

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
