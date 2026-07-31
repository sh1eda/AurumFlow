# XAUUSD Tick Export — Bounded Inspection

Inspection date: 2026-07-17  
Input: `data/local/XAUUSD_202507171300_202607171409.csv`  
Import status: **not imported**; this report uses bounded byte and row samples only.

## Detected format

| Property | Finding |
|---|---|
| File size | 4,794,134,791 bytes (4.794 GB; 4.465 GiB) |
| Container | Delimited text despite the `.csv` extension |
| Encoding | 7-bit ASCII (valid UTF-8 subset), no BOM |
| Line endings | CRLF |
| Delimiter | Tab (`\t`) |
| Header | `<DATE>`, `<TIME>`, `<BID>`, `<ASK>`, `<LAST>`, `<VOLUME>`, `<FLAGS>` |
| Timestamp representation | Separate date and time fields: `%Y.%m.%d` + `%H:%M:%S.%f`, observed millisecond precision |
| Timezone marker | None; timestamps are timezone-naive |
| Bid / ask | `<BID>` / `<ASK>` |
| Optional last / volume | Columns exist but were empty in all 249,999 sampled data rows |
| Optional flags | `<FLAGS>` is populated; sampled values were `2`, `4`, and `6` |
| Approximate data rows | 112,705,352, estimated from file bytes and a 249,999-row sampled mean of 42.54 physical bytes per row |

The row estimate is approximate and is not used as the final row count. The full streaming validation will count rows exactly.

## Bounded chronology checks

- First observed row: `2025-07-17 13:00:00.428` (source wall clock).
- Last observed row: `2026-07-17 14:09:53.920` (source wall clock).
- Five samples were read near byte offsets 0%, 25%, 50%, 75%, and the final 8 MB.
- Each 50,000-row sample was internally non-decreasing, and sample boundary timestamps were ordered.
- The file therefore **appears sorted and monotonic**, but this is not yet a whole-file result.
- All 250,000 sampled physical rows had seven tab-separated fields (one was the header).

## Timezone finding

The file itself does not identify a timezone or UTC offset, so timezone cannot be proven from this export. The first tick bid (`3325.56` at source time `2025-07-17 13:00`) exactly matches the open of the existing `XAUUSDM15.csv` bar at the same naive wall time. This strongly links the tick export to the same broker/server clock as that file.

The repository's earlier data-quality report treats that server clock as `Europe/Helsinki` based on the observed UTC+2/UTC+3 session pattern, while explicitly recording that inference as unconfirmed. That IANA zone is a defensible normalization assumption for qualification, not a fact present in the tick file. Final event-time conclusions still require broker/server timezone confirmation.

## Inspection gate

The structure is suitable for a streaming parser. No sampled record showed a malformed field count, missing bid/ask value, or obvious encoding problem. Full validation may proceed without loading the file into memory. Normalization remains conditional on full-file integrity checks and will preserve the original export unchanged.
