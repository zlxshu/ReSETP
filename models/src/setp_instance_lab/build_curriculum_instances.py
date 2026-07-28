from __future__ import annotations

import argparse
import copy
import json
import shutil
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Iterable

from .config import DynamicEventConfig, ScenarioConfig
from .generator import generate_scenario
from .io import write_scenario_bundle


DR_MANIFEST_SCHEMA_VERSION = "dr-alns-ppo-bundle-manifest.v1"
DEFAULT_TEMPLATE_MANIFEST = Path(
    "models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113/scenario_manifest.json"
)
DEFAULT_OUTPUT_ROOT = Path("models/data_bundle/generated_instances")
DEFAULT_MANIFEST_OUTPUT = Path(
    "solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot08/training_bundle_manifest_curriculum.json"
)
DEFAULT_HELD_OUT = "models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113"
DEFAULT_FORMAL_EVAL = "models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113"
CARBON_PROFILE_RELATIVE = Path("data/Carbon/时变碳强度/regional_carbon_intensity_2025-11-01_to_2025-11-30.csv")
REQUIRED_BUNDLE_FILES = ("instance.json", "distance_matrix.npy", "carbon_profile.csv", "scenario_manifest.json")
SCENARIO_TUPLE_FIELDS = {"coord_bounds", "carbon_regions", "add_event_source_paths"}
DYNAMIC_TUPLE_FIELDS = {"event_ratio", "time_window_change_ratio"}


@dataclass(frozen=True)
class CurriculumSpec:
    base_id: str
    n_customers: int
    seed: int

    @property
    def scenario_id(self) -> str:
        return f"{self.base_id}__curric_d2_s3_seed{self.seed}_24h"

    @property
    def bundle_rel_path(self) -> str:
        return f"models/data_bundle/generated_instances/{self.scenario_id}"


DEFAULT_SPECS: tuple[CurriculumSpec, ...] = tuple(
    [CurriculumSpec(f"E-UK25_{idx:02d}", 25, idx) for idx in range(2, 10)]
    + [CurriculumSpec(f"E-UK50_{idx:02d}", 50, idx) for idx in range(1, 5)]
)


