#!/usr/bin/env python3
"""生成 China81 京津冀 50 客户路线图可读性试画。

本脚本只读取给定算例，使用本地方位等距投影、容量约束最近邻构造路线，
不导入或调用求解器。所有路线都是示意，不是求解结果。
"""

from __future__ import annotations

import csv
import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

import matplotlib as mpl
mpl.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.patches import FancyArrowPatch
from matplotlib.ticker import MultipleLocator


ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = (
    ROOT
    / "data/ChinaInstances/china81_suite_prd_fix_v1_20260812/instances"
    / "cn-jjj-50c-01-V3-TWO-SHIFT-PRDFIX"
)
SOURCE_PDF = Path(
    "/Users/zhouleixishu/Zotero/storage/AYDB6KXP/"
    "陈雨蝶 等 _ 2025 _ 双碳背景下复杂冷链物流模型及求解算法.pdf"
)

SHUNHANG = "D_beijing_shunhang_dp"
TONGZHOU = "D_beijing_tongzhou_dp"
DEPOT_ORDER = (SHUNHANG, TONGZHOU)
DEPOT_CN = {SHUNHANG: "顺航场", TONGZHOU: "通州场"}
CAPACITY_KG = 1735
EARTH_RADIUS_KM = 6371.0088
FIGSIZE_IN = (4.92, 2.30)
PNG_DPI = 300
AXIS_LINE_PT = 0.468
ROUTE_LINE_PT = 0.50
FIG_TEXT_PT = 8.0
CAPTION_PT = 9.0

PROTECTED_FILES = (
    ROOT / "solver/src/setp_solver/cost.py",
    ROOT / "solver/src/setp_solver/check.py",
    ROOT / "solver/src/setp_solver/search/evaluation.py",
)


@dataclass(frozen=True)
class Customer:
    customer_id: str
    latitude: float
    longitude: float
    demand_kg: int
    home_depot_id: str


@dataclass(frozen=True)
class Route:
    depot_id: str
    trip_index: int
    customer_ids: tuple[str, ...]
    load_kg: int
    distance_km: float


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    assignment: Mapping[str, str]
    routes: tuple[Route, ...]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def format_hash(short_or_path: Path) -> str:
    return sha256(short_or_path)


def load_inputs() -> tuple[
    dict[str, Customer],
    dict[str, tuple[float, float]],
    dict[str, dict[str, str]],
]:
    order_rows = read_csv(INSTANCE_DIR / "orders.csv")
    node_rows = read_csv(INSTANCE_DIR / "nodes.csv")
    contest_rows = read_csv(INSTANCE_DIR / "contestability.csv")

    if len(order_rows) != 50:
        raise ValueError(f"预期 50 个客户，实际为 {len(order_rows)}")

    customers = {
        row["customer_id"]: Customer(
            customer_id=row["customer_id"],
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
            demand_kg=int(row["demand_kg"]),
            home_depot_id=row["home_depot_id"],
        )
        for row in order_rows
    }
    expected_ids = {f"C{number:03d}" for number in range(1, 51)}
    if set(customers) != expected_ids:
        raise ValueError("客户编号不是完整的 C001--C050")

    nodes = {
        row["node_id"]: (float(row["latitude"]), float(row["longitude"]))
        for row in node_rows
    }
    contests = {row["customer_id"]: row for row in contest_rows}
    if set(contests) != expected_ids:
        raise ValueError("contestability.csv 客户集合与 orders.csv 不一致")
    for customer_id, customer in customers.items():
        if customer_id not in nodes:
            raise ValueError(f"nodes.csv 缺少 {customer_id}")
        node_lat, node_lon = nodes[customer_id]
        if (node_lat, node_lon) != (customer.latitude, customer.longitude):
            raise ValueError(f"{customer_id} 在 orders.csv 与 nodes.csv 中的坐标不一致")
        if customer.home_depot_id not in DEPOT_ORDER:
            raise ValueError(f"{customer_id} 归属未知车场 {customer.home_depot_id}")

    for depot_id in DEPOT_ORDER:
        if depot_id not in nodes:
            raise ValueError(f"nodes.csv 缺少车场 {depot_id}")
    return customers, nodes, contests


