# External Data Setup

## Local discovery result

No usable empirical input was found. The repository contains only `XAUUSDM15.csv` and its UTC-normalized derivative. Both are 15-minute single-price bars with no usable bid/ask spread history. No tick archive, one-minute bid/ask export, economic-calendar export, connector implementation or matching credential variable was detected.

The M15 files are deliberately rejected. They must not be copied, relabeled or upsampled for this study.

## Installation

Install the repository dependencies:

```bash
python -m pip install -e ".[dev]"
```

For Parquet input/output, install the isolated optional requirement:

```bash
python -m pip install -r research/event_study_0830_0930/requirements-empirical.txt
```

Store licensed data under `research/event_study_0830_0930/external_data/raw/`. That path and all normalized/output directories are ignored by the local research `.gitignore`.

## Market adapters

| Adapter | Input | Notes |
|---|---|---|
| `generic-csv` | CSV bars or ticks | Uses canonical names or a mapping JSON |
| `broker-csv` | Vendor-specific CSV | Requires explicit canonical-to-source mapping where aliases do not match |
| `mt5` | MT5 ticks or explicit bid/ask bars | Combines MT5 date/time fields; refuses ordinary single-price OHLC bars |
| `dukascopy` | Dukascopy tick CSV | Recognizes common bid/ask price and volume labels |
| `parquet` | Canonical or mapped Parquet | Requires `pyarrow` from the isolated requirements file |

Example tick import and aggregation:

```bash
python -m research.event_study_0830_0930.empirical_cli import-market \
  --input research/event_study_0830_0930/external_data/raw/xauusd_ticks.csv \
  --adapter mt5 \
  --mode ticks \
  --source-timezone UTC \
  --source "BROKER_OR_VENDOR" \
  --symbol "XAUUSD" \
  --ticks-output research/event_study_0830_0930/external_data/normalized/xauusd_ticks.csv \
  --output research/event_study_0830_0930/external_data/normalized/xauusd_1m_bidask.csv \
  --metadata-output research/event_study_0830_0930/external_data/normalized/market_metadata.json
```

For a broker CSV, `--column-mapping-json` accepts an object such as `{"timestamp":"Time","bid":"BidPx","ask":"AskPx"}`. Mapping values are source-column names. Do not place credentials in mapping files.

## Calendar adapters

Calendar input supports `generic-csv`, `broker-csv`, `mt5` and `parquet`. Point-in-time verification defaults to false when the source does not provide the field.

```bash
python -m research.event_study_0830_0930.empirical_cli import-calendar \
  --input research/event_study_0830_0930/external_data/raw/us_releases.csv \
  --adapter generic-csv \
  --source-timezone America/New_York \
  --source "CALENDAR_VENDOR" \
  --events-output research/event_study_0830_0930/external_data/calendar/releases_canonical.csv \
  --clusters-output research/event_study_0830_0930/external_data/calendar/event_clusters.csv \
  --metadata-output research/event_study_0830_0930/external_data/calendar/calendar_metadata.json
```

An optional directional mapping is supplied through `--direction-mapping-json`. No direction is assumed by default. The mapping must separately state implications for the U.S. dollar, nominal yields, real yields, risk sentiment and any derived gold-direction hypothesis.

Credentials, if later required by a licensed provider, must remain in an approved connector or ignored environment configuration. The current repository contains no approved data-access implementation, so this phase performs file-based ingestion only.
