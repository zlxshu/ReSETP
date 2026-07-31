"""只读：Q1 事件流强度 vs 车队余量。

复刻 solver/src/setp_solver/search/dynamic.py:998 `_build_trigger_batches` 的分批规则，
不 import solver（避免任何副作用），逐条事件流统计每阶段新增订单数、时间窗、
以及名义方案里按 (车场, 车型) 分桶的可继承资产数。
"""
import csv, json, os, collections

ROOT = '/Volumes/移动硬盘（512G）/ReSETP'
EVENTS = os.path.join(ROOT, 'baselines/china_e3_e7/mechanism_foundation_20260730/inputs/e7_events')
OWNERS = os.path.join(ROOT, 'baselines/china_e3_e7/e7_dynamic_v3_20260731/inputs/owners')
FLEET = os.path.join(ROOT, 'data/ChinaInstances/china81_finite_fleet_authority_v1_20260723/fleet_caps.csv')
UNITS = os.path.join(os.path.dirname(__file__), 'units_table.json')

INSTANCE_BY_SCALE = {
    '50c': 'cn-prd-50c-01-V2-LOCATIONS',
    '100c': 'cn-prd-100c-02-V2-LOCATIONS',
    '150c': 'cn-prd-150c-01-V2-LOCATIONS',
}


def build_trigger_batches(events, delta_t, q_bar):
    """逐行复刻 dynamic.py:998-1023。"""
    se = sorted(events, key=lambda e: (float(e['t_appear']), str(e['event_id'])))
    batches = [{'stage': 0, 'trigger_time': 0.0, 'trigger_reason': 'initial', 'events': []}]
    cursor, last_trigger, stage = 0, 0.0, 1
    while cursor < len(se):
        deadline = last_trigger + float(delta_t)
        batch = []
        broke = False
        while cursor < len(se) and float(se[cursor]['t_appear']) <= deadline:
            batch.append(se[cursor])
            cursor += 1
            if len(batch) >= int(q_bar):
                trigger_time = float(batch[-1]['t_appear'])
                batches.append({'stage': stage, 'trigger_time': trigger_time,
                                'trigger_reason': 'q_bar', 'events': batch})
                last_trigger = trigger_time
                stage += 1
                broke = True
                break
        if not broke:
            if batch:
                batches.append({'stage': stage, 'trigger_time': deadline,
                                'trigger_reason': 'delta_t', 'events': batch})
                stage += 1
            last_trigger = deadline
    return batches


def fleet_caps():
    caps = collections.defaultdict(dict)
    with open(FLEET) as fh:
        for row in csv.DictReader(fh):
            caps[row['instance_id']][row['depot_id']] = {
                'cv': int(row['num_cv']), 'ev': int(row['num_ev']),
                'total': int(row['total_fleet_cap']),
            }
    return caps


def plan_assets(path):
    d = json.load(open(os.path.join(ROOT, path)))
    routes = d['solution']['routes'] if 'solution' in d else d['routes']
    c = collections.Counter((r['home_depot_id'], r['vehicle_type'].lower()) for r in routes)
    return dict(c), len(routes)


def main():
    units = json.load(open(UNITS))
    plan_by = {}
    for u in units:
        plan_by.setdefault((u['scale'], u['seed']), u['nominal_plan_path'])
    caps = fleet_caps()

    out = {'streams': [], 'fleet_caps': {}, 'nominal_plan_assets': {}}
    for scale, inst in INSTANCE_BY_SCALE.items():
        out['fleet_caps'][scale] = caps[inst]

    # 名义方案资产（按 seed）
    for (scale, seed), path in sorted(plan_by.items()):
        by, n = plan_assets(path)
        out['nominal_plan_assets'][f'{scale}|seed{seed:02d}'] = {
            'path': path, 'route_count': n,
            'by_depot_type': {f'{d}|{t}': v for (d, t), v in sorted(by.items())},
        }

    for scale, inst in INSTANCE_BY_SCALE.items():
        for stream in range(1, 6):
            ev = json.load(open(f'{EVENTS}/{inst}/stream_seed{stream}.json'))
            ow = json.load(open(f'{OWNERS}/{inst}/stream_seed{stream}.json'))['mapping']
            rp = ev['rolling_parameters']
            batches = build_trigger_batches(ev['events'], rp['delta_t_seconds'], rp['q_bar'])
            stages = []
            for b in batches:
                if not b['events']:
                    continue
                adds = [e for e in b['events'] if e['event_type'] == 'add']
                by_depot = collections.Counter(ow.get(e['customer_id'], 'UNMAPPED') for e in adds)
                stages.append({
                    'stage': b['stage'],
                    'trigger_time': b['trigger_time'],
                    'trigger_reason': b['trigger_reason'],
                    'event_count': len(b['events']),
                    'type_counts': dict(collections.Counter(e['event_type'] for e in b['events'])),
                    'add_count': len(adds),
                    'add_by_owner_depot': dict(by_depot),
                    'adds': [{
                        'customer_id': e['customer_id'],
                        'owner_depot': ow.get(e['customer_id'], 'UNMAPPED'),
                        'donor': e['donor_customer_id'],
                        't_appear': e['t_appear'],
                        'ready': e['new_ready_time'],
                        'due': e['new_due_time'],
                        'service': e['new_service_time'],
                        'demand': e['new_demand'],
                        'slack_trigger_to_due': e['new_due_time'] - b['trigger_time'],
                        'due_before_trigger': e['new_due_time'] < b['trigger_time'],
                    } for e in adds],
                })
            out['streams'].append({
                'scale': scale, 'instance': inst, 'stream_seed': stream,
                'rolling_parameters': rp,
                'total_events': len(ev['events']),
                'total_adds': sum(1 for e in ev['events'] if e['event_type'] == 'add'),
                'batch_count': len(stages),
                'stages': stages,
            })

    json.dump(out, open(os.path.join(os.path.dirname(__file__), 'q1_event_vs_fleet.json'), 'w'),
              ensure_ascii=False, indent=1)

    # 打印
    print('== fleet caps ==')
    for scale, d in out['fleet_caps'].items():
        tot_cv = sum(v['cv'] for v in d.values()); tot_ev = sum(v['ev'] for v in d.values())
        print(f'{scale}: depots={len(d)} cv={tot_cv} ev={tot_ev} total={tot_cv+tot_ev}  {d}')
    print()
    print('== nominal plan assets ==')
    for k, v in out['nominal_plan_assets'].items():
        print(f"{k}: routes={v['route_count']} {v['by_depot_type']}")
    print()
    print('== streams ==')
    for s in out['streams']:
        print(f"--- {s['scale']} stream{s['stream_seed']} events={s['total_events']} adds={s['total_adds']} batches={s['batch_count']}")
        for st in s['stages']:
            print(f"   stage{st['stage']} trig={st['trigger_time']:.1f} ({st['trigger_reason']}) "
                  f"n={st['event_count']} {st['type_counts']} adds={st['add_count']} by_depot={st['add_by_owner_depot']}")
            for a in st['adds']:
                print(f"        {a['customer_id']:6} {a['owner_depot']:14} appear={a['t_appear']:9.1f} "
                      f"ready={a['ready']:9.1f} due={a['due']:9.1f} slack_to_due={a['slack_trigger_to_due']:9.1f} "
                      f"due<trig={a['due_before_trigger']} q={a['demand']}")


if __name__ == '__main__':
    main()
