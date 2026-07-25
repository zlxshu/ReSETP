"""Generate paper TeX tables only after an explicit evidence release."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from .contract import ROOT, load_contract
    from .e3_exhibits import (
        REGIONS,
        build_e3_cell_rows,
        build_e3_layer_rows,
    )
except ImportError:  # pragma: no cover - direct script compatibility
    from contract import ROOT, load_contract
    from e3_exhibits import (
        REGIONS,
        build_e3_cell_rows,
        build_e3_layer_rows,
    )


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


def _format_p(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return r"p=\mathrm{NA}"
    if number < 0.001:
        return r"p<0.001"
    return f"p={number:.3f}"


def _released_raw_path(
    aggregate_dir: Path,
    aggregate_decision: dict[str, Any],
    *,
    repo_root: Path,
) -> tuple[Path | None, str]:
    if (
        aggregate_decision.get("status")
        != "AGGREGATE_READY_FOR_REVIEW"
        or aggregate_decision.get(
            "independent_recalc_complete"
        )
        is not True
    ):
        return None, "aggregate decision has not released E3 evidence"
    raw_value = str(
        aggregate_decision.get("raw_path", "")
    ).strip()
    if not raw_value:
        return None, "aggregate decision has no raw path"
    raw_path = Path(raw_value)
    if not raw_path.is_absolute():
        raw_path = repo_root / raw_path
    certificate_path = (
        aggregate_dir / "independent_recalc_certificate.json"
    )
    if not raw_path.is_file() or not certificate_path.is_file():
        return None, "released raw file or independent certificate is absent"
    try:
        certificate = json.loads(
            certificate_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"cannot read independent certificate: {exc}"
    if (
        certificate.get("status") != "PASS_INDEPENDENT_RECALC"
        or certificate.get("task_count") != 810
        or certificate.get("pair_count") != 405
        or certificate.get("raw_runs_sha256")
        != _sha256(raw_path)
    ):
        return None, "independent certificate does not bind the 810-row raw file"
    return raw_path, "PASS"


def _render_e3_table(
    raw_rows: list[dict[str, str]],
    summary_rows: list[dict[str, str]],
    output_dir: Path,
) -> dict[str, Any]:
    cell_rows = build_e3_cell_rows(raw_rows)
    layer_rows = build_e3_layer_rows(cell_rows)
    display_rows = [
        row for row in layer_rows if row["region"] != "overall"
    ]
    overall = next(
        row for row in layer_rows if row["region"] == "overall"
    )
    total_cost_summary = next(
        (
            row
            for row in summary_rows
            if row.get("family") == "E3"
            and row.get("contrast_role") == "primary"
            and row.get("metric") == "total_cost"
            and row.get("status") == "PASS_DATA_COMPLETE"
        ),
        {},
    )
    path = output_dir / "e3_summary.tex"
    lines = [
        r"\begin{table}[H]",
        r"\centering",
        r"\caption{中国算例责任错配与跨场协同结果}",
        r"\label{tab:e3-summary}",
        r"\setptabsetup",
        r"\begin{tabular*}{\linewidth}{@{\extracolsep{\fill}}ccrrrrr@{}}",
        r"\toprule",
        (
            r"\multirow{2}{*}{城市群} & "
            r"\multirow{2}{*}{规模层} & "
            r"\multicolumn{2}{c}{总成本(元)} & "
            r"\multirow{2}{*}{成本降低(\%)} & "
            r"\multirow{2}{*}{跨场服务数} & "
            r"\multirow{2}{*}{服务完成率(\%)} \\"
        ),
        r"\cmidrule(lr){3-4}",
        r" & & 冻结责任 & 优化责任 & & & \\",
        r"\midrule",
    ]
    for region_index, region in enumerate(REGIONS):
        region_rows = [
            row for row in display_rows if row["region"] == region
        ]
        for row_index, row in enumerate(region_rows):
            region_cell = (
                rf"\multirow{{3}}{{*}}{{{_tex(row['region_label'])}}}"
                if row_index == 0
                else ""
            )
            lines.append(
                "{} & {} & {:.2f} & {:.2f} & {:.2f} & {:.2f} & {:.2f} \\\\".format(
                    region_cell,
                    _tex(row["scale_layer"]),
                    float(row["control_cost_mean"]),
                    float(row["treatment_cost_mean"]),
                    float(row["cost_reduction_percent"]),
                    float(
                        row[
                            "treatment_cross_site_service_mean"
                        ]
                    ),
                    float(
                        row[
                            "treatment_service_level_percent"
                        ]
                    ),
                )
            )
        if region_index < len(REGIONS) - 1:
            lines.append(r"\addlinespace[1pt]")
    lines.extend(
        [
            r"\midrule",
            (
                "总体 & 全部 & {:.2f} & {:.2f} & {:.2f} & "
                "{:.2f} & {:.2f} \\\\"
            ).format(
                float(overall["control_cost_mean"]),
                float(overall["treatment_cost_mean"]),
                float(overall["cost_reduction_percent"]),
                float(
                    overall[
                        "treatment_cross_site_service_mean"
                    ]
                ),
                float(
                    overall[
                        "treatment_service_level_percent"
                    ]
                ),
            ),
            r"\bottomrule",
            r"\end{tabular*}",
            (
                r"\tabnote{注：每个地区--规模单元由3张互斥地图和5个共同随机种子等权聚合；"
                r"成本降低=(冻结责任成本$-$优化责任成本)/冻结责任成本$\times100\%$，"
                r"正值表示优化责任与跨场协同成本更低。跨场服务数和服务完成率均为优化方案平均值；"
                rf"主要成本终点以27个配对单元检验，随机化检验${_format_p(total_cost_summary.get('randomization_p'))}$。"
                r"全部数值来自封存结果及独立复算证书。}"
            ),
            r"\end{table}",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cell_csv = output_dir / "e3_paired_cells.csv"
    layer_csv = output_dir / "e3_region_layer_rows.csv"
    with cell_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(cell_rows[0]),
        )
        writer.writeheader()
        writer.writerows(cell_rows)
    with layer_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(layer_rows[0]),
        )
        writer.writeheader()
        writer.writerows(layer_rows)
    return {
        "family": "E3",
        "status": "TABLE_GENERATED_FROM_27_PAIRED_CELLS",
        "file": str(path),
        "source_cells": len(cell_rows),
        "display_rows": len(display_rows) + 1,
        "data_files": [str(cell_csv), str(layer_csv)],
    }


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
    released_raw, release_reason = _released_raw_path(
        aggregate_dir,
        aggregate_decision,
        repo_root=repo_root,
    )
    evidence_release = released_raw is not None
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
            if family["id"] == "E3":
                try:
                    statuses.append(
                        _render_e3_table(
                            _read_csv(released_raw),
                            rows,
                            output_dir,
                        )
                    )
                except (OSError, RuntimeError, ValueError) as exc:
                    statuses.append(
                        {
                            "family": "E3",
                            "status": "HALT_E3_EXHIBIT_DATA",
                            "reason": str(exc),
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
    table_halts = [
        item
        for item in statuses
        if str(item.get("status", "")).startswith("HALT")
    ]
    generated_tables = [
        item
        for item in statuses
        if "TABLE_GENERATED" in str(item.get("status", ""))
    ]
    if not usable or not evidence_release:
        overall_status = "NO_TABLES"
    elif table_halts:
        overall_status = "HALT_TABLE_BUILD"
    elif generated_tables:
        overall_status = "TABLE_REVIEW_REQUIRED"
    else:
        overall_status = "NO_TABLES"
    decision = {
        "schema": "resetp.china.e3-e7-table-decision.v2",
        "status": overall_status,
        "aggregate_dir": str(aggregate_dir),
        "usable_summary_rows": len(usable),
        "independent_recalc_complete": evidence_release,
        "release_reason": release_reason,
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
    files.extend(path for path in output_dir.glob("*.csv"))
    _write_json(
        output_dir / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "algorithm": "sha256",
            "files": {_artifact_path(path, repo_root): _sha256(path) for path in files},
        },
    )
    return decision
