"""Causal downstream-only forward outcomes for D005_E1."""

from __future__ import annotations

from collections.abc import Iterable
import hashlib

import numpy as np
import pandas as pd

from research.context_engine.config import local_bounds

from .config import EmpiricalStudyConfig


def _anchor_id(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


class _ExtremumTree:
    """Static range extremum and first-threshold index."""

    def __init__(self, values: np.ndarray, *, maximum: bool) -> None:
        size = 1
        while size < len(values):
            size <<= 1
        self.size = size
        self.maximum = maximum
        fill = -np.inf if maximum else np.inf
        self.values = np.full(2 * size, fill, dtype=float)
        self.indices = np.full(2 * size, -1, dtype=np.int64)
        self.values[size : size + len(values)] = values
        self.indices[size : size + len(values)] = np.arange(len(values))
        for node in range(size - 1, 0, -1):
            left = node * 2
            right = left + 1
            left_value = self.values[left]
            right_value = self.values[right]
            choose_left = (
                left_value > right_value
                if maximum
                else left_value < right_value
            ) or (
                left_value == right_value
                and self.indices[left] >= 0
                and (
                    self.indices[right] < 0
                    or self.indices[left] <= self.indices[right]
                )
            )
            selected = left if choose_left else right
            self.values[node] = self.values[selected]
            self.indices[node] = self.indices[selected]

    def _better(
        self,
        first: tuple[float, int],
        second: tuple[float, int],
    ) -> tuple[float, int]:
        if first[1] < 0:
            return second
        if second[1] < 0:
            return first
        if self.maximum:
            return (
                first
                if first[0] > second[0]
                or (first[0] == second[0] and first[1] <= second[1])
                else second
            )
        return (
            first
            if first[0] < second[0]
            or (first[0] == second[0] and first[1] <= second[1])
            else second
        )

    def query(self, left: int, right: int) -> tuple[float, int]:
        result = (
            (-np.inf, -1) if self.maximum else (np.inf, -1)
        )
        left += self.size
        right += self.size
        while left < right:
            if left & 1:
                result = self._better(
                    result,
                    (float(self.values[left]), int(self.indices[left])),
                )
                left += 1
            if right & 1:
                right -= 1
                result = self._better(
                    result,
                    (float(self.values[right]), int(self.indices[right])),
                )
            left >>= 1
            right >>= 1
        return result

    def first_threshold(
        self,
        left: int,
        right: int,
        threshold: float,
    ) -> int:
        def search(node: int, node_left: int, node_right: int) -> int:
            if node_right <= left or right <= node_left:
                return -1
            value = float(self.values[node])
            qualifies = (
                value >= threshold
                if self.maximum
                else value <= threshold
            )
            if not qualifies:
                return -1
            if node_right - node_left == 1:
                return node_left
            middle = (node_left + node_right) // 2
            found = search(node * 2, node_left, middle)
            return (
                found
                if found >= 0
                else search(node * 2 + 1, middle, node_right)
            )

        return search(1, 0, self.size)


def session_label(stamp: pd.Timestamp, timezone: str) -> str:
    local = pd.Timestamp(stamp).tz_convert(timezone)
    minutes = local.hour * 60 + local.minute
    if minutes >= 18 * 60:
        return "asia"
    if minutes < 8 * 60 + 30:
        return "premarket"
    if minutes < 12 * 60:
        return "ny_observation"
    if minutes < 17 * 60:
        return "ny_afternoon"
    if minutes < 18 * 60:
        return "maintenance"
    return "asia"


def add_causal_volatility_regime(
    anchors: pd.DataFrame,
    daily: pd.DataFrame,
    config: EmpiricalStudyConfig,
) -> pd.DataFrame:
    """Label anchors using only previously available completed daily ranges."""

    if anchors.empty:
        result = anchors.copy()
        result["volatility_regime"] = pd.Series(dtype="object")
        result["volatility_ratio"] = pd.Series(dtype="float64")
        return result
    daily_work = daily.copy()
    daily_work["daily_range"] = daily_work["high"] - daily_work["low"]
    daily_work["prior_range_median"] = (
        daily_work["daily_range"]
        .shift(1)
        .rolling(
            config.volatility_lookback_days,
            min_periods=config.volatility_lookback_days,
        )
        .median()
    )
    daily_work["volatility_ratio"] = (
        daily_work["daily_range"] / daily_work["prior_range_median"]
    )
    available = pd.DatetimeIndex(
        pd.to_datetime(daily_work["available_at"], utc=True)
    ).as_unit("ns").asi8
    ratios = daily_work["volatility_ratio"].to_numpy(dtype=float)
    result = anchors.copy()
    values: list[float] = []
    labels: list[str] = []
    for value in pd.to_datetime(result["anchor_at"], utc=True):
        position = int(
            np.searchsorted(available, pd.Timestamp(value).value, side="right")
        ) - 1
        ratio = ratios[position] if position >= 0 else np.nan
        values.append(float(ratio) if np.isfinite(ratio) else np.nan)
        labels.append(
            "unavailable"
            if not np.isfinite(ratio)
            else "low"
            if ratio < config.low_volatility_ratio
            else "high"
            if ratio > config.high_volatility_ratio
            else "normal"
        )
    result["volatility_ratio"] = values
    result["volatility_regime"] = labels
    return result


def build_forward_outcomes(
    anchors: pd.DataFrame,
    one_minute: pd.DataFrame,
    *,
    config: EmpiricalStudyConfig,
) -> pd.DataFrame:
    """Calculate future paths without feeding outcomes into D005 state."""

    if anchors.empty:
        return pd.DataFrame()
    available = pd.DatetimeIndex(one_minute.index) + pd.Timedelta(minutes=1)
    available_ns = available.as_unit("ns").asi8
    closes = one_minute["close"].to_numpy(dtype=float, copy=False)
    highs = one_minute["high"].to_numpy(dtype=float, copy=False)
    lows = one_minute["low"].to_numpy(dtype=float, copy=False)
    high_tree = _ExtremumTree(highs, maximum=True)
    low_tree = _ExtremumTree(lows, maximum=False)
    rows: list[dict[str, object]] = []
    for anchor in anchors.to_dict("records"):
        anchor_at = pd.Timestamp(anchor["anchor_at"]).tz_convert("UTC")
        position = int(
            np.searchsorted(available_ns, anchor_at.value, side="right")
        ) - 1
        if position < 0:
            continue
        anchor_price = float(closes[position])
        direction = int(anchor.get("direction", 0) or 0)
        local_date = anchor_at.tz_convert(config.timezone).date()
        noon, _ = local_bounds(
            local_date, "12:00", "12:00", config.timezone
        )
        day_end, _ = local_bounds(
            local_date,
            config.day_end_clock,
            config.day_end_clock,
            config.timezone,
        )
        horizons: list[tuple[str, pd.Timestamp]] = [
            (
                f"{minutes}m",
                anchor_at + pd.Timedelta(minutes=minutes),
            )
            for minutes in config.forward_minutes
        ]
        if anchor_at < noon:
            horizons.append(("ny_noon", noon))
        if anchor_at < day_end:
            horizons.append(("trading_day_end", day_end))
        for label, horizon_at in horizons:
            end_position = int(
                np.searchsorted(
                    available_ns, horizon_at.value, side="right"
                )
            ) - 1
            if end_position <= position:
                continue
            end_price = float(closes[end_position])
            path_left = position + 1
            path_right = end_position + 1
            if path_left >= path_right:
                continue
            maximum_high, high_position = high_tree.query(
                path_left,
                path_right,
            )
            minimum_low, low_position = low_tree.query(
                path_left,
                path_right,
            )
            if direction > 0:
                mfe = maximum_high - anchor_price
                mae = anchor_price - minimum_low
                mfe_position, mae_position = high_position, low_position
            elif direction < 0:
                mfe = anchor_price - minimum_low
                mae = maximum_high - anchor_price
                mfe_position, mae_position = low_position, high_position
            else:
                mfe = np.nan
                mae = np.nan
                mfe_position = mae_position = -1
            mfe_at = (
                pd.Timestamp(available[mfe_position])
                if direction
                else None
            )
            mae_at = (
                pd.Timestamp(available[mae_position])
                if direction
                else None
            )
            invalidation_level = anchor.get("invalidation_level")
            opposing_level = anchor.get("opposing_liquidity_level")
            target_hit_at: pd.Timestamp | None = None
            invalidation_hit_at: pd.Timestamp | None = None
            if direction and opposing_level is not None and not pd.isna(
                opposing_level
            ):
                target_position = (
                    high_tree.first_threshold(
                        path_left,
                        path_right,
                        float(opposing_level),
                    )
                    if direction > 0
                    else low_tree.first_threshold(
                        path_left,
                        path_right,
                        float(opposing_level),
                    )
                )
                if target_position >= 0:
                    target_hit_at = pd.Timestamp(
                        available[target_position]
                    )
            if direction and invalidation_level is not None and not pd.isna(
                invalidation_level
            ):
                invalidation_position = (
                    low_tree.first_threshold(
                        path_left,
                        path_right,
                        float(invalidation_level),
                    )
                    if direction > 0
                    else high_tree.first_threshold(
                        path_left,
                        path_right,
                        float(invalidation_level),
                    )
                )
                if invalidation_position >= 0:
                    invalidation_hit_at = pd.Timestamp(
                        available[invalidation_position]
                    )
            rows.append(
                {
                    **anchor,
                    "anchor_id": anchor.get("anchor_id")
                    or _anchor_id(
                        anchor.get("anchor_type"),
                        anchor.get("source_id"),
                        anchor_at,
                        anchor.get("mapping_variant"),
                    ),
                    "anchor_at": anchor_at,
                    "anchor_price": anchor_price,
                    "horizon": label,
                    "horizon_at": horizon_at,
                    "observed_until": pd.Timestamp(
                        available[end_position]
                    ),
                    "end_price": end_price,
                    "signed_change": (
                        (end_price - anchor_price) * direction
                        if direction
                        else np.nan
                    ),
                    "absolute_change": abs(end_price - anchor_price),
                    "mfe": mfe,
                    "mae": mae,
                    "range_expansion": maximum_high - minimum_low,
                    "time_to_mfe_minutes": (
                        (mfe_at - anchor_at).total_seconds() / 60.0
                        if direction
                        else np.nan
                    ),
                    "time_to_mae_minutes": (
                        (mae_at - anchor_at).total_seconds() / 60.0
                        if direction
                        else np.nan
                    ),
                    "opposing_liquidity_reached": (
                        target_hit_at is not None
                        if opposing_level is not None
                        and not pd.isna(opposing_level)
                        else None
                    ),
                    "invalidation_reached": (
                        invalidation_hit_at is not None
                        if invalidation_level is not None
                        and not pd.isna(invalidation_level)
                        else None
                    ),
                    "invalidation_first": (
                        invalidation_hit_at is not None
                        and (
                            target_hit_at is None
                            or invalidation_hit_at < target_hit_at
                        )
                        if invalidation_level is not None
                        and not pd.isna(invalidation_level)
                        else None
                    ),
                    "target_hit_at": target_hit_at,
                    "invalidation_hit_at": invalidation_hit_at,
                    "outcome_is_downstream_only": True,
                }
            )
    return pd.DataFrame.from_records(rows)


def transition_anchors(transitions: pd.DataFrame) -> pd.DataFrame:
    if transitions.empty:
        return pd.DataFrame()
    frame = transitions.copy()
    frame["anchor_type"] = "state_transition"
    frame["source_id"] = frame["transition_id"]
    frame["anchor_at"] = pd.to_datetime(frame["occurred_at"], utc=True)
    frame["invalidation_level"] = np.nan
    frame["opposing_liquidity_level"] = np.nan
    return frame[
        [
            "anchor_type",
            "source_id",
            "anchor_at",
            "direction",
            "mapping_variant",
            "mode",
            "session_date",
            "outcome",
            "invalidation_level",
            "opposing_liquidity_level",
        ]
    ]


def event_anchors(
    events: Iterable[dict[str, object]],
    *,
    timezone: str,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for event in events:
        anchor_at = (
            event.get("interacted_at")
            if event.get("event_type") in {"raw_fvg", "order_block"}
            and event.get("interacted_at") is not None
            else event.get("available_at")
        )
        if anchor_at is None or pd.isna(anchor_at):
            continue
        direction = int(event.get("direction", 0) or 0)
        invalidation_level = (
            event.get("zone_low")
            if direction > 0
            else event.get("zone_high")
            if direction < 0
            else None
        )
        rows.append(
            {
                "anchor_type": str(event.get("event_type")),
                "source_id": str(event.get("event_id")),
                "anchor_at": pd.Timestamp(anchor_at),
                "direction": direction,
                "mapping_variant": event.get("mapping_variant"),
                "mode": "event_inventory",
                "outcome": "not_applicable",
                "session_date": pd.Timestamp(anchor_at)
                .tz_convert(timezone)
                .date()
                .isoformat(),
                "invalidation_level": invalidation_level,
                "opposing_liquidity_level": event.get(
                    "opposing_liquidity_level"
                ),
            }
        )
    return pd.DataFrame.from_records(rows).drop_duplicates(
        ["anchor_type", "source_id", "mapping_variant", "anchor_at"]
    )
