from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
PANEL = HERE / "formal_panel_20260801"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_formal_panel_preserves_rows_and_reproduces_results() -> None:
    with (PANEL / "raw_runs.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    source_rows = []
    members = sorted(path for path in PANEL.iterdir() if path.is_dir())
    for member in members:
        with (member / "raw_runs.csv").open(encoding="utf-8", newline="") as handle:
            source_rows.extend(csv.DictReader(handle))

    canonical = lambda row: json.dumps(row, sort_keys=True)
    assert sorted(map(canonical, rows)) == sorted(map(canonical, source_rows))

    paired: dict[tuple[str, int], dict[str, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        paired[(row["instance_id"], int(row["seed"]))][row["objective_mode"]] = row
    assert len(rows) == 90
    assert len(paired) == 30
    assert all(set(unit) == {"COST_ONLY", "COST_PLUS_CARBON", "PURE_CARBON"} for unit in paired.values())

    expected = {
        "COST_PLUS_CARBON": (-2.679143431232458, 0.0000448066640604612, -0.7022608671934595, 2),
        "PURE_CARBON": (-13.935352970128326, 2.4865635350362165, 307.4133802850394, 19),
    }
    for mode, (emissions, cost, electricity, changed) in expected.items():
        def mean_change(field: str) -> float:
            values = []
            for unit in paired.values():
                base = float(unit["COST_ONLY"][field])
                values.append(100.0 * (float(unit[mode][field]) - base) / base)
            return sum(values) / len(values)

        assert abs(mean_change("system_emissions_kg") - emissions) < 1.0e-12
        assert abs(mean_change("operating_cost_cny") - cost) < 1.0e-12
        assert abs(mean_change("electricity_cost_cny") - electricity) < 1.0e-12
        assert sum(
            unit[mode]["typed_path_hash"] != unit["COST_ONLY"]["typed_path_hash"]
            for unit in paired.values()
        ) == changed

    metadata = json.loads((PANEL / "metadata.json").read_text(encoding="utf-8"))
    for member in members:
        assert sha256(member / "artifact_hashes.json") == metadata[
            "source_member_manifest_sha256"
        ][member.name]
    manifest = json.loads((PANEL / "artifact_hashes.json").read_text(encoding="utf-8"))[
        "artifacts"
    ]
    assert all(sha256(PANEL / name) == expected_hash for name, expected_hash in manifest.items())
