# Broker timezone validation

## Decision

- Selected model: **Europe/Helsinki**
- Confidence grade: **STRONGLY SUPPORTED**
- Event-time attribution safe for Stage 1: **yes**
- Stage 1 run: **no**
- Normalized datasets regenerated: **no**

The existing Europe/Helsinki interpretation is the only tested model that follows the observed release reaction across winter standard time, summer daylight time, and the U.S.–Europe DST-transition mismatch. A fixed UTC+2 clock fails the summer evidence; fixed UTC+3 fails the winter and mismatch evidence. The grade is deliberately capped at STRONGLY SUPPORTED because no broker/feed document directly states the server clock.

## Scope and non-mutation control

This is a clock-identification qualification, not an event study or strategy test. Measurements use the existing tick-derived one-minute bid/ask file at one-minute resolution. The canonical tick file and the one-minute file are opened read-only and are not regenerated.

- Minute bars: `research/event_study_0830_0930/external_data/normalized/XAUUSD_202507171300_202607171409.1m_bidask.csv`
- Size before validation: 56,204,048 bytes
- Modification time before validation: `2026-07-17T14:02:05.197798+00:00`

## Official-time verification

The register contains 27 independently dated releases: 20 at 08:30 ET and 7 at 10:00 ET. BLS calendar pages explicitly state that their times are Eastern Time. BEA separately confirms the March 13 releases at 08:30. The Conference Board states that Consumer Confidence is published at 10:00 ET on the last Tuesday of each month; October 28, 2025 was that month's last Tuesday.

