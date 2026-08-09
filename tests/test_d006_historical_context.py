from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pandas as pd
import pytest

from research.d006_rejection_block_research.context import (
    D004_CAUSAL_COLUMNS,
    D005_E1_CAUSAL_COLUMNS,
    D005_E3_CAUSAL_COLUMNS,
    FrozenArtifact,
    FrozenContextError,
    FrozenContextTables,
    interaction_registry,
    join_block_contexts,
    load_frozen_context,
)


def _write_artifact(tmp_path: Path, name: str, frame: pd.DataFrame) -> FrozenArtifact:
    parquet = tmp_path / name
    frame.to_parquet(parquet, index=False)
    digest = sha256(parquet.read_bytes()).hexdigest()
    manifest = tmp_path / f"{name}.manifest.json"
    manifest.write_text(json.dumps({"files": [{"path": name, "sha256": digest}]}), encoding="utf-8")
    return FrozenArtifact(name=name, parquet_path=parquet, manifest_path=manifest)


def _artifacts(tmp_path: Path) -> tuple[FrozenArtifact, FrozenArtifact, FrozenArtifact]:
    d004 = _write_artifact(tmp_path, "daily_events.parquet", pd.DataFrame([{
        "trading_date": "2025-01-02", "high_sweep": True, "low_sweep": False,
        "high_reentry": True, "low_reentry": False,
        "high_reentry_time": "2025-01-02T10:00:00Z", "low_reentry_time": None,
        "horizon_60m_return": 999.0,
    }]))
    snapshots = _write_artifact(tmp_path, "context_snapshots.parquet", pd.DataFrame([{
        "snapshot_id": "snapshot-a", "evaluation_at": "2025-01-02T10:02:00Z",
        "mapping_name": "1h_5m_1m", "mapping_variant": "1h_5m",
        "optional_1m_refinement": False,
        "parent_timeframe": "1H", "reaction_timeframe": "5min",
        "state": "reaction_confirmed", "direction": -1,
        "volatility_regime": "normal", "volatility_ratio": 1.0,
        "forward_return_60m": 999.0,
    }]))
    anchors = _write_artifact(tmp_path, "anchor_events.parquet", pd.DataFrame([
        {"anchor_id": "liq-a", "anchor_event_id": "event-liq", "anchor_type": "named_liquidity_sweep", "anchor_at": "2025-01-02T10:03:00Z", "direction": -1, "main_scope_eligible": True, "anchor_causally_observable": True, "anchor_selected_using_later_completion": False, "anchor_price_override": 101.5, "invalidated_at": None, "forward_return_60m": 999.0},
        {"anchor_id": "disp-a", "anchor_event_id": "event-disp", "anchor_type": "displacement_confirmation", "anchor_at": "2025-01-02T10:04:00Z", "direction": -1, "main_scope_eligible": True, "anchor_causally_observable": True, "anchor_selected_using_later_completion": False, "anchor_price_override": None, "forward_return_60m": 999.0},
        {"anchor_id": "ref-a", "anchor_event_id": "event-ref", "anchor_type": "refinement_array_creation", "anchor_at": "2025-01-02T10:06:00Z", "direction": -1, "main_scope_eligible": True, "anchor_causally_observable": True, "anchor_selected_using_later_completion": False, "anchor_price_override": 101.0, "forward_return_60m": 999.0},
        {"anchor_id": "fvg-a", "anchor_event_id": "event-fvg", "anchor_type": "first_aligned_raw_fvg_creation", "anchor_at": "2025-01-02T10:05:00Z", "direction": -1, "main_scope_eligible": True, "anchor_causally_observable": True, "anchor_selected_using_later_completion": False, "anchor_price_override": 100.5, "forward_return_60m": 999.0},
    ]))
    return d004, snapshots, anchors


def _blocks() -> pd.DataFrame:
    return pd.DataFrame([{
        "block_id": "rb-1", "direction": -1,
        "causal_availability": "2025-01-02T10:05:00Z",
        "first_touch_timestamp": "2025-01-02T10:07:00Z",
        "trading_date": "2025-01-02", "expansion_bar_id": "rb-expansion",
    }])


