from __future__ import annotations

import ast
import subprocess
from pathlib import Path

from setp_solver.china81 import (
    CV_FIXED_CNY_PER_DAY,
    EV_FIXED_CNY_PER_DAY,
    EV_NON_ENERGY_CNY_PER_KM,
)
from setp_solver.private_instance_rebuild_20260811 import (
    BATTERY_DEPRECIATION_CNY_PER_KM,
    load_private_instance_rebuild,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_ev_non_energy_final_constant_has_the_approved_float_bits() -> None:
    component_sum = 0.6700 + BATTERY_DEPRECIATION_CNY_PER_KM

    assert component_sum.hex() == "0x1.d4395810624dep-1"
    assert EV_NON_ENERGY_CNY_PER_KM.hex() == "0x1.d4395810624ddp-1"
    assert component_sum != EV_NON_ENERGY_CNY_PER_KM

    bundle = load_private_instance_rebuild(REPO_ROOT)
    runtime_value = bundle.instance.vehicle_parameters[
        "ev"
    ].non_energy_distance_cost_per_km
    assert runtime_value == EV_NON_ENERGY_CNY_PER_KM
    assert runtime_value.hex() == "0x1.d4395810624ddp-1"
    fallback = float(bundle.prices.vehicle_fixed_cost)
    assert (
        bundle.instance.vehicle_fixed_cost_per_day("cv", fallback=fallback)
        == CV_FIXED_CNY_PER_DAY
    )
    assert (
        bundle.instance.vehicle_fixed_cost_per_day("ev", fallback=fallback)
        == EV_FIXED_CNY_PER_DAY
    )


def _tracked_python_sources() -> set[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "--cached", "--", "*.py"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return {
        REPO_ROOT / relative
        for relative in completed.stdout.splitlines()
        if relative
    }


def _active_solver_sources() -> set[Path]:
    paths: set[Path] = set()
    for root in (REPO_ROOT / "solver/src", REPO_ROOT / "solver/scripts"):
        paths.update(root.rglob("*.py"))
    return paths


def _is_atomic_component(
    node: ast.AST,
    *,
    kind: str,
    aliases: dict[str, set[str]] | None = None,
) -> bool:
    if isinstance(node, ast.BinOp):
        return False
    text = ast.unparse(node).replace(" ", "").lower()
    if (
        aliases is not None
        and isinstance(node, ast.Name)
        and kind in aliases.get(node.id, set())
    ):
        return True
    numeric_values = {
        float(item.value)
        for item in ast.walk(node)
        if isinstance(item, ast.Constant)
        and isinstance(item.value, (int, float))
        and not isinstance(item.value, bool)
    }
    if kind == "ev_base":
        return (
            "base_non_energy" in text
            or text in {"base", "ev_base"}
            or 0.67 in numeric_values
        )
    if kind == "battery_depreciation":
        return (
            "battery_depreciation" in text
            or text in {"depreciation", "battery_depreciation"}
            or 0.2445 in numeric_values
        )
    if kind == "fixed_base":
        return (
            text == "base"
            or "base_daily_fixed" in text
            or "cv_fixed_cny_per_day" in text
            or 170.0 in numeric_values
        )
    if kind == "fixed_premium":
        return (
            text == "premium"
            or "daily_fixed_premium" in text
            or "fixed_premium" in text
            or 50.0 in numeric_values
        )
    raise AssertionError(f"unknown component kind: {kind}")


def _reconstructs_approved_final_value(
    node: ast.AST,
    *,
    aliases: dict[str, set[str]] | None = None,
) -> bool:
    if isinstance(node, ast.BinOp):
        if not isinstance(node.op, ast.Add):
            return False
        components = (node.left, node.right)
    elif isinstance(node, ast.AugAssign):
        if not isinstance(node.op, ast.Add):
            return False
        components = (node.target, node.value)
    elif isinstance(node, ast.Call):
        function = ast.unparse(node.func).replace(" ", "").lower()
        additive_functions = {
            "sum",
            "builtins.sum",
            "math.fsum",
            "add",
            "operator.add",
            "_operator.add",
            "np.add",
            "numpy.add",
            "np.sum",
            "numpy.sum",
            "reduce",
            "functools.reduce",
        }
        if function not in additive_functions or not node.args:
            return False
        if function.endswith("reduce"):
            reducer = ast.unparse(node.args[0]).replace(" ", "").lower()
            if reducer not in {
                "add",
                "operator.add",
                "_operator.add",
                "np.add",
                "numpy.add",
            } or len(node.args) < 2:
                return False
            components = ()
            first_argument = node.args[1]
        elif function.endswith(".add") or function == "add":
            components = tuple(node.args)
            first_argument = None
        else:
            first_argument = node.args[0]
        if isinstance(first_argument, (ast.List, ast.Tuple, ast.Set)):
            components = tuple(first_argument.elts)
        elif first_argument is not None:
            components = (first_argument,)
    else:
        return False

    pairs = (
        ("ev_base", "battery_depreciation"),
        ("fixed_base", "fixed_premium"),
    )
    return any(
        any(
            _is_atomic_component(component, kind=left_kind, aliases=aliases)
            for component in components
        )
        and any(
            _is_atomic_component(component, kind=right_kind, aliases=aliases)
            for component in components
        )
        for left_kind, right_kind in pairs
    )


def test_guard_recognizes_every_removed_runtime_addition_shape() -> None:
    old_expressions = (
        "0.67 + BATTERY_DEPRECIATION_CNY_PER_KM",
        (
            'float(row["base_non_energy_cost_cny_per_km"]) '
            '+ float(row["battery_depreciation_cny_per_km"])'
        ),
        "170.0 + EV_DAILY_FIXED_PREMIUM_CNY",
        "base + premium",
    )

    for expression in old_expressions:
        node = ast.parse(expression, mode="eval").body
        assert isinstance(node, ast.BinOp)
        assert _reconstructs_approved_final_value(node), expression

    aliased = ast.parse(
        "ev_base = 0.67\n"
        "depreciation = BATTERY_DEPRECIATION_CNY_PER_KM\n"
        "final = ev_base + depreciation\n"
    )
    aliases = _component_aliases(aliased)
    aliased_addition = aliased.body[-1].value
    assert isinstance(aliased_addition, ast.BinOp)
    assert _reconstructs_approved_final_value(
        aliased_addition,
        aliases=aliases,
    )

    call_expressions = (
        "sum([0.67, BATTERY_DEPRECIATION_CNY_PER_KM])",
        "math.fsum((170.0, EV_DAILY_FIXED_PREMIUM_CNY))",
        "operator.add(0.67, BATTERY_DEPRECIATION_CNY_PER_KM)",
        "numpy.sum([170.0, EV_DAILY_FIXED_PREMIUM_CNY])",
        (
            "functools.reduce(operator.add, "
            "[0.67, BATTERY_DEPRECIATION_CNY_PER_KM])"
        ),
    )
    for expression in call_expressions:
        node = ast.parse(expression, mode="eval").body
        assert isinstance(node, ast.Call)
        assert _reconstructs_approved_final_value(node), expression

    aliased_call = ast.parse(
        "components = [0.67, BATTERY_DEPRECIATION_CNY_PER_KM]\n"
        "final = sum(components)\n"
    )
    aliases = _component_aliases(aliased_call)
    call = aliased_call.body[-1].value
    assert isinstance(call, ast.Call)
    assert _reconstructs_approved_final_value(call, aliases=aliases)

    augmented = ast.parse(
        "ev_base = 0.67\n"
        "ev_base += BATTERY_DEPRECIATION_CNY_PER_KM\n"
    )
    aliases = _component_aliases(augmented)
    augmented_addition = augmented.body[-1]
    assert isinstance(augmented_addition, ast.AugAssign)
    assert _reconstructs_approved_final_value(
        augmented_addition,
        aliases=aliases,
    )

    imported_alias = ast.parse(
        "from parameters import BATTERY_DEPRECIATION_CNY_PER_KM as DEP\n"
        "final = 0.67 + DEP\n"
    )
    aliases = _component_aliases(imported_alias)
    imported_alias_addition = imported_alias.body[-1].value
    assert isinstance(imported_alias_addition, ast.BinOp)
    assert _reconstructs_approved_final_value(
        imported_alias_addition,
        aliases=aliases,
    )

    non_additive_reduce = ast.parse(
        "functools.reduce(operator.mul, "
        "[0.67, BATTERY_DEPRECIATION_CNY_PER_KM])",
        mode="eval",
    ).body
    assert isinstance(non_additive_reduce, ast.Call)
    assert not _reconstructs_approved_final_value(non_additive_reduce)


def _component_aliases(tree: ast.AST) -> dict[str, set[str]]:
    aliases: dict[str, set[str]] = {}
    kinds = (
        "ev_base",
        "battery_depreciation",
        "fixed_base",
        "fixed_premium",
    )
    assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr))
    ]
    changed = True
    while changed:
        changed = False
        for assignment in assignments:
            value = assignment.value
            if value is None:
                continue
            targets = (
                assignment.targets
                if isinstance(assignment, ast.Assign)
                else [assignment.target]
            )
            discovered = {
                kind
                for kind in kinds
                if _is_atomic_component(value, kind=kind, aliases=aliases)
            }
            for target in targets:
                if not isinstance(target, ast.Name) or not discovered:
                    continue
                previous = aliases.setdefault(target.id, set())
                before = len(previous)
                previous.update(discovered)
                changed = changed or len(previous) != before
        for imported in ast.walk(tree):
            if not isinstance(imported, (ast.Import, ast.ImportFrom)):
                continue
            for alias in imported.names:
                local_name = alias.asname or alias.name.rsplit(".", 1)[-1]
                source_name = alias.name.lower()
                discovered = {
                    kind
                    for kind in kinds
                    if _is_atomic_component(
                        ast.Name(id=source_name, ctx=ast.Load()),
                        kind=kind,
                        aliases=aliases,
                    )
                }
                if discovered:
                    previous = aliases.setdefault(local_name, set())
                    before = len(previous)
                    previous.update(discovered)
                    changed = changed or len(previous) != before
    return aliases


