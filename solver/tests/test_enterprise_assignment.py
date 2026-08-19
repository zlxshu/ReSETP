from __future__ import annotations

import csv
from pathlib import Path

import pytest

from setp_solver.enterprise_assignment import (
    AssignmentContractError,
    load_enterprise_assignment,
    normalize_enterprise_depot_id,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
INSTANCE = (
    REPO_ROOT
    / "data/ChinaInstances/china81_final_suite_v2_20260815/instances/"
    / "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd"
)
INSTANCE_ID = "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd"


def test_registered_depot_assignment_is_normalized_and_balanced() -> None:
    with (INSTANCE / "orders.csv").open(newline="", encoding="utf-8-sig") as handle:
        customer_ids = [row["customer_id"] for row in csv.DictReader(handle)]

    assignment = load_enterprise_assignment(
        INSTANCE / "enterprise_assignment.csv",
        INSTANCE / "nodes.csv",
        expected_instance_id=INSTANCE_ID,
        expected_customer_ids=customer_ids,
    )

    assert normalize_enterprise_depot_id("way/1003511503") == "D_OSM_WAY_1003511503"
    assert len(assignment.customer_home_depot) == 50
    assert list(assignment.enterprise_by_customer.values()).count("ENT_A") == 25
    assert list(assignment.enterprise_by_customer.values()).count("ENT_B") == 25
    assert [assignment.enterprise_by_customer[customer_id] for customer_id in customer_ids[:5]] == [
        "ENT_A"
    ] * 5
    assert assignment.customer_home_depot["C001"] == "D_OSM_WAY_1003511503"
    assert assignment.customer_home_depot["C050"] == "D_OSM_WAY_1071205721"


def test_assignment_rejects_unknown_way_identity(tmp_path: Path) -> None:
    assignment_path = tmp_path / "enterprise_assignment.csv"
    assignment_path.write_text(
        "instance_id,customer_id,enterprise_id,enterprise_depot_osm,rule_id\n"
        "case,C001,ENT_A,way/999,P65\n",
        encoding="utf-8",
    )
    nodes_path = tmp_path / "nodes.csv"
    nodes_path.write_text(
        "node_id,node_type,source_identity\n"
        "D_OSM_WAY_1003511503,depot,way/1003511503\n",
        encoding="utf-8",
    )

    with pytest.raises(AssignmentContractError, match="ASSIGNMENT_CONTRACT_ERROR"):
        load_enterprise_assignment(
            assignment_path,
            nodes_path,
            expected_instance_id="case",
            expected_customer_ids=["C001"],
        )


def test_assignment_rejects_customer_set_mismatch(tmp_path: Path) -> None:
    assignment_path = tmp_path / "enterprise_assignment.csv"
    assignment_path.write_text(
        "instance_id,customer_id,enterprise_id,enterprise_depot_osm,rule_id\n"
        "case,C001,ENT_A,way/1003511503,P65\n",
        encoding="utf-8",
    )
    nodes_path = tmp_path / "nodes.csv"
    nodes_path.write_text(
        "node_id,node_type,source_identity\n"
        "D_OSM_WAY_1003511503,depot,way/1003511503\n",
        encoding="utf-8",
    )

    with pytest.raises(AssignmentContractError, match="customer set disagrees"):
        load_enterprise_assignment(
            assignment_path,
            nodes_path,
            expected_instance_id="case",
            expected_customer_ids=["C001", "C002"],
        )
