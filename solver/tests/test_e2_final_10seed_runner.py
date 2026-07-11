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


def test_task_executes_frozen_code_but_reads_hash_locked_active_data(tmp_path) -> None:
    task = runner.build_task(runner.DEFAULT_EXECUTION_ROOT, tmp_path, runner.INSTANCES[0], "GA", 6, 200)
    assert task["repo_root"] == str(runner.REPO_ROOT)
    assert task["head"] == runner.FREEZE_COMMIT
