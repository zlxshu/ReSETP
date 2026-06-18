# Observation Aliasing Probe

| split | algorithm | rows | unique rounded obs | obs reuse | conflict rate |
|---|---|---:|---:|---:|---:|
| formal_10001 | alpha_ucb_env | 6144 | 832 | 0.865 | 0.069 |
| formal_10001 | ppo_full | 6144 | 2684 | 0.563 | 0.001 |
| formal_10001 | random_full | 6144 | 6058 | 0.014 | 0.000 |
| held_out | alpha_ucb_env | 6144 | 889 | 0.855 | 0.067 |
| held_out | ppo_full | 6144 | 1782 | 0.710 | 0.000 |
| held_out | random_full | 6144 | 6049 | 0.015 | 0.000 |
| train0 | alpha_ucb_env | 6144 | 864 | 0.859 | 0.058 |
| train0 | ppo_full | 6144 | 2199 | 0.642 | 0.000 |
| train0 | random_full | 6144 | 6057 | 0.014 | 0.000 |

Interpretation: repeated/coarse observations with conflicting outcomes suggest the policy cannot reliably condition operator choices.
