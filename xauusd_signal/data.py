from __future__ import annotations

from pathlib import Path

import pandas as pd


CANONICAL_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def _as_utc(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce")


def infer_bar_delta(df: pd.DataFrame) -> pd.Timedelta:
    if len(df) < 2:
        return pd.Timedelta(minutes=15)
    deltas = df["timestamp"].sort_values().diff().dropna()
    if deltas.empty:
        return pd.Timedelta(minutes=15)
    return deltas.median()


def add_closed_at(df: pd.DataFrame, bar_delta: pd.Timedelta | None = None) -> pd.DataFrame:
    result = df.copy()
    delta = bar_delta or infer_bar_delta(result)
    result["closed_at"] = result["timestamp"] + delta
    return result


def load_ohlcv_csv(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    first_line = path.read_text(encoding="utf-8", errors="ignore").splitlines()[0]

    if first_line.startswith("Price,"):
        df = pd.read_csv(
            path,
            skiprows=3,
            header=None,
            names=["timestamp", "close", "high", "low", "open", "volume"],
        )
    else:
        raw = pd.read_csv(path)
        rename = {column: column.strip().lower() for column in raw.columns}
        raw = raw.rename(columns=rename)
        if "date" in raw.columns:
            date_col = "date"
        elif "datetime" in raw.columns:
            date_col = "datetime"
        else:
            date_col = "timestamp"
        df = raw.rename(columns={date_col: "timestamp"})
        df = df[["timestamp", "open", "high", "low", "close", "volume"]]

    df["timestamp"] = _as_utc(df["timestamp"])
    for column in ["open", "high", "low", "close", "volume"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["timestamp", "open", "high", "low", "close"])
    df = df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    return add_closed_at(df[CANONICAL_COLUMNS])


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    frame = df.sort_values("timestamp").set_index("timestamp")
    resampled = frame.resample(rule, label="left", closed="left").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    resampled = resampled.dropna(subset=["open", "high", "low", "close"]).reset_index()
    return add_closed_at(resampled[CANONICAL_COLUMNS], pd.to_timedelta(rule))


def causal_join_htf(base: pd.DataFrame, htf: pd.DataFrame, prefix: str) -> pd.DataFrame:
    base_sorted = base.sort_values("closed_at").reset_index(drop=True)
    htf_sorted = htf.sort_values("closed_at").reset_index(drop=True)
    htf_cols = ["closed_at", "open", "high", "low", "close", "volume"]
    renamed = htf_sorted[htf_cols].rename(
        columns={
            "closed_at": f"{prefix}_closed_at",
            "open": f"{prefix}_open",
            "high": f"{prefix}_high",
            "low": f"{prefix}_low",
            "close": f"{prefix}_close",
            "volume": f"{prefix}_volume",
        }
    )
    joined = pd.merge_asof(
        base_sorted,
        renamed,
        left_on="closed_at",
        right_on=f"{prefix}_closed_at",
        direction="backward",
        allow_exact_matches=True,
    )
    return joined
