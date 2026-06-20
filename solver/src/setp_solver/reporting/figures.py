from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev, stdev

from .style import DOUBLE_COL_FIGSIZE, LINE_STYLES, MARKERS, PALETTE, SINGLE_COL_FIGSIZE, cm_to_inch, sample_watermark, save_pdf_png, setup_matplotlib


CARBON_MAIN_PRICE_GBP_PER_TONNE = 50.34

ALGORITHM_DISPLAY_LABELS = {
    "ALNS-Wouda": "ALNS",
    "ALNS@wangqianlongucas": "ALNS-WQL",
    "NSGA-II@haris989": "NSGA-II",
    "VNS@Valdecy": "VNS",
    "scikit-opt-GA": "GA",
    "scikit-opt-SA": "SA",
}


def _algorithm_label(name: str) -> str:
    return ALGORITHM_DISPLAY_LABELS.get(name, name)


def figure_f1_route_map(nodes_csv: str | Path, routes_csv: str | Path, output_stem: str | Path, *, watermark: bool = True) -> tuple[Path, Path]:
    setup_matplotlib()
    from matplotlib.lines import Line2D
    from matplotlib import pyplot as plt

    nodes = {row["node_id"]: row for row in _read_rows(nodes_csv)}
    routes = _read_rows(routes_csv)
    fig, axes = plt.subplots(1, 2, figsize=DOUBLE_COL_FIGSIZE)
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
            markersize=2.6,
            linewidth=0.85,
        )
    _draw_nodes(axes[1], nodes, depot_colors)
    axes[1].set_title("(b) 路线方案")

    for ax in axes:
        _scale_bar(ax)
        ax.set_xlabel("横坐标 / km")
        ax.set_ylabel("纵坐标 / km")
        ax.set_aspect("equal", adjustable="box")
    axes[1].legend(
        handles=[
            Line2D([0], [0], color=PALETTE["gray"], linestyle="-", linewidth=0.9, label="燃油车路线"),
            Line2D([0], [0], color=PALETTE["gray"], linestyle="--", linewidth=0.9, label="电动车路线"),
        ],
        loc="upper right",
        fontsize=7,
        handlelength=1.5,
        borderaxespad=0.25,
    )
    fig.subplots_adjust(left=0.075, right=0.985, bottom=0.14, top=0.88, wspace=0.24)
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
    fig, axes = plt.subplots(1, 2, figsize=DOUBLE_COL_FIGSIZE, constrained_layout=True)
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
        axes[0].step(xs, ys, where="post", color=color, linestyle=LINE_STYLES[idx % len(LINE_STYLES)], marker=MARKERS[idx % len(MARKERS)], markersize=2.7, label=_algorithm_label(algorithm))
        axes[0].fill_between(xs, [y - s for y, s in zip(ys, std)], [y + s for y, s in zip(ys, std)], step="post", color=color, alpha=0.10)
    axes[0].set_title("(a) 收敛曲线")
    axes[0].set_xlabel("评估次数")
    axes[0].set_ylabel("最优目标")
    grouped = [[float(row["final_obj"]) for row in final_rows if row["algorithm"] == algorithm] for algorithm in algorithms]
    axes[1].boxplot(grouped, tick_labels=[_algorithm_label(algorithm) for algorithm in algorithms], patch_artist=True)
    axes[1].tick_params(axis="x", rotation=28)
    axes[1].set_title("(b) 终值分布")
    axes[1].set_ylabel("目标")
    axes[0].legend(ncols=2, fontsize=6.8, handlelength=1.35, columnspacing=0.85, borderaxespad=0.2)
    if watermark:
        for ax in axes:
            sample_watermark(ax)
    return save_pdf_png(fig, output_stem)


F3_STAGE_LABELS = {"纯油车": "纯油车（同路线动力替换）"}


def _f3_stage_label(stage: str) -> str:
    return F3_STAGE_LABELS.get(stage, stage)


def figure_f3_two_layer_waterfall(csv_path: str | Path, output_stem: str | Path) -> tuple[Path, Path]:
    setup_matplotlib()
    from matplotlib import pyplot as plt

    rows = _read_rows(csv_path)
    labels = [_f3_stage_label(row["stage"]) for row in rows]
    values = [float(row["total_carbon_kg"]) for row in rows]
    fig, ax = plt.subplots(figsize=SINGLE_COL_FIGSIZE, constrained_layout=True)
    xs = list(range(len(values)))
    ax.bar(xs, values, color=[PALETTE["gray"], PALETTE["blue"], PALETTE["green"]], width=0.62)
    for i in range(1, len(values)):
        delta = values[i] - values[i - 1]
        pct = delta / values[i - 1] * 100.0 if values[i - 1] else 0.0
        y = max(values[i], values[i - 1])
        ax.plot([i - 1, i], [y, y], color="#334155", linewidth=0.9)
        ax.text(i - 0.5, y * 1.01, f"{delta:+.1f} kg ({pct:+.1f}%)", ha="center", fontsize=8)
    ax.set_xticks(xs, labels)
    ax.tick_params(axis="x", labelsize=7)
    ax.set_xlabel("阶段（纯油车为同路线动力替换基线）", fontsize=8)
    ax.set_ylabel("总碳 kg")
    ax.set_title("F3 两层减碳瀑布")
    ax.margins(y=0.18)
    return save_pdf_png(fig, output_stem)


