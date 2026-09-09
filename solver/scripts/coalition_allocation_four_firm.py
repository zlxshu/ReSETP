#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Four-firm cooperative-game cost allocation for the coalition experiment.

Reads the 15 coalition optimal costs from a coalition results tree and reports
four allocation rules (Shapley value, nucleolus, proportional-to-standalone,
equal savings) together with individual-rationality / core checks and the
"minimise the maximum dissatisfaction (excess)" criterion.

Supported result-tree layouts (both are probed for every coalition):

    <root>/<KEY>/run_*/best_solution.json
    <root>/pairs_seeded/<KEY>/run_*/best_solution.json

where <KEY> is "D1", "D1+D2", "D1+D2+D3", ... and the grand coalition may be
stored either as "GRAND" or as "D1+D2+D3+D4".

Coalition cost is best_solution.json -> evaluation.total_cost; emissions, when
present, come from evaluation.breakdown.E_total.

Conventions
-----------
Cost game c(S).  Savings (characteristic function of the savings game):
    v(S) = sum_{i in S} c({i}) - c(S)
Excess of a coalition under allocation x (cost convention):
    e(S, x) = sum_{i in S} x_i - c(S)
which is identical to  v(S) - (savings granted to S), so the nucleolus of the
cost game and of the savings game coincide.  An allocation is in the core iff
e(S, x) <= 0 for every proper coalition S and sum_i x_i = c(N).

Usage
-----
    python3 coalition_allocation_four_firm.py --root solver/reports/<pkg>
    python3 coalition_allocation_four_firm.py --root <pkg> --out alloc.json
    python3 coalition_allocation_four_firm.py --self-test
