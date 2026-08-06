from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _carbon_slot_calls(path: Path) -> list[tuple[int, bool]]:
    source = path.read_text(encoding="utf-8")
    if "carbon_slot_index(" not in source:
        return []
    tree = ast.parse(source, filename=str(path))
    calls: list[tuple[int, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function_name = (
            node.func.id
            if isinstance(node.func, ast.Name)
            else node.func.attr
            if isinstance(node.func, ast.Attribute)
            else ""
        )
        if function_name == "carbon_slot_index":
            calls.append(
                (node.lineno, any(keyword.arg == "n_slots" for keyword in node.keywords))
            )
    return calls


def test_every_repository_carbon_slot_call_explicitly_passes_n_slots() -> None:
    missing: list[str] = []
    for path in REPO_ROOT.rglob("*.py"):
        relative = path.relative_to(REPO_ROOT)
        if any(part.startswith("._") for part in relative.parts):
            continue
        if any(
            part in {".git", ".agents", ".claude", ".codex", "__pycache__", ".pytest_cache"}
            for part in relative.parts
        ):
            continue
        for line, has_n_slots in _carbon_slot_calls(path):
            if not has_n_slots:
                missing.append(f"{relative}:{line}")
    assert missing == [], "carbon_slot_index calls missing n_slots: " + ", ".join(missing)
