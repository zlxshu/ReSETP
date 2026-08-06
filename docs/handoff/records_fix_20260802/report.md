# Z2 记录层修复报告

任务编号：`Z2`

日期：`2026-08-02`

终态：`Z2_RECORDS_FIX_PARTIAL__X2_DF_007_HALTED`

## 结论

六项中五项完成，`X2-DF-007` 按停止条件标为 HALT。HALT 原因不是用户决议缺失，而是指定的第二条 `resolved_by` 目标 `baselines/china_e3_e7/blocker_fix_20260802/` 不存在，无法登记该包的字段与 SHA-256。其余五项均已完成补记或清单。未修改 `docs/paper_v2/paper_main.tex`，未修改源码，未删除或移动文件，未运行实验。

本轮直接依据为 `docs/handoff/legacy_sweep_20260802/legacy_ledger.json`（SHA-256 `78c73657c65eff0b47b7a69da0b6ea0ae7d6fafac13fbb9a3d9acf8972d56b01`）与 `docs/handoff/legacy_sweep_round2_20260802/legacy_ledger_round2.json:58-160`（SHA-256 `e678744c042d7237a0410b4f7fa9dc1fe4dd6a6187d92091561a4d460586d7e6`）。

## X2-DF-007 — HALT

在 `docs/handoff/model_change_approval_register_20260718.md:2498-2504` 追加“决议状态补记”。原 `AWAITING_USER_DECISION` 段、M1/M2 选项和旧包单趟边界仍完整保留在该文件 `:2491-2493`；文件由追加前 SHA-256 `e4ed91503fccb7773a936e6af188e1df2d499b37b27b04244a33050650e00b49` 变为 `aad0f09c75803113fa6000a576da5996d411b94cd4a622d8133c45ca8e56a1ff`。

追加内容把用户“打开”的决议绑定到 `docs/handoff/TODO_施工总清单_20260802.md:20-33` 的 B1/C1（字段值：`B1=[x]`、`C1=[ ]`；SHA-256 `56bfebeded7900b06e9af5e86874dba8ab5043b5374fd7d579f89ee6ab8ebdd7`），并明确“多趟由环境变量升级为默认开启的显式模型配置”。指定的 `baselines/china_e3_e7/blocker_fix_20260802/` 经只读核验不存在，因此 `resolved_by[1]` 无字段值和 SHA-256，本项记为 `HALT_REQUIRED_RESOLVED_BY_TARGET_ABSENT`。

现存相关证据 `baselines/china_e3_e7/multitrip_interface_completion_20260802/decision.json:17` 的 `status=MULTITRIP_INTERFACE_COMPLETE`，SHA-256 为 `19b66506e0f5acfa92f010eb3d1bde7df0d17c1ab2634c17196937775b081208`；同包 `report.md:79` 的 SHA-256 为 `b9ff52f621ecb6ed12c31c8a44e242e56f5b5daea559630550c9805c39b3135c`。它只列为相关技术证据，没有替代缺失的指定目标包。

## X2-DF-008 — COMPLETE

在 `docs/handoff/experiment_contract_v2_journal_aligned_20260730.md:115-122` 追加适用范围补记。原合同第 2 节纪律及第 3--7 节历史条款均未改写；文件由追加前 SHA-256 `0e10e8ea20917eb140a945909539cc3ee1e649774758252c0477741d4e742c35` 变为 `f4134443c59b932db0e7c23c76c7f7b4fdacec8abc12f9eb55f23392cc280b10`。

新增字段值为 `scope_status=PARTIALLY_HISTORICAL` 与 `HISTORICAL_SCOPE_20260730_E3_E5_E6_E7`。第 2 节继续作为通用记录纪律；旧并列实验规程只解释历史包，不再授权新实验。新主线指向 `docs/handoff/TODO_施工总清单_20260802.md:10-18,107-136`（SHA-256 `56bfebeded7900b06e9af5e86874dba8ab5043b5374fd7d579f89ee6ab8ebdd7`）和 `docs/handoff/paper_restructure_20260802/SYNTHESIS_施工图_20260802.md:6-18,27-49`（SHA-256 `2e11cd285657592a9d636ed9e74c3e5c86b04df5fb0f8b09772346b9db3e43bf`）。覆盖关系依据 `docs/handoff/legacy_sweep_round2_20260802/docs_supersede_dag.json:summary,conflicting_pairs`，SHA-256 `ad442cdf1e7afb70eef6232a78b9e5d23336b13ccdfb0d3f29822678f58165cf`。

## X2-HR-004 — COMPLETE

新建 `docs/handoff/input_provenance_manifest_20260802/manifest.json`。`docs/handoff/legacy_sweep_round2_20260802/instance_hash_audit.json:25-29` 的字段值为 `unique_effective_four_authority_runtime_inputs=572`、`formal_metadata_hash_claims_on_effective_inputs=0`、`effective_inputs_with_no_formal_metadata_claim=572`，源审计 SHA-256 为 `f4f22affda220eaa8a8ef56a711e9d12794e12cc5190e661822532096216d0c9`。

清单在 `manifest.json:3-11644` 逐文件登记 572 个 authority 输入和 2 个补充输入；每条含 `path`、`sha256`、`authority`、`instance_ids` 与 `used_by_formal_package_ids`。记录 573 为 `orders.csv`，字段 `runtime_relation=DIRECT_RUNTIME_READ`，SHA-256 `a36b833228f9313f02a5e7796156b1f1e0b1a39982e5427c017d25522349c982`；记录 574 为 vehicle lock，字段 `runtime_relation=LOADER_SOURCE_PATH_DECLARATION; FILE_NOT_OPENED_BY_CURRENT_LOADER`，SHA-256 `05078ffd735fc0f17f22b47d0c4d709dab2ba6838c002ab7cd85436010e155a8`。`manifest.json:11657-11664` 汇总字段为 `authority_input_files=572`、`registered_files=574`、`rehash_mismatches=0`；`:11666-末尾` 登记六组正式包实际使用范围及调用证据。清单 SHA-256 为 `8ed7d96ecf5cacc59b1c2eaa61734d380eb5927daea6866ee5b44bb803d3c072`。

