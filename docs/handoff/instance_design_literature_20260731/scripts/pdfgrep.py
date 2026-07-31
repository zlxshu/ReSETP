"""Read-only per-page grep over a PDF, so quotes can be cited with a page number."""
import re, subprocess, sys

path, pattern = sys.argv[1], sys.argv[2]
ctx = int(sys.argv[3]) if len(sys.argv) > 3 else 2
n = int(subprocess.run(["pdfinfo", path], capture_output=True, text=True).stdout
        .split("Pages:")[1].split()[0])
rx = re.compile(pattern, re.I)
for p in range(1, n + 1):
    txt = subprocess.run(["pdftotext", "-f", str(p), "-l", str(p), path, "-"],
                         capture_output=True, text=True).stdout
    lines = txt.splitlines()
    for i, line in enumerate(lines):
        if rx.search(line):
            print(f"--- PDFpage {p} line {i}")
            print("\n".join(lines[max(0, i - ctx):i + ctx + 1]))
