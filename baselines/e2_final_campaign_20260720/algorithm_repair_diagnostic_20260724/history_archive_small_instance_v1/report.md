# Small-instance history archive diagnostic

- Verdict: `CONFIRM_SMALL_ARCHIVE_LEGACY_GATE_BUG`
- Unit: `cn-cy-10c-01-V2-LOCATIONS`, seed `1`
- Purpose: distinguish a real missing-history failure from the legacy requirement that every stage must select at least one extra diversity candidate.
- Formal V5/V6 outputs were not read as resumable input and were not modified.

The raw CSV records all six view-stage archive ledgers. A stage is complete when it records all checkpoints, references historical population members, and selects every available candidate up to the frozen archive limit. Requiring a positive diversity remainder is not meaningful when the unique candidate count does not exceed the archive capacity.
