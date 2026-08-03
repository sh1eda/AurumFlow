"""Causal, synthetic-bar rejection-block detection and relationships."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Iterable
from zoneinfo import ZoneInfo

import pandas as pd

from .config import D006Config
from .models import Direction, RejectionBlock
from .schemas import validate_bars


def _true_ranges(bars: pd.DataFrame) -> pd.Series:
    previous_close = bars["close"].shift(1)
    return pd.concat(
        [bars["high"] - bars["low"], (bars["high"] - previous_close).abs(), (bars["low"] - previous_close).abs()],
        axis=1,
    ).max(axis=1)


def _candidate_direction(
    bars: pd.DataFrame, index: int, true_ranges: pd.Series, prior_atrs: pd.Series, config: D006Config
) -> Direction | None:
    if index < max(config.atr_min_periods, config.swing_left_lookback):
        return None
    row, previous = bars.iloc[index], bars.iloc[index - 1]
    span = row.high - row.low
    prior_atr = prior_atrs.iloc[index]
    if span <= 0 or pd.isna(prior_atr) or prior_atr <= 0:
        return None
    if true_ranges.iloc[index] / prior_atr < config.candidate_tr_to_prior_atr_minimum:
        return None
    lower_body, upper_body = min(row.open, row.close), max(row.open, row.close)
    prior_lower, prior_upper = min(previous.open, previous.close), max(previous.open, previous.close)
    left = bars.iloc[index - config.swing_left_lookback:index]
    if (
        row.low < left["low"].min()
        and (lower_body - row.low) / span >= config.wick_fraction_minimum
        and row.close >= row.low + span / 2
        and row.low < prior_lower <= row.close
    ):
        return Direction.BULLISH
    if (
        row.high > left["high"].max()
        and (row.high - upper_body) / span >= config.wick_fraction_minimum
        and row.close <= row.low + span / 2
        and row.high > prior_upper >= row.close
    ):
        return Direction.BEARISH
    return None


def _is_confirmation(
    bars: pd.DataFrame, index: int, direction: Direction, true_ranges: pd.Series, prior_atrs: pd.Series,
    source_rows: pd.DataFrame, config: D006Config,
) -> bool:
    row = bars.iloc[index]
    span = row.high - row.low
    prior_atr = prior_atrs.iloc[index]
    if span <= 0 or pd.isna(prior_atr) or prior_atr <= 0:
        return False
    directional = row.close > row.open if direction is Direction.BULLISH else row.close < row.open
    beyond = source_rows[["open", "close"]].max(axis=1).max() if direction is Direction.BULLISH else source_rows[["open", "close"]].min(axis=1).min()
    close_beyond = row.close > beyond if direction is Direction.BULLISH else row.close < beyond
    does_not_cross_distal = row.low >= source_rows["low"].min() if direction is Direction.BULLISH else row.high <= source_rows["high"].max()
    return (
        directional
        and abs(row.close - row.open) / span >= config.confirmation_body_fraction_minimum
        and true_ranges.iloc[index] / prior_atr >= config.confirmation_tr_to_prior_atr_minimum
        and close_beyond
        and does_not_cross_distal
    )


def _session_label(availability: pd.Timestamp) -> str:
    local = availability.tz_convert(ZoneInfo("America/New_York"))
    minute = local.hour * 60 + local.minute
    if minute >= 18 * 60:
        return "asia"
    if minute < 8 * 60 + 30:
        return "premarket"
    if minute < 12 * 60:
        return "ny_observation"
    if minute < 17 * 60:
        return "ny_afternoon"
    return "maintenance"


def _trading_date(availability: pd.Timestamp) -> str:
    local = availability.tz_convert(ZoneInfo("America/New_York"))
    named_date = local.date()
    if local.hour >= 18:
        named_date += pd.Timedelta(days=1)
    return named_date.isoformat()


def _block_id(config: D006Config, definition: str, direction: Direction, bar_ids: tuple[str, ...], expansion_bar_id: str, creation: pd.Timestamp, availability: pd.Timestamp, distal: float, midpoint: float, proximal: float) -> str:
    material = json.dumps(
        (
            config.version,
            definition,
            config.timeframe,
            direction.value,
            bar_ids,
            expansion_bar_id,
            creation.isoformat(),
            availability.isoformat(),
            float(distal).hex(),
            float(midpoint).hex(),
            float(proximal).hex(),
        ),
        separators=(",", ":"),
    )
    return sha256(material.encode("utf-8")).hexdigest()[:16]


def _build_block(bars: pd.DataFrame, source_indices: tuple[int, ...], confirmation_index: int, direction: Direction, definition: str, true_ranges: pd.Series, prior_atrs: pd.Series, config: D006Config) -> RejectionBlock:
    source = bars.iloc[list(source_indices)]
    if direction is Direction.BULLISH:
        distal = float(source["low"].min())
        proximal = float(source[["open", "close"]].min(axis=1).max())
    else:
        proximal = float(source[["open", "close"]].max(axis=1).min())
        distal = float(source["high"].max())
    bar_ids = tuple(str(value) for value in source["bar_id"])
    confirmation = bars.iloc[confirmation_index]["available_at"]
    expansion_bar_id = str(bars.iloc[confirmation_index]["bar_id"])
    midpoint = (distal + proximal) / 2
    block_range = abs(proximal - distal)
    normalized_range = float(block_range / prior_atrs.iloc[source_indices[-1]])
    preavailability = any(
        row.low <= max(distal, proximal) and row.high >= min(distal, proximal)
        for _, row in bars.iloc[source_indices[-1] + 1 : confirmation_index + 1].iterrows()
    )
    return RejectionBlock(
        block_id=_block_id(config, definition, direction, bar_ids, expansion_bar_id, source.index[-1], confirmation, distal, midpoint, proximal),
        definition_name=definition,
        direction=direction,
        timeframe=config.timeframe,
        source_bar_ids=bar_ids,
        expansion_bar_id=expansion_bar_id,
        creation_timestamp=source.index[-1],
        confirmation_timestamp=confirmation,
        causal_availability=bars.iloc[confirmation_index]["available_at"],
        distal=distal,
        proximal=proximal,
        midpoint=midpoint,
        range=block_range,
        normalized_range=normalized_range,
        session=_session_label(confirmation),
        trading_date=_trading_date(confirmation),
        context_keys=(),
        preavailability_interaction=preavailability,
    )


def _relationship_sort_key(block: RejectionBlock, registry_order: dict[str, int] | None = None) -> tuple[object, ...]:
    direction_order = 0 if block.direction is Direction.BEARISH else 1
    return (
        block.causal_availability,
        (registry_order or {}).get(block.definition_name, 0),
        block.creation_timestamp,
        direction_order,
        block.source_bar_ids,
        block.block_id,
    )


def _attach_relationships(blocks: Iterable[RejectionBlock], registry_order: dict[str, int] | None = None) -> list[RejectionBlock]:
    ordered = sorted(blocks, key=lambda block: _relationship_sort_key(block, registry_order))
    groups: list[list[RejectionBlock]] = []
    for block in ordered:
        lower, upper = sorted((block.distal, block.proximal))
        connected = [group for group in groups if any(lower <= max(item.distal, item.proximal) and upper >= min(item.distal, item.proximal) for item in group)]
        if not connected:
            groups.append([block])
        else:
            combined = [item for group in connected for item in group] + [block]
            groups = [group for group in groups if group not in connected] + [combined]
    assigned: dict[str, RejectionBlock] = {}
    for group in sorted(groups, key=lambda group: min(_relationship_sort_key(item, registry_order) for item in group)):
        group_id = "overlap-" + sha256("|".join(sorted(item.block_id for item in group)).encode("utf-8")).hexdigest()[:16]
        for block in sorted(group, key=lambda item: _relationship_sort_key(item, registry_order)):
            parents = [
                candidate for candidate in group
                if candidate.direction is block.direction
                and _relationship_sort_key(candidate, registry_order) < _relationship_sort_key(block, registry_order)
                and min(candidate.distal, candidate.proximal) <= min(block.distal, block.proximal)
                and max(candidate.distal, candidate.proximal) >= max(block.distal, block.proximal)
            ]
            parent = min(parents, key=lambda item: _relationship_sort_key(item, registry_order)).block_id if parents else None
            assigned[block.block_id] = block.with_relationships(group_id, parent)
    return [assigned[block.block_id] for block in ordered]


def detect_rejection_blocks(bars: pd.DataFrame, evaluation_at: object, config: D006Config = D006Config()) -> list[RejectionBlock]:
    """Detect only causally confirmed structures from already closed synthetic bars."""

    bars = validate_bars(bars, evaluation_at)
    true_ranges = _true_ranges(bars)
    prior_atrs = true_ranges.shift(1).rolling(config.atr_period, min_periods=config.atr_min_periods).mean()
    def candidate_direction(index: int) -> Direction | None:
        start = index - config.swing_left_lookback
        if start < 0 or not (
            bars.index[index] - bars.index[start]
            == pd.Timedelta(minutes=config.bar_minutes * config.swing_left_lookback)
        ):
            return None
        return _candidate_direction(bars, index, true_ranges, prior_atrs, config)

    directions = [candidate_direction(index) for index in range(len(bars))]
    detected: list[RejectionBlock] = []
    for definition_order, definition in enumerate(config.definitions):
        width = definition.rejection_bar_count
        for start in range(len(bars) - width):
            source_indices = tuple(range(start, start + width))
            direction = directions[start]
            if direction is None or any(directions[position] is not direction for position in source_indices):
                continue
            source = bars.iloc[list(source_indices)]
            confirmation_index = next(
                (
                    position for position in range(start + width, min(start + width + config.confirmation_bars, len(bars)))
                    if bars.index[position] - bars.index[source_indices[-1]]
                    == pd.Timedelta(minutes=config.bar_minutes * (position - source_indices[-1]))
                    and _is_confirmation(bars, position, direction, true_ranges, prior_atrs, source, config)
                ),
                None,
            )
            if confirmation_index is not None:
                detected.append(_build_block(bars, source_indices, confirmation_index, direction, definition.name, true_ranges, prior_atrs, config))
    unique = {block.block_id: block for block in detected}
    registry_order = {definition.name: index for index, definition in enumerate(config.definitions)}
    return _attach_relationships(unique.values(), registry_order)