def local_aeqd(
    latitude: float,
    longitude: float,
    center_latitude: float,
    center_longitude: float,
) -> tuple[float, float]:
    """球面方位等距投影，返回相对投影中心的公里坐标。"""
    phi = math.radians(latitude)
    lam = math.radians(longitude)
    phi_0 = math.radians(center_latitude)
    lam_0 = math.radians(center_longitude)
    delta_lam = lam - lam_0
    cos_c = (
        math.sin(phi_0) * math.sin(phi)
        + math.cos(phi_0) * math.cos(phi) * math.cos(delta_lam)
    )
    c = math.acos(max(-1.0, min(1.0, cos_c)))
    k = 1.0 if abs(c) < 1e-14 else c / math.sin(c)
    x = EARTH_RADIUS_KM * k * math.cos(phi) * math.sin(delta_lam)
    y = EARTH_RADIUS_KM * k * (
        math.cos(phi_0) * math.sin(phi)
        - math.sin(phi_0) * math.cos(phi) * math.cos(delta_lam)
    )
    return x, y


def project_nodes(
    customers: Mapping[str, Customer],
    nodes: Mapping[str, tuple[float, float]],
) -> tuple[dict[str, tuple[float, float]], float, float, float, float]:
    plotted_ids = [*DEPOT_ORDER, *sorted(customers)]
    center_lat = sum(nodes[node_id][0] for node_id in plotted_ids) / len(plotted_ids)
    center_lon = sum(nodes[node_id][1] for node_id in plotted_ids) / len(plotted_ids)
    raw_xy = {
        node_id: local_aeqd(*nodes[node_id], center_lat, center_lon)
        for node_id in plotted_ids
    }
    min_x = min(point[0] for point in raw_xy.values())
    min_y = min(point[1] for point in raw_xy.values())
    shifted_xy = {
        node_id: (point[0] - min_x, point[1] - min_y)
        for node_id, point in raw_xy.items()
    }
    return shifted_xy, center_lat, center_lon, min_x, min_y


def distance(
    first_id: str,
    second_id: str,
    xy: Mapping[str, tuple[float, float]],
) -> float:
    return math.dist(xy[first_id], xy[second_id])


def make_assignments(
    customers: Mapping[str, Customer],
    contests: Mapping[str, Mapping[str, str]],
    xy: Mapping[str, tuple[float, float]],
) -> tuple[dict[str, str], dict[str, str], dict[str, str], list[str]]:
    assignment_a = {
        customer_id: customer.home_depot_id
        for customer_id, customer in customers.items()
    }
    assignment_b = dict(assignment_a)
    for customer_id in sorted(customers):
        if contests[customer_id]["contestable_at_25pct"] == "1":
            assignment_b[customer_id] = min(
                DEPOT_ORDER,
                key=lambda depot_id: (
                    distance(customer_id, depot_id, xy),
                    depot_id,
                ),
            )

    counts_b = {
        depot_id: sum(value == depot_id for value in assignment_b.values())
        for depot_id in DEPOT_ORDER
    }
    smaller_depot = min(DEPOT_ORDER, key=lambda depot_id: (counts_b[depot_id], depot_id))
    baseline_target = sum(
        value == smaller_depot for value in assignment_a.values()
    )
    moved_away = sorted(
        customer_id
        for customer_id in customers
        if assignment_a[customer_id] == smaller_depot
        and assignment_b[customer_id] != smaller_depot
        and contests[customer_id]["contestable_at_25pct"] == "1"
    )
    assignment_c = dict(assignment_b)
    for customer_id in moved_away:
        if sum(value == smaller_depot for value in assignment_c.values()) >= baseline_target:
            break
        assignment_c[customer_id] = smaller_depot

    if sum(value == smaller_depot for value in assignment_c.values()) != baseline_target:
        raise ValueError("(c) 未能把客户数恢复到 (a) 基准")
    changed_b = sorted(
        customer_id
        for customer_id in customers
        if assignment_a[customer_id] != assignment_b[customer_id]
    )
    return assignment_a, assignment_b, assignment_c, changed_b


