"""Auditable direction semantics for D005_E2."""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd


HIGH_LIQUIDITY_TAXONOMIES = frozenset(
    {
        "buy_side_liquidity",
        "equal_high_liquidity",
        "premarket_high",
    }
)
LOW_LIQUIDITY_TAXONOMIES = frozenset(
    {
        "sell_side_liquidity",
        "equal_low_liquidity",
        "premarket_low",
    }
)


def liquidity_raid_direction(taxonomy: str | None) -> int:
    """Direction into the swept pool, distinct from the expected reaction."""

    if taxonomy in HIGH_LIQUIDITY_TAXONOMIES:
        return 1
    if taxonomy in LOW_LIQUIDITY_TAXONOMIES:
        return -1
    return 0


def expected_post_sweep_direction(taxonomy: str | None) -> int:
    """Expected move away from the swept pool under frozen D005 semantics."""

    raid = liquidity_raid_direction(taxonomy)
    return -raid if raid else 0


def classify_outcome(
    *,
    candidate_type: str,
    candidate_direction: int,
    parent_direction: int,
    pre_candidate_child_direction: int,
) -> str:
    """Reproduce D005 reversal/continuation labeling without changing it."""

    if pre_candidate_child_direction not in (0, candidate_direction):
        return "reversal"
    if parent_direction == 0 and candidate_type == "liquidity_sweep":
        return "reversal"
    return "continuation"


def direction_mismatch_table(
    frame: pd.DataFrame,
    *,
    direction_columns: Iterable[str],
    groups: Iterable[str] = ("population", "mapping_variant", "outcome"),
) -> pd.DataFrame:
    """Return all pairwise observed-direction agreement diagnostics."""

    columns = list(direction_columns)
    group_columns = [column for column in groups if column in frame]
    rows: list[dict[str, object]] = []
    for left_position, left in enumerate(columns):
        if left not in frame:
            continue
        for right in columns[left_position + 1 :]:
            if right not in frame:
                continue
            subset = frame[
                frame[left].notna()
                & frame[right].notna()
                & frame[left].ne(0)
                & frame[right].ne(0)
            ].copy()
            if subset.empty:
                continue
            subset["_mismatch"] = subset[left].astype(int).ne(
                subset[right].astype(int)
            )
            subset["_sign_inversion"] = subset[left].astype(int).eq(
                -subset[right].astype(int)
            )
            grouper: str | list[str] = (
                group_columns[0]
                if len(group_columns) == 1
                else group_columns
            )
            grouped = (
                subset.groupby(grouper, dropna=False)
                if group_columns
                else [((), subset)]
            )
            for key, group in grouped:
                keys = (
                    key
                    if isinstance(key, tuple)
                    else (key,)
                    if group_columns
                    else ()
                )
                record = {
                    column: value
                    for column, value in zip(
                        group_columns, keys, strict=True
                    )
                }
                count = len(group)
                rows.append(
                    {
                        **record,
                        "left_direction": left,
                        "right_direction": right,
                        "observations": count,
                        "matches": int((~group["_mismatch"]).sum()),
                        "mismatches": int(group["_mismatch"].sum()),
                        "mismatch_rate": float(group["_mismatch"].mean()),
                        "exact_sign_inversions": int(
                            group["_sign_inversion"].sum()
                        ),
                        "sign_inversion_rate": float(
                            group["_sign_inversion"].mean()
                        ),
                    }
                )
    return pd.DataFrame.from_records(rows)

