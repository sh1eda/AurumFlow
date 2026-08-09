"""Read-only, causal joins to the frozen D004/D005 research artifacts.

This module deliberately has no default artifact paths and performs no work at
import time.  Callers must supply a verified artifact/manifest pair explicitly.
Only the listed structural columns are projected from Parquet; outcome and
price-path columns are neither requested nor normalized here.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping

import pandas as pd


SOURCE_END = pd.Timestamp("2026-01-01T00:00:00Z")

# These are intentionally exact projections.  Do not replace them with a
# whole-file read: D004 and D005 artifacts also contain retrospective metrics.
D004_CAUSAL_COLUMNS = (
    "trading_date",
    "high_sweep",
    "low_sweep",
    "high_reentry",
    "low_reentry",
    "high_reentry_time",
    "low_reentry_time",
)
D005_E1_CAUSAL_COLUMNS = (
    "snapshot_id",
    "evaluation_at",
    "mapping_name",
    "mapping_variant",
    "optional_1m_refinement",
    "parent_timeframe",
    "reaction_timeframe",
    "state",
    "direction",
    "volatility_regime",
    "volatility_ratio",
)
D005_E3_CAUSAL_COLUMNS = (
    "anchor_id",
    "anchor_event_id",
    "anchor_type",
    "anchor_at",
    "direction",
    "main_scope_eligible",
    "anchor_causally_observable",
    "anchor_selected_using_later_completion",
    "anchor_price_override",
)
OPTIONAL_D005_E3_CAUSAL_COLUMNS = ("invalidated_at",)

INTERACTION_NAMES = (
    "rb_alone",
    "aligned_d005_context",
    "after_d004_manipulation",
    "frozen_liquidity_sweep",
    "displacement_confirmation",
    "refinement_confirmation",
    "against_d005_context_negative_control",
)
REDUNDANCY_ANCHOR_TYPES = (
    "named_liquidity_sweep",
    "mss_body_close_confirmation",
    "displacement_confirmation",
    "refinement_array_creation",
    "first_aligned_raw_fvg_creation",
    "first_context_qualified_fvg_creation",
)


class FrozenContextError(ValueError):
    """Raised when a frozen artifact cannot be authenticated or normalized."""


@dataclass(frozen=True)
class FrozenArtifact:
    """One immutable structural artifact and the manifest that records its hash."""

    name: str
    parquet_path: Path
    manifest_path: Path

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("artifact name is required")


@dataclass(frozen=True)
class FrozenContextTables:
    """Normalized, outcome-free structural tables used by D006 joins."""

    d004_events: pd.DataFrame
    snapshots: pd.DataFrame
    anchors: pd.DataFrame


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_hashes(value: object, *, artifact: FrozenArtifact) -> set[str]:
    """Return hashes in manifest records that identify this exact artifact."""

    matches: set[str] = set()
    target_names = {artifact.name, artifact.parquet_path.name, str(artifact.parquet_path)}
    try:
        target_names.add(str(artifact.parquet_path.relative_to(artifact.manifest_path.parent)))
    except ValueError:
        pass

    def visit(node: object, key: object | None = None) -> None:
        if isinstance(node, Mapping):
            digest = node.get("sha256")
            identity = next(
                (
                    node.get(field)
                    for field in ("path", "file", "name", "artifact")
                    if node.get(field) is not None
                ),
                None,
            )
            if isinstance(digest, str) and (
                str(key) in target_names
                or identity is not None and str(identity) in target_names
            ):
                matches.add(digest.lower())
            for child_key, child in node.items():
                visit(child, child_key)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return matches


def verify_artifact_bytes(artifact: FrozenArtifact) -> str:
    """Verify bytes before a Parquet reader is allowed to inspect its schema."""

    if not artifact.parquet_path.is_file() or not artifact.manifest_path.is_file():
        raise FrozenContextError("artifact and manifest must both exist")
    try:
        manifest = json.loads(artifact.manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FrozenContextError("manifest must be readable JSON") from error
    expected = _manifest_hashes(manifest, artifact=artifact)
    if len(expected) != 1:
        raise FrozenContextError("manifest must contain one unambiguous artifact SHA-256")
    actual = _sha256_file(artifact.parquet_path)
    if actual != next(iter(expected)):
        raise FrozenContextError("artifact SHA-256 does not match its manifest")
    return actual


def _read_causal_parquet(artifact: FrozenArtifact, columns: tuple[str, ...]) -> pd.DataFrame:
    verify_artifact_bytes(artifact)
    # Verification is intentionally before this projected read.
    return pd.read_parquet(artifact.parquet_path, columns=list(columns))


def _parquet_columns(artifact: FrozenArtifact) -> set[str]:
    """Read Parquet metadata only after byte verification, never any rows."""

    try:
        from pyarrow.parquet import ParquetFile
    except ImportError as error:  # pragma: no cover - pandas test dependency supplies pyarrow
        raise FrozenContextError("pyarrow is required for causal Parquet projection") from error
    verify_artifact_bytes(artifact)
    return set(ParquetFile(artifact.parquet_path).schema.names)


def _utc(values: pd.Series, name: str) -> pd.Series:
    result = pd.to_datetime(values, utc=True, errors="coerce")
    if result.isna().any():
        raise FrozenContextError(f"{name} must contain explicit UTC timestamps")
    return result


def _bool(values: pd.Series, name: str) -> pd.Series:
    if values.isna().any() or not values.map(lambda value: type(value) is bool).all():
        raise FrozenContextError(f"{name} must be non-null booleans")
    return values.astype(bool)


def _direction(values: pd.Series, name: str) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.isna().any() or not numeric.isin((-1, 1)).all():
        raise FrozenContextError(f"{name} must contain only -1 or 1")
    return numeric.astype("int8")


def _before_2026(frame: pd.DataFrame, timestamp_column: str) -> pd.DataFrame:
    return frame.loc[frame[timestamp_column].lt(SOURCE_END)].copy()


def load_d004_events(artifact: FrozenArtifact) -> pd.DataFrame:
    """Normalize D004 completed sweep/re-entry events with conservative timing."""

    frame = _read_causal_parquet(artifact, D004_CAUSAL_COLUMNS)
    missing = set(D004_CAUSAL_COLUMNS) - set(frame.columns)
    if missing:
        raise FrozenContextError(f"D004 causal columns missing: {sorted(missing)}")
    high_sweep = _bool(frame["high_sweep"], "high_sweep")
    low_sweep = _bool(frame["low_sweep"], "low_sweep")
    high_reentry = _bool(frame["high_reentry"], "high_reentry")
    low_reentry = _bool(frame["low_reentry"], "low_reentry")
    dates = pd.to_datetime(frame["trading_date"], errors="coerce")
    if dates.isna().any():
        raise FrozenContextError("D004 trading_date must be valid")
    rows: list[dict[str, object]] = []
    for index, record in frame.iterrows():
        trading_date = dates.at[index].date().isoformat()
        for side, direction, swept, reentered in (
            ("high", -1, high_sweep.at[index], high_reentry.at[index]),
            ("low", 1, low_sweep.at[index], low_reentry.at[index]),
        ):
            if not (swept and reentered):
                continue
            event_at = pd.to_datetime(record[f"{side}_reentry_time"], utc=True, errors="coerce")
            if pd.isna(event_at):
                raise FrozenContextError("D004 completed re-entry requires a timestamp")
            # D004 records a one-minute bar's left edge.  Its close is the first
            # causally usable instant, so retain a full one-minute delay.
            available_at = event_at + pd.Timedelta(minutes=1)
            rows.append(
                {
                    "context_id": f"d004:{trading_date}:{side}",
                    "trading_date": trading_date,
                    "direction": direction,
                    "event_at": event_at,
                    "available_at": available_at,
                    "feature": "d004_sweep_reentry_v1",
                }
            )
    result = pd.DataFrame.from_records(
        rows,
        columns=("context_id", "trading_date", "direction", "event_at", "available_at", "feature"),
    )
    if result.empty:
        return result
    result = _before_2026(result, "available_at")
    return result.sort_values(["available_at", "context_id"], kind="mergesort").reset_index(drop=True)


def load_d005_snapshots(artifact: FrozenArtifact) -> pd.DataFrame:
    """Normalize only reaction-confirmed D005 1h_5m snapshots."""

    frame = _read_causal_parquet(artifact, D005_E1_CAUSAL_COLUMNS)
    missing = set(D005_E1_CAUSAL_COLUMNS) - set(frame.columns)
    if missing:
        raise FrozenContextError(f"D005 E1 causal columns missing: {sorted(missing)}")
    result = frame.loc[
        frame["state"].eq("reaction_confirmed")
        & frame["mapping_name"].eq("1h_5m_1m")
        & frame["mapping_variant"].eq("1h_5m")
        & ~_bool(frame["optional_1m_refinement"], "optional_1m_refinement")
        & frame["parent_timeframe"].eq("1H")
        & frame["reaction_timeframe"].eq("5min")
    ].copy()
    result["context_id"] = result["snapshot_id"].astype(str)
    if result["context_id"].eq("").any() or result["context_id"].duplicated().any():
        raise FrozenContextError("D005 snapshot_id must be non-empty and unique")
    result["context_at"] = _utc(result["evaluation_at"], "D005 evaluation_at")
    result["available_at"] = result["context_at"]
    result["direction"] = _direction(result["direction"], "D005 direction")
    result = _before_2026(result, "available_at")
    result["feature"] = "d005_e1_reaction_confirmed_1h_5m_v1"
    return result.loc[:, (
        "context_id", "context_at", "available_at", "direction", "volatility_regime", "volatility_ratio", "feature"
    )].sort_values(["available_at", "context_id"], kind="mergesort").reset_index(drop=True)


def load_d005_anchors(artifact: FrozenArtifact) -> pd.DataFrame:
    """Normalize causal E3 anchors without later-completion conditioning."""

    available_columns = _parquet_columns(artifact)
    projection = D005_E3_CAUSAL_COLUMNS + tuple(
        name for name in OPTIONAL_D005_E3_CAUSAL_COLUMNS if name in available_columns
    )
    frame = _read_causal_parquet(artifact, projection)
    missing = set(D005_E3_CAUSAL_COLUMNS) - set(frame.columns)
    if missing:
        raise FrozenContextError(f"D005 E3 causal columns missing: {sorted(missing)}")
    allowed = set(REDUNDANCY_ANCHOR_TYPES) | {
        "refinement_array_first_interaction",
    }
    allowed.update(
        value for value in frame["anchor_type"].dropna().astype(str).unique()
        if value.startswith("qualifying_ob_") and value.endswith("_creation")
    )
    result = frame.loc[frame["anchor_type"].isin(allowed)].copy()
    result = result.loc[
        _bool(result["main_scope_eligible"], "main_scope_eligible")
        & _bool(result["anchor_causally_observable"], "anchor_causally_observable")
        & ~_bool(result["anchor_selected_using_later_completion"], "anchor_selected_using_later_completion")
    ].copy()
    result["context_id"] = result["anchor_id"].astype(str)
    if result["context_id"].eq("").any() or result["context_id"].duplicated().any():
        raise FrozenContextError("D005 anchor_id must be non-empty and unique")
    result["context_at"] = _utc(result["anchor_at"], "D005 anchor_at")
    result["available_at"] = result["context_at"]
    result["direction"] = _direction(result["direction"], "D005 anchor direction")
    result["anchor_price"] = pd.to_numeric(result["anchor_price_override"], errors="coerce")
    if "invalidated_at" in result:
        result["invalidated_at"] = pd.to_datetime(
            result["invalidated_at"], utc=True, errors="coerce"
        )
        result["invalidation_observable"] = True
    else:
        result["invalidated_at"] = pd.Series(
            pd.NaT, index=result.index, dtype="datetime64[ns, UTC]"
        )
        result["invalidation_observable"] = False
    result = _before_2026(result, "available_at")
    result["feature"] = "d005_e3_causal_anchor_v1"
    return result.loc[:, (
        "context_id", "anchor_event_id", "anchor_type", "context_at", "available_at", "invalidated_at", "invalidation_observable", "direction", "anchor_price", "feature"
    )].sort_values(["available_at", "context_id"], kind="mergesort").reset_index(drop=True)


def load_frozen_context(
    d004_daily_events: FrozenArtifact,
    d005_context_snapshots: FrozenArtifact,
    d005_anchor_events: FrozenArtifact,
) -> FrozenContextTables:
    """Authenticate then load the three required frozen context artifacts."""

    return FrozenContextTables(
        d004_events=load_d004_events(d004_daily_events),
        snapshots=load_d005_snapshots(d005_context_snapshots),
        anchors=load_d005_anchors(d005_anchor_events),
    )


def _stable_key(feature: str, row: Mapping[str, object], agreement: str) -> str:
    return "|".join((feature, str(row["context_id"]), pd.Timestamp(row["context_at"] if "context_at" in row else row["event_at"]).isoformat(), pd.Timestamp(row["available_at"]).isoformat(), agreement))


def _latest_unambiguous(
    frame: pd.DataFrame,
    *,
    at: pd.Timestamp,
    timestamp: str = "available_at",
    strict: bool = False,
) -> tuple[pd.Series | None, str | None]:
    mask = frame[timestamp].lt(at) if strict else frame[timestamp].le(at)
    candidates = frame.loc[mask]
    if candidates.empty:
        return None, "missing"
    latest_at = candidates[timestamp].max()
    latest = candidates.loc[candidates[timestamp].eq(latest_at)]
    if latest["direction"].nunique() != 1:
        return None, "ambiguous_opposite_direction"
    return latest.sort_values("context_id", kind="mergesort").iloc[0], None


def _anchor_subset(anchors: pd.DataFrame, kind: str) -> pd.DataFrame:
    if kind == "liquidity":
        return anchors.loc[anchors["anchor_type"].eq("named_liquidity_sweep")]
    if kind == "displacement":
        return anchors.loc[anchors["anchor_type"].eq("displacement_confirmation")]
    if kind == "refinement":
        return anchors.loc[anchors["anchor_type"].eq("refinement_array_creation")]
    return anchors.iloc[0:0]


def join_block_contexts(blocks: pd.DataFrame, context: FrozenContextTables) -> pd.DataFrame:
    """Attach fixed interaction eligibility using causal timestamps only.

    The returned data frame is intentionally structural.  ``unavailable_reasons``
    makes missing or ambiguous evidence explicit, and no interaction is guessed.
    """

    required = {"block_id", "direction", "causal_availability", "first_touch_timestamp", "trading_date", "expansion_bar_id"}
    missing = required - set(blocks.columns)
    if missing:
        raise FrozenContextError(f"block columns missing: {sorted(missing)}")
    result_rows: list[dict[str, object]] = []
    for block in blocks.to_dict("records"):
        availability = pd.to_datetime(block["causal_availability"], utc=True, errors="coerce")
        touch = pd.to_datetime(block["first_touch_timestamp"], utc=True, errors="coerce")
        if pd.isna(availability) or pd.isna(touch) or touch < availability:
            raise FrozenContextError("block availability and first touch must be causal UTC timestamps")
        if availability >= SOURCE_END:
            raise FrozenContextError("D006 context joins exclude 2026 and later blocks")
        direction = int(block["direction"])
        if direction not in (-1, 1):
            raise FrozenContextError("block direction must be -1 or 1")
        row: dict[str, object] = {"block_id": str(block["block_id"]), "rb_alone": True}
        unavailable: list[str] = []

        snapshot, issue = _latest_unambiguous(context.snapshots, at=availability)
        if issue:
            unavailable.append(f"d005_context:{issue}")
            row["aligned_d005_context"] = False
            row["against_d005_context_negative_control"] = False
            row["d005_context_key"] = None
        else:
            agreement = "agree" if int(snapshot["direction"]) == direction else "disagree"
            row["d005_context_key"] = _stable_key("d005_context", snapshot, agreement)
            row["aligned_d005_context"] = agreement == "agree"
            row["against_d005_context_negative_control"] = agreement == "disagree"

        same_date = context.d004_events.loc[context.d004_events["trading_date"].eq(str(block["trading_date"]))]
        d004, issue = _latest_unambiguous(same_date, at=availability, strict=True)
        prior_directions = same_date.loc[same_date["available_at"].lt(availability), "direction"].unique()
        if len(prior_directions) > 1:
            d004, issue = None, "conflicting_same_trading_date"
        if issue:
            unavailable.append(f"d004:{issue}")
            row["after_d004_manipulation"] = False
            row["d004_context_key"] = None
        else:
            agreement = "agree" if int(d004["direction"]) == direction else "disagree"
            row["d004_context_key"] = _stable_key("d004", d004, agreement)
            row["after_d004_manipulation"] = agreement == "agree"

        liquidity_candidates = _anchor_subset(context.anchors, "liquidity")
        # Invalidation is considered only when the frozen artifact actually
        # records one.  An equal timestamp is fail-closed rather than ordered
        # optimistically against the block availability.
        liquidity_candidates = liquidity_candidates.loc[
            liquidity_candidates["invalidation_observable"]
            & (
                liquidity_candidates["invalidated_at"].isna()
                | liquidity_candidates["invalidated_at"].gt(availability)
            )
        ]
        liquidity, issue = _latest_unambiguous(liquidity_candidates, at=availability)
        if issue:
            unavailable.append(f"liquidity:{issue}")
            row["frozen_liquidity_sweep"] = False
            row["liquidity_context_key"] = None
        else:
            agreement = "agree" if int(liquidity["direction"]) == direction else "disagree"
            row["liquidity_context_key"] = _stable_key("liquidity", liquidity, agreement)
            row["frozen_liquidity_sweep"] = agreement == "agree"

        displacement = _anchor_subset(context.anchors, "displacement")
        displacement = displacement.loc[
            displacement["available_at"].le(availability)
            & displacement["available_at"].ge(availability - pd.Timedelta(minutes=60))
            & ~displacement["context_id"].eq(str(block["expansion_bar_id"]))
            & ~displacement["anchor_event_id"].astype(str).eq(str(block["expansion_bar_id"]))
        ]
        displacement, issue = _latest_unambiguous(displacement, at=availability)
        if issue:
            unavailable.append(f"displacement:{issue}")
            row["displacement_confirmation"] = False
            row["displacement_context_key"] = None
        else:
            agreement = "agree" if int(displacement["direction"]) == direction else "disagree"
            row["displacement_context_key"] = _stable_key("displacement", displacement, agreement)
            row["displacement_confirmation"] = agreement == "agree"

        refinement, issue = _latest_unambiguous(_anchor_subset(context.anchors, "refinement"), at=touch)
        if issue:
            unavailable.append(f"refinement:{issue}")
            row["refinement_confirmation"] = False
            row["refinement_context_key"] = None
        else:
            agreement = "agree" if int(refinement["direction"]) == direction else "disagree"
            row["refinement_context_key"] = _stable_key("refinement", refinement, agreement)
            row["refinement_confirmation"] = agreement == "agree"

        # Redundancy is registered as a local causal-time/price-zone overlap,
        # not the unbounded history of every earlier anchor.  Keeping the same
        # frozen +/-60 minute audit window used by the downstream overlap
        # analysis also prevents a quadratic export of irrelevant keys.
        redundancy = context.anchors.loc[
            context.anchors["available_at"].le(availability)
            & context.anchors["available_at"].ge(availability - pd.Timedelta(minutes=60))
        ]
        row["redundancy_context_keys"] = tuple(
            _stable_key(str(item.anchor_type), item._asdict(), "observed")
            for item in redundancy.sort_values(["available_at", "context_id"], kind="mergesort").itertuples(index=False)
        )
        row["unavailable_reasons"] = tuple(sorted(unavailable))
        row["context_available"] = not unavailable
        result_rows.append(row)
    return pd.DataFrame.from_records(result_rows).sort_values("block_id", kind="mergesort").reset_index(drop=True)


def interaction_registry() -> tuple[str, ...]:
    """Return the immutable D006 interaction IDs without discovery or tuning."""

    from .config import FIXED_INTERACTIONS

    configured = tuple(item.name for item in FIXED_INTERACTIONS)
    if configured != INTERACTION_NAMES:
        raise FrozenContextError("D006 interaction registry drifted from its preregistration")
    return configured
