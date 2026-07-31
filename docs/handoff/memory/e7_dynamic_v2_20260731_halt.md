# E7 dynamic v2 startup halt — 2026-07-30

## Authority and scope

Authoritative evidence directory:
`baselines/china_e3_e7/e7_dynamic_v2_20260731/`.

This attempt reused, without redesign, the prior registration at
`baselines/china_e3_e7/e7_dynamic_20260731/pre_registration.json`: four arms,
three scales, five frozen streams per scale, ten seeds, the seed-to-stream
mapping, the convergence-probe rule, scale order, estimands, and hard stops.

## Closed finding: original KeyError

The prior E7 adapter expected the legacy single-file source key
`instance_json` and exported it as `instance_path`. China81 instead exposes
eight joined sources: `catalog`, `facilities`, `finite_fleet_authority`,
`nodes`, `orders`, `road_matrices`, `tariff_carbon_calendar`, and
`vehicle_parameter_lock`.

The v2 adapter requires exactly those eight keys, resolves every source to an
existing project-local absolute path, and records each source hash. It does not
use `dict.get`, a fallback, or a fabricated instance JSON. The zero-search
regression check passed. Therefore the original KeyError is fixed.

## New hard stop

The monitored 50c seed-1 FULL_ROLLING minimum startup validation failed before
`probe.run_probe_arm`. Shared `_initial_plan` calls
`reschedule_between_trip_charging` without `prices=sources["prices"]`, so its
legacy linear `DEFAULT_PRICES` is checked against the China81
`E3_STRICT_MULTITRIP_V3_NL` certificate.

Zero-search inspection proved that the certificate and real China81 prices
agree: both use `NL90_mild`, parameter hash
`605f66b161bb16e9383ceec724d10ec09c6033eb9e600f11b64e5af9b8fd1e54`,
physical hash
`3350c2624f438a01779dcebc5ac058a851ea7ba6a4f0322dd0bf07951ddd4de6`,
and 77.28 kWh capacity. Supplying the real prices diagnostically made the
naive reschedule pass with eight routes and four charging actions. The aware
reschedule then failed because prehorizon charging requires the authoritative
carbon profile for `charge_day_offset=-1`, while current E7 sources provide
only offset 0.

No previous-day profile was invented or copied from the operating day. No
shared probe, protected evaluator, search semantic, arm, stream, seed, or
budget rule was changed.

## Terminal status

Status: `HALT_PROBE_STARTUP_CURVE_CALENDAR_CONTRACT`.

Search evaluations: 0. Formal budget: not selected. Completed formal
instances: none. Static degradation and dynamic recovery: unavailable. All
four arms are blocked by their shared initial-plan layer. Cross-depot
reassignment, member-profit shifts, and carbon-aware charging shifts are
unobserved, not negative findings.

A fresh attempt requires explicit user authorization to pass China81 prices
into both shared rescheduling calls and to construct the offset -1 profile from
the frozen authoritative calendar, followed by zero-search contract tests.
