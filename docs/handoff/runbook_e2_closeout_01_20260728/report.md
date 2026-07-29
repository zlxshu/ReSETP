# RUNBOOK-E2-CLOSEOUT-01：E2 洁净批完成后一键收口操作清单

- 任务编号：`RUNBOOK-E2-CLOSEOUT-01`
- 编制日期：2026-07-28
- 仓库：`/Volumes/移动硬盘（512G）/ReSETP`
- 当前状态：`PLAN_ONLY_NOT_EXECUTED`
- 适用对象：`baselines/e2_rerun_unified_01_20260727/` 的 4-worker 洁净批

> **本文件只是操作清单。编制本文件时没有执行下列任何收口命令，没有运行 solver、benchmark、pytest、进程池、统计、制表、XeLaTeX、栅格化或进程清理，也没有修改实验目录、源码、论文或 HANDOFF。**

## 一、总判定原则

1. `progress.json` 到达 2025 个基础尝试行不是终点。基础波完成后，runner 还会按“臂 × 饥饿规模层”检查 `L/S > 0.5` 的占比；超过 20% 的单元格会整体以 `K=6000` 重跑，仍饥饿时再以 `K=12000` 重跑。只有 runner 完成这些波次、选出 2025 个最终单元、写完表源和哈希后，才会写 `done.json`。
2. 真完成必须同时满足：`done.json` 语义通过、五件套齐全、`starvation_history` 已到合法终态、attempt/K 全覆盖、2025 个最终单元唯一且全 PASS、独立复算零违约、哈希闭合、165 行超订污染批路径级排除。
3. 任一门失败即停在对应 `HALT_*`，不得手工补 `done.json`、不得把失败行删掉凑齐、不得从受污染归档复制结果、不得临时改 K/阈值/分层、不得先改论文再等数据。
4. 洁净批属于“同批、同机、同一收敛规则族”的比较，但 MV 额外执行三个视角、外层轮次和限时路线池重组；`decision.json` 明确要求 `equal_compute_claim_allowed=false`。论文不得写成等算力优越。

## 二、唯一写入者与互斥规则

执行前把下列角色具体落实到一个终端、一个代理或一个人；同一时刻不得有第二写入者。

|受保护写入面|唯一写入者代号|允许写入|禁止事项|
|---|---|---|---|
|活动实验目录 `baselines/e2_rerun_unified_01_20260727/`|`W-E2-RUNNER`|仅当前 `run_unified_campaign.py --workers 4` 进程按冻结合同写入|任何收口人、论文人或 HANDOFF 人均不得写；`done.json` 后立即封只读|
|独立收口审计记录|`W-E2-AUDIT`|仅写 `docs/handoff/runbook_e2_closeout_01_20260728/execution/`|不得回写实验目录或改原始行|
|正式表体目录及 `docs/paper_v2/paper_main.tex`|`W-PAPER`|正式生成表、隔离干跑表、按顺序回填 TeX|不得修改实验数据或 HANDOFF|
|`HANDOFF.md` 及相关 `docs/handoff/memory/*.md`|`W-HANDOFF`|只在数据、论文和 PDF 全部验收后顺序登记|不得与 `W-PAPER` 并发，不得提前写完成|

互斥锁建议使用原子目录，不使用宽泛删除命令：

```bash
cd '/Volumes/移动硬盘（512G）/ReSETP'
mkdir /tmp/RUNBOOK-E2-CLOSEOUT-01.audit.lock
mkdir /tmp/RUNBOOK-E2-CLOSEOUT-01.paper.lock
mkdir /tmp/RUNBOOK-E2-CLOSEOUT-01.handoff.lock
```

通过判据：每个锁只由对应唯一写入者持有；`W-E2-RUNNER` 仍运行时，另外三者只能读。若锁已存在且所有者不明，判 `HALT_CLOSEOUT_WRITER_OWNERSHIP_UNKNOWN`，先确认所有者，不覆盖锁。

## 三、按执行顺序的清单

### 1. 判定 runner 是否真的到达终态

**唯一写入者**：实验目录仍只有 `W-E2-RUNNER`；本步 `W-E2-AUDIT` 只读，尚不写论文或 HANDOFF。

**要做什么**：检查 `done.json`、五件套、机器 verdict 和饥饿历史终态。禁止以 2025 行、进程退出、监控显示 `COMPLETED` 中任意一项单独代替终态。

**命令**：

```bash
cd '/Volumes/移动硬盘（512G）/ReSETP'
python3 - <<'PY'
from pathlib import Path
import json

root = Path('baselines/e2_rerun_unified_01_20260727')
required = [
    'done.json',
    'metadata.json',
    'raw_runs.csv',
    'decision.json',
    'artifact_hashes.json',
    'report.md',
]
missing = [name for name in required if not (root / name).is_file()]
assert not missing, f'HALT_MISSING_TERMINAL_SURFACES: {missing}'

done = json.loads((root / 'done.json').read_text(encoding='utf-8'))
decision = json.loads((root / 'decision.json').read_text(encoding='utf-8'))
history = decision.get('starvation_history')
assert done.get('status') == 'COMPLETED', done
assert done.get('verdict') == 'PASS_E2_RERUN_UNIFIED_01_COMPLETE', done
assert done.get('final_units') == 2025, done
assert decision.get('verdict') == done.get('verdict'), decision
assert decision.get('expected_final_units') == 2025, decision
assert decision.get('actual_final_units') == 2025, decision
assert isinstance(history, list) and history, 'HALT_STARVATION_HISTORY_MISSING'

last = history[-1]
normal_stop = (
    'triggered_cells' in last
    and last.get('triggered_cells') == {}
    and last.get('after_attempt') in (0, 1)
)
max_stop = (
    last.get('after_attempt') == 2
    and 'triggered_cells_after_max_doublings' in last
)
assert normal_stop or max_stop, f'HALT_DOUBLING_WAVES_NOT_TERMINAL: {last}'
print('PASS_TERMINAL_MARKER_AND_FIVE_SURFACES')
print(json.dumps(last, ensure_ascii=False, sort_keys=True))
PY
```

**通过判据**：六个文件都存在；`done.status=COMPLETED`；`done.verdict=decision.verdict=PASS_E2_RERUN_UNIFIED_01_COMPLETE`；最终单元为 2025；最后一条饥饿记录满足以下二者之一：

- `after_attempt` 为 0 或 1 且 `triggered_cells={}`，说明不再有下一波；
- `after_attempt=2` 且存在 `triggered_cells_after_max_doublings`，说明两次加倍已经用尽。该字段即使非空也代表协议合法终止，但必须在论文和报告中披露仍有饥饿指纹，不能写“全部非饥饿”。

**不通过时怎么办**：若 runner 仍活着，只等待，不启动任何收口下游；若 runner 已退出却缺 `done.json`，判 `HALT_CAMPAIGN_EXITED_WITHOUT_DONE`，保留现场并查 `progress.json`、监控异常和最后一个任务错误，禁止手工调用 `_finalize()` 或伪造五件套。

### 2. 独立复核任务唯一性、K 加倍、失败数和污染排除

**唯一写入者**：`W-E2-AUDIT` 只写 `execution/record_layer_audit.json`；实验目录保持只读。