def construct_routes(
    assignment: Mapping[str, str],
    customers: Mapping[str, Customer],
    xy: Mapping[str, tuple[float, float]],
) -> tuple[Route, ...]:
    routes: list[Route] = []
    for depot_id in DEPOT_ORDER:
        remaining = {
            customer_id
            for customer_id, assigned_depot in assignment.items()
            if assigned_depot == depot_id
        }
        trip_index = 0
        while remaining:
            trip_index += 1
            current_id = depot_id
            load_kg = 0
            sequence: list[str] = []
            while True:
                feasible = [
                    customer_id
                    for customer_id in remaining
                    if load_kg + customers[customer_id].demand_kg <= CAPACITY_KG
                ]
                if not feasible:
                    break
                next_id = min(
                    feasible,
                    key=lambda customer_id: (
                        distance(current_id, customer_id, xy),
                        customer_id,
                    ),
                )
                remaining.remove(next_id)
                sequence.append(next_id)
                load_kg += customers[next_id].demand_kg
                current_id = next_id

            if not sequence:
                raise ValueError(f"{depot_id} 产生空路线")
            path = [depot_id, *sequence, depot_id]
            distance_km = sum(
                distance(first_id, second_id, xy)
                for first_id, second_id in zip(path, path[1:])
            )
            routes.append(
                Route(
                    depot_id=depot_id,
                    trip_index=trip_index,
                    customer_ids=tuple(sequence),
                    load_kg=load_kg,
                    distance_km=distance_km,
                )
            )

    served = [customer_id for route in routes for customer_id in route.customer_ids]
    if len(served) != len(customers) or set(served) != set(customers):
        raise ValueError("路线未完整且唯一地覆盖 50 个客户")
    if any(route.load_kg > CAPACITY_KG for route in routes):
        raise ValueError("有路线超过 1735 kg 载重")
    return tuple(routes)


def make_scenarios(
    customers: Mapping[str, Customer],
    contests: Mapping[str, Mapping[str, str]],
    xy: Mapping[str, tuple[float, float]],
) -> tuple[tuple[Scenario, ...], list[str]]:
    assignment_a, assignment_b, assignment_c, changed_b = make_assignments(
        customers, contests, xy
    )
    specs = (
        ("a", "(a) 各场单干", assignment_a),
        ("b", "(b) 成本最优（示意）", assignment_b),
        ("c", "(c) 全员不劣（示意）", assignment_c),
    )
    scenarios = tuple(
        Scenario(
            key=key,
            title=title,
            assignment=assignment,
            routes=construct_routes(assignment, customers, xy),
        )
        for key, title, assignment in specs
    )
    return scenarios, changed_b


def font_properties() -> tuple[FontProperties, FontProperties]:
    regular = FontProperties(
        family=["Times New Roman", "Songti SC"],
        size=FIG_TEXT_PT,
        weight="normal",
    )
    caption = FontProperties(
        family=["Times New Roman", "Heiti SC"],
        size=CAPTION_PT,
        weight="normal",
    )
    return regular, caption


def configure_matplotlib() -> None:
    required_fonts = (
        Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
        Path("/System/Library/Fonts/STHeiti Medium.ttc"),
        Path("/System/Library/Fonts/Supplemental/Times New Roman.ttf"),
        Path("/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf"),
    )
    missing = [str(path) for path in required_fonts if not path.exists()]
    if missing:
        raise FileNotFoundError("缺少冻结字体：" + ", ".join(missing))
    mpl.rcParams.update(
        {
            "font.family": ["Times New Roman", "Songti SC"],
            "font.size": FIG_TEXT_PT,
            "axes.unicode_minus": False,
            "axes.linewidth": AXIS_LINE_PT,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "savefig.transparent": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
        }
    )


def route_path(route: Route) -> tuple[str, ...]:
    return (route.depot_id, *route.customer_ids, route.depot_id)


def draw_route_segment(
    ax: mpl.axes.Axes,
    first: tuple[float, float],
    second: tuple[float, float],
) -> None:
    ax.plot(
        [first[0], second[0]],
        [first[1], second[1]],
        color="black",
        linewidth=ROUTE_LINE_PT,
        solid_capstyle="butt",
        zorder=1,
    )
    arrow_start = (
        first[0] + 0.44 * (second[0] - first[0]),
        first[1] + 0.44 * (second[1] - first[1]),
    )
    arrow_end = (
        first[0] + 0.58 * (second[0] - first[0]),
        first[1] + 0.58 * (second[1] - first[1]),
    )
    ax.add_patch(
        FancyArrowPatch(
            arrow_start,
            arrow_end,
            arrowstyle="-|>",
            mutation_scale=3.2,
            linewidth=ROUTE_LINE_PT,
            color="black",
            shrinkA=0.0,
            shrinkB=0.0,
            zorder=2,
        )
    )


