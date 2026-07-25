# G1 v5 pre-result abort

G1 v5 was stopped before any objective value or arm comparison was read.

The stop was caused by a contract mismatch found during code review. The
route-local checker correctly needed to ignore global messages saying that
customers assigned to other routes were not served by a one-route fragment.
Its predicate was too broad, however, because it ignored every
`CUSTOMER_COVERAGE` message, including a duplicate-customer message that
belongs to the fragment itself.

The complete evaluator would still have rejected a duplicate in a full
solution, so this is not evidence that an infeasible final result passed.
Nevertheless, the implementation did not match the frozen fail-closed wording.
The active run was therefore terminated. Four `result.json` paths had already
appeared; only their count was observed. Their contents and all objective
values remain unread, and they are forbidden from scientific use or reuse.

The next run must use a new version and new work/output directories after the
predicate is narrowed, tests pass, and the zero-search wiring and six-worker
resource gates are repeated against the new source hashes.
