from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date

import pandas as pd

from .config import StudyConfig
from .features import _timestamp, _window
from .structures import (
    aggregate_structure_bars,
    find_first_mss,
    find_fvgs,
    mark_displacement,
    rejection_zone,
)


@dataclass(frozen=True)
class CandidateOrder:
    order_id: str
    setup_id: str
    session_date: date
    family: str
    structure_scale: str
    geometry: str
    direction: int
    created_at: pd.Timestamp
    entry_price: float | None
    stop_price: float
    opposing_level: float | None
    expiry: pd.Timestamp
    event_class: str
    news_category: str
    important_1000_release: bool
    impulse_size_bucket: str
    higher_timeframe_bias_alignment: bool
    directional_relationship_0830_0930: str


def _first_post_0930_sweep(
    bars: pd.DataFrame,
    *,
    high_level: float,
    low_level: float,
    buffer: float,
    maximum_reentry_bars: int,
) -> dict | None:
    candidates: list[dict] = []
    for position, (timestamp, bar) in enumerate(bars.iterrows()):
        if float(bar["high"]) >= high_level + buffer:
            future = bars.iloc[position : position + maximum_reentry_bars + 1]
            reentries = future[future["close"] <= high_level]
            if not reentries.empty:
                candidates.append(
                    {
                        "breach_time": timestamp,
                        "reentry_time": reentries.index[0],
                        "trade_direction": -1,
                        "invalidation": float(future.loc[: reentries.index[0], "high"].max()) + buffer,
                        "opposing_level": low_level,
                    }
                )
        if float(bar["low"]) <= low_level - buffer:
            future = bars.iloc[position : position + maximum_reentry_bars + 1]
            reentries = future[future["close"] >= low_level]
            if not reentries.empty:
                candidates.append(
                    {
                        "breach_time": timestamp,
                        "reentry_time": reentries.index[0],
                        "trade_direction": 1,
                        "invalidation": float(future.loc[: reentries.index[0], "low"].min()) - buffer,
                        "opposing_level": high_level,
                    }
                )
    return min(candidates, key=lambda value: value["reentry_time"]) if candidates else None


