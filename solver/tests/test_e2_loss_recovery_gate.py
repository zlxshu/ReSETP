from __future__ import annotations

import inspect
from pathlib import Path


def test_loss_recovery_gate_uses_the_formal_e2_start_contract() -> None:
    from baselines.e2_alns import e2_loss_recovery_gate as gate

    source = inspect.getsource(gate._run_task)
    assert "make_shared_initial_solution(bundle, prices=prices)" in source
    assert "common_flip_preprocess=True" in source
    assert "introduce_ev=False" not in source


def test_loss_recovery_gate_keeps_a_bounded_nine_pair_matrix() -> None:
    from baselines.e2_alns import e2_loss_recovery_gate as gate

    pairs = (*gate.DEVELOPMENT_PAIRS, *gate.GUARD_PAIRS)
    algorithms = ("staged", "true_lns_middle", "LNS")
    tasks = [(instance, seed, algorithm) for instance, seed in pairs for algorithm in algorithms]
    assert len(pairs) == 9
    assert len(tasks) == 27
    assert len(set(tasks)) == 27
    assert set(gate.CANDIDATE_ALGORITHMS) == {
        "restarted",
        "true_lns_middle",
        "proportional_true_lns_middle",
    }


def test_loss_recovery_verifier_accepts_any_registered_short_gate_candidate() -> None:
    from baselines.e2_alns.e2_loss_recovery_verify import _is_short_gate_decision

    assert _is_short_gate_decision("RESTART_SHORT_GATE_REJECTED")
    assert _is_short_gate_decision("TRUE_LNS_MIDDLE_SHORT_GATE_PROMOTED")
    assert not _is_short_gate_decision("HALT_INCOMPLETE")


def test_unseen_seed_gate_matches_the_preregistered_matrix() -> None:
    from baselines.e2_alns import e2_loss_recovery_unseen_seed_gate as gate

    pairs = gate.validation_pairs()
    tasks = [(instance, seed, algorithm) for instance, seed in pairs for algorithm in ("staged", gate.CANDIDATE_ID, "LNS")]
    assert gate.LOSS_PRONE_SCALES == (15, 20, 50, 75, 100, 150)
    assert gate.UNSEEN_SEEDS == (6, 7, 8)
    assert gate.GUARD_PAIRS == (("L-main-threeshift-200c-01", 6),)
    assert len(pairs) == 19
    assert len(set(pairs)) == 19
    assert len(tasks) == 57
    assert len(set(tasks)) == 57


def test_unseen_seed_gate_promotes_only_after_contract_and_scientific_checks(tmp_path: Path) -> None:
    from baselines.e2_alns import e2_loss_recovery_unseen_seed_gate as gate

    rows = []
    for instance, seed in gate.validation_pairs():
        scale = int(instance.split("-")[-2].removesuffix("c"))
        lns_cost = 100.0
        staged_cost = 102.0 if scale in {15, 20, 50} else 98.0
        candidate_cost = 97.0
        for algorithm, cost in (
            ("staged", staged_cost),
            (gate.CANDIDATE_ID, candidate_cost),
            ("LNS", lns_cost),
        ):
            rows.append(
                {
                    "run_id": f"{instance}__seed{seed}__{algorithm}",
                    "instance": instance,
                    "seed": seed,
                    "algorithm": algorithm,
                    "status": "OK",
                    "actual_evals": 4000,
                    "violations": 0,
                    "cost": cost,
                }
            )
    metadata = {"expected_runs": 57, "eval_budget": 4000}
    decision = gate._finalize(tmp_path, rows, metadata)
    assert decision["verdict"] == "E2_UNSEEN_SEED_4000_PROMOTED"
    assert decision["loss_reduction_vs_staged"] >= 2
    assert decision["nonworse_loss_prone_scales"] >= 4

    rows[0]["actual_evals"] = 3999
    halted_dir = tmp_path / "halted"
    halted_dir.mkdir()
    halted = gate._finalize(halted_dir, rows, metadata)
    assert halted["verdict"] == "HALT_INCOMPLETE_OR_CONTRACT_FAILURE"
