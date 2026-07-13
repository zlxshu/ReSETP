# ReSETP

ReSETP is a research codebase for dynamic collaborative multi-depot vehicle routing with a mixed diesel-electric fleet, time-varying grid carbon intensity, strict physical-vehicle multi-trip scheduling, and profit-fairness constraints.

**Private repository:** <https://github.com/zlxshu/ReSETP>

The project supports a Chinese journal manuscript targeting *Systems Engineering — Theory & Practice*. It contains the instance-building pipeline, the TVCI-ALNS solver, comparison algorithms, experiment evidence, and the LaTeX manuscript. This is a research prototype rather than a packaged end-user application.

## What is in the repository

| Path | Purpose |
|---|---|
| `models/` | Reproducible construction of the UK-coordinate-based regional/intercity test networks and dynamic demand scenarios |
| `solver/src/setp_solver/` | Cost and carbon accounting, feasibility checks, strict multi-trip scheduling, TVCI-ALNS, baselines, and dynamic replanning |
| `baselines/` | Experiment runners and auditable result packages |
| `docs/paper_submission_final/` | Journal class, manuscript source, generated tables and vector figures, and compiled PDF |
| `CONTROL_CONSOLE.py` | Safe project-level entry point for listing, checking, and dispatching registered experiment or paper jobs |
| `AGENTS.md` | Repository-wide instructions for coding agents |
| `docs/handoff/READ_ME_FIRST_FOR_AGENTS.md` | Mandatory project-state and evidence protocol for agents working in this repository |

Large generated datasets and temporary run products are intentionally excluded from Git by `.gitignore`. The tracked repository is sufficient to inspect the implementation, tests, experiment contracts, sealed evidence committed under `baselines/`, and the paper. Re-running every formal experiment may additionally require the original local data bundle described by the relevant experiment metadata.

## Environment and minimum-cost verification

Python 3.10 or newer is required. The following setup is sufficient for the instance package, the control-console check, and the core non-RL solver tests:

```bash
git clone https://github.com/zlxshu/ReSETP.git
cd ReSETP

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e models numpy scipy pyyaml
```

Start with the low-cost checks below. They inspect the registered project entry points and run unit tests; they do **not** launch the formal experiment matrix.

```bash
python CONTROL_CONSOLE.py --list
python CONTROL_CONSOLE.py --self-check
PYTHONPATH=models/src python -m unittest discover -s models/tests
PYTHONPATH=solver/src:. python -m unittest discover -s solver/tests
```

The optional reinforcement-learning research lane has a separate frozen environment:

```bash
python -m pip install -r solver/rl/requirements.txt
```

Do not start a full experiment merely to test the installation. Each formal experiment has its own frozen inputs, run budget, stop conditions, raw results, decision file, hashes, and report under `baselines/`. Read the corresponding metadata and project handoff before a formal rerun.

## Control console

The default console configuration is a dry run. It is designed to show what would execute before any expensive computation begins.

```bash
# List registered experiments and paper artifacts
python CONTROL_CONSOLE.py --list

# Validate configuration, paths, and preflight conditions only
python CONTROL_CONSOLE.py --self-check

# Preview jobs selected in CONTROL_CONSOLE.yaml without running solvers
python CONTROL_CONSOLE.py --dry-run
```

`CONTROL_CONSOLE.yaml` selects the job; `PARAMETERS_CONSOLE.yaml` supplies paths and parameters. A live run must be an explicit, evidence-backed decision. Never replace a low-cost probe with a full matrix run.

## Manuscript

The principal manuscript files are:

- `docs/paper_submission_final/paper_main.tex`
- `docs/paper_submission_final/paper_main.pdf`
- `docs/paper_submission_final/setp-new.cls`

On a machine with XeLaTeX and the required Chinese/Latin fonts, compile from the manuscript directory:

```bash
cd docs/paper_submission_final
xelatex -interaction=nonstopmode -halt-on-error paper_main.tex
xelatex -interaction=nonstopmode -halt-on-error paper_main.tex
```