def test_loads_only_causal_columns_and_normalizes_directions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifacts = _artifacts(tmp_path)
    observed: list[tuple[str, ...]] = []
    real_read = pd.read_parquet

    def tracked_read(path: object, *, columns: list[str], **kwargs: object) -> pd.DataFrame:
        observed.append(tuple(columns))
        return real_read(path, columns=columns, **kwargs)

    monkeypatch.setattr(pd, "read_parquet", tracked_read)
    tables = load_frozen_context(*artifacts)
    assert observed == [
        D004_CAUSAL_COLUMNS,
        D005_E1_CAUSAL_COLUMNS,
        D005_E3_CAUSAL_COLUMNS + ("invalidated_at",),
    ]
    assert all("return" not in name and "outcome" not in name for columns in observed for name in columns)
    assert tables.d004_events.iloc[0]["direction"] == -1
    assert tables.snapshots.iloc[0]["direction"] == -1
    assert tables.anchors.loc[tables.anchors["context_id"].eq("liq-a"), "anchor_price"].iloc[0] == 101.5


def test_snapshots_are_limited_to_the_frozen_nonoptional_1h_5m_variant(tmp_path: Path) -> None:
    artifacts = list(_artifacts(tmp_path))
    snapshots = pd.read_parquet(artifacts[1].parquet_path)
    alternate = snapshots.iloc[[0]].copy()
    alternate.loc[:, "snapshot_id"] = "snapshot-other-mapping"
    alternate.loc[:, "mapping_variant"] = "1h_5m_optional_1m"
    alternate.loc[:, "optional_1m_refinement"] = True
    artifacts[1] = _write_artifact(
        tmp_path,
        "snapshots-mappings.parquet",
        pd.concat([snapshots, alternate], ignore_index=True),
    )
    tables = load_frozen_context(*artifacts)
    assert list(tables.snapshots["context_id"]) == ["snapshot-a"]


def test_checksum_failure_prevents_any_parquet_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifacts = list(_artifacts(tmp_path))
    artifacts[0].manifest_path.write_text('{"files":[{"path":"daily_events.parquet","sha256":"00"}]}', encoding="utf-8")
    monkeypatch.setattr(pd, "read_parquet", lambda *args, **kwargs: pytest.fail("must not read before checksum verification"))
    with pytest.raises(FrozenContextError, match="SHA-256"):
        load_frozen_context(*artifacts)


def test_2026_rows_and_later_completion_selection_are_excluded(tmp_path: Path) -> None:
    artifacts = list(_artifacts(tmp_path))
    d004 = pd.read_parquet(artifacts[0].parquet_path)
    d004.loc[len(d004)] = {**d004.iloc[0].to_dict(), "trading_date": "2026-01-02", "high_reentry_time": "2026-01-02T10:00:00Z"}
    artifacts[0] = _write_artifact(tmp_path, "daily-events-future.parquet", d004)
    snapshots = pd.read_parquet(artifacts[1].parquet_path)
    snapshots.loc[len(snapshots)] = {**snapshots.iloc[0].to_dict(), "snapshot_id": "snapshot-future", "evaluation_at": "2026-01-02T10:00:00Z"}
    artifacts[1] = _write_artifact(tmp_path, "snapshots-future.parquet", snapshots)
    anchors = pd.read_parquet(artifacts[2].parquet_path)
    anchors.loc[len(anchors)] = {**anchors.iloc[0].to_dict(), "anchor_id": "future", "anchor_at": "2026-01-01T00:00:00Z"}
    anchors.loc[len(anchors)] = {**anchors.iloc[0].to_dict(), "anchor_id": "later-selected", "anchor_selected_using_later_completion": True}
    artifacts[2] = _write_artifact(tmp_path, "anchors-rewritten.parquet", anchors)
    tables = load_frozen_context(*artifacts)
    assert len(tables.d004_events) == 1
    assert len(tables.snapshots) == 1
    assert "future" not in set(tables.anchors["context_id"])
    assert "later-selected" not in set(tables.anchors["context_id"])


