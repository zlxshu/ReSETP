from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import torch

from .action_space import (
    ALPHA_UCB_CHOICE,
    BLOCK_ACTION_NVECS,
    BLOCK_DESTROY_IDS,
    BLOCK_EXPLORATION_RATIOS,
    BLOCK_Q_RATIOS,
    BLOCK_REPAIR_IDS,
    BLOCK_THRESHOLD_RATIOS,
)
from .async_block_policy import BlockActorCritic, load_async_block_policy
from .baselines import normalize_result_row, solution_signature_hash
from .block_env import BlockAlnsEnv
from .pilot08_eval_tools import (
    BLOCK_SIZE,
    DEFAULT_WORKER,
    EVAL_FINAL_DIR,
    FORMAL_BUNDLE,
    HELD_OUT_BUNDLE,
    REQUIRED_NUMPY,
    RESULT_COLUMNS as PILOT08_RESULT_COLUMNS,
    TRAIN_BUNDLE,
    row_gate_issues,
)


PILOT09_DIR = Path("solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot09")
RESCUE_DIR = PILOT09_DIR / "rescue_diag"
PILOT08_TRAIN_FINAL_DIR = Path("solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot08/train_final")
PILOT08_BEST_CHECKPOINT = PILOT08_TRAIN_FINAL_DIR / "checkpoints" / "async_block_ppo_update_0240.pt"
PILOT08_FINAL_MODEL = PILOT08_TRAIN_FINAL_DIR / "async_block_ppo_model.pt"
ZOTERO_SKILL_ROOT = Path.home() / ".codex/plugins/cache/openai-curated-remote/zotero/0.1.2/skills/zotero"
ZOTERO_HELPER = ZOTERO_SKILL_ROOT / "scripts" / "zotero.py"
DEFAULT_DIAGNOSTIC_BUDGET = 600
DEFAULT_META_SCREEN_BUDGET = 600
DEFAULT_SEEDS = (1, 2, 3)
GATE_SEEDS = (1, 2, 3, 4, 5)
RUNTIME_TARGET_SECONDS = 0.0
REPO_EVIDENCE_FILES = (
    Path("HANDOFF.md"),
    Path("docs/handoff/memory/baseline-algorithm-catalog.md"),
    Path("docs/handoff/memory/alns-crush-root-cause.md"),
    Path("docs/handoff/memory/algorithm-pivot-ca-alns.md"),
)

EXTRA_COLUMNS = [
    "elapsed_seconds",
    "runtime_target_seconds",
    "model_label",
    "checkpoint_update",
    "eval_mode",
    "bundle_role",
    "selection_mode",
    "meta_q_ratio",
    "meta_threshold_ratio",
    "meta_exploration_ratio",
]
RESULT_COLUMNS = [*PILOT08_RESULT_COLUMNS, *[col for col in EXTRA_COLUMNS if col not in PILOT08_RESULT_COLUMNS]]

TRACE_COLUMNS = [
    "algorithm",
    "bundle",
    "seed",
    "step_index",
    "best_obj",
    "current_obj",
    "reward",
    "action_destroy",
    "action_repair",
    "action_q",
    "action_threshold",
    "action_exploration",
    "top_destroy",
    "top_repair",
    "top_q",
    "top_threshold",
    "top_exploration",
    "block_best_delta",
    "block_current_delta",
    "block_improved_best_count",
    "block_improved_current_count",
    "block_accepted_count",
    "block_rejected_count",
    "reward_components",
    "worker_python_executable",
    "worker_numpy_version",
    *[f"obs_{idx:02d}" for idx in range(19)],
]

LITERATURE_QUERIES = (
    "DRL EVRPTW curriculum",
    "reinforcement learning ALNS operator selection",
    "contextual bandit ALNS",
    "neural ALNS vehicle routing",
    "PPO combinatorial optimization collapse",
    "Daysalilar",
    "Wan DRL FSMVRP",
    "Narayanan EVRP",
)


def default_web_evidence() -> list[dict[str, Any]]:
    return [
        {
            "source_type": "web",
            "title": "A curriculum-based deep reinforcement learning framework for the electric vehicle routing problem",
            "authors": "Mertcan Daysalilar; Fuat Uyguroglu; Gabriel Nicolosi; Adam Meyers",
            "year": "2026",
            "url": "https://arxiv.org/abs/2601.15038",
            "finding": (
                "CB-DRL decomposes EVRPTW into routing, energy, and full-constraint phases with "
                "phase-specific PPO hyperparameters, value/advantage clipping, and small-to-large generalization."
            ),
            "pilot09_implication": (
                "Pilot08 already applied this family of fixes and trained healthily, so Pilot09 should look for "
                "headroom/action-space issues rather than repeat the same long curriculum PPO run."
            ),
        },
        {
            "source_type": "web",
            "title": "Online Control of Adaptive Large Neighborhood Search Using Deep Reinforcement Learning",
            "authors": "Robbert Reijnen; Yingqian Zhang; Hoong Chuin Lau; Zaharah Bukhsh",
            "year": "2024",
            "url": "https://ojs.aaai.org/index.php/ICAPS/article/view/31507",
            "finding": "DR-ALNS is framed as online ALNS operator selection and parameter configuration.",
            "pilot09_implication": (
                "Pilot09 should separately test operator-choice headroom and parameter-only headroom instead of "
                "assuming one PPO policy must learn both."
            ),
        },
        {
            "source_type": "web",
            "title": "DR-ALNS: Deep Reinforced Adaptive Large Neighborhood Search",
            "authors": "Robbert Reijnen et al.",
            "year": "2024",
            "url": "https://github.com/RobbertReijnen/DR-ALNS",
            "finding": "The public DR-ALNS implementation ties the method to the ICAPS 2024 online-control paper.",
            "pilot09_implication": (
                "Use trace/profile diagnostics before redesigning the controller; compare learned operator choices "
                "against the classical adaptive selector."
            ),
        },
        {
            "source_type": "web",
            "title": "A Deep Reinforcement Learning-Based Adaptive Large Neighborhood Search for Capacitated Electric Vehicle Routing Problems",
            "authors": "Chao Wang; Mengmeng Cao; Hao Jiang; Xiaoshu Xiang; Xingyi Zhang",
            "year": "2024/2025",
            "url": "https://ieeexplore.ieee.org/document/10660531/",
            "finding": "Recent EVRP work applies DRL specifically to ALNS operator selection.",
            "pilot09_implication": (
                "Keep the rescue bounded to learning/search-control diagnostics before changing EVRP feasibility or cost semantics."
            ),
        },
        {
            "source_type": "web",
            "title": "A Reinforcement Learning Approach for Electric Vehicle Routing Problem with Vehicle-to-Grid Supply",
            "authors": "Ajay Narayanan et al.",
            "year": "2022",
            "url": "https://arxiv.org/abs/2204.05545",
            "finding": "RL can be much faster than MILP/GA while staying within a quality gap, but it is not necessarily better quality.",
            "pilot09_implication": (
                "Treat a DR result that is only near AlphaUCB as meaningful speed/learning evidence, not automatic quality dominance."
            ),
        },
        {
            "source_type": "web",
            "title": "Deep Reinforcement Learning for Solving the Fleet Size and Mix Vehicle Routing Problem",
            "authors": "Pengfu Wan; Jiawei Chen; Gangyan Xu",
            "year": "2025",
            "url": "https://arxiv.org/abs/2512.24251",
            "finding": "FSMVRP DRL uses specialized embeddings for fleet composition and routing decisions.",
            "pilot09_implication": (
                "Pilot09 should record whether the current 19-dimensional flat observation aliases fleet-mix states; if so, "
                "the next fix is richer state representation, not more PPO episodes."
            ),
        },
    ]


