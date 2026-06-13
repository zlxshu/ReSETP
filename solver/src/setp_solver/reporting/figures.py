from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev

from .style import LINE_STYLES, MARKERS, PALETTE, cm_to_inch, sample_watermark, save_pdf_png, setup_matplotlib


def figure_f1_route_map(nodes_csv: str | Path, routes_csv: str | Path, output_stem: str | Path, *, watermark: bool = True) -> tuple[Path, Path]:
    setup_matplotlib()
    from matplotlib import pyplot as plt

    nodes = {row["node_id"]: row for row in _read_rows(nodes_csv)}
    routes = _read_rows(routes_csv)
    fig, axes = plt.subplots(1, 2, figsize=cm_to_inch(16.0, 7.2), constrained_layout=True)
    depot_colors = {"D0": PALETTE["blue"], "D1": PALETTE["green"]}
    route_colors = [PALETTE["blue"], PALETTE["green"], PALETTE["red"], PALETTE["purple"], PALETTE["amber"], PALETTE["gray"]]

    _draw_nodes(axes[0], nodes, depot_colors)
    axes[0].set_title("(a) 节点地理分布")

    for idx, route in enumerate(routes):
        seq = [item for item in route["node_sequence"].split(">") if item in nodes]
        xs = [float(nodes[item]["x"]) for item in seq]
        ys = [float(nodes[item]["y"]) for item in seq]
        is_cv = route["vehicle_type"].lower() == "cv" or route["vehicle_type"] == "油车"
        axes[1].plot(
            xs,
            ys,
            color=route_colors[idx % len(route_colors)],
            linestyle="-" if is_cv else "--",
            marker=MARKERS[idx % len(MARKERS)],
            markersize=3,
            linewidth=0.95,
            label=route["route_id"],
        )
    _draw_nodes(axes[1], nodes, depot_colors)
    axes[1].set_title("(b) 路线方案")

    for ax in axes:
        _scale_bar(ax)
        ax.set_xlabel("横坐标 / km")
        ax.set_ylabel("纵坐标 / km")
        ax.set_aspect("equal", adjustable="box")
    axes[1].legend(loc="best", fontsize=7, ncols=1)
    if watermark:
        sample_watermark(axes[0])
    return save_pdf_png(fig, output_stem)


def figure_f2_algorithm_performance(curves_csv: str | Path, finals_csv: str | Path, output_stem: str | Path, *, watermark: bool = True) -> tuple[Path, Path]:
    setup_matplotlib()
    from matplotlib import pyplot as plt

    curve_rows = _read_rows(curves_csv)
    final_rows = _read_rows(finals_csv)
    algorithms = sorted({row["algorithm"] for row in curve_rows})
    colors = [PALETTE["blue"], PALETTE["green"], PALETTE["red"], PALETTE["purple"]]
    fig, axes = plt.subplots(1, 2, figsize=cm_to_inch(16.0, 7.0), constrained_layout=True)
    for idx, algorithm in enumerate(algorithms):
        by_eval: dict[int, list[float]] = defaultdict(list)
        for row in curve_rows:
            if row["algorithm"] == algorithm:
                # v2026-06-13: Formal W2 CSV may serialize eval counts as "16021.0";
                # this parser is report-layer only and keeps the plotted value unchanged.
                by_eval[int(float(row["evals"]))].append(float(row["best_obj"]))
        xs = sorted(by_eval)
        ys = [mean(by_eval[x]) for x in xs]
        std = [pstdev(by_eval[x]) if len(by_eval[x]) > 1 else 0.0 for x in xs]
        color = colors[idx % len(colors)]
        axes[0].step(xs, ys, where="post", color=color, linestyle=LINE_STYLES[idx % len(LINE_STYLES)], marker=MARKERS[idx % len(MARKERS)], markersize=3, label=algorithm)
        axes[0].fill_between(xs, [y - s for y, s in zip(ys, std)], [y + s for y, s in zip(ys, std)], step="post", color=color, alpha=0.10)
    axes[0].set_title("(a) 收敛曲线")
    axes[0].set_xlabel("评估次数")
    axes[0].set_ylabel("最优目标")
    grouped = [[float(row["final_obj"]) for row in final_rows if row["algorithm"] == algorithm] for algorithm in algorithms]
    axes[1].boxplot(grouped, labels=algorithms, patch_artist=True)
    axes[1].set_title("(b) 终值分布")
    axes[1].set_ylabel("目标")
    axes[0].legend()
    if watermark:
        for ax in axes:
            sample_watermark(ax)
    return save_pdf_png(fig, output_stem)