**要做什么**：用单进程标准库脚本独立重建 attempt 账本和加倍状态机；验证活动 `tasks/*/result.json` 与 `raw_runs.csv` 闭合；验证 165 行污染归档没有被复制进活动账或哈希/统计输入。

**命令**：

```bash
cd '/Volumes/移动硬盘（512G）/ReSETP'
mkdir -p docs/handoff/runbook_e2_closeout_01_20260728/execution
python3 - <<'PY'
from pathlib import Path
import csv
import hashlib
import json
import math

repo = Path.cwd().resolve()
e2 = repo / 'baselines/e2_rerun_unified_01_20260727'
out = repo / 'docs/handoff/runbook_e2_closeout_01_20260728/execution/record_layer_audit.json'
arms = ('O', 'F', 'E', 'M', 'MV')

def need(condition, message):
    if not condition:
        raise RuntimeError(message)

def truthy(value):
    return str(value).strip().lower() in {'1', 'true', 'yes'}

def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()

def text(value):
    if value is None:
        return ''
    return str(value)

with (e2 / 'raw_runs.csv').open(newline='', encoding='utf-8') as handle:
    reader = csv.DictReader(handle)
    fields = list(reader.fieldnames or [])
    rows = list(reader)
need(rows and fields, 'HALT_RAW_RUNS_EMPTY_OR_HEADERLESS')

def science_key(row):
    return (row['instance_id'], int(row['seed']), row['arm'])

def attempt_key(row):
    return (*science_key(row), int(row['attempt']), int(row['k']))

attempt_keys = [attempt_key(row) for row in rows]
need(len(attempt_keys) == len(set(attempt_keys)), 'HALT_DUPLICATE_ATTEMPT_PRIMARY_KEY')
need(all(row['arm'] in arms for row in rows), 'HALT_UNKNOWN_ARM')
need(all(int(row['attempt']) in (0, 1, 2) for row in rows), 'HALT_ATTEMPT_OUT_OF_RANGE')
need(
    all(int(row['k']) == 3000 * (2 ** int(row['attempt'])) for row in rows),
    'HALT_ATTEMPT_K_MAPPING_BROKEN',
)

base = [row for row in rows if int(row['attempt']) == 0]
need(len(base) == 2025, f'HALT_BASE_UNIT_COUNT_{len(base)}')
science = {science_key(row) for row in base}
need(len(science) == 2025, 'HALT_BASE_SCIENCE_KEY_NOT_UNIQUE')

selected = [row for row in rows if truthy(row['selected_final_attempt'])]
need(len(selected) == 2025, f'HALT_SELECTED_FINAL_COUNT_{len(selected)}')
need(len({science_key(row) for row in selected}) == 2025, 'HALT_DUPLICATE_FINAL_SCIENCE_KEY')

failed_all = [row for row in rows if row['status'] != 'PASS']
failed_final = [row for row in selected if row['status'] != 'PASS']
need(not failed_all and not failed_final, 'HALT_FAILED_ATTEMPT_ROWS_PRESENT')
need(
    all(
        truthy(row['feasible'])
        and int(row['violation_count']) == 0
        and int(row['independent_violation_count']) == 0
        and not row.get('error_type')
        and not row.get('error_message')
        for row in rows
    ),
    'HALT_FEASIBILITY_OR_RECORDED_VIOLATION_FAILURE',
)

# 活动 task JSON 必须与 raw_runs.csv 一一闭合；聚合时只允许 selected_final_attempt 字段变化。
task_paths = sorted((e2 / 'tasks').glob('*/result.json'))
need(len(task_paths) == len(rows), 'HALT_ACTIVE_TASK_RESULT_COUNT_MISMATCH')
csv_by_key = {attempt_key(row): row for row in rows}
active_payloads = []
for path in task_paths:
    payload = json.loads(path.read_text(encoding='utf-8'))
    key = (
        payload['instance_id'], int(payload['seed']), payload['arm'],
        int(payload['attempt']), int(payload['k']),
    )
    need(key in csv_by_key, f'HALT_TASK_NOT_IN_RAW:{path}')
    row = csv_by_key[key]
    for field in fields:
        if field == 'selected_final_attempt':
            continue
        need(text(payload.get(field, '')) == row.get(field, ''), f'HALT_TASK_RAW_DRIFT:{path}:{field}')
    active_payloads.append(payload)

decision = json.loads((e2 / 'decision.json').read_text(encoding='utf-8'))
metadata = json.loads((e2 / 'metadata.json').read_text(encoding='utf-8'))
done = json.loads((e2 / 'done.json').read_text(encoding='utf-8'))
history = decision['starvation_history']

row_by_science_attempt = {
    (*science_key(row), int(row['attempt'])): row for row in rows
}
base_meta = {science_key(row): row for row in base}
current_attempt = {key: 0 for key in science}

def empirical_starved(current):
    result = {}
    for arm in arms:
        for layer in ('small', 'medium', 'large'):
            values = [
                float(row_by_science_attempt[(*key, current[key])]['l_over_s'])
                for key in science
                if key[2] == arm and base_meta[key]['size_layer'] == layer
            ]
            need(values, f'HALT_EMPTY_STARVATION_CELL:{arm}:{layer}')
            fraction = sum(value > 0.5 for value in values) / len(values)
            if fraction > 0.20:
                result[f'{arm}:{layer}'] = fraction
    return result

stage = 0
terminal = False
for index, record in enumerate(history):
    need(record.get('after_attempt') == stage, f'HALT_HISTORY_STAGE_ORDER:{record}')
    empirical = empirical_starved(current_attempt)
    if 'triggered_cells' in record:
        recorded = {key: float(value) for key, value in record['triggered_cells'].items()}
        need(set(recorded) == set(empirical), f'HALT_TRIGGERED_CELL_SET_DRIFT:{recorded}:{empirical}')
        need(
            all(math.isclose(recorded[key], empirical[key], rel_tol=0.0, abs_tol=1e-12) for key in recorded),
            'HALT_TRIGGERED_CELL_FRACTION_DRIFT',
        )
        if not recorded:
            need(index == len(history) - 1, 'HALT_HISTORY_CONTINUES_AFTER_EMPTY_TRIGGER')
            terminal = True
            break
        next_attempt = stage + 1
        need(next_attempt <= 2, 'HALT_MORE_THAN_TWO_K_DOUBLINGS')
        expected = {
            key for key in science
            if f"{key[2]}:{base_meta[key]['size_layer']}" in recorded
        }
        actual = {science_key(row) for row in rows if int(row['attempt']) == next_attempt}
        need(actual == expected, f'HALT_INCOMPLETE_OR_EXTRANEOUS_DOUBLING_WAVE_{next_attempt}')
        for key in expected:
            current_attempt[key] = next_attempt
        stage = next_attempt
    elif 'triggered_cells_after_max_doublings' in record:
        need(stage == 2 and index == len(history) - 1, 'HALT_INVALID_MAX_DOUBLING_TERMINUS')
        recorded = {
            key: float(value)
            for key, value in record['triggered_cells_after_max_doublings'].items()
        }
        need(set(recorded) == set(empirical), 'HALT_FINAL_STARVATION_FINGERPRINT_SET_DRIFT')
        need(
            all(math.isclose(recorded[key], empirical[key], rel_tol=0.0, abs_tol=1e-12) for key in recorded),
            'HALT_FINAL_STARVATION_FINGERPRINT_VALUE_DRIFT',
        )
        terminal = True
        break
    else:
        raise RuntimeError(f'HALT_UNKNOWN_STARVATION_HISTORY_RECORD:{record}')
need(terminal, 'HALT_STARVATION_STATE_MACHINE_NOT_TERMINAL')

selected_attempts = {science_key(row): int(row['attempt']) for row in selected}
need(selected_attempts == current_attempt, 'HALT_SELECTED_FINAL_ATTEMPT_DRIFT')

# 哈希清单闭合；done.json 和清单本身由外层审计另记哈希。
manifest = json.loads((e2 / 'artifact_hashes.json').read_text(encoding='utf-8'))
files = manifest.get('files')
need(isinstance(files, dict) and files, 'HALT_EMPTY_HASH_MANIFEST')
need(manifest.get('algorithm') == 'sha256', 'HALT_HASH_ALGORITHM')
need(manifest.get('self_excluded') is True, 'HALT_HASH_SELF_EXCLUSION_FLAG')
need(manifest.get('appledouble_files_included') is False, 'HALT_APPLEDOUBLE_FLAG')
need(manifest.get('monitor_directories_excluded') is True, 'HALT_MONITOR_EXCLUSION_FLAG')
need(manifest.get('contaminated_partial_run_excluded') is True, 'HALT_CONTAMINATION_EXCLUSION_FLAG')
for relative, expected in files.items():
    path = repo / relative
    need(path.is_file(), f'HALT_HASHED_FILE_MISSING:{relative}')
    need(sha256(path) == expected, f'HALT_HASH_DRIFT:{relative}')
    parts = Path(relative).parts
    need('contaminated_partial_run_oversubscribed' not in parts, f'HALT_CONTAMINATED_PATH_HASHED:{relative}')
    need(not any(part.endswith('.monitor') for part in parts), f'HALT_MONITOR_PATH_HASHED:{relative}')
    need(not Path(relative).name.startswith('._'), f'HALT_APPLEDOUBLE_HASHED:{relative}')
need(metadata.get('frozen_hashes_before') == manifest.get('frozen_hashes_after'), 'HALT_FROZEN_HASHES_CHANGED')
need(decision.get('protected_files_modified') == [], 'HALT_PROTECTED_FILE_CHANGE_RECORDED')

for name in (
    'raw_runs.csv', 'decision.json', 'metadata.json', 'report.md',
    'paper_table_city_size_five_arms.csv', 'paper_table_mv_vs_o_pairs.csv',
    'run_unified_campaign.py', 'monitor.json',
):
    relative = str((e2 / name).relative_to(repo))
    need(relative in files, f'HALT_REQUIRED_ARTIFACT_NOT_HASHED:{name}')

# 165 行污染批必须留在独立归档，且没有活动 task 文件与归档文件逐字相同。
archive = e2 / 'contaminated_partial_run_oversubscribed'
archived_results = sorted(archive.rglob('result.json'))
need(len(archived_results) == 165, f'HALT_CONTAMINATED_ARCHIVE_COUNT_{len(archived_results)}')
active_hashes = {sha256(path) for path in task_paths}
archive_hashes = {sha256(path) for path in archived_results}
need(active_hashes.isdisjoint(archive_hashes), 'HALT_CONTAMINATED_RESULT_COPIED_INTO_ACTIVE_TASKS')
active_pids = {int(row['pid']) for row in rows}
archive_pids = {
    int(json.loads(path.read_text(encoding='utf-8'))['pid'])
    for path in archived_results
}
need(active_pids.isdisjoint(archive_pids), 'HALT_ACTIVE_AND_CONTAMINATED_PID_LINEAGE_OVERLAP')
need(metadata.get('contaminated_completed_attempt_rows_archived') == 165, 'HALT_METADATA_CONTAMINATED_COUNT')
need(metadata.get('contaminated_archive') == 'contaminated_partial_run_oversubscribed', 'HALT_METADATA_CONTAMINATED_PATH')
need(metadata.get('workers') == 4, 'HALT_NOT_CLEAN_4_WORKER_PROTOCOL')
need(done.get('verdict') == decision.get('verdict'), 'HALT_DONE_DECISION_MISMATCH')

payload = {
    'verdict': 'PASS_E2_RECORD_LAYER_AND_DOUBLING_AUDIT',
    'attempt_rows': len(rows),
    'base_rows': len(base),
    'selected_final_rows': len(selected),
    'duplicate_attempt_primary_keys': 0,
    'failed_attempt_rows': len(failed_all),
    'failed_final_rows': len(failed_final),
    'selected_violation_count': sum(int(row['violation_count']) for row in selected),
    'selected_independent_violation_count': sum(int(row['independent_violation_count']) for row in selected),
    'max_selected_attempt': max(selected_attempts.values()),
    'terminal_starvation_record': history[-1],
    'contaminated_archive_result_rows': len(archived_results),
    'contaminated_results_used_in_active_tasks': 0,
    'artifact_hashes_json_sha256': sha256(e2 / 'artifact_hashes.json'),
    'done_json_sha256': sha256(e2 / 'done.json'),
}
out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
PY
```

