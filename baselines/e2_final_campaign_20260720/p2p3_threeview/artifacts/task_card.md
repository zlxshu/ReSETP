# S5 统一表图生成任务卡

仅从已封存的 S2/S3/S4 CSV、轨迹、witness 和 P1 `decision.json` 生成表4、表5、表6、图4、附录 A1；不读取或修改论文 TeX 语义段，不手工修图。

图4使用 S3 四臂 exact incumbent 轨迹，按 10 个 seed 在共同时间网格上取 step-wise median；时间轴为分钟，成本为元，4.30×2.80 inch，0.62 pt 曲线、异线型、无网格、四边框、图例右上，输出矢量 PDF 与 300 dpi PNG。表4直接使用 S4 独立复算 CSV，表5从 P1 已封存 `table5` 和 raw runs 计算 Best/Avg，表6从 S3 raw 计算每臂 10 seed 的值/CPU 及 Min/Avg/Max。

生成脚本只在所有输入 gate PASS 且字段/行数完整时输出 `PASS_S5_ARTIFACTS`；否则 `HALT_S5_INPUT_GATE`，不补值、不改结果。