def _trigger_for_session(
    structural_day: pd.DataFrame,
    row: pd.Series,
    *,
    family: str,
    structure_minutes: int,
    config: StudyConfig,
) -> dict | None:
    session_date = row.name
    impulse_direction = int(row["impulse_direction"])
    if impulse_direction == 0:
        return None
    start_0835 = _timestamp(session_date, config.impulse_end, config.timezone)
    open_0930 = _timestamp(session_date, config.equity_open, config.timezone)
    end_1000 = _timestamp(session_date, config.delivery_end, config.timezone)

    if family == "A_0830_impulse_continuation":
        acceptance_time = row["directional_boundary_acceptance_time"]
        if pd.isna(acceptance_time):
            return None
        start = max(start_0835, acceptance_time)
        mss = find_first_mss(
            structural_day,
            direction=impulse_direction,
            start=start,
            end=open_0930,
            width=config.swing_width,
            require_displacement=True,
        )
        if not mss:
            return None
        before_signal = structural_day[(structural_day.index >= start_0835) & (structural_day.index <= mss["mss_time"])]
        midpoint = float(row["impulse_midpoint"])
        buffer = float(row["tick_buffer"])
        held = bool(
            before_signal["close"].ge(midpoint - buffer).all()
            if impulse_direction > 0
            else before_signal["close"].le(midpoint + buffer).all()
        )
        if not held:
            return None
        return {
            **mss,
            "family": family,
            "trigger_time": mss["mss_time"],
            "trade_direction": impulse_direction,
            "invalidation": (
                float(row["impulse_0830_0835_low"]) - buffer
                if impulse_direction > 0
                else float(row["impulse_0830_0835_high"]) + buffer
            ),
            "opposing_level": (
                float(row["previous_day_high"])
                if impulse_direction > 0
                else float(row["previous_day_low"])
            ),
            "reentry_time": pd.NaT,
        }

    if family == "B_0830_false_move_reversal":
        reentry_time = row["directional_boundary_reentry_time"]
        if not bool(row["reentry_before_acceptance"]) or pd.isna(reentry_time):
            return None
        trade_direction = -impulse_direction
        mss = find_first_mss(
            structural_day,
            direction=trade_direction,
            start=reentry_time,
            end=open_0930,
            width=config.swing_width,
            require_displacement=True,
        )
        if not mss:
            return None
        pre_signal = structural_day[
            (structural_day.index >= row["directional_boundary_breach_time"])
            & (structural_day.index <= mss["mss_time"])
        ]
        invalidation = (
            float(pre_signal["high"].max()) + float(row["tick_buffer"])
            if trade_direction < 0
            else float(pre_signal["low"].min()) - float(row["tick_buffer"])
        )
        return {
            **mss,
            "family": family,
            "trigger_time": mss["mss_time"],
            "trade_direction": trade_direction,
            "invalidation": invalidation,
            "opposing_level": (
                float(row["pre_0730_0829_low"])
                if trade_direction < 0
                else float(row["pre_0730_0829_high"])
            ),
            "reentry_time": reentry_time,
        }

    if family == "C_0930_non_news_manipulation":
        if row["event_class"] != "C_no_meaningful_0830":
            return None
        post_open = structural_day[(structural_day.index >= open_0930) & (structural_day.index < end_1000)]
        sweep = _first_post_0930_sweep(
            post_open,
            high_level=float(row["pre_0730_0829_high"]),
            low_level=float(row["pre_0730_0829_low"]),
            buffer=float(row["tick_buffer"]),
            maximum_reentry_bars=max(1, config.sweep_reentry_minutes // structure_minutes),
        )
        if not sweep:
            return None
        mss = find_first_mss(
            structural_day,
            direction=sweep["trade_direction"],
            start=sweep["reentry_time"],
            end=end_1000,
            width=config.swing_width,
            require_displacement=True,
        )
        if not mss:
            return None
        return {
            **mss,
            **sweep,
            "family": family,
            "trigger_time": mss["mss_time"],
        }
    raise ValueError(f"Unknown strategy family: {family}")


def _base_order_fields(
    row: pd.Series,
    trigger: dict,
    *,
    geometry: str,
    entry_price: float | None,
    structure_minutes: int,
    config: StudyConfig,
    serial: int,
) -> CandidateOrder:
    session_date = row.name
    return CandidateOrder(
        order_id=f"{session_date}-{trigger['family']}-{structure_minutes}m-{geometry}-{serial}",
        setup_id=f"{session_date}-{trigger['family']}-{structure_minutes}m",
        session_date=session_date,
        family=trigger["family"],
        structure_scale=f"{structure_minutes}m",
        geometry=geometry,
        direction=int(trigger["trade_direction"]),
        created_at=trigger["trigger_time"],
        entry_price=entry_price,
        stop_price=float(trigger["invalidation"]),
        opposing_level=(
            float(trigger["opposing_level"])
            if pd.notna(trigger.get("opposing_level", math.nan))
            else None
        ),
        expiry=_timestamp(session_date, config.secondary_end, config.timezone),
        event_class=str(row["event_class"]),
        news_category=str(row.get("news_category_0830", "")),
        important_1000_release=bool(row["important_1000_release"]),
        impulse_size_bucket=str(row.get("impulse_size_bucket", "unknown")),
        higher_timeframe_bias_alignment=bool(row.get("higher_timeframe_bias_alignment", False)),
        directional_relationship_0830_0930=str(
            row.get("directional_relationship_0830_0930", "unknown")
        ),
    )


def generate_candidate_orders(
    prices: pd.DataFrame,
    features: pd.DataFrame,
    *,
    structure_minutes: int,
    config: StudyConfig | None = None,
) -> pd.DataFrame:
    """Generate causal orders for the three standalone registered families."""

    cfg = config or StudyConfig()
    bars = mark_displacement(aggregate_structure_bars(prices, structure_minutes), config=cfg)
    order_records: list[dict] = []
    serial = 0
    families = (
        "A_0830_impulse_continuation",
        "B_0830_false_move_reversal",
        "C_0930_non_news_manipulation",
    )
    for session_date, row in features.iterrows():
        structural_day = bars[bars["session_date"].eq(session_date)]
        if structural_day.empty or not bool(row.get("core_windows_complete", False)):
            continue
        for family in families:
            trigger = _trigger_for_session(
                structural_day,
                row,
                family=family,
                structure_minutes=structure_minutes,
                config=cfg,
            )
            if not trigger:
                continue

            serial += 1
            order_records.append(
                asdict(
                    _base_order_fields(
                        row,
                        trigger,
                        geometry="market_after_confirmed_mss",
                        entry_price=None,
                        structure_minutes=structure_minutes,
                        config=cfg,
                        serial=serial,
                    )
                )
            )

            session_fvgs = find_fvgs(
                structural_day,
                minimum_width=cfg.minimum_tick_price,
                require_middle_displacement=True,
            )
            if not session_fvgs.empty:
                eligible = session_fvgs[
                    (session_fvgs["created_at"] >= trigger["trigger_time"])
                    & session_fvgs["direction"].eq(trigger["trade_direction"])
                ]
                if not eligible.empty:
                    fvg = eligible.sort_values("created_at").iloc[0]
                    trigger_for_fvg = {**trigger, "trigger_time": fvg["created_at"]}
                    if trigger["trade_direction"] > 0:
                        edges = {
                            "first_fvg_proximal": float(fvg["zone_high"]),
                            "first_fvg_midpoint": float(fvg["zone_midpoint"]),
                            "first_fvg_distal": float(fvg["zone_low"]),
                        }
                    else:
                        edges = {
                            "first_fvg_proximal": float(fvg["zone_low"]),
                            "first_fvg_midpoint": float(fvg["zone_midpoint"]),
                            "first_fvg_distal": float(fvg["zone_high"]),
                        }
                    for geometry, price in edges.items():
                        serial += 1
                        order_records.append(
                            asdict(
                                _base_order_fields(
                                    row,
                                    trigger_for_fvg,
                                    geometry=geometry,
                                    entry_price=price,
                                    structure_minutes=structure_minutes,
                                    config=cfg,
                                    serial=serial,
                                )
                            )
                        )

            reentry_time = trigger.get("reentry_time")
            if pd.notna(reentry_time) and reentry_time in structural_day.index:
                zone = rejection_zone(
                    structural_day.loc[reentry_time], direction=trigger["trade_direction"]
                )
                if zone:
                    serial += 1
                    order_records.append(
                        asdict(
                            _base_order_fields(
                                row,
                                trigger,
                                geometry="rejection_block_midpoint",
                                entry_price=float(zone["zone_midpoint"]),
                                structure_minutes=structure_minutes,
                                config=cfg,
                                serial=serial,
                            )
                        )
                    )

            if family == "A_0830_impulse_continuation":
                impulse_high = float(row["impulse_0830_0835_high"])
                impulse_low = float(row["impulse_0830_0835_low"])
                impulse_range = impulse_high - impulse_low
                ratios = {
                    "impulse_retracement_50": 0.50,
                    "impulse_retracement_62": 0.62,
                    "impulse_retracement_75": 0.75,
                    # With OHLC bars, the conservative deterministic proxy for
                    # first entry into the 62–79% OTE zone is its proximal 62%
                    # boundary. The 70.5% level is retained as a separate
                    # practitioner sensitivity, not privileged a priori.
                    "ote_zone_first_touch_62_79": 0.62,
                    "ote_midpoint_705": 0.705,
                }
                for geometry, ratio in ratios.items():
                    entry = (
                        impulse_high - ratio * impulse_range
                        if trigger["trade_direction"] > 0
                        else impulse_low + ratio * impulse_range
                    )
                    serial += 1
                    order_records.append(
                        asdict(
                            _base_order_fields(
                                row,
                                trigger,
                                geometry=geometry,
                                entry_price=entry,
                                structure_minutes=structure_minutes,
                                config=cfg,
                                serial=serial,
                            )
                        )
                    )
    orders = pd.DataFrame.from_records(order_records)
    if not orders.empty:
        complete = features[features["core_windows_complete"]]
        eligible = {
            "A_0830_impulse_continuation": len(complete),
            "B_0830_false_move_reversal": len(complete),
            "C_0930_non_news_manipulation": int(
                complete["event_class"].eq("C_no_meaningful_0830").sum()
            ),
        }
        orders["eligible_session_count"] = orders["family"].map(eligible)
    return orders


def simulate_orders(
    prices: pd.DataFrame,
    orders: pd.DataFrame,
    *,
    assumed_spread_price: float,
    assumed_slippage_price_per_side: float,
    close_before_important_1000: bool,
    target_r: float = 2.0,
    config: StudyConfig | None = None,
) -> pd.DataFrame:
    """Conservative one-minute OHLC simulation with session-level cost assumptions."""

    cfg = config or StudyConfig()
    results: list[dict] = []
    for _, order in orders.iterrows():
        expiry = order["expiry"]
        if close_before_important_1000 and bool(order["important_1000_release"]):
            expiry = min(expiry, _timestamp(order["session_date"], "10:00", cfg.timezone))
        available = prices[(prices.index > order["created_at"]) & (prices.index < expiry)]
        base = order.to_dict()
        base.update(
            {
                "cost_scenario_spread_price": assumed_spread_price,
                "cost_scenario_slippage_per_side": assumed_slippage_price_per_side,
                "exit_policy": (
                    "close_before_important_1000" if close_before_important_1000 else "hold_to_expiry"
                ),
            }
        )
        if available.empty:
            results.append({**base, "order_status": "expired_unfilled", "exit_reason": "no_bars"})
            continue
        if pd.isna(order["entry_price"]):
            fill_time = available.index[0]
            entry = float(available.iloc[0]["open"])
        else:
            touches = available[
                available["low"].le(float(order["entry_price"]))
                & available["high"].ge(float(order["entry_price"]))
            ]
            if touches.empty:
                results.append({**base, "order_status": "expired_unfilled", "exit_reason": "limit_not_touched"})
                continue
            fill_time = touches.index[0]
            entry = float(order["entry_price"])
        direction = int(order["direction"])
        stop = float(order["stop_price"])
        risk = direction * (entry - stop)
        if risk <= 0:
            results.append({**base, "order_status": "invalid", "exit_reason": "non_positive_risk"})
            continue

        after_fill = prices[(prices.index >= fill_time) & (prices.index < expiry)]
        target = entry + direction * target_r * risk
        mfe_r = 0.0
        mae_r = 0.0
        times: dict[str, float | None] = {"time_to_1r_minutes": None, "time_to_1_5r_minutes": None, "time_to_2r_minutes": None}
        time_to_opposing: float | None = None
        exit_time = after_fill.index[-1]
        exit_price = float(after_fill["close"].iloc[-1])
        exit_reason = "time_expiry"
        for timestamp, bar in after_fill.iterrows():
            if direction > 0:
                favorable = (float(bar["high"]) - entry) / risk
                adverse = (float(bar["low"]) - entry) / risk
                stop_touched = float(bar["low"]) <= stop
                target_touched = float(bar["high"]) >= target
                opposing_touched = pd.notna(order["opposing_level"]) and float(bar["high"]) >= float(order["opposing_level"])
            else:
                favorable = (entry - float(bar["low"])) / risk
                adverse = (entry - float(bar["high"])) / risk
                stop_touched = float(bar["high"]) >= stop
                target_touched = float(bar["low"]) <= target
                opposing_touched = pd.notna(order["opposing_level"]) and float(bar["low"]) <= float(order["opposing_level"])
            mfe_r = max(mfe_r, favorable)
            mae_r = min(mae_r, adverse)
            elapsed = (timestamp - fill_time).total_seconds() / 60
            for threshold, key in ((1.0, "time_to_1r_minutes"), (1.5, "time_to_1_5r_minutes"), (2.0, "time_to_2r_minutes")):
                if times[key] is None and favorable >= threshold:
                    times[key] = elapsed
            if time_to_opposing is None and opposing_touched:
                time_to_opposing = elapsed
            # Conservative same-bar ordering: stop wins when both are touched.
            if stop_touched:
                exit_time, exit_price, exit_reason = timestamp, stop, "stop"
                break
            if target_touched:
                exit_time, exit_price, exit_reason = timestamp, target, f"target_{target_r:g}r"
                break
        gross_r = direction * (exit_price - entry) / risk
        spread_at_fill = prices.loc[fill_time, "spread"] if "spread" in prices else math.nan
        # A zero broker-export spread is normally a missing-value encoding, not
        # evidence of costless execution. Fall back to the declared scenario.
        observed_spread = (
            float(spread_at_fill)
            if pd.notna(spread_at_fill) and float(spread_at_fill) > 0
            else assumed_spread_price
        )
        round_trip_cost = observed_spread + 2 * assumed_slippage_price_per_side
        net_r = gross_r - round_trip_cost / risk
        results.append(
            {
                **base,
                "order_status": "filled",
                "fill_time": fill_time,
                "fill_price": entry,
                "risk_price": risk,
                "target_price": target,
                "exit_time": exit_time,
                "exit_price": exit_price,
                "exit_reason": exit_reason,
                "gross_r": gross_r,
                "observed_or_assumed_spread_price": observed_spread,
                "round_trip_cost_price": round_trip_cost,
                "net_r": net_r,
                "mfe_r": mfe_r,
                "mae_r": mae_r,
                **times,
                "time_to_opposing_liquidity_minutes": time_to_opposing,
            }
        )
    return pd.DataFrame.from_records(results)
