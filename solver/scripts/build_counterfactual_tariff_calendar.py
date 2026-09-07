#!/usr/bin/env python3
"""Generate the three counterfactual tariff calendars used by section 4.4.

Both outputs keep **every** column of the approved runtime calendar byte for
byte except four price/label columns, and they touch **only** the ``beijing``
rows (all 28 dates alike).  Everything else -- the other eight cities, the
carbon-intensity column, the diesel columns, the mapping columns and the status
columns -- is copied out verbatim, line by line, so no re-serialisation can
change a value the loader validates.

Three scenarios are written:

``midday_valley``
    The three Beijing tariff tiers are re-laid on the clock following the
    Hebei southern-grid winter practice of putting a valley window at midday,
    while keeping Beijing's own three price levels *and* keeping each tier at
    exactly 8.0 hours:

    * valley  01:00-06:00 and 12:00-15:00
    * peak    10:00-12:00 and 17:00-23:00
    * flat    00:00-01:00, 06:00-10:00, 15:00-17:00, 23:00-24:00

``uniform``
    Every Beijing half-hour slot carries the arithmetic mean of the 48
    original slot prices (Shi 2025 §5.2.2's flat-tariff control): the daily
    unweighted price level is unchanged, the time structure is gone.

``midday_discount``
    The "green charging window" subsidy lever (2026-09-04).  Beijing's own
    time-of-use structure is left completely alone; only the six half-hour
    slots covering 12:00-15:00 are priced at the valley rate, the difference
    being paid by the treasury.  Unlike the two layouts above this is a
    *price subsidy*, not a re-arrangement, so the daily mean price must and
    does fall -- it therefore has its own assertion block and is deliberately
    kept out of the two checks below.

Because the midday layout is a permutation of the original 48 slot prices and
the uniform layout is their mean, ``original`` / ``midday_valley`` / ``uniform``
must have the *same* daily unweighted mean price.  The generator asserts that
bit for bit (with ``math.fsum``, which is permutation invariant) and refuses to
write otherwise.  ``midday_discount`` is excluded from that check on purpose;
it is instead required to come out strictly *below* the original.

Usage (repository root)::

    .public-hgs-venv/bin/python3 solver/scripts/build_counterfactual_tariff_calendar.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
from collections import Counter
from pathlib import Path
from typing import Sequence

CALENDAR_FILENAME = "tariff_carbon_hourly_calendar.csv"
DEFAULT_SOURCE = Path(
    "data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723"
)
DEFAULT_MIDDAY_OUT = Path(
    "data/ChinaInstances/china81_cf_calendar_midday_valley_v1_20260904"
)
DEFAULT_UNIFORM_OUT = Path(
    "data/ChinaInstances/china81_cf_calendar_uniform_v1_20260904"
)
DEFAULT_MIDDAY_DISCOUNT_OUT = Path(
    "data/ChinaInstances/china81_cf_calendar_midday_discount_v1_20260904"
)

TARGET_CITY = "beijing"
SLOTS_PER_DAY = 48
SLOT_MINUTES = 30
LINE_TERMINATOR = "\r\n"

# Half-hour slot k (1-based) covers minute [(k-1)*30, k*30).
MIDDAY_VALLEY_SLOTS: dict[str, tuple[int, ...]] = {
    # 01:00-06:00 and 12:00-15:00
    "valley": tuple(range(3, 13)) + tuple(range(25, 31)),
    # 10:00-12:00 and 17:00-23:00
    "peak": tuple(range(21, 25)) + tuple(range(35, 47)),
    # 00:00-01:00, 06:00-10:00, 15:00-17:00, 23:00-24:00
    "flat": (1, 2)
    + tuple(range(13, 21))
    + tuple(range(31, 35))
    + (47, 48),
}

MUTABLE_COLUMNS = (
    "tariff_period",
    "depot_energy_cny_per_kwh",
    "public_energy_cny_per_kwh",
    "public_total_cny_per_kwh",
)

REFERENCE_DATE = "2025-02-12"

# ---------------------------------------------------------------------------
# ``midday_discount``：绿色充电窗口补贴（2026-09-04 加）
#
# 与上面两个情景**性质不同**，所以它有自己一套断言，不进「三档各 8 h」与
# 「日均电价逐位相等」那两条检查：
#   * 上面两个是**重排**（时段结构变、价格水平不变）；
#   * 这个是**补贴**（时段结构不变、12:00-15:00 六个槽的电价被压到谷价，
#     日均电价必然低于原日历，差价由财政出）。
# 半小时槽 k 覆盖分钟 [(k-1)*30, k*30)，故 12:00-15:00 ＝ 槽 25..30。
MIDDAY_DISCOUNT_SLOTS: tuple[int, ...] = tuple(range(25, 31))
MIDDAY_DISCOUNT_PERIOD_LABEL = "valley_subsidised"


def _read_lines(path: Path) -> tuple[str, list[str]]:
    """Return the header line and the data lines, terminators stripped."""

    raw = path.read_text(encoding="utf-8", newline="")
    if LINE_TERMINATOR not in raw:
        raise SystemExit(f"{path}: expected CRLF line terminators")
    if raw.endswith(LINE_TERMINATOR):
        raw = raw[: -len(LINE_TERMINATOR)]
    lines = raw.split(LINE_TERMINATOR)
    return lines[0], lines[1:]


def _fields(line: str) -> list[str]:
    parsed = next(csv.reader([line]))
    if ",".join(parsed) != line:
        raise SystemExit(
            "calendar line is not plain comma separated; refusing to rewrite it"
        )
    return parsed


def _hour_span(slots: Sequence[int]) -> float:
    return len(slots) * SLOT_MINUTES / 60.0


def _daily_mean(prices: Sequence[float]) -> float:
    if len(prices) != SLOTS_PER_DAY:
        raise SystemExit(f"expected {SLOTS_PER_DAY} slots, got {len(prices)}")
    return math.fsum(prices) / float(SLOTS_PER_DAY)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tier_prices(
    header: list[str],
    data_lines: list[str],
) -> tuple[dict[str, dict[str, str]], str]:
    """Read Beijing's three tiers straight out of the source calendar."""

    idx = {name: header.index(name) for name in header}
    tiers: dict[str, set[tuple[str, str, str, str]]] = {}
    for line in data_lines:
        fields = _fields(line)
        if fields[idx["city"]] != TARGET_CITY:
            continue
        tiers.setdefault(fields[idx["tariff_period"]], set()).add(
            (
                fields[idx["depot_energy_cny_per_kwh"]],
                fields[idx["public_energy_cny_per_kwh"]],
                fields[idx["public_service_fee_cny_per_kwh"]],
                fields[idx["public_total_cny_per_kwh"]],
            )
        )
    if set(tiers) != {"valley", "flat", "peak"}:
        raise SystemExit(f"unexpected Beijing tariff tiers: {sorted(tiers)}")
    service_fees = set()
    out: dict[str, dict[str, str]] = {}
    for tier, values in tiers.items():
        if len(values) != 1:
            raise SystemExit(f"Beijing tier {tier!r} is not a single price: {values}")
        depot, public, service, total = next(iter(values))
        if depot != public:
            raise SystemExit(
                f"Beijing tier {tier!r} has depot {depot} != public {public}"
            )
        if abs((float(public) + float(service)) - float(total)) > 1e-12:
            raise SystemExit(f"Beijing tier {tier!r} price components do not close")
        service_fees.add(service)
        out[tier] = {
            "depot_energy_cny_per_kwh": depot,
            "public_energy_cny_per_kwh": public,
            "public_service_fee_cny_per_kwh": service,
            "public_total_cny_per_kwh": total,
        }
    if len(service_fees) != 1:
        raise SystemExit(f"Beijing service fee is not constant: {service_fees}")
    return out, next(iter(service_fees))


