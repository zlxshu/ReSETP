# ALNS Scale Crush 150/200

This report uses newly generated static three-shift 24h instances and compares winner_kernel_v1 against fair scikit-opt-SA with the same 16000-evaluation / 900-second口径.

Honesty note: 150/200 follow the same tight three-shift construction as L-main, so持平 is expected if route-count headroom is physically thin. No parameter tuning, seed picking, route-elimination add-on, true-cost repair, RRT/AlphaUCB, or embedded LS is introduced in this scale run.

## Generation
- Scale-150: customers=150 requested=150, demand=70242.400, capacity_lb=44, FFD=45, kept_by_shift={"0": 64, "1": 64, "2": 22}, deleted=43, dynamic_events_tsv_exists=False.
- Scale-200: customers=200 requested=200, demand=90021.400, capacity_lb=57, FFD=57, kept_by_shift={"0": 87, "1": 88, "2": 25}, deleted=62, dynamic_events_tsv_exists=False.

## Scale Verdict
- Scale-150: 失败; winner mean £5814.048 vs fair SA £5754.712, diff=1.031%, best winner £5682.491, p_less=0.967773, p_greater=0.0419922, wins=3/10, routes=49.00 vs capacity_lb=44.0.
- Scale-200: 持平; winner mean £7545.632 vs fair SA £7601.908, diff=-0.740%, best winner £7492.133, p_less=0.0966797, p_greater=0.919922, wins=6/10, routes=61.00 vs capacity_lb=57.0.

## Context
- 100-01-24h: 碾压; V2: winner kernel mean £4878 vs fair SA £5347, about 8.8% lower; 32 routes. single 100-customer static instance, looser route-count headroom.
- L-main: 持平; V2: winner kernel about £8351 vs fair SA about £8319; capacity lower bound 60, best near 64 routes. three-shift 219-customer instance near capacity route-count lower bound.

Conclusion rule: 碾压 requires >1pp lower mean cost, paired Wilcoxon p_less<0.05, wins>=8/10, and winner std <= 1.25x SA std. 失败 is used when winner is >1pp worse and paired Wilcoxon p_greater<0.05. Otherwise the scale instance is marked 持平.