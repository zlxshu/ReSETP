# ReSETP DR-ALNS Project Rhythm Manual

Date: 2026-06-26
Repo: `D:\ReSETP`
Branch context: `dr-x86`

This manual records the operating rhythm for the ReSETP algorithm work so the project does not drift back into long, expensive, low-evidence DR training loops. It is a coordination document, not a result report.

## 1. Current Project Truth

The paper goal is still a strong, reproducible algorithm story for the ReSETP green VRP model: multi-depot, mixed CV/EV fleet, time-varying carbon intensity, nonlinear charging, time windows, profit fairness, and rolling dynamic demand. The algorithm side must be credible against literature baselines, not merely better than weak SA.

The current stable paper backbone is the ALNS winner kernel plus the mechanism contributions. DR-ALNS remains desirable, but it is no longer allowed to consume unlimited time as the paper's only path. Pilot08, Pilot09, and Pilot10 changed the evidence picture:

- Pilot08 showed the curriculum PPO training pipeline can run healthily, but learned operator selection only reached roughly AlphaUCB level and received a WEAK verdict.
- Pilot09 showed operator selection has little or no headroom, while static search-parameter retuning has real headroom.
- Pilot10 showed dynamic `block_meta` training did not beat the best static meta setting. The remaining gain is an AlphaUCB retune, not a demonstrated learning contribution.

The working conclusion is: same-shape PPO over the current block interface is stopped. Any further DR work must first fix the policy interface: what the learner sees, what it controls, and how reward is connected to route, EV, charging, and acceptance decisions.

## 2. Non-Negotiable Boundaries

No task may modify the semantics of `cost.py`, `check.py`, `search/evaluation.py`, protected feasibility logic, or winner-operator meaning without an explicit user instruction naming that file and reason.

No DR result may compare x86 absolute objectives against M1 absolute objectives. x86 DR results are same-machine relative percentages only.

No future DR claim may use default AlphaUCB as the only serious opponent. The honest opponent is the best known static or tuned AlphaUCB/meta configuration under the same worker, bundle, seed, budget, and runtime rules.

No long training may start until a cheap diagnostic has shown that the proposed new state/action interface can actually expose the missing decision signal. Training is a consequence of a passed diagnostic, not a way to discover the plan.

No agent should invent algorithms from taste. When a design question appears, first read project records, repository reference code, Zotero papers, downloaded source code, and web sources if needed. Engineering experiments verify evidence; they do not replace evidence.

No report may label a negative or narrow result as success. `HALT`, `WEAK`, and `WEAK_RETUNE` are acceptable project outcomes when they prevent wasted training.

## 3. Workstream Priorities

The project has four workstreams. They are not equal.

First priority is the paper backbone: formal winner-kernel numbers, mechanism results, figure/table consistency, and literature baseline credibility. This work protects the submission even if DR remains future work.

Second priority is DR interface redesign. This is the only remaining DR path with a plausible learning contribution. It must be evidence-first and must compare against tuned/static baselines.

Third priority is engineering retune value. Static meta retuning can be useful as a stronger ALNS configuration, but it must be labeled as parameter tuning, not neural learning.

Fourth priority is archival and handoff hygiene. Every major decision must be recorded in `HANDOFF.md`, `docs/handoff/memory/`, or a focused handoff document before the next expensive run.

## 4. The Required Loop

Every substantial algorithm step follows this loop:

1. Read the current facts. Start from `HANDOFF.md`, `docs/handoff/memory/`, current pilot reports, and the relevant code files. Do not rely on memory alone when the files are cheap to inspect.
2. Compare against literature and reference implementations. Identify which problem the paper or source code is solving, what state it exposes, what action it lets the learner control, and what reward or search loop it uses.
3. Diagnose the mismatch. Name the specific missing state, missing action, wrong baseline, weak reward, cost wall, or runtime bottleneck.
4. Propose the smallest diagnostic. Prefer static audit, trace replay, cheap A/B, or one-bundle short run before any long training.
5. Execute only the approved diagnostic. Keep artifacts local and ignored unless the user asks to curate and commit.
6. Test the tooling. Unit tests must cover schema, gates, signs, path handling, and failure modes. Experiment rows must pass worker, NumPy, feasibility, finite objective, and budget/runtime gates.
7. Accept or stop. A passed diagnostic opens the next plan. A failed diagnostic writes a halt report and stops the branch instead of continuing by inertia.
8. Record the decision. Update the handoff layer with the reason, the evidence, and the next allowed action.

## 5. Communication Rhythm

For short tasks, report only the current action and the result. For stable long tasks, use low-frequency heartbeats. Increase update frequency only when something fails, memory approaches danger, or a decision gate is reached.

Status updates should use plain Chinese and answer: what is already done, what is running, what comes next, how long it may take, and whether it deviates from the plan. Avoid internal jargon unless it directly changes a decision.

When explaining DR failures, separate these ideas clearly: the model trained successfully, the target was not achieved, and the evidence says why. A healthy training run can still be an algorithmic failure.

## 6. DR Stop Lines

The current block PPO lane is stopped under this interface. Do not rerun it with more seeds, more timesteps, more checkpoints, or different selection windows unless a new interface diagnostic passes first.

The `block_meta` lane is stopped as a learning claim because Pilot10 did not beat best static meta. It can only return as an engineering retune comparison or as part of a redesigned state/action interface.

Any future DR policy must beat the best static/tuned meta baseline on train and held-out bundles by positive mean relative percentage and wins, not merely beat default AlphaUCB or SA.

