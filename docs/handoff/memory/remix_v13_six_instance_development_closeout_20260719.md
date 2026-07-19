# ReMIX V13 六题开发门收口

日期：2026-07-19

陈雨蝶式比较基础已经闭合：公开主场为带可验 BKS 的
`V13-MDVRPTW-28`，China81 是唯一完整模型赛场。接线门、PR17A 行为门和
PyVRP 0.12.2 HGS 到 0.13.4 ILS 路线桥均通过，说明实现路径、计数和验解可用。

第一个完整 ReMIX 候选把 HGS 首可行供料、缩短版 ILS、五轮路线交换—拆解重建—
局部搜索和一次 MILP 路线会审放在同一十秒上限内。六题结果为 `0 胜、0 平、6 负`，
新 BKS 为 0；所有题的较强可运行核心都是完整预算 PyVRP 0.13.4 ILS。全部 18 个
方案独立有效，全部运行不超过十秒，保护文件未变；清理 AppleDouble 后 34 个证据
哈希复算失败 0。

死因是预算架构：ReMIX 把 ILS 从 8.5 秒削到约 6.19--7.01 秒，其他层没有补回
损失。PR11A 路线会审对缩短版 ILS 只改善约 0.074%，仍输完整预算 ILS；其余五题
没有净改善。原脚本标签 `HOLD_MIXED` 语义不准确，权威判定为
`STOP_CURRENT_REMIX_V13_CANDIDATE_ALL_LOSS`。

当前停止，不进确认块、完整 28 题、China81 或阶段二。若用户复盘后批准继续，下一
候选只能先验证“完整 ILS 主循环内，以 ALNS 式多车场/时间窗大扰动替换一次原有扰动”
的深度融合；不再并排启动 HGS 首解、重复局部搜索或常开末尾路线会审。再次出现任一
负或零严格胜，则关闭当前公开逐题超越路线，不靠延时、换题、平均数或参数网格救援。

权威尸检：
`docs/handoff/remix_v13_development_forensics_20260719.md`。
证据：
`baselines/algorithm_foundation/remix_v13_six_instance_development_20260719/`。

主稿同步删除旧 Solomon 56题门和“PyVRP 0.13.4为HGS”的错误说法，改用
V13-MDVRPTW 28题与职责化对手表；Vidal等（2013）和Lei、Hao（2026）已进入
参考文献。正式V13结果文件不存在时原子门保持关闭。XeLaTeX/latexmk双遍通过，
24页A4，无未定义引用或overfull。
