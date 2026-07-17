# Carbon/nonlinear-charging isolated prototype

This directory is an EA-001 exploration artifact. It is not imported by the
formal ReSETP solver.

The Python-only acceptance tests are reproducible with:

```text
python3 -m pytest -q tests
```

The sealed cspy comparison used a disposable environment and the following
dependency command:

```text
python3 -m venv <temporary-directory>
<temporary-directory>/bin/python -m pip install cspy==0.1.2
<temporary-directory>/bin/python cspy_compare.py
```

`cspy` is MIT licensed. The disposable environment is intentionally absent
from this repository. See `metadata.json` and `cspy_probe.json` for the exact
observed versions and comparison boundary.

