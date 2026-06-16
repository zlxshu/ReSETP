from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "dr-alns-ppo-bundle-manifest.v1"

TRAIN_BUNDLES = (
    "models/data_bundle/generated_instances/verify_20251113",
    "models/data_bundle/generated_instances/verify_20251113_evheavy",
    "models/data_bundle/generated_instances/demo_carbon",
    "models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113",
)

HELD_OUT_BUNDLES = (
    "models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113",
)

FORMAL_EVAL_BUNDLES = (
    "models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113",
    "models/data_bundle/generated_instances/E-UK24h-三班-01",
)

EXCLUDED_FROM_TRAINING_REASON = {
    "100-01/L-main only": "single-main-case training would overfit and is not evidence of general DRL control",
}

REQUIRED_BUNDLE_FILES = ("instance.json", "distance_matrix.npy", "carbon_profile.csv")


def build_manifest() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "train": list(TRAIN_BUNDLES),
        "held_out": list(HELD_OUT_BUNDLES),
        "formal_eval": list(FORMAL_EVAL_BUNDLES),
        "excluded_from_training_reason": dict(EXCLUDED_FROM_TRAINING_REASON),
    }


def validate_manifest(manifest: dict[str, Any], *, root: str | Path = ".") -> None:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported schema_version: {manifest.get('schema_version')!r}")

    train = _checked_bundle_list(manifest, "train")
    held_out = _checked_bundle_list(manifest, "held_out")
    formal_eval = _checked_bundle_list(manifest, "formal_eval")
    all_bundles = train + held_out + formal_eval
    duplicates = sorted({path for path in all_bundles if all_bundles.count(path) > 1})
    if duplicates:
        joined = ", ".join(duplicates)
        raise ValueError(f"Bundle appears more than once: {joined}")

    missing = missing_bundle_files(all_bundles, root=root)
    if missing:
        details = "; ".join(f"{bundle}: {', '.join(files)}" for bundle, files in missing.items())
        raise FileNotFoundError(f"Missing required bundle files: {details}")


def missing_bundle_files(bundle_dirs: list[str] | tuple[str, ...], *, root: str | Path = ".") -> dict[str, list[str]]:
    root_path = Path(root)
    missing: dict[str, list[str]] = {}
    for bundle_dir in bundle_dirs:
        bundle_path = root_path / bundle_dir
        missing_files = [name for name in REQUIRED_BUNDLE_FILES if not (bundle_path / name).is_file()]
        if missing_files:
            missing[bundle_dir] = missing_files
    return missing


def load_manifest(path: str | Path, *, root: str | Path = ".", validate: bool = True) -> dict[str, Any]:
    manifest_path = Path(path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError(f"Manifest must be a JSON object: {manifest_path}")
    if validate:
        validate_manifest(manifest, root=root)
    return manifest


def write_manifest(path: str | Path, *, root: str | Path = ".") -> dict[str, Any]:
    manifest = build_manifest()
    validate_manifest(manifest, root=root)
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def _checked_bundle_list(manifest: dict[str, Any], key: str) -> list[str]:
    value = manifest.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"Manifest field {key!r} must be a list of bundle path strings")
    return value


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and validate the DR-ALNS-PPO training bundle manifest.")
    parser.add_argument(
        "--output",
        default="solver/reports/dr_alns_ppo_v2/training_bundle_manifest.json",
        help="Path where the manifest JSON will be written.",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root used to validate relative bundle paths.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    manifest = write_manifest(args.output, root=args.root)
    bundle_count = len(manifest["train"]) + len(manifest["held_out"]) + len(manifest["formal_eval"])
    print(f"DR_ALNS_PPO_MANIFEST_OK bundles={bundle_count} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
