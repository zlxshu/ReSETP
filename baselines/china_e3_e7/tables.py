"""Generate paper TeX tables only after an explicit evidence release."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from .contract import ROOT, load_contract
except ImportError:  # pragma: no cover - direct script compatibility
    from contract import ROOT, load_contract


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _artifact_path(path: Path, repo_root: Path) -> str:
    """Return a stable path for both repository and temporary test outputs."""
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def _tex(value: Any) -> str:
    text = "---" if value is None or str(value).strip() == "" else str(value)
    return (
        text.replace("%", r"\%")
        .replace("&", r"\&")
        .replace("_", r"\_")
    )


def render_tables(
    aggregate_dir: Path,
    output_dir: Path,
    *,
    repo_root: Path = ROOT,
) -> dict[str, Any]:
    contract = load_contract(repo_root)
    decision_path = aggregate_dir / "decision.json"
    summary_path = aggregate_dir / "summary.csv"
    aggregate_decision = (
        json.loads(decision_path.read_text(encoding="utf-8"))
        if decision_path.is_file()
        else {}
    )
    rows = _read_csv(summary_path) if summary_path.is_file() else []
    evidence_release = bool(aggregate_decision.get("independent_recalc_complete"))
    usable = [row for row in rows if row.get("status") == "PASS_DATA_COMPLETE"]
    output_dir.mkdir(parents=True, exist_ok=True)
    statuses: list[dict[str, Any]] = []
    if not usable or not evidence_release:
        statuses = [
            {
                "family": family["id"],
                "status": "NO_TABLE_UNTIL_INDEPENDENT_RECALC_RELEASE",
                "reason": "需要正式统计行且 aggregate decision 明确 independent_recalc_complete=true",
            }
            for family in contract["families"]
        ]
    else:
        for family in contract["families"]:
            family_rows = [row for row in usable if row.get("family") == family["id"]]
            if not family_rows:
                statuses.append(
                    {
                        "family": family["id"],
                        "status": "NO_FORMAL_RESULTS_NO_TABLE",
                        "reason": (
                            "该 family 尚无完成且独立复算通过的统计行"
                        ),
                    }
                )
                continue
            path = output_dir / f"{family['id'].lower()}_summary.tex"
            lines = [
                r"\begin{table}[H]",
                r"\centering",
                f"\\caption{{{family['title_zh']}}}",
                f"\\label{{tab:{family['id'].lower()}-summary-generated}}",
                r"\setptabsetup",
                r"\begin{tabular*}{\linewidth}{@{\extracolsep{\fill}}lrrrrrr@{}}",
                r"\toprule",
                r"指标 & cell数 & 均值效应 & 中位数效应 & 均值变化(\%) & 随机化检验$p$ & Holm校正$p$ \\\\",
                r"\midrule",
            ]
            for row in family_rows:
                line = "{} & {} & {} & {} & {} & {} & {} ".format(
                    _tex(f"{row.get('contrast')} / {row.get('metric')}"),
                    _tex(row.get("n_cells")),
                    _tex(row.get("mean_delta")),
                    _tex(row.get("median_delta")),
                    _tex(row.get("mean_reduction_percent")),
                    _tex(row.get("randomization_p")),
                    _tex(row.get("holm_adjusted_p")),
                )
                lines.append(line + r"\\")
            lines.extend(
                [
                    r"\bottomrule",
                    r"\end{tabular*}",
                    r"\end{table}",
                ]
            )
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            statuses.append({"family": family["id"], "status": "TABLE_GENERATED", "file": str(path)})
    decision = {
        "schema": "resetp.china.e3-e7-table-decision.v1",
        "status": "NO_TABLES" if not usable or not evidence_release else "TABLE_REVIEW_REQUIRED",
        "aggregate_dir": str(aggregate_dir),
        "usable_summary_rows": len(usable),
        "independent_recalc_complete": evidence_release,
        "scientific_claim_allowed": False,
        "families": statuses,
    }
    _write_json(output_dir / "decision.json", decision)
    (output_dir / "report.md").write_text(
        "\n".join(
            [
                "# 中国 E3–E7 论文表格生成状态",
                "",
                f"状态：`{decision['status']}`。",
                "",
                "表格生成器不会把缺少独立复算证书的统计行写进论文。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    files = [output_dir / name for name in ("decision.json", "report.md")]
    files.extend(path for path in output_dir.glob("*.tex"))
    _write_json(
        output_dir / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "algorithm": "sha256",
            "files": {_artifact_path(path, repo_root): _sha256(path) for path in files},
        },
    )
    return decision