def test_runtime_code_never_reconstructs_approved_final_values() -> None:
    violations: list[str] = []
    sources = _tracked_python_sources() | _active_solver_sources()
    for path in sorted(sources):
        relative = path.relative_to(REPO_ROOT)
        if (
            not path.is_file()
            or path.name.startswith("._")
            or "tests" in relative.parts
            or ".venv" in relative.parts
            or "third_party" in relative.parts
            or "tmp" in relative.parts
        ):
            continue
        source = path.read_text(encoding="utf-8")
        if not any(
            marker in source
            for marker in (
                "0.2445",
                "BATTERY_DEPRECIATION",
                "battery_depreciation",
                "daily_fixed_premium",
                "FIXED_PREMIUM",
                "base + premium",
                "170.0 +",
                "170.0",
                "sum(",
                "fsum(",
            )
        ):
            continue
        tree = ast.parse(source, filename=str(relative))
        aliases = _component_aliases(tree)
        for node in ast.walk(tree):
            if _reconstructs_approved_final_value(node, aliases=aliases):
                expression = ast.get_source_segment(source, node) or ast.unparse(node)
                violations.append(
                    f"{relative}:{node.lineno}: {expression.replace(chr(10), ' ')}"
                )

    assert violations == [], (
        "approved final parameters must be loaded from named constants; "
        "component addition found:\n" + "\n".join(violations)
    )
