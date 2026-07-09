"""Turn console selections into an ordered job list."""

from __future__ import annotations

from typing import Any

from .registry import (
    ARTIFACT_ORDER,
    EXPERIMENT_ORDER,
    Job,
    expand_range,
    normalize_artifacts,
    normalize_experiments,
)


def _instances(block: dict[str, Any] | None) -> tuple[str, ...]:
    if not block:
        return ()
    items = block.get("instances") or []
    return tuple(str(x) for x in items)


def plan_jobs(control: dict[str, Any]) -> list[Job]:
    mode = str(control.get("mode", "select")).strip().lower()
    if mode == "select":
        return _plan_select(control.get("select") or {})
    if mode == "batch":
        return _plan_batch(control.get("batch") or {})
    if mode == "range":
        return _plan_range(control.get("range") or {})
    raise ValueError(f"Unknown mode {mode!r}. Use: batch | select | range")


def _plan_select(block: dict[str, Any]) -> list[Job]:
    experiments = normalize_experiments(block.get("experiments") or [])
    if not experiments:
        raise ValueError("select.experiments is empty")
    artifacts = normalize_artifacts(block.get("artifacts") or [])
    instances = _instances(block)
    jobs: list[Job] = []
    for exp in experiments:
        arts = artifacts or normalize_artifacts(None, experiment=exp)
        if not arts:
            raise ValueError(f"No artifacts resolved for experiment {exp}")
        for art in arts:
            jobs.append(
                Job(
                    experiment=exp,
                    artifact=art,
                    instances=instances,
                    job_id=f"select_{exp}_{art}",
                )
            )
    return jobs


def _plan_batch(block: dict[str, Any]) -> list[Job]:
    raw_jobs = block.get("jobs") or []
    if not raw_jobs:
        raise ValueError("batch.jobs is empty")
    jobs: list[Job] = []
    for i, raw in enumerate(raw_jobs):
        if not isinstance(raw, dict):
            raise ValueError(f"batch.jobs[{i}] must be a mapping")
        exp = normalize_experiments([raw.get("experiment")])[0]
        arts = normalize_artifacts(raw.get("artifacts") or [], experiment=exp)
        instances = tuple(str(x) for x in (raw.get("instances") or []))
        jid = str(raw.get("id") or f"batch_{i}_{exp}")
        for art in arts:
            jobs.append(Job(experiment=exp, artifact=art, instances=instances, job_id=f"{jid}_{art}"))
    return jobs


def _plan_range(block: dict[str, Any]) -> list[Job]:
    exps = expand_range(
        str(block.get("experiment_from", "E1")),
        str(block.get("experiment_to", "E1")),
        EXPERIMENT_ORDER,
        "experiment",
    )
    arts = expand_range(
        str(block.get("artifact_from", "T3")),
        str(block.get("artifact_to", "T3")),
        ARTIFACT_ORDER,
        "artifact",
    )
    instances = _instances(block)
    jobs: list[Job] = []
    for exp in exps:
        for art in arts:
            jobs.append(
                Job(
                    experiment=exp,
                    artifact=art,
                    instances=instances,
                    job_id=f"range_{exp}_{art}",
                )
            )
    return jobs
