# S2-REV-V2 统计收口任务卡

本修订只处理已完成 S2 的一条确定性不可行记录，不重跑、不换种子、不改 raw、不改完成器、评价器、时窗或 route-proxy 定义。

原始证据 decision.json、report.md 和 raw_runs.csv 原样保留，原判定 HALT_S2_VIEW_INFEASIBLE_OR_ERROR 不回写。v2 只新增独立判定与报告：

- 810/810 新单元均有 raw 行；809 行 OK，1 行 ERROR，按登记条目 S2-INFEASIBLE-UNIT-001 分类为 INFEASIBLE。
- 失败单元固定为 cn-jjj-200c-01-V2-LOCATIONS、seed 2、naive_ev/HGS-E；完整模型下 C099 迟到 0.388 秒。
- 统计时该题 HGS-E 只用其余 4 个可行种子计算 Best/avg，并在报告和后续表注披露；不删除失败行。
- HGS-F/cv_only 405/405，HGS-E/naive_ev 404/405，HGS-M/mechanism_ev 405/405、MV-HGS-SP 405/405 均含 P3 只读复用。
- v2 通过后，S3 及后续读取 v2 判定；若 S3 同类失败，原样记入并按登记的单臂失败率超过 5% 停止。

保护边界：cost.py、check.py、search/evaluation.py、prices.py、P3 raw 和主 TeX 零改。产物排除 AppleDouble、缓存和临时文件；发现 AppleDouble 时标记 HASH_CONTAMINATED_APPLEDOUBLE，清理后重算 hash。