**通过判据**：脚本输出 `PASS_E2_RECORD_LAYER_AND_DOUBLING_AUDIT`；attempt 主键 `(instance_id, seed, arm, attempt, k)` 无重复；基础 2025 行和最终 2025 个科学主键 `(instance_id, seed, arm)` 均唯一；每个 attempt 与 `K=3000×2^attempt` 一致；每个触发单元格的下一波覆盖该单元格全部实例和 5 个种子且无额外行；所有尝试失败数为 0；活动 task 与 raw 一一闭合；污染归档恰有 165 个 `result.json`，与活动结果文件哈希和 PID 谱系均不相交；清单内所有哈希重算一致。

**不通过时怎么办**：判 `HALT_E2_RECORD_LAYER_AUDIT`。不删除重复行、不补跑单个缺口、不把污染归档搬回活动目录。先保存审计异常和涉及的主键；任何恢复都必须回到冻结 runner 的整单元格续跑语义，并由用户另批。

### 3. 单进程重放 2025 个最终 witness 的完整模型与独立检查器

**唯一写入者**：`W-E2-AUDIT` 只写 `execution/full_witness_replay.json`；实验目录保持只读。

**要做什么**：从每个最终行的 `witness_path` 反序列化解，分别调用 `exact_china81_score` 与 `check_solution + evaluate` 复算。该步骤不调用 HGS、MIP 或任何 solver，只做单进程评价重放。

**命令**：先从 `metadata.json` 使用与正式批相同的 Python 解释器；下例中的解释器路径必须与 `metadata.python` 逐字一致。