def draw_panel(
    ax: mpl.axes.Axes,
    scenario: Scenario,
    customers: Mapping[str, Customer],
    xy: Mapping[str, tuple[float, float]],
    regular_font: FontProperties,
    x_limits: tuple[float, float],
    y_limits: tuple[float, float],
) -> None:
    for route in scenario.routes:
        path = route_path(route)
        for first_id, second_id in zip(path, path[1:]):
            draw_route_segment(ax, xy[first_id], xy[second_id])

    customer_ids = sorted(customers)
    ax.scatter(
        [xy[customer_id][0] for customer_id in customer_ids],
        [xy[customer_id][1] for customer_id in customer_ids],
        s=4.0,
        marker="o",
        facecolor="black",
        edgecolor="black",
        linewidth=0.0,
        zorder=3,
    )
    for customer_id in customer_ids:
        numeric_label = str(int(customer_id[1:]))
        ax.annotate(
            numeric_label,
            xy[customer_id],
            xytext=(1.4, 1.4),
            textcoords="offset points",
            ha="left",
            va="bottom",
            fontproperties=regular_font,
            color="black",
            annotation_clip=False,
            zorder=4,
        )

    for depot_id in DEPOT_ORDER:
        ax.scatter(
            [xy[depot_id][0]],
            [xy[depot_id][1]],
            s=28.0,
            marker="*",
            facecolor="black",
            edgecolor="black",
            linewidth=0.3,
            zorder=5,
        )
        vertical_offset = -2.0 if depot_id == SHUNHANG else 2.0
        ax.annotate(
            DEPOT_CN[depot_id],
            xy[depot_id],
            xytext=(-2.0, vertical_offset),
            textcoords="offset points",
            ha="right",
            va="top" if vertical_offset < 0 else "bottom",
            fontproperties=regular_font,
            color="black",
            annotation_clip=False,
            zorder=6,
        )

    ax.set_xlim(*x_limits)
    ax.set_ylim(*y_limits)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("横坐标/km", fontproperties=regular_font, labelpad=1.0)
    ax.set_ylabel("纵坐标/km", fontproperties=regular_font, labelpad=0.5)
    ax.xaxis.set_major_locator(MultipleLocator(5.0))
    ax.yaxis.set_major_locator(MultipleLocator(10.0))
    ax.tick_params(
        axis="both",
        which="major",
        direction="out",
        length=2.0,
        width=AXIS_LINE_PT,
        pad=1.0,
        labelsize=FIG_TEXT_PT,
        top=False,
        right=False,
    )
    for label in [*ax.get_xticklabels(), *ax.get_yticklabels()]:
        label.set_fontproperties(regular_font)
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(AXIS_LINE_PT)
        spine.set_color("black")
    ax.grid(False)


def data_limits(xy: Mapping[str, tuple[float, float]]) -> tuple[tuple[float, float], tuple[float, float]]:
    x_values = [point[0] for point in xy.values()]
    y_values = [point[1] for point in xy.values()]
    return (
        (-1.0, math.ceil(max(x_values)) + 1.0),
        (-1.0, math.ceil(max(y_values)) + 1.0),
    )


def save_figure(fig: mpl.figure.Figure, stem: str) -> None:
    pdf_path = OUT_DIR / f"{stem}.pdf"
    png_path = OUT_DIR / f"{stem}.png"
    fig.savefig(
        pdf_path,
        format="pdf",
        dpi=PNG_DPI,
        facecolor="white",
        bbox_inches=None,
        pad_inches=0.0,
    )
    fig.savefig(
        png_path,
        format="png",
        dpi=PNG_DPI,
        facecolor="white",
        bbox_inches=None,
        pad_inches=0.0,
    )
    plt.close(fig)