def test_d004_high_and_low_sweep_reentries_have_frozen_opposite_directions(tmp_path: Path) -> None:
    artifacts = list(_artifacts(tmp_path))
    d004 = pd.read_parquet(artifacts[0].parquet_path)
    d004.loc[len(d004)] = {
        **d004.iloc[0].to_dict(), "high_sweep": False, "high_reentry": False,
        "low_sweep": True, "low_reentry": True,
        "high_reentry_time": None, "low_reentry_time": "2025-01-03T10:00:00Z",
        "trading_date": "2025-01-03",
    }
    artifacts[0] = _write_artifact(tmp_path, "daily-events-directions.parquet", d004)
    tables = load_frozen_context(*artifacts)
    assert list(tables.d004_events["direction"]) == [-1, 1]


def test_recorded_liquidity_invalidation_fails_closed(tmp_path: Path) -> None:
    artifacts = list(_artifacts(tmp_path))
    anchors = pd.read_parquet(artifacts[2].parquet_path)
    anchors["invalidated_at"] = pd.Series(
        pd.NaT, index=anchors.index, dtype="datetime64[ns, UTC]"
    )
    anchors.loc[anchors["anchor_id"].eq("liq-a"), "invalidated_at"] = pd.Timestamp("2025-01-02T10:05:00Z")
    artifacts[2] = _write_artifact(tmp_path, "anchors-invalidated.parquet", anchors)
    joined = join_block_contexts(_blocks(), load_frozen_context(*artifacts)).iloc[0]
    assert not bool(joined["frozen_liquidity_sweep"])
    assert "liquidity:missing" in joined["unavailable_reasons"]


def test_causal_join_uses_registered_times_and_fixed_interactions(tmp_path: Path) -> None:
    tables = load_frozen_context(*_artifacts(tmp_path))
    joined = join_block_contexts(_blocks(), tables).iloc[0]
    assert bool(joined["context_available"])
    assert bool(joined["aligned_d005_context"])
    assert bool(joined["after_d004_manipulation"])
    assert bool(joined["frozen_liquidity_sweep"])
    assert bool(joined["displacement_confirmation"])
    assert bool(joined["refinement_confirmation"])
    assert not bool(joined["against_d005_context_negative_control"])
    assert "fvg-a" in " ".join(joined["redundancy_context_keys"])
    assert interaction_registry() == (
        "rb_alone", "aligned_d005_context", "after_d004_manipulation", "frozen_liquidity_sweep",
        "displacement_confirmation", "refinement_confirmation", "against_d005_context_negative_control",
    )


def test_strict_d004_timing_and_same_timestamp_opposites_are_unavailable(tmp_path: Path) -> None:
    tables = load_frozen_context(*_artifacts(tmp_path))
    d004 = tables.d004_events.copy()
    d004.loc[0, "available_at"] = pd.Timestamp("2025-01-02T10:05:00Z")
    strict_tables = FrozenContextTables(d004_events=d004, snapshots=tables.snapshots, anchors=tables.anchors)
    strict_joined = join_block_contexts(_blocks(), strict_tables).iloc[0]
    assert not bool(strict_joined["after_d004_manipulation"])
    assert "d004:missing" in strict_joined["unavailable_reasons"]

    d004.loc[0, "available_at"] = pd.Timestamp("2025-01-02T10:04:00Z")
    opposite = d004.iloc[[0]].copy()
    opposite.loc[:, "context_id"] = "d004:2025-01-02:low"
    opposite.loc[:, "direction"] = 1
    tables = FrozenContextTables(d004_events=pd.concat([d004, opposite], ignore_index=True), snapshots=tables.snapshots, anchors=tables.anchors)
    joined = join_block_contexts(_blocks(), tables).iloc[0]
    assert not bool(joined["after_d004_manipulation"])
    assert "d004:conflicting_same_trading_date" in joined["unavailable_reasons"]

    ambiguous = tables.snapshots.copy()
    extra = ambiguous.iloc[[0]].copy()
    extra.loc[:, "context_id"] = "snapshot-opposite"
    extra.loc[:, "direction"] = 1
    tables = FrozenContextTables(d004_events=tables.d004_events, snapshots=pd.concat([ambiguous, extra], ignore_index=True), anchors=tables.anchors)
    joined = join_block_contexts(_blocks(), tables).iloc[0]
    assert not bool(joined["aligned_d005_context"])
    assert "d005_context:ambiguous_opposite_direction" in joined["unavailable_reasons"]
