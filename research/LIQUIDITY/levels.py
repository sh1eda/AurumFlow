"""Causal liquidity-level construction, state transitions, and study samples."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import math
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

from research.HTF_BIAS.features import (
    DataQualificationError,
    _aggregate_h4,
    _daily_bars,
    _weekly_bars,
    confirmed_swings,
    qualify_calendar,
    qualify_market_data,
)

from .definitions import (
    DEFAULT_SWING_MAX_AGE_DAYS,
    EVALUATION_CLOCKS,
    FORWARD_HORIZONS_MINUTES,
    MINIMUM_PRICE_TOLERANCE,
    NEW_YORK_STUDY_END,
    NEW_YORK_TIMEZONE,
    PRIMARY_APPROACH_VOLATILITY_FACTOR,
    PRIMARY_EVENT_COOLDOWN_MINUTES,
    PRIMARY_EXCEED_SPREAD_FACTOR,
    PRIMARY_LEVEL_VARIANTS,
    PRIMARY_TOUCH_SPREAD_FACTOR,
    RECLAIM_WINDOW_MINUTES,
    TRADING_DAY_END,
)


LEVEL_COLUMNS = [
    "level_id",
    "family",
    "label",
    "side",
    "price",
    "variant",
    "is_primary",
    "created_at",
    "available_at",
    "natural_expires_at",
    "source_period",
    "source_complete",
    "confirmation_delay",
    "volatility_scale",
    "contributor_count",
]

TRANSITION_COLUMNS = [
    "level_id",
    "family",
    "side",
    "variant",
    "event_type",
    "observed_bar_at",
    "event_at",
    "level_price",
    "touch_tolerance",
    "exceedance_threshold",
    "approach_band",
    "interaction_number",
]


@dataclass(frozen=True)
class LiquidityBuildResult:
    market: pd.DataFrame
    levels: pd.DataFrame
    transitions: pd.DataFrame
    anchor_observations: pd.DataFrame
    raw_events: pd.DataFrame
    events: pd.DataFrame
    exclusions: pd.DataFrame
    availability_audit: pd.DataFrame
    data_quality: dict[str, object]
    level_report: dict[str, object]
    event_report: dict[str, object]


def _stable_id(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:20]


def _timestamp(value: object) -> pd.Timestamp:
    result = pd.Timestamp(value)
    if result.tzinfo is None:
        result = result.tz_localize(NEW_YORK_TIMEZONE)
    return result


def _bar_extreme_timestamp(
    frame: pd.DataFrame, *, start: pd.Timestamp, end: pd.Timestamp, side: str
) -> pd.Timestamp:
    window = frame.loc[(frame.index >= start) & (frame.index < end)]
    if window.empty:
        return start
    column = "mid_high" if side == "high" else "mid_low"
    return pd.Timestamp(window[column].idxmax() if side == "high" else window[column].idxmin()) + pd.Timedelta(minutes=1)


def _prior_range_scale(daily: pd.DataFrame, available_at: pd.Timestamp) -> float:
    eligible = daily[
        daily["eligible"]
        & pd.to_datetime(daily["available_at"], utc=True).le(available_at)
    ]
    if eligible.empty:
        return math.nan
    ranges = eligible["range"].tail(14).astype(float)
    return float(ranges.median()) if not ranges.empty else math.nan


def _level_record(
    *,
    family: str,
    label: str,
    side: str,
    price: float,
    variant: str,
    created_at: pd.Timestamp,
    available_at: pd.Timestamp,
    natural_expires_at: pd.Timestamp,
    source_period: str,
    source_complete: bool,
    confirmation_delay: str,
    volatility_scale: float,
    contributor_count: int = 1,
) -> dict[str, object]:
    is_primary = PRIMARY_LEVEL_VARIANTS.get(family) == variant
    return {
        "level_id": _stable_id(family, label, variant, available_at.isoformat(), round(price, 8)),
        "family": family,
        "label": label,
        "side": side,
        "price": float(price),
        "variant": variant,
        "is_primary": bool(is_primary),
        "created_at": created_at,
        "available_at": available_at,
        "natural_expires_at": natural_expires_at,
        "source_period": source_period,
        "source_complete": bool(source_complete),
        "confirmation_delay": confirmation_delay,
        "volatility_scale": float(volatility_scale) if pd.notna(volatility_scale) else math.nan,
        "contributor_count": int(contributor_count),
    }


def _construct_previous_day_levels(
    frame: pd.DataFrame, daily: pd.DataFrame
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for source_date, row in daily[daily["eligible"]].iterrows():
        local_start = pd.Timestamp(source_date, tz=NEW_YORK_TIMEZONE)
        local_end = local_start + pd.DateOffset(days=1)
        available = _timestamp(row["available_at"])
        expires = available + pd.DateOffset(days=1)
        scale = _prior_range_scale(daily, available)
        for side, label, column in (
            ("high", "PDH", "high"),
            ("low", "PDL", "low"),
        ):
            created = _bar_extreme_timestamp(
                frame,
                start=local_start.tz_convert("UTC"),
                end=local_end.tz_convert("UTC"),
                side=side,
            )
            records.append(
                _level_record(
                    family="previous_day",
                    label=label,
                    side=side,
                    price=float(row[column]),
                    variant="completed_primary",
                    created_at=created,
                    available_at=available.tz_convert("UTC"),
                    natural_expires_at=expires.tz_convert("UTC"),
                    source_period=str(source_date),
                    source_complete=True,
                    confirmation_delay="completed New York weekday",
                    volatility_scale=scale,
                )
            )
    return records


def _construct_previous_week_levels(
    frame: pd.DataFrame, daily: pd.DataFrame, weekly: pd.DataFrame
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    complete = weekly[weekly["coverage"].ge(0.90)]
    for week_start, row in complete.iterrows():
        local_start = pd.Timestamp(week_start, tz=NEW_YORK_TIMEZONE)
        local_end = local_start + pd.DateOffset(days=5)
        available = _timestamp(row["available_at"])
        expires = available + pd.DateOffset(days=7)
        scale = _prior_range_scale(daily, available.tz_convert("UTC"))
        for side, label, column in (
            ("high", "PWH", "high"),
            ("low", "PWL", "low"),
        ):
            created = _bar_extreme_timestamp(
                frame,
                start=local_start.tz_convert("UTC"),
                end=local_end.tz_convert("UTC"),
                side=side,
            )
            records.append(
                _level_record(
                    family="previous_week",
                    label=label,
                    side=side,
                    price=float(row[column]),
                    variant="completed_primary",
                    created_at=created,
                    available_at=available.tz_convert("UTC"),
                    natural_expires_at=expires.tz_convert("UTC"),
                    source_period=str(week_start),
                    source_complete=True,
                    confirmation_delay="completed >=90%-covered market week",
                    volatility_scale=scale,
                )
            )
    return records


def _dynamic_monday_side_records(
    monday: pd.DataFrame,
    daily: pd.DataFrame,
    *,
    source_date: object,
    side: str,
) -> list[dict[str, object]]:
    column = "mid_high" if side == "high" else "mid_low"
    running = monday[column].cummax() if side == "high" else monday[column].cummin()
    revisions = running.ne(running.shift())
    positions = np.flatnonzero(revisions.to_numpy())
    if not len(positions):
        return []
    tuesday = pd.Timestamp(source_date, tz=NEW_YORK_TIMEZONE) + pd.DateOffset(days=1)
    records: list[dict[str, object]] = []
    label = "FORMING_MONDAY_HIGH" if side == "high" else "FORMING_MONDAY_LOW"
    for offset, position in enumerate(positions):
        observed = pd.Timestamp(monday.index[position])
        available = observed + pd.Timedelta(minutes=1)
        if offset + 1 < len(positions):
            expires = pd.Timestamp(monday.index[positions[offset + 1]]) + pd.Timedelta(minutes=1)
        else:
            expires = tuesday.tz_convert("UTC")
        # A 23:59 Monday revision becomes known exactly at Tuesday midnight,
        # when the forming formulation expires and the completed formulation
        # takes over. It has no observable eligibility interval.
        if available >= expires:
            continue
        records.append(
            _level_record(
                family="monday_dynamic",
                label=label,
                side=side,
                price=float(running.iloc[position]),
                variant="forming_primary",
                created_at=available,
                available_at=available,
                natural_expires_at=expires,
                source_period=str(source_date),
                source_complete=False,
                confirmation_delay="one completed minute",
                volatility_scale=_prior_range_scale(daily, available),
            )
        )
    return records


def _construct_monday_levels(
    frame: pd.DataFrame, daily: pd.DataFrame
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    monday_dates = [
        value for value in frame["date_new_york"].unique() if pd.Timestamp(value).weekday() == 0
    ]
    for source_date in sorted(monday_dates):
        monday = frame[frame["date_new_york"].eq(source_date)]
        if monday.empty:
            continue
        records.extend(
            _dynamic_monday_side_records(
                monday, daily, source_date=source_date, side="high"
            )
        )
        records.extend(
            _dynamic_monday_side_records(
                monday, daily, source_date=source_date, side="low"
            )
        )
        if source_date not in daily.index or not bool(daily.loc[source_date, "eligible"]):
            continue
        available = pd.Timestamp(source_date, tz=NEW_YORK_TIMEZONE) + pd.DateOffset(days=1)
        expires = pd.Timestamp(source_date, tz=NEW_YORK_TIMEZONE) + pd.DateOffset(days=5)
        row = daily.loc[source_date]
        for side, label, column in (
            ("high", "MONDAY_HIGH", "high"),
            ("low", "MONDAY_LOW", "low"),
        ):
            created = pd.Timestamp(
                monday[column.replace("high", "mid_high").replace("low", "mid_low")].idxmax()
                if side == "high"
                else monday["mid_low"].idxmin()
            ) + pd.Timedelta(minutes=1)
            records.append(
                _level_record(
                    family="monday_completed",
                    label=label,
                    side=side,
                    price=float(row[column]),
                    variant="completed_primary",
                    created_at=created,
                    available_at=available.tz_convert("UTC"),
                    natural_expires_at=expires.tz_convert("UTC"),
                    source_period=str(source_date),
                    source_complete=True,
                    confirmation_delay="completed eligible Monday",
                    volatility_scale=_prior_range_scale(daily, available.tz_convert("UTC")),
                )
            )
    return records


def _eligible_daily_swing_bars(daily: pd.DataFrame) -> pd.DataFrame:
    bars = daily[daily["eligible"]][["high", "low", "available_at", "range"]].copy()
    bars["atr14"] = bars["range"].shift(1).rolling(14, min_periods=5).mean()
    return bars


def _construct_swing_levels(
    daily: pd.DataFrame, h4: pd.DataFrame
) -> tuple[list[dict[str, object]], dict[tuple[str, int], pd.DataFrame]]:
    records: list[dict[str, object]] = []
    daily_bars = _eligible_daily_swing_bars(daily)
    h4_bars = h4.copy()
    h4_bars["range"] = h4_bars["high"] - h4_bars["low"]
    h4_bars["atr14"] = h4_bars["range"].shift(1).rolling(14, min_periods=5).mean()
    tables: dict[tuple[str, int], pd.DataFrame] = {}
    for timeframe, bars, family in (
        ("daily", daily_bars, "swing_daily"),
        ("4h", h4_bars, "swing_4h"),
    ):
        for width in (2, 3):
            swings = confirmed_swings(bars, width=width)
            tables[(timeframe, width)] = swings
            for _, swing in swings.iterrows():
                available = pd.Timestamp(swing["confirmation_at"])
                pivot = pd.Timestamp(swing["pivot_at"])
                created = (
                    pd.Timestamp(bars.loc[swing["pivot_at"], "available_at"])
                    if swing["pivot_at"] in bars.index
                    else pivot
                )
                scale = float(bars.loc[swing["pivot_at"], "atr14"]) if swing["pivot_at"] in bars.index else math.nan
                side = str(swing["swing_type"])
                records.append(
                    _level_record(
                        family=family,
                        label=f"CONFIRMED_{timeframe.upper()}_SWING_{side.upper()}",
                        side=side,
                        price=float(swing["level"]),
                        variant=f"width_{width}",
                        created_at=created,
                        available_at=available,
                        natural_expires_at=available + pd.Timedelta(days=DEFAULT_SWING_MAX_AGE_DAYS),
                        source_period=pivot.isoformat(),
                        source_complete=True,
                        confirmation_delay=f"{width} completed right-side {timeframe} bars",
                        volatility_scale=scale,
                    )
                )
    return records, tables


def _spread_before(frame: pd.DataFrame, timestamp: pd.Timestamp) -> float:
    position = frame.index.searchsorted(timestamp, side="left") - 1
    if position < 0:
        return math.nan
    start = max(0, position - 29)
    return float(frame["median_spread"].iloc[start : position + 1].median())


def _construct_equal_levels(
    frame: pd.DataFrame,
    h4: pd.DataFrame,
    swings: pd.DataFrame,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    if swings.empty:
        return records
    bars = h4.copy()
    bars["range"] = bars["high"] - bars["low"]
    bars["atr14"] = bars["range"].shift(1).rolling(14, min_periods=5).mean()
    ordered = swings.sort_values("confirmation_at").reset_index(drop=True)
    for current_position, current in ordered.iterrows():
        prior = ordered.iloc[:current_position]
        prior = prior[prior["swing_type"].eq(current["swing_type"])]
        pivot_at = pd.Timestamp(current["pivot_at"])
        prior = prior[
            pd.to_datetime(prior["pivot_at"], utc=True).le(pivot_at - pd.Timedelta(hours=8))
        ]
        prior = prior[
            pd.to_datetime(prior["confirmation_at"], utc=True).ge(
                pd.Timestamp(current["confirmation_at"]) - pd.Timedelta(days=20)
            )
        ]
        if prior.empty:
            continue
        available = pd.Timestamp(current["confirmation_at"])
        spread = _spread_before(frame, available)
        atr = float(bars.loc[current["pivot_at"], "atr14"]) if current["pivot_at"] in bars.index else math.nan
        tolerances = {
            "absolute": 0.50,
            "spread_aware": max(MINIMUM_PRICE_TOLERANCE, 2.0 * spread) if pd.notna(spread) else 0.50,
            "volatility_normalized": max(MINIMUM_PRICE_TOLERANCE, 0.08 * atr) if pd.notna(atr) else 0.50,
        }
        current_price = float(current["level"])
        for variant, tolerance in tolerances.items():
            qualifying = prior[(prior["level"].astype(float) - current_price).abs().le(tolerance)]
            if qualifying.empty:
                continue
            nearest_index = (qualifying["level"].astype(float) - current_price).abs().idxmin()
            matched = qualifying.loc[nearest_index]
            cluster_price = (float(matched["level"]) + current_price) / 2.0
            side = str(current["swing_type"])
            records.append(
                _level_record(
                    family="equal_high_low",
                    label="EQUAL_HIGH_CLUSTER" if side == "high" else "EQUAL_LOW_CLUSTER",
                    side=side,
                    price=cluster_price,
                    variant=variant,
                    created_at=pivot_at,
                    available_at=available,
                    natural_expires_at=available + pd.Timedelta(days=DEFAULT_SWING_MAX_AGE_DAYS),
                    source_period=f"{matched['pivot_at']}|{current['pivot_at']}",
                    source_complete=True,
                    confirmation_delay="both width-2 4H pivots confirmed; minimum 8-hour pivot spacing",
                    volatility_scale=atr,
                    contributor_count=2,
                )
            )
    return records


def construct_liquidity_levels(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    """Construct all candidate level families without reading beyond availability."""

    daily = _daily_bars(frame)
    weekly = _weekly_bars(frame)
    h4 = _aggregate_h4(frame)
    records: list[dict[str, object]] = []
    records.extend(_construct_previous_day_levels(frame, daily))
    records.extend(_construct_previous_week_levels(frame, daily, weekly))
    records.extend(_construct_monday_levels(frame, daily))
    swing_records, swing_tables = _construct_swing_levels(daily, h4)
    records.extend(swing_records)
    records.extend(_construct_equal_levels(frame, h4, swing_tables[("4h", 2)]))
    levels = pd.DataFrame.from_records(records, columns=LEVEL_COLUMNS)
    if levels.empty:
        raise DataQualificationError("no timestamp-safe liquidity levels were constructed")
    for column in ("created_at", "available_at", "natural_expires_at"):
        levels[column] = pd.to_datetime(levels[column], utc=True)
    levels = levels.sort_values(["available_at", "family", "side", "variant", "level_id"]).reset_index(drop=True)
    report = {
        "total_levels": int(len(levels)),
        "primary_levels": int(levels["is_primary"].sum()),
        "families": {
            str(family): {
                "levels": int(len(group)),
                "primary_levels": int(group["is_primary"].sum()),
                "variants": sorted(group["variant"].astype(str).unique().tolist()),
                "complete_sources": int(group["source_complete"].sum()),
            }
            for family, group in levels.groupby("family", sort=True)
        },
        "incomplete_daily_periods_excluded": int((daily["weekday"].le(4) & ~daily["eligible"]).sum()),
        "incomplete_weeks_excluded_primary": int((weekly["coverage"] < 0.90).sum()),
        "dynamic_monday_is_separate": True,
        "future_confirmed_swings_prohibited": True,
    }
    return levels, report


def _entry_mask(condition: pd.Series) -> pd.Series:
    return condition.fillna(False) & ~condition.fillna(False).shift(fill_value=False)


def _transition_records_for_level(
    frame: pd.DataFrame,
    level: Mapping[str, object],
    *,
    touch_factor: float = PRIMARY_TOUCH_SPREAD_FACTOR,
    exceed_factor: float = PRIMARY_EXCEED_SPREAD_FACTOR,
    reclaim_window_minutes: int = RECLAIM_WINDOW_MINUTES,
) -> tuple[list[dict[str, object]], pd.Timestamp | pd.NaT]:
    available = pd.Timestamp(level["available_at"])
    natural_expiry = pd.Timestamp(level["natural_expires_at"])
    path = frame.loc[(frame.index >= available) & (frame.index < natural_expiry)]
    if path.empty:
        return [], pd.NaT
    price = float(level["price"])
    side = str(level["side"])
    tolerance = np.maximum(
        MINIMUM_PRICE_TOLERANCE,
        touch_factor * path["median_spread"].astype(float).to_numpy(),
    )
    exceedance = np.maximum(
        MINIMUM_PRICE_TOLERANCE,
        exceed_factor * path["median_spread"].astype(float).to_numpy(),
    )
    volatility_scale = float(level["volatility_scale"]) if pd.notna(level["volatility_scale"]) else price * 0.002
    approach_band = np.maximum(tolerance * 2.0, PRIMARY_APPROACH_VOLATILITY_FACTOR * volatility_scale)
    tol = pd.Series(tolerance, index=path.index)
    exc = pd.Series(exceedance, index=path.index)
    app = pd.Series(approach_band, index=path.index)
    if side == "high":
        touch = path["ask_high"].ge(price - tol) & path["ask_low"].le(price + tol)
        exceeded = path["ask_high"].ge(price + exc)
        closed = path["ask_close"].ge(price + exc)
        original_close = path["ask_close"].lt(price)
        moved_away = path["mid_close"].le(price - app)
        approached = path["ask_high"].ge(price - app) & ~touch & ~exceeded
    else:
        touch = path["bid_low"].le(price + tol) & path["bid_high"].ge(price - tol)
        exceeded = path["bid_low"].le(price - exc)
        closed = path["bid_close"].le(price - exc)
        original_close = path["bid_close"].gt(price)
        moved_away = path["mid_close"].ge(price + app)
        approached = path["bid_low"].le(price + app) & ~touch & ~exceeded

    seen_exceed = exceeded.cummax().shift(fill_value=False)
    seen_touch = touch.cummax().shift(fill_value=False)
    reclaim = original_close & seen_exceed
    away = moved_away & seen_touch
    conditions = {
        "approach": approached,
        "touch": touch,
        "exceed": exceeded,
        "close_beyond": closed,
        "reclaim": reclaim,
        "move_away": away,
    }
    records: list[dict[str, object]] = []
    counters: dict[str, int] = {key: 0 for key in conditions}
    for event_type, condition in conditions.items():
        for observed_at in path.index[_entry_mask(condition)]:
            counters[event_type] += 1
            records.append(
                {
                    "level_id": level["level_id"],
                    "family": level["family"],
                    "side": side,
                    "variant": level["variant"],
                    "event_type": event_type,
                    "observed_bar_at": observed_at,
                    "event_at": observed_at + pd.Timedelta(minutes=1),
                    "level_price": price,
                    "touch_tolerance": float(tol.loc[observed_at]),
                    "exceedance_threshold": float(exc.loc[observed_at]),
                    "approach_band": float(app.loc[observed_at]),
                    "interaction_number": counters[event_type],
                }
            )

    consumed_at: pd.Timestamp | pd.NaT = pd.NaT
    close_entries = path.index[_entry_mask(closed)]
    reclaim_times = [record["event_at"] for record in records if record["event_type"] == "reclaim"]
    for observed_at in close_entries:
        event_at = observed_at + pd.Timedelta(minutes=1)
        candidate = event_at + pd.Timedelta(minutes=reclaim_window_minutes)
        terminal_bar = candidate - pd.Timedelta(minutes=1)
        if terminal_bar not in path.index:
            continue
        if any(event_at < value <= candidate for value in reclaim_times):
            continue
        terminal_position = path.index.get_loc(terminal_bar)
        terminal_beyond = bool(closed.iloc[terminal_position])
        expected = path.loc[(path.index >= event_at) & (path.index <= terminal_bar)]
        if terminal_beyond and len(expected) >= reclaim_window_minutes:
            consumed_at = candidate
            records.append(
                {
                    "level_id": level["level_id"],
                    "family": level["family"],
                    "side": side,
                    "variant": level["variant"],
                    "event_type": "consumed",
                    "observed_bar_at": terminal_bar,
                    "event_at": candidate,
                    "level_price": price,
                    "touch_tolerance": float(tol.loc[terminal_bar]),
                    "exceedance_threshold": float(exc.loc[terminal_bar]),
                    "approach_band": float(app.loc[terminal_bar]),
                    "interaction_number": 1,
                }
            )
            break
    if pd.notna(consumed_at):
        records = [record for record in records if record["event_at"] <= consumed_at]
    return records, consumed_at


def derive_level_transitions(
    frame: pd.DataFrame,
    levels: pd.DataFrame,
    *,
    touch_factor: float = PRIMARY_TOUCH_SPREAD_FACTOR,
    exceed_factor: float = PRIMARY_EXCEED_SPREAD_FACTOR,
    reclaim_window_minutes: int = RECLAIM_WINDOW_MINUTES,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Derive timestamp-available episodes and the primary consumed timestamp."""

    all_records: list[dict[str, object]] = []
    consumed: dict[str, pd.Timestamp | pd.NaT] = {}
    for level in levels.to_dict(orient="records"):
        records, consumed_at = _transition_records_for_level(
            frame,
            level,
            touch_factor=touch_factor,
            exceed_factor=exceed_factor,
            reclaim_window_minutes=reclaim_window_minutes,
        )
        all_records.extend(records)
        consumed[str(level["level_id"])] = consumed_at
    transitions = pd.DataFrame.from_records(all_records, columns=TRANSITION_COLUMNS)
    if not transitions.empty:
        transitions = transitions.sort_values(
            ["event_at", "family", "side", "level_id", "event_type"]
        ).reset_index(drop=True)
    enriched = levels.copy()
    enriched["consumed_at"] = enriched["level_id"].map(consumed)
    enriched["consumed_at"] = pd.to_datetime(enriched["consumed_at"], utc=True)
    enriched["effective_expires_at"] = enriched["natural_expires_at"]
    mask = enriched["consumed_at"].notna() & enriched["consumed_at"].lt(enriched["natural_expires_at"])
    enriched.loc[mask, "effective_expires_at"] = enriched.loc[mask, "consumed_at"]
    return enriched, transitions


