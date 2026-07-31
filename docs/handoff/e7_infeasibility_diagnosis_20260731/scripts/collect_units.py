"""只读：把 120 个 E7 单元 JSON 的关键字段汇总成一张表。"""
import json, glob, os, re, sys, collections

ROOT = '/Volumes/移动硬盘（512G）/ReSETP'
BASE = os.path.join(ROOT, 'baselines/china_e3_e7/e7_dynamic_v3_20260731/formal')

def load_units():
    rows = []
    for sc in ['50c', '100c', '150c']:
        for f in sorted(glob.glob(f'{BASE}/{sc}/tasks/*.json')):
            if os.path.basename(f).startswith('._'):
                continue
            d = json.load(open(f))
            d['_file'] = os.path.relpath(f, ROOT)
            rows.append(d)
    return rows

def reason_class(r):
    if not r:
        return 'NONE'
    if 'no inherited asset can serve open route' in r:
        return 'NO_INHERITED_ASSET'
    if 'no executable continuation' in r:
        return 'NO_EXECUTABLE_CONTINUATION'
    return 'OTHER'

if __name__ == '__main__':
    rows = load_units()
    out = []
    for d in rows:
        reason = d.get('legal_infeasibility_reason')
        out.append(dict(
            file=d['_file'], scale=d['scale'], instance=d['instance_id'],
            seed=d['algorithm_seed'], stream=d['stream_seed'], arm=d['arm'],
            status=d['status'], feasible=d.get('feasible'),
            stage_count=d['stage_count'],
            attempted=d.get('attempted_stage_count'),
            completed=d.get('completed_stage_count'),
            failure_stage=d.get('failure_stage'),
            reason_class=reason_class(reason), reason=reason,
            nominal_total_cost=d['nominal_total_cost'],
            final_total_cost=d['final_total_cost'],
            actual_evaluations=d['actual_evaluations'],
            wall_seconds=d['wall_seconds'],
            cross_depot=d['cross_depot_reassignment_after_event'],
            carbon_shift=d['carbon_aware_charging_shift_after_event'],
            moved_charge=d['moved_charge_actions_after_event'],
            member_profit_shift=d['member_profit_shift_after_event'],
            vehicle_count=d['vehicle_count'],
            nominal_plan_path=d['nominal_plan_path'],
            nominal_plan_sha256=d['nominal_plan_sha256'],
            event_path=d['event_path'],
        ))
    json.dump(out, open(os.path.join(os.path.dirname(__file__), 'units_table.json'), 'w'),
              ensure_ascii=False, indent=1)
    print(f'units={len(out)}')
    c = collections.Counter((r['scale'], r['status']) for r in out)
    for k, v in sorted(c.items()):
        print(k, v)
    c2 = collections.Counter((r['scale'], r['reason_class']) for r in out)
    for k, v in sorted(c2.items()):
        print(k, v)
