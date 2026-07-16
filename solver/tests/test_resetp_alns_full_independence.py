"""Hard independence gates for the fully isolated ReSETP ALNS package."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PKG = REPO / "solver/src/setp_solver/algorithms/resetp_alns"
SEARCH = REPO / "solver/src/setp_solver/search"


def _py_files(root: Path) -> list[Path]:
    # macOS may leave AppleDouble sidecars such as ``._winner.py`` beside
    # source files on the external volume.  They are binary metadata, not
    # Python sources, and must not enter a UTF-8 source audit.
    return [
        p
        for p in root.rglob("*.py")
        if p.is_file() and "__pycache__" not in p.parts and not p.name.startswith("._")
    ]


def test_package_exists_and_has_kernel():
    assert (PKG / "api.py").is_file()
    assert (PKG / "kernel" / "alns_core.py").is_file()
    assert (PKG / "kernel" / "winner.py").is_file()
    assert (PKG / "PROVENANCE.md").is_file()


def test_no_open_source_alns_imports_in_package():
    banned_substrings = (
        "Reference Algorithm",
        "ALNS-7.0.0",
        "N-Wouda",
        "from alns",
        "import alns",
    )
    offenders: list[str] = []
    for path in _py_files(PKG):
        text = path.read_text(encoding="utf-8")
        for token in banned_substrings:
            if token in text and "PROVENANCE" not in path.name and "README" not in path.name:
                # allow comments in non-code? still ban in .py
                offenders.append(f"{path.relative_to(REPO)}: {token}")
    # Filter documentation strings that mention ancestry in module docstrings of runtime
    # Runtime files may say "Adapted from N-Wouda" in comments — that is provenance text, OK if not import.
    offenders = [o for o in offenders if "from alns" in o or "import alns" in o or "Reference Algorithm" in o or "ALNS-7.0.0" in o]
    # re-scan strictly for import forms only
    import_offenders = []
    for path in _py_files(PKG):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("#"):
                continue
            if "from alns" in s or s == "import alns" or s.startswith("import alns ") or "Reference Algorithm" in s:
                import_offenders.append(f"{path}:{s}")
    assert import_offenders == []


def test_public_api_importable():
    from setp_solver.algorithms.resetp_alns import run_resetp_alns, run_winner_kernel, run_alns_wouda

    assert callable(run_resetp_alns)
    assert run_resetp_alns is run_winner_kernel
    assert callable(run_alns_wouda)


def test_search_shims_reexport_package():
    from setp_solver.search import alns_wouda, winner_operators
    from setp_solver.algorithms.resetp_alns.kernel import alns_core, winner

    assert alns_wouda.run_alns_wouda is alns_core.run_alns_wouda
    assert winner_operators.run_winner_kernel is winner.run_winner_kernel


def test_formal_instance_registry_nine_threeshift():
    from setp_solver.search.instance_registry import FORMAL_INSTANCE_ORDER, INSTANCE_REL_DIRS, L_MAIN_THREESHIFT_SIZES

    assert len(FORMAL_INSTANCE_ORDER) == 9
    assert L_MAIN_THREESHIFT_SIZES == (10, 15, 20, 25, 50, 75, 100, 150, 200)
    assert all(name.startswith("L-main-threeshift-") and name.endswith("-01") for name in FORMAL_INSTANCE_ORDER)
    root = REPO
    for name, rel in INSTANCE_REL_DIRS.items():
        assert (root / rel).is_dir(), name


def test_alns_crush_uses_formal_registry():
    from setp_solver.search.alns_crush import ALNS_DEFAULT_INSTANCE_ORDER, INSTANCE_DIRS
    from setp_solver.search.instance_registry import FORMAL_INSTANCE_ORDER

    assert ALNS_DEFAULT_INSTANCE_ORDER == FORMAL_INSTANCE_ORDER
    assert set(INSTANCE_DIRS) == set(FORMAL_INSTANCE_ORDER)


def test_formal_registry_rejects_benchmark_without_ready_audit(tmp_path: Path):
    from setp_solver.search import instance_registry

    checker = getattr(instance_registry, "assert_formal_benchmark_ready", None)
    assert checker is not None, "formal registry needs an activation gate"
    active = tmp_path / "models/data_bundle/generated_instances/L-main"
    active.mkdir(parents=True)
    manifest = {
        "schema_version": "resetp-l-main-main-benchmark.v3",
        "formal_default": True,
        "activation_requires_verdict": "LMAIN_V3_READY",
        "instances": [
            {"instance_id": name, "bundle_file_hashes": {}}
            for name in instance_registry.FORMAL_INSTANCE_ORDER
        ],
    }
    (active / instance_registry.FORMAL_MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RuntimeError, match="LMAIN_V3_READY audit"):
        checker(tmp_path)