def _state_at(history: pd.DataFrame, timestamp: pd.Timestamp) -> dict[str, object]:
    known = history[history["event_at"].le(timestamp)].sort_values("event_at")
    if known.empty:
        return {
            "state": "untouched",
            "prior_approaches": 0,
            "prior_touches": 0,
            "prior_exceedances": 0,
            "prior_reclaims": 0,
        }
    counts = known["event_type"].value_counts()
    latest = str(known.iloc[-1]["event_type"])
    state_map = {
        "approach": "approached",
        "touch": "touched",
        "exceed": "exceeded",
        "close_beyond": "closed_beyond",
        "reclaim": "reclaimed",
        "move_away": "moved_away",
        "consumed": "consumed",
    }
    return {
        "state": state_map[latest],
        "prior_approaches": int(counts.get("approach", 0)),
        "prior_touches": int(counts.get("touch", 0)),
        "prior_exceedances": int(counts.get("exceed", 0)),
        "prior_reclaims": int(counts.get("reclaim", 0)),
    }


def generate_seeded_control_level(
    *, anchor_id: str, level_id: str, evaluation_price: float, level_price: float, seed: int
) -> float:
    """Generate an order-independent, seeded distance sensitivity control."""

    digest = hashlib.sha256(f"{seed}|{anchor_id}|{level_id}".encode("utf-8")).digest()
    multiplier = (0.9, 1.0, 1.1)[digest[0] % 3]
    distance = abs(level_price - evaluation_price) * multiplier
    direction = -1.0 if level_price >= evaluation_price else 1.0
    return float(evaluation_price + direction * distance)


