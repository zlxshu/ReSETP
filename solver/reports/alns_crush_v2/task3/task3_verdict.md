# Task3 Lean ALNS Verdict

Methodological note: V2 keeps the kernel threshold-style acceptance when selected; the ALNS-vs-SA distinction is the large destroy-repair neighborhood, not the acceptance criterion.

- 100-01-24h winner_kernel_only ALNS-Wouda: 碾压; mean=4878.331796, fair-SA=5346.986857, delta=-468.655061, wins=10/10, p=0.000976562.
- L-main winner_kernel_only ALNS-Wouda: 失败; mean=8351.639755, fair-SA=8319.837849, delta=31.801906, wins=5/10, p=0.652344.
- 100-01-24h winner_kernel_route_elimination ALNS-Wouda: 失败; mean=4893.225562, fair-SA=5346.986857, delta=-453.761295, wins=10/10, p=0.000976562.
- L-main winner_kernel_route_elimination ALNS-Wouda: 失败; mean=8424.043977, fair-SA=8319.837849, delta=104.206129, wins=2/10, p=0.975586.