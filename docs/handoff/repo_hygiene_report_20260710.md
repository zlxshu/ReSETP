# Repository Hygiene Report — 2026-07-10

## Scope and decision

This pass repairs ExFAT/macOS metadata pollution without deleting experiment evidence, rewriting Git history, or removing Claude worktrees.  Large E2 experiment directories and already tracked checkpoints remain in place.

## AppleDouble quarantine

- Volume: external USB ExFAT, `/Volumes/移动硬盘（512G）`.
- Sidecar files found: `28,506`; no `._*` path was tracked by Git.
- Quarantine: `/Users/zhouleixishu/ReSETP_appledouble_quarantine_20260710`.
- Quarantined files: `28,506`; size reported by `du`: `111M`.
- Source-list SHA-256: `736fbfc897003ff7872f6a7fada208306a6ba6d6a1f6701acf3df772891a7d70`.
- Post-removal count under the repository: `0`.
- Ignored machine inventory: `.superpowers/sdd/repo_hygiene_20260710/appledouble_inventory.jsonl`.
- Ignored inventory summary and hash: `.superpowers/sdd/repo_hygiene_20260710/summary.json`.

The first tar attempt was rejected because macOS `tar` treated the sidecars as metadata and produced an empty archive.  No source file was removed until an explicit path-preserving `rsync` quarantine matched the source file count.

The ignored JSONL inventory contains one row per quarantined sidecar with its original relative path, quarantine-relative path, byte size, batch, and SHA-256.  Its ignored `summary.json` records the final inventory hash plus per-batch counts and byte totals, including sidecars recreated during staging and commit verification.  The tracked report intentionally carries only the stable audit summary; the large machine inventory remains outside Git history.

An ordinary `git gc --prune=2.weeks.ago` was attempted only after the first strict integrity check passed.  ExFAT immediately recreated AppleDouble files beside temporary and existing pack files and Git reported `non-monotonic index` while scanning those sidecars.  The GC was interrupted before completion; no real `.tmp-*` pack remained.  The 39 regenerated sidecars were copied separately to `ReSETP_appledouble_quarantine_20260710/gc_abort_regenerated` (156K), then deleted.  Their sorted path-list SHA-256 is `cecbf3b1d22f8af9fbbd1dece90ee53f867ddd66688fd40b4c1ec16f981c15b9` and the aggregate sorted content-hash SHA-256 is `b8c7601d069588d26793ade8d8868d5c625fdfd508fb4f3b306d998d0d34f523`.

Repository policy is therefore: do not run in-place GC on this ExFAT worktree.  Any future compaction must be performed from a verified APFS clone, or only after a separately proven metadata-suppression workflow.  `--aggressive`, history rewriting, and pruning outside the approved two-week horizon remain prohibited.

## Git integrity and remote checks

- Pre-GC `git fsck --full --strict`: exit `0`; no integrity error.
- Post-abort `git fsck --full --strict`: exit `0`; only dangling objects were reported.
- Post-abort `git fsck --full --strict --no-dangling`: exit `0`; no output.
- No real temporary pack file remained after the interrupted GC.
- Remote branch baseline before this cleanup: `d9b8e32f`.

## Protected evaluator hashes before cleanup

```text
ab9bfb9f8e95a92d599d07bd21de7780a52884fe72d227b58d4e9fe5e55d8a37  solver/src/setp_solver/cost.py
1e36735429360d22987353519a4dee3a43b58ed9b32e8693fdfbf201dd8a4f81  solver/src/setp_solver/check.py
1fae4f76ac6ff0a2caa36e78b3b68740b1fa65738474d9ecf1f4875983e1545d  solver/src/setp_solver/search/evaluation.py
```

These hashes are the final closeout comparison anchors.

## Worktree preservation

- Main worktree: clean at `d9b8e32f` on `codex/reporting-pipeline`.
- Dirty and preserved: `charming-sammet-4d06fe` (4 paths), `compassionate-lamport-ebd93b` (1 path).
- Clean worktrees are also preserved; three of them point at branch state not contained in the main branch.
- No worktree or branch is removed by this cleanup.

| Worktree | Branch | Initial HEAD | Initial state |
|---|---|---:|---|
| repository root | `codex/reporting-pipeline` | `d9b8e32f` | clean |
| `charming-sammet-4d06fe` | `claude/charming-sammet-4d06fe` | `73cd0fe8` | dirty: 2 modified, 2 untracked |
| `compassionate-lamport-ebd93b` | `claude/compassionate-lamport-ebd93b` | `754a4102` | dirty: 1 modified |
| `ecstatic-pasteur-7f18fd` | `claude/ecstatic-pasteur-7f18fd` | `57449c55` | clean |
| `frosty-saha-b0a9c4` | `claude/frosty-saha-b0a9c4` | `65e69124` | clean |
| `reverent-tu-36f162` | `claude/reverent-tu-36f162` | `520e8a27` | clean |
| `trusting-thompson-2497b4` | `claude/trusting-thompson-2497b4` | `793ab399` | clean |
| `vigorous-jennings-fe690a` | `claude/vigorous-jennings-fe690a` | `57449c55` | clean |
| `vigorous-lederberg-14c188` | `claude/vigorous-lederberg-14c188` | `57449c55` | clean |

## Tracking policy

`models/data_bundle` remains ignored for local generated/raw data, while new source, scripts, and tests under `models/src`, `models/scripts`, and `models/tests` are now visible to Git.  Future `.tmp`, Python caches, and checkpoint directories are ignored; existing tracked historical evidence is not untracked.
