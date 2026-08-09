"""Causal D007 OTE construction from synthetic/frozen upstream inputs only."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Iterable

import pandas as pd

from .config import D007Config, GeometryDefinition
from .models import (
    ClosedBar,
    Direction,
    FrozenDisplacementAnchor,
    OTERange,
    attach_relationships,
    stable_id,
)


def _ordered_bars(bars: Iterable[ClosedBar]) -> tuple[ClosedBar, ...]:
    ordered = tuple(sorted(bars, key=lambda item: (item.available_at, item.bar_id)))
    if len({item.bar_id for item in ordered}) != len(ordered):
        raise ValueError("D007 source bar IDs must be unique")
    if len({item.available_at for item in ordered}) != len(ordered):
        raise ValueError("D007 source bar availability timestamps must be unique")
    return ordered


def _level(
    origin: float,
    endpoint: float,
    direction: Direction,
    depth: float,
) -> float:
    return endpoint - int(direction) * depth * abs(endpoint - origin)


def construct_ote_ranges(
    anchor: FrozenDisplacementAnchor,
    bars: Iterable[ClosedBar],
    config: D007Config = D007Config(),
) -> tuple[OTERange, ...]:
    """Build the fixed geometry family without reading a later price.

    The origin is supplied by the latest frozen, already-confirmed opposite
    swing. The endpoint is the furthest directional extreme from the D005
    displacement creation bar through its frozen availability timestamp. Bars
    after that timestamp are discarded before any OHLC field is inspected.
    """

    if anchor.mapping_name != config.upstream_mapping:
        raise ValueError("upstream mapping does not match frozen D007 primary")
    ordered = _ordered_bars(bars)
    causal = tuple(
        bar
        for bar in ordered
        if anchor.displacement_created_at <= bar.opened_at
        and bar.available_at <= anchor.displacement_available_at
    )
    if not causal:
        raise ValueError("D007 range requires causal displacement bars")
    if causal[0].opened_at != anchor.displacement_created_at:
        raise ValueError("displacement creation bar is missing")
    if causal[-1].available_at != anchor.displacement_available_at:
        raise ValueError("displacement confirmation sequence is incomplete")
    if any(not bar.is_complete for bar in causal):
        raise ValueError("D007 range construction requires complete closed bars")
    expected_duration = pd.Timedelta(minutes=config.bar_minutes)
    if any(bar.available_at - bar.opened_at != expected_duration for bar in causal):
        raise ValueError("D007 range construction requires exact five-minute bars")
    if any(
        current.opened_at - previous.opened_at != expected_duration
        for previous, current in zip(causal, causal[1:])
    ):
        raise ValueError("displacement confirmation sequence has a missing bar")

    endpoint_bar = (
        max(causal, key=lambda item: (item.high, -item.opened_at.value))
        if anchor.direction == Direction.BULLISH
        else min(causal, key=lambda item: (item.low, item.opened_at.value))
    )
    endpoint = endpoint_bar.high if anchor.direction == Direction.BULLISH else endpoint_bar.low
    if int(anchor.direction) * (endpoint - anchor.origin_price) <= 0:
        raise ValueError("upstream impulse has no positive directional magnitude")

    ranges: list[OTERange] = []
    for geometry in config.geometries:
        ranges.append(_construct_geometry(anchor, causal, endpoint_bar, endpoint, geometry, config))
    return tuple(ranges)


def _construct_geometry(
    anchor: FrozenDisplacementAnchor,
    causal: tuple[ClosedBar, ...],
    endpoint_bar: ClosedBar,
    endpoint: float,
    geometry: GeometryDefinition,
    config: D007Config,
) -> OTERange:
    proximal = _level(anchor.origin_price, endpoint, anchor.direction, geometry.proximal_depth)
    reference = _level(anchor.origin_price, endpoint, anchor.direction, geometry.reference_depth)
    distal = _level(anchor.origin_price, endpoint, anchor.direction, geometry.distal_depth)
    equilibrium = _level(anchor.origin_price, endpoint, anchor.direction, 0.50)
    zone_low, zone_high = sorted((proximal, distal))
    preavailability = any(
        bar.opened_at > endpoint_bar.opened_at
        and bar.low <= zone_high
        and bar.high >= zone_low
        for bar in causal
    )
    range_id = stable_id(
        config.version,
        anchor.upstream_event_id,
        geometry.geometry_id,
        int(anchor.direction),
        float(anchor.origin_price).hex(),
        float(endpoint).hex(),
        anchor.origin_swing_at.isoformat(),
        endpoint_bar.opened_at.isoformat(),
        anchor.displacement_available_at.isoformat(),
        *(item.bar_id for item in causal),
    )
    return OTERange(
        range_id=range_id,
        upstream_event_id=anchor.upstream_event_id,
        geometry_id=geometry.geometry_id,
        direction=anchor.direction,
        origin_price=anchor.origin_price,
        endpoint_price=endpoint,
        origin_at=anchor.origin_swing_at,
        origin_available_at=anchor.origin_confirmed_at,
        endpoint_at=endpoint_bar.opened_at,
        range_available_at=anchor.displacement_available_at,
        proximal=proximal,
        reference=reference,
        distal=distal,
        equilibrium=equilibrium,
        zone_low=zone_low,
        zone_high=zone_high,
        invalidation_price=anchor.origin_price,
        expiry_deadline=anchor.displacement_available_at
        + timedelta(hours=config.lifecycle_expiry_hours),
        source_bar_ids=tuple(item.bar_id for item in causal),
        preavailability_interaction=preavailability,
    )


def deduplicate_ranges(
    ranges: Iterable[OTERange],
) -> tuple[tuple[OTERange, ...], tuple[OTERange, ...]]:
    """Keep one exact event/geometry object and preserve distinct fixed geometries."""

    ordered = sorted(
        ranges,
        key=lambda item: (
            item.upstream_event_id,
            item.geometry_id,
            item.range_available_at,
            item.range_id,
        ),
    )
    selected: list[OTERange] = []
    excluded: list[OTERange] = []
    seen: dict[tuple[str, str], OTERange] = {}
    for item in ordered:
        key = (item.upstream_event_id, item.geometry_id)
        prior = seen.get(key)
        if prior is None:
            seen[key] = item
            selected.append(item)
        elif prior == item:
            excluded.append(item)
        else:
            raise ValueError("conflicting reconstruction for one upstream event/geometry")
    return tuple(selected), tuple(excluded)


def deduplicate_primary_overlaps(
    ranges: Iterable[OTERange],
    config: D007Config = D007Config(),
) -> tuple[tuple[OTERange, ...], tuple[OTERange, ...]]:
    """Retain earliest primary-band object per same-direction overlap group."""

    primary_geometry = next(
        item.geometry_id for item in config.geometries if item.role == "primary"
    )
    primary = [item for item in ranges if item.geometry_id == primary_geometry]
    related = attach_relationships(primary)
    ordered = sorted(
        related,
        key=lambda item: (
            int(item.direction),
            item.overlap_group_id or item.range_id,
            item.range_available_at,
            item.range_id,
        ),
    )
    selected: list[OTERange] = []
    excluded: list[OTERange] = []
    seen: set[tuple[Direction, str]] = set()
    for item in ordered:
        key = (item.direction, item.overlap_group_id or item.range_id)
        if key in seen:
            excluded.append(item)
        else:
            seen.add(key)
            selected.append(item)
    return tuple(selected), tuple(excluded)


def no_range_extension_after_availability(
    original: OTERange,
    proposed_endpoint: float,
) -> OTERange:
    """Fail closed if a caller attempts to move an available D007 range."""

    if proposed_endpoint != original.endpoint_price:
        raise ValueError("D007 forbids range extension after causal availability")
    return replace(original)