def figure_f3_two_layer_bars(csv_path: str | Path, output_stem: str | Path) -> tuple[Path, Path]:
    setup_matplotlib()
    from matplotlib import pyplot as plt

    rows = _read_rows(csv_path)
    labels = [_f3_stage_label(row["stage"]) for row in rows]
    values = [float(row["total_carbon_kg"]) for row in rows]
    fig, ax = plt.subplots(figsize=SINGLE_COL_FIGSIZE, constrained_layout=True)
    ax.bar(range(len(values)), values, color=[PALETTE["gray"], PALETTE["blue"], PALETTE["green"]], width=0.58, edgecolor=PALETTE["dark"], linewidth=0.7)
    ax.set_xticks(range(len(values)), labels)
    ax.tick_params(axis="x", labelsize=7)
    ax.set_xlabel("阶段（纯油车为同路线动力替换基线）", fontsize=8)
    ax.set_ylabel("总碳 kg")
    ax.set_title("F3 两层减碳柱图备版")
    for idx, value in enumerate(values):
        ax.text(idx, value * 1.01, f"{value:.0f}", ha="center", fontsize=8)
    ax.margins(y=0.16)
    return save_pdf_png(fig, output_stem)


def figure_f4_48slot_charging(csv_path: str | Path, output_stem: str | Path) -> tuple[Path, Path]:
    setup_matplotlib()
    from matplotlib import pyplot as plt

    rows = _f4_normalized_rows(_read_rows(csv_path))
    if not rows:
        raise ValueError("F4 charging source has no rows")
    scenarios = ["朴素充电", "碳感知充电"]
    fig, axes = plt.subplots(1, 2, figsize=DOUBLE_COL_FIGSIZE, constrained_layout=True)
    gamma_rows = _f4_gamma_baseline(rows)
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
    max_kwh = max((float(row["total_kwh"]) for row in rows), default=0.0)
    ax2.set_ylim(0, max(max_kwh * 1.15, 1.0))
    axes[0].legend(loc="upper left", fontsize=7, handlelength=1.3)
    ax2.legend(loc="upper right", fontsize=7, handlelength=1.3)

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


F4_SCENARIO_LABELS = {
    "naive_return_charge": "朴素充电",
    "carbon_aware": "碳感知充电",
    "朴素充电": "朴素充电",
    "碳感知充电": "碳感知充电",
}


def _f4_normalized_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    normalized = []
    for row in rows:
        scenario = F4_SCENARIO_LABELS.get(str(row.get("scenario", "")).strip(), str(row.get("scenario", "")).strip())
        if scenario not in {"朴素充电", "碳感知充电"}:
            continue
        item = dict(row)
        item["scenario"] = scenario
        item["hour"] = f"{_f4_hour(row):.6f}"
        normalized.append(item)
    return sorted(normalized, key=lambda item: (item["scenario"], float(item["hour"])))


def _f4_hour(row: dict[str, str]) -> float:
    if str(row.get("hour", "")).strip():
        return float(row["hour"])
    if str(row.get("horizon_second_start", "")).strip():
        return float(row["horizon_second_start"]) / 3600.0
    if str(row.get("slot_index", "")).strip():
        return float(row["slot_index"]) * 0.5
    raise KeyError("F4 row needs one of hour, horizon_second_start, or slot_index")


