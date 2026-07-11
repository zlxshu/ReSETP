from __future__ import annotations

from baselines.e2_alns import e2_final_10seed_runner as runner


def _synthetic_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for instance_index, instance in enumerate(runner.INSTANCES):
        for algorithm_index, algorithm in enumerate(runner.ALGORITHMS):
            for seed in runner.SEEDS:
                rows.append(
                    {
                        "instance": instance,
                        "algorithm": algorithm,
                        "seed": seed,
                        "best_cost": 1000.0 + instance_index * 100.0 + algorithm_index * 10.0 + seed,
                        "elapsed_seconds": 1.0 + algorithm_index,
                        "gate_status": "OK",
                    }
                )
    return rows


def test_final_matrix_identity_and_reuse_contract() -> None:
    assert len(runner.INSTANCES) == 9
    assert len(runner.ALGORITHMS) == 9
    assert runner.SEEDS == tuple(range(1, 11))
    assert "ALNS-Wouda" not in runner.ALGORITHMS
    assert runner.ABLATION not in runner.ALGORITHMS

    reused_main, reused_ablation = runner.frozen_rows()
    manifest = runner.manifest_rows(reused_main, [])
    assert len(reused_main) == 225
    assert len(reused_ablation) == 45
    assert len(manifest) == 810
    assert sum(row["action"] == "REUSE" for row in manifest) == 225
    assert sum(row["action"] == "RUN" for row in manifest) == 585


def test_self_created_instance_table_does_not_invent_bks_or_gap() -> None:
    table, algorithm_summary, pairwise = runner.build_statistics(_synthetic_rows())
    assert len(table) == 81
    assert len(algorithm_summary) == 9
    assert len(pairwise) == 8
    assert all(int(row["independent_runs"]) == 10 for row in table)
    forbidden = {"external_bks", "external_bks_gap_pct", "best_gap_to_study_reference_pct", "avg_gap_to_study_reference_pct"}
    assert all(not forbidden.intersection(row) for row in table)


def test_expected_matrix_keys_are_the_exact_810_contract() -> None:
    expected = runner.expected_matrix_keys()
    assert len(expected) == 810
    assert expected == {
        (instance, algorithm, seed)
        for instance in runner.INSTANCES
        for algorithm in runner.ALGORITHMS
        for seed in runner.SEEDS
    }


def test_instance_ranking_uses_average_rank_for_exact_ties() -> None:
    rows = _synthetic_rows()
    for row in rows:
        if row["algorithm"] in runner.ALGORITHMS[:2]:
            row["best_cost"] = 1000.0 + runner.INSTANCES.index(str(row["instance"])) * 100.0
        elif row["algorithm"] == runner.ALGORITHMS[2]:
            row["best_cost"] = 1010.0 + runner.INSTANCES.index(str(row["instance"])) * 100.0
    _, algorithm_summary, _ = runner.build_statistics(rows)
    by_algorithm = {row["algorithm"]: row for row in algorithm_summary}
    assert by_algorithm[runner.ALGORITHMS[0]]["mean_rank_by_instance_avg"] == 1.5
    assert by_algorithm[runner.ALGORITHMS[1]]["mean_rank_by_instance_avg"] == 1.5
    assert by_algorithm[runner.ALGORITHMS[2]]["mean_rank_by_instance_avg"] == 3.0
    assert by_algorithm[runner.ALGORITHMS[0]]["best_instance_avg_count"] == 9
    assert by_algorithm[runner.ALGORITHMS[1]]["best_instance_avg_count"] == 9
    assert by_algorithm[runner.ALGORITHMS[2]]["best_instance_avg_count"] == 0


def test_holm_adjust_matches_step_down_monotone_rule() -> None:
    assert runner.holm_adjust([0.01, 0.04, 0.03]) == [0.03, 0.06, 0.06]


def test_task_executes_frozen_code_but_reads_hash_locked_active_data(tmp_path) -> None:
    task = runner.build_task(runner.DEFAULT_EXECUTION_ROOT, tmp_path, runner.INSTANCES[0], "GA", 6, 200)
    assert task["repo_root"] == str(runner.REPO_ROOT)
    assert task["head"] == runner.FREEZE_COMMIT


def test_representative_gate_accepts_executed_baseline_that_did_not_beat_warm_start() -> None:
    rows = [
        {
            "instance": runner.INSTANCES[4],
            "algorithm": "IWD",
            "seed": 6,
            "gate_status": "OK",
            "actual_evals": 4000,
            "violation_count": 0,
            "algorithm_specific_update_count": 0,
            "operator_counts_json": '{"iwd_construct_sa": 3810, "iwd_iteration_best_lns": 190}',
        }
    ]
    decision = runner.phase_decision(rows, expected=1, eval_budget=4000, representative=True)
    assert decision["verdict"] == "E2_10SEED_REPRESENTATIVE_READY"
    assert decision["algorithm_specific_update_rows"] == 0
    assert decision["algorithm_specific_operator_activity_rows"] == 1


def test_representative_gate_rejects_row_without_update_or_operator_ledger() -> None:
    rows = [
        {
            "instance": runner.INSTANCES[4],
            "algorithm": "IWD",
            "seed": 6,
            "gate_status": "OK",
            "actual_evals": 4000,
            "violation_count": 0,
            "algorithm_specific_update_count": 0,
            "operator_counts_json": "{}",
        }
    ]
    decision = runner.phase_decision(rows, expected=1, eval_budget=4000, representative=True)
    assert decision["verdict"] == "HALT_E2_10SEED_GATE"
