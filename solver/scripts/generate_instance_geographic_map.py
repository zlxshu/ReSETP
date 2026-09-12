#!/usr/bin/env python3
"""Generate the Beijing instance node-distribution map from saved coordinates."""

from __future__ import annotations

import csv
import math
import subprocess
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont


REPO = Path(__file__).resolve().parents[2]
INSTANCE = (
    REPO
    / "data/ChinaInstances/china81_final_suite_v2_20260815/instances"
    / "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd"
)
OUT = REPO / "docs/paper_v2/generated_figures/figure_instance_geographic_distribution_preview.png"
ZOOM = 11
CUSTOMER_COLOR = "#2166AC"
DEPOT_COLOR = "#D73027"
STATION_COLOR = "#198754"
TILE_SIZE = 256
STATIONS = {
    "S_OSM_WAY_1347678396": "S1",
    "S_OSM_WAY_1348314458": "S2",
}
DEPOTS = {
    "D_OSM_WAY_1003511503": "D1",
    "D_OSM_WAY_1071205721": "D2",
}


def tile_xy(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    n = 2**zoom
    lat_rad = math.radians(lat)
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def fetch_tile(x: int, y: int, zoom: int) -> Image.Image:
    url = f"https://tile.openstreetmap.org/{zoom}/{x}/{y}.png"
    response = subprocess.run(
        ["curl", "-fsSL", "--max-time", "30", "-A", "ReSETP academic figure/1.0", url],
        check=True,
        capture_output=True,
    )
    return Image.open(BytesIO(response.stdout)).convert("RGB")


def load_nodes() -> list[dict[str, str]]:
    with (INSTANCE / "nodes.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return [
        row
        for row in rows
        if row["node_type"] == "customer"
        or row["node_id"] in DEPOTS
        or row["node_id"] in STATIONS
    ]


def dashed_line(
    draw: ImageDraw.ImageDraw,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    fill: str,
    width: int,
    dash: int = 13,
    gap: int = 9,
) -> None:
    x0, y0 = start
    x1, y1 = end
    length = math.hypot(x1 - x0, y1 - y0)
    if length == 0:
        return
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    pos = 0.0
    while pos < length:
        stop = min(pos + dash, length)
        draw.line(
            (x0 + ux * pos, y0 + uy * pos, x0 + ux * stop, y0 + uy * stop),
            fill=fill,
            width=width,
        )
        pos += dash + gap


def main() -> None:
    rows = load_nodes()
    lons = [float(row["longitude"]) for row in rows]
    lats = [float(row["latitude"]) for row in rows]
    lon_pad = (max(lons) - min(lons)) * 0.055
    lat_pad = (max(lats) - min(lats)) * 0.09
    west, east = min(lons) - lon_pad, max(lons) + lon_pad
    south, north = min(lats) - lat_pad, max(lats) + lat_pad

    x0, y0 = tile_xy(west, north, ZOOM)
    x1, y1 = tile_xy(east, south, ZOOM)
    tx0, ty0 = math.floor(x0), math.floor(y0)
    tx1, ty1 = math.floor(x1), math.floor(y1)
    mosaic = Image.new(
        "RGB",
        ((tx1 - tx0 + 1) * TILE_SIZE, (ty1 - ty0 + 1) * TILE_SIZE),
        "white",
    )
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            mosaic.paste(fetch_tile(tx, ty, ZOOM), ((tx - tx0) * TILE_SIZE, (ty - ty0) * TILE_SIZE))

    crop = (
        round((x0 - tx0) * TILE_SIZE),
        round((y0 - ty0) * TILE_SIZE),
        round((x1 - tx0) * TILE_SIZE),
        round((y1 - ty0) * TILE_SIZE),
    )
    base = mosaic.crop(crop)
    base = ImageEnhance.Color(base).enhance(0.10)
    base = ImageEnhance.Contrast(base).enhance(0.70)
    base = Image.blend(base, Image.new("RGB", base.size, "white"), 0.43)
    scale = 1800 / base.width
    base = base.resize((1800, round(base.height * scale)), Image.Resampling.LANCZOS)
    map_only = base.copy()

    draw = ImageDraw.Draw(base)
    song = "/Applications/Microsoft Word.app/Contents/Resources/DFonts/Simsun.ttc"
    times = "/System/Library/Fonts/Supplemental/Times New Roman.ttf"
    # The figure is inserted at 0.82\textwidth. At that final print size,
    # 62 px here corresponds to about 8 pt, matching the other journal figures.
    label_font = ImageFont.truetype(times, 62)
    legend_cn = ImageFont.truetype(song, 62)

    def point(lon: float, lat: float) -> tuple[float, float]:
        tx, ty = tile_xy(lon, lat, ZOOM)
        px = (tx - x0) * TILE_SIZE * scale
        py = (ty - y0) * TILE_SIZE * scale
        return px, py

    for row in rows:
        if row["node_type"] != "customer":
            continue
        px, py = point(float(row["longitude"]), float(row["latitude"]))
        radius = 10
        draw.ellipse(
            (px - radius, py - radius, px + radius, py + radius),
            fill=CUSTOMER_COLOR,
            outline="white",
            width=2,
        )

    for row in rows:
        node_id = row["node_id"]
        px, py = point(float(row["longitude"]), float(row["latitude"]))
        if node_id in DEPOTS:
            draw.rectangle(
                (px - 23, py - 23, px + 23, py + 23),
                fill=DEPOT_COLOR,
                outline="white",
                width=4,
            )
            label = DEPOTS[node_id]
            offset = (28, -48) if label == "D1" else (28, 8)
        elif node_id in STATIONS:
            draw.polygon([(px, py - 26), (px - 23, py + 21), (px + 23, py + 21)], fill=STATION_COLOR, outline="white", width=4)
            label = STATIONS[node_id]
            offset = (-82, -62) if label == "S1" else (28, 9)
        else:
            continue
        draw.text((px + offset[0], py + offset[1]), label, font=label_font, fill="black", stroke_width=4, stroke_fill="white")

    box = (34, 32, 530, 332)
    legend_background = base.crop(box)
    legend_background = Image.blend(
        legend_background, Image.new("RGB", legend_background.size, "white"), 0.65
    )
    base.paste(legend_background, box[:2])
    y = 91
    draw.ellipse((53, y - 13, 79, y + 13), fill=CUSTOMER_COLOR, outline="white", width=2)
    draw.text((105, y - 37), "客户", font=legend_cn, fill="black")
    y += 94
    draw.rectangle((49, y - 18, 83, y + 18), fill=DEPOT_COLOR, outline="white", width=3)
    draw.text((105, y - 37), "配送中心", font=legend_cn, fill="black")
    y += 94
    draw.polygon([(66, y - 22), (47, y + 18), (85, y + 18)], fill=STATION_COLOR, outline="white", width=3)
    draw.text((105, y - 37), "公共充电站", font=legend_cn, fill="black")

    mid_lat = (south + north) / 2
    km10_lon = 10.0 / (111.32 * math.cos(math.radians(mid_lat)))
    sx0, sy = point(west + 0.045, south + 0.035)
    sx1, _ = point(west + 0.045 + km10_lon, south + 0.035)
    draw.line((sx0, sy, sx1, sy), fill="black", width=3)
    draw.line((sx0, sy - 9, sx0, sy + 9), fill="black", width=3)
    draw.line((sx1, sy - 9, sx1, sy + 9), fill="black", width=3)
    scale_text = "10 km"
    scale_box = draw.textbbox((0, 0), scale_text, font=label_font)
    draw.text(((sx0 + sx1 - (scale_box[2] - scale_box[0])) / 2, sy - 53), scale_text, font=label_font, fill="black", stroke_width=3, stroke_fill="white")

    draw.rectangle((0, 0, base.width - 1, base.height - 1), outline="#222222", width=2)

    inset_west, inset_east = 116.27, 116.44
    inset_south, inset_north = 39.88, 40.02
    crop_left, crop_top = point(inset_west, inset_north)
    crop_right, crop_bottom = point(inset_east, inset_south)
    locator = [
        ((crop_left, crop_top), (crop_right, crop_top)),
        ((crop_right, crop_top), (crop_right, crop_bottom)),
        ((crop_right, crop_bottom), (crop_left, crop_bottom)),
        ((crop_left, crop_bottom), (crop_left, crop_top)),
    ]
    for start, end in locator:
        draw.line((*start, *end), fill="#555555", width=2)
    inset_source = map_only.crop((round(crop_left), round(crop_top), round(crop_right), round(crop_bottom)))
    inset_width = 950
    inset_scale = inset_width / inset_source.width
    inset = inset_source.resize(
        (inset_width, round(inset_source.height * inset_scale)),
        Image.Resampling.LANCZOS,
    )
    inset_draw = ImageDraw.Draw(inset)

    def inset_point(lon: float, lat: float) -> tuple[float, float]:
        px, py = point(lon, lat)
        return (px - crop_left) * inset_scale, (py - crop_top) * inset_scale

    for row in rows:
        lon = float(row["longitude"])
        lat = float(row["latitude"])
        if not (inset_west <= lon <= inset_east and inset_south <= lat <= inset_north):
            continue
        px, py = inset_point(lon, lat)
        if row["node_type"] == "customer":
            radius = 11
            inset_draw.ellipse(
                (px - radius, py - radius, px + radius, py + radius),
                fill=CUSTOMER_COLOR,
                outline="white",
                width=2,
            )
        elif row["node_id"] in STATIONS:
            inset_draw.polygon(
                [(px, py - 23), (px - 20, py + 18), (px + 20, py + 18)],
                fill=STATION_COLOR,
                outline="white",
                width=3,
            )
            label = STATIONS[row["node_id"]]
            offset = (-94, -76) if label == "S1" else (-18, 24)
            inset_draw.text(
                (px + offset[0], py + offset[1]),
                label,
                font=label_font,
                fill="black",
                stroke_width=3,
                stroke_fill="white",
            )

    inset_mid_lat = (inset_south + inset_north) / 2
    inset_km_lon = 5.0 / (111.32 * math.cos(math.radians(inset_mid_lat)))
    isx0, isy = inset_point(inset_west + 0.012, inset_south + 0.012)
    isx1, _ = inset_point(inset_west + 0.012 + inset_km_lon, inset_south + 0.012)
    inset_draw.line((isx0, isy, isx1, isy), fill="black", width=3)
    inset_draw.line((isx0, isy - 8, isx0, isy + 8), fill="black", width=3)
    inset_draw.line((isx1, isy - 8, isx1, isy + 8), fill="black", width=3)
    inset_scale_text = "5 km"
    inset_scale_box = inset_draw.textbbox((0, 0), inset_scale_text, font=label_font)
    inset_draw.text(
        ((isx0 + isx1 - (inset_scale_box[2] - inset_scale_box[0])) / 2, isy - 50),
        inset_scale_text,
        font=label_font,
        fill="black",
        stroke_width=3,
        stroke_fill="white",
    )
    inset_draw.rectangle((0, 0, inset.width - 1, inset.height - 1), outline="#222222", width=3)

    gutter = 100
    panel_width = inset.width + 2 * gutter
    label_band = 88
    canvas = Image.new("RGB", (base.width + panel_width, base.height + label_band), "white")
    canvas.paste(base, (0, 0))
    inset_x = base.width + gutter
    inset_y = (base.height - inset.height) // 2
    canvas.paste(inset, (inset_x, inset_y))
    canvas_draw = ImageDraw.Draw(canvas)
    for source, target in (
        ((crop_right, crop_top), (inset_x, inset_y)),
        ((crop_right, crop_bottom), (inset_x, inset_y + inset.height - 1)),
    ):
        canvas_draw.line((*source, *target), fill="#888888", width=2)
    for center_x, title in (
        (base.width / 2, "(a) 全域分布"),
        (inset_x + inset.width / 2, "(b) 城区局部放大"),
    ):
        title_box = canvas_draw.textbbox((0, 0), title, font=legend_cn)
        canvas_draw.text(
            (center_x - (title_box[2] - title_box[0]) / 2, base.height + 18),
            title,
            font=legend_cn,
            fill="black",
        )

    target_width = 2760  # 6.9 in at 400 dpi: full journal text width.
    final_scale = target_width / canvas.width
    canvas = canvas.resize(
        (target_width, round(canvas.height * final_scale)),
        Image.Resampling.LANCZOS,
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUT, dpi=(400, 400), optimize=True)
    canvas.save(OUT.with_suffix(".pdf"), "PDF", resolution=400.0)
    print(f"wrote {OUT}")
    print(f"customers={sum(r['node_type'] == 'customer' for r in rows)} depots=2 stations=2")


if __name__ == "__main__":
    main()