def run_all(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    literature = write_literature_review(output_dir=output_dir)
    facts = write_pilot08_fact_audit(output_dir=output_dir)
    summary: dict[str, Any] = {
        "format": "pilot09_rescue_summary.v1",
        "output_dir": str(output_dir),
        "literature_status": literature["status"],
        "pilot08_fact_status": facts["status"],
        "diagnostics_status": "SKIPPED",
        "recommendation": "RUN_DIAGNOSTICS",
    }
    if not args.skip_diagnostics:
        diagnostics = run_rescue_diagnostics(
            output_dir=output_dir,
            eval_budget=int(args.eval_budget),
            meta_screen_budget=int(args.meta_screen_budget),
            seeds=parse_seeds(args.seeds),
            max_meta_configs=int(args.max_meta_configs),
            trace_steps=int(args.trace_steps),
        )
        summary.update(diagnostics)
    _write_json(output_dir / "pilot09_summary.json", summary)
    _write_text(output_dir / "pilot09_rescue_report.md", rescue_report_markdown(literature, facts, summary))
    return summary


def write_literature_review(*, output_dir: str | Path) -> dict[str, Any]:
    out = Path(output_dir)
    status = run_zotero_status()
    searches: dict[str, Any] = {}
    if status.get("api_running") and status.get("api_status") == 200:
        for query in LITERATURE_QUERIES:
            searches[query] = run_zotero_search(query)
        zotero_state = "PASS"
    else:
        zotero_state = "ZOTERO_UNAVAILABLE"
    repo_entries = repo_literature_evidence()
    entries = merge_literature_entries(status, searches, default_web_evidence(), repo_entries)
    payload = {
        "format": "pilot09_literature_review.v1",
        "status": zotero_state,
        "zotero_status": status,
        "queries": list(LITERATURE_QUERIES),
        "zotero_searches": searches,
        "repo_evidence_files": [str(path) for path in REPO_EVIDENCE_FILES if path.is_file()],
        "entries": entries,
    }
    _write_json(out / "literature_review.json", payload)
    _write_text(out / "literature_review.md", literature_markdown(payload))
    return payload


def run_zotero_status() -> dict[str, Any]:
    if not ZOTERO_HELPER.is_file():
        return {
            "status": "ZOTERO_UNAVAILABLE",
            "reason": f"helper missing: {ZOTERO_HELPER}",
            "api_running": False,
        }
    proc = subprocess.run(
        [sys.executable, str(ZOTERO_HELPER), "status", "--json"],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if proc.returncode != 0:
        return {
            "status": "ZOTERO_UNAVAILABLE",
            "reason": (proc.stderr or proc.stdout)[-2000:],
            "api_running": False,
        }
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {"status": "ZOTERO_UNAVAILABLE", "reason": str(exc), "api_running": False}
    payload["status"] = "PASS" if payload.get("api_running") else "ZOTERO_UNAVAILABLE"
    return payload


def run_zotero_search(query: str) -> list[dict[str, Any]]:
    proc = subprocess.run(
        [sys.executable, str(ZOTERO_HELPER), "search", query, "--json"],
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    if proc.returncode != 0:
        return [{"error": (proc.stderr or proc.stdout)[-2000:]}]
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return [{"error": str(exc)}]
    return payload if isinstance(payload, list) else []


def merge_literature_entries(
    zotero_status: dict[str, Any],
    zotero_searches: dict[str, Any],
    web_entries: list[dict[str, Any]],
    repo_entries: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for query, rows in zotero_searches.items():
        for row in rows if isinstance(rows, list) else []:
            if "error" in row:
                continue
            key = str(row.get("key", ""))
            title = str(row.get("title", ""))
            dedupe = ("zotero", key or title)
            if dedupe in seen:
                continue
            seen.add(dedupe)
            entries.append(
                {
                    "source_type": "zotero",
                    "query": query,
                    "zotero_item_key": key,
                    "title": title,
                    "authors": "; ".join(str(name) for name in row.get("creators", [])),
                    "year": str(row.get("year", "")),
                    "url": "",
                    "finding": literature_finding_for_title(title),
                    "pilot09_implication": literature_implication_for_title(title),
                }
            )
    entries.extend(repo_entries or [])
    entries.extend(web_entries)
    if zotero_status.get("status") != "PASS":
        entries.insert(
            0,
            {
                "source_type": "zotero_status",
                "title": "ZOTERO_UNAVAILABLE",
                "authors": "",
                "year": "",
                "url": "",
                "finding": str(zotero_status.get("reason", "Zotero local API unavailable")),
                "pilot09_implication": "Use web/paper fallback and mark the gate explicitly.",
            },
        )
    return entries


def repo_literature_evidence() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in REPO_EVIDENCE_FILES:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.name == "baseline-algorithm-catalog.md":
            entries.extend(repo_baseline_catalog_entries(path, text))
        elif path.name == "alns-crush-root-cause.md":
            entries.append(
                {
                    "source_type": "repo",
                    "title": "alns-crush-root-cause: PPO headroom against winner/AlphaUCB",
                    "authors": "repo handoff memory",
                    "year": "2026",
                    "url": str(path),
                    "finding": _snippet_after(
                        text,
                        "PPO现实天花板=匹配kernel",
                        fallback="Repo memory records that PPO should be judged against AlphaUCB/winner headroom, not SA alone.",
                    ),
                    "pilot09_implication": (
                        "Pilot09 should stop same-shape PPO long training if stochastic policy and AlphaUCB-meta diagnostics "
                        "cannot find reliable train+held-out headroom."
                    ),
                }
            )
        elif path.name == "algorithm-pivot-ca-alns.md":
            entries.append(
                {
                    "source_type": "repo",
                    "title": "algorithm-pivot-ca-alns: protect solver semantics and fair harness",
                    "authors": "repo handoff memory",
                    "year": "2026",
                    "url": str(path),
                    "finding": _snippet_after(
                        text,
                        "CA-ALNS = Carbon-Aware ALNS",
                        fallback="Repo memory says ALNS/DR work must stay inside the established destroy-repair-search framework.",
                    ),
                    "pilot09_implication": (
                        "The rescue tool may diagnose controller choices and traces, but must not rewrite cost, feasibility, "
                        "evaluation, or winner-operator semantics."
                    ),
                }
            )
        elif path.name == "HANDOFF.md":
            entries.append(
                {
                    "source_type": "repo",
                    "title": "HANDOFF Pilot08 WEAK and literature-first discipline",
                    "authors": "repo handoff",
                    "year": "2026",
                    "url": str(path),
                    "finding": _snippet_after(
                        text,
                        "pilot08 = **WEAK",
                        fallback="HANDOFF records Pilot08 as trained cleanly but WEAK under train+held-out gates.",
                    ),
                    "pilot09_implication": (
                        "Phase 1 must audit B2/C artifacts before running any new diagnostics, and Phase 3 must allow HALT_DR_HEADROOM."
                    ),
                }
            )
    return entries


def repo_baseline_catalog_entries(path: Path, text: str) -> list[dict[str, Any]]:
    return [
        {
            "source_type": "repo",
            "title": "baseline catalog: Daysalilar curriculum DRL-EVRP",
            "authors": "repo Zotero catalog",
            "year": "2026",
            "url": str(path),
            "zotero_item_key": "GKWV7NHV",
            "finding": _snippet_after(
                text,
                "Daysalilar2026课程PPO-EVRPTW",
                fallback="Daysalilar is recorded as curriculum PPO for EVRPTW with small-to-large generalization.",
            ),
            "pilot09_implication": (
                "Because Pilot08 already used small-to-large curriculum and phase-specific stabilization, the next fix "
                "should diagnose policy selection, meta-parameter headroom, reward alignment, and observations."
            ),
        },
        {
            "source_type": "repo",
            "title": "baseline catalog: Wan DRL-FSMVRP state representation",
            "authors": "repo Zotero catalog",
            "year": "2025",
            "url": str(path),
            "zotero_item_key": "6VNYWJ7Q",
            "finding": _snippet_after(
                text,
                "Wan2025 DRL-FSM",
                fallback="Wan is recorded as using fleet/routing representation ideas for FSMVRP DRL.",
            ),
            "pilot09_implication": (
                "Trace/profile diagnostics should look for observation aliasing in the current flat 19-dimensional state."
            ),
        },
        {
            "source_type": "repo",
            "title": "baseline catalog: Narayanan EVRP action masking",
            "authors": "repo Zotero catalog",
            "year": "2022",
            "url": str(path),
            "zotero_item_key": "BCBMVPMB",
            "finding": _snippet_after(
                text,
                "Narayanan2022 RL-EVRP-V2G",
                fallback="Narayanan is recorded as an EVRP RL baseline and source for action-mask style constraints.",
            ),
            "pilot09_implication": (
                "Pilot09 should explicitly test mask-aware stochastic evaluation because Pilot08 C used the standard ppo_block path."
            ),
        },
    ]


def _snippet_after(text: str, needle: str, *, fallback: str, length: int = 260) -> str:
    idx = text.find(needle)
    if idx < 0:
        return fallback
    snippet = text[idx : idx + length]
    return " ".join(snippet.split())


def literature_finding_for_title(title: str) -> str:
    lowered = title.lower()
    if "curriculum" in lowered and "electric vehicle routing" in lowered:
        return "Curriculum decomposition and phase-specific PPO stabilization are recommended for dense EVRP constraints."
    if "fleet size and mix" in lowered:
        return "Fleet-mix DRL benefits from state representations that separate fleet composition and routing context."
    return "Relevant DRL/VRP reference retrieved from Zotero; use it as evidence before changing the DR lane."


def literature_implication_for_title(title: str) -> str:
    lowered = title.lower()
    if "curriculum" in lowered:
        return "Pilot08 already tested the main curriculum/stability recipe; next step is headroom diagnosis, not another identical long run."
    if "fleet size and mix" in lowered:
        return "Check observation aliasing for fleet-mix signals before adding more PPO updates."
    return "Document how the reference informs any Pilot09 change before implementing that change."


def write_pilot08_fact_audit(*, output_dir: str | Path) -> dict[str, Any]:
    out = Path(output_dir)
    facts = pilot08_fact_audit()
    _write_json(out / "pilot08_fact_audit.json", facts)
    _write_text(out / "pilot08_fact_audit.md", pilot08_fact_markdown(facts))
    return facts


def pilot08_fact_audit() -> dict[str, Any]:
    b2 = _read_json(PILOT08_TRAIN_FINAL_DIR / "async_train_summary.json")
    b2_config = _read_json(PILOT08_TRAIN_FINAL_DIR / "async_training_config.json")
    c_summary = _read_json(EVAL_FINAL_DIR / "pilot08_summary.json")
    refine = _read_csv(EVAL_FINAL_DIR / "pilot08_checkpoint_refine_ranking.csv")
    paired = _read_csv(EVAL_FINAL_DIR / "pilot08_paired_relative.csv")
    runtime = _read_csv(EVAL_FINAL_DIR / "pilot08_runtime_summary.csv")
    best = refine[0] if refine else {}
    final_rank = next((row.get("rank", "") for row in refine if row.get("model_label") == "final"), "")
    return {
        "format": "pilot09_pilot08_fact_audit.v1",
        "status": "PASS",
        "b2_training": {
            "episodes": _to_int(b2.get("completed_episodes", b2.get("episodes"))),
            "policy_version": _to_int(b2.get("policy_version")),
            "final_curriculum_phase": b2.get("final_curriculum_phase"),
            "device": b2_config.get("resolved_device", b2.get("device")),
            "train_bundles": len(b2_config.get("train_bundles", b2.get("train_bundles", []))),
            "shared_baseline_by_bundle": bool(b2_config.get("shared_baseline_by_bundle", b2.get("shared_baseline_by_bundle"))),
        },
        "c_eval": {
            "verdict": c_summary.get("verdict"),
            "integrity": c_summary.get("integrity", {}),
            "equal_wall_clock_note": c_summary.get("equal_wall_clock_note", ""),
            "best_checkpoint": best,
            "final_refine_rank": final_rank,
        },
        "paired_relative": paired,
        "runtime_summary": runtime,
        "gates": {
            "best_checkpoint_exists": PILOT08_BEST_CHECKPOINT.is_file(),
            "final_model_exists": PILOT08_FINAL_MODEL.is_file(),
            "worker_py313_numpy_rows_ok": _comparison_rows_worker_ok(),
        },
    }


def run_rescue_diagnostics(
    *,
    output_dir: str | Path,
    eval_budget: int,
    meta_screen_budget: int,
    seeds: list[int],
    max_meta_configs: int,
    trace_steps: int,
) -> dict[str, Any]:
    out = Path(output_dir)
    rows: list[dict[str, Any]] = []
    for bundle, role in ((TRAIN_BUNDLE, "train"), (HELD_OUT_BUNDLE, "held_out"), (FORMAL_BUNDLE, "formal_eval")):
        for seed in seeds:
            rows.append(
                run_rescue_ppo_row(
                    model_path=PILOT08_BEST_CHECKPOINT,
                    bundle=bundle,
                    seed=seed,
                    eval_budget=eval_budget,
                    block_size=BLOCK_SIZE,
                    stochastic=False,
                    model_label="best_deterministic",
                    checkpoint_update_value=240,
                    bundle_role=role,
                )
            )
            rows.append(
                run_rescue_ppo_row(
                    model_path=PILOT08_BEST_CHECKPOINT,
                    bundle=bundle,
                    seed=seed,
                    eval_budget=eval_budget,
                    block_size=BLOCK_SIZE,
                    stochastic=True,
                    model_label="best_stochastic",
                    checkpoint_update_value=240,
                    bundle_role=role,
                )
            )
            rows.append(
                run_alpha_ucb_meta_row(
                    bundle=bundle,
                    seed=seed,
                    eval_budget=eval_budget,
                    block_size=BLOCK_SIZE,
                    q_ratio=0.16,
                    threshold_ratio=0.0,
                    exploration_ratio=0.0,
                    bundle_role=role,
                    model_label="alpha_default",
                )
            )
    _write_csv(out / "pilot09_policy_probe_rows.csv", rows, RESULT_COLUMNS)

    meta_screen = screen_alpha_ucb_meta(
        bundles=[TRAIN_BUNDLE, HELD_OUT_BUNDLE],
        eval_budget=meta_screen_budget,
        max_configs=max_meta_configs,
    )
    _write_csv(out / "pilot09_meta_screen_rows.csv", meta_screen, RESULT_COLUMNS)
    meta_ranking = rank_meta_configs(meta_screen)
    _write_csv(out / "pilot09_meta_screen_ranking.csv", meta_ranking)

    trace_rows = trace_policy_profiles(
        bundle=HELD_OUT_BUNDLE,
        seed=1,
        eval_budget=min(int(eval_budget), int(trace_steps) * int(BLOCK_SIZE)),
        block_size=BLOCK_SIZE,
        max_steps=trace_steps,
    )
    _write_csv(out / "pilot09_trace_profile.csv", trace_rows, TRACE_COLUMNS)

    stochastic_gate = classify_stochastic_gate(rows)
    meta_gate = classify_meta_gate(meta_ranking)
    diagnostics = {
        "diagnostics_status": "PASS",
        "policy_probe_rows": len(rows),
        "meta_screen_rows": len(meta_screen),
        "trace_rows": len(trace_rows),
        "stochastic_gate": stochastic_gate,
        "meta_gate": meta_gate,
        "recommendation": recommendation_from_gates(stochastic_gate, meta_gate),
    }
    _write_json(out / "pilot09_diagnostics_summary.json", diagnostics)
    return diagnostics


def run_rescue_ppo_row(
    *,
    model_path: str | Path,
    bundle: str,
    seed: int,
    eval_budget: int,
    block_size: int,
    stochastic: bool,
    model_label: str,
    checkpoint_update_value: int,
    bundle_role: str,
) -> dict[str, Any]:
    policy = load_async_block_policy(model_path)
    started = time.perf_counter()
    row, _trace = run_block_model_policy(
        model=policy.model,
        bundle=bundle,
        seed=seed,
        eval_budget=eval_budget,
        block_size=block_size,
        stochastic=stochastic,
        collect_trace=False,
    )
    elapsed = time.perf_counter() - started
    row.update(
        {
            "algorithm": "ppo_block_stochastic" if stochastic else "ppo_block_deterministic_masked",
            "elapsed_seconds": elapsed,
            "runtime_target_seconds": RUNTIME_TARGET_SECONDS,
            "model_label": model_label,
            "checkpoint_update": int(checkpoint_update_value),
            "eval_mode": "budget",
            "bundle_role": bundle_role,
            "selection_mode": "stochastic_masked" if stochastic else "deterministic_masked",
            "meta_q_ratio": "",
            "meta_threshold_ratio": "",
            "meta_exploration_ratio": "",
        }
    )
    issues = row_gate_issues(row, expected_budget=eval_budget)
    if issues:
        raise RuntimeError(f"rescue PPO row failed gates: {issues}")
    return normalize_rescue_row(row)


def run_block_model_policy(
    *,
    model: BlockActorCritic,
    bundle: str,
    seed: int,
    eval_budget: int,
    block_size: int,
    stochastic: bool,
    collect_trace: bool,
    max_steps: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    model.eval()
    env = BlockAlnsEnv(bundle, seed=int(seed), eval_budget=int(eval_budget), block_size=int(block_size))
    trace_rows: list[dict[str, Any]] = []
    destroy_counts: dict[str, int] = {}
    repair_counts: dict[str, int] = {}
    q_counts: dict[str, int] = {}
    try:
        obs, info = env.reset(seed=int(seed))
        current_mask = info.get("action_mask")
        terminated = False
        truncated = False
        step_idx = 0
        best_response = env.last_response or {}
        last_info = env.last_response or {}
        while not (terminated or truncated):
            if max_steps is not None and step_idx >= int(max_steps):
                break
            action, decision = sample_block_action(
                model,
                obs,
                current_mask,
                seed=policy_step_seed(seed, step_idx),
                deterministic=not stochastic,
            )
            next_obs, reward, terminated, truncated, step_info = env.step(action)
            trace = dict(step_info.get("trace", {}) or {})
            _inc(destroy_counts, str(trace.get("block_requested_destroy_id") or trace.get("destroy_id") or ""))
            _inc(repair_counts, str(trace.get("block_requested_repair_id") or trace.get("repair_id") or ""))
            q_value = trace.get("block_requested_q_ratio", trace.get("q_ratio"))
            if q_value not in (None, ""):
                _inc(q_counts, f"{float(q_value):.6f}")
            if collect_trace:
                trace_rows.append(
                    build_trace_row(
                        algorithm="ppo_block_stochastic" if stochastic else "ppo_block_deterministic_masked",
                        bundle=bundle,
                        seed=seed,
                        step_index=step_idx + 1,
                        obs=obs,
                        action=action,
                        decision=decision,
                        reward=reward,
                        info=step_info,
                    )
                )
            if float(step_info.get("best_obj", float("inf"))) <= float(best_response.get("best_obj", float("inf"))) + 1e-9:
                best_response = step_info
            last_info = step_info
            obs = next_obs
            current_mask = step_info.get("action_mask")
            step_idx += 1
        best_solution = best_response.get("solution", {})
        row = {
            "algorithm": "ppo_block",
            "bundle": bundle,
            "seed": int(seed),
            "eval_budget": int(eval_budget),
            "best_obj": float(last_info.get("best_obj", best_response.get("best_obj", 0.0))),
            "actual_evals": int(last_info.get("actual_evals", 0)),
            "candidate_scores": int(last_info.get("candidate_scores", 0)),
            "repair_delta_count": int(last_info.get("repair_delta_count", 0)),
            "operator_base_id": str((last_info.get("trace", {}) or {}).get("operator_base_id", "")),
            "control_mode": str((last_info.get("trace", {}) or {}).get("control_mode", "")),
            "violation_count": int(best_response.get("violation_count", 1)),
            "feasible": int(best_response.get("violation_count", 1)) == 0,
            "solution_signature_hash": solution_signature_hash(best_solution),
            "operator_counts": {},
            "destroy_counts": destroy_counts,
            "repair_counts": repair_counts,
            "q_ratio_counts": q_counts,
            "worker_python_executable": str((last_info.get("trace", {}) or {}).get("worker_python_executable", "")),
            "worker_python_version": str((last_info.get("trace", {}) or {}).get("worker_python_version", "")),
            "worker_numpy_version": str((last_info.get("trace", {}) or {}).get("worker_numpy_version", "")),
        }
        return normalize_result_row(row), trace_rows
    finally:
        env.close()


def sample_block_action(
    model: BlockActorCritic,
    obs: np.ndarray,
    mask: list[list[bool]] | None,
    *,
    seed: int,
    deterministic: bool,
) -> tuple[np.ndarray, dict[str, Any]]:
    torch.manual_seed(int(seed))
    np.random.seed(int(seed) % (2**32 - 1))
    decision = model.act(obs, deterministic=bool(deterministic), masks=mask)
    decision["top_labels"] = top_labels(model, obs, mask)
    return np.asarray(decision["action"], dtype=np.int64), decision


def top_labels(model: BlockActorCritic, obs: np.ndarray, mask: list[list[bool]] | None) -> list[str]:
    import torch

    obs_tensor = torch.as_tensor(obs, dtype=torch.float32).unsqueeze(0)
    logits, _values = model.forward(obs_tensor, masks=mask)
    labels = [BLOCK_DESTROY_IDS, BLOCK_REPAIR_IDS, tuple(str(v) for v in BLOCK_Q_RATIOS), tuple(str(v) for v in BLOCK_THRESHOLD_RATIOS), tuple(str(v) for v in BLOCK_EXPLORATION_RATIOS)]
    out: list[str] = []
    for idx, logit in enumerate(logits):
        top = int(torch.argmax(logit, dim=-1).item())
        out.append(str(labels[idx][top]))
    return out


def policy_step_seed(seed: int, step_idx: int) -> int:
    return int(seed) * 1_000_003 + int(step_idx) * 97 + 17


def run_alpha_ucb_meta_row(
    *,
    bundle: str,
    seed: int,
    eval_budget: int,
    block_size: int,
    q_ratio: float,
    threshold_ratio: float,
    exploration_ratio: float,
    bundle_role: str,
    model_label: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    row, _trace = run_fixed_block_action_policy(
        bundle=bundle,
        seed=seed,
        eval_budget=eval_budget,
        block_size=block_size,
        action=meta_action_tuple(q_ratio=q_ratio, threshold_ratio=threshold_ratio, exploration_ratio=exploration_ratio),
        algorithm="alpha_ucb_block_meta",
        collect_trace=False,
    )
    elapsed = time.perf_counter() - started
    label = model_label or meta_label(q_ratio, threshold_ratio, exploration_ratio)
    row.update(
        {
            "algorithm": "alpha_ucb_block_meta",
            "elapsed_seconds": elapsed,
            "runtime_target_seconds": RUNTIME_TARGET_SECONDS,
            "model_label": label,
            "checkpoint_update": "",
            "eval_mode": "budget",
            "bundle_role": bundle_role,
            "selection_mode": "alpha_ucb_meta",
            "meta_q_ratio": float(q_ratio),
            "meta_threshold_ratio": float(threshold_ratio),
            "meta_exploration_ratio": float(exploration_ratio),
        }
    )
    issues = row_gate_issues(row, expected_budget=eval_budget)
    if issues:
        raise RuntimeError(f"alpha_ucb_meta row failed gates: {issues}")
    return normalize_rescue_row(row)


def run_fixed_block_action_policy(
    *,
    bundle: str,
    seed: int,
    eval_budget: int,
    block_size: int,
    action: tuple[int, int, int, int, int],
    algorithm: str,
    collect_trace: bool,
    max_steps: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    env = BlockAlnsEnv(bundle, seed=int(seed), eval_budget=int(eval_budget), block_size=int(block_size))
    trace_rows: list[dict[str, Any]] = []
    destroy_counts: dict[str, int] = {}
    repair_counts: dict[str, int] = {}
    q_counts: dict[str, int] = {}
    try:
        obs, _info = env.reset(seed=int(seed))
        terminated = False
        truncated = False
        step_idx = 0
        best_response = env.last_response or {}
        last_info = env.last_response or {}
        while not (terminated or truncated):
            if max_steps is not None and step_idx >= int(max_steps):
                break
            next_obs, reward, terminated, truncated, step_info = env.step(action)
            trace = dict(step_info.get("trace", {}) or {})
            _inc(destroy_counts, str(trace.get("destroy_id", "")))
            _inc(repair_counts, str(trace.get("repair_id", "")))
            q_value = trace.get("q_ratio")
            if q_value not in (None, ""):
                _inc(q_counts, f"{float(q_value):.6f}")
            if collect_trace:
                trace_rows.append(
                    build_trace_row(
                        algorithm=algorithm,
                        bundle=bundle,
                        seed=seed,
                        step_index=step_idx + 1,
                        obs=obs,
                        action=np.asarray(action, dtype=np.int64),
                        decision={"top_labels": ["alpha_ucb", "alpha_ucb", "", "", ""]},
                        reward=reward,
                        info=step_info,
                    )
                )
            if float(step_info.get("best_obj", float("inf"))) <= float(best_response.get("best_obj", float("inf"))) + 1e-9:
                best_response = step_info
            obs = next_obs
            last_info = step_info
            step_idx += 1
        row = {
            "algorithm": algorithm,
            "bundle": bundle,
            "seed": int(seed),
            "eval_budget": int(eval_budget),
            "best_obj": float(last_info.get("best_obj", best_response.get("best_obj", 0.0))),
            "actual_evals": int(last_info.get("actual_evals", 0)),
            "candidate_scores": int(last_info.get("candidate_scores", 0)),
            "repair_delta_count": int(last_info.get("repair_delta_count", 0)),
            "operator_base_id": str((last_info.get("trace", {}) or {}).get("operator_base_id", "")),
            "control_mode": str((last_info.get("trace", {}) or {}).get("control_mode", "")),
            "violation_count": int(best_response.get("violation_count", 1)),
            "feasible": int(best_response.get("violation_count", 1)) == 0,
            "solution_signature_hash": solution_signature_hash(best_response.get("solution", {})),
            "operator_counts": {},
            "destroy_counts": destroy_counts,
            "repair_counts": repair_counts,
            "q_ratio_counts": q_counts,
            "worker_python_executable": str((last_info.get("trace", {}) or {}).get("worker_python_executable", "")),
            "worker_python_version": str((last_info.get("trace", {}) or {}).get("worker_python_version", "")),
            "worker_numpy_version": str((last_info.get("trace", {}) or {}).get("worker_numpy_version", "")),
        }
        return normalize_result_row(row), trace_rows
    finally:
        env.close()


def meta_action_tuple(*, q_ratio: float, threshold_ratio: float, exploration_ratio: float) -> tuple[int, int, int, int, int]:
    return (
        BLOCK_DESTROY_IDS.index(ALPHA_UCB_CHOICE),
        BLOCK_REPAIR_IDS.index(ALPHA_UCB_CHOICE),
        _nearest_index(BLOCK_Q_RATIOS, q_ratio),
        _nearest_index(BLOCK_THRESHOLD_RATIOS, threshold_ratio),
        _nearest_index(BLOCK_EXPLORATION_RATIOS, exploration_ratio),
    )


def screen_alpha_ucb_meta(*, bundles: list[str], eval_budget: int, max_configs: int) -> list[dict[str, Any]]:
    configs = limited_meta_configs(max_configs)
    rows: list[dict[str, Any]] = []
    for bundle in bundles:
        role = "train" if bundle == TRAIN_BUNDLE else "held_out" if bundle == HELD_OUT_BUNDLE else "formal_eval"
        for q_ratio, threshold_ratio, exploration_ratio in configs:
            rows.append(
                run_alpha_ucb_meta_row(
                    bundle=bundle,
                    seed=1,
                    eval_budget=eval_budget,
                    block_size=BLOCK_SIZE,
                    q_ratio=q_ratio,
                    threshold_ratio=threshold_ratio,
                    exploration_ratio=exploration_ratio,
                    bundle_role=role,
                    model_label=meta_label(q_ratio, threshold_ratio, exploration_ratio),
                )
            )
    return rows


def meta_grid() -> list[tuple[float, float, float]]:
    return [
        (float(q), float(threshold), float(exploration))
        for q in BLOCK_Q_RATIOS
        for threshold in (0.0, 0.0025, 0.0075)
        for exploration in (0.0, 0.05, 0.15)
    ]


def default_meta_config() -> tuple[float, float, float]:
    return (0.16, 0.0, 0.0)


def limited_meta_configs(max_configs: int) -> list[tuple[float, float, float]]:
    configs = list(meta_grid())
    if max_configs <= 0:
        return configs
    limited = configs[: int(max_configs)]
    default = default_meta_config()
    if default not in limited:
        if len(limited) >= int(max_configs):
            limited[-1] = default
        else:
            limited.append(default)
    return limited


def rank_meta_configs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("model_label", ""))].append(row)
    ranked: list[dict[str, Any]] = []
    for label, group in grouped.items():
        train = [row for row in group if row.get("bundle") == TRAIN_BUNDLE]
        held = [row for row in group if row.get("bundle") == HELD_OUT_BUNDLE]
        if not train or not held:
            continue
        ranked.append(
            {
                "model_label": label,
                "n": len(group),
                "mean_best_obj": statistics.fmean(float(row["best_obj"]) for row in group),
                "train_best_obj": statistics.fmean(float(row["best_obj"]) for row in train),
                "held_out_best_obj": statistics.fmean(float(row["best_obj"]) for row in held),
                "meta_q_ratio": group[0].get("meta_q_ratio", ""),
                "meta_threshold_ratio": group[0].get("meta_threshold_ratio", ""),
                "meta_exploration_ratio": group[0].get("meta_exploration_ratio", ""),
            }
        )
    ranked.sort(key=lambda row: (float(row["mean_best_obj"]), str(row["model_label"])))
    for idx, row in enumerate(ranked, start=1):
        row["rank"] = idx
    return ranked


def trace_policy_profiles(*, bundle: str, seed: int, eval_budget: int, block_size: int, max_steps: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    policy = load_async_block_policy(PILOT08_BEST_CHECKPOINT)
    _row, ppo_trace = run_block_model_policy(
        model=policy.model,
        bundle=bundle,
        seed=seed,
        eval_budget=eval_budget,
        block_size=block_size,
        stochastic=False,
        collect_trace=True,
        max_steps=max_steps,
    )
    rows.extend(ppo_trace)
    action = meta_action_tuple(q_ratio=0.16, threshold_ratio=0.0, exploration_ratio=0.0)
    _row, alpha_trace = run_fixed_block_action_policy(
        bundle=bundle,
        seed=seed,
        eval_budget=eval_budget,
        block_size=block_size,
        action=action,
        algorithm="alpha_ucb_block_meta",
        collect_trace=True,
        max_steps=max_steps,
    )
    rows.extend(alpha_trace)
    return rows


def build_trace_row(
    *,
    algorithm: str,
    bundle: str,
    seed: int,
    step_index: int,
    obs: np.ndarray,
    action: np.ndarray,
    decision: dict[str, Any],
    reward: float,
    info: dict[str, Any],
) -> dict[str, Any]:
    trace = dict(info.get("trace", {}) or {})
    labels = list(decision.get("top_labels", []))
    padded_action = list(action.astype(int).tolist()) + ["", "", "", "", ""]
    padded_labels = labels + ["", "", "", "", ""]
    row: dict[str, Any] = {
        "algorithm": algorithm,
        "bundle": bundle,
        "seed": int(seed),
        "step_index": int(step_index),
        "best_obj": float(info.get("best_obj", 0.0) or 0.0),
        "current_obj": float(info.get("current_obj", 0.0) or 0.0),
        "reward": float(reward),
        "action_destroy": padded_action[0],
        "action_repair": padded_action[1],
        "action_q": padded_action[2],
        "action_threshold": padded_action[3],
        "action_exploration": padded_action[4],
        "top_destroy": padded_labels[0],
        "top_repair": padded_labels[1],
        "top_q": padded_labels[2],
        "top_threshold": padded_labels[3],
        "top_exploration": padded_labels[4],
        "block_best_delta": _to_float(trace.get("block_best_delta")),
        "block_current_delta": _to_float(trace.get("block_current_delta")),
        "block_improved_best_count": _to_int(trace.get("block_improved_best_count")),
        "block_improved_current_count": _to_int(trace.get("block_improved_current_count")),
        "block_accepted_count": _to_int(trace.get("block_accepted_count")),
        "block_rejected_count": _to_int(trace.get("block_rejected_count")),
        "reward_components": info.get("reward_components", {}),
        "worker_python_executable": str(trace.get("worker_python_executable", "")),
        "worker_numpy_version": str(trace.get("worker_numpy_version", "")),
    }
    for idx, value in enumerate(np.asarray(obs, dtype=float).tolist()):
        row[f"obs_{idx:02d}"] = float(value)
    return row


def classify_stochastic_gate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    paired = paired_relative(rows, left_algorithm="ppo_block_stochastic", baseline_algorithm="alpha_ucb_block_meta")
    train = paired.get(TRAIN_BUNDLE)
    held = paired.get(HELD_OUT_BUNDLE)
    paired_n = min(_to_int((train or {}).get("paired_n")), _to_int((held or {}).get("paired_n")))
    if paired_n < 5:
        return {
            "status": "INCONCLUSIVE_STOCHASTIC",
            "paired": list(paired.values()),
            "rule": "requires train and held_out paired_n >= 5 before applying the 4/5 win gate",
        }
    passed = bool(
        train
        and held
        and float(train["mean_relative_pct"]) > 0.0
        and int(train["wins"]) >= 4
        and float(held["mean_relative_pct"]) > 0.0
        and int(held["wins"]) >= 4
    )
    return {
        "status": "PROMISING_STOCHASTIC" if passed else "WEAK_STOCHASTIC",
        "paired": list(paired.values()),
        "rule": "train and held_out mean_relative_pct > 0 and wins >= 4/5 versus alpha_ucb default",
    }


def classify_meta_gate(meta_ranking: list[dict[str, Any]]) -> dict[str, Any]:
    if not meta_ranking:
        return {"status": "INCONCLUSIVE_META", "reason": "no meta rows"}
    best = meta_ranking[0]
    default = next((row for row in meta_ranking if row["model_label"] == meta_label(0.16, 0.0, 0.0)), None)
    if default is None:
        return {"status": "INCONCLUSIVE_META", "best": best, "reason": "default alpha_ucb meta row missing"}
    train_rel = (float(default["train_best_obj"]) - float(best["train_best_obj"])) / max(abs(float(default["train_best_obj"])), 1.0) * 100.0
    held_rel = (float(default["held_out_best_obj"]) - float(best["held_out_best_obj"])) / max(abs(float(default["held_out_best_obj"])), 1.0) * 100.0
    passed = train_rel > 0.5 and held_rel > 0.5
    return {
        "status": "PROMISING_META_SCREEN" if passed else "WEAK_META_SCREEN",
        "best": best,
        "default": default,
        "train_relative_pct": train_rel,
        "held_out_relative_pct": held_rel,
        "rule": "screen only: best meta config improves train and held_out by > 0.5% versus default alpha_ucb meta; 3-seed wins gate still required before training block_meta",
    }


def recommendation_from_gates(stochastic_gate: dict[str, Any], meta_gate: dict[str, Any]) -> str:
    if stochastic_gate.get("status") == "PROMISING_STOCHASTIC":
        return "PROMISING_STOCHASTIC"
    if meta_gate.get("status") == "PROMISING_META_SCREEN":
        return "REFINE_ALPHA_UCB_META_NEXT"
    if "INCONCLUSIVE" in str(stochastic_gate.get("status")) or "INCONCLUSIVE" in str(meta_gate.get("status")):
        return "INCONCLUSIVE_NEEDS_FULL_GATE"
    return "HALT_DR_HEADROOM"


def paired_relative(
    rows: list[dict[str, Any]],
    *,
    left_algorithm: str,
    baseline_algorithm: str,
) -> dict[str, dict[str, Any]]:
    grouped: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in rows:
        grouped[(str(row["algorithm"]), str(row["bundle"]), int(row["seed"]))] = row
    by_bundle: dict[str, list[float]] = defaultdict(list)
    wins: dict[str, int] = defaultdict(int)
    counts: dict[str, int] = defaultdict(int)
    for (algorithm, bundle, seed), left in list(grouped.items()):
        if algorithm != left_algorithm:
            continue
        base = grouped.get((baseline_algorithm, bundle, seed))
        if base is None:
            continue
        left_cost = float(left["best_obj"])
        base_cost = float(base["best_obj"])
        relative = (base_cost - left_cost) / max(abs(base_cost), 1.0) * 100.0
        by_bundle[bundle].append(relative)
        wins[bundle] += int(left_cost < base_cost)
        counts[bundle] += 1
    out: dict[str, dict[str, Any]] = {}
    for bundle, values in by_bundle.items():
        out[bundle] = {
            "bundle": bundle,
            "left_algorithm": left_algorithm,
            "baseline_algorithm": baseline_algorithm,
            "paired_n": counts[bundle],
            "wins": wins[bundle],
            "mean_relative_pct": statistics.fmean(values),
            "std_relative_pct": statistics.stdev(values) if len(values) > 1 else 0.0,
            "min_relative_pct": min(values),
            "max_relative_pct": max(values),
        }
    return out


def normalize_rescue_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_result_row(row)
    for key in EXTRA_COLUMNS:
        normalized[key] = row.get(key, "")
    normalized["elapsed_seconds"] = float(normalized.get("elapsed_seconds") or 0.0)
    normalized["runtime_target_seconds"] = float(normalized.get("runtime_target_seconds") or 0.0)
    return normalized


def parse_seeds(text: str) -> list[int]:
    seeds = [int(part.strip()) for part in str(text).split(",") if part.strip()]
    if not seeds:
        raise ValueError("at least one seed is required")
    return seeds


def literature_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Pilot09 Literature Review",
        "",
        f"- Zotero status: `{payload['status']}`",
        f"- Zotero API running: `{payload.get('zotero_status', {}).get('api_running', False)}`",
        "",
        "## Evidence",
        "",
    ]
    for item in payload["entries"]:
        key = item.get("zotero_item_key") or item.get("url") or item.get("source_type")
        lines.extend(
            [
                f"### {item.get('title', '')}",
                "",
                f"- source: `{item.get('source_type', '')}` `{key}`",
                f"- authors/year: {item.get('authors', '')} / {item.get('year', '')}",
                f"- finding: {item.get('finding', '')}",
                f"- Pilot09 implication: {item.get('pilot09_implication', '')}",
                "",
            ]
        )
    return "\n".join(lines)


def pilot08_fact_markdown(payload: dict[str, Any]) -> str:
    b2 = payload["b2_training"]
    c_eval = payload["c_eval"]
    return "\n".join(
        [
            "# Pilot08 Fact Audit",
            "",
            f"- B2 episodes: `{b2['episodes']}`",
            f"- B2 updates/policy_version: `{b2['policy_version']}`",
            f"- B2 final phase: `{b2['final_curriculum_phase']}`",
            f"- B2 device: `{b2['device']}`",
            f"- C verdict: `{c_eval['verdict']}`",
            f"- C best checkpoint: `{c_eval['best_checkpoint'].get('model_label', '')}` update `{c_eval['best_checkpoint'].get('checkpoint_update', '')}`",
            f"- C final refine rank: `{c_eval['final_refine_rank']}`",
            f"- Integrity: `{json.dumps(c_eval['integrity'], ensure_ascii=False)}`",
            "",
            "## Equal-Wall-Clock Caveat",
            "",
            str(c_eval.get("equal_wall_clock_note", "")),
            "",
        ]
    )


def rescue_report_markdown(literature: dict[str, Any], facts: dict[str, Any], summary: dict[str, Any]) -> str:
    lines = [
        "# Pilot09 DR Rescue Diagnostic Report",
        "",
        "This report uses same-machine x86 relative percentages only and does not compare x86 absolute objectives to M1.",
        "",
        f"- literature_status: `{literature.get('status')}`",
        f"- pilot08_fact_status: `{facts.get('status')}`",
        f"- diagnostics_status: `{summary.get('diagnostics_status')}`",
        f"- recommendation: `{summary.get('recommendation')}`",
        "",
    ]
    if "stochastic_gate" in summary:
        lines.extend(["## Stochastic Gate", "", "```json", json.dumps(summary["stochastic_gate"], ensure_ascii=False, indent=2), "```", ""])
    if "meta_gate" in summary:
        lines.extend(["## Meta Gate", "", "```json", json.dumps(summary["meta_gate"], ensure_ascii=False, indent=2), "```", ""])
    return "\n".join(lines)


def meta_label(q_ratio: float, threshold_ratio: float, exploration_ratio: float) -> str:
    return f"meta_q{float(q_ratio):.2f}_t{float(threshold_ratio):.4f}_e{float(exploration_ratio):.2f}"


def _nearest_index(values: tuple[float, ...], target: float) -> int:
    return min(range(len(values)), key=lambda idx: abs(float(values[idx]) - float(target)))


def _comparison_rows_worker_ok() -> bool:
    path = EVAL_FINAL_DIR / "pilot08_comparison_rows.csv"
    if not path.is_file():
        return False
    rows = _read_csv(path)
    return all(
        str(row.get("worker_python_executable", "")) == DEFAULT_WORKER
        and str(row.get("worker_numpy_version", "")) == REQUIRED_NUMPY
        and _to_int(row.get("violation_count")) == 0
        for row in rows
    )


def _inc(counts: dict[str, int], key: str) -> None:
    if key:
        counts[key] = int(counts.get(key, 0)) + 1


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _read_csv(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_json(path: str | Path, payload: Any) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: str | Path, text: str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def _write_csv(path: str | Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key, "")) for key in fieldnames})


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if isinstance(value, bool):
        return int(value)
    return value


def _to_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pilot09 literature-first DR rescue diagnostics.")
    parser.add_argument("--output-dir", default=str(RESCUE_DIR))
    parser.add_argument("--eval-budget", type=int, default=DEFAULT_DIAGNOSTIC_BUDGET)
    parser.add_argument("--meta-screen-budget", type=int, default=DEFAULT_META_SCREEN_BUDGET)
    parser.add_argument("--seeds", default=",".join(str(seed) for seed in DEFAULT_SEEDS))
    parser.add_argument("--max-meta-configs", type=int, default=0, help="0 means full Pilot09 meta grid.")
    parser.add_argument("--trace-steps", type=int, default=5)
    parser.add_argument("--skip-diagnostics", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    summary = run_all(parse_args(argv))
    print(f"PILOT09_RESCUE_OK recommendation={summary['recommendation']} output={summary.get('output_dir', RESCUE_DIR)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
