# Stage 2 Dynamic Failure Decomposition

Status: `TRACE_LIMITED_EXISTING_PAYLOAD`
Rows: 84
Mean information cost pct: 44.70696096379163
Missing fields: active_customer_count, committed_customer_count, newly_revealed_customer_count, planned_customer_count, stage_charging_action_count, stage_ev_route_count, stage_route_count

## Answers

1. Existing Track23 payloads prove a large information-cost pool but do not expose enough route/depot/EV slack to honestly assign the loss to capacity lock-in, depot mismatch, early commitment, EV slack, or budget.
2. Track23 Track20 reserve/commit/preposition changed the online surface but did not reduce mean information cost by the 2pp gate.
3. Only actions that change active customer commitment, initial stage plan, or stage budget are eligible for Stage 3.