def figure_f3_two_layer_waterfall(csv_path: str | Path, output_stem: str | Path) -> tuple[Path, Path]:
    setup_matplotlib()
    from matplotlib import pyplot as plt

    rows = _read_rows(csv_path)
    labels = [row["stage"] for row in rows]
    values = [float(row["total_carbon_kg"]) for row in rows]
    fig, ax = plt.subplots(figsize=cm_to_inch(8.0, 5.8))
    xs = list(range(len(values)))
    ax.bar(xs, values, color=[PALETTE["gray"], PALETTE["blue"], PALETTE["green"]], width=0.62)
    for i in range(1, len(values)):
        delta = values[i] - values[i - 1]
        pct = delta / values[i - 1] * 100.0 if values[i - 1] else 0.0
        y = max(values[i], values[i - 1])
        ax.plot([i - 1, i], [y, y], color="#334155", linewidth=0.9)
        ax.text(i - 0.5, y * 1.01, f"{delta:+.1f} kg ({pct:+.1f}%)", ha="center", fontsize=8)
    ax.set_xticks(xs, labels)
    ax.set_ylabel("总碳 kg")
    ax.set_title("F3 两层减碳瀑布")
    ax.margins(y=0.18)
    return save_pdf_png(fig, output_stem)


def figure_f3_two_layer_bars(csv_path: str | Path, output_stem: str | Path) -> tuple[Path, Path]:
    setup_matplotlib()
    from matplotlib import pyplot as plt

    rows = _read_rows(csv_path)
    labels = [row["stage"] for row in rows]
    values = [float(row["total_carbon_kg"]) for row in rows]
    fig, ax = plt.subplots(figsize=cm_to_inch(8.0, 5.4))
    ax.bar(range(len(values)), values, color=[PALETTE["gray"], PALETTE["blue"], PALETTE["green"]], width=0.58, edgecolor=PALETTE["dark"], linewidth=0.7)
    ax.set_xticks(range(len(values)), labels)
    ax.set_ylabel("总碳 kg")
    ax.set_title("F3 两层减碳柱图备版")
    for idx, value in enumerate(values):
        ax.text(idx, value * 1.01, f"{value:.0f}", ha="center", fontsize=8)
    ax.margins(y=0.16)
    return save_pdf_png(fig, output_stem)


def figure_f4_48slot_charging(csv_path: str | Path, output_stem: str | Path) -> tuple[Path, Path]:
    setup_matplotlib()
    from matplotlib import pyplot as plt

    rows = _read_rows(csv_path)
    scenarios = ["朴素充电", "碳感知充电"]
    fig, axes = plt.subplots(1, 2, figsize=cm_to_inch(16.0, 6.8), constrained_layout=True)
    gamma_rows = [row for row in rows if row["scenario"] == scenarios[0]]
    x = [float(row["hour"]) for row in gamma_rows]
    gamma = [float(row["gamma_gco2_per_kwh"]) for row in gamma_rows]
    axes[0].axvspan(8, 17, color=PALETTE["light_gray"], alpha=0.55, label="日间作业窗")
    ax2 = axes[0].twinx()
    axes[0].plot(x, gamma, color=PALETTE["dark"], linewidth=0.9, linestyle="-", label="$\\gamma$")
    offsets = {"朴素充电": -0.09, "碳感知充电": 0.09}
    colors = {"朴素充电": PALETTE["red"], "碳感知充电": PALETTE["green"]}
    hatches = {"朴素充电": "//", "碳感知充电": ""}
    for scenario in scenarios:
        data = [row for row in rows if row["scenario"] == scenario]
        x = [float(row["hour"]) for row in data]
        kwh = [float(row["total_kwh"]) for row in data]
        shifted = [value + offsets[scenario] for value in x]
        ax2.bar(shifted, kwh, width=0.16, color=colors[scenario], alpha=0.78, hatch=hatches[scenario], label=scenario)
    axes[0].set_title("(a) 48槽碳强度与充电负荷")
    axes[0].set_xlabel("时间 / h")
    axes[0].set_ylabel("$\\gamma$ gCO2/kWh")
    axes[0].set_xlim(0, 24)
    ax2.set_ylabel("充电 kWh")
    ax2.set_ylim(bottom=0)
    axes[0].legend(loc="upper left", fontsize=7)
    ax2.legend(loc="upper right", fontsize=7)

    shares = charging_period_shares(rows)
    bottoms = {scenario: 0.0 for scenario in scenarios}
    share_colors = {"谷": PALETTE["green"], "平": PALETTE["gray"], "峰": PALETTE["red"]}
    share_hatches = {"谷": "", "平": "..", "峰": "//"}
    xpos = range(len(scenarios))
    for period in ("谷", "平", "峰"):
        values = [shares.get(scenario, {}).get(period, 0.0) * 100.0 for scenario in scenarios]
        axes[1].bar(xpos, values, bottom=[bottoms[scenario] * 100.0 for scenario in scenarios], color=share_colors[period], hatch=share_hatches[period], width=0.55, label=period, edgecolor=PALETTE["dark"], linewidth=0.55)
        for scenario, value in zip(scenarios, values):
            bottoms[scenario] += value / 100.0
    axes[1].set_xticks(list(xpos), scenarios)
    axes[1].set_ylim(0, 100)
    axes[1].set_ylabel("充电量占比 %")
    axes[1].set_title("(b) 峰/平/谷充电占比")
    axes[1].legend(loc="upper center", ncols=3, fontsize=7)
    return save_pdf_png(fig, output_stem)


