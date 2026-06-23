# 提示词⑨g — 决定性确认:城市配送参数下"混合最优 + ALNS 反超 GLNS"(真实重优化,内存覆盖,不改文件)

> 先读 `HANDOFF.md` + `baselines/e2_alns/largescale_allcv_diagnostic.md`(09f)。M1 系统 Python、`codex/reporting-pipeline`。**确认性测试:内存 `dataclasses.replace` 覆盖、不改任何文件、碳价钉死 0.05034、不改算法。**

## 要确认什么(09f 的关键悬而未决点)
09f(fixed-replay)显示:200c 真·全油最优,而**速度=40km/h 能把混合翻到全油以下**(电池160/便宜电价/零占用费 near-flip);100c/150c 是算法方差。**但直接重优化超时未完成,所以"城市速度→混合最优"还没有重优化级证明。** 本步用**真实重优化**确认两件事:
1. 城市配送参数下,**混合车队真的成为最优**(优化器自选车型时用 EV);
2. 此时**我们的(碳/EV 感知)ALNS 反超无 EV 机器的 GLNS 基线**(且方差收敛、不再像 100/150c 那样不稳)。

## 实验设置(真实重优化,够预算别欠跑)
- 算例:`e2-threeshift-100c-01 / 150c-01 / 200c-01`(覆盖"算法方差档"100/150c + "经济全油档"200c);可加 `e2-multidepot-100c-01`。seed≥5。
- 墙钟:沿用协议(100c=300s/150c+=900s)。**这是少量焦点重优化,不是 09f 那种"参数×重优化"大扫,正常预算即可;若仍太慢,减算例/seed 但必须是真重优化、不得退回 fixed-replay。**
- 三组**内存覆盖情景**(碳价全程钉死真实值),每组都**重优化** 我们的 ALNS(09d 定稿那套)与 GLNS 基线,自由选车型:
  - **(A) baseline**:全真实参数(对照,应复现 200c 全油、ALNS 输 GLNS);
  - **(B) urban-speed**:`v_speed_ms=11.1`(40km/h),其余真实;
  - **(C) urban-speed + modern-battery**:`v_speed_ms=11.1` + `B_battery_kwh=160`,其余真实。
- 每情景每算例报:最优车队 CV/EV 数、是否用 EV(混合是否成为最优)、ALNS vs GLNS 的 best/mean/std + 配对胜负 + Wilcoxon、零违约。

## 判定(报告一句话结论)
- **确认成立** = 在 (B) 或 (C) 下:混合成为最优(EV 被用)**且** ALNS 在 100/150/200c 上 mean 追平/超过 GLNS、方差收敛。→ 证明"城市配送参数 = 解决故事退化 + 算法输 GLNS 的钥匙",据此可建议把主算例/E2 参数标定到城市配送口径(后续单独决定,本步不落盘改参数)。
- **不成立** = 即便城市参数下 ALNS 仍输 GLNS → 则 100/150c 的"算法方差"是独立硬伤,需另解;如实报。
- 诚实:哪组翻、哪组没翻、ALNS 到底反超没有,数据说话,不预设。

## 边界
- 不改文件参数/算例/算法/碳价;纯内存 `dataclasses.replace` 覆盖的确认测试。
- 必须**真实重优化**,不得用 fixed-replay 充当;跑不完就减规模但保持真重优化、诚实 HALT。
- 禁改 `cost.py`/`check.py`/`evaluation.py` 语义;系统 Python + `PYTHONHASHSEED=0`;零违约。

## 交付
`baselines/e2_alns/urban_reopt_confirmation.md`(三情景 × 算例:车队/ALNS-vs-GLNS/方差表 + 结论)+ 脚本 + commit(写 hash)。