def _touch_condition_for_target(
    window: pd.DataFrame, *, level_price: float, evaluation_price: float, tolerance_factor: float = 1.0
) -> pd.Series:
    tolerance = np.maximum(
        MINIMUM_PRICE_TOLERANCE,
        tolerance_factor * PRIMARY_TOUCH_SPREAD_FACTOR * window["median_spread"].astype(float),
    )
    if level_price >= evaluation_price:
        return window["ask_high"].ge(level_price - tolerance) & window["ask_low"].le(level_price + tolerance)
    return window["bid_low"].le(level_price + tolerance) & window["bid_high"].ge(level_price - tolerance)


def _valid_window(
    frame: pd.DataFrame, start: pd.Timestamp, endpoint: pd.Timestamp
) -> tuple[pd.DataFrame, bool]:
    expected = int((endpoint - start).total_seconds() // 60)
    if expected <= 0:
        return frame.iloc[0:0], False
    window = frame.loc[(frame.index >= start) & (frame.index < endpoint)]
    valid = bool(
        endpoint - pd.Timedelta(minutes=1) in window.index
        and len(window) / expected >= 0.95
    )
    return window, valid


def _reach_window_metrics(
    frame: pd.DataFrame,
    *,
    start: pd.Timestamp,
    endpoint: pd.Timestamp,
    level_price: float,
    evaluation_price: float,
) -> dict[str, object]:
    window, valid = _valid_window(frame, start, endpoint)
    if not valid:
        return {"reached": math.nan, "time_minutes": math.nan, "censored": math.nan, "coverage": len(window)}
    condition = _touch_condition_for_target(
        window, level_price=level_price, evaluation_price=evaluation_price
    )
    touched = window.index[condition]
    reached = bool(len(touched))
    time_minutes = (
        float(((pd.Timestamp(touched[0]) + pd.Timedelta(minutes=1)) - start).total_seconds() / 60.0)
        if reached
        else math.nan
    )
    return {
        "reached": reached,
        "time_minutes": time_minutes,
        "censored": not reached,
        "coverage": float(len(window) / max(1, int((endpoint - start).total_seconds() // 60))),
    }


def _path_before_reach(
    frame: pd.DataFrame,
    *,
    start: pd.Timestamp,
    endpoint: pd.Timestamp,
    level_price: float,
    evaluation_price: float,
) -> dict[str, float]:
    window, valid = _valid_window(frame, start, endpoint)
    if not valid or window.empty:
        return {key: math.nan for key in ("toward_excursion", "away_excursion", "efficiency", "maximum_deviation", "realized_volatility")}
    condition = _touch_condition_for_target(window, level_price=level_price, evaluation_price=evaluation_price)
    if condition.any():
        first = window.index[condition][0]
        path = window.loc[:first]
    else:
        path = window
    sign = 1.0 if level_price >= evaluation_price else -1.0
    signed_high = sign * (path["mid_high"].astype(float) - evaluation_price)
    signed_low = sign * (path["mid_low"].astype(float) - evaluation_price)
    toward = float(max(signed_high.max(), signed_low.max()))
    away = float(max(-signed_high.min(), -signed_low.min()))
    closes = path["mid_close"].astype(float)
    changes = closes.diff().abs().dropna().sum()
    net = abs(float(closes.iloc[-1] - evaluation_price))
    returns = np.log(closes / closes.shift(1)).dropna()
    return {
        "toward_excursion": toward,
        "away_excursion": away,
        "efficiency": float(net / changes) if changes > 0 else math.nan,
        "maximum_deviation": away,
        "realized_volatility": float(10000.0 * math.sqrt(float(np.square(returns).sum()))),
    }


def _anchor_snapshot_scale(
    frame: pd.DataFrame, daily: pd.DataFrame, evaluation_at: pd.Timestamp
) -> tuple[float, float]:
    eligible = daily[
        daily["eligible"]
        & pd.to_datetime(daily["available_at"], utc=True).le(evaluation_at)
    ]
    prior_day_range = float(eligible.iloc[-1]["range"]) if not eligible.empty else math.nan
    rolling = frame.loc[
        (frame.index >= evaluation_at - pd.Timedelta(minutes=120)) & (frame.index < evaluation_at)
    ]
    true_range = (rolling["mid_high"] - rolling["mid_low"]).astype(float)
    volatility = float(true_range.median() * math.sqrt(120)) if len(true_range) >= 60 else math.nan
    return prior_day_range, volatility


def build_fixed_anchor_observations(
    frame: pd.DataFrame,
    calendar: pd.DataFrame,
    levels: pd.DataFrame,
    transitions: pd.DataFrame,
    *,
    evaluation_clocks: Iterable[str] = EVALUATION_CLOCKS,
    seed: int = 1729,
) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    daily = _daily_bars(frame)
    eligible_levels = levels.copy()
    primary_levels = levels[levels["is_primary"]].copy()
    histories = {key: value for key, value in transitions.groupby("level_id", sort=False)}
    records: list[dict[str, object]] = []
    exclusions: list[dict[str, object]] = []
    dates = sorted(set(calendar.index) & set(frame["date_new_york"].unique()))
    for session_date in dates:
        if pd.Timestamp(session_date).weekday() >= 5:
            continue
        for clock in evaluation_clocks:
            local = pd.Timestamp(f"{session_date} {clock}", tz=NEW_YORK_TIMEZONE)
            evaluation_at = local.tz_convert("UTC")
            if evaluation_at not in frame.index:
                exclusions.append({"study": "fixed_anchor", "session_date": str(session_date), "clock": clock, "reason": "missing_evaluation_bar"})
                continue
            active = eligible_levels[
                eligible_levels["available_at"].le(evaluation_at)
                & eligible_levels["natural_expires_at"].gt(evaluation_at)
            ].copy()
            if active.empty:
                exclusions.append({"study": "fixed_anchor", "session_date": str(session_date), "clock": clock, "reason": "no_active_primary_levels"})
                continue
            evaluation_bar = frame.loc[evaluation_at]
            evaluation_price = float(evaluation_bar["mid_open"])
            prior_day_range, rolling_volatility = _anchor_snapshot_scale(frame, daily, evaluation_at)
            confluence_threshold = max(
                0.50,
                0.10 * prior_day_range if pd.notna(prior_day_range) else 0.50,
            )
            anchor_id = f"{session_date}_{clock.replace(':', '')}"
            confluence_candidates = primary_levels[
                primary_levels["available_at"].le(evaluation_at)
                & primary_levels["effective_expires_at"].gt(evaluation_at)
            ]
            for level in active.to_dict(orient="records"):
                history = histories.get(level["level_id"], pd.DataFrame(columns=TRANSITION_COLUMNS))
                state = _state_at(history, evaluation_at)
                close_history = history[
                    history["event_type"].eq("close_beyond")
                    & history["event_at"].le(evaluation_at)
                ]
                immediate_consumed_at = (
                    pd.Timestamp(close_history["event_at"].min())
                    if not close_history.empty
                    else pd.NaT
                )
                other = confluence_candidates[
                    confluence_candidates["family"].ne(level["family"])
                    & confluence_candidates["level_id"].ne(level["level_id"])
                ]
                differences = (other["price"].astype(float) - float(level["price"])).abs()
                confluence_count = 1 + int(differences.le(confluence_threshold).sum())
                nearest_other = float(differences.min()) if not differences.empty else math.nan
                raw_distance = abs(float(level["price"]) - evaluation_price)
                spread = float(evaluation_bar["median_spread"])
                record: dict[str, object] = {
                    "anchor_id": anchor_id,
                    "level_id": level["level_id"],
                    "session_date": str(session_date),
                    "evaluation_clock": clock,
                    "evaluation_timestamp_new_york": local,
                    "evaluation_timestamp_utc": evaluation_at,
                    "evaluation_price": evaluation_price,
                    "family": level["family"],
                    "label": level["label"],
                    "side": level["side"],
                    "level_price": float(level["price"]),
                    "variant": level["variant"],
                    "is_primary": bool(level["is_primary"]),
                    "level_available_at": level["available_at"],
                    "level_effective_expires_at": level["effective_expires_at"],
                    "level_natural_expires_at": level["natural_expires_at"],
                    "active_under_primary_lifecycle": bool(
                        evaluation_at < pd.Timestamp(level["effective_expires_at"])
                    ),
                    "active_under_immediate_close_lifecycle": bool(
                        pd.isna(immediate_consumed_at)
                    ),
                    "active_under_natural_expiry_lifecycle": True,
                    "level_age_minutes": float((evaluation_at - level["available_at"]).total_seconds() / 60.0),
                    "level_age_sessions": float((evaluation_at - level["available_at"]).total_seconds() / 86400.0),
                    "raw_distance": raw_distance,
                    "spread_adjusted_distance": max(0.0, raw_distance - spread),
                    "prior_day_range_normalized_distance": raw_distance / prior_day_range if pd.notna(prior_day_range) and prior_day_range > 0 else math.nan,
                    "rolling_volatility_normalized_distance": raw_distance / rolling_volatility if pd.notna(rolling_volatility) and rolling_volatility > 0 else math.nan,
                    "prior_day_range": prior_day_range,
                    "rolling_volatility_scale": rolling_volatility,
                    "evaluation_median_spread": spread,
                    "evaluation_maximum_spread": float(evaluation_bar["maximum_spread"]),
                    "day_of_week": int(pd.Timestamp(session_date).weekday()),
                    "news_0830": bool(calendar.loc[session_date, "has_0830_release"]),
                    "news_day_class": str(calendar.loc[session_date, "news_day_class"]),
                    "confluence_count": confluence_count,
                    "nearest_independent_family_distance": nearest_other,
                    "confluence_threshold": confluence_threshold,
                    **state,
                }
                control_level = evaluation_price - (float(level["price"]) - evaluation_price)
                seeded_control = generate_seeded_control_level(
                    anchor_id=anchor_id,
                    level_id=str(level["level_id"]),
                    evaluation_price=evaluation_price,
                    level_price=float(level["price"]),
                    seed=seed,
                )
                record["matched_control_level"] = control_level
                record["seeded_control_level"] = seeded_control
                full_outcomes = bool(
                    level["is_primary"]
                    and record["active_under_primary_lifecycle"]
                )
                endpoints = {
                    "60m": evaluation_at + pd.Timedelta(minutes=60)
                }
                if full_outcomes:
                    endpoints = {
                        **{name: evaluation_at + pd.Timedelta(minutes=minutes) for name, minutes in FORWARD_HORIZONS_MINUTES.items()},
                        "study_end_1200": pd.Timestamp(f"{session_date} {NEW_YORK_STUDY_END}", tz=NEW_YORK_TIMEZONE).tz_convert("UTC"),
                        "trading_day_end_1700": pd.Timestamp(f"{session_date} {TRADING_DAY_END}", tz=NEW_YORK_TIMEZONE).tz_convert("UTC"),
                    }
                for label, endpoint in endpoints.items():
                    observed = _reach_window_metrics(
                        frame,
                        start=evaluation_at,
                        endpoint=endpoint,
                        level_price=float(level["price"]),
                        evaluation_price=evaluation_price,
                    )
                    control = _reach_window_metrics(
                        frame,
                        start=evaluation_at,
                        endpoint=endpoint,
                        level_price=control_level,
                        evaluation_price=evaluation_price,
                    )
                    seeded = _reach_window_metrics(
                        frame,
                        start=evaluation_at,
                        endpoint=endpoint,
                        level_price=seeded_control,
                        evaluation_price=evaluation_price,
                    )
                    record[f"reached_{label}"] = observed["reached"]
                    record[f"time_to_reach_minutes_{label}"] = observed["time_minutes"]
                    record[f"censored_{label}"] = observed["censored"]
                    record[f"outcome_coverage_{label}"] = observed["coverage"]
                    record[f"matched_control_reached_{label}"] = control["reached"]
                    record[f"seeded_control_reached_{label}"] = seeded["reached"]
                    if label in FORWARD_HORIZONS_MINUTES:
                        window, valid = _valid_window(frame, evaluation_at, endpoint)
                        for factor_label, factor in (("0_5x", 0.5), ("1_5x", 1.5)):
                            if not valid:
                                record[f"reached_{label}_touch_{factor_label}"] = math.nan
                                record[f"matched_control_reached_{label}_touch_{factor_label}"] = math.nan
                            else:
                                record[f"reached_{label}_touch_{factor_label}"] = bool(
                                    _touch_condition_for_target(
                                        window,
                                        level_price=float(level["price"]),
                                        evaluation_price=evaluation_price,
                                        tolerance_factor=factor,
                                    ).any()
                                )
                                record[f"matched_control_reached_{label}_touch_{factor_label}"] = bool(
                                    _touch_condition_for_target(
                                        window,
                                        level_price=control_level,
                                        evaluation_price=evaluation_price,
                                        tolerance_factor=factor,
                                    ).any()
                                )
                if full_outcomes:
                    path = _path_before_reach(
                        frame,
                        start=evaluation_at,
                        endpoint=evaluation_at + pd.Timedelta(minutes=120),
                        level_price=float(level["price"]),
                        evaluation_price=evaluation_price,
                    )
                    record.update({f"path_before_reach_{key}_120m": value for key, value in path.items()})
                records.append(record)
    return pd.DataFrame.from_records(records), exclusions


def deduplicate_interaction_events(
    events: pd.DataFrame, *, cooldown_minutes: int = PRIMARY_EVENT_COOLDOWN_MINUTES
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cluster same-family/side/type/zone events and keep the earliest."""

    if events.empty:
        return events.copy(), events.copy()
    ordered = events.sort_values(["event_at", "family", "side", "event_type", "level_id"]).copy()
    kept_indices: list[int] = []
    dropped: list[dict[str, object]] = []
    last_kept: dict[tuple[str, str, str], tuple[pd.Timestamp, float, float, int]] = {}
    cooldown = pd.Timedelta(minutes=cooldown_minutes)
    for index, row in ordered.iterrows():
        key = (str(row["family"]), str(row["side"]), str(row["event_type"]))
        prior = last_kept.get(key)
        clustered = False
        if prior is not None:
            prior_time, prior_price, prior_band, prior_index = prior
            zone = max(float(row["approach_band"]), prior_band)
            clustered = bool(
                pd.Timestamp(row["event_at"]) - prior_time <= cooldown
                and abs(float(row["level_price"]) - prior_price) <= zone
            )
            if clustered:
                dropped.append(
                    {
                        "event_id": row.get("event_id", _stable_id(row["level_id"], row["event_at"], row["event_type"])),
                        "kept_row_index": int(prior_index),
                        "reason": "same_family_side_event_zone_within_cooldown",
                    }
                )
        if not clustered:
            kept_indices.append(index)
            last_kept[key] = (
                pd.Timestamp(row["event_at"]),
                float(row["level_price"]),
                float(row["approach_band"]),
                int(index),
            )
    kept = ordered.loc[kept_indices].copy().reset_index(drop=True)
    kept["previous_same_group_event_at"] = kept.groupby(
        ["family", "side", "event_type"], sort=False
    )["event_at"].shift()
    kept["overlaps_prior_120m"] = (
        kept["event_at"] - kept["previous_same_group_event_at"] < pd.Timedelta(minutes=120)
    ).fillna(False)
    dropped_frame = pd.DataFrame.from_records(
        dropped, columns=["event_id", "kept_row_index", "reason"]
    )
    return kept, dropped_frame


def _event_outcomes(
    frame: pd.DataFrame,
    *,
    event_at: pd.Timestamp,
    level_price: float,
    side: str,
    threshold: float,
    opposing_level: float | None,
) -> dict[str, object]:
    record: dict[str, object] = {}
    if event_at not in frame.index:
        return record
    evaluation_price = float(frame.loc[event_at, "mid_open"])
    side_sign = 1.0 if side == "high" else -1.0
    for label, minutes in FORWARD_HORIZONS_MINUTES.items():
        endpoint = event_at + pd.Timedelta(minutes=minutes)
        window, valid = _valid_window(frame, event_at, endpoint)
        if not valid or window.empty:
            for name in (
                "forward_return_bps", "absolute_return_bps", "up_excursion_bps",
                "down_excursion_bps", "side_aligned_return_bps", "continuation_depth",
                "close_relative_to_level", "time_beyond_minutes", "realized_volatility_bps",
                "returned_original_side", "opposing_level_reached",
            ):
                record[f"{name}_{label}"] = math.nan
            continue
        ending = float(window["mid_close"].iloc[-1])
        forward = 10000.0 * math.log(ending / evaluation_price)
        high = float(window["mid_high"].max())
        low = float(window["mid_low"].min())
        returns = np.log(window["mid_close"] / window["mid_close"].shift(1)).dropna()
        if side == "high":
            continuation = max(0.0, high - level_price)
            beyond = window["ask_close"].ge(level_price + threshold)
            returned = window["ask_close"].lt(level_price).any()
        else:
            continuation = max(0.0, level_price - low)
            beyond = window["bid_close"].le(level_price - threshold)
            returned = window["bid_close"].gt(level_price).any()
        record.update(
            {
                f"forward_return_bps_{label}": forward,
                f"absolute_return_bps_{label}": abs(forward),
                f"up_excursion_bps_{label}": 10000.0 * math.log(high / evaluation_price),
                f"down_excursion_bps_{label}": 10000.0 * math.log(evaluation_price / low),
                f"side_aligned_return_bps_{label}": side_sign * forward,
                f"continuation_depth_{label}": continuation,
                f"close_relative_to_level_{label}": side_sign * (ending - level_price),
                f"time_beyond_minutes_{label}": int(beyond.sum()),
                f"realized_volatility_bps_{label}": 10000.0 * math.sqrt(float(np.square(returns).sum())),
                f"returned_original_side_{label}": bool(returned),
                f"opposing_level_reached_{label}": (
                    bool(_touch_condition_for_target(window, level_price=float(opposing_level), evaluation_price=evaluation_price).any())
                    if opposing_level is not None
                    else math.nan
                ),
            }
        )
    return record


def trading_session_date(timestamp: pd.Timestamp) -> date:
    """Map an instant to the validated 18:00-17:00 New York session label."""

    local = pd.Timestamp(timestamp)
    if local.tzinfo is None:
        raise ValueError("trading session mapping requires a timezone-aware timestamp")
    local = local.tz_convert(NEW_YORK_TIMEZONE)
    session_label = local.normalize() + (
        pd.DateOffset(days=1) if local.hour >= 18 else pd.DateOffset(days=0)
    )
    return session_label.date()


def build_interaction_events(
    frame: pd.DataFrame,
    calendar: pd.DataFrame,
    levels: pd.DataFrame,
    transitions: pd.DataFrame,
    *,
    cooldown_minutes: int = PRIMARY_EVENT_COOLDOWN_MINUTES,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object]]:
    primary_ids = set(levels.loc[levels["is_primary"], "level_id"].astype(str))
    raw = transitions[
        transitions["level_id"].astype(str).isin(primary_ids)
        & transitions["event_type"].isin(
            ["approach", "touch", "exceed", "close_beyond", "reclaim", "move_away"]
        )
    ].copy()
    level_fields = levels.set_index("level_id")[
        ["label", "available_at", "effective_expires_at", "is_primary"]
    ]
    raw = raw.join(level_fields, on="level_id")
    raw["event_id"] = [
        _stable_id(level_id, event_type, timestamp, number)
        for level_id, event_type, timestamp, number in zip(
            raw["level_id"], raw["event_type"], raw["event_at"], raw["interaction_number"]
        )
    ]
    raw["is_first_interaction"] = raw["interaction_number"].eq(1)
    kept, dropped = deduplicate_interaction_events(raw, cooldown_minutes=cooldown_minutes)
    primary = levels[levels["is_primary"]].copy()
    records: list[dict[str, object]] = []
    outcome_excluded = 0
    for event in kept.to_dict(orient="records"):
        event_at = pd.Timestamp(event["event_at"])
        if event_at not in frame.index:
            outcome_excluded += 1
            continue
        local = event_at.tz_convert(NEW_YORK_TIMEZONE)
        # Reuse the validated 18:00-17:00 New York trading-day convention for
        # event clustering. Sunday 18:00 and every weekday evening belong to
        # the following named trading session; fixed daytime anchors are
        # unchanged.
        session_date = trading_session_date(event_at)
        session_label = pd.Timestamp(session_date)
        active_opposing = primary[
            primary["available_at"].le(event_at)
            & primary["effective_expires_at"].gt(event_at)
            & primary["side"].ne(event["side"])
        ]
        if active_opposing.empty:
            opposing = None
        else:
            distances = (active_opposing["price"].astype(float) - float(event["level_price"])).abs()
            opposing = float(active_opposing.loc[distances.idxmin(), "price"])
        record = dict(event)
        record.update(
            {
                "session_date": session_date.isoformat(),
                "event_timestamp_new_york": local,
                "day_of_week": int(session_label.weekday()),
                "news_0830": bool(calendar.loc[session_date, "has_0830_release"]) if session_date in calendar.index else False,
                "news_day_class": str(calendar.loc[session_date, "news_day_class"]) if session_date in calendar.index else "calendar_unavailable",
                "level_age_minutes": float((event_at - pd.Timestamp(event["available_at"])).total_seconds() / 60.0),
                "opposing_level_price": opposing if opposing is not None else math.nan,
            }
        )
        record.update(
            _event_outcomes(
                frame,
                event_at=event_at,
                level_price=float(event["level_price"]),
                side=str(event["side"]),
                threshold=float(event["exceedance_threshold"]),
                opposing_level=opposing,
            )
        )
        records.append(record)
    events = pd.DataFrame.from_records(records)
    report = {
        "raw_primary_events": int(len(raw)),
        "kept_events_after_cooldown": int(len(kept)),
        "events_with_usable_start_bar": int(len(events)),
        "dropped_clustered_events": int(len(dropped)),
        "excluded_missing_event_start_bar": int(outcome_excluded),
        "cooldown_minutes": int(cooldown_minutes),
        "deduplication_key": "family x side x event_type x overlapping price zone",
        "trading_day_mapping": "18:00-17:00 America/New_York; evening events map to the following named session",
        "overlap_policy": "30-minute clustered primary; 120-minute overlap flag retained and non-overlap sensitivity reported",
        "raw_by_type": {str(key): int(value) for key, value in raw["event_type"].value_counts().sort_index().items()},
        "kept_by_type": {str(key): int(value) for key, value in events["event_type"].value_counts().sort_index().items()} if not events.empty else {},
    }
    return raw, events, dropped, report


def _availability_audit(levels: pd.DataFrame, transitions: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for (family, variant), group in levels.groupby(["family", "variant"], sort=True):
        creation_violations = int(group["created_at"].gt(group["available_at"]).sum())
        expiration_violations = int(group["available_at"].ge(group["natural_expires_at"]).sum())
        event_group = transitions[transitions["level_id"].isin(group["level_id"])]
        joined = event_group.join(group.set_index("level_id")[["available_at"]], on="level_id")
        event_violations = int(joined["event_at"].lt(joined["available_at"]).sum()) if not joined.empty else 0
        records.append(
            {
                "family": family,
                "variant": variant,
                "levels": int(len(group)),
                "events": int(len(event_group)),
                "creation_after_availability_violations": creation_violations,
                "invalid_expiration_violations": expiration_violations,
                "event_before_availability_violations": event_violations,
                "future_information_violations": creation_violations + expiration_violations + event_violations,
                "status": "PASS" if creation_violations + expiration_violations + event_violations == 0 else "FAIL",
            }
        )
    audit = pd.DataFrame.from_records(records)
    if int(audit["future_information_violations"].sum()):
        raise DataQualificationError("liquidity availability audit found future information")
    return audit


def build_liquidity_dataset(
    raw_market: pd.DataFrame,
    raw_calendar: pd.DataFrame,
    *,
    evaluation_clocks: Iterable[str] = EVALUATION_CLOCKS,
    seed: int = 1729,
    event_cooldown_minutes: int = PRIMARY_EVENT_COOLDOWN_MINUTES,
) -> LiquidityBuildResult:
    """Build both Phase 1 study designs from the validated canonical derivative."""

    frame, quality = qualify_market_data(raw_market)
    calendar = qualify_calendar(raw_calendar)
    levels, level_report = construct_liquidity_levels(frame)
    levels, transitions = derive_level_transitions(frame, levels)
    audit = _availability_audit(levels, transitions)
    anchors, anchor_exclusions = build_fixed_anchor_observations(
        frame,
        calendar,
        levels,
        transitions,
        evaluation_clocks=evaluation_clocks,
        seed=seed,
    )
    raw_events, events, dropped_events, event_report = build_interaction_events(
        frame,
        calendar,
        levels,
        transitions,
        cooldown_minutes=event_cooldown_minutes,
    )
    exclusions = pd.DataFrame.from_records(anchor_exclusions)
    if not dropped_events.empty:
        clustered = dropped_events.copy()
        clustered["study"] = "interaction_event"
        clustered["session_date"] = None
        clustered["clock"] = None
        clustered.rename(columns={"reason": "reason"}, inplace=True)
        exclusions = pd.concat(
            [exclusions, clustered[["study", "session_date", "clock", "reason"]]],
            ignore_index=True,
        )
    quality.update(
        {
            "calendar_rows": int(len(calendar)),
            "level_availability_audit": "PASS",
            "total_levels": int(len(levels)),
            "primary_levels": int(levels["is_primary"].sum()),
            "fixed_anchor_observations": int(len(anchors)),
            "fixed_anchor_sessions": int(anchors["session_date"].nunique()) if not anchors.empty else 0,
            "interaction_events": int(len(events)),
            "interaction_event_sessions": int(events["session_date"].nunique()) if not events.empty else 0,
            "missing_data_policy": "no imputation; exact anchor/event start and >=95% endpoint coverage required",
            "calendar_policy": "official timing/category context only; no actual, consensus, revision, surprise, or direction",
            "htf_bias_used_as_filter": False,
        }
    )
    level_report["consumed_primary_levels"] = int(
        (levels["is_primary"] & levels["consumed_at"].notna()).sum()
    )
    event_report["dropped_event_audit_rows"] = int(len(dropped_events))
    return LiquidityBuildResult(
        market=frame,
        levels=levels,
        transitions=transitions,
        anchor_observations=anchors,
        raw_events=raw_events,
        events=events,
        exclusions=exclusions,
        availability_audit=audit,
        data_quality=quality,
        level_report=level_report,
        event_report=event_report,
    )