def make_three_panel_figure(
    scenarios: tuple[Scenario, ...],
    customers: Mapping[str, Customer],
    xy: Mapping[str, tuple[float, float]],
) -> None:
    regular_font, caption_font = font_properties()
    x_limits, y_limits = data_limits(xy)
    fig, axes = plt.subplots(1, 3, figsize=FIGSIZE_IN, squeeze=False)
    fig.subplots_adjust(left=0.067, right=0.995, top=0.985, bottom=0.305, wspace=0.38)
    for ax, scenario in zip(axes[0], scenarios):
        draw_panel(
            ax,
            scenario,
            customers,
            xy,
            regular_font,
            x_limits,
            y_limits,
        )
        bbox = ax.get_position()
        fig.text(
            (bbox.x0 + bbox.x1) / 2.0,
            0.120,
            scenario.title,
            ha="center",
            va="center",
            fontproperties=regular_font,
            color="black",
        )
    fig.text(
        0.5,
        0.028,
        "不同配送方案路线图（示意，非求解结果）",
        ha="center",
        va="bottom",
        fontproperties=caption_font,
        color="black",
    )
    save_figure(fig, "route_map_three_panel")


def make_single_figure(
    scenario: Scenario,
    customers: Mapping[str, Customer],
    xy: Mapping[str, tuple[float, float]],
) -> None:
    regular_font, caption_font = font_properties()
    x_limits, y_limits = data_limits(xy)
    fig, ax = plt.subplots(1, 1, figsize=FIGSIZE_IN)
    fig.subplots_adjust(left=0.10, right=0.985, top=0.985, bottom=0.305)
    draw_panel(
        ax,
        scenario,
        customers,
        xy,
        regular_font,
        x_limits,
        y_limits,
    )
    fig.text(
        0.5,
        0.120,
        "(a) 各场单干",
        ha="center",
        va="center",
        fontproperties=regular_font,
        color="black",
    )
    fig.text(
        0.5,
        0.028,
        "各场单干路线图（示意，非求解结果）",
        ha="center",
        va="bottom",
        fontproperties=caption_font,
        color="black",
    )
    save_figure(fig, "route_map_single")


def markdown_route_row(route: Route) -> str:
    customer_sequence = " → ".join(route.customer_ids)
    return (
        f"| {DEPOT_CN[route.depot_id]} | 燃油车（示意） | {route.trip_index} | "
        f"{customer_sequence} | {route.load_kg} | {route.distance_km:.2f} |"
    )


def write_markdown_table(scenarios: Iterable[Scenario]) -> None:
    lines = [
        "# 路线表（示意，非求解结果）",
        "",
        "路线由 1735 kg 载重上限下的确定性最近邻规则构造。客户序列只列客户；每趟均从表中车场出发并返回该车场。",
        "里程是本地方位等距投影平面上的直线折线里程，不是路网里程。车型只是为对应 1735 kg 载重而设的示意标签，不是车型优化结果。",
        "",
    ]
    for scenario in scenarios:
        lines.extend(
            [
                f"## {scenario.title}",
                "",
                "| 车场 | 车型 | 趟序 | 客户序列 | 载重/kg | 里程/km |",
                "|---|---|---:|---|---:|---:|",
                *[markdown_route_row(route) for route in scenario.routes],
                "",
            ]
        )
    (OUT_DIR / "route_table.md").write_text("\n".join(lines), encoding="utf-8")


