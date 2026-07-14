from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).with_name("build_e7_setp_integration_20260714.py")
SPEC = importlib.util.spec_from_file_location("build_e7_setp_integration", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_sealed_e7_values_are_loaded_without_cost_percent_comparison() -> None:
    values, emissions, participation, summary = MODULE.load_evidence()

    assert len(values) == len(emissions) == len(participation) == 5
    assert round(sum(row["net_benefit_change_percent"] for row in values) / 5, 3) == 1.118
    assert sum(row["net_benefit_change_percent"] > 0 for row in values) == 4
    assert round(
        sum(row["total_emission_intensity_change_percent"] for row in emissions) / 5,
        3,
    ) == 15.294
    assert sum(row["total_emission_intensity_change_percent"] > 0 for row in emissions) == 5
    assert sum(row["both_depots_no_worse"] for row in participation) == 2
    assert summary["value"]["all_pairs_had_different_realized_workload"] is True


def test_generated_tables_keep_one_result_family_per_table(tmp_path: Path) -> None:
    values, emissions, participation, _ = MODULE.load_evidence()
    original_tables = MODULE.TABLES
    MODULE.TABLES = tmp_path
    try:
        MODULE.write_value_table(values)
        MODULE.write_emission_table(emissions)
        MODULE.write_participation_table(participation)
    finally:
        MODULE.TABLES = original_tables

    value_table = (tmp_path / "e7_dynamic_value.tex").read_text(encoding="utf-8")
    emission_table = (tmp_path / "e7_dynamic_emissions.tex").read_text(encoding="utf-8")
    participation_table = (tmp_path / "e7_dynamic_participation.tex").read_text(
        encoding="utf-8"
    )
    assert "经营净收益" in value_table and "排放" not in value_table
    assert "排放强度" in emission_table and "收益比" not in emission_table
    assert "收益比" in participation_table and "排放" not in participation_table
