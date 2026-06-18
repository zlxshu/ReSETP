# Observed Action-Value Table

This is an empirical trace ranking, not a counterfactual proof. It shows which action families looked useful in observed trajectories.

| split | algorithm | destroy | repair | q | steps | improved-best rate | mean reward |
|---|---|---|---|---:|---:|---:|---:|
| formal_10001 | alpha_ucb_env | random_customer_removal | greedy_insert_repair |  | 1294 | 0.0386 | 0.1932 |
| formal_10001 | alpha_ucb_env | shaw_related_removal | regret3_insert_repair |  | 60 | 0.0333 | 0.1667 |
| formal_10001 | alpha_ucb_env | vehicle_type_swap | greedy_insert_repair |  | 1912 | 0.0319 | 0.1595 |
| formal_10001 | alpha_ucb_env | worst_customer_removal | greedy_insert_repair |  | 83 | 0.0241 | 0.1205 |
| formal_10001 | alpha_ucb_env | worst_customer_removal | regret3_insert_repair |  | 83 | 0.0241 | 0.1205 |
| formal_10001 | alpha_ucb_env | shaw_related_removal | greedy_insert_repair |  | 1029 | 0.0224 | 0.1118 |
| formal_10001 | alpha_ucb_env | route_segment_removal | regret2_insert_repair |  | 143 | 0.0140 | 0.0699 |
| formal_10001 | alpha_ucb_env | whole_route_removal | greedy_insert_repair |  | 1496 | 0.0120 | 0.0602 |
| formal_10001 | alpha_ucb_env | whole_route_removal | regret3_insert_repair |  | 8 | 0.0000 | 0.0000 |
| formal_10001 | ppo_full | vehicle_type_swap | regret2_insert_repair | 0.333333 | 6144 | 0.0057 | 0.1264 |
| formal_10001 | random_full | vehicle_type_swap | greedy_insert_repair | 0.166667 | 41 | 0.2439 | 1.3464 |
| formal_10001 | random_full | vehicle_type_swap | greedy_insert_repair | 0.366667 | 29 | 0.2414 | 1.3656 |
| formal_10001 | random_full | vehicle_type_swap | regret3_insert_repair | 0.133333 | 44 | 0.2045 | 1.1727 |
| formal_10001 | random_full | vehicle_type_swap | regret2_insert_repair | 0.366667 | 30 | 0.2000 | 1.1178 |
| formal_10001 | random_full | vehicle_type_swap | regret3_insert_repair | 0.233333 | 37 | 0.1892 | 1.1319 |
| formal_10001 | random_full | vehicle_type_swap | regret2_insert_repair | 0.300000 | 27 | 0.1852 | 1.1121 |
| formal_10001 | random_full | vehicle_type_swap | regret2_insert_repair | 0.266667 | 28 | 0.1786 | 1.0237 |
| formal_10001 | random_full | vehicle_type_swap | greedy_insert_repair | 0.266667 | 30 | 0.1667 | 1.0188 |
| formal_10001 | random_full | vehicle_type_swap | greedy_insert_repair | 0.233333 | 33 | 0.1515 | 0.9417 |
| formal_10001 | random_full | vehicle_type_swap | regret2_insert_repair | 0.133333 | 31 | 0.1290 | 0.8213 |
| formal_10001 | random_full | vehicle_type_swap | regret3_insert_repair | 0.166667 | 32 | 0.1250 | 0.7853 |
| formal_10001 | random_full | vehicle_type_swap | regret3_insert_repair | 0.200000 | 33 | 0.1212 | 0.8153 |
| formal_10001 | random_full | vehicle_type_swap | regret3_insert_repair | 0.100000 | 25 | 0.1200 | 0.7768 |
| formal_10001 | random_full | vehicle_type_swap | regret2_insert_repair | 0.100000 | 42 | 0.1190 | 0.7656 |
| formal_10001 | random_full | vehicle_type_swap | regret2_insert_repair | 0.166667 | 34 | 0.1176 | 0.7623 |
| formal_10001 | random_full | vehicle_type_swap | greedy_insert_repair | 0.333333 | 29 | 0.1034 | 0.6616 |
| formal_10001 | random_full | vehicle_type_swap | regret3_insert_repair | 0.300000 | 39 | 0.1026 | 0.7063 |
| formal_10001 | random_full | vehicle_type_swap | regret3_insert_repair | 0.266667 | 36 | 0.0833 | 0.5496 |
| formal_10001 | random_full | vehicle_type_swap | regret2_insert_repair | 0.233333 | 42 | 0.0714 | 0.5603 |
| formal_10001 | random_full | vehicle_type_swap | greedy_insert_repair | 0.133333 | 43 | 0.0698 | 0.5417 |
| formal_10001 | random_full | worst_customer_removal | regret3_insert_repair | 0.333333 | 43 | 0.0698 | 0.3488 |
| formal_10001 | random_full | vehicle_type_swap | regret3_insert_repair | 0.366667 | 30 | 0.0667 | 0.5535 |
| formal_10001 | random_full | vehicle_type_swap | regret2_insert_repair | 0.333333 | 30 | 0.0667 | 0.4820 |
| formal_10001 | random_full | vehicle_type_swap | greedy_insert_repair | 0.200000 | 31 | 0.0645 | 0.5022 |
| formal_10001 | random_full | vehicle_type_swap | regret2_insert_repair | 0.200000 | 35 | 0.0571 | 0.4982 |
| formal_10001 | random_full | vehicle_type_swap | greedy_insert_repair | 0.300000 | 35 | 0.0571 | 0.4799 |
| formal_10001 | random_full | random_customer_removal | regret3_insert_repair | 0.200000 | 36 | 0.0556 | 0.2778 |
| formal_10001 | random_full | whole_route_removal | regret2_insert_repair | 0.233333 | 38 | 0.0526 | 0.2745 |
| formal_10001 | random_full | route_segment_removal | greedy_insert_repair | 0.233333 | 39 | 0.0513 | 0.2608 |
| formal_10001 | random_full | route_segment_removal | greedy_insert_repair | 0.366667 | 39 | 0.0513 | 0.2564 |
| formal_10001 | random_full | whole_route_removal | greedy_insert_repair | 0.133333 | 40 | 0.0500 | 0.2500 |
| formal_10001 | random_full | random_customer_removal | regret2_insert_repair | 0.166667 | 41 | 0.0488 | 0.2439 |
| formal_10001 | random_full | vehicle_type_swap | regret3_insert_repair | 0.333333 | 46 | 0.0435 | 0.4267 |
| formal_10001 | random_full | whole_route_removal | regret2_insert_repair | 0.200000 | 23 | 0.0435 | 0.2174 |
| formal_10001 | random_full | shaw_related_removal | greedy_insert_repair | 0.333333 | 24 | 0.0417 | 0.2083 |
| formal_10001 | random_full | shaw_related_removal | regret3_insert_repair | 0.266667 | 24 | 0.0417 | 0.2083 |
| formal_10001 | random_full | whole_route_removal | regret3_insert_repair | 0.233333 | 25 | 0.0400 | 0.2287 |
| formal_10001 | random_full | shaw_related_removal | regret2_insert_repair | 0.100000 | 25 | 0.0400 | 0.2012 |
| formal_10001 | random_full | worst_customer_removal | regret2_insert_repair | 0.300000 | 27 | 0.0370 | 0.1852 |
| formal_10001 | random_full | route_segment_removal | greedy_insert_repair | 0.133333 | 29 | 0.0345 | 0.1838 |
| formal_10001 | random_full | random_customer_removal | regret3_insert_repair | 0.333333 | 29 | 0.0345 | 0.1724 |
| formal_10001 | random_full | worst_customer_removal | regret2_insert_repair | 0.266667 | 29 | 0.0345 | 0.1724 |
| formal_10001 | random_full | shaw_related_removal | regret3_insert_repair | 0.400000 | 31 | 0.0323 | 0.1671 |
| formal_10001 | random_full | random_customer_removal | regret3_insert_repair | 0.300000 | 31 | 0.0323 | 0.1613 |
| formal_10001 | random_full | shaw_related_removal | greedy_insert_repair | 0.300000 | 32 | 0.0312 | 0.1562 |
| formal_10001 | random_full | shaw_related_removal | regret3_insert_repair | 0.300000 | 32 | 0.0312 | 0.1562 |
| formal_10001 | random_full | vehicle_type_swap | greedy_insert_repair | 0.100000 | 33 | 0.0303 | 0.3525 |
| formal_10001 | random_full | route_segment_removal | regret2_insert_repair | 0.233333 | 33 | 0.0303 | 0.1529 |
| formal_10001 | random_full | route_segment_removal | regret2_insert_repair | 0.166667 | 33 | 0.0303 | 0.1518 |
| formal_10001 | random_full | worst_customer_removal | greedy_insert_repair | 0.366667 | 33 | 0.0303 | 0.1515 |
