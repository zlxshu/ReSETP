# DR-ALNS-PPO Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an isolated, truthfully named Reijnen-style `DR-ALNS-PPO` lane where PPO controls destroy/repair operator choice, removal intensity, and SA temperature, then produce a 100k-step smoke result against random and strengthened ALNS baselines without touching the formal runner or manuscript.

**Architecture:** The PPO process lives under `solver/rl/` and uses its own virtual environment. It does not import `setp_solver` directly; it communicates with a long-lived JSONL worker that applies SETP ALNS operators and returns candidate solutions, scores, metrics, and evaluation counts. Formal-runner outputs remain read-only references; all new artifacts are written under `solver/reports/dr_alns_ppo/`.

**Tech Stack:** Python 3.11 or 3.12, `stable-baselines3==2.4.1`, `torch==2.5.1`, `gymnasium==1.0.0`, `numpy==1.26.4`, existing `setp_solver` evaluator/checker/charging repair through JSON protocol.

---

## C2 Survey Conclusions

- Existing truth sources: `solver/src/setp_solver/search/evaluation.py` already defines `EvalBudget`, `score_candidate()`, `score_reference()`, and `repair_delta_count`; use that accounting model.
- Existing ALNS path: `solver/src/setp_solver/search/alns_wouda.py` has destroy/repair functions and `run_alns_wouda()`, but its current package selector is not PPO-controlled.
- Existing candidate label risk: `solver/src/setp_solver/search/candidates.py` already has a legacy `DR-ALNS` adapter. Do not rename that into PPO. New outputs must use `DR-ALNS-PPO`.
- Formal boundary: do not edit `solver/src/setp_solver/search/formal_runner.py`, `solver/src/setp_solver/search/candidates.py`, or `docs/paper_submission_final/*` in this plan. If later integration is desired, it must be a separate reviewed plan.
- Operator-manual requirement: destroy removal count `q` is adaptive and must be `0.1N..0.4N`; fixed `q=1` is a failure. Repair must include greedy, regret-2, and regret-3 with EV-route calls to `repair_route_charging`.

## File Structure

- Create `solver/rl/requirements.txt`: pinned RL-only dependencies.
- Create `solver/rl/.gitignore`: keep `.venv/`, AppleDouble sidecars, and Python caches out of commits.
- Create `solver/rl/README.md`: setup, commands, artifact contract, and non-pollution rules.
- Create `solver/rl/dr_alns_ppo/__init__.py`: package marker and version string.
- Create `solver/rl/dr_alns_ppo/schemas.py`: dataclasses for actions, observations, worker requests/responses, result summaries.
- Create `solver/rl/dr_alns_ppo/solution_json.py`: JSON conversion for `Solution`, `Route`, and `ChargingAction` payloads.
- Create `solver/rl/dr_alns_ppo/action_space.py`: `MultiDiscrete([5, 3, 10, 100])` decoding to `D1..D5`, `R1..R3`, `q_ratio`, and temperature multiplier.
- Create `solver/rl/dr_alns_ppo/operator_manual.py`: D1-D5, R1-R3, SA acceptance, and RouletteWheel scoring implemented against `setp_solver` inside the worker.
- Create `solver/rl/dr_alns_ppo/worker.py`: long-lived JSONL worker; imports `setp_solver`, loads one bundle, applies one full destroy+repair+score per request.
- Create `solver/rl/dr_alns_ppo/worker_client.py`: RL-side subprocess client; exchanges JSONL only and reports worker failures with stderr tail.
- Create `solver/rl/dr_alns_ppo/env.py`: `SetpAlnsEnv(gymnasium.Env)` with normalized observation vector and one candidate evaluation per `step()`.
- Create `solver/rl/dr_alns_ppo/bundle_manifest.py`: training/held-out manifest builder and loader.
- Create `solver/rl/dr_alns_ppo/baselines.py`: random-action policy and strengthened ALNS-Wouda comparison runner.
- Create `solver/rl/dr_alns_ppo/train_ppo.py`: PPO training entrypoint for smoke and pilot runs.
- Create `solver/rl/dr_alns_ppo/evaluate_policy.py`: held-out evaluation for PPO, random, and ALNS-Wouda.
- Create `solver/rl/dr_alns_ppo/report_smoke.py`: writes `smoke_100k_summary.json`, `smoke_100k_summary.md`, and CSV comparisons.
- Create `solver/rl/tests/test_action_space.py`: action decoding tests.
- Create `solver/rl/tests/test_operator_manual.py`: removal-count, related-removal, regret, SA, and RouletteWheel tests.
- Create `solver/rl/tests/test_env_contract.py`: Gymnasium shape, evaluation accounting, and JSON-only client tests.
- Output only under `solver/reports/dr_alns_ppo/`: manifests, monitor CSVs, TensorBoard logs, model checkpoints, and smoke reports.

