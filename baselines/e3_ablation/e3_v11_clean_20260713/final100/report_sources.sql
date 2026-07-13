-- Read-only report layer over the audited E3 exhibit tables.
CREATE OR REPLACE VIEW cooperation AS SELECT * FROM read_csv_auto('exhibits/cooperation_paired_200c.csv', header=true);
CREATE OR REPLACE VIEW carbon_timing AS SELECT * FROM read_csv_auto('exhibits/carbon_timing_paired_200c.csv', header=true);
CREATE OR REPLACE VIEW fairness AS SELECT * FROM read_csv_auto('exhibits/fairness_paired_200c.csv', header=true);
CREATE OR REPLACE VIEW friction AS SELECT * FROM read_csv_auto('exhibits/friction_axis_200c.csv', header=true);
SELECT * FROM cooperation ORDER BY seed;
SELECT * FROM carbon_timing ORDER BY seed;
SELECT * FROM fairness ORDER BY seed;
SELECT cross_site_fee_per_customer, avg(cross_site_customers) AS mean_cross_site_customers, avg(CASE WHEN strict_cooperation_win THEN 1.0 ELSE 0.0 END) AS strict_win_rate FROM friction GROUP BY 1 ORDER BY 1;