```bash
cd '/Volumes/移动硬盘（512G）/ReSETP'
env OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
  /opt/anaconda3/bin/python3.13 - <<'PY'
from pathlib import Path
import csv
import hashlib
import json
import math
import sys

repo = Path.cwd().resolve()
sys.path.insert(0, str(repo / 'solver/src'))

from setp_solver.china81 import load_china81_bundle
from setp_solver.china81_completion import exact_china81_score
from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.solution import ChargingAction, CrossSiteService, Route, Solution

e2 = repo / 'baselines/e2_rerun_unified_01_20260727'
out = repo / 'docs/handoff/runbook_e2_closeout_01_20260728/execution/full_witness_replay.json'

def need(condition, message):
    if not condition:
        raise RuntimeError(message)

def truthy(value):
    return str(value).strip().lower() in {'1', 'true', 'yes'}

def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()

def load_solution(payload):
    return Solution(
        routes=[
            Route(
                vehicle_id=str(row['vehicle_id']),
                vehicle_type=str(row['vehicle_type']),
                home_depot_id=str(row['home_depot_id']),
                node_sequence=[str(item) for item in row['node_sequence']],
            )
            for row in payload['routes']
        ],
        charging_actions=[
            ChargingAction(
                vehicle_id=str(row['vehicle_id']),
                station_id=str(row['station_id']),
                energy_kwh=float(row['energy_kwh']),
                occupancy_minutes=float(row['occupancy_minutes']),
                charge_start_second=float(row['charge_start_second']),
                charge_day_offset=int(row.get('charge_day_offset', 0)),
                start_energy_kwh=None if row.get('start_energy_kwh') is None else float(row['start_energy_kwh']),
                end_energy_kwh=None if row.get('end_energy_kwh') is None else float(row['end_energy_kwh']),
                charging_curve_id=row.get('charging_curve_id'),
            )
            for row in payload.get('charging_actions', [])
        ],
        cross_site_services=[
            CrossSiteService(
                customer_id=str(row['customer_id']),
                served_by_depot_id=str(row['served_by_depot_id']),
            )
            for row in payload.get('cross_site_services', [])
        ],
    )

with (e2 / 'raw_runs.csv').open(newline='', encoding='utf-8') as handle:
    selected = [row for row in csv.DictReader(handle) if truthy(row['selected_final_attempt'])]
need(len(selected) == 2025, 'HALT_REPLAY_SELECTED_COUNT')

bundles = {}
replayed = 0
for row in selected:
    witness_path = repo / row['witness_path']
    need(witness_path.is_file(), f'HALT_WITNESS_MISSING:{witness_path}')
    need(sha256(witness_path) == row['witness_sha256'], f'HALT_WITNESS_HASH:{witness_path}')
    payload = json.loads(witness_path.read_text(encoding='utf-8'))
    need(payload.get('violations') == [], f'HALT_SERIALIZED_VIOLATIONS:{witness_path}')
    solution = load_solution(payload['solution'])
    instance_id = row['instance_id']
    if instance_id not in bundles:
        bundles[instance_id] = load_china81_bundle(repo, instance_id)
    bundle = bundles[instance_id]
    exact_cost, _breakdown, exact_violations = exact_china81_score(solution, bundle)
    independent_violations = check_solution(solution, bundle.instance, bundle.prices)
    independent_cost = float(evaluate(solution, bundle.instance, bundle.time_profile, bundle.prices)['total_cost'])
    expected = float(row['final_cost'])
    need(exact_violations == independent_violations, f'HALT_VIOLATION_LEDGER_DISAGREES:{instance_id}:{row["seed"]}:{row["arm"]}')
    need(not exact_violations, f'HALT_REPLAY_VIOLATIONS:{instance_id}:{row["seed"]}:{row["arm"]}')
    need(math.isclose(exact_cost, independent_cost, rel_tol=0.0, abs_tol=1e-9), 'HALT_EXACT_INDEPENDENT_COST_DRIFT')
    need(math.isclose(exact_cost, expected, rel_tol=0.0, abs_tol=1e-9), 'HALT_REPORTED_REPLAY_COST_DRIFT')
    need(math.isclose(float(payload['objective']), expected, rel_tol=0.0, abs_tol=1e-9), 'HALT_WITNESS_OBJECTIVE_DRIFT')
    replayed += 1

result = {
    'verdict': 'PASS_E2_2025_FINAL_WITNESS_REPLAY',
    'replayed_final_units': replayed,
    'instance_count': len(bundles),
    'exact_violation_count': 0,
    'independent_violation_count': 0,
    'objective_mismatch_count': 0,
    'solver_or_search_calls': 0,
    'process_count': 1,
}
out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, sort_keys=True))
PY
```

**通过判据**：`metadata.python` 与实际解释器一致；2025/2025 witness 哈希通过；两个违约账本均为 0 且逐单元一致；两个目标值实现与 `raw_runs.csv`、witness 记录在绝对误差 `1e-9` 内闭合；无 solver/search 调用。

**不通过时怎么办**：判 `HALT_E2_FINAL_WITNESS_REPLAY`。不选择性删除失败单元、不放宽误差、不改 checker。保留第一个失败主键、witness 路径、两套违约和成本差；论文和表生成全部停止。

### 4. 生成正式五臂分层表、MV-vs-O 配对表和统计汇总

**唯一写入者**：`W-PAPER`。它是 `docs/paper_v2/generated_tables/formal_e2_clean_20260728/` 和后续 `paper_main.tex` 的唯一写入者；`W-E2-RUNNER` 与 `W-E2-AUDIT` 不写论文目录。

**要做什么**：只从洁净批的 `raw_runs.csv` 生成正式 TeX，不读取污染归档，不传 `--format-dry-run`。正式分层表使用论文生成器冻结的三档：`10/15/20`、`25/50/75`、`100/150/200`。runner 自带的 `paper_table_city_size_five_arms.csv` 使用的是饥饿层 `≤25`、`50/75/100`、`150/200`，只能作收敛诊断交叉检查，不能直接作为论文分层表。

**命令**：

```bash
cd '/Volumes/移动硬盘（512G）/ReSETP'
export RESET_E2_INPUT='baselines/e2_rerun_unified_01_20260727/raw_runs.csv'
export RESET_E2_FORMAL_TABLE_DIR='docs/paper_v2/generated_tables/formal_e2_clean_20260728'
mkdir -p "$RESET_E2_FORMAL_TABLE_DIR"

python3 docs/paper_v2/generated_tables/generate_china81_five_arm_summary.py \
  "$RESET_E2_INPUT" \
  "$RESET_E2_FORMAL_TABLE_DIR/table_a_five_arm_summary.tex"

python3 docs/paper_v2/generated_tables/generate_china81_mv_vs_o_pairs.py \
  "$RESET_E2_INPUT" \
  "$RESET_E2_FORMAL_TABLE_DIR/table_b_mv_vs_o_pairs.tex"
```

随后生成统计汇总。O-vs-MV 报告 405 个实例—种子配对的胜/平/负、均值和中位数改善；既有 MV-vs-F/E/M 检验仍以每实例 5 种子均值形成 81 个配对单位，并对三项双侧 Wilcoxon 做 Holm 校正。不要在结果揭盲后临时把 O 加进既有三检验族；O-vs-MV 保持预先实现的描述性配对表。统计显著性不是本批完成门，只决定论文措辞。

