"""Repair this task family's hash manifests that included AppleDouble files."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EVENT = "HASH_CONTAMINATED_APPLEDOUBLE_CLEANED_BEFORE_FINAL_AUDIT"
REPORT_NOTE = (
    "\n\n证据卫生修复：首次哈希清单误含macOS AppleDouble旁车，已标"
    f"`{EVENT}`。原始运行、比较和判定未改；最终清单删除旁车项并从"
    "现有主体文件重算。\n"
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    repaired: list[str] = []
    for manifest_path in sorted(ROOT.glob("*/artifact_hashes.json")):
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not any(str(name).startswith("._") for name in old):
            continue
        evidence_root = manifest_path.parent
        metadata_path = evidence_root / "metadata.json"
        decision_path = evidence_root / "decision.json"
        report_path = evidence_root / "report.md"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
        metadata["hygiene_event"] = EVENT
        decision["hygiene_event"] = EVENT
        _write_json(metadata_path, metadata)
        _write_json(decision_path, decision)
        report = report_path.read_text(encoding="utf-8")
        if EVENT not in report:
            report_path.write_text(report.rstrip() + REPORT_NOTE, encoding="utf-8")
        clean_names = [
            str(name)
            for name in old
            if not str(name).startswith("._")
            and (evidence_root / str(name)).is_file()
        ]
        _write_json(
            manifest_path,
            {
                name: _sha(evidence_root / name)
                for name in sorted(clean_names)
            },
        )
        repaired.append(evidence_root.name)
    print(json.dumps({"repaired": repaired}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
