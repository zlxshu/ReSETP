#!/usr/bin/env python3
"""把 4.4 节草稿装配进 paper_main.tex：占位符换成表/图环境，整段替换。

用法： python3 assemble_section_4_4.py [--dry-run]
草稿：同目录 section_4_4_v3_draft.tex（占位符 %%TABLE10%% %%FIGURE4%% %%FIGURE5%% %%TABLE13%% %%TABLE12%%）。
"""
from __future__ import annotations
import sys, shutil, datetime
from pathlib import Path

REPO = Path("/Volumes/移动硬盘（512G）/ReSETP")
TEX = REPO / "docs/paper_v2/paper_main.tex"
DRAFT = Path(__file__).with_name("section_4_4_v3_draft.tex")
START = "\\subsection{时变碳强度与充电时刻分析}"
END = "\\subsection{不同配送模式对比分析}"

BLOCKS = {
    "%%TABLE10%%": """\\begin{table}[H]
  \\centering
  \\caption{不同充电安排下的配送方案对比}
  \\label{tab:carbon-charging}
  \\small
  \\input{generated_tables/carbon_charging_table.tex}
\\end{table}""",
    "%%FIGURE4%%": """\\begin{figure}[H]
  \\centering
  \\includegraphics[width=\\textwidth]{generated_figures/figure_3_carbon_tariff_charging.pdf}
  \\caption{同一配送路线在两种充电安排下的充电时刻}
  \\label{fig:carbon-charging}
\\end{figure}""",
    "%%FIGURE5%%": """\\begin{figure}[H]
  \\centering
  \\includegraphics[width=\\textwidth]{generated_figures/figure_5_carbon_price_curve.pdf}
  \\caption{不同单位碳价下的派遣电动车占比与总成本}
  \\label{fig:carbon-price-sweep}
\\end{figure}""",
    "%%TABLE13%%": "\\input{generated_tables/policy_table.tex}",
    "%%TABLE12%%": """\\begin{table}[H]
  \\centering
  \\caption{不同电价时段方案与单位碳价下三种充电安排的对比}
  \\label{tab:grid2x2}
  \\small
  \\setlength{\\tabcolsep}{2.5pt}
  \\input{generated_tables/grid2x2_table.tex}
\\end{table}""",
}


def main() -> int:
    dry = "--dry-run" in sys.argv
    draft = DRAFT.read_text(encoding="utf-8")
    for key, block in BLOCKS.items():
        assert draft.count(key) == 1, f"占位符 {key} 出现 {draft.count(key)} 次"
        draft = draft.replace(key, block)
    leftover = [l for l in draft.splitlines() if "%%" in l]
    assert not leftover, f"仍有占位符未替换: {leftover}"
    tex = TEX.read_text(encoding="utf-8")
    i = tex.index(START)
    j = tex.index(END)
    assert i < j
    new_tex = tex[:i] + draft.rstrip("\n") + "\n\n" + tex[j:]
    if dry:
        print("dry-run ok; 新段落行数", draft.count("\n"))
        return 0
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    backup = Path(__file__).with_name(f"paper_main.tex.bak_assemble_{stamp}")
    shutil.copy(TEX, backup)
    TEX.write_text(new_tex, encoding="utf-8")
    print("assembled; backup", backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