def figure_f5_carbon_heatmap(csv_path: str | Path, output_stem: str | Path, *, watermark: bool = True) -> tuple[Path, Path]:
    setup_matplotlib()
    from matplotlib import pyplot as plt

    rows = _read_rows(csv_path)
    prices = sorted({row["carbon_price"] for row in rows}, key=float)
    quotas = sorted({row["quota"] for row in rows}, key=float)
    grid = [[_value_for(rows, price, quota, "total_carbon_kg") for price in prices] for quota in quotas]
    fig, ax = plt.subplots(figsize=cm_to_inch(8.0, 6.2))
    image = ax.imshow(grid, cmap="YlGnBu", aspect="auto")
    ax.set_xticks(range(len(prices)), prices)
    ax.set_yticks(range(len(quotas)), quotas)
    ax.set_xlabel("碳价档")
    ax.set_ylabel("配额档")
    ax.set_title("F5 碳敏感热力图")
    for y, row in enumerate(grid):
        for x, value in enumerate(row):
            ax.text(x, y, f"{value:.0f}", ha="center", va="center", fontsize=8)
    fig.colorbar(image, ax=ax, label="总碳 kg")
    if watermark:
        sample_watermark(ax)
    return save_pdf_png(fig, output_stem)


def figure_f6_fairness_frontier(csv_path: str | Path, output_stem: str | Path, *, watermark: bool = True) -> tuple[Path, Path]:
    setup_matplotlib()
    from matplotlib import pyplot as plt

    rows = [row for row in _read_rows(csv_path) if row.get("theta", row.get("$\\theta$", "")) not in {"off", "关闭"}]
    xs = [float(row.get("theta", row.get("$\\theta$", "0"))) for row in rows]
    ratio_values = [_float_or_none(row.get("cost_ratio_to_independent", row.get("总成本/独立运营总成本", ""))) for row in rows]
    # v2026-06-13: Formal W2 F6 source has infeasible theta rows and no
    # independent-cost ratio column. Fall back to observed total_cost and mark
    # infeasible theta values as disconnected points instead of fabricating ratios.
    use_ratio_axis = any(value is not None for value in ratio_values)
    ys = ratio_values if use_ratio_axis else [_float_or_none(row.get("total_cost", row.get("总成本", ""))) for row in rows]
    feasible = [_is_yes(row.get("feasible", row.get("可行", ""))) and y is not None for row, y in zip(rows, ys)]
    fig, ax = plt.subplots(figsize=cm_to_inch(8.0, 5.6))
    feasible_x = [x for x, y, ok in zip(xs, ys, feasible) if ok and y is not None]
    feasible_y = [float(y) for y, ok in zip(ys, feasible) if ok and y is not None]
    ax.plot(feasible_x, feasible_y, color=PALETTE["blue"], linestyle="-", marker="o", markersize=4, label="可行前沿")
    marker_y = max(feasible_y) * 1.01 if feasible_y else 1.0
    for x, y, ok in zip(xs, ys, feasible):
        if not ok:
            y = float(y) if y is not None else marker_y
            ax.scatter([x], [y], marker="x", color=PALETTE["red"], s=36, label="不可行" if "不可行" not in ax.get_legend_handles_labels()[1] else None)
            ax.annotate("不可行", (x, y), xytext=(4, 6), textcoords="offset points", fontsize=8)
    ax.set_xlabel("$\\theta$")
    ax.set_ylabel("总成本/独立运营总成本" if use_ratio_axis else "总成本")
    ax.set_title("F6 公平前沿")
    ax.legend(loc="best", fontsize=8)
    if watermark:
        sample_watermark(ax)
    return save_pdf_png(fig, output_stem)


