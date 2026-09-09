#!/usr/bin/env python3
"""Re-apply the retired STRICT acceptance rules to a section 4.7 dynamic run.

The current runner (``solver/scripts/run_dynamic_experiment.py``) writes a
thin package and hard-codes ``run_status: "completed"``.  The retired runner
(git 21d958db6, same path) enforced a much stricter contract before it would
call a run accepted.  This script reads a finished run directory -- either
layout -- re-applies those rules read-only, and prints the paper's
``tab:dynamic`` rows.

It never writes, never launches a solve, and never imports the solver.

Usage
-----
    python3 solver/scripts/dynamic_run_audit.py <run_dir> [options]

Examples
--------
    python3 solver/scripts/dynamic_run_audit.py \
        solver/reports/dynamic_v7_20260909
    python3 solver/scripts/dynamic_run_audit.py \
        solver/reports/submission_fallback_20260824/\
56_dynamic_formal_seed1_single_seed_corrected \
        --expected-batches 6 --expected-carbon-price 0.2
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

csv.field_size_limit(sys.maxsize)


# --------------------------------------------------------------------------
# Layout normalisation.  The two runners name the same things differently.
# --------------------------------------------------------------------------

ROLLING = "rolling"
SEQUENTIAL = "sequential"
STATIC = "static"

ARM_ALIASES = {
    # current runner (run_dynamic_experiment.py, ARM_* constants)
    "rolling_reoptimization": ROLLING,
    "sequential_insertion": SEQUENTIAL,
    "full_information_reference": STATIC,
    # retired runner / 2026-08-24 package
    "rolling_dynamic": ROLLING,
    "mechanical_online_p38": SEQUENTIAL,
    "full_information_static_reference": STATIC,
}

ARM_LABEL = {
    ROLLING: "rolling_reoptimization (rolling_dynamic)",
    SEQUENTIAL: "sequential_insertion (mechanical_online_p38)",
    STATIC: "full_information_static_reference",
}

BATCH_FILES = ("dynamic_events.csv", "per_reveal_events.csv")

# decision_detail / decision_status values that the retired acceptance gate
# treated as a hard failure (see main3b_backend.rolling_reoptimize).
DEFER_DETAILS = (
    "rolling_defer_no_feasible_candidate",
    "rolling_defer_dynamic_insertion_exception",
)
LATCH_STATUS = "infeasible_candidate_policy_required"
EXHAUSTED_TOKEN = "NOT_INSERTED_SEARCH_EXHAUSTED"
FAILURE_DIAG_KINDS = (
    "dynamic_insertion_no_feasible_candidate",
    "dynamic_insertion_exception",
    "mechanical_no_feasible_candidate",
    "static_preinsert_failure",
)


class AuditError(RuntimeError):
    pass


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_arm(value: str) -> str | None:
    return ARM_ALIASES.get(str(value).strip())


def _num(row: Mapping[str, Any], *names: str) -> float | None:
    """First present, non-empty, numeric field among ``names``."""
    for name in names:
        raw = row.get(name)
        if raw in (None, ""):
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def _text(row: Mapping[str, Any], *names: str) -> str:
    for name in names:
        raw = row.get(name)
        if raw not in (None, ""):
            return str(raw)
    return ""


def _bool(value: Any) -> bool | None:
    text = str(value).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    return None


def _ids(value: str) -> tuple[str, ...]:
    return tuple(item for item in str(value or "").split("|") if item)


def _json_list(raw: str) -> list[Any]:
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return decoded if isinstance(decoded, list) else []


def _snapshot_routes(raw: str) -> list[dict[str, Any]]:
    """Route list out of a route snapshot.

    ``main3b_backend._route_snapshot_json`` emits an object with a ``routes``
    key (alongside ``coordinates``); older packages may hold a bare list.
    """
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(decoded, dict):
        decoded = decoded.get("routes", [])
    if not isinstance(decoded, list):
        return []
    return [item for item in decoded if isinstance(item, dict)]


# --------------------------------------------------------------------------
# Run loading
# --------------------------------------------------------------------------


class Run:
    def __init__(self, run_dir: Path) -> None:
        self.dir = run_dir
        if not run_dir.is_dir():
            raise AuditError(f"not a directory: {run_dir}")
        self.raw_rows = _read_csv(run_dir / "raw_runs.csv")
        if not self.raw_rows:
            raise AuditError(f"missing or empty raw_runs.csv in {run_dir}")
        self.batch_file = ""
        batch_rows: list[dict[str, str]] = []
        for name in BATCH_FILES:
            rows = _read_csv(run_dir / name)
            if rows:
                self.batch_file, batch_rows = name, rows
                break
        self.metadata = _read_json(run_dir / "metadata.json") or {}
        self.decision = _read_json(run_dir / "decision.json") or {}
        self.paired = _read_csv(run_dir / "paired_results.csv")

        self.raw: dict[str, dict[str, str]] = {}
        for row in self.raw_rows:
            arm = _canonical_arm(row.get("arm", ""))
            if arm:
                self.raw[arm] = row

        self.batches: dict[str, list[dict[str, str]]] = {}
        for row in batch_rows:
            arm = _canonical_arm(row.get("arm", ""))
            if arm is None:
                continue
            self.batches.setdefault(arm, []).append(row)
        for rows in self.batches.values():
            rows.sort(key=lambda item: int(float(item.get("batch_index") or 0)))

        # ``fallback_diagnostics_json`` is the state's whole diagnostics list,
        # so batch n contains batch n-1 as a prefix.  Slice it back apart.
        self.diag: dict[str, list[list[dict[str, Any]]]] = {}
        for arm, rows in self.batches.items():
            previous = 0
            per_batch: list[list[dict[str, Any]]] = []
            for row in rows:
                whole = _json_list(row.get("fallback_diagnostics_json", ""))
                if len(whole) < previous:  # not a prefix chain; keep it whole
                    per_batch.append([d for d in whole if isinstance(d, dict)])
                else:
                    per_batch.append(
                        [d for d in whole[previous:] if isinstance(d, dict)]
                    )
                previous = len(whole)
            self.diag[arm] = per_batch

    @property
    def instance_id(self) -> str:
        return _text(self.raw_rows[0], "instance_id")

    def batch_count(self, arm: str) -> int:
        return len(self.batches.get(arm, ()))


# --------------------------------------------------------------------------
# Reporting helpers
# --------------------------------------------------------------------------


class Report:
    def __init__(self) -> None:
        self.results: list[tuple[str, str, bool | None]] = []

    def check(self, name: str, passed: bool | None, *evidence: str) -> None:
        mark = {True: "PASS", False: "FAIL", None: "UNRESOLVED"}[passed]
        print(f"[{mark}] {name}")
        for line in evidence:
            print(f"       {line}")
        self.results.append((name, mark, passed))

    def note(self, *lines: str) -> None:
        for line in lines:
            print(f"       {line}")

    def summary(self) -> int:
        print()
        print("=" * 78)
        failed = [n for n, m, _ in self.results if m == "FAIL"]
        unresolved = [n for n, m, _ in self.results if m == "UNRESOLVED"]
        print(
            f"AUDIT VERDICT: {'FAILED' if failed else 'PASSED'}  "
            f"({len(failed)} FAIL, {len(unresolved)} UNRESOLVED, "
            f"{len(self.results)} checks)"
        )
        for name in failed:
            print(f"  FAIL       {name}")
        for name in unresolved:
            print(f"  UNRESOLVED {name}")
        return 1 if failed else 0


def _section(title: str) -> None:
    print()
    print("-" * 78)
    print(title)
    print("-" * 78)


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------


def check_service(run: Run, report: Report) -> None:
    """1. Every batch served all active customers; final unserved == 0."""
    _section("CHECK 1 -- every batch served all active customers")
    per_batch_ok = True
    for arm in (ROLLING, SEQUENTIAL):
        rows = run.batches.get(arm, [])
        if not rows:
            report.note(f"{ARM_LABEL[arm]}: no per-batch rows found")
            continue
        for row in rows:
            index = _text(row, "batch_index")
            served = _num(row, "customers_served")
            # new runner: customers_total; retired runner: customers_revealed
            total = _num(row, "customers_total", "customers_revealed")
            unserved = _ids(_text(row, "unserved_customer_ids"))
            if served is None or total is None:
                report.note(f"{arm} batch {index}: served/total field missing")
                per_batch_ok = False
                continue
            ok = int(served) == int(total) and not unserved
            per_batch_ok = per_batch_ok and ok
            if not ok:
                print(
                    f"       {arm:<10} batch {index}: served {int(served)} "
                    f"of {int(total)} active; unserved={'|'.join(unserved) or '-'}"
                )
    report.check("1a  served == active in every batch", per_batch_ok)

    final_ok = True
    lines: list[str] = []
    for arm, row in sorted(run.raw.items()):
        served = _num(row, "customers_served")
        total = _num(row, "customers_total")
        unserved = _ids(_text(row, "unserved_customer_ids"))
        ok = (
            served is not None
            and total is not None
            and int(served) == int(total)
            and not unserved
        )
        final_ok = final_ok and ok
        lines.append(
            f"{ARM_LABEL[arm]}: {int(served or 0)}/{int(total or 0)} served, "
            f"unserved={'|'.join(unserved) or 'none'}"
        )
    report.check("1b  final plan unserved == 0", final_ok, *lines)


def check_hgs_calls(run: Run, report: Report, expected: int | None) -> None:
    """2. Exactly one HGS stage call per trigger batch on the rolling arm."""
    _section("CHECK 2 -- one HGS stage call per rolling trigger batch")
    rows = run.batches.get(ROLLING, [])
    diags = run.diag.get(ROLLING, [])
    if not rows:
        report.check("2   one problem_hgs_stage call per batch", None,
                     "no rolling per-batch rows to count")
        return
    target = expected if expected is not None else len(rows)
    total = 0
    offenders: list[str] = []
    for row, batch_diag in zip(rows, diags):
        index = _text(row, "batch_index")
        stages = [d for d in batch_diag if d.get("kind") == "problem_hgs_stage"]
        total += len(stages)
        sources = [str(d.get("source", "primary")) for d in stages]
        print(
            f"       batch {index}: problem_hgs_stage x{len(stages)}"
            f"  source={sources or ['-']}"
        )
        if len(stages) != 1:
            offenders.append(
                f"batch {index}: {len(stages)} calls "
                f"({'defer-all' if not stages else 'multiple'})"
            )
    # cross-check against whatever the run recorded itself
    recorded = _num(run.raw.get(ROLLING, {}), "hgs_call_count",
                    "actual_hgs_call_count")
    evidence = [
        f"counted {total} problem_hgs_stage rows over {len(rows)} trigger "
        f"batches; expected {target}",
    ]
    if recorded is not None:
        evidence.append(f"run's own hgs_call_count field = {int(recorded)}")
    evidence.extend(offenders)
    evidence.append(
        "note: the partial-fallback path also emits kind=problem_hgs_stage "
        "with source=partial_mechanical_fallback, so a count of 1 is not by "
        "itself proof the batch used the ordinary rolling search"
    )
    report.check(
        "2   one problem_hgs_stage call per batch",
        total == target and not offenders,
        *evidence,
    )


def check_batch_terminations(run: Run, report: Report) -> None:
    """3. No batch ended deferred or search-exhausted; per-batch ledger."""
    _section("CHECK 3 -- per-batch decision ledger (rolling arm)")
    rows = run.batches.get(ROLLING, [])
    diags = run.diag.get(ROLLING, [])
    if not rows:
        report.check("3   no defer / search-exhausted batch", None,
                     "no rolling per-batch rows")
        return
    bad: list[str] = []
    previous_defer: tuple[str, ...] = ()
    for row, batch_diag in zip(rows, diags):
        index = _text(row, "batch_index")
        detail = _text(row, "decision_detail")
        status = _text(row, "decision_status") or "(field absent in this layout)"
        wall = _num(row, "actual_wall_clock_seconds") or 0.0
        blob = json.dumps(batch_diag, ensure_ascii=False)
        attempts = 0
        for diag in batch_diag:
            if "dynamic_insertion_candidate_count" in diag:
                attempts += int(diag["dynamic_insertion_candidate_count"])
            elif isinstance(diag.get("candidate_diagnostics"), list):
                attempts += len(diag["candidate_diagnostics"])
        partial = sum(
            1
            for diag in batch_diag
            if diag.get("kind") == "mechanical_insertion"
            and diag.get("source") == "partial_mechanical_fallback"
        )
        defer_now = _ids(_text(row, "defer_customer_ids"))
        new_defer = tuple(item for item in defer_now if item not in previous_defer)
        previous_defer = defer_now
        exhausted = EXHAUSTED_TOKEN in blob or EXHAUSTED_TOKEN in detail
        deferred = detail in DEFER_DETAILS
        failure_kinds = sorted(
            {
                str(diag.get("kind"))
                for diag in batch_diag
                if str(diag.get("kind")) in FAILURE_DIAG_KINDS
            }
        )
        print(
            f"       batch {index}: detail={detail}\n"
            f"                 status={status}  wall={wall:.1f}s  "
            f"candidate_attempts={attempts}  partial_fallback_insertions={partial}\n"
            f"                 newly_deferred={'|'.join(new_defer) or 'none'}  "
            f"failure_diagnostics={failure_kinds or 'none'}"
        )
        if deferred or exhausted or new_defer or failure_kinds:
            bad.append(
                f"batch {index}: "
                + ", ".join(
                    filter(
                        None,
                        (
                            f"detail={detail}" if deferred else "",
                            EXHAUSTED_TOKEN if exhausted else "",
                            f"deferred {'|'.join(new_defer)}" if new_defer else "",
                            f"diagnostics {failure_kinds}" if failure_kinds else "",
                        ),
                    )
                )
            )
    report.check("3   no defer / search-exhausted batch", not bad, *bad)


def check_full_evaluation(
    run: Run, report: Report, stream_dir: Path | None
) -> None:
    """4. Full evaluation feasible; totals match what the stream declares."""
    _section("CHECK 4 -- full evaluation feasible and declared totals")
    feasible_ok = True
    lines: list[str] = []
    for arm, row in sorted(run.raw.items()):
        flag = _bool(row.get("full_evaluation_feasible"))
        feasible_ok = feasible_ok and flag is True
        lines.append(f"{ARM_LABEL[arm]}: full_evaluation_feasible={flag}")
    report.check("4a  full evaluation feasible for every arm", feasible_ok, *lines)

    totals = {
        arm: (
            int(_num(row, "customers_total") or -1),
            round(_num(row, "demand_total_kg") or -1.0, 3),
        )
        for arm, row in run.raw.items()
    }
    agree = len(set(totals.values())) == 1
    report.check(
        "4b  the three arms agree on customer / demand totals",
        agree,
        *(f"{ARM_LABEL[a]}: {t[0]} customers, {t[1]:g} kg" for a, t in
          sorted(totals.items())),
    )

    declared = _stream_declaration(stream_dir)
    if declared is None:
        report.check(
            "4c  totals cross-checked against the stream directory",
            None,
            "no stream directory readable; pass --stream-dir to enable",
        )
    else:
        for line in declared["lines"]:
            print(f"       {line}")
        report.check(
            "4c  totals cross-checked against the stream directory",
            None,
            "the stream files declare events, not the served totals; the run's "
            "customers_total / demand_total_kg above come from "
            "backend.active_totals and already net out cancellations",
        )


def _stream_declaration(stream_dir: Path | None) -> dict[str, Any] | None:
    if stream_dir is None or not stream_dir.is_dir():
        return None
    lines: list[str] = [f"stream dir: {stream_dir}"]
    generation = _read_json(stream_dir / "generation.json")
    if isinstance(generation, dict):
        lines.append(
            f"generation.json: base_instance_id="
            f"{generation.get('base_instance_id')} "
            f"event_count={generation.get('event_count')} "
            f"types={generation.get('event_type_counts')}"
        )
        lines.append(
            f"generation.json: reception_window_second="
            f"{generation.get('reception_window_second')}"
        )
    events = stream_dir / "events.tsv"
    if events.exists():
        with events.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        added = sum(
            float(r.get("new_demand_kg") or 0.0)
            for r in rows
            if r.get("event_type") == "add"
        )
        cancelled = sum(
            float(r.get("old_demand_kg") or 0.0)
            for r in rows
            if r.get("event_type") == "cancel"
        )
        delta = sum(
            float(r.get("new_demand_kg") or 0.0) - float(r.get("old_demand_kg") or 0.0)
            for r in rows
            if r.get("event_type") == "demand_change"
        )
        lines.append(
            f"events.tsv: {len(rows)} events; "
            f"+{sum(1 for r in rows if r.get('event_type') == 'add')} adds "
            f"({added:g} kg), "
            f"-{sum(1 for r in rows if r.get('event_type') == 'cancel')} cancels "
            f"({cancelled:g} kg), demand_change net {delta:+g} kg"
        )
        lines.append(
            "events.tsv: net customer delta from the base instance = "
            f"{sum(1 for r in rows if r.get('event_type') == 'add') - sum(1 for r in rows if r.get('event_type') == 'cancel'):+d}"
        )
    # retired layout carries the stream inside the run package instead
    return {"lines": lines}


def check_options(run: Run, report: Report, expected_price: float | None) -> None:
    """5. Carbon price and backend options actually recorded."""
    _section("CHECK 5 -- carbon price and backend options")
    price = None
    for source, blob in (("metadata.json", run.metadata),
                         ("decision.json", run.decision)):
        if not isinstance(blob, dict):
            continue
        for key in ("carbon_price", "carbon_price_cny_per_kg"):
            if key in blob:
                price = (source, key, blob[key])
                break
        options = blob.get("backend_options")
        if isinstance(options, dict):
            for key in ("carbon_price", "carbon_price_cny_per_kg"):
                if key in options:
                    price = (f"{source}:backend_options", key, options[key])
    if price is None:
        report.check(
            "5a  carbon price recorded and equal to the expected value",
            None,
            "run_dynamic_experiment.write_output_package writes only "
            "contract_id / repetition_count / event_source / stop_rule / arms "
            "/ backend_options -- --carbon-price never reaches metadata.json",
            f"expected {expected_price} CNY/kg; NOT verifiable from the "
            "artefacts, only from the command line that launched the run",
        )
    else:
        source, key, value = price
        ok = expected_price is None or abs(float(value) - expected_price) <= 1e-9
        report.check(
            "5a  carbon price recorded and equal to the expected value",
            ok,
            f"{source}[{key}] = {value}; expected {expected_price}",
        )

    options = run.metadata.get("backend_options")
    if isinstance(options, dict) and options:
        report.check(
            "5b  backend options recorded",
            True,
            *(f"{key} = {value!r}" for key, value in sorted(options.items())),
        )
    else:
        report.check(
            "5b  backend options recorded",
            None,
            "metadata.json has no backend_options block, so the prefilter / "
            "partial_fallback / candidate_budget switches cannot be read back "
            "(the retired runner never wrote one; the current runner does, "
            "via run_dynamic_experiment._backend_options)",
            f"infeasible_candidate_policy in this package: "
            f"{run.metadata.get('infeasible_candidate_policy', 'absent')}",
        )


def check_termination(run: Run, report: Report) -> None:
    """6. Normal termination; no infeasible-candidate latch left standing."""
    _section("CHECK 6 -- termination")
    statuses = {
        arm: _text(row, "run_status") for arm, row in sorted(run.raw.items())
    }
    latched: list[str] = []
    for arm, status in statuses.items():
        if status and status != "completed":
            latched.append(f"{ARM_LABEL[arm]}: run_status={status}")
    # the current runner hard-codes run_status="completed" in
    # run_paired_pipeline, so also derive the latch from the batch ledger
    derived: list[str] = []
    for arm, rows in sorted(run.batches.items()):
        for row in rows:
            index = _text(row, "batch_index")
            status = _text(row, "decision_status")
            detail = _text(row, "decision_detail")
            if status == LATCH_STATUS:
                derived.append(f"{arm} batch {index}: decision_status={status}")
            if detail in DEFER_DETAILS:
                derived.append(f"{arm} batch {index}: decision_detail={detail}")
    reasons = list(run.metadata.get("acceptance_failure_reasons") or [])
    accepted = run.decision.get("accepted")
    evidence = [
        *(latched or ["run_status == 'completed' for every arm"]),
        "run_status is hard-coded 'completed' by the current runner "
        "(run_paired_pipeline) -- informational only, not evidence",
        *(derived or ["no latch or defer detail in the per-batch ledger"]),
        f"decision.json accepted={accepted} status={run.decision.get('status')}",
        *(f"recorded failure reason: {reason}" for reason in reasons),
    ]
    report.check(
        "6   termination normal, no infeasible_candidate latch",
        not latched and not derived and accepted is not False,
        *evidence,
    )


# --------------------------------------------------------------------------
# Paper table
# --------------------------------------------------------------------------


def route_adjustment_count(run: Run, arm: str) -> tuple[int | None, str]:
    """The paper's 在线调整次数.

    Retired runner ``_table10_rows`` (git 21d958db6,
    solver/scripts/run_dynamic_experiment.py:1247)::

        adjustments = changed if row["arm"] == ARM_DYNAMIC \
            else int(row["mechanical_insertion_count"]) \
            if row["arm"] == ARM_MECHANICAL else 0

    where (line 1238) ``changed = sum(bool(row["future_route_changed"])
    for row in table9_rows)`` and (line 1186, ``_validated_route_evidence``)
    ``future_route_changed = route_snapshot_before_json !=
    route_snapshot_after_json``, evaluated over the rolling arm's batch rows
    only.  That is: the number of trigger batches in which the future
    (unexecuted) plan actually moved.
    """
    if arm == STATIC:
        return 0, "static reference has no online batches (retired rule: 0)"
    if arm == SEQUENTIAL:
        value = _num(run.raw.get(SEQUENTIAL, {}), "mechanical_insertion_count")
        if value is None:
            return None, "mechanical_insertion_count absent from raw_runs.csv"
        return int(value), "raw_runs.mechanical_insertion_count"
    rows = run.batches.get(ROLLING, [])
    if not rows:
        return None, "no rolling batch rows"
    changed = 0
    missing = 0
    for row in rows:
        before = row.get("route_snapshot_before_json")
        after = row.get("route_snapshot_after_json")
        if before in (None, "") or after in (None, ""):
            missing += 1
            continue
        try:
            if json.loads(before) != json.loads(after):
                changed += 1
        except json.JSONDecodeError:
            missing += 1
    if missing:
        return changed, (
            f"batches whose future plan changed ({changed}); "
            f"{missing} batch(es) lacked route snapshots"
        )
    return changed, "batches whose future plan changed (before != after)"


def _route_level_rows(run: Run) -> None:
    _section("ROUTE-LEVEL ROW -- existing routes changed vs new routes opened")
    any_rows = False
    for arm in (ROLLING, SEQUENTIAL):
        rows = run.batches.get(arm, [])
        if not rows:
            continue
        print(f"       {ARM_LABEL[arm]}")
        for row in rows:
            index = _text(row, "batch_index")
            before = _snapshot_routes(row.get("route_snapshot_before_json", ""))
            after = _snapshot_routes(row.get("route_snapshot_after_json", ""))
            if not before and not after:
                print(f"         batch {index}: not derivable "
                      "(no route snapshots in this row)")
                continue
            any_rows = True
            before_by_id = {
                str(item.get("route_id")): item.get("node_sequence")
                for item in before
            }
            after_by_id = {
                str(item.get("route_id")): item.get("node_sequence")
                for item in after
            }
            opened = sorted(set(after_by_id) - set(before_by_id))
            closed = sorted(set(before_by_id) - set(after_by_id))
            modified = sorted(
                route_id
                for route_id in set(before_by_id) & set(after_by_id)
                if before_by_id[route_id] != after_by_id[route_id]
            )
            print(
                f"         batch {index}: existing routes changed="
                f"{len(modified)}  new routes opened={len(opened)}  "
                f"routes closed={len(closed)}"
            )
            if opened:
                print(f"                    opened: {', '.join(opened)}")
            if modified:
                print(f"                    changed: {', '.join(modified)}")
        if arm == SEQUENTIAL:
            print(
                "         note: on a deferred batch the sequential arm carries "
                "route_change_evidence over from the previous state "
                "(main3b_backend.py:829), so its snapshots can be stale"
            )
    print("       full_information_static_reference: N/A, no online batches")
    if not any_rows:
        print(
            "       NOT DERIVABLE for this run: the per-batch file carries no "
            "route_snapshot_before_json / route_snapshot_after_json columns"
        )


def print_table(run: Run) -> None:
    _section("PAPER TABLE  tab:dynamic")
    fields = (
        ("总成本 (CNY)", "total_cost", "{:.2f}"),
        ("总排放 (kg)", "total_emissions_kg", "{:.2f}"),
        ("总距离 (km)", "total_distance_km", "{:.2f}"),
        ("实际车辆数", "enabled_vehicles", "{:.0f}"),
    )
    order = (SEQUENTIAL, ROLLING, STATIC)
    header = f"{'指标':<16}" + "".join(f"{ARM_LABEL[a].split(' ')[0]:>34}" for a in order)
    print(header)
    values: dict[str, dict[str, float | None]] = {a: {} for a in order}
    for label, key, fmt in fields:
        cells = []
        for arm in order:
            value = _num(run.raw.get(arm, {}), key)
            values[arm][key] = value
            cells.append(fmt.format(value) if value is not None else "n/a")
        print(f"{label:<16}" + "".join(f"{c:>34}" for c in cells))

    adjustments = {arm: route_adjustment_count(run, arm) for arm in order}
    print(
        f"{'在线调整次数':<14}"
        + "".join(
            f"{(str(adjustments[a][0]) if adjustments[a][0] is not None else 'n/a'):>34}"
            for a in order
        )
    )
    for arm in order:
        print(f"                 {ARM_LABEL[arm]}: {adjustments[arm][1]}")

    for label, key, fmt in (
        ("完成客户数", "customers_served", "{:.0f}"),
        ("完成需求量 (kg)", "demand_served_kg", "{:.0f}"),
    ):
        cells = []
        for arm in order:
            value = _num(run.raw.get(arm, {}), key)
            values[arm][key] = value
            cells.append(fmt.format(value) if value is not None else "n/a")
        print(f"{label:<16}" + "".join(f"{c:>34}" for c in cells))
    cells = []
    for arm in order:
        row = run.raw.get(arm, {})
        served = _num(row, "customers_served")
        total = _num(row, "customers_total")
        unserved = _ids(_text(row, "unserved_customer_ids"))
        if unserved:
            cells.append(str(len(unserved)))
        elif served is not None and total is not None:
            cells.append(str(int(total - served)))
        else:
            cells.append("n/a")
    print(f"{'最终未服务订单数':<12}" + "".join(f"{c:>34}" for c in cells))

    print()
    print("相对变化 (rolling vs sequential):")
    for label, key in (
        ("总成本", "total_cost"),
        ("总排放", "total_emissions_kg"),
        ("总距离", "total_distance_km"),
        ("实际车辆数", "enabled_vehicles"),
    ):
        base = values[SEQUENTIAL].get(key)
        other = values[ROLLING].get(key)
        if base in (None, 0) or other is None:
            print(f"  {label}: n/a")
            continue
        print(
            f"  {label}: {other - base:+.2f} "
            f"({(other - base) / base * 100:+.2f}%)"
        )
    base = adjustments[SEQUENTIAL][0]
    other = adjustments[ROLLING][0]
    if base and other is not None:
        print(
            f"  在线调整次数: {other - base:+d} "
            f"({(other - base) / base * 100:+.2f}%)"
        )


# --------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("run_dir", type=Path, help="a finished dynamic run directory")
    parser.add_argument(
        "--stream-dir",
        type=Path,
        default=Path(
            "data/dynamic_streams/"
            "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd_mixed_events"
        ),
        help="event stream directory to read declared totals from",
    )
    parser.add_argument(
        "--expected-batches",
        type=int,
        default=None,
        help="expected number of trigger batches (default: as many as found)",
    )
    parser.add_argument(
        "--expected-carbon-price",
        type=float,
        default=0.2,
        help="carbon price the run was supposed to use, CNY/kg",
    )
    args = parser.parse_args(argv)

    try:
        run = Run(args.run_dir.resolve())
    except AuditError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    print("=" * 78)
    print("DYNAMIC RUN STRICT AUDIT")
    print("=" * 78)
    print(f"run dir        : {run.dir}")
    print(f"instance       : {run.instance_id}")
    print(f"per-batch file : {run.batch_file or '(none found)'}")
    print(f"arms found     : {', '.join(sorted(run.raw))}")
    print(
        "trigger batches: "
        + ", ".join(f"{arm}={run.batch_count(arm)}" for arm in sorted(run.batches))
    )
    print(f"contract_id    : {run.metadata.get('contract_id', 'absent')}")

    report = Report()
    stream = args.stream_dir
    if stream is not None and not stream.is_absolute():
        stream = Path(__file__).resolve().parents[2] / stream
    check_service(run, report)
    check_hgs_calls(run, report, args.expected_batches)
    check_batch_terminations(run, report)
    check_full_evaluation(run, report, stream)
    check_options(run, report, args.expected_carbon_price)
    check_termination(run, report)
    print_table(run)
    _route_level_rows(run)
    return report.summary()


if __name__ == "__main__":
    raise SystemExit(main())
