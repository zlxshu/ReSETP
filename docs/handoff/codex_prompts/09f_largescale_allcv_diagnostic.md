# 提示词⑨f — 在"全油车占优"的大算例上诊断真凶(承接 09e,内存覆盖、不改文件、碳价钉死)

> 先读 `HANDOFF.md` + `baselines/e2_alns/instance_param_diagnostic.md`(09e) + `throughput_halt_report.md`(09d)。M1 系统 Python、`codex/reporting-pipeline`。**诊断,不改算法、不动碳价、不改文件参数(全用内存 `dataclasses.replace` 覆盖)。**

## 为什么要这一步(09e 的修正)
09e 在小算例(25c/50c)上跑,发现**固定真实碳价下 mixed 本就 < cv_only(3/3),没有全油退化**。说明**全油车占优是"大算例"现象**(09d 里 LNS 全油在 threeshift 100/150/200c 占优、尤其 200c+3.45%)。**所以诊断必须搬到这些大算例上,并用 LNS 级的强全油参考解**(09e 的 solver cv_only 可能弱于 LNS 的全油)。

## 关键要分清的两件事(报告必须明确回答)
在大算例上,"全油更便宜"到底是:
- **(经济/参数真凶)** EV 在长路线上撑不住 80kWh、被迫上贵公共快充(£0.82/kWh + £0.50/min 占用)→ 全油**真的**更优;还是
- **(算法没找到)** 好的混合解其实存在(EV 本可靠便宜场站电跑完),只是求解器在大规模下没找到 → 是算法问题不是经济问题。

## Phase 0 — 复现 + 取强参考解(大算例)
- 算例:`e2-threeshift-100c-01 / 150c-01 / 200c-01`(全油占优最明显),可加 `e2-multidepot-100c-01 / vanilla-100c-01` 交叉。
- 每个算例取三种**尽量强**的解(够预算,别欠跑):**LNS 全油解**(现成强全油参考)、**solver cv_only**、**最强 mixed**(自由混合,用现有最好算法+够预算)。确认在大算例上确实 全油 ≤ mixed(复现 09d)。

## Phase 1 — 成本分解 + EV 充电行为(大算例,不改参数)
对 全油 vs 最强 mixed 解,报**完整成本分解**(`cost_fix/cost_km/cost_fuel/cost_elec/cost_occ/cost_carbon/total`)并排;对 mixed 解报 **EV 充电行为**:公共 vs 场站充电能量与花费、占用费、充电绕行、**多少 EV 路线撞 80kWh 上限/被迫公共充电、单条 EV 路线平均里程 vs 满电续航**。→ 实锤 mixed 在大算例输在哪一项,以及 EV 是不是真被长路线逼上贵公共充电。

## Phase 2 — 控制变量单参数扫描(内存覆盖,碳钉死,大算例)
每次只改一个非碳参数(其余真实、碳价钉死 0.05034),看**哪个把大算例的"全油 ≤ mixed"翻成"mixed < 全油"**:
- 电池 `B_battery_kwh`:80/160/320/480;速度 `v_speed_ms`:25/16.7/11.1;公共电价 `electricity_price(+station)`:0.82/0.40/0.1853;占用费 `occupancy_fee`:0.50/0.10/0。
- **优先 re-optimize**(覆盖能穿透求解器时,在新参数下重求最优车队);若只能 `fixed_replay`(09e 退路),就对**强参考解**(LNS全油 + 最强mixed)在新参数下重算(注:改电池/电价会改 mixed 的充电调度与成本,fixed_replay 对"充电成本类参数"仍有效,对"需要重路由才体现的参数"要注明局限)。
- 报每参数值下 全油/mixed 最优成本 + mixed 是否反超。

## 结论(报告一句话)
大算例"全油占优"的真凶 = **经济/参数(哪个)** 还是 **算法没找到混合解**;若是参数,哪个非碳参数(最可能电池续航/速度)更新到什么现实值能让大算例也"混合最优";若是算法,指出 mixed 解差在哪、是否需要更强混合搜索。**诚实:数据指向哪个写哪个,别预设。**

## 边界
- 不改文件参数/不动算法/不碰碳价;纯内存 `dataclasses.replace` 覆盖。
- 禁改 `cost.py`/`check.py`/`evaluation.py` 语义。
- 系统 Python + `PYTHONHASHSEED=0`;零违约;跑不出诚实 HALT。

## 交付
`baselines/e2_alns/largescale_allcv_diagnostic.md`(Phase1 分解+充电行为 + Phase2 扫描表 + 经济vs算法结论)+ 诊断脚本 + commit(写 hash)。