## Task 1: Isolated RL Environment

**Files:**
- Create: `solver/rl/requirements.txt`
- Create: `solver/rl/.gitignore`
- Create: `solver/rl/README.md`

- [x] **Step 1: Write the dependency pins**

Create `solver/rl/requirements.txt`:

```text
stable-baselines3==2.4.1
torch==2.5.1
gymnasium==1.0.0
numpy==1.26.4
```

- [x] **Step 2: Add RL-lane git hygiene**

Create `solver/rl/.gitignore`:

```text
.venv/
._*
.DS_Store
__pycache__/
*.pyc
```

- [x] **Step 3: Write setup instructions**

Create `solver/rl/README.md` with:

```markdown
# DR-ALNS-PPO Lane

This directory is isolated from the formal solver lane. The PPO process uses
the packages pinned in `requirements.txt`. It communicates with the SETP
solver through JSONL worker messages and writes artifacts only under
`solver/reports/dr_alns_ppo/`.

## Setup

```bash
cd /Volumes/移动硬盘（512G）/ReSETP
python3.11 -m venv solver/rl/.venv
solver/rl/.venv/bin/python -m pip install --upgrade pip
solver/rl/.venv/bin/pip install -r solver/rl/requirements.txt
```

If `python3.11` is unavailable, use Python 3.12. Do not use Python 3.13 for
this lane unless `torch==2.5.1` and `stable-baselines3==2.4.1` install cleanly.

## Non-Pollution Rule

Do not edit `solver/src/setp_solver/search/formal_runner.py`,
`solver/src/setp_solver/search/candidates.py`, or `docs/paper_submission_final/*`
for this lane. Smoke and pilot outputs belong in `solver/reports/dr_alns_ppo/`.
```

- [x] **Step 4: Verify dependency install**

Run:

```bash
cd /Volumes/移动硬盘（512G）/ReSETP
solver/rl/.venv/bin/python - <<'PY'
import gymnasium, numpy, stable_baselines3, torch
print("gymnasium", gymnasium.__version__)
print("numpy", numpy.__version__)
print("sb3", stable_baselines3.__version__)
print("torch", torch.__version__)
PY
```

Expected: versions are `1.0.0`, `1.26.4`, `2.4.1`, and `2.5.1`.

## Task 2: JSON Schemas and Action Decoding

**Files:**
- Create: `solver/rl/dr_alns_ppo/__init__.py`
- Create: `solver/rl/dr_alns_ppo/schemas.py`
- Create: `solver/rl/dr_alns_ppo/action_space.py`
- Create: `solver/rl/tests/test_action_space.py`

- [x] **Step 1: Add package marker**

Create `solver/rl/dr_alns_ppo/__init__.py`:

```python
"""Isolated DR-ALNS-PPO lane for SETP experiments."""

__version__ = "0.1.0"
```

- [x] **Step 2: Define schemas**

Create `solver/rl/dr_alns_ppo/schemas.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DecodedAction:
    destroy_id: str
    repair_id: str
    q_ratio: float
    temperature: float
    raw: tuple[int, int, int, int]


@dataclass(frozen=True)
class WorkerRequest:
    request_id: int
    op: str
    action: dict[str, Any]
    current_solution: dict[str, Any] | None = None


@dataclass(frozen=True)
class CandidateResponse:
    request_id: int
    ok: bool
    accepted: bool
    improved_current: bool
    improved_best: bool
    actual_evals: int
    current_obj: float
    best_obj: float
    candidate_obj: float
    violation_count: int
    metrics: dict[str, float] = field(default_factory=dict)
    solution: dict[str, Any] = field(default_factory=dict)
    trace: dict[str, Any] = field(default_factory=dict)
    error: str = ""
```

- [x] **Step 3: Decode PPO action**

Create `solver/rl/dr_alns_ppo/action_space.py`:

```python
from __future__ import annotations

from .schemas import DecodedAction

DESTROY_IDS = ("D1", "D2", "D3", "D4", "D5")
REPAIR_IDS = ("R1", "R2", "R3")


def decode_action(raw: list[int] | tuple[int, int, int, int], *, base_temperature: float) -> DecodedAction:
    if len(raw) != 4:
        raise ValueError(f"Expected 4 action components, got {len(raw)}")
    d_idx, r_idx, q_idx, t_idx = [int(value) for value in raw]
    if not 0 <= d_idx < len(DESTROY_IDS):
        raise ValueError(f"destroy index out of range: {d_idx}")
    if not 0 <= r_idx < len(REPAIR_IDS):
        raise ValueError(f"repair index out of range: {r_idx}")
    if not 0 <= q_idx < 10:
        raise ValueError(f"q index out of range: {q_idx}")
    if not 0 <= t_idx < 100:
        raise ValueError(f"temperature index out of range: {t_idx}")

    q_ratio = 0.10 + (0.30 * q_idx / 9.0)
    temperature = float(base_temperature) * (0.10 + 1.90 * t_idx / 99.0)
    return DecodedAction(
        destroy_id=DESTROY_IDS[d_idx],
        repair_id=REPAIR_IDS[r_idx],
        q_ratio=float(q_ratio),
        temperature=float(temperature),
        raw=(d_idx, r_idx, q_idx, t_idx),
    )
```

- [x] **Step 4: Test action decoding**

Create `solver/rl/tests/test_action_space.py`:

```python
from dr_alns_ppo.action_space import decode_action


def test_decode_action_maps_multi_discrete_components() -> None:
    action = decode_action([4, 2, 9, 99], base_temperature=100.0)

    assert action.destroy_id == "D5"
    assert action.repair_id == "R3"
    assert abs(action.q_ratio - 0.40) < 1e-12
    assert abs(action.temperature - 200.0) < 1e-12


def test_decode_action_has_lower_q_bound_not_fixed_one_customer() -> None:
    action = decode_action([0, 0, 0, 0], base_temperature=100.0)

    assert action.destroy_id == "D1"
    assert action.repair_id == "R1"
    assert abs(action.q_ratio - 0.10) < 1e-12
    assert action.temperature == 10.0
```

- [x] **Step 5: Run tests**

Run:

```bash
cd /Volumes/移动硬盘（512G）/ReSETP
PYTHONPATH=solver/rl solver/rl/.venv/bin/python -m pytest solver/rl/tests/test_action_space.py -q
```

Expected: `2 passed`.

## Task 3: Solution JSON Bridge

**Files:**
- Create: `solver/rl/dr_alns_ppo/solution_json.py`
- Create: `solver/rl/tests/test_solution_json.py`

- [x] **Step 1: Implement JSON conversion**

Create `solver/rl/dr_alns_ppo/solution_json.py`:

```python
from __future__ import annotations

from dataclasses import asdict
from typing import Any


def solution_to_json(solution: Any) -> dict[str, Any]:
    return {
        "routes": [asdict(route) for route in solution.routes],
        "charging_actions": [asdict(action) for action in solution.charging_actions],
        "cross_site_services": [asdict(item) for item in getattr(solution, "cross_site_services", [])],
    }


def solution_from_json(payload: dict[str, Any]) -> Any:
    from setp_solver.solution import ChargingAction, CrossSiteService, Route, Solution

    return Solution(
        routes=[Route(**row) for row in payload.get("routes", [])],
        charging_actions=[ChargingAction(**row) for row in payload.get("charging_actions", [])],
        cross_site_services=[CrossSiteService(**row) for row in payload.get("cross_site_services", [])],
    )
```

- [x] **Step 2: Test round trip through existing solver dataclasses**

Create `solver/rl/tests/test_solution_json.py`:

```python
from dr_alns_ppo.solution_json import solution_from_json, solution_to_json
from setp_solver.solution import ChargingAction, Route, Solution


def test_solution_json_round_trip_preserves_routes_and_charging() -> None:
    solution = Solution(
        routes=[Route("EV1", "ev", "D0", ["D0", "F1", "C1", "D0"])],
        charging_actions=[ChargingAction("EV1", "F1", 12.5, 15.0, 1800.0)],
    )

    restored = solution_from_json(solution_to_json(solution))

    assert restored == solution
```

- [x] **Step 3: Run bridge test**

Run:

```bash
cd /Volumes/移动硬盘（512G）/ReSETP
PYTHONPATH=solver/rl:solver/src solver/rl/.venv/bin/python -m pytest solver/rl/tests/test_solution_json.py -q
```

Expected: `1 passed`.

## Task 4: Strong ALNS Operator Manual

**Files:**
- Create: `solver/rl/dr_alns_ppo/operator_manual.py`
- Create: `solver/rl/tests/test_operator_manual.py`

- [x] **Step 1: Implement destroy/repair/SA/RouletteWheel**

Create `solver/rl/dr_alns_ppo/operator_manual.py` with these public functions:

```python
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np


@dataclass
class RouletteStats:
    weights: dict[str, float]
    scores: dict[str, float]
    uses: dict[str, int]
    lambda_decay: float = 0.8

    @classmethod
    def create(cls, operator_ids: list[str]) -> "RouletteStats":
        return cls(
            weights={op: 1.0 for op in operator_ids},
            scores={op: 0.0 for op in operator_ids},
            uses={op: 0 for op in operator_ids},
        )

    def record(self, operator_id: str, reward_code: str) -> None:
        sigma = {"global_best": 6.0, "current_improved": 3.0, "accepted_worse": 1.0}.get(reward_code, 0.0)
        self.scores[operator_id] = self.scores.get(operator_id, 0.0) + sigma
        self.uses[operator_id] = self.uses.get(operator_id, 0) + 1

    def update_segment(self) -> None:
        for op, weight in list(self.weights.items()):
            uses = self.uses.get(op, 0)
            if uses > 0:
                rate = self.scores.get(op, 0.0) / uses
                self.weights[op] = self.lambda_decay * weight + (1.0 - self.lambda_decay) * rate
            self.scores[op] = 0.0
            self.uses[op] = 0


def removal_count(customer_count: int, q_ratio: float) -> int:
    if customer_count <= 0:
        return 0
    clipped = min(0.40, max(0.10, float(q_ratio)))
    return max(1, min(customer_count, int(math.ceil(clipped * customer_count))))


def sa_accept(delta: float, temperature: float, random_value: float) -> bool:
    if delta <= 0.0:
        return True
    if temperature <= 0.0:
        return False
    return float(random_value) < math.exp(-float(delta) / float(temperature))


def relatedness(left: Any, right: Any, same_route: bool, weights: tuple[float, float, float, float]) -> float:
    w_dist, w_time, w_demand, w_route = weights
    dx = float(left.x) - float(right.x)
    dy = float(left.y) - float(right.y)
    distance = math.hypot(dx, dy)
    time_gap = abs(float(left.ready_time) - float(right.ready_time)) + abs(float(left.due_time) - float(right.due_time))
    demand_gap = abs(float(left.demand) - float(right.demand))
    route_bonus = 0.0 if same_route else 1.0
    return w_dist * distance + w_time * time_gap + w_demand * demand_gap + w_route * route_bonus
```

The same file must also implement worker-side functions:

```python
def apply_destroy(solution, context, rng, destroy_id: str, q_ratio: float):
    """Return `(partial_solution, removed_customer_ids, trace)` for D1-D5."""


def apply_repair(partial_solution, removed_customer_ids, context, repair_id: str):
    """Return `(candidate_solution, trace)` for R1-R3 using incremental scoring."""
```

Implementation requirements for `apply_destroy`:

- D1 random removal: sample `q` customers without replacement.
- D2 worst removal: rank customers by `score_reference(full) - score_reference(without_customer)`, descending.
- D3 Shaw/related removal: choose a seed customer, compute `w1*distance + w2*time-window-gap + w3*demand-gap + w4*same-route-penalty`, remove seed plus most related customers.
- D4 route removal: remove all customers from the shortest route among the top half by route objective contribution, or all customers from the most expensive route when the top half is empty.
- D5 segment removal: remove a contiguous segment from one customer-bearing route, with length capped by `q`.

Implementation requirements for `apply_repair`:

- R1 greedy/best insertion: repeatedly choose the globally cheapest feasible insertion.
- R2 regret-2 insertion: choose the customer with largest `(second_best - best)` before insertion.
- R3 regret-3 insertion: choose the customer with largest `(third_best - best)`; if only two options exist, use regret-2; if only one exists, use `0`.
- EV route insertion must call `repair_route_charging`; infeasible insertion candidates must be discarded.
- Incremental scoring must call `record_repair_delta()` for insertion-option ranking and must not increment `actual_evals`.

- [x] **Step 2: Add operator tests**

Create `solver/rl/tests/test_operator_manual.py`:

```python
from dr_alns_ppo.operator_manual import RouletteStats, removal_count, sa_accept


def test_removal_count_uses_adaptive_fraction_bounds() -> None:
    assert removal_count(25, 0.10) == 3
    assert removal_count(25, 0.40) == 10
    assert removal_count(25, 0.01) == 3
    assert removal_count(25, 0.90) == 10


def test_sa_accepts_better_and_probabilistically_accepts_worse() -> None:
    assert sa_accept(-1.0, 0.0, 0.99)
    assert not sa_accept(10.0, 0.0, 0.0)
    assert sa_accept(10.0, 100.0, 0.05)
    assert not sa_accept(10.0, 100.0, 0.99)


def test_roulette_weight_segment_update_uses_scores_per_use() -> None:
    stats = RouletteStats.create(["D1", "D2"])

    stats.record("D1", "global_best")
    stats.record("D1", "current_improved")
    stats.record("D2", "accepted_worse")
    stats.update_segment()

    assert stats.weights["D1"] > stats.weights["D2"]
    assert stats.scores == {"D1": 0.0, "D2": 0.0}
    assert stats.uses == {"D1": 0, "D2": 0}
```

- [x] **Step 3: Run manual tests**

Run:

```bash
cd /Volumes/移动硬盘（512G）/ReSETP
PYTHONPATH=solver/rl:solver/src solver/rl/.venv/bin/python -m pytest solver/rl/tests/test_operator_manual.py -q
```

Expected: at least the three pure tests pass. Add integration tests for `apply_destroy/apply_repair` before marking this task complete:

```bash
PYTHONPATH=solver/rl:solver/src solver/rl/.venv/bin/python -m pytest solver/rl/tests/test_operator_manual.py -q -k "destroy or repair"
```

Expected integration assertions:

- D1, D2, D3, and D5 remove at least `ceil(0.1N)` customers on `verify_20251113`.
- R2 and R3 produce a feasible solution with `repair_delta_count > 0`.
- EV insertion candidates touching EV routes call `repair_route_charging`.

## Task 5: JSONL Worker and Client

**Files:**
- Create: `solver/rl/dr_alns_ppo/worker.py`
- Create: `solver/rl/dr_alns_ppo/worker_client.py`
- Create: `solver/rl/tests/test_worker_contract.py`

- [x] **Step 1: Implement worker**

`worker.py` must:

- parse CLI args `--bundle-dir`, `--seed`, `--carbon-quota-kg`, `--carbon-weight`, `--max-evals`;
- load `load_search_bundle(bundle_dir)`;
- build the initial solution with `build_initial_solution(...)`;
- create `EvaluationContext(..., budget=EvalBudget(limit=max_evals + max(1000, max_evals // 10), target=max_evals))`;
- accept JSONL messages on stdin:
  - `{"op": "reset"}`;
  - `{"op": "step", "action": {"destroy_id": "D1", "repair_id": "R2", "q_ratio": 0.2, "temperature": 100.0}}`;
  - `{"op": "close"}`;
- for each `step`, perform one full destroy+repair candidate scoring with `score_candidate()`;
- apply SA acceptance with selected temperature;
- update current/best solution and RouletteWheel stats;
- emit one JSON line containing `actual_evals`, `candidate_scores`, `repair_delta_count`, `accepted`, `improved_current`, `improved_best`, `metrics`, `violation_count`, `solution`, and `trace`.

- [x] **Step 2: Implement client**

`worker_client.py` must start the worker with:

```python
cmd = [
    sys.executable,
    "-m",
    "dr_alns_ppo.worker",
    "--bundle-dir",
    str(bundle_dir),
    "--seed",
    str(seed),
    "--max-evals",
    str(max_evals),
]
```

The client must:

- write one JSON object per line;
- read exactly one response per request;
- raise `RuntimeError` with the request payload and stderr tail if the worker dies;
- expose `reset()`, `step(decoded_action)`, and `close()`.

- [x] **Step 3: Test one worker step**

Create `solver/rl/tests/test_worker_contract.py`:

```python
from dr_alns_ppo.action_space import decode_action
from dr_alns_ppo.worker_client import WorkerClient

FIXTURE_DIR = "models/data_bundle/generated_instances/verify_20251113"


def test_worker_step_counts_one_candidate_eval() -> None:
    client = WorkerClient(FIXTURE_DIR, seed=1, max_evals=20)
    try:
        reset = client.reset()
        response = client.step(decode_action([0, 1, 3, 50], base_temperature=100.0))
    finally:
        client.close()

    assert reset["actual_evals"] == 0
    assert response["actual_evals"] == 1
    assert response["candidate_scores"] == 1
    assert response["repair_delta_count"] > 0
    assert response["trace"]["destroy_id"] == "D1"
    assert response["trace"]["repair_id"] == "R2"
```

- [x] **Step 4: Run worker contract test**

Run:

```bash
cd /Volumes/移动硬盘（512G）/ReSETP
PYTHONPATH=solver/rl:solver/src solver/rl/.venv/bin/python -m pytest solver/rl/tests/test_worker_contract.py -q
```

Expected: `1 passed`.

## Task 6: SetpAlnsEnv

**Files:**
- Create: `solver/rl/dr_alns_ppo/env.py`
- Create: `solver/rl/tests/test_env_contract.py`

- [x] **Step 1: Implement Gymnasium env**

`env.py` must define `SetpAlnsEnv(gymnasium.Env)`:

```python
import gymnasium as gym
import numpy as np
from gymnasium import spaces

from .action_space import decode_action
from .worker_client import WorkerClient


class SetpAlnsEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, bundle_dir: str, seed: int = 1, eval_budget: int = 16000, base_temperature: float = 100.0):
        super().__init__()
        self.bundle_dir = bundle_dir
        self.seed_value = int(seed)
        self.eval_budget = int(eval_budget)
        self.base_temperature = float(base_temperature)
        self.action_space = spaces.MultiDiscrete([5, 3, 10, 100])
        self.observation_space = spaces.Box(low=-10.0, high=10.0, shape=(11,), dtype=np.float32)
        self.client = WorkerClient(bundle_dir, seed=self.seed_value, max_evals=self.eval_budget)
        self.last_response = None

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        if seed is not None and int(seed) != self.seed_value:
            self.client.close()
            self.seed_value = int(seed)
            self.client = WorkerClient(self.bundle_dir, seed=self.seed_value, max_evals=self.eval_budget)
        self.last_response = self.client.reset()
        return self._obs(self.last_response), {"actual_evals": 0}

    def step(self, action):
        decoded = decode_action(action, base_temperature=self.base_temperature)
        response = self.client.step(decoded)
        self.last_response = response
        reward = self._reward(response)
        terminated = bool(response["actual_evals"] >= self.eval_budget)
        truncated = False
        return self._obs(response), reward, terminated, truncated, response

    def close(self):
        self.client.close()

    def _reward(self, response):
        if response.get("improved_best"):
            return 5.0
        if response.get("improved_current"):
            return max(0.01, min(1.0, float(response.get("relative_improvement", 0.0)) * 100.0))
        return 0.0
```

Observation vector order:

1. current/best gap;
2. last-step improvement;
3. current-is-best flag;
4. stagnation steps normalized by budget;
5. budget progress;
6. current temperature normalized by base temperature;
7. EV/CV route ratio;
8. charging action count normalized by route count;
9. carbon cost share;
10. quota slack `(quota - E_total) / max(E_total, 1)`;
11. constraint violation count clipped to 10 and divided by 10.

- [x] **Step 2: Test env contract**

Create `solver/rl/tests/test_env_contract.py`:

```python
from dr_alns_ppo.env import SetpAlnsEnv

FIXTURE_DIR = "models/data_bundle/generated_instances/verify_20251113"


def test_env_reset_and_step_return_expected_shapes_and_eval_count() -> None:
    env = SetpAlnsEnv(FIXTURE_DIR, seed=1, eval_budget=5, base_temperature=100.0)
    try:
        obs, info = env.reset()
        next_obs, reward, terminated, truncated, step_info = env.step([0, 1, 3, 50])
    finally:
        env.close()

    assert obs.shape == (11,)
    assert next_obs.shape == (11,)
    assert info["actual_evals"] == 0
    assert step_info["actual_evals"] == 1
    assert reward >= 0.0
    assert terminated is False
    assert truncated is False
```

- [x] **Step 3: Run env test**

Run:

```bash
cd /Volumes/移动硬盘（512G）/ReSETP
PYTHONPATH=solver/rl:solver/src solver/rl/.venv/bin/python -m pytest solver/rl/tests/test_env_contract.py -q
```

Expected: `1 passed`.

## Task 7: Training and Held-Out Bundle Manifest

**Files:**
- Create: `solver/rl/dr_alns_ppo/bundle_manifest.py`
- Output: `solver/reports/dr_alns_ppo/training_bundle_manifest.json`

- [x] **Step 1: Implement manifest builder**

`bundle_manifest.py` must write:

```json
{
  "schema_version": "dr-alns-ppo-bundle-manifest.v1",
  "train": [
    "models/data_bundle/generated_instances/verify_20251113",
    "models/data_bundle/generated_instances/verify_20251113_evheavy",
    "models/data_bundle/generated_instances/E-UK100_01__u0_seed1_24h_20251113",
    "models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113"
  ],
  "held_out": [
    "models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113",
    "models/data_bundle/generated_instances/E-UK24h-三班-01"
  ],
  "excluded_from_training_reason": {
    "100-01/L-main only": "single-main-case training would overfit and is not evidence of general DRL control"
  }
}
```

- [x] **Step 2: Validate every bundle exists**

Run:

```bash
cd /Volumes/移动硬盘（512G）/ReSETP
for d in \
  models/data_bundle/generated_instances/verify_20251113 \
  models/data_bundle/generated_instances/verify_20251113_evheavy \
  models/data_bundle/generated_instances/E-UK100_01__u0_seed1_24h_20251113 \
  models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113 \
  models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113 \
  models/data_bundle/generated_instances/E-UK24h-三班-01
do
  test -f "$d/instance.json" && test -f "$d/distance_matrix.npy" && test -f "$d/carbon_profile.csv" || exit 2
done
echo "DR_ALNS_PPO_BUNDLES_OK"
```

Expected: `DR_ALNS_PPO_BUNDLES_OK`.

## Task 8: PPO Training Script

**Files:**
- Create: `solver/rl/dr_alns_ppo/train_ppo.py`
- Output: `solver/reports/dr_alns_ppo/smoke_100k/`

- [x] **Step 1: Implement training CLI**

`train_ppo.py` must accept:

```bash
--manifest solver/reports/dr_alns_ppo/training_bundle_manifest.json
--timesteps 100000
--eval-budget 16000
--seed 1
--output-dir solver/reports/dr_alns_ppo/smoke_100k
```

It must:

- construct training envs from `manifest["train"]`;
- use PPO with `MultiInputPolicy` only if observations become dicts; otherwise use `MlpPolicy`;
- save `model.zip`, `monitor.csv`, `training_config.json`, and `env_eval_counts.csv`;
- write `actual_evals` per episode and never infer it from neural inference steps.

- [ ] **Step 2: Smoke train**

Run:

```bash
cd /Volumes/移动硬盘（512G）/ReSETP
PYTHONPATH=solver/rl:solver/src solver/rl/.venv/bin/python -m dr_alns_ppo.train_ppo \
  --manifest solver/reports/dr_alns_ppo/training_bundle_manifest.json \
  --timesteps 100000 \
  --eval-budget 16000 \
  --seed 1 \
  --output-dir solver/reports/dr_alns_ppo/smoke_100k
```

Expected files:

- `solver/reports/dr_alns_ppo/smoke_100k/model.zip`
- `solver/reports/dr_alns_ppo/smoke_100k/training_config.json`
- `solver/reports/dr_alns_ppo/smoke_100k/env_eval_counts.csv`

## Task 9: Random and Strengthened ALNS Baselines

**Files:**
- Create: `solver/rl/dr_alns_ppo/baselines.py`
- Create: `solver/rl/dr_alns_ppo/evaluate_policy.py`
- Output: `solver/reports/dr_alns_ppo/smoke_100k/comparison.csv`

- [x] **Step 1: Implement random baseline**

Random baseline must use `env.action_space.sample()` and the same `eval_budget=16000`, same held-out bundles, and same seeds as PPO evaluation. It must report:

- `algorithm=random_action`
- `bundle`
- `seed`
- `best_obj`
- `actual_evals`
- `candidate_scores`
- `repair_delta_count`
- `feasible`
- `solution_signature_hash`

- [x] **Step 2: Implement strengthened ALNS-Wouda comparison**

Strengthened ALNS comparison must call existing `run_alns_wouda()` through a separate JSON worker command or a subprocess with `PYTHONPATH=solver/src`, not by importing `setp_solver` in the PPO process. It must report the same columns as random and PPO, plus `operator_counts`.

- [ ] **Step 3: Evaluate PPO on held-out**

Run:

```bash
cd /Volumes/移动硬盘（512G）/ReSETP
PYTHONPATH=solver/rl:solver/src solver/rl/.venv/bin/python -m dr_alns_ppo.evaluate_policy \
  --manifest solver/reports/dr_alns_ppo/training_bundle_manifest.json \
  --model solver/reports/dr_alns_ppo/smoke_100k/model.zip \
  --eval-budget 16000 \
  --seeds 1,2,3 \
  --output-dir solver/reports/dr_alns_ppo/smoke_100k
```

Expected: `comparison.csv` includes `ppo`, `random_action`, and `alns_wouda_strengthened` rows for every held-out bundle and seed.

## Task 10: Smoke Gate and Escape Rules

**Files:**
- Create: `solver/rl/dr_alns_ppo/report_smoke.py`
- Output: `solver/reports/dr_alns_ppo/smoke_100k/smoke_100k_summary.json`
- Output: `solver/reports/dr_alns_ppo/smoke_100k/smoke_100k_summary.md`

- [x] **Step 1: Implement smoke summary**

`report_smoke.py` must compute:

- median held-out best objective by algorithm;
- paired PPO-vs-random gap by bundle and seed;
- paired PPO-vs-ALNS-Wouda gap by bundle and seed;
- `actual_evals_min`, `actual_evals_max`, and any under-budget runs;
- feasibility rate;
- `q_ratio` distribution and D/R operator usage.

Gate logic:

```text
PASS_RANDOM if PPO median held-out best_obj < random_action median held-out best_obj
HALT_RANDOM otherwise

PASS_ALNS_PILOT only if PPO median held-out best_obj < alns_wouda_strengthened median held-out best_obj
FUTURE_WORK otherwise
```

- [x] **Step 2: Write the mandatory interpretation text**

`smoke_100k_summary.md` must include exactly these lines with computed values filled in:

```markdown
# DR-ALNS-PPO 100k Smoke

This smoke does not modify the formal runner or manuscript.

Each `env.step()` performs one full candidate solution scoring. The reported
`actual_evals` values come from the shared evaluator budget counter, not from
PPO inference calls.

Gate versus random: `PASS_RANDOM` or `HALT_RANDOM`.
Gate versus strengthened ALNS-Wouda: `PASS_ALNS_PILOT`, `FUTURE_WORK`, or `NOT_RUN`.

If the 100k smoke does not beat random on held-out bundles, this lane must not
be called successful DRL control. If the 1-2M pilot does not beat strengthened
ALNS-Wouda on held-out bundles, the result is future work rather than main T3
evidence.
```

- [ ] **Step 3: Generate smoke report**

Run:

```bash
cd /Volumes/移动硬盘（512G）/ReSETP
PYTHONPATH=solver/rl:solver/src solver/rl/.venv/bin/python -m dr_alns_ppo.report_smoke \
  --comparison solver/reports/dr_alns_ppo/smoke_100k/comparison.csv \
  --output-dir solver/reports/dr_alns_ppo/smoke_100k
```

Expected:

- `smoke_100k_summary.json` has `gate_vs_random`.
- `smoke_100k_summary.md` explicitly says whether PPO beat random.

## Task 11: Verification and Non-Pollution Audit

**Files:**
- No source files created.

- [ ] **Step 1: Run RL test suite**

Run:

```bash
cd /Volumes/移动硬盘（512G）/ReSETP
PYTHONPATH=solver/rl:solver/src solver/rl/.venv/bin/python -m pytest solver/rl/tests -q
```

Expected: all `solver/rl/tests` pass.

- [ ] **Step 2: Prove formal runner untouched**

Run:

```bash
cd /Volumes/移动硬盘（512G）/ReSETP
git diff -- solver/src/setp_solver/search/formal_runner.py solver/src/setp_solver/search/candidates.py docs/paper_submission_final
```

Expected: no output.

- [ ] **Step 3: Prove artifacts are in allowed directories**

Run:

```bash
cd /Volumes/移动硬盘（512G）/ReSETP
git status --short
```

Expected new or modified paths are limited to:

- `docs/superpowers/plans/2026-06-15-dr-alns-ppo.md`
- `solver/rl/`
- `solver/reports/dr_alns_ppo/`

## Task 12: 1-2M Pilot Gate

**Files:**
- Output: `solver/reports/dr_alns_ppo/pilot_1m/`

- [ ] **Step 1: Run pilot only after 100k beats random**

Run:

```bash
cd /Volumes/移动硬盘（512G）/ReSETP
PYTHONPATH=solver/rl:solver/src solver/rl/.venv/bin/python -m dr_alns_ppo.train_ppo \
  --manifest solver/reports/dr_alns_ppo/training_bundle_manifest.json \
  --timesteps 1000000 \
  --eval-budget 16000 \
  --seed 1 \
  --output-dir solver/reports/dr_alns_ppo/pilot_1m
```

Expected: pilot artifacts mirror the smoke directory.

- [ ] **Step 2: Evaluate pilot**

Run:

```bash
cd /Volumes/移动硬盘（512G）/ReSETP
PYTHONPATH=solver/rl:solver/src solver/rl/.venv/bin/python -m dr_alns_ppo.evaluate_policy \
  --manifest solver/reports/dr_alns_ppo/training_bundle_manifest.json \
  --model solver/reports/dr_alns_ppo/pilot_1m/model.zip \
  --eval-budget 16000 \
  --seeds 1,2,3,4,5 \
  --output-dir solver/reports/dr_alns_ppo/pilot_1m
```

Expected: held-out comparison includes PPO, random, and strengthened ALNS-Wouda.

- [ ] **Step 3: Apply escape trigger**

If PPO fails to beat strengthened ALNS-Wouda on held-out bundles with matched `actual_evals`, record:

```text
Decision: FUTURE_WORK
Reason: PPO did not beat strengthened ALNS-Wouda under held-out matched actual_evals.
Paper action: Do not include this lane in main T3.
```

If PPO beats strengthened ALNS-Wouda, record:

```text
Decision: PILOT_PASS
Reason: PPO beat strengthened ALNS-Wouda under held-out matched actual_evals.
Paper action: Eligible for a separate manuscript-integration plan, not automatic T3 insertion.
```

## Self-Review

- Spec coverage: isolation, `SetpAlnsEnv`, D1-D5, R1-R3, adaptive `q`, SA acceptance, RouletteWheel updates, training bundles, held-out evaluation, `actual_evals`, 100k smoke, 1-2M pilot, and escape triggers are covered.
- Placeholder scan: no implementation step relies on `TBD` or unspecified acceptance criteria. The only deliberately deferred path is manuscript/formal-runner integration, which is outside the user's requested scope.
- Type consistency: `DecodedAction`, `CandidateResponse`, worker JSON messages, and env `info` keys are consistently named across tasks.
