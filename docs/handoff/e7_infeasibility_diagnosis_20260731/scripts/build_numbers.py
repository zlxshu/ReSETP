"""只读：汇总六个问题的数字，写出 diagnosis_numbers.json。"""
import json, os, collections

HERE = os.path.dirname(__file__)
OUT = os.path.abspath(os.path.join(HERE, '..', 'diagnosis_numbers.json'))

units = json.load(open(os.path.join(HERE, 'units_table.json')))
q1 = json.load(open(os.path.join(HERE, 'q1_event_vs_fleet.json')))

ROLLING = {'FULL_ROLLING', 'NO_COOPERATION', 'CARBON_BLIND'}


def reason_prefix(r):
    if r is None:
        return 'NONE'
    if r.startswith('no feasible vehicle type assignment'):
        return 'NO_FEASIBLE_VEHICLE_TYPE_ASSIGNMENT'
    if r.startswith('stage search found no executable continuation'):
        return 'NO_EXECUTABLE_CONTINUATION'
    return 'OTHER'


res = {}

# ---- 单元层 ----
res['unit_census'] = {
    'total_units': len(units),
    'by_scale_status': {f'{k[0]}|{k[1]}': v for k, v in
                        sorted(collections.Counter((u['scale'], u['status']) for u in units).items())},
    'by_scale_arm_reason': {f'{k[0]}|{k[1]}|{k[2]}': v for k, v in
                            sorted(collections.Counter(
                                (u['scale'], u['arm'], reason_prefix(u['reason'])) for u in units).items())},
    'pass_units': [f"{u['scale']}|seed{u['seed']:02d}|stream{u['stream']}|{u['arm']}"
                   for u in units if u['status'] == 'PASS'],
}

# ---- 名义方案退化度 ----
plans = collections.defaultdict(set)
for u in units:
    plans[u['scale']].add(u['nominal_plan_sha256'])
res['nominal_plan_degeneracy'] = {
    sc: {'distinct_plan_sha256': len(v), 'units': sum(1 for u in units if u['scale'] == sc)}
    for sc, v in sorted(plans.items())
}
res['nominal_plan_degeneracy']['note'] = (
    '150c 的 40 个单元共用同一个名义方案（来自 E6 initial_solution），'
    '故 150c 的 seed 维度不携带独立信息；50c/100c 每个 seed 有独立 E3 JOINT 方案。'
)

# ---- Q1 事件强度 vs 车队 ----
caps = q1['fleet_caps']
assets = q1['nominal_plan_assets']
scale_rows = []
for s in q1['streams']:
    sc = s['scale']
    seed_key = f'{sc}|seed01'
    by = assets[seed_key]['by_depot_type']
    depot_adds = collections.Counter()
    for st in s['stages']:
        for d, n in st['add_by_owner_depot'].items():
            depot_adds[d] += n
    per_stage = []
    for st in s['stages']:
        expired = [a['customer_id'] for a in st['adds'] if a['due_before_trigger']]
        dep = list(st['add_by_owner_depot'])
        inh = {d: by.get(f'{d}|cv', 0) + by.get(f'{d}|ev', 0) for d in dep}
        per_stage.append({
            'stage': st['stage'],
            'trigger_second': st['trigger_time'],
            'trigger_reason': st['trigger_reason'],
            'events': st['event_count'],
            'adds': st['add_count'],
            'add_by_owner_depot': st['add_by_owner_depot'],
            'inheritable_assets_at_those_depots_upper_bound': inh,
            'adds_over_inheritable_ratio': {
                d: round(st['add_by_owner_depot'][d] / inh[d], 4) for d in dep if inh.get(d)
            },
            'expired_adds_due_before_trigger': expired,
            'expired_count': len(expired),
        })
    fail_roll = [u['failure_stage'] for u in units
                 if u['scale'] == sc and u['stream'] == s['stream_seed'] and u['arm'] in ROLLING]
    fail_static = [u['failure_stage'] for u in units
                   if u['scale'] == sc and u['stream'] == s['stream_seed']
                   and u['arm'] == 'STATIC_FIXED_RECOURSE']
    first_expired = next((x['stage'] for x in per_stage if x['expired_count']), None)
    scale_rows.append({
        'scale': sc, 'stream_seed': s['stream_seed'],
        'rolling_parameters': s['rolling_parameters'],
        'total_events': s['total_events'], 'total_adds': s['total_adds'],
        'add_owner_depots_over_whole_stream': dict(depot_adds),
        'stages': per_stage,
        'first_stage_with_expired_add': first_expired,
        'observed_failure_stage_rolling_arms': sorted(set(x for x in fail_roll if x is not None)) or None,
        'observed_failure_stage_static_arm': sorted(set(fail_static)),
    })