```bash
cd '/Volumes/移动硬盘（512G）/ReSETP'
/opt/anaconda3/bin/python3.13 - <<'PY'
from pathlib import Path
from collections import defaultdict
from statistics import fmean, median
import csv
import json
import math
from scipy.stats import wilcoxon

repo = Path.cwd().resolve()
e2 = repo / 'baselines/e2_rerun_unified_01_20260727'
out = repo / 'docs/paper_v2/generated_tables/formal_e2_clean_20260728/e2_clean_statistical_summary.json'
eps = 1e-9

def need(condition, message):
    if not condition:
        raise RuntimeError(message)

def truthy(value):
    return str(value).strip().lower() in {'1', 'true', 'yes'}

with (e2 / 'raw_runs.csv').open(newline='', encoding='utf-8') as handle:
    rows = [row for row in csv.DictReader(handle) if truthy(row['selected_final_attempt'])]
need(len(rows) == 2025, 'HALT_STATS_SELECTED_COUNT')

cost = {(row['instance_id'], int(row['seed']), row['arm']): float(row['final_cost']) for row in rows}
units = sorted({(row['instance_id'], int(row['seed'])) for row in rows})
need(len(units) == 405, 'HALT_STATS_PAIR_COUNT')

def outcomes(primary, baseline, pairs):
    differences = [baseline_value - primary_value for primary_value, baseline_value in pairs]
    gains = [100.0 * (baseline_value - primary_value) / baseline_value for primary_value, baseline_value in pairs]
    wins = sum(value > eps for value in differences)
    losses = sum(value < -eps for value in differences)
    return {
        'primary': primary,
        'baseline': baseline,
        'paired_units': len(pairs),
        'wins_primary_lower': wins,
        'ties': len(pairs) - wins - losses,
        'losses_primary_higher': losses,
        'mean_gain_percent': fmean(gains),
        'median_gain_percent': median(gains),
    }

mv_o = outcomes('MV', 'O', [(cost[(i, s, 'MV')], cost[(i, s, 'O')]) for i, s in units])
decision = json.loads((e2 / 'decision.json').read_text(encoding='utf-8'))
recorded = decision['mv_vs_o']
need(mv_o['paired_units'] == recorded['paired_units'], 'HALT_MV_O_PAIR_COUNT_DRIFT')
need(mv_o['wins_primary_lower'] == recorded['wins'], 'HALT_MV_O_WIN_DRIFT')
need(mv_o['ties'] == recorded['ties'], 'HALT_MV_O_TIE_DRIFT')
need(mv_o['losses_primary_higher'] == recorded['losses'], 'HALT_MV_O_LOSS_DRIFT')
need(math.isclose(mv_o['mean_gain_percent'], recorded['mean_improvement_percent'], rel_tol=0.0, abs_tol=1e-12), 'HALT_MV_O_MEAN_DRIFT')

by_instance_arm = defaultdict(list)
for row in rows:
    by_instance_arm[(row['instance_id'], row['arm'])].append(float(row['final_cost']))
instances = sorted({row['instance_id'] for row in rows})
instance_means = {
    (instance, arm): fmean(by_instance_arm[(instance, arm)])
    for instance in instances
    for arm in ('O', 'F', 'E', 'M', 'MV')
}

tests = []
raw_p = []
for baseline in ('F', 'E', 'M'):
    pairs = [(instance_means[(i, 'MV')], instance_means[(i, baseline)]) for i in instances]
    row = outcomes('MV', baseline, pairs)
    nonzero = [base - mv for mv, base in pairs if abs(base - mv) > eps]
    if nonzero:
        statistic, p_value = wilcoxon(nonzero, alternative='two-sided', zero_method='wilcox', method='auto')
        row['wilcoxon_statistic'] = float(statistic)
        row['wilcoxon_p_raw'] = float(p_value)
    else:
        row['wilcoxon_statistic'] = 0.0
        row['wilcoxon_p_raw'] = 1.0
    row['nonzero_pairs'] = len(nonzero)
    tests.append(row)
    raw_p.append(row['wilcoxon_p_raw'])

ordered = sorted(enumerate(raw_p), key=lambda item: item[1])
adjusted = [1.0] * len(raw_p)
running = 0.0
for rank, (index, p_value) in enumerate(ordered):
    running = max(running, min(1.0, (len(raw_p) - rank) * p_value))
    adjusted[index] = running
for row, value in zip(tests, adjusted, strict=True):
    row['wilcoxon_p_holm'] = value

transitions = {}
for old, new in (('O', 'F'), ('F', 'E'), ('E', 'M'), ('M', 'MV')):
    transitions[f'{old}_to_{new}'] = outcomes(
        new, old,
        [(cost[(i, s, new)], cost[(i, s, old)]) for i, s in units],
    )

payload = {
    'verdict': 'PASS_E2_CLEAN_STATISTICS_RECOMPUTED',
    'source': str((e2 / 'raw_runs.csv').relative_to(repo)),
    'selected_rows': len(rows),
    'mv_vs_o_instance_seed_descriptive': mv_o,
    'mv_vs_single_view_instance_mean_tests': tests,
    'holm_family': ['MV_vs_F', 'MV_vs_E', 'MV_vs_M'],
    'o_vs_mv_in_holm_family': False,
    'five_arm_transitions_instance_seed_descriptive': transitions,
    'equal_compute_claim_allowed': False,
    'inference_note': 'Seeds are repeated algorithm runs; region-scale summaries are descriptive and not unconditional IID samples.',
}
out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
PY
```

最后写一个来源清单，固定原始数据、生成器和输出哈希：

```bash
cd '/Volumes/移动硬盘（512G）/ReSETP'
python3 - <<'PY'
from pathlib import Path
import hashlib
import json

repo = Path.cwd().resolve()
out_dir = repo / 'docs/paper_v2/generated_tables/formal_e2_clean_20260728'
sources = [
    repo / 'baselines/e2_rerun_unified_01_20260727/raw_runs.csv',
    repo / 'baselines/e2_rerun_unified_01_20260727/decision.json',
    repo / 'baselines/e2_rerun_unified_01_20260727/done.json',
    repo / 'baselines/e2_rerun_unified_01_20260727/artifact_hashes.json',
    repo / 'docs/paper_v2/generated_tables/table_common.py',
    repo / 'docs/paper_v2/generated_tables/generate_china81_five_arm_summary.py',
    repo / 'docs/paper_v2/generated_tables/generate_china81_mv_vs_o_pairs.py',
    out_dir / 'table_a_five_arm_summary.tex',
    out_dir / 'table_b_mv_vs_o_pairs.tex',
    out_dir / 'e2_clean_statistical_summary.json',
]
def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()
assert all(path.is_file() for path in sources)
payload = {
    'schema': 'resetp.e2-clean-paper-tables.sources.v1',
    'format_dry_run': False,
    'files': {str(path.relative_to(repo)): digest(path) for path in sources},
}
(out_dir / 'source_manifest.json').write_text(
    json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
    encoding='utf-8',
)
print('PASS_FORMAL_TABLE_SOURCE_MANIFEST')
PY
```

**通过判据**：两个生成器均以 0 退出；没有使用 `--format-dry-run`；表 A 含 O/F/E/M/MV 五臂、9 个城市群—论文规模层行和总体行；表 B 总体配对数为 405，四个逐层转换各为 405；统计 JSON 与 `decision.mv_vs_o` 逐项一致；三项 Wilcoxon/Holm 只决定文字强度，不作为删数据或救援调参门；`source_manifest.json` 指向洁净 `raw_runs.csv` 且 `format_dry_run=false`。

**不通过时怎么办**：判 `HALT_FORMAL_E2_TABLE_GENERATION`。不得放宽 `table_common.py` 的 2025 行、五臂、种子、可行性或分层检查；不得从 runner 的饥饿分层 CSV 手工拼论文表；不得手填 TeX 数字。

