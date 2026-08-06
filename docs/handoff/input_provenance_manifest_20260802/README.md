# China81 输入来源登记（2026-08-02）

状态：`COMPLETE`。本目录是后续正式包 metadata 登记 China81 输入哈希的来源，不改写任何历史 metadata。

`manifest.json` 逐文件登记四条 authority 的 572 个唯一有效输入，并另列 `orders.csv` 与 vehicle lock，共 574 条。每条含仓库相对路径、当前 SHA-256、所属 authority、适用算例，以及实际使用它的正式包注册 ID；正式包 ID 的完整路径、实例范围、调用行号和证据文件 SHA-256 见 `usage_package_registry`。

核验依据为 `docs/handoff/legacy_sweep_round2_20260802/instance_hash_audit.json:25-29,31-7174,7175-15360,15361-15374`，源文件 SHA-256 为 `f4f22affda220eaa8a8ef56a711e9d12794e12cc5190e661822532096216d0c9`。本轮对 572 个 authority 输入逐个重算，`572/572` 与审计哈希一致；两个追加输入也 `2/2` 一致。原 2,838 份 metadata 对 572 个输入的三类直接 hash 声明仍为 `0`，本目录只补记录边，不回写旧包。

vehicle lock 的登记关系与 `orders.csv` 不同：`orders.csv` 由 `solver/src/setp_solver/china81.py:248-252` 直接读取；vehicle lock 仅在 `solver/src/setp_solver/china81.py:430-440` 被写入 bundle 的 `source_paths`，当前 loader 没有打开该文件。因此 manifest 对前者使用 `DIRECT_RUNTIME_READ`，对后者使用 `LOADER_SOURCE_PATH_DECLARATION; FILE_NOT_OPENED_BY_CURRENT_LOADER`，不把声明路径写成已读取事实。

本目录没有运行实验，没有修改输入、源码、正式包或论文。
