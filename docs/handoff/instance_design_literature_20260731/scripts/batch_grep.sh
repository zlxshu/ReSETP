#!/bin/zsh
# Read-only: per-page grep across several PDFs.
PAT="$1"; shift
for f in "$@"; do
  n=$(pdfinfo "$f" 2>/dev/null | awk '/^Pages:/{print $2}')
  [[ -z "$n" ]] && continue
  echo "########## $(basename "$f")"
  for p in $(seq 1 $n); do
    pdftotext -f $p -l $p "$f" - 2>/dev/null | grep -n -i -B1 -A3 -E "$PAT" | sed "s/^/[p$p] /"
  done
done