### 5. 删除或隔离全部 `FORMAT_DRY_RUN_INVALID` 产物

**唯一写入者**：`W-PAPER`。只有它能移动 `docs/paper_v2/generated_tables/` 下的文件。

**要做什么**：采用可恢复隔离，不直接删除。整个 `generated_tables/dry_run/` 移出论文树；正式主稿和正式表目录不得再出现 `FORMAT_DRY_RUN_INVALID`、`格式干跑`、`已作废超订批次` 或 `dry_run` 输入路径。

**命令**：

```bash
cd '/Volumes/移动硬盘（512G）/ReSETP'
mkdir -p docs/handoff/runbook_e2_closeout_01_20260728/quarantine
if test -d docs/paper_v2/generated_tables/dry_run; then
  test ! -e docs/handoff/runbook_e2_closeout_01_20260728/quarantine/generated_tables_dry_run
  mv docs/paper_v2/generated_tables/dry_run \
    docs/handoff/runbook_e2_closeout_01_20260728/quarantine/generated_tables_dry_run
fi

if rg --files docs/paper_v2 | rg 'FORMAT_DRY_RUN_INVALID|(^|/)dry_run/'; then
  echo 'HALT_DRY_RUN_ARTIFACT_REMAINS_IN_PAPER_TREE'
  exit 2
fi

if rg -n 'FORMAT_DRY_RUN_INVALID|格式干跑|已作废超订批次|generated_tables/dry_run' \
  docs/paper_v2/paper_main.tex \
  docs/paper_v2/generated_tables/formal_e2_clean_20260728; then
  echo 'HALT_DRY_RUN_REFERENCE_REMAINS'
  exit 2
fi
```

**通过判据**：论文树中不存在 `*FORMAT_DRY_RUN_INVALID.tex` 和 `dry_run/`；主 TeX 只输入 `formal_e2_clean_20260728/` 的正式文件；隔离目录保留原文件用于审计，但永不进入 TeX 搜索路径。`prepare_contaminated_format_input.py` 只保留为历史格式工具，本次及以后正式制表均不得运行。

**不通过时怎么办**：判 `HALT_INVALID_DRY_RUN_ARTIFACT_REACHABLE`，停止论文回填和编译；先解除所有引用与路径可达性，不通过改名掩盖 `INVALID` 文件。

### 6. 论文回填第一阶段：先换表体和物理口径表

**唯一写入者**：`W-PAPER`，且此时 `W-HANDOFF` 不得并发编辑。编辑工具使用受控 `apply_patch`；编辑前把 `paper_main.tex` 的副本放在 `/tmp/RUNBOOK-E2-CLOSEOUT-01.paper_main.pre_edit.tex`，不在论文目录制造备份副本。

**要做什么**：先处理所有由新车型/新价格/新洁净批直接失效的表体；表体通过后才能写解释文字。当前行号是本清单编制时对 `docs/paper_v2/paper_main.tex` 的 1 基快照；执行时先用锚点复核，若行号漂移则重定位后再改，禁止按旧行号盲补。

**命令/定位**：

```bash
cd '/Volumes/移动硬盘（512G）/ReSETP'
cp docs/paper_v2/paper_main.tex /tmp/RUNBOOK-E2-CLOSEOUT-01.paper_main.pre_edit.tex
nl -ba docs/paper_v2/paper_main.tex | sed -n '950,1080p;1180,1280p'
```

**表体回填行号清单**：

|当前行号|对象|必须动作|
|---:|---|---|
|954--976|车型参数表|把旧 EV“ES1·140厢式、3300 kg、1000 kg、6.08 m²、140.41 kWh”替换为批准的新 `FOTON-AUMARK-ES1-EXPRESS-STAKE` 口径：整备 2600 kg、载重 1700 kg、电池 77.28 kWh；迎风面积按 `0.85×2.2×2.480`，表注必须写 `HEIGHT_ASSUMED_SYMMETRIC_WITH_CV_FIELD_INCOMPLETE` 的情景边界，不称厂家官方车高。|
|1038--1076|旧最终解分析和逐路径表|旧 2393.819 元、9 趟、旧车型能耗和路线表不得与新洁净表共存。必须从预先指定的洁净 MV witness 用“零搜索、只读 witness、完整评价器”的受审查提取器重生成；当前仓库的 `run_s4_route_detail_v2.py` 只可作字段/版式参考，不能直接拿旧 S3 输入运行。若没有新提取器，删除或暂时屏蔽该结果块，判 `HALT_PAPER_ROUTE_DETAIL_SOURCE_MISSING`，严禁手算填表。|
|1197--1204|历史 10 次机制展示表|洁净批只有 5 个共同种子且协议不同。要么从洁净五种子重新生成并改表注，要么明确移出正式证据；不得继续用旧十种子表支持新外层协议。|
|1206--1211|历史收敛图|本清单不生成图。若保留，必须明确是历史开发图且不参与新协议结论；若正文用它证明新协议，则需另立洁净轨迹制图任务，不能在本收口中临时画图。|
|1236--1243|`tab:china81-summary`|把旧 v4 四臂 `table8b_china81_summary.tex` 输入替换为 `generated_tables/formal_e2_clean_20260728/table_a_five_arm_summary.tex`；表注改为五臂、5 种子、全 PASS、分层定义和非等算力边界。|
|紧接 1243 后|新增 MV-vs-O 配对/逐层转换表|新增独立 table 环境，输入 `generated_tables/formal_e2_clean_20260728/table_b_mv_vs_o_pairs.tex`，标签不得与现有表重复。|

**通过判据**：所有表体数字只来自 `source_manifest.json` 锁定的洁净 raw；主稿不再输入旧四臂表或干跑表；旧车型和旧柴油价下的最终解表不与新批并存；新表注不声称等算力、不把 L/S 饥饿层误写成论文规模层。

**不通过时怎么办**：停止在 `HALT_PAPER_TABLE_BODY_NOT_CLOSED`。不要先修改正文数字来“适配”旧表；从 `/tmp` 副本对照人工回退有问题的单个补丁，不覆盖其他人的工作。

### 7. 论文回填第二阶段：正文数字、边界和结语

**唯一写入者**：仍为 `W-PAPER`。`W-HANDOFF` 继续等待。

**要做什么**：表体验收后，逐项从 `e2_clean_statistical_summary.json`、`decision.json` 和 witness 重放报告回填正文。任何方向、显著性或效应量都以新数据为准，不保留旧 354/46/5、1.919%、299/405 等数字，除非新洁净批独立复算恰好得到相同值且来源已切换。

**正文回填行号清单**：

