# TARC G0 final closure

The frozen six-task G0 was launched once with six workers and no protected or
registered hash drift.

The 50-customer `ORDER_ONLY` and `ORDER_PLUS_TYPE` workers completed, but their
candidate rows were intentionally not released by the parent process after the
registered terminal condition fired. They must not be reconstructed by rerun or
used as performance evidence.

Both arms failed before objective comparison on the 100-customer case:
`D_beijing|cv` had no typed split under the registered fleet cap. Both arms also
failed on the 200-customer case (`D_foshan|cv` for `ORDER_ONLY`,
`D_guangzhou|cv` for `ORDER_PLUS_TYPE`).

This is a scientific representation failure rather than a launcher failure.
After customer-order crossover, forcing customers to stay within low-cardinality
depot/powertrain groups destroys the route-boundary and time-window combinations
needed by the medium and large cases. Because the same failure occurs when all
resource labels are frozen to the stronger parent, the experiment never reaches
a fair performance comparison.

Final decision:
`FINAL_STOP_TARC_TYPED_CHROMOSOME_LOSES_MEDIUM_LARGE_FEASIBILITY`.

No repair, parameter change, longer run, replacement instance, public benchmark,
China81 full run, paper claim, or E3 work is authorized.

