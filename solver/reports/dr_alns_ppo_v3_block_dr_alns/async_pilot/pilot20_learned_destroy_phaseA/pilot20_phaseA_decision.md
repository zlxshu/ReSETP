# Pilot20 Learned-Destroy Phase A Decision

Final decision: `UNDERTRAINED_DEFERRED_RUNTIME`

This run did not pass Phase A, but it also should not be treated as a true learned-destroy negative result. All formal runs used the required py313 worker with NumPy 2.3.5, used the full evaluation budget, and produced zero learned-solution violations. The learning curves did not show a clear learning signal after the planned escalation cap.

| Run | Train episodes | Eval budget | Runner verdict | Avg vs operator-select | Min scale | Avg vs random | Reward early/mid/late | Final decision use |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | --- |
| `formal_120` | 120 | 120 | `HALT_LEARNED_DESTROY` | -22.429% | -30.613% | -23.104% | 39.508 / 39.720 / 39.158 | undertrained |
| `formal_240` | 240 | 120 | `HALT_LEARNED_DESTROY` | -12.259% | -19.481% | -12.887% | 39.614 / 39.724 / 38.812 | undertrained |
| `formal_240_b180` | 240 | 180 | `HALT_LEARNED_DESTROY` | -14.493% | -15.453% | -15.439% | 42.728 / 42.671 / 42.933 | undertrained cap |

`formal_240_b180` was the configured cap for this turn. Its late reward mean improved only +0.480% over the early mean, while entropy increased from 29.804 to 32.680 and peaked at 38.698. That is not a clear learned policy signal. Therefore Phase B is not opened, and the result is recorded as deferred/undertrained rather than as proof that customer-level learned destroy cannot work.

Smoke and formal artifacts are kept under this directory. The authoritative final decision is this file plus the HANDOFF entry, not the raw runner verdict alone.
