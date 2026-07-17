# China regional price and source gate — 2026-07-17

Decision: `PARTIAL_CHINA_REGION_PRICE_SOURCE_GATE`.

This is a zero-optimization source gate. It does not authorize C31 construction, solver configuration, or performance runs. All usable numeric electricity values below are dated historical snapshots, not permanent tariffs.

| Region | Decision | Electricity evidence | Diesel evidence | CEA / local-market interpretation | S1-2025 TVCI |
|---|---|---|---|---|---|
| Beijing / JJJ | PARTIAL | July-2024 State Grid Beijing 1-10 kV two-part proxy-purchase: sharp/peak/flat/valley `1.057777/0.926841/0.681335/0.435829 CNY/kWh`; policy times and industrial-commercial scope are saved. | 2026-07-03 NDRC 0# standard-product ceiling `7935 CNY/t`; no same-date official CNY/L conversion saved. | National CEA close `75.02 CNY/tCO2e` on 2025-06-30 can only be an internal shadow price. | PASS: `Beijing` exact column. |
| Guangdong / PRD | PARTIAL | Guangzhou/Foshan October-2021 1-10 kV table gives flat/valley/peak `0.6475/0.24605/1.10075 CNY/kWh`; sharp peak is the official formula `peak x 1.25`. It does not cover Shenzhen. | 2026-07-03 NDRC ceiling `7970 CNY/t`; no same-date official CNY/L conversion saved. | CEA is national; do not substitute Guangdong or Shenzhen local-market prices for it. | PASS: `Guangdong` exact column. |
| Chongqing / Sichuan–Chongqing | PARTIAL | July-2024 State Grid Chongqing 1-10 kV two-part proxy-purchase: sharp/peak/flat/valley `1.291963/1.093205/0.720533/0.335439 CNY/kWh`. No Sichuan electricity chain is saved. | Chongqing 2026-07-03 official `6.90 CNY/L` and `8110 CNY/t`; Chengdu `8135 CNY/t` only in the NDRC table. | CEA is not a Chongqing/Sichuan road-logistics compliance cost. | PASS: `Chongqing` exact column. |

## Time periods and applicability

- Beijing: peak `10:00-13:00, 17:00-22:00`; flat `07:00-10:00, 13:00-17:00, 22:00-23:00`; valley `23:00-07:00`; sharp peak in July/August `11:00-13:00, 16:00-17:00`. The saved table is State Grid proxy purchase, commercial-industrial two-part, 1-10 kV.
- Guangdong excluding Shenzhen: peak `10:00-12:00, 14:00-19:00`; valley `00:00-08:00`; remaining hours flat. Sharp peak is `11:00-12:00, 15:00-17:00` in July–September and qualifying hot days; price is 25% above peak. The saved Guangzhou/Foshan table says its general-commercial TOU eligibility is restricted to former ordinary-industrial special-transformer users and excludes government funds/surcharges.
- Shenzhen: the independently issued city rule covers the Shenzhen-grid supply area, excludes specified incremental/distributed areas, and retains flat price for ordinary commercial/other users. The official original URL was found but this machine's TLS client could not download it; this is deliberately a recorded gap, not a substituted Guangdong value.
- Chongqing: policy scope is 10 kV+ and 100 kVA+ large industry plus ordinary-industrial motive electricity. Peak `11:00-17:00, 20:00-22:00`; flat `08:00-11:00, 17:00-20:00, 22:00-24:00`; valley `00:00-08:00`; sharp `12:00-14:00` in July/August and December/January. The saved State Grid table is a broader proxy-purchase table, so a future depot contract must establish actual eligibility.

## Carbon market boundary

The national market is a central CEA market, not three regional price series. The MEE 2026 work notice identifies power, steel, cement, and aluminium smelting as the trading covered sectors; it does not list road logistics. The regulation says local carbon markets continue under transition arrangements and must not be merged with the national CEA price. Therefore the 2025-06-30 CEA close is a shared, dated internal shadow-price input only. The Shanghai exchange page also states reuse/republishing conditions; its quote must retain attribution.

## TVCI connection

The predecessor source gate already verified the Figshare S1 workbook and its 2025 derivative. This gate recomputed the trusted derivative hash and checked the exact `Beijing`, `Guangdong`, and `Chongqing` headers. Direct attachment is valid in the data-lineage sense, with the existing qualification unchanged: it is a provincial hourly simulation/projection, not official observed, real-time, or marginal carbon intensity.

## Why the decision is not PASS

The issue is not absence of official evidence. It is scope and geography: Shenzhen is outside Guangdong's provincial policy, the Chengdu–Chongqing corridor crosses two electricity-price jurisdictions, historic proxy-purchase numbers change by month, and two regional diesel snapshots remain in CNY/t rather than an official same-date CNY/L model input. Copying Shanghai values, converting units by assumption, or treating a single city as a silent corridor-wide tariff would conceal those failures.

## Evidence and use restrictions

`raw_runs.csv` records original URLs, retrieval date, saved filename, SHA-256, and an explicit status for the Shenzhen page that could not be saved due local TLS failure. Official public pages/tables did not expose a machine-readable reuse licence in this audit; they should be cited with attribution and reused only under the publisher's terms. The S1 source uses CC BY 4.0. All artefact hashes exclude AppleDouble files; acquisition-created `._*` files were removed before final hashing.
