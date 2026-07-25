# HASH_CONTAMINATED_APPLEDOUBLE

This snapshot is preserved but superseded. Its `metadata.json` accidentally
included AppleDouble `._*.py` sidecars in `input_hashes`. The eleven static
check outcomes are unchanged, but this directory is not the canonical
reproducibility package. Use `g0_static_semantics_gate_v4/`, generated after
cleaning sidecars and excluding them from the input manifest.
