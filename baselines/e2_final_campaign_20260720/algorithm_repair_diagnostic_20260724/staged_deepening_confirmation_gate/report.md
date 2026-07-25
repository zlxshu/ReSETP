# Staged deepening confirmation incident

Decision: `HALT_STAGED_DEEPENING_CONFIRMATION_EXECUTION`.

Five of six preregistered tasks completed and remain sealed. The remaining task, `cn-prd-200c-02-V2-LOCATIONS` seed 14, failed during stage-2 warm-start projection because more than 12 routes were assigned to PyVRP vehicle type 4. Static review found that `_project_initial_solution` ignored each route's CV/EV type and always selected the depot CV type. The failed panel is not rerun, the incomplete acceptance gate is not evaluated, and none of these rows is formal evidence.

Among the five completed tasks, 3 improved over protected stage 1, 0 strictly improved over the best current single view, and 3 met the trajectory gate. These partial counts cannot pass the confirmation.