"""

from __future__ import annotations

import argparse
import glob
import itertools
import json
import math
import os
import sys
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

try:
    import numpy as np
    from scipy.optimize import linprog

    HAVE_SCIPY = True
except ImportError:  # pragma: no cover - environment dependent
    HAVE_SCIPY = False

# --------------------------------------------------------------------------
# Player definitions
# --------------------------------------------------------------------------

PLAYERS: Tuple[str, ...] = ("D1", "D2", "D3", "D4")

PLAYER_LABELS: Dict[str, str] = {
    "D1": "东莞 D_dongguan",
    "D2": "佛山 D_foshan",
    "D3": "广州 D_guangzhou",
    "D4": "深圳 D_shenzhen",
}

# Depot ids as run_coalition_experiment.py --coalition expects them.  The index
# in D1..D4 is the position of the depot in the instance's depot_ids, which the
# runner writes into every STARTING line ("label" / "members"); the mapping
# below was verified against those lines for all 15 coalitions.
PLAYER_DEPOT_IDS: Dict[str, str] = {
    "D1": "D_dongguan",
    "D2": "D_foshan",
    "D3": "D_guangzhou",
    "D4": "D_shenzhen",
}

TOL = 1e-6


def coalition_key(members: Sequence[str]) -> str:
    """Directory key for a coalition, in canonical D1<D2<D3<D4 order."""
    ordered = [p for p in PLAYERS if p in members]
    return "+".join(ordered)


def all_coalitions(players: Sequence[str] = PLAYERS) -> List[FrozenSet[str]]:
    """Every non-empty coalition, ordered by size then by member order."""
    out: List[FrozenSet[str]] = []
    for size in range(1, len(players) + 1):
        for combo in itertools.combinations(players, size):
            out.append(frozenset(combo))
    return out


# --------------------------------------------------------------------------
# Loader
# --------------------------------------------------------------------------


class MissingCoalitions(RuntimeError):
    def __init__(self, missing: Sequence[str], found: Sequence[str], root: str):
        self.missing = list(missing)
        self.found = list(found)
        self.root = root
        super().__init__(
            "missing %d of %d coalitions under %s: %s (found: %s)"
            % (
                len(missing),
                len(missing) + len(found),
                root,
                ", ".join(missing),
                ", ".join(found) if found else "none",
            )
        )


def _candidate_dirs(root: str, key: str) -> List[str]:
    cands = [os.path.join(root, key), os.path.join(root, "pairs_seeded", key)]
    if key == coalition_key(PLAYERS):
        # grand coalition may be stored under the GRAND alias in either layout
        cands += [os.path.join(root, "GRAND"), os.path.join(root, "pairs_seeded", "GRAND")]
    return cands


def _read_run(path: str) -> Dict[str, object]:
    with open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    ev = doc.get("evaluation")
    if not isinstance(ev, dict) or "total_cost" not in ev:
        raise ValueError("no evaluation.total_cost in %s" % path)
    breakdown = ev.get("breakdown") or {}
    return {
        "path": path,
        "total_cost": float(ev["total_cost"]),
        "emissions": (
            float(breakdown["E_total"]) if isinstance(breakdown.get("E_total"), (int, float)) else None
        ),
        "feasible": ev.get("feasible"),
    }


def scan_root(root: str) -> Dict[FrozenSet[str], Dict[str, object]]:
    """Best run per coalition inside a single root; silently partial.

    When several run_* directories exist for one coalition the cheapest run is
    used (the coalition's optimal cost is the best solution found for it).
    Runs whose evaluation.feasible is explicitly False are never eligible: an
    infeasible run can carry an arbitrarily low total_cost and would otherwise
    make a superadditivity violation disappear on paper.
    """
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise FileNotFoundError("results root does not exist: %s" % root)

    data: Dict[FrozenSet[str], Dict[str, object]] = {}
    for coal in all_coalitions():
        key = coalition_key(sorted(coal))
        runs: List[Dict[str, object]] = []
        for cand in _candidate_dirs(root, key):
            for jpath in sorted(glob.glob(os.path.join(cand, "run_*", "best_solution.json"))):
                try:
                    run = _read_run(jpath)
                except (ValueError, json.JSONDecodeError):
                    continue
                if run["feasible"] is False:
                    continue
                runs.append(run)
        if not runs:
            continue
        best = min(runs, key=lambda r: r["total_cost"])
        best["n_runs"] = len(runs)
        best["root"] = root
        data[coal] = best
    return data


def load_coalition_costs(root: str) -> Dict[FrozenSet[str], Dict[str, object]]:
    """Load c(S) for all 15 coalitions; raise MissingCoalitions if any is absent."""
    data, _ = load_coalition_costs_multi([root])
    return data


def load_coalition_costs_multi(
    roots: Sequence[str],
) -> Tuple[Dict[FrozenSet[str], Dict[str, object]], List[str]]:
    """Best-known c(S) across several roots.

    The characteristic function is the best known feasible routing cost, so for
    every coalition the minimum total_cost over all roots that hold it is used.
    The winning root is recorded on the entry ("root"), and every root's own
    value is kept in "cost_by_root" so a later run can be traced back.

    Returns (data, used_roots).  A root that does not exist on disk is skipped
    with a note on stderr -- reseed rounds create their roots as they go.
    """
    used: List[str] = []
    per_root: List[Tuple[str, Dict[FrozenSet[str], Dict[str, object]]]] = []
    for root in roots:
        try:
            scanned = scan_root(root)
        except FileNotFoundError:
            print("note: skipping absent results root %s" % root, file=sys.stderr)
            continue
        used.append(os.path.abspath(root))
        per_root.append((os.path.abspath(root), scanned))

    data: Dict[FrozenSet[str], Dict[str, object]] = {}
    missing: List[str] = []
    found: List[str] = []
    for coal in all_coalitions():
        key = coalition_key(sorted(coal))
        cands = [(r, d[coal]) for r, d in per_root if coal in d]
        if not cands:
            missing.append(key)
            continue
        best_root, best = min(cands, key=lambda rc: rc[1]["total_cost"])
        entry = dict(best)
        entry["root"] = best_root
        entry["cost_by_root"] = {r: float(e["total_cost"]) for r, e in cands}
        data[coal] = entry
        found.append(key)

    if missing:
        raise MissingCoalitions(missing, found, " + ".join(used) or "(no root)")
    return data, used


# --------------------------------------------------------------------------
# Structural checks: superadditivity / monotonicity of the cost game
# --------------------------------------------------------------------------


def best_partition_cost(
    coal: FrozenSet[str], cost: Dict[FrozenSet[str], float]
) -> Tuple[float, List[FrozenSet[str]]]:
    """Cheapest way to split `coal` into sub-coalitions run separately.

    Returns (value, parts).  The trivial partition {coal} is included, so the
    value never exceeds c(coal).
    """
    members = sorted(coal, key=PLAYERS.index)
    n = len(members)
    idx = {m: i for i, m in enumerate(members)}
    full = (1 << n) - 1

    def to_set(mask: int) -> FrozenSet[str]:
        return frozenset(members[i] for i in range(n) if mask & (1 << i))

    best: Dict[int, Tuple[float, List[int]]] = {0: (0.0, [])}
    for mask in range(1, full + 1):
        low = mask & (-mask)  # force the lowest-indexed member into the first part
        sub = mask
        best_val = math.inf
        best_parts: List[int] = []
        while sub:
            if sub & low:
                part_cost = cost[to_set(sub)]
                rest_val, rest_parts = best[mask ^ sub]
                total = part_cost + rest_val
                if total < best_val - 1e-12:
                    best_val = total
                    best_parts = [sub] + rest_parts
            sub = (sub - 1) & mask
        best[mask] = (best_val, best_parts)

    val, parts = best[full]
    return val, [to_set(p) for p in parts]


def structural_report(cost: Dict[FrozenSet[str], float]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for coal in all_coalitions():
        c = cost[coal]
        bp, parts = best_partition_cost(coal, cost)
        gap = c - bp  # > 0  =>  the coalition run is worse than splitting it up
        rows.append(
            {
                "coalition": coalition_key(sorted(coal)),
                "runner_tag": runner_tag(coal),
                "cost": c,
                "best_partition_cost": bp,
                "best_partition": " | ".join(coalition_key(sorted(p)) for p in parts),
                "gap": gap,
                "superadditive_violation": gap > 1e-6,
            }
        )
    return rows


# --------------------------------------------------------------------------
# Allocation rules
# --------------------------------------------------------------------------


def shapley_value(
    players: Sequence[str], cost: Dict[FrozenSet[str], float]
) -> Dict[str, float]:
    """Shapley value of the cost game (c(empty) = 0)."""
    n = len(players)
    others = {p: [q for q in players if q != p] for p in players}
    fact = [math.factorial(k) for k in range(n + 1)]
    phi: Dict[str, float] = {}
    for p in players:
        total = 0.0
        rest = others[p]
        for size in range(0, n):
            weight = fact[size] * fact[n - size - 1] / fact[n]
            for combo in itertools.combinations(rest, size):
                s = frozenset(combo)
                c_s = cost[s] if s else 0.0
                c_si = cost[s | {p}]
                total += weight * (c_si - c_s)
        phi[p] = total
    return phi


def proportional_allocation(
    players: Sequence[str], cost: Dict[FrozenSet[str], float]
) -> Dict[str, float]:
    """Split c(N) in proportion to standalone costs."""
    grand = frozenset(players)
    stand = {p: cost[frozenset([p])] for p in players}
    tot = sum(stand.values())
    return {p: cost[grand] * stand[p] / tot for p in players}


def equal_savings_allocation(
    players: Sequence[str], cost: Dict[FrozenSet[str], float]
) -> Dict[str, float]:
    """Each firm pays its standalone cost minus an equal share of total savings."""
    grand = frozenset(players)
    stand = {p: cost[frozenset([p])] for p in players}
    savings = sum(stand.values()) - cost[grand]
    share = savings / len(players)
    return {p: stand[p] - share for p in players}


# --------------------------------------------------------------------------
# Nucleolus: sequential (lexicographic) linear programmes
# --------------------------------------------------------------------------


def _lp_min(
    c_obj: Sequence[float],
    A_ub: Optional[Sequence[Sequence[float]]],
    b_ub: Optional[Sequence[float]],
    A_eq: Sequence[Sequence[float]],
    b_eq: Sequence[float],
):
    kwargs = dict(
        c=np.asarray(c_obj, dtype=float),
        A_eq=np.asarray(A_eq, dtype=float),
        b_eq=np.asarray(b_eq, dtype=float),
        bounds=[(None, None)] * len(c_obj),
        method="highs",
    )
    if A_ub is not None and len(A_ub) > 0:
        kwargs["A_ub"] = np.asarray(A_ub, dtype=float)
        kwargs["b_ub"] = np.asarray(b_ub, dtype=float)
    res = linprog(**kwargs)
    if not res.success:
        raise RuntimeError("linprog failed: %s" % res.message)
    return res


def nucleolus(
    players: Sequence[str],
    cost: Dict[FrozenSet[str], float],
    tol: float = 1e-7,
) -> Tuple[Dict[str, float], List[Dict[str, object]]]:
    """Nucleolus of the cost game by lexicographic minimisation of excesses.

    Excess convention e(S, x) = sum_{i in S} x_i - c(S); proper coalitions only
    (the empty set and the grand coalition carry excess 0 by efficiency).

    At every round the coalitions that are fixed are those whose excess equals
    the round optimum t* in EVERY optimal solution -- established by re-solving
    with t held at t* and maximising that coalition's slack.  Relying on the
    tight set of whatever vertex the solver happens to return is wrong on
    degenerate games (e.g. when a null player is present), which is exactly the
    structure of the four-firm instance.
    """
    if not HAVE_SCIPY:
        raise RuntimeError("scipy is required for the nucleolus LP")

    players = list(players)
    n = len(players)
    pidx = {p: i for i, p in enumerate(players)}
    grand = frozenset(players)

    proper = [s for s in all_coalitions(players) if s != grand]
    active = list(proper)
    fixed: List[Tuple[FrozenSet[str], float]] = []
    rounds: List[Dict[str, object]] = []

    def indicator(s: FrozenSet[str]) -> List[float]:
        row = [0.0] * n
        for p in s:
            row[pidx[p]] = 1.0
        return row

    # efficiency is always an equality
    eff_row = [1.0] * n
    eff_rhs = cost[grand]

    while active:
        # ---- round LP: variables (x, t), minimise t ----
        A_ub, b_ub = [], []
        for s in active:
            A_ub.append(indicator(s) + [-1.0])   # x(S) - t <= c(S)
            b_ub.append(cost[s])
        A_eq, b_eq = [eff_row + [0.0]], [eff_rhs]
        for s, tval in fixed:
            A_eq.append(indicator(s) + [0.0])    # x(S) = c(S) + t_fixed
            b_eq.append(cost[s] + tval)
        obj = [0.0] * n + [1.0]
        res = _lp_min(obj, A_ub, b_ub, A_eq, b_eq)
        t_star = float(res.x[-1])

        # ---- decide which active coalitions are tight in EVERY optimum ----
        A_ub_f, b_ub_f = [], []
        for s in active:
            A_ub_f.append(indicator(s))          # x(S) <= c(S) + t*
            b_ub_f.append(cost[s] + t_star)
        A_eq_f, b_eq_f = [eff_row], [eff_rhs]
        for s, tval in fixed:
            A_eq_f.append(indicator(s))
            b_eq_f.append(cost[s] + tval)

        newly_fixed: List[FrozenSet[str]] = []
        for s in active:
            # maximise slack c(S) + t* - x(S)  <=>  minimise x(S)
            r = _lp_min(indicator(s), A_ub_f, b_ub_f, A_eq_f, b_eq_f)
            max_slack = (cost[s] + t_star) - float(r.fun)
            if max_slack <= tol * max(1.0, abs(cost[s])):
                newly_fixed.append(s)

        if not newly_fixed:
            raise RuntimeError(
                "nucleolus round %d fixed no coalition (t*=%r)" % (len(rounds) + 1, t_star)
            )

        rounds.append(
            {
                "round": len(rounds) + 1,
                "t_star": t_star,
                "fixed_coalitions": [coalition_key(sorted(s)) for s in newly_fixed],
            }
        )
        for s in newly_fixed:
            fixed.append((s, t_star))
            active.remove(s)

        # ---- stop as soon as x is uniquely determined by the fixed set ----
        # x is unique iff the equality system {efficiency} U {fixed excesses}
        # has full column rank n.
        A_eq_u = np.asarray([eff_row] + [indicator(s) for s, _ in fixed], dtype=float)
        b_eq_u = np.asarray([eff_rhs] + [cost[s] + tval for s, tval in fixed], dtype=float)
        if np.linalg.matrix_rank(A_eq_u, tol=1e-9) == n:
            sol, *_ = np.linalg.lstsq(A_eq_u, b_eq_u, rcond=None)
            resid = float(np.max(np.abs(A_eq_u @ sol - b_eq_u)))
            if resid > 1e-6:
                raise RuntimeError("inconsistent nucleolus equality system (residual %.3e)" % resid)
            return {players[i]: float(sol[i]) for i in range(n)}, rounds

    raise RuntimeError("nucleolus did not converge to a unique allocation")


# --------------------------------------------------------------------------
# Diagnostics per allocation
# --------------------------------------------------------------------------


def excess_table(
    players: Sequence[str], cost: Dict[FrozenSet[str], float], x: Dict[str, float]
) -> List[Tuple[str, float]]:
    grand = frozenset(players)
    rows = []
    for s in all_coalitions(players):
        if s == grand:
            continue
        rows.append((coalition_key(sorted(s)), sum(x[p] for p in s) - cost[s]))
    rows.sort(key=lambda kv: -kv[1])
    return rows


def diagnose(
    players: Sequence[str],
    cost: Dict[FrozenSet[str], float],
    x: Dict[str, float],
) -> Dict[str, object]:
    grand = frozenset(players)
    stand = {p: cost[frozenset([p])] for p in players}
    exc = excess_table(players, cost, x)
    max_exc = exc[0][1]
    argmax = [k for k, v in exc if v >= max_exc - 1e-9]
    ir = {p: x[p] <= stand[p] + 1e-9 for p in players}
    core_viol = [(k, v) for k, v in exc if v > 1e-6]
    return {
        "allocation": dict(x),
        "savings": {p: stand[p] - x[p] for p in players},
        "savings_rate": {p: (stand[p] - x[p]) / stand[p] for p in players},
        "efficiency_gap": sum(x.values()) - cost[grand],
        "individual_rationality": ir,
        "individually_rational": all(ir.values()),
        "in_core": not core_viol,
        "core_violations": [{"coalition": k, "excess": v} for k, v in core_viol],
        "max_excess": max_exc,
        "max_excess_coalitions": argmax,
        "excess_vector_desc": [{"coalition": k, "excess": v} for k, v in exc],
    }


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


def runner_tag(coal: FrozenSet[str]) -> str:
    """Output directory name run_coalition_experiment.py gives this coalition."""
    return "GRAND" if len(coal) == len(PLAYERS) else coalition_key(sorted(coal))


def reseed_plan(rep: Dict[str, object]) -> List[Dict[str, object]]:
    """One entry per superadditivity violation, ready to be re-run.

    A coalition costing more than the best split of itself lost to its own
    parts, so the union of the parts' saved solutions is a strictly better
    starting point than whatever that run began from.  seed_dirs are the run_*
    directories holding the current best value of each part, taken from
    whichever root supplied that value.
    """
    sources = rep["sources"]
    rows: List[Dict[str, object]] = []
    for row in rep["structure"]:
        if not row["superadditive_violation"]:
            continue
        parts = [p.strip() for p in row["best_partition"].split("|") if p.strip()]
        members = [m for m in PLAYERS if m in row["coalition"].split("+")]
        rows.append(
            {
                "tag": row["runner_tag"],
                "coalition": row["coalition"],
                "members": [PLAYER_DEPOT_IDS[m] for m in members],
                "best_partition": parts,
                "cost": row["cost"],
                "best_partition_cost": row["best_partition_cost"],
                "gap": row["gap"],
                "seed_dirs": [os.path.dirname(sources[p]) for p in parts],
            }
        )
    return rows


def print_reseed_plan(rep: Dict[str, object]) -> List[Dict[str, object]]:
    rows = reseed_plan(rep)
    print("=== reseed plan (superadditivity violations) ===")
    if not rows:
        print("no violation: nothing to reseed")
        print("RESEED_COUNT 0")
        print()
        return rows
    for r in rows:
        print(
            "%-12s c(S)=%.4f > best split %.4f (%s) by %.4f"
            % (r["tag"], r["cost"], r["best_partition_cost"],
               " | ".join(r["best_partition"]), r["gap"])
        )
        print("   --coalition     %s" % ",".join(r["members"]))
        print("   --seed-from-dirs %s" % ",".join(r["seed_dirs"]))
    print()
    for r in rows:
        print("RESEED %s %s %s" % (r["tag"], ",".join(r["members"]), ",".join(r["seed_dirs"])))
    print("RESEED_COUNT %d" % len(rows))
    print()
    return rows


def describe(
    raw: Dict[FrozenSet[str], Dict[str, object]], used_roots: Sequence[str]
) -> Dict[str, object]:
    """Costs, provenance and the superadditivity table -- no allocation rules.

    Kept separate from `analyse` so that --print-reseed-plan still works when
    the allocation LPs cannot run (no scipy, or a degenerate game).
    """
    cost = {s: float(v["total_cost"]) for s, v in raw.items()}
    return {
        "root": used_roots[0] if used_roots else "",
        "roots": list(used_roots),
        "players": {p: PLAYER_LABELS[p] for p in PLAYERS},
        "costs": {coalition_key(sorted(s)): c for s, c in cost.items()},
        "emissions": {coalition_key(sorted(s)): v["emissions"] for s, v in raw.items()},
        "sources": {coalition_key(sorted(s)): v["path"] for s, v in raw.items()},
        "value_root": {coalition_key(sorted(s)): v["root"] for s, v in raw.items()},
        "cost_by_root": {
            coalition_key(sorted(s)): v.get("cost_by_root", {}) for s, v in raw.items()
        },
        "feasible": {coalition_key(sorted(s)): v["feasible"] for s, v in raw.items()},
        "structure": structural_report(cost),
    }


def analyse(roots: Sequence[str]) -> Dict[str, object]:
    raw, used_roots = load_coalition_costs_multi(roots)
    return analyse_from_raw(raw, used_roots)


def analyse_from_raw(
    raw: Dict[FrozenSet[str], Dict[str, object]], used_roots: Sequence[str]
) -> Dict[str, object]:
    cost = {s: float(v["total_cost"]) for s, v in raw.items()}
    players = list(PLAYERS)
    grand = frozenset(players)
    stand = {p: cost[frozenset([p])] for p in players}
    total_savings = sum(stand.values()) - cost[grand]

    methods: Dict[str, Dict[str, float]] = {
        "shapley": shapley_value(players, cost),
        "proportional": proportional_allocation(players, cost),
        "equal_savings": equal_savings_allocation(players, cost),
    }
    nuc_rounds: List[Dict[str, object]] = []
    if HAVE_SCIPY:
        methods["nucleolus"], nuc_rounds = nucleolus(players, cost)
    order = ["shapley", "nucleolus", "proportional", "equal_savings"]
    methods = {k: methods[k] for k in order if k in methods}

    rep = describe(raw, used_roots)
    rep.update(
        {
            "standalone_total": sum(stand.values()),
            "grand_cost": cost[grand],
            "total_savings": total_savings,
            "nucleolus_rounds": nuc_rounds,
            "results": {m: diagnose(players, cost, x) for m, x in methods.items()},
        }
    )
    return rep


METHOD_TITLES = {
    "shapley": "Shapley",
    "nucleolus": "Nucleolus",
    "proportional": "Proportional",
    "equal_savings": "Equal savings",
}


def print_report(rep: Dict[str, object]) -> None:
    players = list(PLAYERS)
    cost = rep["costs"]
    roots = rep.get("roots") or [rep["root"]]
    for i, r in enumerate(roots):
        print("results root : %s%s" % (r, "" if i == 0 else "   (extra)"))
    if len(roots) > 1:
        print("               c(S) = best known feasible cost over all roots above")
    print("players      : %s" % ", ".join("%s=%s" % (p, rep["players"][p]) for p in players))
    print()

    print("=== coalition costs and best partition (superadditivity / monotonicity) ===")
    show_src = len(roots) > 1
    print(
        "%-10s %14s %14s %12s  %s%s"
        % ("coalition", "c(S)", "best partition", "gap", "split",
           "   from" if show_src else "")
    )
    flagged = []
    for row in rep["structure"]:
        flag = " <== VIOLATION" if row["superadditive_violation"] else ""
        if row["superadditive_violation"]:
            flagged.append(row["coalition"])
        src = ""
        if show_src:
            src = "   %s" % os.path.basename(rep["value_root"][row["coalition"]])
        print(
            "%-10s %14.4f %14.4f %12.4f  %s%s%s"
            % (row["coalition"], row["cost"], row["best_partition_cost"], row["gap"],
               row["best_partition"], src, flag)
        )
    print()
    if flagged:
        print("!! superadditivity violated for: %s" % ", ".join(flagged))
        print("   (a coalition costing more than the best split of itself indicates a")
        print("    search failure in that run, not an economic property)")
    else:
        print("no superadditivity violation: every c(S) equals or beats its best split")
        print("(gap == 0.0000 exactly means the coalition run found no gain over running")
        print(" the parts separately -- zero synergy and a non-improving search are")
        print(" numerically indistinguishable at this level)")
    print()

    print("standalone total  = %.4f" % rep["standalone_total"])
    print("grand coalition   = %.4f" % rep["grand_cost"])
    print("total savings v(N)= %.4f" % rep["total_savings"])
    print()

    methods = list(rep["results"].keys())
    print("=== allocations (yuan) ===")
    header = "%-8s %14s" % ("firm", "standalone")
    for m in methods:
        header += " %14s" % METHOD_TITLES.get(m, m)
    print(header)
    for p in players:
        line = "%-8s %14.4f" % (p, cost[p])
        for m in methods:
            line += " %14.4f" % rep["results"][m]["allocation"][p]
        print(line)
    line = "%-8s %14.4f" % ("total", rep["standalone_total"])
    for m in methods:
        line += " %14.4f" % sum(rep["results"][m]["allocation"].values())
    print(line)
    print()

    print("=== savings (yuan) and savings rate ===")
    for m in methods:
        r = rep["results"][m]
        print("-- %s" % METHOD_TITLES.get(m, m))
        for p in players:
            print(
                "   %-4s savings %10.4f   rate %7.3f%%   IR %s"
                % (p, r["savings"][p], 100.0 * r["savings_rate"][p],
                   "ok" if r["individual_rationality"][p] else "VIOLATED")
            )
        print("   efficiency gap %.2e" % r["efficiency_gap"])
    print()

    print("=== stability: core check and max dissatisfaction (excess) ===")
    print("%-16s %-10s %-14s %14s  %s" % ("method", "in core", "individually", "max excess", "attained by"))
    print("%-16s %-10s %-14s %14s" % ("", "", "rational", ""))
    for m in methods:
        r = rep["results"][m]
        print(
            "%-16s %-10s %-14s %14.4f  %s"
            % (
                METHOD_TITLES.get(m, m),
                "yes" if r["in_core"] else "NO",
                "yes" if r["individually_rational"] else "NO",
                r["max_excess"],
                ", ".join(r["max_excess_coalitions"]),
            )
        )
    print()
    for m in methods:
        r = rep["results"][m]
        if r["core_violations"]:
            print(
                "core violations for %s: %s"
                % (
                    METHOD_TITLES.get(m, m),
                    "; ".join(
                        "%s excess %+.4f" % (cv["coalition"], cv["excess"])
                        for cv in r["core_violations"]
                    ),
                )
            )
    print()

    print("=== lexicographic excess vector (descending, proper coalitions) ===")
    print("%-10s" % "rank" + "".join(" %22s" % METHOD_TITLES.get(m, m) for m in methods))
    n_rows = len(rep["results"][methods[0]]["excess_vector_desc"])
    for i in range(n_rows):
        line = "%-10d" % (i + 1)
        for m in methods:
            e = rep["results"][m]["excess_vector_desc"][i]
            line += " %10s %11.4f" % (e["coalition"], e["excess"])
        print(line)
    print()

    if rep["nucleolus_rounds"]:
        print("=== nucleolus sequential LP rounds ===")
        for r in rep["nucleolus_rounds"]:
            print(
                "round %d: t* = %12.6f   fixed: %s"
                % (r["round"], r["t_star"], ", ".join(r["fixed_coalitions"]))
            )
        print()

    best = min(methods, key=lambda m: rep["results"][m]["max_excess"])
    ties = [
        m for m in methods
        if abs(rep["results"][m]["max_excess"] - rep["results"][best]["max_excess"]) <= 1e-6
    ]
    core_ok = [m for m in methods if rep["results"][m]["in_core"]]
    print("core-feasible methods            : %s" % (", ".join(METHOD_TITLES.get(m, m) for m in core_ok) or "none"))
    if len(ties) > 1:
        print(
            "min-max-excess criterion         : TIE between %s (max excess %.4f)"
            % (", ".join(METHOD_TITLES.get(m, m) for m in ties), rep["results"][best]["max_excess"])
        )
        print("                                   -> compare the second-highest excess above")
    else:
        print(
            "min-max-excess criterion selects : %s (max excess %.4f)"
            % (METHOD_TITLES.get(best, best), rep["results"][best]["max_excess"])
        )


# --------------------------------------------------------------------------
# Self-test
# --------------------------------------------------------------------------


def _cost_game_from_savings(
    players: Sequence[str], v: Dict[FrozenSet[str], float], base: float = 1000.0
) -> Dict[FrozenSet[str], float]:
    """Cost game with c({i}) = base and v(S) = sum_i base - c(S)."""
    return {s: base * len(s) - v.get(s, 0.0) for s in all_coalitions(players)}


def _approx(a: Sequence[float], b: Sequence[float], tol: float = 1e-6) -> bool:
    return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


def self_test() -> int:
    failures: List[str] = []

    def check(name: str, got: Sequence[float], want: Sequence[float], tol: float = 1e-6):
        ok = _approx(got, want, tol)
        print(
            "  [%s] %-46s got %s  want %s"
            % ("PASS" if ok else "FAIL", name,
               "(" + ", ".join("%.4f" % g for g in got) + ")",
               "(" + ", ".join("%.4f" % w for w in want) + ")")
        )
        if not ok:
            failures.append(name)

    print("scipy available: %s" % HAVE_SCIPY)
    print()

    # ---- textbook 3-player game A: empty core, prenucleolus branch ----------
    # v(i)=0, v(12)=60, v(13)=80, v(23)=100, v(123)=105.
    # All three pair-excesses can be equalised: x_i = (v(N)+sum v(jk))/3 - v(jk),
    # giving (15, 35, 55) with common pair excess +10 (core is empty).
    P3 = ("D1", "D2", "D3")
    vA = {
        frozenset(("D1", "D2")): 60.0,
        frozenset(("D1", "D3")): 80.0,
        frozenset(("D2", "D3")): 100.0,
        frozenset(P3): 105.0,
    }
    cA = _cost_game_from_savings(P3, vA)
    print("case A: 3-player game, v(12,13,23,123) = 60/80/100/105, empty core")
    if HAVE_SCIPY:
        xA, _ = nucleolus(P3, cA)
        sA = [1000.0 - xA[p] for p in P3]
        check("A nucleolus savings", sA, [15.0, 35.0, 55.0])
    phiA = shapley_value(P3, cA)
    check("A Shapley savings", [1000.0 - phiA[p] for p in P3], [25.0, 35.0, 45.0])

    # ---- textbook 3-player game B: non-empty core, needs two LP rounds -----
    # Same pairs, v(123)=200.  Round 1 pins x1=50 (t*=-50), round 2 balances
    # e({3}) against e({1,2}) at -55, giving (50, 65, 85).
    vB = dict(vA)
    vB[frozenset(P3)] = 200.0
    cB = _cost_game_from_savings(P3, vB)
    print("case B: same pairs with v(123)=200, non-empty core, two rounds")
    if HAVE_SCIPY:
        xB, _ = nucleolus(P3, cB)
        check("B nucleolus savings", [1000.0 - xB[p] for p in P3], [50.0, 65.0, 85.0])

    # ---- case C: case B plus a null 4th player -----------------------------
    # A null player must receive zero savings and must not disturb the others.
    # This is the degenerate structure of the real four-firm instance.
    P4 = ("D1", "D2", "D3", "D4")
    vC: Dict[FrozenSet[str], float] = {}
    for s in all_coalitions(P4):
        base = s - {"D4"}
        vC[s] = vB.get(frozenset(base), 0.0) if base else 0.0
    cC = _cost_game_from_savings(P4, vC)
    print("case C: case B with a null player D4 (degenerate, ties at t*=0)")
    if HAVE_SCIPY:
        xC, roundsC = nucleolus(P4, cC)
        check("C nucleolus savings", [1000.0 - xC[p] for p in P4], [50.0, 65.0, 85.0, 0.0])
        print("       rounds: %s" % "; ".join(
            "t*=%.4f fix %s" % (r["t_star"], ",".join(r["fixed_coalitions"])) for r in roundsC))
    phiC = shapley_value(P4, cC)
    check("C Shapley gives null player 0 savings", [1000.0 - phiC["D4"]], [0.0])

    # ---- case D: glove game, core is the single point (1,0,0) --------------
    vD = {
        frozenset(("D1", "D2")): 1.0,
        frozenset(("D1", "D3")): 1.0,
        frozenset(("D2", "D3")): 0.0,
        frozenset(P3): 1.0,
    }
    cD = _cost_game_from_savings(P3, vD)
    print("case D: glove game (1 left, 2 right), core = {(1,0,0)}")
    if HAVE_SCIPY:
        xD, _ = nucleolus(P3, cD)
        check("D nucleolus savings", [1000.0 - xD[p] for p in P3], [1.0, 0.0, 0.0])

    # ---- case E: partition DP on a trivially additive game -----------------
    cE = _cost_game_from_savings(P3, {})  # fully additive: no synergy anywhere
    bp, parts = best_partition_cost(frozenset(P3), cE)
    check("E best partition of an additive game", [bp], [3000.0])
    print("       parts: %s" % " | ".join(coalition_key(sorted(p)) for p in parts))

    print()
    if failures:
        print("SELF-TEST FAILED: %s" % ", ".join(failures))
        return 1
    print("SELF-TEST PASSED")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", help="coalition results root directory")
    ap.add_argument(
        "--extra-root",
        action="append",
        default=[],
        metavar="DIR",
        help=(
            "additional results root (repeatable); c(S) becomes the minimum "
            "over every root that holds the coalition.  Absent directories are "
            "skipped, so a not-yet-created reseed round can be listed"
        ),
    )
    ap.add_argument(
        "--print-reseed-plan",
        action="store_true",
        help=(
            "for every superadditivity violation print the best partition and "
            "the run dirs to warm-start a re-run from, as a --seed-from-dirs "
            "string, plus one machine-readable 'RESEED <tag> <members> <dirs>' "
            "line per violation"
        ),
    )
    ap.add_argument("--out", help="optional path to write the full report as JSON")
    ap.add_argument("--self-test", action="store_true", help="run unit checks on textbook games and exit")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.root:
        ap.error("--root is required unless --self-test is given")

    if not HAVE_SCIPY:
        print("WARNING: scipy is not importable; the nucleolus will be skipped.", file=sys.stderr)

    roots = [args.root] + list(args.extra_root)
    try:
        raw, used_roots = load_coalition_costs_multi(roots)
        # the plan is printed before the allocation LPs so that a degenerate
        # game (or a missing scipy) cannot swallow it
        if args.print_reseed_plan:
            print_reseed_plan(describe(raw, used_roots))
        rep = analyse_from_raw(raw, used_roots)
    except MissingCoalitions as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        print("", file=sys.stderr)
        print("missing coalitions (%d):" % len(exc.missing), file=sys.stderr)
        for k in exc.missing:
            print("  %s" % k, file=sys.stderr)
        print("present coalitions (%d): %s" % (len(exc.found), ", ".join(exc.found)), file=sys.stderr)
        return 2

    print_report(rep)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=2)
        print()
        print("wrote %s" % os.path.abspath(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
