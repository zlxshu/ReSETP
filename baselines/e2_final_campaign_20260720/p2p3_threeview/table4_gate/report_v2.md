# S4 Route detail independent recheck — v2

Decision: `PASS_S4_ROUTE_DETAIL`.
Representative `cn-prd-50c-01-V2-LOCATIONS`, best seed `4`.
The v1 HALT was an acceptance-script bug: global `check_solution` was applied to each one-route fragment, so customers served by the other eight routes were reported as 400 pseudo `CUSTOMER_COVERAGE` violations.
The v2 runner applies global `check_solution` and `exact_china81_score` only to the complete solution, checks every customer exactly once at that level, and uses arithmetic-only route-fragment recomputation plus full-solution closure.
Recorded S3 cost=2357.117862392110; direct cost=2357.117862392110; exact cost=2357.117862392110.
Full check violations=0; exact violations=0; unique-coverage pass=True; cost match=True.

Arithmetic closure (route sum versus complete-solution value):
- `距离(km)`: route=613.197927956015; full=613.197927956015; delta=1.14e-13; pass=True.
- `成本(元)`: route=2357.117862392110; full=2357.117862392110; delta=0; pass=True.
- `时间(h)`: route=100.729965122222; full=100.729965122222; delta=1.42e-14; pass=True.
- `油耗(L)`: route=42.144653814414; full=42.144653814414; delta=0; pass=True.
- `电耗(kWh)`: route=109.174538582661; full=109.174538582661; delta=0; pass=True.
- `碳排放(kg)`: route=116.405841992356; full=116.405841992356; delta=1.42e-14; pass=True.
- `num(满足时窗客户数)`: route=50.000000000000; full=50.000000000000; delta=0; pass=True.
- `装载率(%)`: route=100.000000000000; full=100.000000000000; delta=0; pass=True.
- `装载率(%)` uses the maximum route load rate for the total row, not a sum.

No solution, witness, protected evaluator, primary configuration, P3 raw data, or main TeX was changed; this revision only re-accepts the sealed witness.

Integrity flag: HASH_CONTAMINATED_APPLEDOUBLE; AppleDouble sidecars were removed before the final hash refresh. Raw data files were not overwritten.

Integrity flag: HASH_CONTAMINATED_APPLEDOUBLE; AppleDouble sidecars were removed before the final hash refresh. Raw data files were not overwritten.