res['q1_event_intensity_vs_fleet'] = {
    'fleet_caps_by_depot': caps,
    'nominal_plan_assets_upper_bound': assets,
    'unused_legal_fleet_lower_bound': {
        '50c': {'cap_total': 12, 'nominal_plan_routes': 8, 'unused_at_least': 4,
                'D_guangzhou_cap': {'cv': 4, 'ev': 1}, 'D_guangzhou_plan': {'cv': 2, 'ev': 1},
                'all_adds_owner_depot': 'D_guangzhou'},
        '100c': {'cap_total': 23, 'nominal_plan_routes': 17, 'unused_at_least': 6,
                 'D_guangzhou_cap': {'cv': 8, 'ev': 2}, 'D_guangzhou_plan': {'cv': 5, 'ev': 2},
                 'all_adds_owner_depot': 'D_guangzhou'},
        '150c': {'cap_total': 35, 'nominal_plan_routes': 27, 'unused_at_least': 8,
                 'D_dongguan_cap': {'cv': 4, 'ev': 1}, 'D_dongguan_plan': {'cv': 3, 'ev': 1},
                 'all_adds_owner_depot': 'D_dongguan'},
    },
    'streams': scale_rows,
}

# ---- Q5 四臂数值 ----
def unit(sc, seed, arm):
    for u in units:
        if u['scale'] == sc and u['seed'] == seed and u['arm'] == arm:
            return u
    return None

arm_cmp = {}
for seed in (4, 9):
    row = {}
    for arm in ['STATIC_FIXED_RECOURSE', 'FULL_ROLLING', 'NO_COOPERATION', 'CARBON_BLIND']:
        u = unit('50c', seed, arm)
        row[arm] = {'status': u['status'], 'final_total_cost': u['final_total_cost'],
                    'nominal_total_cost': u['nominal_total_cost'],
                    'vehicle_count': u['vehicle_count'],
                    'cross_depot_reassignment_after_event': u['cross_depot'],
                    'carbon_aware_charging_shift_after_event': u['carbon_shift'],
                    'moved_charge_actions_after_event': u['moved_charge']}
    fr, nc, cb = row['FULL_ROLLING'], row['NO_COOPERATION'], row['CARBON_BLIND']
    row['_delta_no_cooperation_vs_full_pct'] = (
        None if fr['final_total_cost'] is None else
        round(100.0 * (nc['final_total_cost'] - fr['final_total_cost']) / fr['final_total_cost'], 6))
    row['_carbon_blind_equals_full'] = cb['final_total_cost'] == fr['final_total_cost']
    arm_cmp[f'50c|seed{seed:02d}|stream4'] = row
res['q5_arm_contrast'] = arm_cmp

json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=1)
print('written', OUT)
for k, v in res['q5_arm_contrast'].items():
    print(k, v['_delta_no_cooperation_vs_full_pct'], v['_carbon_blind_equals_full'])
for r in scale_rows:
    print(r['scale'], r['stream_seed'], 'first_expired', r['first_stage_with_expired_add'],
          'fail_roll', r['observed_failure_stage_rolling_arms'],
          'depots', r['add_owner_depots_over_whole_stream'])
