#!/usr/bin/env python3
"""Generate the independent C8-1 dynamic order stream.

The selected unified instance is read only.  The output directory is a new
stream artifact; no file under the instance package is written.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "solver/src"))
sys.path.insert(0, str(REPO_ROOT / "third_party/setp_hgs_kernel"))
sys.path.insert(0, str(REPO_ROOT / "solver/scripts"))

from run_problem_hgs_private_technical import (  # noqa: E402
    DEPOT_SEARCH_INSTANCE_ID,
    ENDOGENOUS_FLEET_PARAMETERS,
    _build_context,
)
from setp_solver.c8_dynamic_stream import (  # noqa: E402
    C8_BASE_INSTANCE_ID,
    c8_generation_rules,
    generate_c8_stream,
    write_c8_stream,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--output-parent",
        type=Path,
        default=Path("data/dynamic_streams"),
        help="new stream directories are created below this path",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="optional reproducible seed; omitted means derive from target package hash",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repo = args.repo.resolve()
    if DEPOT_SEARCH_INSTANCE_ID != C8_BASE_INSTANCE_ID:
        raise RuntimeError("C8 target identity constants disagree")
    source_dir = (
        repo
        / "data/ChinaInstances/china81_final_suite_v2_20260815/instances"
        / C8_BASE_INSTANCE_ID
    )
    orders_path = source_dir / "orders.csv"
    with orders_path.open(newline="", encoding="utf-8-sig") as handle:
        order_rows = list(csv.DictReader(handle))
    bundle, _initial, _pi0, _context = _build_context(
        repo,
        C8_BASE_INSTANCE_ID,
        fleet_parameters=ENDOGENOUS_FLEET_PARAMETERS,
    )
    stream = generate_c8_stream(
        bundle=bundle,
        order_rows=order_rows,
        source_instance_dir=source_dir,
        seed=args.seed,
    )
    output_parent = args.output_parent
    if not output_parent.is_absolute():
        output_parent = repo / output_parent
    output_dir = output_parent / (
        f"{C8_BASE_INSTANCE_ID}_q500_t30_{stream.stream_content_sha256[:12]}"
    )
    write_c8_stream(
        stream,
        output_dir,
        generator_source=Path(__file__).resolve(),
        rules=c8_generation_rules(stream.protocol),
    )
    print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
