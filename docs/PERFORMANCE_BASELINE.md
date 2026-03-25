# LifeData V4 — Performance Baselines

Benchmarks run on synthetic data. Compare future runs against these
numbers to detect performance regressions.

## Baseline — 2026-03-25 01:21

**Hardware:** 12th Gen Intel(R) Core(TM) i7-12700H | RAM: 33G | Disk: nvme0n1 (SSD/NVMe, 1.8T) Samsung SSD 970 EVO Plus 2TB; nvme1n1 (SSD/NVMe, 953.9G) WD PC SN560 SDDPNQE-1T00-1002


| Test | Dataset | Duration (s) | Throughput |
|------|---------|-------------|------------|
| test_parse_large_csv | 100,000 rows | 0.767 | 130,347 rows/sec |
| test_insert_10k_events | 10,000 events | 0.237 | 42,151 events/sec |
| test_daily_summary_query_at_scale | 500,000 events / 180 days | 0.062 | 5 groups in 0.062s |
| test_correlation_query_at_scale | 500,000 events / 30 days | 0.024 | 47 aligned days in 0.024s |
| test_fts_search_at_scale | 50,000 events | 0.000 | 100 matches in 0.0002s |
