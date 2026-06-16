# ALNS Scale Crush Generation

Scale instances use the L-main three-shift static 24h construction. No dynamic event stream is generated.

- Scale-150: requested=150, actual=150, exact=True, demand=70242.400, capacity_lb=44, ffd=45, kept_by_shift={"0": 64, "1": 64, "2": 22}, deleted=43.
- Scale-200: requested=200, actual=200, exact=True, demand=90021.400, capacity_lb=57, ffd=57, kept_by_shift={"0": 87, "1": 88, "2": 25}, deleted=62.

Post-merge deletion to hit a target count was not used.