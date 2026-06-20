---
name: deferred-instance-robustness
description: NOW ACTIVE (2026-06-16) — generate 150c/200c three-shift dynamic instances; primary purpose shifted to ALNS-vs-SA crush test + robustness
metadata: 
  node_type: memory
  type: project
  originSessionId: c7e19b75-f4af-454a-9cdd-0285773bf61c
---

After the R2 carbon stress test (run on the 219-customer main instance `E-UK24h-三班-01`), the user wants to verify robustness across **three-shift concatenated instances of multiple customer sizes (100 / 150 / 200, "全部测一遍")**. The user's "100算例" means a three-shift *concatenated* instance, not the original `E-UK100_01` pilot. 150c and 200c instances do **not exist in the repo yet** — they must be generated first.

**Why:** The carbon-price insensitivity finding currently rests on one main instance (219c). Reviewer external-validity concern.

**2026-06-16 ACTIVATED + repurposed:** after ALNS crush settled (100-01 crush, L-main tie via lower-bound proof, see [[alns-crush-root-cause]]), user chose to **generate 150c/200c three-shift dynamic instances** (same E-UK24h-三班-01 generation pipeline) and test whether winner-kernel ALNS crushes fair SA on them — PRIMARY purpose now = find crush headroom at other scales; carbon robustness is secondary. **Honest expectation:** crush depends on constraint tightness, NOT size (L-main 219c ties because near route-count lower bound; 100c crushes because looser). Tight three-shift instances at 150/200c may also tie — report honestly, don't force a crush narrative. Needs the instance-generation script located + an E4/comparison "swap instance" hook (E4 hardcoded to L-main in formal_runner.py). Write to solver/reports/alns_scale_crush/.