def build_curriculum_instances(
    *,
    root: str | Path,
    output_root: str | Path | None = None,
    manifest_output: str | Path | None = None,
    template_manifest: str | Path | None = None,
    specs: Iterable[CurriculumSpec] = DEFAULT_SPECS,
    overwrite: bool = False,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    output_root_path = _resolve_under_root(root_path, output_root or DEFAULT_OUTPUT_ROOT)
    manifest_output_path = _resolve_under_root(root_path, manifest_output or DEFAULT_MANIFEST_OUTPUT)
    template_manifest_path = _resolve_under_root(root_path, template_manifest or DEFAULT_TEMPLATE_MANIFEST)
    template_config = _load_template_config(template_manifest_path)

    rows: list[dict[str, Any]] = []
    for spec in specs:
        output_dir = output_root_path / spec.scenario_id
        if output_dir.exists():
            if not overwrite:
                raise FileExistsError(f"Refusing to overwrite existing curriculum bundle: {output_dir}")
            _remove_existing_output(output_dir, output_root_path)

        scenario_config, manifest_config = build_config_for_spec(root_path, template_config, spec)
        scenario = generate_scenario(scenario_config)
        write_scenario_bundle(scenario, output_dir, config=manifest_config)
        bundle_manifest = validate_generated_bundle(output_dir, expected_n=spec.n_customers)
        rows.append(
            {
                "name": spec.scenario_id,
                "path": _manifest_bundle_path(root_path, output_dir),
                "n_customers": int(bundle_manifest["validation"]["customer_count"]),
                "validation_passed": bool(bundle_manifest["validation"]["passed"]),
            }
        )

    manifest = build_curriculum_manifest(rows)
    manifest_output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_output_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return {"bundles": rows, "manifest_path": str(manifest_output_path), "manifest": manifest}


def build_config_for_spec(
    root: str | Path,
    template_config: dict[str, Any],
    spec: CurriculumSpec,
) -> tuple[ScenarioConfig, dict[str, Any]]:
    root_path = Path(root).resolve()
    base_instance_path = root_path / "models" / "data_bundle" / "raw_instances" / "goeke_uk" / f"{spec.base_id}.txt"
    carbon_profile_path = root_path / CARBON_PROFILE_RELATIVE
    if not base_instance_path.is_file():
        raise FileNotFoundError(f"Missing base instance: {base_instance_path}")
    if not carbon_profile_path.is_file():
        raise FileNotFoundError(f"Missing carbon profile: {carbon_profile_path}")

    manifest_config = copy.deepcopy(template_config)
    manifest_config.update(
        {
            "scenario_id": spec.scenario_id,
            "seed": int(spec.seed),
            "base_id": spec.base_id,
            "base_instance_path": str(base_instance_path),
            "n_customers": int(spec.n_customers),
            "carbon_profile_path": str(carbon_profile_path),
            "add_event_source_paths": _filter_10001_paths(manifest_config.get("add_event_source_paths", [])),
        }
    )

    dynamic_config_payload = manifest_config.get("dynamic_event_config", {})
    if not isinstance(dynamic_config_payload, dict):
        raise ValueError("dynamic_event_config must be a JSON object")
    dynamic_kwargs = _dataclass_kwargs(dynamic_config_payload, DynamicEventConfig, DYNAMIC_TUPLE_FIELDS)
    scenario_kwargs = _dataclass_kwargs(manifest_config, ScenarioConfig, SCENARIO_TUPLE_FIELDS)
    scenario_kwargs["dynamic_event_config"] = DynamicEventConfig(**dynamic_kwargs)
    scenario_config = ScenarioConfig(**scenario_kwargs)
    return scenario_config, manifest_config


def validate_generated_bundle(output_dir: str | Path, *, expected_n: int) -> dict[str, Any]:
    bundle_dir = Path(output_dir)
    missing = [name for name in REQUIRED_BUNDLE_FILES if not (bundle_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"{bundle_dir}: missing {', '.join(missing)}")
    manifest = json.loads((bundle_dir / "scenario_manifest.json").read_text(encoding="utf-8"))
    validation = manifest.get("validation")
    if not isinstance(validation, dict):
        raise ValueError(f"{bundle_dir}: scenario_manifest.validation must be an object")
    if validation.get("passed") is not True:
        raise ValueError(f"{bundle_dir}: validation did not pass: {validation}")
    if validation.get("customer_count") != int(expected_n):
        raise ValueError(f"{bundle_dir}: expected customer_count={expected_n}, got {validation.get('customer_count')}")
    return manifest


def build_curriculum_manifest(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": DR_MANIFEST_SCHEMA_VERSION,
        "train": [str(row["path"]) for row in rows],
        "held_out": [DEFAULT_HELD_OUT],
        "formal_eval": [DEFAULT_FORMAL_EVAL],
        "excluded_from_training_reason": {
            "curriculum_small_to_large": (
                "Intentional Daysalilar-style small-to-large DR curriculum: train on 25c/50c generated bundles "
                "and reserve 100c held-out/formal bundles for honest zero-shot validation."
            ),
            "not_verify_or_demo": "These are generated curriculum bundles, not verify/demo toy bundles.",
            "E-UK100_01_reserved": "E-UK100_01 remains formal evaluation only and must not appear in train or donor paths.",
        },
    }


def _load_template_config(template_manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(template_manifest_path.read_text(encoding="utf-8"))
    config = manifest.get("config")
    if not isinstance(config, dict):
        raise ValueError(f"Template scenario_manifest missing config object: {template_manifest_path}")
    return config


def _dataclass_kwargs(payload: dict[str, Any], cls: type, tuple_fields: set[str]) -> dict[str, Any]:
    names = {field.name for field in fields(cls)}
    kwargs = {name: copy.deepcopy(payload[name]) for name in names if name in payload}
    for name in tuple_fields:
        if name in kwargs and isinstance(kwargs[name], list):
            kwargs[name] = tuple(kwargs[name])
    return kwargs


def _filter_10001_paths(paths: Any) -> tuple[str, ...]:
    if paths is None:
        return ()
    if not isinstance(paths, (list, tuple)):
        raise ValueError("add_event_source_paths must be a list or tuple")
    return tuple(str(path) for path in paths if "E-UK100_01" not in str(path))


def _resolve_under_root(root: Path, path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return root / candidate


def _manifest_bundle_path(root: Path, output_dir: Path) -> str:
    resolved_root = root.resolve()
    resolved_output = output_dir.resolve()
    try:
        return resolved_output.relative_to(resolved_root).as_posix()
    except ValueError:
        return str(resolved_output)


def _remove_existing_output(output_dir: Path, output_root: Path) -> None:
    resolved_output = output_dir.resolve()
    resolved_root = output_root.resolve()
    if resolved_output == resolved_root or resolved_root not in resolved_output.parents:
        raise ValueError(f"Refusing to remove output outside curriculum root: {resolved_output}")
    shutil.rmtree(resolved_output)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Pilot08 small curriculum instance bundles and manifest.")
    parser.add_argument("--root", default=".", help="Repository root.")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT), help="Generated bundle output root.")
    parser.add_argument("--manifest-output", default=str(DEFAULT_MANIFEST_OUTPUT), help="Curriculum manifest output JSON.")
    parser.add_argument("--template-manifest", default=str(DEFAULT_TEMPLATE_MANIFEST), help="Template scenario_manifest.json.")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing curriculum bundle directories.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_curriculum_instances(
        root=args.root,
        output_root=args.output_root,
        manifest_output=args.manifest_output,
        template_manifest=args.template_manifest,
        overwrite=args.overwrite,
    )
    for row in result["bundles"]:
        print(
            "CURRICULUM_BUNDLE_OK "
            f"name={row['name']} n={row['n_customers']} validation_passed={row['validation_passed']}"
        )
    print(f"CURRICULUM_MANIFEST_OK output={result['manifest_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