def _f4_gamma_baseline(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    by_hour: dict[float, dict[str, str]] = {}
    for row in rows:
        hour = round(float(row["hour"]), 6)
        by_hour.setdefault(hour, row)
    return [by_hour[hour] for hour in sorted(by_hour)]


def figure_f5_carbon_heatmap(csv_path: str | Path, output_stem: str | Path, *, watermark: bool = True) -> tuple[Path, Path]:
    setup_matplotlib()
    from matplotlib import pyplot as plt

    rows = _read_rows(csv_path)
    prices = sorted({row["carbon_price"] for row in rows}, key=float)
    quotas = sorted({row["quota"] for row in rows}, key=float)
    grid = [[_value_for(rows, price, quota, "total_carbon_kg") for price in prices] for quota in quotas]
    fig, ax = plt.subplots(figsize=SINGLE_COL_FIGSIZE, constrained_layout=True)
    image = ax.imshow(grid, cmap="YlGnBu", aspect="auto")
    ax.set_xticks(range(len(prices)), prices)
    ax.set_yticks(range(len(quotas)), quotas)
    ax.set_xlabel("碳价档")
    ax.set_ylabel("配额档")
    ax.set_title("F5 碳敏感热力图")
    for y, row in enumerate(grid):
        for x, value in enumerate(row):
            ax.text(x, y, f"{value:.0f}", ha="center", va="center", fontsize=8)
    fig.colorbar(image, ax=ax, label="总碳 kg", fraction=0.055, pad=0.03)
    if watermark:
        sample_watermark(ax)
    return save_pdf_png(fig, output_stem)


def figure_f5b_carbon_stress(means_csv: str | Path, seed_detail_csv: str | Path, output_stem: str | Path) -> tuple[Path, Path]:
    setup_matplotlib()
    from matplotlib import pyplot as plt

    points = carbon_stress_points(means_csv, seed_detail_csv)
    prices = [point["price_gbp_per_tonne"] for point in points]
    carbon_means = [point["carbon_mean"] for point in points]
    carbon_stds = [point["carbon_std"] for point in points]
    ev_counts = [point["ev_count"] for point in points]
    threshold = 32.0 * CARBON_MAIN_PRICE_GBP_PER_TONNE

    fig, ax = plt.subplots(figsize=SINGLE_COL_FIGSIZE, constrained_layout=True)
    ax.errorbar(
        prices,
        carbon_means,
        yerr=carbon_stds,
        color=PALETTE["blue"],
        marker=MARKERS[0],
        markersize=4,
        linestyle=LINE_STYLES[0],
        linewidth=1.05,
        capsize=2.4,
        elinewidth=0.8,
        label="总碳排放",
    )
    ax.set_xscale("log")
    ax.set_xticks(prices)
    ax.set_xticklabels([f"{price:.0f}" for price in prices], rotation=32, ha="right")
    ax.tick_params(axis="x", labelsize=8)
    ax.set_xlabel("碳价 / $£$/tCO$_2$e")
    ax.set_ylabel("总碳排放 kgCO$_2$e")
    ax.set_title("F5b 碳价压力曲线")
    ax.margins(x=0.05, y=0.18)

    ax2 = ax.twinx()
    ax2.plot(
        prices,
        ev_counts,
        color=PALETTE["green"],
        marker=MARKERS[1],
        markersize=3.8,
        linestyle=LINE_STYLES[1],
        linewidth=1.0,
        label="电动车路线数",
    )
    ax2.set_ylabel("电动车路线数")

    ax.axvline(threshold, color=PALETTE["red"], linestyle=LINE_STYLES[1], linewidth=0.85)
    ax.annotate(
        "阈值≈30×主值",
        xy=(threshold, 0.95),
        xycoords=ax.get_xaxis_transform(),
        xytext=(4, -4),
        textcoords="offset points",
        color=PALETTE["red"],
        fontsize=8,
        ha="left",
        va="top",
    )

    handles, labels = ax.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(handles + handles2, labels + labels2, loc="best", fontsize=8)
    return save_pdf_png(fig, output_stem)


def carbon_stress_points(means_csv: str | Path, seed_detail_csv: str | Path) -> list[dict[str, float]]:
    mean_rows = sorted(_read_rows(means_csv), key=lambda row: float(row["carbon_price"]))
    seed_rows = _read_rows(seed_detail_csv)
    carbon_by_factor: dict[float, list[float]] = defaultdict(list)
    for row in seed_rows:
        factor_text = row.get("carbon_price", row.get("price_factor", ""))
        carbon_text = row.get("total_carbon_kg", "")
        if factor_text == "" or carbon_text == "":
            continue
        carbon_by_factor[float(factor_text)].append(float(carbon_text))

    points: list[dict[str, float]] = []
    for row in mean_rows:
        factor = float(row["carbon_price"])
        carbon_values = carbon_by_factor.get(factor, [])
        points.append(
            {
                "factor": factor,
                "price_gbp_per_tonne": factor * CARBON_MAIN_PRICE_GBP_PER_TONNE,
                "carbon_mean": float(row["total_carbon_kg"]),
                "carbon_std": stdev(carbon_values) if len(carbon_values) > 1 else 0.0,
                "ev_count": float(row["ev_count"]),
            }
        )
    return points


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
    fig, ax = plt.subplots(figsize=SINGLE_COL_FIGSIZE, constrained_layout=True)
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