- [BLS July 2025 calendar](https://www.bls.gov/schedule/2025/07_sched_list.htm)
- [BLS August 2025 calendar](https://www.bls.gov/schedule/2025/08_sched_list.htm)
- [BLS September 2025 calendar](https://www.bls.gov/schedule/2025/09_sched_list.htm)
- [BLS December 2025 calendar](https://www.bls.gov/schedule/2025/12_sched_list.htm)
- [BLS 2026 release calendar](https://www.bls.gov/schedule/2026/home.htm)
- [BLS March 2026 calendar](https://www.bls.gov/schedule/2026/03_sched_list.htm)
- [BEA March 13 schedule update](https://www.bea.gov/news/blog/2026-01-15/economic-release-schedule-updates-gdp-personal-income-and-outlays)
- [Conference Board release convention](https://www.conference-board.org/topics/consumer-confidence/index.cfm)

## Model mappings

| Regime | Official ET | Europe/Helsinki | fixed UTC+3 | fixed UTC+2 |
|---|---:|---:|---:|---:|
| Winter, both standard | 08:30 | 15:30 | 16:30 | 15:30 |
| Winter, both standard | 10:00 | 17:00 | 18:00 | 17:00 |
| Summer, both DST | 08:30 | 15:30 | 15:30 | 14:30 |
| Summer, both DST | 10:00 | 17:00 | 17:00 | 16:00 |
| U.S. DST / Europe standard | 08:30 | 14:30 | 15:30 | 14:30 |
| U.S. DST / Europe standard | 10:00 | 16:00 | 17:00 | 16:00 |

## Measurement rule

For each model candidate, the baseline is the 25 available one-minute buckets from T−30 through T−6. Expansion is the peak value in T through T+2 divided by the positive baseline median. Mid-price high-low is the range measure; maximum quoted spread is the spread measure; tick_count is the tick-rate measure. A minute is material when at least two of: tick rate ≥ 1.50×, range ≥ 3.00×, or spread ≥ 1.50×. Among the distinct candidate windows, the strongest material composite identifies the observed reaction. Alignment error is observed source-wall minute minus the model's predicted source-wall minute.

The selection rule is diagnostic and uses post-release observations; it is not a tradable signal.

## Aggregate model comparison

| Model | Reactions | ≤2 min aligned | Alignment rate | Mean abs error | Median abs error | P90 abs error | Median composite |
|---|---:|---:|---:|---:|---:|---:|---:|
| Europe/Helsinki | 18 | 16 | 88.89% | 6.83 | 0.00 | 19.00 | 2.53 |
| fixed UTC+3 | 18 | 7 | 38.89% | 36.72 | 60.00 | 60.00 | 1.60 |
| fixed UTC+2 | 18 | 11 | 61.11% | 23.50 | 0.00 | 60.30 | 2.25 |

## Event register

| ID | Official ET | Institution | Regime | Release | Source |
|---|---|---|---|---|---|
| 2025-07-17-import-export | 2025-07-17 08:30 ET | BLS | summer_both_dst | U.S. Import and Export Price Indexes for June 2025 | [official](https://www.bls.gov/schedule/2025/07_sched_list.htm) |
| 2025-07-29-jolts | 2025-07-29 10:00 ET | BLS | summer_both_dst | JOLTS for June 2025 | [official](https://www.bls.gov/schedule/2025/07_sched_list.htm) |
| 2025-07-31-eci | 2025-07-31 08:30 ET | BLS | summer_both_dst | Employment Cost Index for Q2 2025 | [official](https://www.bls.gov/schedule/2025/07_sched_list.htm) |
| 2025-08-01-employment | 2025-08-01 08:30 ET | BLS | summer_both_dst | Employment Situation for July 2025 | [official](https://www.bls.gov/schedule/2025/08_sched_list.htm) |
| 2025-08-12-cpi | 2025-08-12 08:30 ET | BLS | summer_both_dst | Consumer Price Index for July 2025 | [official](https://www.bls.gov/schedule/2025/08_sched_list.htm) |
| 2025-09-03-jolts | 2025-09-03 10:00 ET | BLS | summer_both_dst | JOLTS for July 2025 | [official](https://www.bls.gov/schedule/2025/09_sched_list.htm) |
| 2025-09-05-employment | 2025-09-05 08:30 ET | BLS | summer_both_dst | Employment Situation for August 2025 | [official](https://www.bls.gov/schedule/2025/09_sched_list.htm) |
| 2025-10-28-consumer-confidence | 2025-10-28 10:00 ET | The Conference Board | fall_dst_mismatch | Consumer Confidence Index | [official](https://www.conference-board.org/topics/consumer-confidence/index.cfm) |
| 2025-12-09-jolts | 2025-12-09 10:00 ET | BLS | winter_standard_time | JOLTS for October 2025 | [official](https://www.bls.gov/schedule/2025/12_sched_list.htm) |
| 2025-12-10-eci | 2025-12-10 08:30 ET | BLS | winter_standard_time | Employment Cost Index for Q3 2025 | [official](https://www.bls.gov/schedule/2025/12_sched_list.htm) |
| 2025-12-16-employment | 2025-12-16 08:30 ET | BLS | winter_standard_time | Employment Situation for November 2025 | [official](https://www.bls.gov/schedule/2025/12_sched_list.htm) |
| 2025-12-18-cpi | 2025-12-18 08:30 ET | BLS | winter_standard_time | Consumer Price Index for November 2025 | [official](https://www.bls.gov/schedule/2025/12_sched_list.htm) |
| 2026-01-07-jolts | 2026-01-07 10:00 ET | BLS | winter_standard_time | JOLTS for November 2025 | [official](https://www.bls.gov/schedule/2026/home.htm) |
| 2026-01-09-employment | 2026-01-09 08:30 ET | BLS | winter_standard_time | Employment Situation for December 2025 | [official](https://www.bls.gov/schedule/2026/home.htm) |
| 2026-01-13-cpi | 2026-01-13 08:30 ET | BLS | winter_standard_time | Consumer Price Index for December 2025 | [official](https://www.bls.gov/schedule/2026/home.htm) |
| 2026-01-30-ppi | 2026-01-30 08:30 ET | BLS | winter_standard_time | Producer Price Index for December 2025 | [official](https://www.bls.gov/schedule/2026/home.htm) |
| 2026-02-05-jolts | 2026-02-05 10:00 ET | BLS | winter_standard_time | JOLTS for December 2025 | [official](https://www.bls.gov/schedule/2026/home.htm) |
| 2026-02-10-eci-import-export | 2026-02-10 08:30 ET | BLS | winter_standard_time | ECI Q4 2025 and Import/Export Prices for December 2025 | [official](https://www.bls.gov/schedule/2026/home.htm) |
| 2026-02-11-employment | 2026-02-11 08:30 ET | BLS | winter_standard_time | Employment Situation for January 2026 | [official](https://www.bls.gov/schedule/2026/home.htm) |
| 2026-02-13-cpi | 2026-02-13 08:30 ET | BLS | winter_standard_time | Consumer Price Index for January 2026 | [official](https://www.bls.gov/schedule/2026/home.htm) |
| 2026-02-27-ppi | 2026-02-27 08:30 ET | BLS | winter_standard_time | Producer Price Index for January 2026 | [official](https://www.bls.gov/schedule/2026/home.htm) |
| 2026-03-11-cpi | 2026-03-11 08:30 ET | BLS | spring_dst_mismatch | Consumer Price Index for February 2026 | [official](https://www.bls.gov/schedule/2026/03_sched_list.htm) |
| 2026-03-13-gdp-pce | 2026-03-13 08:30 ET | BEA | spring_dst_mismatch | GDP second estimate Q4 2025 and Personal Income/Outlays January 2026 | [official](https://www.bea.gov/news/blog/2026-01-15/economic-release-schedule-updates-gdp-personal-income-and-outlays) |
| 2026-03-13-jolts | 2026-03-13 10:00 ET | BLS | spring_dst_mismatch | JOLTS for January 2026 | [official](https://www.bls.gov/schedule/2026/03_sched_list.htm) |
| 2026-03-18-ppi | 2026-03-18 08:30 ET | BLS | spring_dst_mismatch | Producer Price Index for February 2026 | [official](https://www.bls.gov/schedule/2026/03_sched_list.htm) |
| 2026-03-24-productivity | 2026-03-24 08:30 ET | BLS | spring_dst_mismatch | Productivity and Costs revised Q4 2025 | [official](https://www.bls.gov/schedule/2026/03_sched_list.htm) |
| 2026-03-25-import-export | 2026-03-25 08:30 ET | BLS | spring_dst_mismatch | U.S. Import and Export Price Indexes for February 2026 | [official](https://www.bls.gov/schedule/2026/03_sched_list.htm) |

## Event-alignment evidence

Expansion columns are peak reaction-window multiples relative to the model-specific baseline.

| Event | Model | Predicted source time | Tick × | Range × | Spread × | Model-local first material | Selected observed reaction | Error min |
|---|---|---|---:|---:|---:|---|---|---:|
| 2025-07-17-import-export | Europe/Helsinki | 2025-07-17T15:30 | 1.57 | 10.10 | 1.11 | 2025-07-17T15:30 | 2025-07-17T15:30 | 0 |
| 2025-07-17-import-export | fixed UTC+3 | 2025-07-17T15:30 | 1.57 | 10.10 | 1.11 | 2025-07-17T15:30 | 2025-07-17T15:30 | 0 |
| 2025-07-17-import-export | fixed UTC+2 | 2025-07-17T14:30 | 0.98 | 0.71 | 1.00 | — | 2025-07-17T15:30 | 60 |
| 2025-07-29-jolts | Europe/Helsinki | 2025-07-29T17:00 | 1.00 | 1.12 | 1.25 | — | — | — |
| 2025-07-29-jolts | fixed UTC+3 | 2025-07-29T17:00 | 1.00 | 1.12 | 1.25 | — | — | — |
| 2025-07-29-jolts | fixed UTC+2 | 2025-07-29T16:00 | 1.24 | 1.44 | 1.06 | — | — | — |
| 2025-07-31-eci | Europe/Helsinki | 2025-07-31T15:30 | 1.41 | 3.24 | 3.31 | 2025-07-31T15:30 | 2025-07-31T15:30 | 0 |
| 2025-07-31-eci | fixed UTC+3 | 2025-07-31T15:30 | 1.41 | 3.24 | 3.31 | 2025-07-31T15:30 | 2025-07-31T15:30 | 0 |
| 2025-07-31-eci | fixed UTC+2 | 2025-07-31T14:30 | 1.26 | 2.68 | 1.19 | — | 2025-07-31T15:30 | 60 |
| 2025-08-01-employment | Europe/Helsinki | 2025-08-01T15:30 | 1.80 | 10.22 | 4.25 | 2025-08-01T15:30 | 2025-08-01T15:30 | 0 |
| 2025-08-01-employment | fixed UTC+3 | 2025-08-01T15:30 | 1.80 | 10.22 | 4.25 | 2025-08-01T15:30 | 2025-08-01T15:30 | 0 |
| 2025-08-01-employment | fixed UTC+2 | 2025-08-01T14:30 | 0.96 | 1.33 | 1.06 | — | 2025-08-01T15:30 | 60 |
| 2025-08-12-cpi | Europe/Helsinki | 2025-08-12T15:30 | 2.02 | 14.87 | 7.24 | 2025-08-12T15:30 | 2025-08-12T15:30 | 0 |
| 2025-08-12-cpi | fixed UTC+3 | 2025-08-12T15:30 | 2.02 | 14.87 | 7.24 | 2025-08-12T15:30 | 2025-08-12T15:30 | 0 |
| 2025-08-12-cpi | fixed UTC+2 | 2025-08-12T14:30 | 0.82 | 1.30 | 1.06 | — | 2025-08-12T15:30 | 60 |
| 2025-09-03-jolts | Europe/Helsinki | 2025-09-03T17:00 | 1.10 | 2.28 | 1.42 | — | — | — |
| 2025-09-03-jolts | fixed UTC+3 | 2025-09-03T17:00 | 1.10 | 2.28 | 1.42 | — | — | — |
| 2025-09-03-jolts | fixed UTC+2 | 2025-09-03T16:00 | 1.24 | 2.60 | 1.11 | — | — | — |
| 2025-09-05-employment | Europe/Helsinki | 2025-09-05T15:30 | 1.64 | 15.17 | 9.42 | 2025-09-05T15:30 | 2025-09-05T15:30 | 0 |
| 2025-09-05-employment | fixed UTC+3 | 2025-09-05T15:30 | 1.64 | 15.17 | 9.42 | 2025-09-05T15:30 | 2025-09-05T15:30 | 0 |
| 2025-09-05-employment | fixed UTC+2 | 2025-09-05T14:30 | 1.03 | 0.93 | 0.94 | — | 2025-09-05T15:30 | 60 |
| 2025-10-28-consumer-confidence | Europe/Helsinki | 2025-10-28T16:00 | 1.03 | 0.80 | 2.03 | — | — | — |
| 2025-10-28-consumer-confidence | fixed UTC+3 | 2025-10-28T17:00 | 1.02 | 1.54 | 1.21 | — | — | — |
| 2025-10-28-consumer-confidence | fixed UTC+2 | 2025-10-28T16:00 | 1.03 | 0.80 | 2.03 | — | — | — |
| 2025-12-09-jolts | Europe/Helsinki | 2025-12-09T17:00 | 1.06 | 2.28 | 4.72 | — | — | — |
| 2025-12-09-jolts | fixed UTC+3 | 2025-12-09T18:00 | 1.07 | 2.15 | 1.00 | — | — | — |
| 2025-12-09-jolts | fixed UTC+2 | 2025-12-09T17:00 | 1.06 | 2.28 | 4.72 | — | — | — |
| 2025-12-10-eci | Europe/Helsinki | 2025-12-10T15:30 | 0.82 | 1.12 | 1.50 | — | 2025-12-10T16:31 | 61 |
| 2025-12-10-eci | fixed UTC+3 | 2025-12-10T16:30 | 1.67 | 3.33 | 1.30 | 2025-12-10T16:31 | 2025-12-10T16:31 | 1 |
| 2025-12-10-eci | fixed UTC+2 | 2025-12-10T15:30 | 0.82 | 1.12 | 1.50 | — | 2025-12-10T16:31 | 61 |
| 2025-12-16-employment | Europe/Helsinki | 2025-12-16T15:30 | 1.61 | 3.76 | 8.11 | 2025-12-16T15:30 | 2025-12-16T15:30 | 0 |
| 2025-12-16-employment | fixed UTC+3 | 2025-12-16T16:30 | 1.54 | 1.74 | 1.05 | — | 2025-12-16T15:30 | -60 |
| 2025-12-16-employment | fixed UTC+2 | 2025-12-16T15:30 | 1.61 | 3.76 | 8.11 | 2025-12-16T15:30 | 2025-12-16T15:30 | 0 |
| 2025-12-18-cpi | Europe/Helsinki | 2025-12-18T15:30 | 1.83 | 6.82 | 8.11 | 2025-12-18T15:30 | 2025-12-18T15:30 | 0 |
| 2025-12-18-cpi | fixed UTC+3 | 2025-12-18T16:30 | 1.54 | 2.51 | 1.05 | — | 2025-12-18T15:30 | -60 |
| 2025-12-18-cpi | fixed UTC+2 | 2025-12-18T15:30 | 1.83 | 6.82 | 8.11 | 2025-12-18T15:30 | 2025-12-18T15:30 | 0 |
| 2026-01-07-jolts | Europe/Helsinki | 2026-01-07T17:00 | 0.83 | 1.58 | 6.10 | — | — | — |
| 2026-01-07-jolts | fixed UTC+3 | 2026-01-07T18:00 | 1.05 | 1.03 | 1.00 | — | — | — |
| 2026-01-07-jolts | fixed UTC+2 | 2026-01-07T17:00 | 0.83 | 1.58 | 6.10 | — | — | — |
| 2026-01-09-employment | Europe/Helsinki | 2026-01-09T15:30 | 1.29 | 6.44 | 8.11 | 2026-01-09T15:30 | 2026-01-09T15:30 | 0 |
| 2026-01-09-employment | fixed UTC+3 | 2026-01-09T16:30 | 1.37 | 2.01 | 1.05 | — | 2026-01-09T15:30 | -60 |
| 2026-01-09-employment | fixed UTC+2 | 2026-01-09T15:30 | 1.29 | 6.44 | 8.11 | 2026-01-09T15:30 | 2026-01-09T15:30 | 0 |
| 2026-01-13-cpi | Europe/Helsinki | 2026-01-13T15:30 | 1.22 | 5.28 | 7.70 | 2026-01-13T15:30 | 2026-01-13T15:30 | 0 |
| 2026-01-13-cpi | fixed UTC+3 | 2026-01-13T16:30 | 1.70 | 2.70 | 2.45 | — | 2026-01-13T15:30 | -60 |
| 2026-01-13-cpi | fixed UTC+2 | 2026-01-13T15:30 | 1.22 | 5.28 | 7.70 | 2026-01-13T15:30 | 2026-01-13T15:30 | 0 |
| 2026-01-30-ppi | Europe/Helsinki | 2026-01-30T15:30 | 1.22 | 1.68 | 7.70 | — | 2026-01-30T16:31 | 61 |
| 2026-01-30-ppi | fixed UTC+3 | 2026-01-30T16:30 | 1.81 | 2.45 | 8.19 | 2026-01-30T16:31 | 2026-01-30T16:31 | 1 |
| 2026-01-30-ppi | fixed UTC+2 | 2026-01-30T15:30 | 1.22 | 1.68 | 7.70 | — | 2026-01-30T16:31 | 61 |
| 2026-02-05-jolts | Europe/Helsinki | 2026-02-05T17:00 | 0.91 | 2.09 | 7.70 | — | — | — |
| 2026-02-05-jolts | fixed UTC+3 | 2026-02-05T18:00 | 1.10 | 1.87 | 1.00 | — | — | — |
| 2026-02-05-jolts | fixed UTC+2 | 2026-02-05T17:00 | 0.91 | 2.09 | 7.70 | — | — | — |
| 2026-02-10-eci-import-export | Europe/Helsinki | 2026-02-10T15:30 | 1.64 | 3.31 | 4.81 | 2026-02-10T15:30 | 2026-02-10T15:30 | 0 |
| 2026-02-10-eci-import-export | fixed UTC+3 | 2026-02-10T16:30 | 1.77 | 2.25 | 1.00 | — | 2026-02-10T15:30 | -60 |
| 2026-02-10-eci-import-export | fixed UTC+2 | 2026-02-10T15:30 | 1.64 | 3.31 | 4.81 | 2026-02-10T15:30 | 2026-02-10T15:30 | 0 |
| 2026-02-11-employment | Europe/Helsinki | 2026-02-11T15:30 | 2.29 | 13.73 | 8.56 | 2026-02-11T15:30 | 2026-02-11T15:30 | 0 |
| 2026-02-11-employment | fixed UTC+3 | 2026-02-11T16:30 | 1.78 | 2.27 | 1.23 | — | 2026-02-11T15:30 | -60 |
| 2026-02-11-employment | fixed UTC+2 | 2026-02-11T15:30 | 2.29 | 13.73 | 8.56 | 2026-02-11T15:30 | 2026-02-11T15:30 | 0 |
| 2026-02-13-cpi | Europe/Helsinki | 2026-02-13T15:30 | 2.40 | 12.56 | 6.04 | 2026-02-13T15:30 | 2026-02-13T15:30 | 0 |
| 2026-02-13-cpi | fixed UTC+3 | 2026-02-13T16:30 | 1.83 | 2.19 | 1.31 | — | 2026-02-13T15:30 | -60 |
| 2026-02-13-cpi | fixed UTC+2 | 2026-02-13T15:30 | 2.40 | 12.56 | 6.04 | 2026-02-13T15:30 | 2026-02-13T15:30 | 0 |
| 2026-02-27-ppi | Europe/Helsinki | 2026-02-27T15:30 | 1.30 | 3.57 | 4.47 | 2026-02-27T15:30 | 2026-02-27T15:30 | 0 |
| 2026-02-27-ppi | fixed UTC+3 | 2026-02-27T16:30 | 1.74 | 3.99 | 1.11 | 2026-02-27T16:31 | 2026-02-27T15:30 | -60 |
| 2026-02-27-ppi | fixed UTC+2 | 2026-02-27T15:30 | 1.30 | 3.57 | 4.47 | 2026-02-27T15:30 | 2026-02-27T15:30 | 0 |
| 2026-03-11-cpi | Europe/Helsinki | 2026-03-11T14:30 | 2.67 | 4.94 | 1.22 | 2026-03-11T14:30 | 2026-03-11T14:30 | 0 |
| 2026-03-11-cpi | fixed UTC+3 | 2026-03-11T15:30 | 1.58 | 2.27 | 1.15 | — | 2026-03-11T14:30 | -60 |
| 2026-03-11-cpi | fixed UTC+2 | 2026-03-11T14:30 | 2.67 | 4.94 | 1.22 | 2026-03-11T14:30 | 2026-03-11T14:30 | 0 |
| 2026-03-13-gdp-pce | Europe/Helsinki | 2026-03-13T14:30 | 1.45 | 1.36 | 1.04 | — | — | — |
| 2026-03-13-gdp-pce | fixed UTC+3 | 2026-03-13T15:30 | 1.56 | 1.24 | 1.04 | — | — | — |
| 2026-03-13-gdp-pce | fixed UTC+2 | 2026-03-13T14:30 | 1.45 | 1.36 | 1.04 | — | — | — |
| 2026-03-13-jolts | Europe/Helsinki | 2026-03-13T16:00 | 0.86 | 2.05 | 1.11 | — | — | — |
| 2026-03-13-jolts | fixed UTC+3 | 2026-03-13T17:00 | 1.30 | 2.10 | 1.04 | — | — | — |
| 2026-03-13-jolts | fixed UTC+2 | 2026-03-13T16:00 | 0.86 | 2.05 | 1.11 | — | — | — |
| 2026-03-18-ppi | Europe/Helsinki | 2026-03-18T14:30 | 2.35 | 2.08 | 3.64 | 2026-03-18T14:30 | 2026-03-18T14:30 | 0 |
| 2026-03-18-ppi | fixed UTC+3 | 2026-03-18T15:30 | 1.20 | 1.59 | 1.47 | — | 2026-03-18T14:30 | -60 |
| 2026-03-18-ppi | fixed UTC+2 | 2026-03-18T14:30 | 2.35 | 2.08 | 3.64 | 2026-03-18T14:30 | 2026-03-18T14:30 | 0 |
| 2026-03-24-productivity | Europe/Helsinki | 2026-03-24T14:30 | 1.29 | 1.59 | 1.27 | — | — | — |
| 2026-03-24-productivity | fixed UTC+3 | 2026-03-24T15:30 | 1.51 | 2.29 | 1.10 | — | — | — |
| 2026-03-24-productivity | fixed UTC+2 | 2026-03-24T14:30 | 1.29 | 1.59 | 1.27 | — | — | — |
| 2026-03-25-import-export | Europe/Helsinki | 2026-03-25T14:30 | 2.09 | 4.87 | 1.46 | 2026-03-25T14:31 | 2026-03-25T14:31 | 1 |
| 2026-03-25-import-export | fixed UTC+3 | 2026-03-25T15:30 | 1.41 | 2.42 | 1.34 | — | 2026-03-25T14:31 | -59 |
| 2026-03-25-import-export | fixed UTC+2 | 2026-03-25T14:30 | 2.09 | 4.87 | 1.46 | 2026-03-25T14:31 | 2026-03-25T14:31 | 1 |

## DST-transition evidence

[NIST](https://www.nist.gov/pml/time-and-frequency-division/popular-links/daylight-saving-time-dst) states that U.S. DST in 2026 ran from March 8 to November 1 and, generally, from the second Sunday in March to the first Sunday in November. The [European Commission](https://transport.ec.europa.eu/transport-themes/summertime_en) states that EU summer time begins on the last Sunday of March and ends on the last Sunday of October. Therefore the tested March 11–25, 2026 releases occurred while New York was UTC−4 but Helsinki remained UTC+2. October 28, 2025 occurred after Europe's October 26 change but before the U.S. November 2 change.

| Mismatch regime | Events | Helsinki aligned ≤2 min | fixed UTC+3 aligned ≤2 min | fixed UTC+2 aligned ≤2 min | Interpretation |
|---|---:|---:|---:|---:|---|
| spring_dst_mismatch | 6 | 3 | 0 | 3 | Helsinki should coincide with UTC+2 during this mismatch; the combined summer and winter evidence is what rejects a permanently fixed +2 clock. |
| fall_dst_mismatch | 1 | 0 | 0 | 0 | Helsinki should coincide with UTC+2 during this mismatch; the combined summer and winter evidence is what rejects a permanently fixed +2 clock. |

## Decision criteria assessment

- Multiple official event dates were tested in December 2025, January 2026, February 2026, summer 2025, and both available DST-mismatch regimes.
- Both 08:30 ET and 10:00 ET releases were included.
- Europe/Helsinki must align across all regimes; a model is not credited merely because it ties Helsinki within one regime.
- A market response is probabilistic. Low-signal releases remain in the table and are not silently treated as confirmations.
- Direct broker documentation is absent, so empirical event alignment supports the clock strongly but does not independently authenticate the broker's server configuration.

## Conflicting and non-confirming dates

Two low-response 08:30 releases selected a material window 61 minutes after the Helsinki candidate. Both selected timestamps are 09:31 ET, immediately after the independent U.S. cash-equity open, while their official 08:30 windows did not meet the material threshold. They are retained as adverse evidence rather than reclassified as confirmations.

| Official release | Helsinki prediction | Selected material time | Helsinki error | Why not decisive |
|---|---|---|---:|---|
| 2025-12-10 08:30 ET — ECI Q3 2025 | 2025-12-10 15:30 source | 2025-12-10 16:31 source | +61 min | Official window was low-response; selected window coincides with 09:31 ET equity-open activity. |
| 2026-01-30 08:30 ET — PPI December 2025 | 2026-01-30 15:30 source | 2026-01-30 16:31 source | +61 min | Official window had spread expansion but insufficient tick/range confirmation; selected window coincides with 09:31 ET. |

Nine further releases produced no qualifying material response under either distinct source-time candidate: 2025-07-29, 2025-09-03, 2025-10-28, 2025-12-09, 2026-01-07, 2026-02-05, 2026-03-13 (08:30 and 10:00), and 2026-03-24. These dates are non-confirming, not contradictory. The fall 2025 mismatch observation is therefore arithmetically useful but empirically inconclusive.

If direct authentication rather than strong empirical support is required, obtain the broker's historical server-time/DST policy, an MT5 server-time log, or a timestamped broker chart/export covering a known transition week. Those items would distinguish a documented broker clock from a clock inferred through market reactions.

## Dataset validity and next gate

The existing canonical tick and one-minute bid/ask datasets remain valid under the selected model. Event-time attribution is safe for Stage 1 under Europe/Helsinki with automatic DST conversion. Stage 1 still requires the point-in-time economic calendar gate and explicit user confirmation; it was not started here.

## Limitations

- First material reaction is resolved to the minute because the focused comparison uses the existing one-minute derivative; it does not claim sub-minute latency.
- The same normalized bars were created under Europe/Helsinki. This test validates source-wall alignment against independent official release times, but direct broker documentation would be stronger non-market corroboration.
- Fixed UTC+2 and Helsinki are observationally identical in winter and during the tested mismatch weeks; fixed UTC+3 and Helsinki are identical when both regions are on DST. Only the combined seasonal sample distinguishes them.
- The fall mismatch has one eligible 10:00 release because the 2025 U.S. government lapse removed or delayed many official releases. It is reported rather than over-weighted.
- Expansion at a scheduled release does not imply a trading edge and is not evidence for continuation, reversal, or manipulation.

Generated at `2026-07-17T14:51:55+00:00`.
