# Empirical Data Quality Report

Status: **NOT RUN — NO ELIGIBLE DATA**

No empirical quality statistics or performance results were calculated.

Local discovery found only the ignored MT5 `XAUUSDM15.csv` file and its UTC-normalized M15 derivative. They are single-price 15-minute bars with a zero spread field and cannot satisfy the one-minute/tick bid/ask contract. No historical point-in-time economic-release export was found.

The pipeline therefore refused to substitute or upsample the available files. The machine-readable companion uses null values rather than fabricated measurements.

Stage 1 remains blocked until both required external inputs are imported and pass `empirical_cli validate`.
