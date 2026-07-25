from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    ROOT
    / "baselines"
    / "e2_final_campaign_20260720"
    / "run_e2_result_strength_audit.py"
)
SPEC = spec_from_file_location("e2_result_strength_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def thresholds() -> dict:
    return {
        "instance_seed_pairs": {
            "maximum_losses_vs_each_single_view": 0,
            "minimum_strict_wins": {
                "HGS-F": 270,
                "HGS-E": 135,
                "HGS-M": 135,
            },
        },
        "instance_five_seed_means": {
            "maximum_losses_vs_each_single_view": 0,
            "minimum_strict_wins": {
                "HGS-F": 60,
                "HGS-E": 30,
                "HGS-M": 30,
            },
            "maximum_holm_adjusted_one_sided_wilcoxon_p": 0.01,
        },
        "overall_mean_cost_reduction_percent": {
            "minimum": {
                "HGS-F": 0.5,
                "HGS-E": 0.1,
                "HGS-M": 0.1,
            }
        },
        "nine_region_scale_layers": {
            "maximum_adverse_layers_vs_each_single_view": 0,
            "minimum_strictly_improved_layers": {
                "HGS-F": 7,
                "HGS-E": 6,
                "HGS-M": 6,
            },
        },
    }


def passing_metrics() -> tuple[dict, dict, dict, dict]:
    task = {
        arm: {"wins": wins, "ties": 405 - wins, "losses": 0}
        for arm, wins in {
            "HGS-F": 300,
            "HGS-E": 180,
            "HGS-M": 170,
        }.items()
    }
    instance = {
        arm: {
            "wins": wins,
            "ties": 81 - wins,
            "losses": 0,
            "holm_adjusted_p_value": 0.001,
        }
        for arm, wins in {
            "HGS-F": 70,
            "HGS-E": 45,
            "HGS-M": 40,
        }.items()
    }
    layer = {
        arm: {"wins": wins, "ties": 9 - wins, "losses": 0}
        for arm, wins in {
            "HGS-F": 9,
            "HGS-E": 7,
            "HGS-M": 6,
        }.items()
    }
    reductions = {"HGS-F": 0.8, "HGS-E": 0.2, "HGS-M": 0.15}
    return task, instance, layer, reductions


def test_result_strength_gate_passes_only_when_every_threshold_passes() -> None:
    task, instance, layer, reductions = passing_metrics()
    checks = MODULE.evaluate_gate(
        task,
        instance,
        layer,
        reductions,
        thresholds(),
    )
    assert checks
    assert all(checks.values())


def test_one_loss_or_weak_mechanism_gain_blocks_release() -> None:
    task, instance, layer, reductions = passing_metrics()
    task["HGS-M"]["losses"] = 1
    reductions["HGS-M"] = 0.099
    checks = MODULE.evaluate_gate(
        task,
        instance,
        layer,
        reductions,
        thresholds(),
    )
    assert checks["HGS-M:task_losses"] is False
    assert checks["HGS-M:mean_reduction"] is False
    assert not all(checks.values())


def test_holm_adjustment_is_monotone_in_sorted_p_values() -> None:
    adjusted = MODULE.holm_adjust(
        {"HGS-F": 0.001, "HGS-E": 0.02, "HGS-M": 0.01}
    )
    assert adjusted["HGS-F"] == 0.003
    assert adjusted["HGS-M"] == 0.02
    assert adjusted["HGS-E"] == 0.02
