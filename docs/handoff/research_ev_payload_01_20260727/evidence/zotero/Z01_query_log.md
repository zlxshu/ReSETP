# Z01 Zotero 检索与只读取证日志

- captured_at: 2026-07-27T21:44:59+08:00
- zotero_sqlite: /Users/zhouleixishu/Zotero/zotero.sqlite
- zotero_sqlite_sha256: cb70fd7cd34c55371eaf365de296620ac0c9fd7961a5a3835d9c59237cf7ff39
- database_open_mode: SQLite URI immutable=1（只读）
- user_library_in_sqlite: libraryID=1
- local_api_required_user_id: userID=0

## userID 0 切换记录

先按任务要求执行本地模式切库：

```text
ZOTERO_LOCAL=true python -m zotero_mcp.cli_standalone library switch --library-id 0 --library-type user
Error: Could not access library 0 ... Operation not permitted
```

失败原因是当前 workspace 沙箱禁止访问 Zotero 本地 HTTP 端点；此前通过未切库的 CLI 检索为空。为避免把“空结果”误当成库中无文献，后续使用同一 Zotero 数据目录下的 `zotero.sqlite`，以 `immutable=1` 只读打开底层 user library。没有写入、迁移或修改 Zotero 库。

## 检索词与纳入规则

检索词包括 `electric vehicle routing`、`mixed fleet`、`EVRP`、`物流车`、`电动车辆路径`。按 DOI 或题名去重。纳入条件为：Zotero 中有本地全文；研究同时包含电动车与燃油/常规车辆；正文或表格可提取两类车辆的数值载重。纯电单车型研究以及不能提取两类载重数值的文献不进入计数。

因此，报告中的 6 篇是“本地 Zotero 库内符合上述条件的定向样本”，不是对全部 EVRP 文献的系统综述。
