# Metaheuristic Baseline Profile

One-line conclusion: profile is a throughput diagnostic only; dominance claims require the formal comparison gate.

Commit: 7de2c847
Environment: /opt/anaconda3/bin/python3.13, numpy 2.3.5
Instance/seed/evals: 100-01-24h / 1 / 100

## Throughput
- ACO: status=OK, eval/s=149.542, projected_16000=107.0s, cap_decision=900s, best_cost=6331.298733608956.
- GWO: status=OK, eval/s=26.154, projected_16000=611.8s, cap_decision=900s, best_cost=6331.298733608956.
- IWD: status=OK, eval/s=102.692, projected_16000=155.8s, cap_decision=900s, best_cost=6331.298733608956.
- VNS: status=OK, eval/s=41.453, projected_16000=386.0s, cap_decision=900s, best_cost=6331.298733608956.
- winner-kernel ALNS: status=OK, eval/s=21.045, projected_16000=760.3s, cap_decision=900s, best_cost=5406.294961824951.

## Time Buckets
- ACO: decode_order_to_solution=57.3%/101x; check_solution=26.8%/239x; evaluate=7.7%/103x; other_or_uninstrumented=7.7%/0x; repair_route_charging=0.5%/34x
- GWO: other_or_uninstrumented=85.2%/0x; decode_order_to_solution=8.5%/82x; check_solution=5.0%/286x; evaluate=1.3%/102x; repair_route_charging=0.1%/50x
- IWD: decode_order_to_solution=38.6%/96x; other_or_uninstrumented=36.1%/0x; check_solution=19.4%/299x; evaluate=5.0%/102x; repair_route_charging=0.9%/96x
- VNS: other_or_uninstrumented=81.8%/0x; decode_order_to_solution=10.4%/62x; check_solution=5.9%/211x; evaluate=1.9%/103x; repair_route_charging=0.0%/6x
- winner-kernel ALNS: other_or_uninstrumented=98.5%/0x; check_solution=0.9%/101x; evaluate=0.7%/102x

## Method
The profile wraps decode, evaluate, check_solution, and EV charging repair call sites in-process. Bucket shares are diagnostic and may overlap less than cProfile; the formal gate is still full eval count, zero violations, and system Python/numpy.
