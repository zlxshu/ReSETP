from __future__ import annotations

import argparse
import json
from pathlib import Path

from .catalog import donor_instance_paths, migrate_goeke_instances, resolve_goeke_instance
from .config import DynamicEventConfig, ScenarioConfig
from .generator import generate_scenario
from .io import ensure_data_roots, write_scenario_bundle


def _parse_ratio(raw: str, expected_len: int) -> tuple[float, ...]:
    values = tuple(float(part.strip()) for part in raw.split(",") if part.strip())
    if len(values) != expected_len or any(value < 0 for value in values) or sum(values) <= 0:
        raise argparse.ArgumentTypeError(f"Expected {expected_len} non-negative comma-separated weights, got: {raw}")
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="setp-lab")
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser("generate", help="Generate a controllable SETP/VRP scenario bundle.")
    generate.add_argument("--output-dir", required=True)
    generate.add_argument("--scenario-id", default="synthetic_setp")
    generate.add_argument("--depots", "--num-depots", dest="depots", type=int, default=2)
    generate.add_argument("--stations", "--num-stations", dest="stations", type=int, default=3)
    # v2026-06-12: Z0b exposes public-station C_s; depot C_s is generated from customer-count upper bound.
    generate.add_argument("--station-chargers", "--station-capacity", dest="station_chargers", type=int, default=1)
    generate.add_argument("--customers", type=int, default=25)
    generate.add_argument("--seed", type=int, default=1)
    # v2026-06-12: expose fleet composition as a structural instance parameter for EV-heavy E5 gates.
    generate.add_argument("--num-cv", type=int, default=10)
    generate.add_argument("--num-ev", type=int, default=10)
    generate.add_argument("--coord-mode", choices=["synthetic", "empirical"], default="synthetic")
    generate.add_argument("--demand-mode", choices=["empirical", "uniform", "truncnorm", "gamma", "lognormal"], default="truncnorm")
    generate.add_argument("--time-window-mode", choices=["empirical", "uniform", "clustered", "tight", "mixed"], default="uniform")
    generate.add_argument("--horizon-start", type=float, default=0.0)
    generate.add_argument("--horizon-end", type=float, default=32400.0)
    # v2026-06-12: Q1 shifted 24h bundle controls; opt-in only.
    generate.add_argument("--time-window-shift-seconds", type=float, default=0.0)
    generate.add_argument("--empirical-exact-base", action="store_true")
    generate.add_argument("--depot-due-time", type=float)
    generate.add_argument("--base-instance")
    generate.add_argument("--data-root", default="data_bundle")
    generate.add_argument("--base-id", "--instance", dest="base_id", help="Goeke instance id from data_root/catalog/goeke_instances.json, e.g. E-UK25_01.")
    generate.add_argument("--synthetic-only", action="store_true", help="Do not switch empirical modes when using --base-id/--base-instance.")
    generate.add_argument("--carbon-profile-path")
    generate.add_argument("--carbon-alignment-mode", choices=["none", "fixed_utc_anchor", "daily_profile", "first_csv_record"], default="none")
    generate.add_argument("--carbon-time-anchor-utc")
    generate.add_argument("--dynamic-events", type=int, default=0)
    generate.add_argument("--dynamic-event-rate", type=float)
    generate.add_argument("--dynamic-event-ratio", default="5,2,1,1", help="add,cancel,demand_change,time_window_change ratio.")
    generate.add_argument("--time-window-change-ratio", default="1,3,1", help="shrink,keep,extend ratio for time_window_change events.")
    generate.add_argument("--donor-limit", type=int, default=80, help="Max migrated Goeke instances used as add-event donor pool.")
    generate.add_argument("--no-evrptwmf", action="store_true")

    catalog = sub.add_parser("catalog", help="Create standard portable data-root folders.")
    catalog.add_argument("data_root")

    migrate = sub.add_parser("migrate-goeke", help="Copy Goeke E-UK*.txt instances into this project data bundle and write a catalog.")
    migrate.add_argument("--source-dir", required=True)
    migrate.add_argument("--data-root", default="data_bundle")
    migrate.add_argument("--overwrite", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "catalog":
        roots = ensure_data_roots(Path(args.data_root))
        print(json.dumps({k: str(v) for k, v in roots.items()}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "migrate-goeke":
        catalog_payload = migrate_goeke_instances(args.source_dir, args.data_root, overwrite=args.overwrite)
        print(json.dumps({
            "data_root": catalog_payload["data_root"],
            "catalog": str(Path(args.data_root) / "catalog" / "goeke_instances.json"),
            "entry_count": catalog_payload["entry_count"],
        }, ensure_ascii=False, indent=2))
        return 0

    base_instance = args.base_instance
    add_event_sources: tuple[str, ...] = ()
    if args.base_id:
        base_instance = str(resolve_goeke_instance(args.data_root, args.base_id))
        add_event_sources = donor_instance_paths(args.data_root, args.base_id, limit=args.donor_limit)
    coord_mode = args.coord_mode
    demand_mode = args.demand_mode
    time_window_mode = args.time_window_mode
    if base_instance and not args.synthetic_only:
        coord_mode = "empirical"
        demand_mode = "empirical"
        time_window_mode = "empirical"
    dynamic = DynamicEventConfig(
        enabled=args.dynamic_events > 0 or (args.dynamic_event_rate is not None and args.dynamic_event_rate > 0),
        n_events=args.dynamic_events,
        event_rate=args.dynamic_event_rate,
        event_ratio=_parse_ratio(args.dynamic_event_ratio, 4),
        time_window_change_ratio=_parse_ratio(args.time_window_change_ratio, 3),
    )
    config = ScenarioConfig(
        scenario_id=args.scenario_id,
        n_depots=args.depots,
        n_stations=args.stations,
        station_capacity=args.station_chargers,
        n_customers=args.customers,
        seed=args.seed,
        num_cv=args.num_cv,
        num_ev=args.num_ev,
        coord_mode=coord_mode,
        demand_mode=demand_mode,
        time_window_mode=time_window_mode,
        horizon_start=args.horizon_start,
        horizon_end=args.horizon_end,
        time_window_shift_seconds=args.time_window_shift_seconds,
        empirical_exact_base=args.empirical_exact_base,
        depot_due_time=args.depot_due_time,
        carbon_alignment_mode=args.carbon_alignment_mode,
        carbon_time_anchor_utc=args.carbon_time_anchor_utc,
        carbon_profile_path=args.carbon_profile_path,
        base_instance_path=base_instance,
        add_event_source_paths=add_event_sources,
        dynamic_event_config=dynamic,
    )
    scenario = generate_scenario(config)
    paths = write_scenario_bundle(
        scenario,
        args.output_dir,
        config=config.to_dict(),
        export_evrptwmf=not args.no_evrptwmf,
        export_dynamic=True,
    )
    print(json.dumps({"paths": paths, "validation": scenario.validation}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
