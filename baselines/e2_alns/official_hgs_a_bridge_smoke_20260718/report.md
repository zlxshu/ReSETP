# Official HGS C++/Python bridge smoke test

- Decision: **HGS_CPP_PYTHON_BRIDGE_READY**
- Instance: `X-n110-k13` (non-frozen development instance)
- Budget: 1 seed × 1 second
- Independently reconstructed cost: `14971.0`
- Routes: `13`
- Validation failures: `[]`

Python invokes the unchanged pinned C++ executable through a strict CLI bridge. No C++-to-Python translation and no Python environment replacement is required.

This bridge currently accepts rounded-Euclidean CVRP only. It deliberately rejects VRPTW and does not represent ReSETP SOC, charging, heterogeneous fleet, multi-depot, carbon, electricity-price, or fairness semantics.
