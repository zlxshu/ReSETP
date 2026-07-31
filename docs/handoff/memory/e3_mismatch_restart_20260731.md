# E3-MISMATCH-RESTART-20260731：全量错配复核、三臂预注册与源合同漂移停机

## 终态

- 权威交付目录：
  `baselines/china_e3_e7/e3_mismatch_20260731/`
- `done.json.status=HALT_SOURCE_CONTRACT_HASH_DRIFT_BEFORE_SEARCH`
- 输入审计与预注册完成；probe 0、formal 0、搜索评价 0。
- 四件套、`report.md`、`pre_registration.json`、`halt_evidence.json`、
  监控异常现场与最后写入的 `done.json` 均已封存。

## 81 实例独立复核

复核使用 China81 当前 static-input authority 和官方 loader，枚举全部 81 个实例、
5805 个客户，逐客户比较 `customer_home_depot` 与有向道路
“车场→客户”距离的最近车场。45 个多车场实例、36 个单车场实例全部进入分母；
最近距离并列为 0。

非零错配实例正好 6 个，与
`docs/handoff/adversarial_review_20260731/report.md` 一致：

| 算例 | 错配客户 | 错配率 |
|---|---:|---:|
| `cn-prd-150c-01-V2-LOCATIONS` | 3/150 | 2.000% |
| `cn-prd-150c-02-V2-LOCATIONS` | 2/150 | 1.333333% |
| `cn-prd-150c-03-V2-LOCATIONS` | 4/150 | 2.666667% |
| `cn-prd-200c-01-V2-LOCATIONS` | 7/200 | 3.500% |
| `cn-prd-200c-02-V2-LOCATIONS` | 6/200 | 3.000% |
| `cn-prd-200c-03-V2-LOCATIONS` | 2/200 | 1.000% |

合计 24/5805，错配率 0.413437%。行政责任由客户城市映射到同城唯一车场；道路
最近责任产生两种跨城市流向：东莞→广州 11 个、广州→佛山 13 个。相对行政车场，
道路距离缩短 920.837--6044.788 m，为行政距离的
2.996%--16.513%。六个实例为三个 150c 和三个 200c 复本，预注册以
`cn-prd-200c-01` 作主展示，余下五个覆盖同规模复本与跨规模稳健性；六个自然
非零错配实例全部入选。

## 搜索前预注册

- IND：客户只由 loader `customer_home_depot` 服务，硬责任锁。
- ZONE：客户改由有向道路最近车场服务，硬责任锁。
- JOINT：复用 ZONE 责任图和初解骨架，解除责任锁。
- 效应定义：IND→ZONE 为空间组织价值；ZONE→JOINT 为剩余协同价值；
  IND→JOINT 为总价值。正值表示后一臂成本下降，负值和零值原样保留。
- 六实例×三臂×种子 1--10，共 180 正式单元；按输入错配率递减逐实例完成。
- 长探针锁定 `cn-prd-200c-01`、JOINT、seed 1、cap 1500；正式共同 cap 由
  平台期规则产生，范围 400--1500。
- `pre_registration.json` 在任何搜索前写入，SHA-256 为
  `b5ee52063090041b8a84c65fac7d16f1c158acec88efe60c06107ce0e6b4a414`。

## 停机时序

E3 在等待另一个两-worker ReSETP 任务释放算力时保持搜索评价 0。监控器发现预注册
源合同 `docs/handoff/experiment_contract_v2_journal_aligned_20260730.md`
被外部写入：

- 锁定 SHA-256：
  `075f0093e90bb583b6c9f0431eeaf186cf30ff109dc164923ca914257f503b5e`
- 观察 SHA-256：
  `0e10e8ea20917eb140a945909539cc3ee1e649774758252c0477741d4e742c35`
- 文件时间：2026-07-30 15:13:17 +08:00
- 监控检出时间：2026-07-30 15:13:23 +08:00
- 动作：`PROTECTED_FILE_DRIFT`，对 E3 PGID 发送 `SIGSTOP` 并保存 scene。

暂停时 `budget_lock.json` 不存在，probe/formal task status 均为 0。随后只终止
零搜索等待控制器并封存现场。漂移后的合同未被静默重签，也未恢复覆盖当前外部文件。
`cost.py`、`check.py`、`search/evaluation.py`、`profit.py`、
`route_pool_sp.py` 和 `epochal_hgs.py` 的关闭哈希均与锁定证据一致。

## 证据入口与后续

- 人读报告：`baselines/china_e3_e7/e3_mismatch_20260731/report.md`
- 终态：`baselines/china_e3_e7/e3_mismatch_20260731/done.json`
- 停机证据：`baselines/china_e3_e7/e3_mismatch_20260731/halt_evidence.json`
- 输入全量审计：
  `baselines/china_e3_e7/e3_mismatch_20260731/input_audit/`
- 异常现场：
  `baselines/china_e3_e7/e3_mismatch_20260731/monitor_runtime/campaign/scenes/20260730-151323-anomaly/`

本轮三项正式效应均为 `null`。零错配封存对照 2.272759% / 0.693115% 只保留为
既有对照，没有与未运行的六实例正式结果拼接。若用户批准按当前源合同重启，应保留
本 HALT 目录不变，在新 sibling 目录重新做搜索前预注册和源锁；若恢复旧合同字节，
也须由用户明确指定权威版本。
