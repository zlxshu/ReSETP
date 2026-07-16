# E7 正式批非计时异常现场报告（2026-07-16）

## 判定

正式 E7 批次未完成，禁止进入28日电网日复算、独立总审计、图表生成或论文终稿。

监控事件为 `PROCESS_EXITED_WITHOUT_COMPLETION`。原始标准输出给出的直接异常为：

```text
N322__historical_mixed__stream1__no_participation:
unstarted charging action was marked locked: EV_D1_5#T2
```

该异常发生在 `e7_full_mechanism_probe_20260714.py::_charging_window_witness()`。`cut.locked_charging_actions` 中出现一项尚未开始的充电动作；见证函数按冻结语义只接受“触发前已完成”或“触发时正在执行”的动作，因此主动抛出异常。它不是阶段墙钟超时，也没有证据表明由13934秒外部 `SIGSTOP` 直接造成。依据冻结恢复规则，本次不得自动恢复或同合同续跑。

## 已保存现场

现场目录：

```text
/private/tmp/.resetp-e7-multinetwork-formal-extended.monitor/scenes/20260716-170133-anomaly
```

目录包含监控状态、断点清单、运行时、有效配置、外部暂停事故记录和完整标准输出。标准输出哈希为：

```text
cbf7aed3656454714e155876da795bf51717050f82bd9162a26a1abfc172ecb2
```

现有正式任务断点为102/120；全部既有非AppleDouble断点原样保留，未删除、未改写。`RUN_FINISHED.json`、`raw_runs.csv`、`decision.json`和`artifact_hashes.json`均未形成，故不存在可以验收的正式结果。

## 保护合同核对

原runtime登记的7项保护哈希与当前文件逐项一致：

| 保护对象 | SHA-256 |
|---|---|
| `e7_formal_dynamic_value_20260714.py` | `579b7f3e8c2d34d102bae8a64ae007571fdc41383a4113e6e447a4b1c542d80f` |
| `e7_formal_resumable_runner_20260715.py` | `cebfc355a07d51cc5f98f3f4a41f606383c23031d9254dc1b94445e751b01a15` |
| `e7_full_mechanism_probe_20260714.py` | `0212c344024f95c9d13f7226f7b9ac7cfaab11f9e4244577d8191d37b5a629ed` |
| `e7_multiday_zero_search_replay_20260715.py` | `33b92d4c160c51f87bbd188a81b1c8086167faac0e4eb60ef506c083c2413dac` |
| 事件流 `artifact_hashes.json` | `a1c9bb2b39e66e5a545780f0323611cbd6dce6743d596b2beffb94b215b9e00e` |
| 事件流 `metadata.json` | `dbc1099bf69a2bb84137de0d0aac7add8762eef16edbc4f0b35d128f01adc210` |
| `responsibility_maps.csv` | `6c17f0b1fcfcdf4bae6fb33399826afa94043b2886d478f75de9696022324c16` |

冻结合同、事件流、50次评价、6 workers、三网络、两类责任、五条事件流和四种机制均未变化。

## 后续允许动作

下一步不能直接重启。应先对“未来充电动作为什么进入 `locked_charging_actions`”做隔离只读复现和状态语义审计，明确问题位于动态切片、继承状态还是充电动作见证。若需要修改受保护的动态调度器，必须把补丁限定为该状态分类错误，增加最小反例、保存—读取和未受影响断点回放；随后以原合同、原目录和102个合法断点补齐18个缺失任务。任何修复不得通过删除异常动作、放宽见证检查、改事件流或改变失败纳入规则来绕过异常。