def _write_calendar(
    path: Path,
    header: str,
    lines: Sequence[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = LINE_TERMINATOR.join([header, *lines]) + LINE_TERMINATOR
    path.write_text(body, encoding="utf-8", newline="")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--source-authority", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--midday-out", type=Path, default=DEFAULT_MIDDAY_OUT)
    parser.add_argument("--uniform-out", type=Path, default=DEFAULT_UNIFORM_OUT)
    parser.add_argument(
        "--midday-discount-out",
        type=Path,
        default=DEFAULT_MIDDAY_DISCOUNT_OUT,
    )
    args = parser.parse_args(argv)

    repo = args.repo_root.resolve()
    source_path = repo / args.source_authority / CALENDAR_FILENAME
    midday_dir = repo / args.midday_out
    uniform_dir = repo / args.uniform_out
    discount_dir = repo / args.midday_discount_out

    header_line, data_lines = _read_lines(source_path)
    header = _fields(header_line)
    idx = {name: position for position, name in enumerate(header)}
    for name in (*MUTABLE_COLUMNS, "city", "date", "hourly_calendar_row",
                 "minute_of_day", "public_service_fee_cny_per_kwh"):
        if name not in idx:
            raise SystemExit(f"source calendar has no column {name!r}")

    tiers, service_fee = _tier_prices(header, data_lines)

    # ---- slot layout assertions on the source ---------------------------
    reference_rows: dict[int, list[str]] = {}
    source_period_slots: dict[str, list[int]] = {}
    beijing_dates: set[str] = set()
    for line in data_lines:
        fields = _fields(line)
        if fields[idx["city"]] != TARGET_CITY:
            continue
        beijing_dates.add(fields[idx["date"]])
        if fields[idx["date"]] != REFERENCE_DATE:
            continue
        slot = int(fields[idx["hourly_calendar_row"]])
        if int(fields[idx["minute_of_day"]]) != (slot - 1) * SLOT_MINUTES:
            raise SystemExit(f"slot {slot} minute_of_day disagrees with its index")
        reference_rows[slot] = fields
        source_period_slots.setdefault(fields[idx["tariff_period"]], []).append(slot)
    if sorted(reference_rows) != list(range(1, SLOTS_PER_DAY + 1)):
        raise SystemExit("Beijing reference date does not carry 48 unique slots")

    source_hours = {
        tier: _hour_span(slots) for tier, slots in source_period_slots.items()
    }
    midday_hours = {
        tier: _hour_span(slots) for tier, slots in MIDDAY_VALLEY_SLOTS.items()
    }
    for label, hours in (("source", source_hours), ("midday_valley", midday_hours)):
        if set(hours) != {"valley", "flat", "peak"}:
            raise SystemExit(f"{label} layout does not carry the three tiers")
        for tier, value in hours.items():
            if value != 8.0:
                raise SystemExit(
                    f"{label} tier {tier!r} spans {value} h, expected 8.0 h"
                )
    covered = sorted(
        slot for slots in MIDDAY_VALLEY_SLOTS.values() for slot in slots
    )
    if covered != list(range(1, SLOTS_PER_DAY + 1)):
        raise SystemExit("midday_valley layout does not partition the 48 slots")

    midday_period_by_slot = {
        slot: tier for tier, slots in MIDDAY_VALLEY_SLOTS.items() for slot in slots
    }

    # ---- uniform tier price ---------------------------------------------
    source_depot = [
        float(reference_rows[slot][idx["depot_energy_cny_per_kwh"]])
        for slot in range(1, SLOTS_PER_DAY + 1)
    ]
    source_public = [
        float(reference_rows[slot][idx["public_energy_cny_per_kwh"]])
        for slot in range(1, SLOTS_PER_DAY + 1)
    ]
    uniform_depot_value = _daily_mean(source_depot)
    uniform_public_value = _daily_mean(source_public)
    uniform_depot_text = repr(uniform_depot_value)
    uniform_public_text = repr(uniform_public_value)
    uniform_total_value = uniform_public_value + float(service_fee)
    uniform_total_text = repr(uniform_total_value)
    if float(uniform_depot_text) != uniform_depot_value:
        raise SystemExit("uniform depot price does not round-trip through text")
    if (
        abs(
            (float(uniform_public_text) + float(service_fee))
            - float(uniform_total_text)
        )
        > 1e-12
    ):
        raise SystemExit("uniform public price components do not close")

    # ---- rewrite the Beijing lines --------------------------------------
    midday_lines: list[str] = []
    uniform_lines: list[str] = []
    rewritten = 0
    for line in data_lines:
        fields = _fields(line)
        if fields[idx["city"]] != TARGET_CITY:
            midday_lines.append(line)
            uniform_lines.append(line)
            continue
        slot = int(fields[idx["hourly_calendar_row"]])
        if int(fields[idx["minute_of_day"]]) != (slot - 1) * SLOT_MINUTES:
            raise SystemExit(f"slot {slot} minute_of_day disagrees with its index")
        if fields[idx["public_service_fee_cny_per_kwh"]] != service_fee:
            raise SystemExit("Beijing service fee is not constant across the file")

        tier = midday_period_by_slot[slot]
        midday = list(fields)
        midday[idx["tariff_period"]] = tier
        midday[idx["depot_energy_cny_per_kwh"]] = tiers[tier][
            "depot_energy_cny_per_kwh"
        ]
        midday[idx["public_energy_cny_per_kwh"]] = tiers[tier][
            "public_energy_cny_per_kwh"
        ]
        midday[idx["public_total_cny_per_kwh"]] = tiers[tier][
            "public_total_cny_per_kwh"
        ]
        midday_lines.append(",".join(midday))

        uniform = list(fields)
        uniform[idx["tariff_period"]] = "flat"
        uniform[idx["depot_energy_cny_per_kwh"]] = uniform_depot_text
        uniform[idx["public_energy_cny_per_kwh"]] = uniform_public_text
        uniform[idx["public_total_cny_per_kwh"]] = uniform_total_text
        uniform_lines.append(",".join(uniform))
        rewritten += 1

    expected_rewrites = len(beijing_dates) * SLOTS_PER_DAY
    if rewritten != expected_rewrites:
        raise SystemExit(
            f"rewrote {rewritten} Beijing rows, expected {expected_rewrites}"
        )

    # ---- only the four columns moved ------------------------------------
    for produced in (midday_lines, uniform_lines):
        for original, new in zip(data_lines, produced, strict=True):
            if original == new:
                continue
            old_fields = _fields(original)
            new_fields = _fields(new)
            moved = {
                header[position]
                for position, (left, right) in enumerate(
                    zip(old_fields, new_fields, strict=True)
                )
                if left != right
            }
            if not moved <= set(MUTABLE_COLUMNS):
                raise SystemExit(
                    f"a column outside {MUTABLE_COLUMNS} changed: {sorted(moved)}"
                )

    _write_calendar(midday_dir / CALENDAR_FILENAME, header_line, midday_lines)
    _write_calendar(uniform_dir / CALENDAR_FILENAME, header_line, uniform_lines)

    # ---- the three daily unweighted means must agree bit for bit --------
    def _reference_prices(path: Path, column: str) -> list[float]:
        head, rows = _read_lines(path)
        columns = {name: pos for pos, name in enumerate(_fields(head))}
        by_slot: dict[int, float] = {}
        for row in rows:
            fields = _fields(row)
            if (
                fields[columns["city"]] != TARGET_CITY
                or fields[columns["date"]] != REFERENCE_DATE
            ):
                continue
            by_slot[int(fields[columns["hourly_calendar_row"]])] = float(
                fields[columns[column]]
            )
        return [by_slot[slot] for slot in range(1, SLOTS_PER_DAY + 1)]

    means: dict[str, dict[str, float]] = {}
    for label, path in (
        ("original", source_path),
        ("midday_valley", midday_dir / CALENDAR_FILENAME),
        ("uniform", uniform_dir / CALENDAR_FILENAME),
    ):
        means[label] = {
            "depot_energy_cny_per_kwh": _daily_mean(
                _reference_prices(path, "depot_energy_cny_per_kwh")
            ),
            "public_total_cny_per_kwh": _daily_mean(
                _reference_prices(path, "public_total_cny_per_kwh")
            ),
        }
    for column in ("depot_energy_cny_per_kwh", "public_total_cny_per_kwh"):
        values = {label: means[label][column] for label in means}
        if len(set(values.values())) != 1:
            raise SystemExit(
                f"daily unweighted mean of {column} is not identical across the "
                f"three calendars: {values}"
            )

    # ---- midday_discount：绿色充电窗口补贴 -------------------------------
    # 时段结构一个字不动，只把 12:00-15:00 六个槽的电价压到谷价，差价由财政补。
    # 因此它**不进**上面那两条断言（三档各 8 h、日均电价逐位相等），
    # 下面这一整段是它自己的断言。
    valley_energy_text = tiers["valley"]["depot_energy_cny_per_kwh"]
    valley_total_text = tiers["valley"]["public_total_cny_per_kwh"]
    valley_energy = float(valley_energy_text)
    if tiers["valley"]["public_energy_cny_per_kwh"] != valley_energy_text:
        raise SystemExit("valley depot price differs from valley public price")
    if abs((valley_energy + float(service_fee)) - float(valley_total_text)) > 1e-12:
        raise SystemExit("valley price components do not close")

    discount_lines: list[str] = []
    discount_rewritten = 0
    discount_kept = 0
    # 窗口内每个槽的原始 (时段标签, 电度价, 公共总价)，顺带核 28 个日期一致。
    window_original: dict[int, tuple[str, str, str]] = {}
    for line in data_lines:
        fields = _fields(line)
        if fields[idx["city"]] != TARGET_CITY:
            discount_lines.append(line)
            continue
        slot = int(fields[idx["hourly_calendar_row"]])
        if int(fields[idx["minute_of_day"]]) != (slot - 1) * SLOT_MINUTES:
            raise SystemExit(f"slot {slot} minute_of_day disagrees with its index")
        if slot not in MIDDAY_DISCOUNT_SLOTS:
            # 窗口外的 42 个槽：整行照抄，一个字节都不碰。
            discount_lines.append(line)
            discount_kept += 1
            continue
        observed = (
            fields[idx["tariff_period"]],
            fields[idx["depot_energy_cny_per_kwh"]],
            fields[idx["public_total_cny_per_kwh"]],
        )
        if fields[idx["depot_energy_cny_per_kwh"]] != fields[
            idx["public_energy_cny_per_kwh"]
        ]:
            raise SystemExit(
                f"slot {slot}: depot price differs from public energy price"
            )
        if fields[idx["public_service_fee_cny_per_kwh"]] != service_fee:
            raise SystemExit(f"slot {slot}: service fee is not the constant one")
        recorded = window_original.setdefault(slot, observed)
        if recorded != observed:
            raise SystemExit(
                f"slot {slot} is not identical across the 28 dates: "
                f"{recorded} vs {observed}"
            )
        row = list(fields)
        row[idx["tariff_period"]] = MIDDAY_DISCOUNT_PERIOD_LABEL
        row[idx["depot_energy_cny_per_kwh"]] = valley_energy_text
        row[idx["public_energy_cny_per_kwh"]] = valley_energy_text
        row[idx["public_total_cny_per_kwh"]] = valley_total_text
        discount_lines.append(",".join(row))
        discount_rewritten += 1

    if sorted(window_original) != list(MIDDAY_DISCOUNT_SLOTS):
        raise SystemExit(
            f"midday_discount window slots not all present: "
            f"{sorted(window_original)}"
        )
    expected_discount_rewrites = len(beijing_dates) * len(MIDDAY_DISCOUNT_SLOTS)
    expected_discount_kept = len(beijing_dates) * (
        SLOTS_PER_DAY - len(MIDDAY_DISCOUNT_SLOTS)
    )
    if discount_rewritten != expected_discount_rewrites:
        raise SystemExit(
            f"midday_discount rewrote {discount_rewritten} rows, "
            f"expected {expected_discount_rewrites}"
        )
    if discount_kept != expected_discount_kept:
        raise SystemExit(
            f"midday_discount kept {discount_kept} Beijing rows verbatim, "
            f"expected {expected_discount_kept}"
        )

    # 断言一：窗口外的每一行（含非北京行）与源文件逐字节相同；
    # 断言二：被改的行只动了那四列。
    changed_rows = 0
    for original, new in zip(data_lines, discount_lines, strict=True):
        if original == new:
            continue
        changed_rows += 1
        old_fields = _fields(original)
        new_fields = _fields(new)
        if old_fields[idx["city"]] != TARGET_CITY:
            raise SystemExit("midday_discount changed a non-Beijing row")
        if int(old_fields[idx["hourly_calendar_row"]]) not in MIDDAY_DISCOUNT_SLOTS:
            raise SystemExit(
                "midday_discount changed a Beijing row outside 12:00-15:00"
            )
        moved = {
            header[position]
            for position, (left, right) in enumerate(
                zip(old_fields, new_fields, strict=True)
            )
            if left != right
        }
        if not moved <= set(MUTABLE_COLUMNS):
            raise SystemExit(
                f"a column outside {MUTABLE_COLUMNS} changed: {sorted(moved)}"
            )
    if changed_rows != expected_discount_rewrites:
        raise SystemExit(
            f"midday_discount has {changed_rows} rows differing from the source, "
            f"expected {expected_discount_rewrites}"
        )

    _write_calendar(discount_dir / CALENDAR_FILENAME, header_line, discount_lines)

    # 写出后复读，逐槽核对（不信内存里的 list，只信落盘的文件）。
    discount_head, discount_rows = _read_lines(discount_dir / CALENDAR_FILENAME)
    if discount_head != header_line:
        raise SystemExit("midday_discount header changed")
    if len(discount_rows) != len(data_lines):
        raise SystemExit("midday_discount row count changed")
    for original, new in zip(data_lines, discount_rows, strict=True):
        new_fields = _fields(new)
        if new_fields[idx["city"]] != TARGET_CITY:
            if new != original:
                raise SystemExit("midday_discount non-Beijing row is not verbatim")
            continue
        slot = int(new_fields[idx["hourly_calendar_row"]])
        if slot not in MIDDAY_DISCOUNT_SLOTS:
            if new != original:
                raise SystemExit(
                    f"midday_discount Beijing slot {slot} is not verbatim"
                )
            continue
        if new_fields[idx["tariff_period"]] != MIDDAY_DISCOUNT_PERIOD_LABEL:
            raise SystemExit(f"slot {slot} label is not {MIDDAY_DISCOUNT_PERIOD_LABEL}")
        if new_fields[idx["depot_energy_cny_per_kwh"]] != valley_energy_text:
            raise SystemExit(f"slot {slot} depot price is not the valley price")
        if new_fields[idx["public_energy_cny_per_kwh"]] != valley_energy_text:
            raise SystemExit(f"slot {slot} public energy price is not the valley price")
        if new_fields[idx["public_total_cny_per_kwh"]] != valley_total_text:
            raise SystemExit(f"slot {slot} public total is not the valley total")
        if (
            abs(
                float(new_fields[idx["public_energy_cny_per_kwh"]])
                + float(new_fields[idx["public_service_fee_cny_per_kwh"]])
                - float(new_fields[idx["public_total_cny_per_kwh"]])
            )
            > 1e-12
        ):
            raise SystemExit(f"slot {slot}: energy + service != total")

    discount_depot_mean = _daily_mean(
        _reference_prices(discount_dir / CALENDAR_FILENAME, "depot_energy_cny_per_kwh")
    )
    discount_total_mean = _daily_mean(
        _reference_prices(discount_dir / CALENDAR_FILENAME, "public_total_cny_per_kwh")
    )
    if discount_depot_mean >= means["original"]["depot_energy_cny_per_kwh"]:
        raise SystemExit(
            "midday_discount daily mean is not below the original; "
            "a subsidy must lower it"
        )

    # 逐槽差价表（README 与日志共用）。
    discount_rows_table: list[tuple[int, str, str, str, float]] = []
    for slot in MIDDAY_DISCOUNT_SLOTS:
        period, depot_text, total_text = window_original[slot]
        start_minute = (slot - 1) * SLOT_MINUTES
        clock = f"{start_minute // 60:02d}:{start_minute % 60:02d}"
        end_minute = start_minute + SLOT_MINUTES
        clock = f"{clock}-{end_minute // 60:02d}:{end_minute % 60:02d}"
        discount_rows_table.append(
            (slot, clock, period, depot_text, float(depot_text) - valley_energy)
        )
        _ = total_text

    midday_counter = Counter(midday_period_by_slot.values())
    print(f"source calendar    : {source_path.relative_to(repo)}")
    print(f"Beijing dates      : {len(beijing_dates)} (all rewritten)")
    print(f"Beijing rows moved : {rewritten}")
    print("")
    print("tier hours (must be 8.0 / 8.0 / 8.0):")
    for tier in ("valley", "flat", "peak"):
        print(
            f"  {tier:<7} original {source_hours[tier]:.1f} h   "
            f"midday_valley {midday_hours[tier]:.1f} h   "
            f"({len(source_period_slots[tier])} / {midday_counter[tier]} slots)"
        )
    print("")
    print(f"Beijing {REFERENCE_DATE} daily unweighted mean price "
          "(48-slot arithmetic mean):")
    for label in ("original", "midday_valley", "uniform"):
        print(
            f"  {label:<14} depot_energy {means[label]['depot_energy_cny_per_kwh']!r}"
            f"   public_total {means[label]['public_total_cny_per_kwh']!r}"
        )
    print("  -> all three identical: PASS")
    print("")
    print(f"uniform slot price : depot/public {uniform_depot_text}, "
          f"total {uniform_total_text}")
    print("")
    print("midday_discount（绿色充电窗口补贴，12:00-15:00 六个槽）：")
    print(f"  谷价 {valley_energy_text}（公共总价 {valley_total_text}）")
    print(f"  {'槽':<4}{'时段':<14}{'原时段':<8}{'原电度价':<14}{'差价 = 原价 − 谷价'}")
    for slot, clock, period, depot_text, delta in discount_rows_table:
        print(f"  {slot:<4}{clock:<14}{period:<8}{depot_text:<14}{delta!r}")
    print(
        f"  窗口外 {SLOTS_PER_DAY - len(MIDDAY_DISCOUNT_SLOTS)} 槽 × "
        f"{len(beijing_dates)} 日 = {discount_kept} 行逐字节同源；"
        f"窗口内改写 {discount_rewritten} 行"
    )
    print(
        f"  日均未加权电价 depot_energy {discount_depot_mean!r} < 原 "
        f"{means['original']['depot_energy_cny_per_kwh']!r}"
        f"（public_total {discount_total_mean!r} < "
        f"{means['original']['public_total_cny_per_kwh']!r}）"
        "  —— 这是补贴，不是重排，日均电价本就该降"
    )

    readme_common = f"""
生成器：`solver/scripts/build_counterfactual_tariff_calendar.py`
来源日历：`{source_path.relative_to(repo)}`
（sha256 `{_sha256(source_path)}`）

只改 `city=beijing` 的行，**全部 {len(beijing_dates)} 个日期同样处理**（共 {rewritten} 行）；
其余八个城市的行逐字节照抄。改动的列只有
`tariff_period` / `depot_energy_cny_per_kwh` / `public_energy_cny_per_kwh` /
`public_total_cny_per_kwh` 四列；`public_service_fee_cny_per_kwh`（{service_fee}）不动，
且 `public_energy + public_service == public_total` 逐位成立。
碳强度列、柴油列、映射列、状态列一律不动。

## 北京 {REFERENCE_DATE} 的日均未加权电价（48 槽算术平均，`math.fsum`）

| 日历 | `depot_energy_cny_per_kwh` | `public_total_cny_per_kwh` |
|---|---|---|
| 原日历 | {means['original']['depot_energy_cny_per_kwh']!r} | {means['original']['public_total_cny_per_kwh']!r} |
| 午谷日历 | {means['midday_valley']['depot_energy_cny_per_kwh']!r} | {means['midday_valley']['public_total_cny_per_kwh']!r} |
| 均一日历 | {means['uniform']['depot_energy_cny_per_kwh']!r} | {means['uniform']['public_total_cny_per_kwh']!r} |

**三者逐位相等**，生成器在写出后复读三份文件复算，不等即退出。
所以两个反事实情景改的是**时段结构**，不是电价水平。

## 三档小时数

| 档 | 原日历 | 午谷日历 |
|---|---:|---:|
| 谷 valley | {source_hours['valley']:.1f} h | {midday_hours['valley']:.1f} h |
| 平 flat | {source_hours['flat']:.1f} h | {midday_hours['flat']:.1f} h |
| 峰 peak | {source_hours['peak']:.1f} h | {midday_hours['peak']:.1f} h |

## 用法

```
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src'
.public-hgs-venv/bin/python3 solver/scripts/build_charge_timing_comparison.py \\
    --tariff-calendar-authority <本目录> ...
```
""".strip()

    midday_readme = f"""# 反事实时段方案日历 · 午间设谷（2026-09-04）

**这是构造情景，不是任何一份现行电价文件。** 它把北京现行的三档电价数值
（谷 {tiers['valley']['depot_energy_cny_per_kwh']} / 平 {tiers['flat']['depot_energy_cny_per_kwh']} /
峰 {tiers['peak']['depot_energy_cny_per_kwh']} 元/kWh）按「午间设谷」的时段边界重排：

- 谷 `valley`：01:00–06:00、12:00–15:00（合计 8.0 h）
- 峰 `peak`：10:00–12:00、17:00–23:00（合计 8.0 h）
- 平 `flat`：00:00–01:00、06:00–10:00、15:00–17:00、23:00–24:00（合计 8.0 h）

引用时只说「午间设谷这一做法有省级先例」，**不要引任何一份文件的价格**，
也不要把它写成对某地电价的现实观察。

{readme_common}
"""

    uniform_readme = f"""# 反事实时段方案日历 · 均一电价（2026-09-04）

**这是构造情景，不是任何一份现行电价文件。** 北京全部 48 个半小时槽都取
原 48 槽电价的算术平均值（`depot_energy` = `public_energy` =
{uniform_depot_text}，`public_total` = {uniform_total_text}），
`tariff_period` 一律标 `flat`。

作用是对照：日均电价水平与原日历逐位相同、时段结构被抹平，
所以它把「电价水平效应」与「时段结构效应」分开。

{readme_common}
"""

    discount_table = "\n".join(
        f"| {slot} | {clock} | {period} | {depot_text} | {valley_energy_text} | {delta!r} |"
        for slot, clock, period, depot_text, delta in discount_rows_table
    )

    discount_common = f"""
生成器：`solver/scripts/build_counterfactual_tariff_calendar.py`
来源日历：`{source_path.relative_to(repo)}`
（sha256 `{_sha256(source_path)}`）

只改 `city=beijing` 的行，**全部 {len(beijing_dates)} 个日期同样处理**；
每个日期只动 12:00–15:00 的 {len(MIDDAY_DISCOUNT_SLOTS)} 个槽（共 {discount_rewritten} 行），
同日其余 {SLOTS_PER_DAY - len(MIDDAY_DISCOUNT_SLOTS)} 个槽（共 {discount_kept} 行）与其余八个城市的行
一律**逐字节照抄**。改动的列只有 `tariff_period` / `depot_energy_cny_per_kwh` /
`public_energy_cny_per_kwh` / `public_total_cny_per_kwh` 四列；
`public_service_fee_cny_per_kwh`（{service_fee}）不动。
碳强度列、柴油列、映射列、状态列一律不动。

## 用法

```
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src'
zsh solver/scripts/run_lever_green_window_one.sh <输出根目录> "01"
```
""".strip()

    discount_readme = f"""# 反事实电价日历 · 绿色充电窗口补贴（2026-09-04）

**这是构造情景，不是任何一份现行电价文件。** 北京现行分时电价的时段结构
**一个字不动**，只把 **12:00–15:00** 这 6 个半小时槽（槽 {MIDDAY_DISCOUNT_SLOTS[0]}–{MIDDAY_DISCOUNT_SLOTS[-1]}）
的电度价按**谷价** {valley_energy_text} 元/kWh 计，差价由财政补贴。
这 6 个槽的 `tariff_period` 标成 `{MIDDAY_DISCOUNT_PERIOD_LABEL}`，纯记录用
（该列全程没有任何代码读取或校验，只在 `solver/src/setp_solver/china81.py` 第 1174 行
原样搬进 profile 字典）。

## 改了哪 6 个槽、原价、每槽差价

| 槽 | 时段 | 原 `tariff_period` | 原电度价 | 补贴后电度价（谷价） | 每 kWh 差价 |
|---:|---|---|---:|---:|---:|
{discount_table}

公共桩服务费 {service_fee} 元/kWh 不动，所以 `public_total` 同步降到
{valley_total_text}，且 `public_energy + public_service == public_total` 逐位成立。
车场（`depot_energy`）与公共桩（`public_energy`）在北京每一行本就相等，
**因此每 kWh 的补贴额对两者完全相同**，财政支出核算不必按节点类型分叉。

## ⚠️ 日均电价会低于原日历——这是补贴，不是重排

另外两份反事实日历（`midday_valley` / `uniform`）改的是**时段结构**，
日均未加权电价与原日历**逐位相等**。这一份不是：它是**价格补贴**，
把窗口内 6 个槽压到谷价，日均电价必然下降。北京 {REFERENCE_DATE} 的 48 槽算术平均：

| 日历 | `depot_energy_cny_per_kwh` | `public_total_cny_per_kwh` |
|---|---|---|
| 原日历 | {means['original']['depot_energy_cny_per_kwh']!r} | {means['original']['public_total_cny_per_kwh']!r} |
| 本日历（补贴后企业实付） | {discount_depot_mean!r} | {discount_total_mean!r} |

生成器为此单独写了一套断言（**不进**「三档各 8.0 h」与「三份日均逐位相等」那两条）：

1. 窗口外的 42 个北京槽 × {len(beijing_dates)} 个日期 = {discount_kept} 行，与源文件**逐字节相同**；
   非北京行同样逐字节相同；
2. 窗口内 {discount_rewritten} 行只动了那四列，且写盘后**复读文件**逐行核对
   标签 / 电度价 / 公共总价 / 价格闭合；
3. 补贴后的日均电价必须**低于**原日历（否则退出）；逐槽差价见上表，生成时逐行打印。

{discount_common}
"""

    (midday_dir / "README.md").write_text(midday_readme, encoding="utf-8")
    (uniform_dir / "README.md").write_text(uniform_readme, encoding="utf-8")
    (discount_dir / "README.md").write_text(discount_readme, encoding="utf-8")

    print("")
    print(f"written -> {midday_dir.relative_to(repo)}")
    print(f"written -> {uniform_dir.relative_to(repo)}")
    print(f"written -> {discount_dir.relative_to(repo)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