同时新建 `README.md`（SHA-256 `a9858c58484b03972d3efbaee5dfdb616e92d30a2b6a5a5a00addfd4cc970cb6`）和目录内 `artifact_hashes.json`，供后续正式包 metadata 引用。

## X2-HR-005 — COMPLETE

源图 `docs/handoff/legacy_sweep_round2_20260802/baselines_reference_graph.json:10-25` 的字段值为 `packages=2838`、`zero_indegree_zero_hash_reference_packages=480`、`formal_marker_packages_among_strict_isolated=21`，SHA-256 为 `a35d23ddd918d6d0ebd0e7a4dc5c824dca609511dc74eab15aca8aa680e40bab`。

新建 `docs/handoff/records_fix_20260802/formal_package_authority_review.json:15-1003`，逐一覆盖上述 21 个包；与源图集合比较结果为 `missing=[]`、`extra=[]`。`:1005-1012` 汇总字段为：承担当前数字 4、已被取代 12、历史 5、删除 0、移动 0。四个仍承担当前数字的包位于清单 `:47-489`：E3 `panel_summary` 补 6 条聚合上游边，E4 三个单题正式包各补 1 条指向输入 provenance manifest 的边（每边列出 13 个实际输入记录及 vehicle-lock 声明记录）。清单 SHA-256 为 `02a620a4744390b52640d4de7555b516504a639e1664283d20948611e8ad962f`。

## X2-HR-006 — COMPLETE

新建 `docs/handoff/paper_number_source_manifest_20260802.json:3-380`，按旧正文中的每个出现位置登记 22 条记录，覆盖 9 个唯一统计量；`:381-387` 的字段值为 `numeric_occurrences=22`、`unique_statistics=9`、`tex_modified=false`。每条含 `paper_value`、`paper_line`、来源包、来源字段、高精度值、舍入规则以及 decision/report 路径与 SHA-256；正文写作“2.95 辆更少”的记录另显式登记由源值 `-2.95` 到绝对幅度的展示变换。清单 SHA-256 为 `5c3ee68ed43602e2689963687c3684aabf22b1c809079566bae17ed02d193bcb`。

E3 汇总 `decision.json` SHA-256 为 `72dbbb1412f2b50096e527845a631930ff9200ea4a56808c7ad3bdd2d7669b87`，`report.md` SHA-256 为 `d9bc01f4e8235d6d623e55c79ff79669ff1a368acdaca7963ccb7663980b2431`。E6 面板包没有名为 `decision.json` 的顶层文件，实际决议文件为 `panel_decision.json`；对应 8 条记录明确写入 `decision_json_sha256=null`、`decision_json_status=ABSENT_IN_SOURCE_PACKAGE; PACKAGE_USES_PANEL_DECISION_JSON`，并登记实际决议 SHA-256 `0c5d7109d6dd4da80c106f73f2d91fe08ca51837a625b0ee7563adcc5b357424` 与 `report.md` SHA-256 `3ee6df2f3caf73b41b7a43cca3e80b9e55ba72020b6bda762b59dd51f77696d2`。E6-S2 的 `decision.json`/`report.md` SHA-256 分别为 `706489c0ff6dc52f61a77cb46e44d2476156674846da2ebcdbd258fef1a7a596`、`a31d4d741b253e3168ed02f8fcb75e3a07bef6a384058108fac8301711259431`。

`docs/paper_v2/paper_main.tex` 核验 SHA-256 始终为 `76425e69ee7e0c0ffe7697dcad72eaf9e6803b95a10ce6ccd383410ffa81096f`，本轮未修改。

## X2-RA-007 — COMPLETE

源图 `docs/handoff/legacy_sweep_round2_20260802/paper_asset_mapping.json:10-25` 的字段值为 `formal_assets=69`、`referenced_formal_assets=5`、`supporting_provenance_assets_not_direct=16`、`orphan_formal_assets=48`，SHA-256 为 `29bcbd20e8b2103179c4dd932576eaede302b8379a886a89c3fa159c6a28bd8c`。

新建 `docs/handoff/orphan_asset_archive_plan_20260802.json:3-542`，把 48 个反向孤儿按 8 个版本包分组；每个文件含路径、SHA-256、字节数、产生批次、映射角色与 `archive_action=PLAN_ONLY_NO_MOVE`，每组含可归档理由。`:543-550` 汇总字段为 `formal_assets=69`、`directly_referenced=5`、`direct_support_assets=16`、`reverse_orphans=48`、`files_moved=0`、`files_deleted=0`。清单 SHA-256 为 `a311450b52b8ced64dd21646bf067c637fb6972a8e9bbf251bf9b774399f50ad`。

## 边界核验

本轮对两个既有记录文件的 Git diff 只有新增行；历史文字没有删除或改写。所有新 JSON 均通过 `jq -e .`。输入清单 572 条与源 authority 哈希逐项重算不匹配数为 0；21 个包集合与源图正式孤立集合完全相等；48 个孤儿路径和 SHA-256 与资产图逐项重算不匹配数为 0。外接盘在本轮涉及位置生成 12 个 `._*` AppleDouble sidecar；遵守“不删除、不移动”边界予以保留，`artifact_hashes.json` 纳入数为 0。

由于 `X2-DF-007` 的指定 `blocker_fix_20260802/` 证据包缺失，本轮不写 `Z2_RECORDS_FIX_COMPLETE`。