|当前行号|对象|必须动作|
|---:|---|---|
|268--285|贡献和“显著提升/验证有效性”|按洁净统计强度收缩；若 Holm 后无统计可区分差异，就写“在本方法特定收敛协议下无统计可区分差异”，不得保留“显著提升”，也不得换写成“融合显著更差”。E3--E7 尚未封存的管理启示不由 E2 填。|
|978--986|柴油价和日期口径|旧 2026-07 的 6.87/6.83/6.90 元/L 必须改为已批准的 2025-02-12 分城市价格，并保持城市—日期绑定及来源边界。|
|1040--1051|最终解正文数字|只有第 6 步的新 witness 路径表生成并独立复算后才可回填；否则连同旧表一起移除，不得保留旧数字。|
|1153--1178|公开算例 13/18 边界|这是独立于 China81 洁净批的既有终局边界；核对但不要用新 China81 数字覆盖。摘要和结论必须继续披露固定协议仅复现 13/18。|
|1182--1195|算法协议和证据来源|把“本节现有表图均为历史封存批”的笼统说法拆开：历史机制表/图若保留则明确历史；新 China81 表明确为本次洁净批。保持 MV 三视角各自收敛、外层轮次、`min()` 接受和额外 CPU 披露。|
|1213--1228|旧机制展示胜负、成本和 CPU|若第 6 步未把展示表/图重生为洁净五种子，就删除这些作为新协议证据的数字和因果语言；不能把旧 10 种子开发结果与新全量表拼接。|
|1231--1271|China81 全量统计主段|全部从新表和统计 JSON 重写：五臂分层、MV-vs-O、四个逐层转换、最终饥饿记录、CPU/墙钟披露。删除旧“非同批次”说明，改为“同批同机但方法计算量不同”；删除旧四臂 p 值和旧混批数字。|
|1824--1833|结语|同步新 E2 结果和公开 13/18 限制；E3--E7 仍未封存的结论继续保持待定，不把 E2 结果外推成机制实验完成。|

**命令/核验**：

```bash
cd '/Volumes/移动硬盘（512G）/ReSETP'
rg -n '354胜|46平|1\.919|299个|268/115/22|290/86/29|79/249/77|114/291/0|不是同批次|固定迭代预算的历史封存批次' \
  docs/paper_v2/paper_main.tex
rg -n 'equal.compute|等算力|同计算量|显著提升|全面支配|普遍单调' \
  docs/paper_v2/paper_main.tex
```

这些搜索命中不是自动失败；每一处必须人工证明已经由新洁净来源支持或已明确降级。旧数字若与新数字偶然相同，也要能追到新的 `source_manifest.json`，不能仅因字符串相同而保留旧来源。

**通过判据**：正文每个 E2 数字都能回指新正式表/统计 JSON；污染批和历史四臂数字不参与统计；同批与等算力边界分开；饥饿最大加倍后仍非空时如实披露；公开 13/18 和 China81 五臂证据不混写。

**不通过时怎么办**：判 `HALT_PAPER_E2_NUMERIC_PROVENANCE_OPEN`，停止摘要和编译；列出未闭合行号、旧值、新来源缺口，不凭语言润色绕过。

### 8. 论文回填第三阶段：最后更新中英文摘要

**唯一写入者**：`W-PAPER`。摘要是它对 `paper_main.tex` 的最后一次数值编辑。

**要做什么**：正文、表体和结语全部闭合后，才把最重要且可由新证据直接支持的 E2 结果压缩进摘要。不能先写摘要再倒推正文。

**摘要回填行号清单**：

|当前行号|对象|必须动作|
|---:|---|---|
|139--148|中文摘要|重点审查 143--145 的算法与“验证有效性”表述；只写洁净批支持的配对结果及公开 13/18 限制。147 行是 E3--E7 专用占位，E2 不得冒充填入。|
|156--165|英文摘要|与中文逐项同义；160--162 的 `full-model adjudication` 改为可定义的完整目标复算/可行性验证术语；164 行 E3--E7 占位保持独立。|

**命令/核验**：

```bash
cd '/Volumes/移动硬盘（512G）/ReSETP'
nl -ba docs/paper_v2/paper_main.tex | sed -n '138,166p'
rg -n 'DATA_PLACEHOLDER' docs/paper_v2/paper_main.tex
```

**通过判据**：中英文数字、方向和边界逐项一致；摘要不把 13/18 写成普遍优越，不把同批写成等算力，不把未完成的 E3--E7 填成结果；E2 相关位置无旧混批口径。

**不通过时怎么办**：判 `HALT_ABSTRACT_BODY_MISMATCH`，回到正文来源核对，不在摘要内单独改数或弱化边界。

### 9. 连续两遍 XeLaTeX、数学审计和逐页栅格化验收

**唯一写入者**：`W-PAPER`。编译产生的 PDF/XDV/AUX/LOG 和 `math_audit_report.md` 也只由它生成；`W-HANDOFF` 不并发。

**要做什么**：同一份已冻结 TeX 连续执行两遍 XeLaTeX，保存两遍日志；运行现有数学审计；把最终 PDF 每页栅格化并逐页人工看表、图、图例、版心和措辞。编译成功不等于视觉验收通过。

**命令**：

```bash
cd '/Volumes/移动硬盘（512G）/ReSETP/docs/paper_v2'
set -euo pipefail
shasum -a 256 paper_main.tex > /tmp/RUNBOOK-E2-CLOSEOUT-01.paper_main.before_compile.sha256
xelatex -interaction=nonstopmode -halt-on-error paper_main.tex \
  > /tmp/RUNBOOK-E2-CLOSEOUT-01.xelatex.pass1.log 2>&1
xelatex -interaction=nonstopmode -halt-on-error paper_main.tex \
  > /tmp/RUNBOOK-E2-CLOSEOUT-01.xelatex.pass2.log 2>&1
shasum -a 256 paper_main.tex > /tmp/RUNBOOK-E2-CLOSEOUT-01.paper_main.after_compile.sha256
cmp /tmp/RUNBOOK-E2-CLOSEOUT-01.paper_main.before_compile.sha256 \
  /tmp/RUNBOOK-E2-CLOSEOUT-01.paper_main.after_compile.sha256
python3 math_audit.py

export RESET_E2_RASTER_DIR="$(mktemp -d /tmp/RUNBOOK-E2-CLOSEOUT-01.pages.XXXXXX)"
pdftoppm -png -r 180 paper_main.pdf "$RESET_E2_RASTER_DIR/page"
pdfinfo paper_main.pdf
if rg -n 'Undefined control sequence|LaTeX Error|Overfull' \
  /tmp/RUNBOOK-E2-CLOSEOUT-01.xelatex.pass1.log; then
  echo 'HALT_XELATEX_PASS1_ERROR_OR_OVERFULL'
  exit 2
fi
if rg -n 'Undefined control sequence|LaTeX Error|undefined references|Rerun to get cross-references right|Overfull' \
  /tmp/RUNBOOK-E2-CLOSEOUT-01.xelatex.pass2.log paper_main.log; then
  echo 'HALT_XELATEX_PASS2_NOT_STABLE'
  exit 2
fi
```

**逐页人工验收项**：

1. 表 A 五臂列、两层表头、Best/avg 黑体、9 个分层行和总体行完整，无裁切、重叠、越界或字号异常。
2. 表 B 的 MV-vs-O 分组表与逐层转换表均完整，胜/平/负和改善百分比与统计 JSON 一致；表注未把描述性单元称为独立样本。
3. 所有图的图例、坐标、线型、颜色和标题可读；图例不遮挡数据；历史图若保留，其证据身份在正文和图注中一致。
4. 页面版心、页眉页脚、浮动体顺序、跨页表、公式、中文断行、英文缩写和参考文献无碰撞；无 Overfull；Underfull 逐条判断是否影响版面。
5. 措辞不出现开发台账黑话替代数学操作，例如无定义的“裁判、封存批、安全网、零回退”；“限时 MIP 解”不称精确最优；“同批”不称“等算力”。
6. 主文中不再可见 `FORMAT_DRY_RUN_INVALID`、格式干跑警告、旧车型/旧柴油价结果或未标明的旧混批数字。
7. PDF、XDV 和 LOG 时间戳均晚于最后一次 TeX 修改，页数与 `pdfinfo` 一致；每一张栅格页都实际打开检查，不抽页代替全检。