def _read_rows(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _value_for(rows: list[dict[str, str]], price: str, quota: str, key: str) -> float:
    for row in rows:
        if row["carbon_price"] == price and row["quota"] == quota:
            return float(row[key])
    raise KeyError((price, quota, key))


def _float_or_none(value: object) -> float | None:
    text = "" if value is None else str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def charging_period_shares(rows: list[dict[str, str]]) -> dict[str, dict[str, float]]:
    gamma_values = sorted({float(row["gamma_gco2_per_kwh"]) for row in rows})
    if not gamma_values:
        return {}
    lower = gamma_values[max(0, len(gamma_values) // 3 - 1)]
    upper = gamma_values[min(len(gamma_values) - 1, (len(gamma_values) * 2) // 3)]
    totals: dict[str, dict[str, float]] = defaultdict(lambda: {"谷": 0.0, "平": 0.0, "峰": 0.0})
    scenario_totals: dict[str, float] = defaultdict(float)
    for row in rows:
        scenario = row["scenario"]
        gamma = float(row["gamma_gco2_per_kwh"])
        kwh = float(row["total_kwh"])
        if gamma <= lower:
            period = "谷"
        elif gamma >= upper:
            period = "峰"
        else:
            period = "平"
        totals[scenario][period] += kwh
        scenario_totals[scenario] += kwh
    return {
        scenario: {period: round(value / scenario_totals[scenario], 2) if scenario_totals[scenario] else 0.0 for period, value in values.items()}
        for scenario, values in totals.items()
    }


def _is_yes(value: object) -> bool:
    return str(value).strip().lower() in {"true", "yes", "1", "是"}


def _scale_bar(ax) -> None:
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    length = max(1.0, round((x1 - x0) / 5.0, 1))
    start_x = x0 + (x1 - x0) * 0.06
    start_y = y0 + (y1 - y0) * 0.07
    ax.plot([start_x, start_x + length], [start_y, start_y], color="#111827", linewidth=2.2)
    ax.text(start_x + length / 2.0, start_y + (y1 - y0) * 0.02, f"{length:g} km", ha="center", fontsize=8)


def _draw_nodes(ax, nodes: dict[str, dict[str, str]], depot_colors: dict[str, str]) -> None:
    for row in nodes.values():
        x, y = float(row["x"]), float(row["y"])
        node_type = row["node_type"]
        if node_type in {"d", "车场"}:
            ax.scatter(x, y, marker="*", s=130, color=depot_colors.get(row["node_id"], PALETTE["dark"]), edgecolor=PALETTE["dark"], linewidth=0.7, zorder=5, label="车场" if "车场" not in ax.get_legend_handles_labels()[1] else None)
            ax.text(x, y + 2.5, row["node_id"], ha="center", fontsize=8)
        elif node_type in {"f", "站点", "充电站"}:
            ax.scatter(x, y, marker="^", s=60, color="white", edgecolor=PALETTE["dark"], linewidth=0.85, zorder=5, label="充电站" if "充电站" not in ax.get_legend_handles_labels()[1] else None)
        else:
            edge_width = 1.7 if _is_yes(row.get("cross_site", "")) else 0.45
            ax.scatter(x, y, marker="o", s=28, color=depot_colors.get(row.get("service_depot", ""), PALETTE["purple"]), edgecolor=PALETTE["dark"], linewidth=edge_width, zorder=4, label="客户" if "客户" not in ax.get_legend_handles_labels()[1] else None)
