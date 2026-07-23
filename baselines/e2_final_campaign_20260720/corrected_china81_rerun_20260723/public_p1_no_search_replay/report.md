# Public P1 no-search preservation replay

Decision: `PASS_PUBLIC_P1_PRESERVATION_NO_SEARCH`.

The sealed 280-row P1 ledger, win/tie/loss counts, improvement percentages, Table 5 rows and average row were reconstructed exactly without running search. P1 did not save route witnesses, so claiming a P1 route-certificate replay would be false. The 30 route witnesses that do exist in the separate P4 public sprint were reconstructed with PyVRP and all passed feasibility, depot, route-distance and total-cost checks. They are not relabelled as P1 witnesses.
