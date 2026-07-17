# China TVCI zero-search source gate

Decision: `PASS_CHINA_TVCI_2025_SOURCE_GATE_WITH_FUTURE_YEAR_NULLS_RECORDED`.

The frozen Figshare v3 S1 workbook contains 8 scenario years, 32 regional/national series, and 8760 hourly rows for 2025. It was converted without interpolation to 17520 half-hour rows; all daily energy-weighted integrals were checked. Shanghai representative days were selected from the carbon curve alone before any optimization result was observed (12 distinct days).

This gate only establishes source identity, shape, completeness, numerical validity, conversion conservation, and result-blind day selection. The source remains a simulation/projection dataset and cannot be described as official, observed, real-time, or marginal emissions.

Recorded non-primary-year warnings:
- 2055: invalid cell/time count 6; this unused projection year is not authorized
- 2060: invalid cell/time count 51; this unused projection year is not authorized

No source-gate failures were observed.