The second pass resolves cross-references. Generated figures are stored as vector PDF files so that journal typography remains sharp.

## How Codex and GPT-5.6 were used

Codex was used as an engineering and research-assistance layer around the human-authored model and scientific decisions. The active local workflow used Codex CLI `0.144.1` with the official model identifier `gpt-5.6-sol`. The model name and reasoning level are selectable; they are not hard-coded into the research algorithms.

Codex and GPT-5.6 assisted with:

- reading the actual source and tracing cost, feasibility, charging, scheduling, and persistence logic before proposing changes;
- implementing narrowly scoped code changes and regression checks;
- creating reproducible plotting and LaTeX-generation scripts from sealed result files;
- running low-cost probes before any long experiment and checking budgets, seeds, hashes, cost closure, and physical-vehicle certificates;
- reviewing experiment evidence, identifying invalid comparisons, and keeping unsupported claims out of the manuscript;
- maintaining the README, handoff records, and reproducibility instructions.

They were **not** used to invent experimental observations, silently select favorable runs, change frozen parameters after seeing outcomes, or replace the authors' responsibility for the model, research question, literature citations, statistical design, and final conclusions. Formal claims must be traceable to committed raw results and their evidence package.

Codex reads `AGENTS.md` files before working and applies more specific instructions found deeper in the repository. This project adds a mandatory second entry point: `docs/handoff/READ_ME_FIRST_FOR_AGENTS.md`. OpenAI documents the general instruction hierarchy in the [AGENTS.md guide](https://developers.openai.com/codex/guides/agents-md).

### Reproducing the interactive Codex workflow

Install and authenticate Codex CLI using the [official Codex CLI documentation](https://developers.openai.com/codex/cli/), then start it at the repository root:

```bash
codex login
codex -C /path/to/ReSETP -m gpt-5.6-sol
```

Use this opening instruction:

```text
Read AGENTS.md and docs/handoff/READ_ME_FIRST_FOR_AGENTS.md completely before action.
Confirm the current handoff and frozen evidence first. Use the smallest useful probe;
do not run a formal experiment or change a scientific contract without explicit authority.
```

Inside Codex, `/status` shows the active session, `/model` selects an available model, `/permissions` displays or changes the approval mode, and `/review` starts a repository review. These commands and the `gpt-5.6-sol` example are documented in OpenAI's [Codex CLI guide](https://developers.openai.com/codex/cli/). Model availability can depend on the user's account or workspace; if `gpt-5.6-sol` is unavailable, select an available Codex model with `/model` and record the substitution in the run report.

### Reproducing a bounded non-interactive task

For a repeatable, non-interactive check, use `codex exec` and keep the task narrow:

```bash
codex exec \
  -C /path/to/ReSETP \
  -m gpt-5.6-sol \
  -s workspace-write \
  "Read AGENTS.md and docs/handoff/READ_ME_FIRST_FOR_AGENTS.md. Run only the control-console self-check and the smallest relevant unit test. Report evidence; do not start formal experiments."
```

Use `--json` when a machine-readable event stream is needed, or `-o result.txt` to save the final response. Avoid `--dangerously-bypass-approvals-and-sandbox` unless Codex is already running inside a separately secured disposable environment.

## Evidence and agent discipline

Before any non-trivial change, read:

1. `AGENTS.md`
2. `docs/handoff/READ_ME_FIRST_FOR_AGENTS.md`
3. the startup documents listed there
4. the target experiment's `metadata.json`, `decision.json`, `report.md`, and source entry point

After material experiment work, preserve the required evidence set: `metadata.json`, `raw_runs.csv`, `decision.json`, `artifact_hashes.json`, and `report.md`. A failed or null result is still a result; it must not be hidden or rerun only because its direction is inconvenient.

## Access and confidentiality

This repository is private. Access is granted only to named collaborators and reviewers. Do not commit API keys, access tokens, private credentials, unpublished third-party datasets, or machine-specific secrets. GitHub collaborators may retain local clones after access is removed, so access should be limited to the people who need it and reviewed after the event.

