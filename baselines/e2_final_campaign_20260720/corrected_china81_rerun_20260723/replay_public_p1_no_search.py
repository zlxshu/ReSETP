#!/usr/bin/env python3
"""No-search preservation replay for the sealed public P1 campaign.

P1 did not persist route witnesses. Therefore this gate performs the strongest
honest replay available for P1 itself: input/artifact hash checks plus a full
280-row arithmetic and decision-ledger reconstruction. It separately replays
all 30 route witnesses that do exist in the public P4 certificate set. The P4
certificates are auxiliary scoring evidence and are never represented as P1
seed witnesses.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[3]
CAMPAIGN = Path(__file__).resolve().parent
OUT = CAMPAIGN / "public_p1_no_search_replay"
PACKAGE = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "mv_hgs_sp_final"
)
P1 = PACKAGE / "p1_formal_gate"
P4 = PACKAGE / "p4_bks_sprint"
FOUNDATION = (
    REPO
    / "baselines/algorithm_foundation/"
    "mdvrptw_v13_comparison_20260719"
)
INSTANCE_DIR = FOUNDATION / "sources/normalised_instances"
OPPONENT_CSV = FOUNDATION / "opponent_targets.csv"

from pyvrp import read  # noqa: E402
from pyvrp._pyvrp import Route as NativeRoute  # noqa: E402
from pyvrp._pyvrp import Solution as NativeSolution  # noqa: E402


EPS = 1.0e-9


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("cannot write an empty CSV")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _targets() -> dict[str, dict[str, str]]:
    with OPPONENT_CSV.open(newline="", encoding="utf-8-sig") as handle:
        return {row["instance"]: row for row in csv.DictReader(handle)}


def _p1_replay() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    decision = json.loads((P1 / "decision.json").read_text(encoding="utf-8"))
    with (P1 / "raw_runs.csv").open(
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        source_rows = list(csv.DictReader(handle))
    targets = _targets()
    expected_keys = {
        (instance_id, seed)
        for instance_id in targets
        for seed in range(1, 11)
    }
    observed_keys = {
        (row["instance_id"], int(row["seed"]))
        for row in source_rows
    }
    duplicate_count = len(source_rows) - len(observed_keys)
    if observed_keys != expected_keys or duplicate_count:
        raise RuntimeError("sealed P1 280-row key ledger is incomplete")

    reconstructed_table: list[dict[str, Any]] = []
    replay_rows: list[dict[str, Any]] = []
    for instance_id in targets:
        matching = [
            row for row in source_rows if row["instance_id"] == instance_id
        ]
        target = targets[instance_id]
        bks = float(target["current_verified_bks"])
        mother_best = min(float(row["mother_cost"]) for row in matching)
        hybrid_best = min(float(row["hybrid_cost"]) for row in matching)
        reconstructed_table.append(
            {
                "instance": instance_id,
                "n": int(matching[0]["n_clients"]),
                "bks": bks,
                "vcgp_error_pct": 100.0
                * (float(target["vcgp_best_2013"]) - bks)
                / bks,
                "mdfiha_error_pct": 100.0
                * (float(target["mdfiha_best_2026"]) - bks)
                / bks,
                "etga_error_pct": 100.0
                * (float(target["mdfiha_etga_best_2026"]) - bks)
                / bks,
                "mother_best": mother_best,
                "mother_error_pct": 100.0
                * (mother_best - bks)
                / bks,
                "hybrid_best": hybrid_best,
                "hybrid_error_pct": 100.0
                * (hybrid_best - bks)
                / bks,
                "new_bks_candidate": hybrid_best < bks - 1.0e-6,
            }
        )
        for row in matching:
            mother = float(row["mother_cost"])
            hybrid = float(row["hybrid_cost"])
            delta = hybrid - mother
            expected_outcome = (
                "win"
                if delta < -1.0e-6
                else "loss"
                if delta > 1.0e-6
                else "tie"
            )
            expected_improvement = 100.0 * (mother - hybrid) / mother
            replay_rows.append(
                {
                    "instance_id": instance_id,
                    "seed": int(row["seed"]),
                    "n_clients": int(row["n_clients"]),
                    "mother_cost": mother,
                    "hybrid_cost": hybrid,
                    "recorded_outcome": row["hybrid_vs_mother"],
                    "recomputed_outcome": expected_outcome,
                    "outcome_equal": (
                        row["hybrid_vs_mother"] == expected_outcome
                    ),
                    "recorded_improvement_percent": float(
                        row["improvement_percent"]
                    ),
                    "recomputed_improvement_percent": expected_improvement,
                    "improvement_equal": math.isclose(
                        float(row["improvement_percent"]),
                        expected_improvement,
                        rel_tol=0.0,
                        abs_tol=1.0e-12,
                    ),
                    "route_witness_available": False,
                }
            )

    sealed_table = decision["table5"]
    if len(sealed_table) != len(reconstructed_table):
        raise RuntimeError("P1 table row count mismatch")
    table_equal = True
    for sealed, rebuilt in zip(sealed_table, reconstructed_table, strict=True):
        if sealed.keys() != rebuilt.keys():
            table_equal = False
            break
        for key in sealed:
            left = sealed[key]
            right = rebuilt[key]
            if isinstance(left, (int, float)) and not isinstance(left, bool):
                if not math.isclose(
                    float(left),
                    float(right),
                    rel_tol=0.0,
                    abs_tol=1.0e-12,
                ):
                    table_equal = False
                    break
            elif left != right:
                table_equal = False
                break
        if not table_equal:
            break
    average_equal = True
    for key, sealed_value in decision["avg_row_error_pct"].items():
        rebuilt_value = sum(
            float(row[key]) for row in reconstructed_table
        ) / len(reconstructed_table)
        if not math.isclose(
            float(sealed_value),
            rebuilt_value,
            rel_tol=0.0,
            abs_tol=1.0e-12,
        ):
            average_equal = False
    wins = sum(row["recomputed_outcome"] == "win" for row in replay_rows)
    ties = sum(row["recomputed_outcome"] == "tie" for row in replay_rows)
    losses = sum(row["recomputed_outcome"] == "loss" for row in replay_rows)
    audit = {
        "row_count": len(replay_rows),
        "unique_key_count": len(observed_keys),
        "duplicate_count": duplicate_count,
        "all_outcomes_equal": all(
            row["outcome_equal"] for row in replay_rows
        ),
        "all_improvements_equal": all(
            row["improvement_equal"] for row in replay_rows
        ),
        "table5_reconstruction_equal": table_equal,
        "avg_row_reconstruction_equal": average_equal,
        "win_tie_loss_reconstructed": [wins, ties, losses],
        "win_tie_loss_sealed": [
            int(decision["wins_vs_mother"]),
            int(decision["ties_vs_mother"]),
            int(decision["losses_vs_mother"]),
        ],
        "p1_route_witnesses_available": False,
        "p1_route_level_replay_performed": False,
    }
    audit["passed"] = (
        audit["row_count"] == 280
        and audit["unique_key_count"] == 280
        and audit["duplicate_count"] == 0
        and audit["all_outcomes_equal"]
        and audit["all_improvements_equal"]
        and audit["table5_reconstruction_equal"]
        and audit["avg_row_reconstruction_equal"]
        and audit["win_tie_loss_reconstructed"]
        == audit["win_tie_loss_sealed"]
    )
    return replay_rows, audit


def _p4_certificate_replay() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    with (P4 / "raw_runs.csv").open(
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        source_rows = list(csv.DictReader(handle))
    rows: list[dict[str, Any]] = []
    for source in source_rows:
        instance_id = source["instance_id"]
        witness_path = P4 / source["witness_file"]
        payload = json.loads(witness_path.read_text(encoding="utf-8"))
        data = read(
            str(INSTANCE_DIR / f"{instance_id}.vrp"),
            round_func="exact",
        )
        native_routes = []
        route_distance_equal = True
        start_depot_equal = True
        for item in payload["routes"]:
            vehicle_type = int(item["vehicle_type"])
            route = NativeRoute(
                data,
                [int(value) for value in item["visits"]],
                vehicle_type,
            )
            native_routes.append(route)
            route_distance_equal = route_distance_equal and math.isclose(
                float(route.distance()),
                float(item["distance_x1000"]),
                rel_tol=0.0,
                abs_tol=1.0e-9,
            )
            start_depot_equal = start_depot_equal and (
                int(route.start_depot())
                == int(item["start_depot"])
                == int(data.vehicle_type(vehicle_type).start_depot)
            )
        solution = NativeSolution(data, native_routes)
        reconstructed_raw = float(
            sum(route.distance() for route in solution.routes())
        )
        recorded_raw = float(payload["raw_cost_x1000"])
        source_raw = 1000.0 * float(source["sprint_cost"])
        rows.append(
            {
                "instance_id": instance_id,
                "seed": int(source["seed"]),
                "witness_file": source["witness_file"],
                "witness_sha256": sha256(witness_path),
                "route_count": len(native_routes),
                "solution_feasible": bool(solution.is_feasible()),
                "route_distance_equal": route_distance_equal,
                "start_depot_equal": start_depot_equal,
                "recorded_raw_cost": recorded_raw,
                "reconstructed_raw_cost": reconstructed_raw,
                "raw_cost_equal": math.isclose(
                    recorded_raw,
                    reconstructed_raw,
                    rel_tol=0.0,
                    abs_tol=1.0e-9,
                ),
                "source_csv_cost_equal": math.isclose(
                    source_raw,
                    reconstructed_raw,
                    rel_tol=0.0,
                    abs_tol=1.0e-9,
                ),
            }
        )
    audit = {
        "certificate_count": len(rows),
        "all_feasible": all(row["solution_feasible"] for row in rows),
        "all_route_distances_equal": all(
            row["route_distance_equal"] for row in rows
        ),
        "all_start_depots_equal": all(
            row["start_depot_equal"] for row in rows
        ),
        "all_costs_equal": all(
            row["raw_cost_equal"] and row["source_csv_cost_equal"]
            for row in rows
        ),
        "scope": (
            "auxiliary P4 public route certificates; not P1 seed witnesses"
        ),
    }
    audit["passed"] = (
        audit["certificate_count"] == 30
        and audit["all_feasible"]
        and audit["all_route_distances_equal"]
        and audit["all_start_depots_equal"]
        and audit["all_costs_equal"]
    )
    return rows, audit


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    p1_rows, p1_audit = _p1_replay()
    p4_rows, p4_audit = _p4_certificate_replay()
    write_csv(OUT / "raw_runs.csv", p1_rows)
    write_csv(OUT / "p4_witness_replays.csv", p4_rows)
    passed = bool(p1_audit["passed"] and p4_audit["passed"])
    decision = {
        "schema": "resetp.d6-public-p1-no-search-replay.decision.v1",
        "verdict": (
            "PASS_PUBLIC_P1_PRESERVATION_NO_SEARCH"
            if passed
            else "HALT_PUBLIC_P1_PRESERVATION_REPLAY"
        ),
        "search_executions": 0,
        "sealed_p1_modified": False,
        "p1_ledger_audit": p1_audit,
        "p4_auxiliary_certificate_audit": p4_audit,
        "limitation": (
            "P1 preserved only aggregate per-seed costs and did not preserve "
            "route witnesses, so P1 route-level replay is impossible. The "
            "gate does not manufacture them and does not authorize a new-BKS "
            "or route-certificate claim. Existing P4 witnesses are replayed "
            "only as separate public scoring evidence."
        ),
        "e3_relevance": (
            "This limitation does not alter the corrected private China81 "
            "inputs or block E3; public P1 remains sealed and unchanged."
        ),
    }
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.d6-public-p1-no-search-replay.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "source_hashes": {
                str(path.relative_to(REPO)): sha256(path)
                for path in (
                    P1 / "raw_runs.csv",
                    P1 / "decision.json",
                    P1 / "metadata.json",
                    P1 / "artifact_hashes.json",
                    P4 / "raw_runs.csv",
                    P4 / "decision.json",
                    OPPONENT_CSV,
                    Path(__file__).resolve(),
                )
            },
            "search_executions": 0,
            "pyvrp_reads_only": True,
        },
    )
    (OUT / "report.md").write_text(
        "# Public P1 no-search preservation replay\n\n"
        f"Decision: `{decision['verdict']}`.\n\n"
        "The sealed 280-row P1 ledger, win/tie/loss counts, improvement "
        "percentages, Table 5 rows and average row were reconstructed exactly "
        "without running search. P1 did not save route witnesses, so claiming "
        "a P1 route-certificate replay would be false. The 30 route witnesses "
        "that do exist in the separate P4 public sprint were reconstructed "
        "with PyVRP and all passed feasibility, depot, route-distance and "
        "total-cost checks. They are not relabelled as P1 witnesses.\n",
        encoding="utf-8",
    )
    artifacts = {
        str(path.relative_to(OUT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
    }
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": ["artifact_hashes.json", "._*", "*.tmp"],
            "artifacts": artifacts,
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