**通过判据**：两遍 XeLaTeX 均退出 0；第二遍无未定义引用和“需再运行”；`math_audit.py` 为 0 error；TeX 编译前后哈希相同；逐页 100% 检查通过；正式表、图、图例、版心和措辞全部闭合。

**不通过时怎么办**：判 `HALT_PAPER_COMPILE_OR_VISUAL_ACCEPTANCE`。只由 `W-PAPER` 修复对应 TeX/表体后重新从“两遍 XeLaTeX”起完整执行；不得只重跑第二遍，不得用旧 PDF 代替新 PDF，不得在栅格图上手工修图。

### 10. 验收后更新 HANDOFF 和相关记忆面

**唯一写入者**：`W-HANDOFF`。只有第 1--9 步全部 PASS 后接管；`W-PAPER` 先释放写锁。

**要做什么**：在 `HANDOFF.md` 登记真实终局，并同步最相关的 `docs/handoff/memory/project-prd-execution-v2.md`。只登记已核验结果，不复制整个表，不把 E2 完成写成 E3--E7 放行或论文完成。

**命令/材料**：

```bash
cd '/Volumes/移动硬盘（512G）/ReSETP'
shasum -a 256 \
  baselines/e2_rerun_unified_01_20260727/done.json \
  baselines/e2_rerun_unified_01_20260727/artifact_hashes.json \
  docs/handoff/runbook_e2_closeout_01_20260728/execution/record_layer_audit.json \
  docs/handoff/runbook_e2_closeout_01_20260728/execution/full_witness_replay.json \
  docs/paper_v2/generated_tables/formal_e2_clean_20260728/source_manifest.json \
  docs/paper_v2/paper_main.tex \
  docs/paper_v2/paper_main.pdf
```

HANDOFF 记录至少包含：最终 attempt 总行数、2025 个最终单元、K 加倍历史、最大加倍后残余饥饿单元格、失败数、两套违约数、MV-vs-O 新配对结果、污染 165 行排除证据、五件套和外层哈希、论文新表路径、两遍编译/逐页验收结果、`equal_compute_claim_allowed=false`、后续 D3/D4 仍需各自合同门。

**通过判据**：HANDOFF 与机器 JSON 数字逐项一致；相关 memory 只作路由摘要；没有“论文已完成”“E3/E6 已放行”或等算力主张；记录由一个提交/一个写入者顺序完成。

**不通过时怎么办**：判 `HALT_HANDOFF_RECORD_DRIFT`，先修记录，不改实验或论文来迎合 HANDOFF。

### 11. 最终资源释放确认；之后才允许准备 D3 和 D4

**唯一写入者**：本步扫描只读；`W-E2-AUDIT` 可写 `execution/resource_release.json`。任何进程终止仍由对应进程所有者执行，不由论文或 HANDOFF 写入者越权。

**要做什么**：在所有审计、制表、编译进程都退出后，确认没有 E2 driver、spawn worker、resource tracker、PyVRP/HiGHS 子进程、监控器或仍持有 E2 文件的孤儿进程，再发出资源释放令牌。不能因为 `done.json` 存在就默认 worker 已回收。

**命令**：

```bash
cd '/Volumes/移动硬盘（512G）/ReSETP'
ps -axo pid=,ppid=,pgid=,state=,etime=,command= | \
  rg '[r]un_unified_campaign\.py|[m]ultiprocessing\.spawn|[m]ultiprocessing\.resource_tracker|[p]yvrp|[h]ighs|e2-rerun-unified-01-full-clean-restart'

lsof 2>/dev/null | \
  rg '/Volumes/移动硬盘（512G）/ReSETP/baselines/e2_rerun_unified_01_20260727/'
```

两个命令在排除当前 `rg/lsof` 自身后都应无匹配。随后由单进程写释放记录：

```bash
cd '/Volumes/移动硬盘（512G）/ReSETP'
python3 - <<'PY'
from pathlib import Path
import datetime
import hashlib
import json

repo = Path.cwd().resolve()
e2 = repo / 'baselines/e2_rerun_unified_01_20260727'
out = repo / 'docs/handoff/runbook_e2_closeout_01_20260728/execution/resource_release.json'
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
payload = {
    'status': 'RESOURCE_RELEASED_FOR_D3_D4_PREPARATION',
    'confirmed_at_utc': datetime.datetime.now(datetime.UTC).isoformat(),
    'residual_e2_driver_count': 0,
    'residual_worker_or_orphan_count': 0,
    'open_e2_file_holder_count': 0,
    'done_json_sha256': sha(e2 / 'done.json'),
    'artifact_hashes_json_sha256': sha(e2 / 'artifact_hashes.json'),
    'note': 'Necessary resource prerequisite only; not automatic authorization to run stale D3/D4 entrypoints.',
}
out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
PY
```

**通过判据**：无残留 driver、worker、resource tracker、监控器、HiGHS/PyVRP 子进程或 E2 文件句柄；释放记录绑定最终 `done.json` 和哈希清单。此后才可进入 D3/D4 的“准备”状态。

**不通过时怎么办**：判 `HALT_E2_RESOURCES_NOT_RELEASED`。先记录 PID/PPID/PGID、状态、命令和所持文件；确认是否仍在原子写盘。不得自动 `kill -9`。需要终止时由进程所有者在确认写盘完成后优先 `SIGTERM`；强制终止必须先取得用户确认。

**D3/D4 额外硬门，不因资源释放而自动满足**：

1. D3 的目标入口是 `baselines/china_e3_e7/verify_e3_arm_semantics.py`，但当前脚本绑定旧 `E3_ARM_GATE` 输出且遇到已有目录会拒绝覆盖；旧门的 adapter/epochal/route-pool 哈希已经漂移。必须先为 2026-07-28 批准合同建立新的输出目录、冻结当前源码哈希，再执行零搜索重放；禁止覆盖旧 PASS 或直接运行旧输出绑定。
2. D4 的目标入口是 `baselines/china_e3_e7/run_e3_budget_pilot.py`，但当前版本只检查固定 80 次候选，并未记录 L/S，也未实现批准的 80/56/32 最小非饥饿档及三档均失败时向 160、240 等上调。因此当前入口判 `HALT_D4_RUNNER_NOT_MATCHING_APPROVED_ANTISTARVATION_CONTRACT`，在代码/合同同步并获独立复核前不得启动。
3. D3 先运行并通过，D4 再单线程运行；二者不得互相并发，也不得与其他正式实验池重叠。

## 四、最终状态词

只有全部步骤通过，才允许写：

```text
PASS_RUNBOOK_E2_CLOSEOUT_01
RESOURCE_RELEASED_FOR_D3_D4_PREPARATION
```

不得仅凭 2025 行、`done.json` 单文件、两张 TeX 表或一次 XeLaTeX 写上述状态。任何中间失败保留具体 `HALT_*`，不救援调参、不混用旧批、不提前启动 D3/D4。