def tex_escape(text: str) -> str:
    replacements = {
        "&": r"\&",
        "%": r"\%",
        "_": r"\_",
        "#": r"\#",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def tex_route_row(route: Route) -> str:
    sequence = r" $\to$ ".join(tex_escape(value) for value in route.customer_ids)
    return (
        f"{DEPOT_CN[route.depot_id]} & 燃油车（示意） & {route.trip_index} & "
        f"{sequence} & {route.load_kg} & {route.distance_km:.2f} \\\\"
    )


def write_tex_table(scenarios: Iterable[Scenario]) -> None:
    lines = [
        r"\documentclass{article}",
        r"\usepackage{fontspec}",
        r"\usepackage{xeCJK}",
        r"\usepackage{booktabs}",
        r"\usepackage{array}",
        r"\usepackage[a4paper,top=18mm,bottom=18mm,textwidth=4.92in]{geometry}",
        r"\setmainfont{Times New Roman}",
        r"\setCJKmainfont{Songti SC}",
        r"\setCJKsansfont{Heiti SC}",
        r"\setlength{\parindent}{0pt}",
        r"\setlength{\tabcolsep}{3pt}",
        r"\renewcommand{\arraystretch}{1.15}",
        r"\newcolumntype{L}[1]{>{\raggedright\arraybackslash}p{#1}}",
        r"\newcolumntype{R}[1]{>{\raggedleft\arraybackslash}p{#1}}",
        r"\begin{document}",
        r"\begin{center}",
        r"{\sffamily\fontsize{9pt}{11pt}\selectfont 路线表（示意，非求解结果）}",
        r"\end{center}",
        r"{\fontsize{8pt}{10pt}\selectfont",
        r"路线由 1735 kg 载重上限下的确定性最近邻规则构造。客户序列只列客户，每趟均从表中车场出发并返回该车场。里程是投影平面直线折线里程，不是路网里程。车型为载重口径的示意标签。",
        r"\par\medskip",
    ]
    for scenario in scenarios:
        lines.extend(
            [
                r"\needspace{7\baselineskip}" if False else "",
                r"{\sffamily " + tex_escape(scenario.title) + r"}\par\smallskip",
                r"\noindent\begin{tabular}{@{}L{1.25cm}L{1.55cm}R{0.55cm}L{5.65cm}R{1.05cm}R{1.05cm}@{}}",
                r"\toprule",
                r"车场 & 车型 & 趟序 & 客户序列 & 载重/kg & 里程/km \\",
                r"\midrule",
                *[tex_route_row(route) for route in scenario.routes],
                r"\bottomrule",
                r"\end{tabular}",
                r"\par\medskip",
            ]
        )
    lines.extend([r"}", r"\end{document}", ""])
    (OUT_DIR / "route_table.tex").write_text(
        "\n".join(line for line in lines if line != ""), encoding="utf-8"
    )


def scenario_counts(scenario: Scenario) -> dict[str, int]:
    return {
        depot_id: sum(value == depot_id for value in scenario.assignment.values())
        for depot_id in DEPOT_ORDER
    }


def scenario_route_counts(scenario: Scenario) -> dict[str, int]:
    return {
        depot_id: sum(route.depot_id == depot_id for route in scenario.routes)
        for depot_id in DEPOT_ORDER
    }


def artifact_hash_lines(paths: Iterable[Path]) -> list[str]:
    return [f"- `{path.name}`: `{sha256(path)}`" for path in paths]


def write_report(
    scenarios: tuple[Scenario, ...],
    customers: Mapping[str, Customer],
    contests: Mapping[str, Mapping[str, str]],
    xy: Mapping[str, tuple[float, float]],
    center_lat: float,
    center_lon: float,
    raw_min_x: float,
    raw_min_y: float,
    changed_b: list[str],
    protected_before: Mapping[str, str],
) -> None:
    counts = {scenario.key: scenario_counts(scenario) for scenario in scenarios}
    route_counts = {
        scenario.key: scenario_route_counts(scenario) for scenario in scenarios
    }
    distances = {
        scenario.key: sum(route.distance_km for route in scenario.routes)
        for scenario in scenarios
    }
    active_contestable = sum(
        row["contestable_at_25pct"] == "1" for row in contests.values()
    )
    total_demand = sum(customer.demand_kg for customer in customers.values())
    x_span = max(point[0] for point in xy.values()) - min(point[0] for point in xy.values())
    y_span = max(point[1] for point in xy.values()) - min(point[1] for point in xy.values())

    protected_after = {
        str(path.relative_to(ROOT)): format_hash(path) for path in PROTECTED_FILES
    }
    if dict(protected_before) != protected_after:
        raise RuntimeError("受保护文件哈希在任务中发生变化")

    artifacts = [
        OUT_DIR / "route_map_three_panel.pdf",
        OUT_DIR / "route_map_three_panel.png",
        OUT_DIR / "route_map_single.pdf",
        OUT_DIR / "route_map_single.png",
        OUT_DIR / "route_table.md",
        OUT_DIR / "route_table.tex",
    ]
    lines = [
        "ROUTEMAP_DONE",
        "",
        "# 路线图可读性试画报告",
        "",
        "## 一句话结论",
        "",
        "**我的判断：三子图版在冻结的双栏图幅下不能清楚辨读路线；单图版只是屏幕放大时稍好，按论文实际尺寸仍拥挤；表格能核对，但三个方案完整列出后太长。** 若路径本身不承担必须的论点，不展示路径比硬塞三子图更合理；最终去留由用户判断。",
        "",
        "## 身份与边界",
        "",
        f"- 数据：`{INSTANCE_DIR.relative_to(ROOT)}/`，50 个客户，总需求 {total_demand} kg；25% 口径下可争夺客户 {active_contestable} 个。",
        "- 三个方案全部是示意，不是求解器输出，不是最优解，也不是正式实验结果。本任务没有运行求解器。",
        "- 每趟仅按 1735 kg 载重限制分趟：从所属车场出发，在剩余容量可容纳的未服务客户中选投影距离最近者，无可加客户时返场。",
        "- 车型列统一写“燃油车（示意）”，只是为对应题设 1735 kg 载重，不表示真实车型决策。",
        "",
        "## 投影与坐标换算",
        "",
        f"- 采用以 50 个客户和 2 个车场的算术平均坐标为中心的球面方位等距投影（local azimuthal equidistant, AEQD）。投影中心为纬度 `{center_lat:.10f}°`、经度 `{center_lon:.10f}°`，球面半径取 `{EARTH_RADIUS_KM}` km。",
        "- 换算公式：`c = acos(sinφ0 sinφ + cosφ0 cosφ cosΔλ)`，`k = c/sin(c)`，`x = R k cosφ sinΔλ`，`y = R k (cosφ0 sinφ - sinφ0 cosφ cosΔλ)`。",
        f"- 为使图轴从约 0 km 起读，对所有投影坐标统一平移：减去原始 `x_min={raw_min_x:.9f}` km 和 `y_min={raw_min_y:.9f}` km。平移不改变距离、角度或比例。全部点的实际跨度为 `{x_span:.3f} km × {y_span:.3f} km`，横纵轴使用相同的公里比例。",
        "- 表中里程是投影平面直线折线里程，不是冻结路网里程。",
        "",
        "## 三个子图的构造与数量",
        "",
        "| 子图 | 客户分配（顺航/通州） | 路线数（顺航/通州） | 客户数 | 投影折线总里程/km |",
        "|---|---:|---:|---:|---:|",
        f"| (a) 各场单干 | {counts['a'][SHUNHANG]}/{counts['a'][TONGZHOU]} | {route_counts['a'][SHUNHANG]}/{route_counts['a'][TONGZHOU]} | 50 | {distances['a']:.2f} |",
        f"| (b) 成本最优（示意） | {counts['b'][SHUNHANG]}/{counts['b'][TONGZHOU]} | {route_counts['b'][SHUNHANG]}/{route_counts['b'][TONGZHOU]} | 50 | {distances['b']:.2f} |",
        f"| (c) 全员不劣（示意） | {counts['c'][SHUNHANG]}/{counts['c'][TONGZHOU]} | {route_counts['c'][SHUNHANG]}/{route_counts['c'][TONGZHOU]} | 50 | {distances['c']:.2f} |",
        "",
        f"(b) 仅对 25% 口径的可争夺客户比较两车场的 AEQD 直线距离，改派了 `{', '.join(changed_b)}`（顺航→通州）。`contestability.csv` 的 `nearest_depot` 是成本口径，本例 50/50 与 `home_depot_id` 相同；因任务指定“更近车场”，本图明确使用投影几何距离。",
        "",
        "(c) 从 (b) 把上述被改派的可争夺客户划回客户数较少的顺航场，直到顺航恢复 (a) 的 9 个客户。因此在本最简规则下，**(c) 与 (a) 的客户归属和路线完全相同**。这是输入与规则的真实结果，未为让三图“看起来不同”而换客户或改路线。",
        "",
        f"另外，(b) 虽按题设称“成本最优（示意）”，但最近场改派与贪心分趟并不保证总里程最小；本次实际投影总里程为 {distances['b']:.2f} km，高于 (a) 的 {distances['a']:.2f} km。所以该名称只是方案标签，不是成本最优性声明。",
        "",
        "## 图幅、字号和线宽",
        "",
        f"- 三子图与单图都是 `{FIGSIZE_IN[0]:.2f} in × {FIGSIZE_IN[1]:.2f} in`（`124.97 mm × 58.42 mm`），宽度和高度均沿用合同冻结的双栏空间结构图图幅。单图没有放大画布。",
        f"- PNG 为 {PNG_DPI} dpi，理论像素尺寸 `1476 × 690`；PDF 中点、线、文字保持矢量。",
        f"- 图内文字、客户编号、车场就地标签、坐标轴标题、刻度和子图题均为 `{FIG_TEXT_PT:.0f} pt`；中文宋体（Songti SC），英文与数字 Times New Roman。图注为 `{CAPTION_PT:.0f} pt` 黑体（Heiti SC）。",
        f"- 坐标轴与刻度线 `{AXIS_LINE_PT:.3f} pt`，路线 `{ROUTE_LINE_PT:.2f} pt`，客户点面积 `4 pt²`，车场星形面积 `28 pt²`，线中箭头尺度 `3.2 pt`。无网格、无独立图例框、无渐变和阴影。",
        "",
        "## 能否看清：我的具体判断",
        "",
        "1. **三子图：不能清楚追踪每条路线。** 50 个 8 pt 编号和 9 条路线被压进每个等宽子图；客户的东西向分布只占约 3.3 km，而全体点南北跨度约 40.1 km，按真实公里比例后，客户点、编号和客户间短线在中间窄带严重重叠。放大 PDF 可核对局部，但按论文实际尺寸不能一眼读出完整趟序。",
        "2. **单图：比三子图少了并排干扰，但实际线性尺度改善很小。** 为了不改公里比例、不放大画布，单图和三子图共用相同高度与等比例坐标框；因地理形状狭长，增加的宽度大部分变成两侧留白，不会自动把中间客户簇拉开。",
        "3. **表格：路线序列最容易核对，但不适合同时容纳三个完整方案。** 当前是 27 个路线行（每个方案 9 行），而 (a)/(c) 重复；它能精确核查载重和序列，但看不到空间形状，且比一张图占页更多。",
        "",
        "## 三种呈现的占版面估计",
        "",
        "| 呈现方式 | 实际/估计占用 | 估计依据 |",
        "|---|---|---|",
        "| 三子图 | 4.92 in × 2.30 in；约占一个 A4 正文页高的 1/4 | 图注已绘入图幅，尚未加正文前后间距 |",
        "| 单图 | 同样 4.92 in × 2.30 in；约 1/4 页 | 为保持同一论文画布和真实比例，未扩大高度 |",
        "| 三方案表格 | 2 个 A4 页 | `route_table.tex` 以 4.92 in 文字宽度、8 pt 表文经 XeLaTeX 实际试编译为 2 页 |",
        "",
        "## 母版与产物核对",
        "",
        f"- 唯一母版：陈雨蝶等（2025）图 5，PDF 物理页 18；源 PDF SHA-256 为 `{sha256(SOURCE_PDF)}`。",
        "- 照搬要素：三个等宽子图横排、子图题在图下、坐标轴写“横坐标/km”和“纵坐标/km”、编号客户黑点、车场星形、黑色细实线与箭头、四边细框、无网格、无独立图例框。",
        "- 未删客户、未抽稀、未为避让标签改坐标、未改横纵比例，也未手工修路线。",
        "- 图上无英镑符号，无退役算法名。",
        "- 本任务不是实验，不产生正式实验四件套。",
        "",
        "受保护文件任务前后 SHA-256 一致：",
        "",
        *[
            f"- `{relative}`: `{digest}`"
            for relative, digest in protected_after.items()
        ],
        "",
        "产物 SHA-256：",
        "",
        *artifact_hash_lines(artifacts),
        "",
        "可复现脚本：`build_route_map_probe.py`。",
        "",
    ]
    (OUT_DIR / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    configure_matplotlib()
    protected_before = {
        str(path.relative_to(ROOT)): format_hash(path) for path in PROTECTED_FILES
    }
    customers, nodes, contests = load_inputs()
    xy, center_lat, center_lon, raw_min_x, raw_min_y = project_nodes(customers, nodes)
    scenarios, changed_b = make_scenarios(customers, contests, xy)
    make_three_panel_figure(scenarios, customers, xy)
    make_single_figure(scenarios[0], customers, xy)
    write_markdown_table(scenarios)
    write_tex_table(scenarios)
    write_report(
        scenarios,
        customers,
        contests,
        xy,
        center_lat,
        center_lon,
        raw_min_x,
        raw_min_y,
        changed_b,
        protected_before,
    )


if __name__ == "__main__":
    main()
