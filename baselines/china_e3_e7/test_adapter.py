"""Low-cost regression tests for the China E3--E7 foundation adapter."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from baselines.china_e3_e7.adapter import ROOT, build_task_manifest, preflight
from baselines.china_e3_e7.charts import generate_figures
from baselines.china_e3_e7.contract import (
    CONTRACT_PATH,
    instance_rows,
    load_contract,
)
from baselines.china_e3_e7.e3_exhibits import (
    build_e3_cell_rows,
    build_e3_layer_rows,
)
from baselines.china_e3_e7.tables import render_tables
from baselines.china_e3_e7.statistics import (
    RAW_FIELDS,
    _cell_map_means,
    _normalise_formal_row,
    _pairing_violations,
    aggregate_raw,
    write_csv,
)


def test_manifest_is_china_only_and_formal_held() -> None:
    contract = load_contract(ROOT)
    assert CONTRACT_PATH.name == (
        "china_e3_formal_release_contract_v6_20260724.json"
    )
    assert contract["schema"].endswith(
        "formal-release-contract.v6"
    )
    assert contract["experiment_id"] == (
        "CHINA-E3-FORMAL-RELEASE-001"
    )
    manifest = build_task_manifest(contract, instance_rows(ROOT))
    assert manifest["status"] == "PLANNING_ONLY_FORMAL_SEARCH_HELD"
    assert manifest["formal_search_allowed"] is False
    assert manifest["search_evaluations"] == 0
    assert manifest["task_count_e3_to_e6"] == 3_240
    assert manifest["seed_expansion_projection"]["e3_to_e6_task_count_at_blind_cap"] == 4_536
    assert manifest["seed_expansion_projection"]["e7_task_count_at_blind_cap"] == 2_835
    assert manifest["e7_full_matrix_projection"]["task_count"] == 2_025
    assert manifest["e7_result_blind_gate_projection"]["task_count"] == 75
    assert all(task["algorithm_id"] == "MV-HGS-SP" for task in manifest["tasks"])
    assert all("uk" not in task["instance_id"].lower() for task in manifest["tasks"])


def test_preflight_loads_corrected_china81_without_search() -> None:
    result = preflight(ROOT)
    assert result["status"] == "PASS_FOUNDATION_PREFLIGHT_FORMAL_HELD"
    assert result["runtime_bundle_join"]["status"] == "PASS"
    assert result["runtime_bundle_join"]["loaded"] == 81
    assert result["runtime_bundle_join"]["errors"] == []
    assert result["runtime_bundle_join"]["search_evaluations"] == 0
    assert result["runtime_bundle_join"]["formal_search_allowed"] is False


def test_empty_raw_aggregate_is_not_a_scientific_result(tmp_path: Path) -> None:
    raw = tmp_path / "raw_runs.csv"
    raw.write_text(",".join(RAW_FIELDS) + "\n", encoding="utf-8")
    decision = aggregate_raw(raw, tmp_path / "aggregate", repo_root=ROOT)
    assert decision["status"] == "NO_FORMAL_RESULTS"
    assert decision["formal_rows"] == 0
    assert decision["search_evaluations"] == 0
    assert decision["scientific_claim_allowed"] is False


def test_independent_certificate_cannot_self_authorize_contract_id(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "raw_runs.csv"
    write_csv(
        raw,
        [
            {
                "record_type": "formal_run",
                "experiment_id": "MALICIOUS-SELF-DECLARED-ID",
                "family": "E3",
                "status": "complete",
            }
        ],
        fieldnames=[
            "record_type",
            "experiment_id",
            "family",
            "status",
        ],
    )
    out = tmp_path / "aggregate"
    out.mkdir()
    (out / "independent_recalc_certificate.json").write_text(
        json.dumps(
            {
                "status": "PASS_INDEPENDENT_RECALC",
                "contract_id": "MALICIOUS-SELF-DECLARED-ID",
                "raw_runs_sha256": hashlib.sha256(
                    raw.read_bytes()
                ).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    decision = aggregate_raw(raw, out, repo_root=ROOT)
    assert decision["independent_recalc_complete"] is False


def test_empty_aggregate_keeps_paper_tables_closed(tmp_path: Path) -> None:
    raw = tmp_path / "raw_runs.csv"
    raw.write_text(",".join(RAW_FIELDS) + "\n", encoding="utf-8")
    aggregate_dir = tmp_path / "aggregate"
    aggregate_raw(raw, aggregate_dir, repo_root=ROOT)
    decision = render_tables(aggregate_dir, tmp_path / "paper_tables", repo_root=ROOT)
    assert decision["status"] == "NO_TABLES"
    assert decision["independent_recalc_complete"] is False
    assert not list((tmp_path / "paper_tables").glob("*.tex"))


def test_raw_customer_size_field_reaches_cell_aggregation() -> None:
    rows = [
        {
            "family": "AUDIT",
            "arm": "control",
            "status": "complete",
            "feasible": "true",
            "region": "jjj",
            "customer_size": "10",
            "instance_id": f"cn-jjj-10c-{map_index:02d}-V2-LOCATIONS",
            "seed": "1",
            "total_cost": "100",
        }
        for map_index in range(1, 4)
    ]
    means, missing = _cell_map_means(
        rows,
        metric="total_cost",
        family_id="AUDIT",
        arm_id="control",
    )
    assert means == {"jjj__10": 100.0}
    assert missing == []


def test_disjoint_arm_seeds_fail_pairing_gate() -> None:
    rows = []
    for arm, seeds in (
        ("control", ("1", "2")),
        ("treatment", ("3", "4")),
    ):
        for map_index in range(1, 4):
            instance_id = (
                f"cn-jjj-10c-{map_index:02d}-V2-LOCATIONS"
            )
            for seed in seeds:
                rows.append(
                    {
                        "family": "AUDIT",
                        "arm": arm,
                        "status": "complete",
                        "region": "jjj",
                        "customer_size": "10",
                        "map_index": str(map_index),
                        "instance_id": instance_id,
                        "seed": seed,
                        "pair_id": (
                            f"AUDIT__{instance_id}__seed{seed}"
                        ),
                        "input_manifest_sha256": "same-input",
                        "contract_sha256": "same-contract",
                    }
                )
    violations = _pairing_violations(
        rows,
        family_id="AUDIT",
        control="control",
        treatment="treatment",
    )
    assert violations
    assert any(":arms=" in item for item in violations)


def test_e3_810_rows_reduce_to_27_paired_cells() -> None:
    rows = []
    for region_index, region in enumerate(("jjj", "prd", "cy")):
        for size_index, size in enumerate(
            (10, 15, 20, 25, 50, 75, 100, 150, 200)
        ):
            for map_index in (1, 2, 3):
                instance_id = (
                    f"cn-{region}-{size}c-{map_index:02d}-"
                    "V2-LOCATIONS"
                )
                for seed in (1, 2, 3, 4, 5):
                    pair = f"E3__{instance_id}__seed{seed}"
                    base_cost = (
                        1000.0
                        + 100.0 * region_index
                        + 10.0 * size_index
                        + map_index
                        + seed / 10.0
                    )
                    common = {
                        "family": "E3",
                        "instance_id": instance_id,
                        "region": region,
                        "customer_size": str(size),
                        "map_index": str(map_index),
                        "seed": str(seed),
                        "pair_id": pair,
                        "status": "complete",
                        "feasible": "true",
                        "input_manifest_sha256": "input",
                        "contract_sha256": "contract",
                        "spatiotemporal_crosswalk_sha256": "crosswalk",
                        "responsibility_map_sha256": "responsibility",
                        "initial_solution_sha256": "initial",
                        "algorithm_source_sha256": "algorithm",
                        "evaluator_source_sha256": "evaluator",
                        "go_decision_sha256": "go",
                    }
                    rows.extend(
                        (
                            {
                                **common,
                                "task_id": (
                                    f"{pair}__"
                                    "status_quo_responsibility"
                                ),
                                "arm": (
                                    "status_quo_responsibility"
                                ),
                                "arm_id": (
                                    "status_quo_responsibility"
                                ),
                                "total_cost": str(base_cost),
                            },
                            {
                                **common,
                                "task_id": (
                                    f"{pair}__"
                                    "optimized_responsibility_cooperation"
                                ),
                                "arm": (
                                    "optimized_responsibility_cooperation"
                                ),
                                "arm_id": (
                                    "optimized_responsibility_cooperation"
                                ),
                                "total_cost": str(base_cost - 10.0),
                            },
                        )
                    )
    assert len(rows) == 810
    violations = _pairing_violations(
        rows,
        family_id="E3",
        control="status_quo_responsibility",
        treatment="optimized_responsibility_cooperation",
    )
    assert violations == []
    control, control_missing = _cell_map_means(
        rows,
        metric="total_cost",
        family_id="E3",
        arm_id="status_quo_responsibility",
        expected_seeds={"1", "2", "3", "4", "5"},
    )
    treatment, treatment_missing = _cell_map_means(
        rows,
        metric="total_cost",
        family_id="E3",
        arm_id="optimized_responsibility_cooperation",
        expected_seeds={"1", "2", "3", "4", "5"},
    )
    assert control_missing == []
    assert treatment_missing == []
    assert len(control) == len(treatment) == 27
    assert all(
        abs(control[cell] - treatment[cell] - 10.0) < 1.0e-12
        for cell in control
    )


def test_infeasible_cost_is_not_aggregated_without_rule() -> None:
    rows = [
        {
            "family": "AUDIT",
            "arm": "control",
            "status": "complete",
            "feasible": "false",
            "region": "jjj",
            "customer_size": "10",
            "instance_id": "cn-jjj-10c-01-V2-LOCATIONS",
            "seed": "1",
            "total_cost": "1",
        }
    ]
    means, missing = _cell_map_means(
        rows,
        metric="total_cost",
        family_id="AUDIT",
        arm_id="control",
    )
    assert means == {}
    assert any(
        "infeasible_without_registered_rule" in item
        for item in missing
    )


def test_formal_e3_pass_row_normalises_to_common_schema() -> None:
    row = _normalise_formal_row(
        {
            "task_id": (
                "E3__cn-prd-50c-02-V2-LOCATIONS__seed1__"
                "status_quo_responsibility"
            ),
            "instance_id": "cn-prd-50c-02-V2-LOCATIONS",
            "arm_id": "status_quo_responsibility",
            "status": "PASS",
            "customer_count": "50",
            "total_emissions_kg": "12.5",
            "elapsed_seconds": "7.0",
            "complete_candidate_attempts": "80",
        }
    )
    assert row["record_type"] == "formal_run"
    assert row["family"] == "E3"
    assert row["arm"] == "status_quo_responsibility"
    assert row["status"] == "complete"
    assert row["feasible"] == "true"
    assert row["customer_size"] == "50"
    assert row["map_index"] == "2"
    assert row["total_emissions"] == "12.5"
    assert row["runtime_seconds"] == "7.0"
    assert row["search_evaluations"] == "80"


def test_formal_e3_pair_requires_extended_hash_identity() -> None:
    common = {
        "family": "E3",
        "instance_id": "cn-prd-50c-02-V2-LOCATIONS",
        "region": "prd",
        "customer_size": "50",
        "map_index": "2",
        "seed": "1",
        "pair_id": "E3__cn-prd-50c-02-V2-LOCATIONS__seed1",
        "status": "PASS",
        "input_manifest_sha256": "input",
        "contract_sha256": "contract",
        "spatiotemporal_crosswalk_sha256": "crosswalk",
        "responsibility_map_sha256": "responsibility",
        "initial_solution_sha256": "initial",
        "algorithm_source_sha256": "algorithm",
        "evaluator_source_sha256": "evaluator",
        "go_decision_sha256": "go",
    }
    rows = [
        {
            **common,
            "arm": arm,
            "arm_id": arm,
        }
        for arm in (
            "status_quo_responsibility",
            "optimized_responsibility_cooperation",
        )
    ]
    assert _pairing_violations(
        rows,
        family_id="E3",
        control="status_quo_responsibility",
        treatment="optimized_responsibility_cooperation",
    ) == []
    rows[1]["go_decision_sha256"] = ""
    violations = _pairing_violations(
        rows,
        family_id="E3",
        control="status_quo_responsibility",
        treatment="optimized_responsibility_cooperation",
    )
    assert any("go_decision_sha256=missing" in item for item in violations)


def test_cell_aggregation_requires_preregistered_common_seeds() -> None:
    rows = [
        {
            "family": "AUDIT",
            "arm": "control",
            "status": "complete",
            "feasible": "true",
            "region": "jjj",
            "customer_size": "10",
            "instance_id": (
                f"cn-jjj-10c-{map_index:02d}-V2-LOCATIONS"
            ),
            "seed": str(seed),
            "total_cost": "100",
        }
        for map_index in range(1, 4)
        for seed in range(1, 5)
    ]
    means, missing = _cell_map_means(
        rows,
        metric="total_cost",
        family_id="AUDIT",
        arm_id="control",
        expected_seeds={"1", "2", "3", "4", "5"},
    )
    assert means == {}
    assert any(":expected=['1', '2', '3', '4', '5']" in item for item in missing)


def test_e3_only_complete_raw_does_not_require_unstarted_families(
    tmp_path: Path,
) -> None:
    contract = load_contract(ROOT)
    rows = []
    for region in contract["data"]["regions"]:
        for size in contract["data"]["customer_sizes"]:
            for map_index in range(1, 4):
                instance_id = (
                    f"cn-{region}-{size}c-{map_index:02d}-"
                    "V2-LOCATIONS"
                )
                for seed in range(1, 6):
                    common = {
                        "record_type": "formal_run",
                        "experiment_id": (
                            "CHINA-E3-FORMAL-RELEASE-001"
                        ),
                        "family": "E3",
                        "instance_id": instance_id,
                        "region": region,
                        "customer_size": str(size),
                        "map_index": str(map_index),
                        "seed": str(seed),
                        "pair_id": (
                            f"E3__{instance_id}__seed{seed}"
                        ),
                        "status": "PASS",
                        "feasible": "true",
                        "cross_site_service_count": "0",
                        "service_level": "1",
                        "total_emissions": "10",
                        "search_evaluations": "80",
                        "input_manifest_sha256": "input",
                        "contract_sha256": "contract",
                        "spatiotemporal_crosswalk_sha256": "crosswalk",
                        "responsibility_map_sha256": "responsibility",
                        "initial_solution_sha256": "initial",
                        "algorithm_source_sha256": "algorithm",
                        "evaluator_source_sha256": "evaluator",
                        "go_decision_sha256": "go",
                    }
                    for arm, cost, cross_site, service, emissions in (
                        (
                            "status_quo_responsibility",
                            100,
                            0,
                            0.99,
                            10,
                        ),
                        (
                            "optimized_responsibility_cooperation",
                            99,
                            1,
                            1.0,
                            9,
                        ),
                    ):
                        rows.append(
                            {
                                **common,
                                "task_id": (
                                    f"E3__{instance_id}__seed{seed}"
                                    f"__{arm}"
                                ),
                                "arm": arm,
                                "arm_id": arm,
                                "total_cost": str(cost),
                                "cross_site_service_count": str(
                                    cross_site
                                ),
                                "service_level": str(service),
                                "total_emissions": str(emissions),
                            }
                        )
    raw = tmp_path / "raw_runs.csv"
    write_csv(
        raw,
        rows,
        fieldnames=sorted(
            {key for row in rows for key in row}
        ),
    )
    decision = aggregate_raw(
        raw,
        tmp_path / "aggregate",
        repo_root=ROOT,
    )
    assert decision["status"] == "AGGREGATE_READY_FOR_REVIEW"
    assert decision["formal_rows"] == 810
    assert decision["active_families"] == ["E3"]
    assert decision["missing_or_incomplete"] == []
    aggregate_dir = tmp_path / "aggregate"
    released = dict(decision)
    released["independent_recalc_complete"] = True
    (aggregate_dir / "decision.json").write_text(
        json.dumps(released),
        encoding="utf-8",
    )
    (
        aggregate_dir / "independent_recalc_certificate.json"
    ).write_text(
        json.dumps(
            {
                "status": "PASS_INDEPENDENT_RECALC",
                "contract_id": "CHINA-E3-FORMAL-RELEASE-001",
                "raw_runs_sha256": hashlib.sha256(
                    raw.read_bytes()
                ).hexdigest(),
                "task_count": 810,
                "pair_count": 405,
            }
        ),
        encoding="utf-8",
    )
    cells = build_e3_cell_rows(rows)
    layers = build_e3_layer_rows(cells)
    assert len(cells) == 27
    assert len(layers) == 10
    assert all(
        row["cost_reduction_percent"] == 1.0
        for row in cells
    )
    table_decision = render_tables(
        aggregate_dir,
        tmp_path / "tables",
        repo_root=ROOT,
    )
    aggregate_decision = json.loads(
        (aggregate_dir / "decision.json").read_text(encoding="utf-8")
    )
    assert aggregate_decision["holm_status"] == (
        "PENDING_UNTIL_ALL_FIVE_PRIMARY_FAMILIES_EXIST"
    )
    with (aggregate_dir / "summary.csv").open(
        newline="",
        encoding="utf-8",
    ) as handle:
        e3_summary_rows = list(csv.DictReader(handle))
    e3_primary = next(
        row
        for row in e3_summary_rows
        if row["family"] == "E3"
        and row["contrast_role"] == "primary"
        and row["metric"] == "total_cost"
    )
    assert e3_primary["holm_adjusted_p"] == ""
    assert table_decision["status"] == "TABLE_REVIEW_REQUIRED"
    assert (tmp_path / "tables/e3_summary.tex").is_file()
    assert (
        "TABLE_GENERATED_FROM_27_PAIRED_CELLS"
        in {
            item["status"]
            for item in table_decision["families"]
        }
    )
    table_text = (
        tmp_path / "tables/e3_summary.tex"
    ).read_text(encoding="utf-8")
    assert r"\multicolumn{2}{c}{总成本(元)}" in table_text
    assert r"\multirow{3}{*}{京津冀}" in table_text
    assert not (tmp_path / "tables/e4_summary.tex").exists()
    figure_decision = generate_figures(
        raw,
        tmp_path / "figures",
        repo_root=ROOT,
        aggregate_dir=aggregate_dir,
    )
    assert figure_decision["status"] == "FIGURE_REVIEW_REQUIRED"
    assert (
        tmp_path / "figures/e3_responsibility.pdf"
    ).is_file()
    assert (
        tmp_path / "figures/e3_responsibility.png"
    ).is_file()
