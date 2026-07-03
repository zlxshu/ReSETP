from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev, stdev

from .style import DOUBLE_COL_FIGSIZE, LINE_STYLES, MARKERS, PALETTE, SINGLE_COL_FIGSIZE, cm_to_inch, sample_watermark, save_pdf_png, setup_matplotlib


CARBON_MAIN_PRICE_GBP_PER_TONNE = 50.34

ALGORITHM_DISPLAY_LABELS = {
    "ALNS-Wouda": "ALNS",
    "ALNS@wangqianlongucas": "ALNS",
    "ALNS-WQL": "ALNS",
    "PyGAD": "GA",
    "NSGA-II@haris989": "NSGA-II",
    "VNS@Valdecy": "VNS",
    "scikit-opt-GA": "GA",
    "scikit-opt-SA": "SA",
    "winner kernel": "ALNS",
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
    route_style = {
        "cv": (PALETTE["blue"], "-"),
        "油车": (PALETTE["blue"], "-"),
        "ev": (PALETTE["green"], "--"),
        "电车": (PALETTE["green"], "--"),
    }

    _draw_nodes(axes[0], nodes, depot_colors)
    axes[0].set_title("(a) 节点地理分布")

    for idx, route in enumerate(routes):
        seq = [item for item in route["node_sequence"].split(">") if item in nodes]
        xs = [float(nodes[item]["x"]) for item in seq]
        ys = [float(nodes[item]["y"]) for item in seq]
        vehicle_key = route["vehicle_type"].lower()
        color, linestyle = route_style.get(vehicle_key, route_style.get(route["vehicle_type"], (PALETTE["gray"], "-")))
        axes[1].plot(
            xs,
            ys,
            color=color,
            linestyle=linestyle,
            marker=MARKERS[idx % len(MARKERS)],
            markersize=2.6,
            linewidth=0.75 + 0.08 * (idx % 3),
            alpha=0.74 + 0.08 * (idx % 2),
        )
    _draw_nodes(axes[1], nodes, depot_colors)
    axes[1].set_title("(b) 路线方案")

    for ax in axes:
        ax.set_xlabel("x 坐标")
        ax.set_ylabel("y 坐标")
        ax.set_aspect("equal", adjustable="box")
    axes[1].legend(
        handles=[
            Line2D([0], [0], color=PALETTE["blue"], linestyle="-", linewidth=0.9, label="燃油车路线"),
            Line2D([0], [0], color=PALETTE["green"], linestyle="--", linewidth=0.9, label="电动车路线"),
            Line2D([0], [0], marker="o", color="none", markerfacecolor="white", markeredgecolor=PALETTE["dark"], markeredgewidth=1.7, markersize=5, label="跨场服务客户（黑色描边）"),
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
    if curve_rows and "instance" in curve_rows[0]:
        return _figure_f2_faceted_algorithm_performance(curve_rows, final_rows, output_stem, watermark=watermark)
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


def _figure_f2_faceted_algorithm_performance(curve_rows: list[dict[str, str]], final_rows: list[dict[str, str]], output_stem: str | Path, *, watermark: bool) -> tuple[Path, Path]:
    from matplotlib import pyplot as plt

    instances = sorted({row["instance"] for row in curve_rows})
    algorithms = sorted({row["algorithm"] for row in curve_rows})
    colors = [PALETTE["blue"], PALETTE["green"], PALETTE["red"], PALETTE["purple"], PALETTE["amber"], PALETTE["sky"]]
    fig, axes = plt.subplots(2, len(instances), figsize=(DOUBLE_COL_FIGSIZE[0], DOUBLE_COL_FIGSIZE[1] * 1.24), squeeze=False, constrained_layout=True)
    for ax, instance in zip(axes[0], instances):
        instance_rows = [row for row in curve_rows if row["instance"] == instance]
        ref_values = [float(row["reference_best"]) for row in instance_rows if row.get("reference_best")]
        if ref_values:
            ax.axhline(ref_values[0], color=PALETTE["dark"], linestyle=":", linewidth=0.85, label="已观测最优")
        for idx, algorithm in enumerate(algorithms):
            by_eval: dict[int, list[float]] = defaultdict(list)
            for row in instance_rows:
                if row["algorithm"] == algorithm:
                    by_eval[int(float(row["evals"]))].append(float(row["best_obj"]))
            if not by_eval:
                continue
            xs = sorted(by_eval)
            median = [_median(by_eval[x]) for x in xs]
            q1 = [_percentile(by_eval[x], 0.25) for x in xs]
            q3 = [_percentile(by_eval[x], 0.75) for x in xs]
            color = colors[idx % len(colors)]
            ax.plot(xs, median, color=color, linestyle=LINE_STYLES[idx % len(LINE_STYLES)], marker=MARKERS[idx % len(MARKERS)], markersize=2.5, label=_algorithm_label(algorithm))
            ax.fill_between(xs, q1, q3, color=color, alpha=0.10)
        ax.set_title(f"(a) {instance} 收敛曲线")
        ax.set_xlabel("评估次数")
        ax.set_ylabel("最优目标")
        ax.tick_params(axis="x", labelrotation=20)
    for ax, instance in zip(axes[1], instances):
        grouped = []
        labels = []
        for algorithm in algorithms:
            values = [float(row["final_obj"]) for row in final_rows if row.get("instance") == instance and row["algorithm"] == algorithm]
            if values:
                grouped.append(values)
                labels.append(_algorithm_label(algorithm))
        boxes = ax.boxplot(grouped, tick_labels=labels, patch_artist=True, widths=0.58)
        for idx, patch in enumerate(boxes["boxes"]):
            patch.set_facecolor(colors[idx % len(colors)])
            patch.set_alpha(0.24)
            patch.set_edgecolor(PALETTE["dark"])
        ax.set_title(f"(b) {instance} 终值箱线图")
        ax.set_ylabel("终值目标")
        ax.tick_params(axis="x", rotation=24)
    axes[0][0].legend(ncols=2, fontsize=6.8, handlelength=1.35, columnspacing=0.85)
    if watermark:
        for row in axes:
            for ax in row:
                sample_watermark(ax)
    return save_pdf_png(fig, output_stem)


F3_STAGE_LABELS = {"纯油车": "纯油车（同路线动力替换）"}


def _f3_stage_label(stage: str) -> str:
    return F3_STAGE_LABELS.get(stage, stage)


def figure_f3_two_layer_waterfall(csv_path: str | Path, output_stem: str | Path, *, watermark: bool = False) -> tuple[Path, Path]:
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
    ax.set_title("两层减碳链")
    ax.margins(y=0.18)
    if watermark:
        sample_watermark(ax)
    return save_pdf_png(fig, output_stem)


def figure_f3_two_layer_bars(csv_path: str | Path, output_stem: str | Path, *, watermark: bool = False) -> tuple[Path, Path]:
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
    ax.set_title("两层排放分解")
    for idx, value in enumerate(values):
        ax.text(idx, value * 1.01, f"{value:.0f}", ha="center", fontsize=8)
    ax.margins(y=0.16)
    if watermark:
        sample_watermark(ax)
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


def figure_f5_carbon_response(csv_path: str | Path, output_stem: str | Path, *, watermark: bool = True) -> tuple[Path, Path]:
    setup_matplotlib()
    from matplotlib import pyplot as plt

    rows = sorted(_read_rows(csv_path), key=lambda row: float(row["price_gbp_per_tonne"]))
    if not rows:
        raise ValueError("F5 carbon response source has no rows")
    near_rows = [row for row in rows if row.get("panel") == "现实邻域"] or rows[: min(4, len(rows))]
    stress_rows = [row for row in rows if row.get("panel") == "宽域压力"] or rows
    fig, axes = plt.subplots(1, 2, figsize=DOUBLE_COL_FIGSIZE, constrained_layout=True)
    _draw_carbon_response_panel(axes[0], near_rows, title="(a) 现实邻域")
    _draw_carbon_response_panel(axes[1], stress_rows, title="(b) 宽域压力", log_x=True, shade_threshold=True)
    if watermark:
        for ax in axes:
            sample_watermark(ax)
    return save_pdf_png(fig, output_stem)


def _draw_carbon_response_panel(ax, rows: list[dict[str, str]], *, title: str, log_x: bool = False, shade_threshold: bool = False) -> None:
    prices = [float(row["price_gbp_per_tonne"]) for row in rows]
    carbon = [float(row["total_carbon_mean"]) for row in rows]
    carbon_std = [float(row.get("total_carbon_std", "0") or 0.0) for row in rows]
    ev_routes = [float(row.get("ev_routes", "0") or 0.0) for row in rows]
    ax.errorbar(prices, carbon, yerr=carbon_std, color=PALETTE["blue"], marker=MARKERS[0], linestyle="-", capsize=2.2, label="总排放")
    ax.set_xlabel("碳价/(GBP/tCO$_2$e)")
    ax.set_ylabel("总排放 kgCO$_2$e")
    ax.set_title(title)
    if log_x:
        ax.set_xscale("log")
    if shade_threshold and len(prices) >= 2:
        threshold = prices[min(3, len(prices) - 1)]
        ax.axvspan(threshold, max(prices), color=PALETTE["light_gray"], alpha=0.35)
        ax.annotate("响应阈值区间", xy=(threshold, max(carbon)), xytext=(3, -12), textcoords="offset points", fontsize=7, color=PALETTE["dark"])
    ax2 = ax.twinx()
    ax2.plot(prices, ev_routes, color=PALETTE["green"], marker=MARKERS[1], linestyle="--", label="电车路线数")
    ax2.set_ylabel("电车路线数")
    handles, labels = ax.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(handles + handles2, labels + labels2, fontsize=6.8, loc="best")


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
    ax.set_xlabel("碳价/(GBP/tCO$_2$e)")
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
    has_cross_site = any(str(row.get("cross_site_customers", row.get("跨场服务数", ""))).strip() for row in rows)
    if has_cross_site:
        fig, axes = plt.subplots(1, 2, figsize=DOUBLE_COL_FIGSIZE, constrained_layout=True)
        ax = axes[0]
    else:
        fig, ax = plt.subplots(figsize=SINGLE_COL_FIGSIZE, constrained_layout=True)
        axes = [ax]
    feasible_x = [x for x, y, ok in zip(xs, ys, feasible) if ok and y is not None]
    feasible_y = [float(y) for y, ok in zip(ys, feasible) if ok and y is not None]
    ax.plot(feasible_x, feasible_y, color=PALETTE["blue"], linestyle="-", marker="o", markersize=4, label="可行前沿")
    if feasible_x:
        natural = min(feasible_x, key=lambda item: abs(item - 1.0))
        ax.axvline(natural, color=PALETTE["dark"], linestyle=":", linewidth=0.8, label="自然比值附近")
    marker_y = max(feasible_y) * 1.01 if feasible_y else 1.0
    for x, y, ok in zip(xs, ys, feasible):
        if not ok:
            y = float(y) if y is not None else marker_y
            ax.axvspan(x - 0.005, x + 0.005, color=PALETTE["red"], alpha=0.12)
    ax.set_xlabel("$\\theta$")
    ax.set_ylabel("总成本/独立运营总成本" if use_ratio_axis else "总成本")
    ax.set_title("(a) 公平代价曲线" if has_cross_site else "公平代价曲线")
    ax.legend(loc="best", fontsize=8)
    if has_cross_site:
        ax_cs = axes[1]
        cross_site = [_float_or_none(row.get("cross_site_customers", row.get("跨场服务数", ""))) for row in rows]
        cs_x = [x for x, value, ok in zip(xs, cross_site, feasible) if ok and value is not None]
        cs_y = [float(value) for value, ok in zip(cross_site, feasible) if ok and value is not None]
        ax_cs.plot(cs_x, cs_y, color=PALETTE["purple"], marker=MARKERS[1], linestyle="--", label="跨场服务数")
        for x, ok in zip(xs, feasible):
            if not ok:
                ax_cs.axvspan(x - 0.005, x + 0.005, color=PALETTE["red"], alpha=0.12)
        ax_cs.set_xlabel("$\\theta$")
        ax_cs.set_ylabel("跨场服务数")
        ax_cs.set_title("(b) 协同收缩")
        ax_cs.legend(loc="best", fontsize=8)
    if watermark:
        for item in axes:
            sample_watermark(item)
    return save_pdf_png(fig, output_stem)


def figure_f7_dynamic_timeline(csv_path: str | Path, output_stem: str | Path, *, watermark: bool = True) -> tuple[Path, Path]:
    setup_matplotlib()
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    from matplotlib import pyplot as plt

    rows = sorted(_read_rows(csv_path), key=lambda row: (row.get("vehicle_id", ""), float(row["stage_start_h"])))
    if not rows:
        raise ValueError("F7 dynamic source has no rows")
    fig, axes = plt.subplots(3, 1, figsize=(DOUBLE_COL_FIGSIZE[0], DOUBLE_COL_FIGSIZE[1] * 1.12), sharex=True, constrained_layout=True, gridspec_kw={"height_ratios": [1.15, 1.0, 1.12]})
    vehicles = sorted({row.get("vehicle_id", "代表事件流") or "代表事件流" for row in rows})
    y_by_vehicle = {vehicle: idx for idx, vehicle in enumerate(vehicles)}
    segment_colors = {"冻结段": PALETTE["gray"], "重规划段": PALETTE["sky"]}
    for row in rows:
        start = float(row["stage_start_h"])
        end = float(row["stage_end_h"])
        vehicle = row.get("vehicle_id", "代表事件流") or "代表事件流"
        color = segment_colors.get(row.get("segment_type", ""), PALETTE["light_gray"])
        axes[0].barh([y_by_vehicle[vehicle]], [max(end - start, 0.01)], left=[start], height=0.42, color=color, edgecolor=PALETTE["dark"], linewidth=0.55, zorder=2)
    event_markers = {"新增": "^", "取消": "x", "变更": "D"}
    event_labels = {"新增": "新增 ▲", "取消": r"取消 $\times$", "变更": "变更 ◆"}
    seen_events: set[tuple[str, float]] = set()
    event_y = len(vehicles) - 0.10
    for row in rows:
        event_type = row.get("event_type", "")
        event_time = row.get("event_time_h", "")
        if not event_type or not event_time:
            continue
        key = (event_type, float(event_time))
        if key in seen_events:
            continue
        seen_events.add(key)
        marker = event_markers.get(event_type, "o")
        if marker == "x":
            axes[0].scatter([float(event_time)], [event_y], marker=marker, s=42, color=PALETTE["red"], linewidth=0.8, zorder=5)
        else:
            axes[0].scatter([float(event_time)], [event_y], marker=marker, s=42, color=PALETTE["red"], edgecolor=PALETTE["dark"], linewidth=0.45, zorder=5)
        axes[0].axvline(float(event_time), color=PALETTE["red"], linestyle=":", linewidth=0.55, alpha=0.55, zorder=1)
    axes[0].set_yticks(list(y_by_vehicle.values()), vehicles)
    axes[0].set_ylim(-0.6, len(vehicles) + 0.35)
    axes[0].set_title("(a) 事件到达与冻结/重规划段")
    axes[0].legend(
        handles=[
            Patch(facecolor=PALETTE["gray"], edgecolor=PALETTE["dark"], label="冻结段"),
            Patch(facecolor=PALETTE["sky"], edgecolor=PALETTE["dark"], label="重规划段"),
            *[Line2D([0], [0], marker=marker, color="none", markerfacecolor=PALETTE["red"], markeredgecolor=PALETTE["dark"], markersize=5, label=event_labels[event]) for event, marker in event_markers.items()],
        ],
        loc="upper right",
        ncols=3,
        fontsize=6.6,
    )

    stage_rows = _f7_stage_metric_rows(rows)
    xs = [float(row["stage_end_h"]) for row in stage_rows]
    cost = [float(row["cumulative_cost"]) for row in stage_rows]
    carbon = [float(row["cumulative_carbon_kg"]) for row in stage_rows]
    hindsight = [float(row["hindsight_cost"]) for row in stage_rows]
    axes[1].step(xs, cost, where="post", color=PALETTE["blue"], marker=MARKERS[0], linewidth=1.15, zorder=5, label="累计成本")
    axes[1].step(xs, hindsight, where="post", color=PALETTE["dark"], linestyle=":", linewidth=1.0, zorder=4, label="静态后见基线")
    ax2 = axes[1].twinx()
    ax2.step(xs, carbon, where="post", color=PALETTE["green"], marker=MARKERS[1], linestyle="--", linewidth=0.95, alpha=0.86, zorder=3, label="累计排放")
    axes[1].set_ylabel("成本/£")
    ax2.set_ylabel("排放 kgCO$_2$e")
    axes[1].set_title("(b) 信息成本与累计排放")
    handles, labels = axes[1].get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    axes[1].legend(handles + handles2, labels + labels2, loc="best", fontsize=6.8)

    cross_site = [float(row["cross_site_customers"]) for row in stage_rows]
    low_carbon = [float(row["low_carbon_charge_share_pct"]) for row in stage_rows]
    fairness = [float(row["min_fairness_ratio"]) for row in stage_rows]
    theta_values = [float(row.get("theta", "1.0") or 1.0) for row in stage_rows]
    width = 0.32
    bars = axes[2].bar(xs, low_carbon, width=width, color=PALETTE["amber"], alpha=0.78, label="低碳充电占比%")
    for bar, value in zip(bars, cross_site):
        axes[2].text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 2.0, f"跨场{value:.0f}", ha="center", va="bottom", fontsize=6.5, color=PALETTE["purple"])
    ax3 = axes[2].twinx()
    ax3.plot(xs, fairness, color=PALETTE["red"], marker=MARKERS[2], label="最小公平比")
    ax3.plot(xs, theta_values, color=PALETTE["dark"], linestyle="--", linewidth=0.8, label="$\\theta$")
    axes[2].set_ylabel("低碳充电占比/%")
    ax3.set_ylabel("公平比")
    axes[2].set_xlabel("时间 / h")
    axes[2].set_title("(c) 协同、公平与低碳充电持续活跃度")
    handles, labels = axes[2].get_legend_handles_labels()
    handles2, labels2 = ax3.get_legend_handles_labels()
    axes[2].legend(handles + handles2, labels + labels2, loc="upper left", ncols=2, fontsize=6.8)
    if watermark:
        for ax in axes:
            sample_watermark(ax)
    return save_pdf_png(fig, output_stem)


def _f7_stage_metric_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    selected: dict[float, dict[str, str]] = {}
    for row in rows:
        if not row.get("cumulative_cost"):
            continue
        selected[float(row["stage_end_h"])] = row
    return [selected[key] for key in sorted(selected)]


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


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    pos = pct * (len(ordered) - 1)
    lower = int(pos)
    upper = min(lower + 1, len(ordered) - 1)
    frac = pos - lower
    return ordered[lower] * (1.0 - frac) + ordered[upper] * frac


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
