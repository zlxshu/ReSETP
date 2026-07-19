# AppleDouble 哈希清单无重跑修复

- 判决：`PASS_APPLEDOUBLE_HASH_MANIFEST_REPAIR_NO_RERUN`
- 修复清单：10。
- 普通证据文件的旧SHA-256全部保持一致。
- 只从哈希清单删除`._*`旁车项并重新验签普通文件。
- 算法重跑0，搜索评价0；修复前后清单均保留。