If a proposed action head cannot affect the target cost component through the solver interface, the plan halts before training.

If the proposed observation cannot distinguish the route, charging, vehicle, or customer condition that the action is supposed to solve, the plan halts before training.

## 7. Next Correct Step: Pilot11 Interface Audit

The next DR step is not training. The next step is Pilot11 interface audit.

Pilot11 should answer three questions:

1. What information do the papers and reference code give their learner that ReSETP's current 19-feature block observation does not give?
2. What decisions do the papers and reference code let their learner control that ReSETP's current action heads do not control?
3. Which smallest new state/action addition is testable without rewriting solver semantics?

The likely missing information categories are route sequence, customer demand/time-window/service features, vehicle type and energy state, charging-station context, edge or insertion features, recent operator outcome by context, and acceptance/search-temperature context.

The likely missing action categories are acceptance or stopping control, destruction severity, charging/energy strategy, repair insertion choice, and learned repair/construction. Acceptance control is the safest first candidate because it matches Reijnen-style DR-ALNS and PPO-ALNS references while touching less EV repair internals. Charging-strategy control is more domain-aligned but must be audited carefully before implementation.

## 8. Pilot11 Gate Design

Pilot11 passes only if it produces a concrete interface proposal with all of the following:

- A list of currently missing state fields, each mapped to at least one literature/source-code precedent and one ReSETP data source.
- A list of feasible action heads, each mapped to the exact solver function or control point it can affect.
- A cheap test that can prove the action head changes objective-relevant behavior before long training.
- A baseline rule that compares against best static/tuned meta, not default AlphaUCB.
- A test plan covering schema, gates, worker path, NumPy version, feasibility, finite objective, and no protected semantics changes.

Pilot11 fails if it only says "use graph neural networks" without identifying available ReSETP data and a minimal integration point. It also fails if the proposed action cannot be evaluated cheaply before training.

## 9. Candidate Step 2 Paths After Pilot11

Path A is an acceptance-control pilot. Add or simulate a small acceptance/threshold/stop control surface, verify that it changes accepted candidates and final costs under a cheap replay or short-run harness, then decide whether PPO is justified.

Path B is a charging-strategy audit. Trace where charging decisions enter candidate repair and cost evaluation, then determine whether a discrete charging strategy head can be exposed without changing feasibility semantics.

Path C is a richer-state trace dataset. Extract route/customer/vehicle/charging features from existing rollouts and test whether they explain improvement better than the current 19 aggregate features. This is diagnostic only and can run before any PPO work.

Path D is static meta retune as engineering. If DR remains blocked, keep best static meta as an ALNS tuning result, clearly labeled as non-learning.

## 10. What Not To Do Next

Do not start Pilot12-style long training before Pilot11 passes.

Do not tune around Pilot10 by selecting different checkpoints until block_meta looks positive.

Do not weaken the comparison by returning to default AlphaUCB as the main opponent.

Do not broaden scope into cost semantics, feasibility semantics, or paper-number reruns unless the user explicitly switches workstreams.

Do not hide a negative result behind "more compute needed" unless the diagnostic specifically shows that compute, not interface design, is the bottleneck.

## 11. Files To Read Before Any DR Action

Always read these first:

- `D:\ReSETP\HANDOFF.md`
- `D:\ReSETP\docs\handoff\memory\project-plan-overview.md`
- `D:\ReSETP\docs\handoff\memory\alns-crush-root-cause.md`
- `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\literature_materials\dr_alns_gap_diagnosis_20260626.md`
- `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\literature_materials\dr_alns_deep_read_master_20260626.md`
- `D:\ReSETP\solver\reports\dr_alns_ppo_v3_block_dr_alns\async_pilot\pilot10\pilot10_summary.json`
- `D:\ReSETP\solver\rl\dr_alns_ppo\block_env.py`
- `D:\ReSETP\solver\rl\dr_alns_ppo\action_space.py`
- `D:\ReSETP\solver\src\setp_solver\search\winner_operators.py`
- `D:\ReSETP\solver\src\setp_solver\search\candidates.py`

Reference-code folders to inspect for design, not blind copying:

- `D:\ReSETP\Reference Algorithm\DR-ALNS@RobbertReijnen`
- `D:\ReSETP\Reference Algorithm\CodeforADeepReinforcementLearningEnhancedAdaptiveLargeNeighborhoodSearchAlgorithmfortheCapacitatedElectricVehicleRoutingProblem`
- `D:\ReSETP\Reference Algorithm\ppo-alns-main`

## 12. Commit And Artifact Rules

Planning documents may be committed normally. Generated reports under `solver/reports/` are ignored by default and should only be force-added when curated and explicitly useful for handoff.

Training models, all checkpoints, long logs, partial rows, cpu probes, and raw trace dumps should not be force-added unless the user explicitly asks for a curated artifact set.

Every commit that changes DR code should include tests. Every commit that records only project planning should avoid touching solver code.

## 13. Immediate Subplans

Subplan 1 is complete when this manual and the execution plan are present and the worktree only contains those intended documents.

Subplan 2 is Pilot11 interface audit. It should create a no-training diagnostic tool and tests. It should not change solver semantics.

Subplan 3 is a user-reviewed choice among acceptance control, charging-strategy control, richer-state trace dataset, or static retune packaging.

Subplan 4 is execution of the chosen small prototype only after Subplan 3 is accepted.

Subplan 5 is testing and validation. It decides whether the project earns a training run or writes a halt report.

This manual is the stop sign against repeating the same DR loop. The next meaningful DR work must improve the interface or stop cleanly.
